#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["snowflake-connector-python"]
# ///
"""Simulate a proposed Snowflake view change read-only and diff it against
the deployed output, with float tolerance and invariant checks.

The live deployment is the only baseline: every run fetches the current DDL
with GET_DDL and records its SHA-256. Nothing here ever writes to the
warehouse — the deploy itself is a human running the emitted worksheet under
their own role, behind a hash guard that fails loud if the live view moved
after the simulation.

Exit codes: 0 clean (float noise only) · 1 findings · 2 refused to run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RunQuery = Callable[[str], list[tuple]]

WRITE_VERBS = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP", "ALTER",
    "TRUNCATE", "GRANT", "REVOKE", "COPY", "PUT", "CALL", "UNDROP",
)

DEFAULT_REL_TOL = 1e-9
DEFAULT_ABS_TOL = 1e-12
DEFAULT_ENV_PREFIX = "SNOWFLAKE_"
DEFAULT_OUT_DIR = "sim_diff_out"


class SpecError(Exception):
    """The run spec is invalid; the harness refuses to run."""


# --------------------------------------------------------------------------- SQL text


def mask_noncode(sql: str, mask_quoted_identifiers: bool = False) -> str:
    """Blank comments and string literals (and optionally "quoted" identifiers)
    with spaces, preserving length and newlines so offsets stay valid."""
    out = list(sql)
    i, n = 0, len(sql)

    def blank(start: int, end: int) -> None:
        for j in range(start, end):
            if out[j] != "\n":
                out[j] = " "

    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end == -1 else end
            blank(i, end)
            i = end
        elif ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = n if end == -1 else end + 2
            blank(i, end)
            i = end
        elif ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and sql.startswith("''", j):
                    j += 2
                elif sql[j] == "'":
                    j += 1
                    break
                else:
                    j += 1
            blank(i, j)
            i = j
        elif ch == '"':
            j = sql.find('"', i + 1)
            j = n if j == -1 else j + 1
            if mask_quoted_identifiers:
                blank(i, j)
            i = j
        else:
            i += 1
    return "".join(out)


def find_write_verbs(sql: str) -> list[str]:
    """Write verbs present in the executable text, ignoring comments,
    strings, and quoted identifiers. Any hit means: refuse to run."""
    masked = mask_noncode(sql, mask_quoted_identifiers=True)
    found = []
    for verb in WRITE_VERBS:
        if re.search(rf"\b{verb}\b", masked, re.IGNORECASE):
            found.append(verb)
    return found


def extract_view_body(ddl: str) -> str:
    """Return the SELECT body of a CREATE [OR REPLACE] VIEW statement,
    dropping the header, optional column list, and trailing semicolon."""
    masked = mask_noncode(ddl)
    m = re.search(r"\bview\b", masked, re.IGNORECASE)
    if not m:
        raise ValueError("not a CREATE VIEW statement")
    i, n = m.end(), len(masked)
    while i < n and masked[i].isspace():
        i += 1
    while i < n and (masked[i].isalnum() or masked[i] in '_$."'):
        i += 1
    while i < n and masked[i].isspace():
        i += 1
    if i < n and masked[i] == "(":
        depth = 0
        while i < n:
            if masked[i] == "(":
                depth += 1
            elif masked[i] == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    m2 = re.compile(r"\bas\b", re.IGNORECASE).search(masked, i)
    if not m2:
        raise ValueError("no AS clause found in view DDL")
    return ddl[m2.end():].rstrip().rstrip(";").strip("\n")


def _ref_pattern(fqn: str) -> re.Pattern:
    parts = [re.escape(p) for p in fqn.split(".")]
    alts = [f'(?:"{p}"|{p})' for p in parts]
    return re.compile(
        r'(?<![\w$".])' + r"\.".join(alts) + r'(?![\w$".])', re.IGNORECASE
    )


def rewrite_refs(
    sql: str,
    mapping: dict[str, str],
    _expanding: frozenset[str] = frozenset(),
) -> str:
    """Replace fully-qualified table/view references with replacement text.

    A CTE only shadows unqualified names, so simulation works by textual
    substitution of the qualified reference itself. Matching skips comments
    and string literals; unquoted segments match case-insensitively, quoted
    segments must match exactly. Replacement bodies are themselves rewritten
    recursively (so chains compose), except for the reference they replace —
    a patch that reads its own table keeps reading the real table.
    """
    active = {f: b for f, b in mapping.items() if f not in _expanding}
    if not active:
        return sql
    masked = mask_noncode(sql)
    hits: list[tuple[int, int, str]] = []
    for fqn, _body in active.items():
        for m in _ref_pattern(fqn).finditer(masked):
            quoted_ok = True
            for canon, got in zip(fqn.split("."), m.group(0).split(".")):
                if got.startswith('"') and got.strip('"') != canon:
                    quoted_ok = False
            if quoted_ok:
                hits.append((m.start(), m.end(), fqn))
    hits.sort()
    out, pos, last_end = [], 0, -1
    for start, end, fqn in hits:
        if start < last_end:
            continue
        out.append(sql[pos:start])
        out.append(rewrite_refs(active[fqn], mapping, _expanding | {fqn}))
        pos = end
        last_end = end
    out.append(sql[pos:])
    return "".join(out)


# --------------------------------------------------------------------------- diffing


@dataclass
class Worst:
    key: tuple
    base: Any
    prop: Any
    rel: float


@dataclass
class DiffResult:
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    noise_count: int = 0
    worst: Worst | None = None


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _compare(a: Any, b: Any, rel_tol: float, abs_tol: float) -> str:
    """'exact', 'noise' (within tolerance), or 'changed'."""
    if a is None and b is None:
        return "exact"
    if a is None or b is None:
        return "changed"
    if _is_number(a) and _is_number(b):
        if a == b:
            return "exact"
        diff = abs(a - b)
        if diff <= max(rel_tol * max(abs(a), abs(b)), abs_tol):
            return "noise"
        return "changed"
    return "exact" if a == b else "changed"


def _rel(a: Any, b: Any) -> float:
    if _is_number(a) and _is_number(b):
        denom = max(abs(a), abs(b))
        return abs(a - b) / denom if denom else 0.0
    return math.inf


def classify_diff(
    base: list[tuple],
    prop: list[tuple],
    key_len: int,
    rel_tol: float = DEFAULT_REL_TOL,
    abs_tol: float = DEFAULT_ABS_TOL,
) -> DiffResult:
    """Bucket a keyed comparison into added / removed / changed / noise.

    Duplicate keys compare as multisets: rows pair up exact-first, then
    within tolerance; leftovers pair as changed; the surplus is added or
    removed. A raw MINUS cannot make these distinctions and drowns in
    last-bit float drift — this classification is the whole point.
    """
    result = DiffResult()

    def group(rows: list[tuple]) -> dict[tuple, list[tuple]]:
        g: dict[tuple, list[tuple]] = {}
        for r in rows:
            g.setdefault(tuple(r[:key_len]), []).append(tuple(r[key_len:]))
        return g

    base_g, prop_g = group(base), group(prop)
    for key in sorted(set(base_g) | set(prop_g), key=repr):
        b_vals = list(base_g.get(key, []))
        p_vals = list(prop_g.get(key, []))
        for verdict_wanted in ("exact", "noise"):
            for bv in list(b_vals):
                for pv in list(p_vals):
                    verdicts = [
                        _compare(x, y, rel_tol, abs_tol) for x, y in zip(bv, pv)
                    ]
                    if "changed" in verdicts:
                        continue
                    worst_v = "noise" if "noise" in verdicts else "exact"
                    if worst_v == verdict_wanted:
                        if worst_v == "noise":
                            result.noise_count += 1
                        b_vals.remove(bv)
                        p_vals.remove(pv)
                        break
                else:
                    continue
        for bv, pv in zip(b_vals, p_vals):
            result.changed.append(key + bv + pv)
            for x, y in zip(bv, pv):
                if _compare(x, y, rel_tol, abs_tol) == "changed":
                    rel = _rel(x, y)
                    if result.worst is None or rel > result.worst.rel:
                        result.worst = Worst(key=key, base=x, prop=y, rel=rel)
        for bv in b_vals[len(p_vals):]:
            result.removed.append(key + bv)
        for pv in p_vals[len(b_vals):]:
            result.added.append(key + pv)
    return result


def new_duplicate_keys(
    base: list[tuple], prop: list[tuple], key_len: int
) -> list[tuple]:
    """Keys duplicated in the proposal that were not already duplicated in
    the baseline. Tolerated legacy duplicates stay tolerated; new ones are
    a grain regression."""

    def dup_keys(rows: list[tuple]) -> set[tuple]:
        seen: dict[tuple, int] = {}
        for r in rows:
            k = tuple(r[:key_len])
            seen[k] = seen.get(k, 0) + 1
        return {k for k, c in seen.items() if c > 1}

    return sorted(dup_keys(prop) - dup_keys(base), key=repr)


# --------------------------------------------------------------------------- spec


@dataclass
class ViewSpec:
    fqn: str
    key: list[str]
    value_columns: list[str]
    proposed_sql: Path | None
    where: str | None
    checks: list[dict]


@dataclass
class Spec:
    base_dir: Path
    views: list[ViewSpec]
    shadow_tables: dict[str, Path]
    rel_tol: float
    abs_tol: float
    env_prefix: str
    out_dir: Path


def load_spec(path: str | Path) -> Spec:
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"cannot read spec {path}: {exc}") from exc
    base = path.resolve().parent

    def resolve(name: str, rel: str) -> Path:
        p = base / rel
        if not p.is_file():
            raise SpecError(f"{name}: file not found: {rel}")
        return p

    views_raw = raw.get("views")
    if not isinstance(views_raw, list) or not views_raw:
        raise SpecError("spec needs a non-empty 'views' list")
    shadow = {
        fqn: resolve(f"shadow_tables[{fqn}]", rel)
        for fqn, rel in (raw.get("shadow_tables") or {}).items()
    }
    views = []
    for i, v in enumerate(views_raw):
        fqn = v.get("fqn")
        if not fqn:
            raise SpecError(f"views[{i}]: 'fqn' is required")
        key = v.get("key")
        if not key:
            raise SpecError(f"views[{i}] ({fqn}): 'key' columns are required")
        value_columns = v.get("value_columns")
        if not value_columns:
            raise SpecError(f"views[{i}] ({fqn}): 'value_columns' is required")
        proposed = v.get("proposed_sql")
        views.append(
            ViewSpec(
                fqn=fqn,
                key=list(key),
                value_columns=list(value_columns),
                proposed_sql=resolve(f"views[{i}].proposed_sql", proposed)
                if proposed
                else None,
                where=v.get("where"),
                checks=list(v.get("checks") or []),
            )
        )
    if not shadow and not any(v.proposed_sql for v in views):
        raise SpecError(
            "nothing to simulate: no view has 'proposed_sql' and there are "
            "no 'shadow_tables'"
        )
    return Spec(
        base_dir=base,
        views=views,
        shadow_tables=shadow,
        rel_tol=float(raw.get("rel_tol", DEFAULT_REL_TOL)),
        abs_tol=float(raw.get("abs_tol", DEFAULT_ABS_TOL)),
        env_prefix=raw.get("env_prefix", DEFAULT_ENV_PREFIX),
        out_dir=base / raw.get("out_dir", DEFAULT_OUT_DIR),
    )


# --------------------------------------------------------------------------- warehouse


def connect_runner(env_prefix: str) -> RunQuery:
    """Build a query runner from environment variables. Imported lazily so
    the test suite (pytest-only) never needs the connector installed."""
    need = ["ACCOUNT", "USER", "WAREHOUSE"]
    missing = [v for v in need if not os.environ.get(env_prefix + v)]
    key_text = os.environ.get(env_prefix + "PRIVATE_KEY")
    password = os.environ.get(env_prefix + "PASSWORD")
    if not key_text and not password:
        missing.append("PRIVATE_KEY (or PASSWORD)")
    if missing:
        raise SpecError(
            "missing environment: " + ", ".join(env_prefix + v for v in missing)
        )
    import snowflake.connector  # noqa: PLC0415

    kwargs: dict[str, Any] = {
        "account": os.environ[env_prefix + "ACCOUNT"],
        "user": os.environ[env_prefix + "USER"],
        "warehouse": os.environ[env_prefix + "WAREHOUSE"],
    }
    for opt in ("DATABASE", "SCHEMA", "ROLE"):
        if os.environ.get(env_prefix + opt):
            kwargs[opt.lower()] = os.environ[env_prefix + opt]
    if key_text:
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

        pem = key_text.replace("\\n", "\n").strip().strip('"').encode()
        passphrase = os.environ.get(env_prefix + "PRIVATE_KEY_PASSPHRASE")
        key = serialization.load_pem_private_key(
            pem, passphrase.encode() if passphrase else None
        )
        kwargs["private_key"] = key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    else:
        kwargs["password"] = password
    conn = snowflake.connector.connect(**kwargs)

    def run(sql: str) -> list[tuple]:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall()
        finally:
            cur.close()

    return run


# --------------------------------------------------------------------------- run


def _body_of(text: str) -> str:
    try:
        return extract_view_body(text)
    except ValueError:
        return text.rstrip().rstrip(";")


def _simulate_one(
    view: ViewSpec, spec: Spec, mapping: dict[str, str], run_query: RunQuery
) -> tuple[dict, int]:
    cols = ", ".join(view.key + view.value_columns)
    where = f" WHERE {view.where}" if view.where else ""
    if view.proposed_sql is not None:
        proposed_text = view.proposed_sql.read_text()
        sim_body = rewrite_refs(
            _body_of(proposed_text), mapping, frozenset({view.fqn})
        )
    else:
        proposed_text = None
        ddl_now = run_query(f"SELECT GET_DDL('VIEW', '{view.fqn}')")[0][0]
        sim_body = rewrite_refs(_body_of(ddl_now), mapping)
    verbs = find_write_verbs(sim_body)
    if verbs:
        raise SpecError(
            f"{view.fqn}: refusing to run — write verbs in simulated body: "
            + ", ".join(verbs)
        )
    ddl = run_query(f"SELECT GET_DDL('VIEW', '{view.fqn}')")[0][0]
    ddl_sha = hashlib.sha256(ddl.encode()).hexdigest()
    baseline = run_query(
        f"/*sim_diff:baseline*/ SELECT {cols} FROM {view.fqn}{where}"
    )
    simulated = run_query(
        f"/*sim_diff:simulated*/ SELECT {cols} FROM (\n{sim_body}\n) __sim{where}"
    )
    diff = classify_diff(
        baseline, simulated, len(view.key), spec.rel_tol, spec.abs_tol
    )
    new_dups = new_duplicate_keys(baseline, simulated, len(view.key))
    checks_out = []
    for check in view.checks:
        check_sql = rewrite_refs(
            check["sql"], {**mapping, view.fqn: f"(\n{sim_body}\n)"}
        )
        verbs = find_write_verbs(check_sql)
        if verbs:
            raise SpecError(
                f"{view.fqn} check '{check.get('label')}': write verbs: "
                + ", ".join(verbs)
            )
        rows = run_query(f"/*sim_diff:check*/ {check_sql}")
        checks_out.append(
            {"label": check.get("label", "check"), "rows": len(rows),
             "passed": len(rows) == 0}
        )
    findings = (
        bool(diff.added or diff.removed or diff.changed or new_dups)
        or any(not c["passed"] for c in checks_out)
    )
    entry = {
        "fqn": view.fqn,
        "ddl_sha256": ddl_sha,
        "baseline_rows": len(baseline),
        "simulated_rows": len(simulated),
        "buckets": {
            "added": len(diff.added),
            "removed": len(diff.removed),
            "changed": len(diff.changed),
            "noise": diff.noise_count,
        },
        "changed_sample": [list(r) for r in diff.changed[:20]],
        "added_sample": [list(r) for r in diff.added[:20]],
        "removed_sample": [list(r) for r in diff.removed[:20]],
        "new_duplicate_keys": [list(k) for k in new_dups[:50]],
        "checks": checks_out,
        "worst": None
        if diff.worst is None
        else {
            "key": list(diff.worst.key),
            "base": diff.worst.base,
            "proposed": diff.worst.prop,
            "rel": diff.worst.rel,
        },
        "verdict": "findings" if findings else "clean",
        "_proposed_text": proposed_text,
    }
    return entry, (1 if findings else 0)


def _write_outputs(spec: Spec, entries: list[dict]) -> None:
    spec.out_dir.mkdir(parents=True, exist_ok=True)
    for i, entry in enumerate(entries, start=1):
        proposed_text = entry.pop("_proposed_text")
        if proposed_text is None:
            continue
        worksheet = (
            f"-- sim_diff worksheet for {entry['fqn']}\n"
            f"-- Baseline guard: run this SELECT first and proceed ONLY if it\n"
            f"-- returns the expected hash. A mismatch means the live view\n"
            f"-- changed after the simulation — re-run sim_diff, do not deploy.\n"
            f"SELECT SHA2(GET_DDL('VIEW', '{entry['fqn']}'), 256) AS live_ddl_sha256;\n"
            f"-- expected: {entry['ddl_sha256']}\n\n"
            f"{proposed_text}"
        )
        (spec.out_dir / f"worksheet_{i}.sql").write_text(worksheet)
    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rel_tol": spec.rel_tol,
        "abs_tol": spec.abs_tol,
        "views": entries,
    }
    (spec.out_dir / "evidence.json").write_text(
        json.dumps(evidence, indent=2, default=str)
    )


def main(argv: list[str] | None = None, run_query: RunQuery | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", help="JSON run spec (see the skill's references/spec.md)")
    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.spec)
        if run_query is None:
            run_query = connect_runner(spec.env_prefix)
        mapping: dict[str, str] = {
            fqn: f"(\n{_body_of(p.read_text())}\n)"
            for fqn, p in spec.shadow_tables.items()
        }
        for view in spec.views:
            if view.proposed_sql is not None:
                mapping[view.fqn] = f"(\n{_body_of(view.proposed_sql.read_text())}\n)"
        exit_code = 0
        entries = []
        for view in spec.views:
            entry, code = _simulate_one(view, spec, mapping, run_query)
            entries.append(entry)
            exit_code = max(exit_code, code)
    except SpecError as exc:
        print(f"sim_diff: refused: {exc}", file=sys.stderr)
        return 2
    _write_outputs(spec, entries)
    for entry in entries:
        b = entry["buckets"]
        print(
            f"{entry['fqn']}: {entry['verdict']} — "
            f"added {b['added']}, removed {b['removed']}, "
            f"changed {b['changed']}, noise {b['noise']}, "
            f"new dup keys {len(entry['new_duplicate_keys'])}, "
            f"checks {sum(c['passed'] for c in entry['checks'])}"
            f"/{len(entry['checks'])} passed"
        )
    print(f"evidence: {spec.out_dir / 'evidence.json'}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
