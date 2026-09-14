#!/usr/bin/env python3
"""Deterministic collector for /wrap-up — a VERDICT, not raw data to re-derive.

`/wrap-up` steps 2-4 (validate each note, index sync, orphans) and the "which
handoff sections did this session touch" evidence for step 9 are mechanical:
they read frontmatter, wikilinks, index files, and a git diff, and compare
against fixed rules. This script runs those checks once, deterministically,
and returns a compact verdict (CLEAN / FINDINGS / INCOMPLETE) so the model
stops re-deriving them by hand every run.

Read-only. Never writes to the vault. graphmark, frontmatter_engine,
vault_audit, and vault_scope_resolved-derived names are all imported lazily
(inside the functions that need them, after ``_pin_vault_root`` has anchored
scope resolution to the vault root in play) so:

- a vault without graphmark still gets the frontmatter/wikilink/index/scope
  checks; only the graph-backed checks (unresolved_links, orphans, gate)
  degrade to ``not_run``.
- ``--vault-root`` (not the process cwd) is authoritative for which owner
  scope config (``.vault/config/vault_scope.py``) applies, including in a
  single long-lived process that audits more than one vault root (this
  module's own test suite included).
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from vault_utils import find_vault_root, read_vault_context  # noqa: E402

HEADING_RE = re.compile(r"^## (.+?)\s*$")
FENCE_RE = re.compile(r"^(```|~~~)")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
PREAMBLE = "(preamble)"

VERDICT_EXIT_CODES = {"CLEAN": 0, "FINDINGS": 1, "INCOMPLETE": 2}


# ---------------------------------------------------------------------------
# vault-root pinning (item 4)
# ---------------------------------------------------------------------------

_PINNED_MODULE_NAMES = (
    "vault_scope", "vault_scope_resolved", "vault_scope_defaults",
    "frontmatter_engine", "vault_audit", "graph_cli",
)


def _pin_vault_root(vault_root: Path) -> tuple[str, Callable[[], None]]:
    """Anchor vault_scope_resolved's owner-config resolution to *vault_root*.

    ``vault_scope_resolved._find_vault_root()`` walks up from
    ``CLAUDE_PROJECT_DIR`` (falling back to cwd) — so a caller running from
    outside the vault, or a ``--vault-root`` the cwd doesn't agree with,
    would otherwise silently get the shipped defaults, which have no
    owner-added directories (e.g. ``school``). Setting ``CLAUDE_PROJECT_DIR``
    here, before this process resolves any vault_scope_resolved-derived name,
    makes ``--vault-root`` authoritative.

    ``vault_scope_resolved`` caches its owner-config resolution for the life
    of the process, and ``frontmatter_engine``/``vault_audit``/``graph_cli``
    each bind their own ``from vault_scope_resolved import ...`` names once
    at their own first import — so a later ``collect()`` call for a
    DIFFERENT vault_root would otherwise keep reading the first vault's
    config. There is no public reset API, so this evicts the cached modules
    directly.

    This is process-global state, so the eviction (and the env var) must not
    outlive one ``collect()`` call: a caller (this test suite included) that
    imported one of these modules for its OWN purposes before ``collect()``
    ran, or that reads ``CLAUDE_PROJECT_DIR`` itself, must see it unchanged
    afterward. Returns ``(scope_config_source, restore)`` — the caller MUST
    invoke ``restore()`` in a ``finally``, on both success and exception, to
    put ``os.environ`` and ``sys.modules`` back exactly as found. Production
    CLI runs are unaffected either way: each is its own fresh subprocess.
    """
    had_env = "CLAUDE_PROJECT_DIR" in os.environ
    prior_env = os.environ.get("CLAUDE_PROJECT_DIR")
    prior_modules = {name: sys.modules.get(name) for name in _PINNED_MODULE_NAMES}

    os.environ["CLAUDE_PROJECT_DIR"] = str(vault_root)
    for name in _PINNED_MODULE_NAMES:
        sys.modules.pop(name, None)

    import vault_scope_resolved  # noqa: PLC0415

    owner = vault_scope_resolved._owner_scope()  # noqa: SLF001
    if owner is not None and getattr(owner, "__file__", None):
        source = owner.__file__
    else:
        source = "shipped defaults (vault_scope_defaults.py)"

    def _restore() -> None:
        if had_env:
            os.environ["CLAUDE_PROJECT_DIR"] = prior_env  # type: ignore[assignment]
        else:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        for name, mod in prior_modules.items():
            if mod is not None:
                sys.modules[name] = mod
            else:
                sys.modules.pop(name, None)

    return source, _restore


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _git(vault_root: Path, args: list[str]) -> str | None:
    """Run a git command in *vault_root*; None on any failure (never raises)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=vault_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_nul_list(raw: str) -> set[str]:
    return {t for t in raw.split("\0") if t}


def _parse_porcelain_z(raw: str) -> set[str]:
    """Parse ``git status --porcelain=v1 -z`` output.

    -z uses NUL separators (no C-quoting of non-ASCII names) and, for the
    default porcelain-v1 shape, splits a rename/copy into two consecutive
    NUL-terminated records: the new path (with its XY status prefix) then
    the bare original path. Both are added to the result.
    """
    if not raw:
        return set()
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens = tokens[:-1]
    paths: set[str] = set()
    i = 0
    while i < len(tokens):
        record = tokens[i]
        if len(record) >= 3:
            status = record[:2]
            path = record[3:]
            paths.add(path)
            if status[0] in "RC" or status[1] in "RC":
                i += 1
                if i < len(tokens):
                    paths.add(tokens[i])
        i += 1
    return paths


def _git_evidence_paths(vault_root: Path, base: str) -> tuple[set[str], bool, list[str]]:
    """Union of dirty (status) and base-diff paths. (paths, ok, warnings).

    ``--untracked-files=all`` expands a wholly-new directory to its
    individual files instead of collapsing it to one directory line; ``-z``
    avoids C-quoting non-ASCII names and disables the ``->`` rename arrow in
    favor of two separate records (handled in ``_parse_porcelain_z``).

    ``ok`` is False only when BOTH git invocations fail outright (git
    missing, or this isn't a git repo at all) — a partial failure (e.g. a
    bad --base ref) still yields the evidence the other command produced,
    with a warning.
    """
    status_out = _git(vault_root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    diff_out = _git(vault_root, ["diff", "--name-only", "-z", base])
    warnings: list[str] = []
    if status_out is None and diff_out is None:
        return set(), False, ["git status and git diff both failed"]

    paths: set[str] = set()
    if status_out is not None:
        paths |= _parse_porcelain_z(status_out)
    else:
        warnings.append("git status --porcelain failed")
    if diff_out is not None:
        paths |= _parse_nul_list(diff_out)
    else:
        warnings.append(f"git diff --name-only {base} failed (bad --base ref?)")
    return paths, True, warnings


def _git_deleted_paths(vault_root: Path, base: str) -> set[str]:
    """Paths git confirms as deleted: committed-since-base, or deleted-but-staged/unstaged."""
    deleted: set[str] = set()
    diff_out = _git(vault_root, ["diff", "--name-only", "--diff-filter=D", "-z", base])
    if diff_out:
        deleted |= _parse_nul_list(diff_out)
    ls_out = _git(vault_root, ["ls-files", "--deleted", "-z"])
    if ls_out:
        deleted |= _parse_nul_list(ls_out)
    return deleted


# ---------------------------------------------------------------------------
# scope (items 2, 5)
# ---------------------------------------------------------------------------

@dataclass
class ScopeResult:
    claimed: list[str] = field(default_factory=list)
    source: str = "explicit"
    warnings: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    unclaimed_dirty: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    git_ok: bool = True


def _case_correct(rel_str: str, vault_root: Path) -> str:
    """Correct each path segment's case to match the real on-disk entry.

    macOS/APFS is case-insensitive but case-preserving: ``Path.exists()``
    finds a file regardless of the case given, but the literal string stays
    as typed — and graphmark's node keys are the exact on-disk names. Walk
    the path one directory at a time, matching each component against its
    parent's real entries case-insensitively.
    """
    parts = Path(rel_str).parts
    current = vault_root
    corrected: list[str] = []
    for part in parts:
        try:
            entries = {e.name.lower(): e.name for e in current.iterdir()}
        except OSError:
            corrected.append(part)
            current = current / part
            continue
        real_name = entries.get(part.lower(), part)
        corrected.append(real_name)
        current = current / real_name
    return Path(*corrected).as_posix()


def _resolve_explicit_entry(
    raw: str, vault_root: Path, cwd: Path, deleted_paths: set[str]
) -> tuple[str, str, str | None]:
    """Resolve one --files entry. Returns (kind, value, reason).

    kind == "claim": value is the case-corrected vault-relative posix path.
    kind == "skip":  value is the vault-relative posix path (a confirmed git deletion).
    kind == "error": value is the raw entry as given; reason explains why.

    Resolution order: absolute paths are used as-is; otherwise cwd-relative
    is tried first, then vault-relative. ``.resolve()`` then normalizes
    ``..`` and equivalent-but-different-string roots (e.g. ``/tmp`` vs
    ``/private/tmp`` on macOS).
    """
    p = Path(raw)
    if p.is_absolute():
        candidate = p
    else:
        cwd_candidate = cwd / p
        vault_candidate = vault_root / p
        candidate = cwd_candidate if cwd_candidate.exists() else vault_candidate

    try:
        resolved = candidate.resolve()
    except OSError as exc:
        return "error", raw, f"could not resolve: {exc}"

    try:
        vault_root_resolved = vault_root.resolve()
    except OSError:
        vault_root_resolved = vault_root

    try:
        rel = resolved.relative_to(vault_root_resolved)
    except ValueError:
        return "error", raw, f"resolves outside the vault: {resolved}"

    rel_str = rel.as_posix()

    if resolved.exists():
        return "claim", _case_correct(rel_str, vault_root_resolved), None

    if rel_str in deleted_paths:
        return "skip", rel_str, "git deletion"

    return "error", raw, f"does not exist and is not a known git deletion: {rel_str}"


def _classify_note(rel: str, vault_root: Path) -> tuple[str, str | None]:
    """kind in {"claim", "skip"}; reason set when skipped."""
    from vault_scope_resolved import (  # noqa: PLC0415
        is_governed_markdown_note,
        is_graph_markdown_note,
        is_operating_file,
    )

    full = vault_root / rel
    if not full.exists():
        return "skip", "does not exist (deleted?)"
    if full.suffix.lower() != ".md":
        return "skip", "not a markdown note"
    if is_operating_file(full):
        return "skip", "operating file"
    if not (is_governed_markdown_note(full, vault_root) or is_graph_markdown_note(full, vault_root)):
        return "skip", "not a governed/graph markdown note"
    return "claim", None


def _compute_scope(vault_root: Path, files: list[str] | None, base: str) -> ScopeResult:
    from vault_scope_resolved import is_graph_markdown_note  # noqa: PLC0415

    git_paths, git_ok, git_warnings = _git_evidence_paths(vault_root, base)
    deleted_paths = _git_deleted_paths(vault_root, base) if git_ok else set()

    warnings: list[str] = []
    errors: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    pre_claim: list[str] = []

    if files is not None:
        source = "explicit"
        if len(files) == 0:
            errors.append({"file": "", "reason": "--files was given but empty"})
        cwd = Path.cwd()
        for raw in files:
            kind, value, reason = _resolve_explicit_entry(raw, vault_root, cwd, deleted_paths)
            if kind == "error":
                errors.append({"file": raw, "reason": reason or "unresolvable"})
            elif kind == "skip":
                skipped.append({"file": value, "reason": reason or "skipped"})
            else:
                pre_claim.append(value)
    else:
        source = "git"
        if git_ok:
            warnings.append(
                "scope_source is git: no --files was given, so scope is git status/diff "
                "evidence, which may include edits unrelated to this session"
            )
            warnings.extend(git_warnings)
            pre_claim.extend(sorted(git_paths))
        else:
            warnings.append("git evidence unavailable; scope could not be determined")
            warnings.extend(git_warnings)
            errors.append({"file": "", "reason": "git evidence unavailable; scope could not be determined"})

    final_claimed: list[str] = []
    seen: set[str] = set()
    for rel in pre_claim:
        if rel in seen:
            continue
        seen.add(rel)
        kind, reason = _classify_note(rel, vault_root)
        if kind == "claim":
            final_claimed.append(rel)
        else:
            skipped.append({"file": rel, "reason": reason or "skipped"})

    # LOW-1: an explicit --files that resolved fine (no per-entry error) but
    # left nothing claimed after note-type filtering — a directory, or only
    # non-note files like the handoff — must not read as "nothing to
    # validate, so CLEAN": nothing was actually audited.
    if files is not None and len(files) > 0 and not final_claimed:
        errors.append({"file": "", "reason": "no claimed notes after filtering"})

    unclaimed_dirty: list[str] = []
    if git_ok:
        claimed_set = set(final_claimed)
        for rel in sorted(git_paths):
            if rel in claimed_set:
                continue
            full = vault_root / rel
            if not full.exists():
                continue
            if is_graph_markdown_note(full, vault_root):
                unclaimed_dirty.append(rel)

    return ScopeResult(
        claimed=sorted(final_claimed),
        source=source,
        warnings=warnings,
        skipped=skipped,
        unclaimed_dirty=unclaimed_dirty,
        errors=errors,
        git_ok=git_ok,
    )


# ---------------------------------------------------------------------------
# checks 1, 2, 5 — frontmatter, no_wikilinks, index_membership (scope-bound)
# ---------------------------------------------------------------------------

def _scoped_checks(vault_root: Path, claimed: list[str]) -> dict[str, list[dict[str, Any]]]:
    from frontmatter_engine import validate as fm_validate  # noqa: PLC0415
    from vault_audit import (  # noqa: PLC0415
        PERSONAL_INDEX_PREFIXES,
        WORK_INDEX_PREFIXES,
        _body,
        _index_links,
        _indexed,
        _is_transient,
        _links,
    )
    from vault_scope_resolved import is_governed_markdown_note, is_graph_markdown_note  # noqa: PLC0415

    frontmatter: list[dict[str, Any]] = []
    no_wikilinks: list[dict[str, Any]] = []
    index_membership: list[dict[str, Any]] = []

    work_index_links = _index_links(vault_root / "work" / "Index.md")
    personal_index_links = _index_links(vault_root / "personal" / "Index.md")

    for rel in claimed:
        full = vault_root / rel
        governed = is_governed_markdown_note(full, vault_root)
        graph_note = is_graph_markdown_note(full, vault_root)

        if governed:
            for err in fm_validate(full, vault_root):
                frontmatter.append({
                    "check": "frontmatter",
                    "file": rel,
                    "detail": f"{err.field}: {err.message}",
                })

        if graph_note:
            body = _body(full).strip()
            note_links = [(is_embed, target) for is_embed, target in _links(full) if not is_embed]
            if len(body) > 300 and not note_links:
                no_wikilinks.append({
                    "check": "no_wikilinks",
                    "file": rel,
                    "detail": f"{len(body)} chars, no wikilinks",
                })

        if governed and not _is_transient(rel):
            if rel.startswith(WORK_INDEX_PREFIXES) and not _indexed(full, vault_root, work_index_links):
                index_membership.append({
                    "check": "index_membership",
                    "file": rel,
                    "detail": "missing from work/Index.md",
                })
            if rel.startswith(PERSONAL_INDEX_PREFIXES) and not _indexed(full, vault_root, personal_index_links):
                index_membership.append({
                    "check": "index_membership",
                    "file": rel,
                    "detail": "missing from personal/Index.md",
                })

    return {
        "frontmatter": frontmatter,
        "no_wikilinks": no_wikilinks,
        "index_membership": index_membership,
    }


# ---------------------------------------------------------------------------
# gate policy parsing (item 1) — static, never imports/execs the gate file
# ---------------------------------------------------------------------------

def _find_policy_assign_nodes(tree: ast.Module) -> list[ast.stmt]:
    """Every ``Assign``/``AnnAssign`` anywhere in the module that targets the bare name ``POLICY``."""
    found: list[ast.stmt] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "POLICY" for t in node.targets):
                found.append(node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "POLICY":
                found.append(node)
    return found


def _find_check_kwarg_values(tree: ast.Module) -> list[ast.expr]:
    """Every ``check=...`` keyword argument value on any Call node anywhere in the module."""
    values: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "check":
                    values.append(kw.value)
    return values


def _parse_gate_policy(vault_root: Path) -> tuple[dict[str, int] | None, str | None]:
    """Statically parse ``<vault_root>/ci/vault_health.py``'s POLICY and confirm it's applied.

    Never imports or execs the gate file: it requires graphmark>=0.7 (this
    process may only have 0.6) and running it as a module executes real vault
    code (``VaultConfig(...)``, ``graphmark.build(...)``) as a side effect of
    import. Parses with ``ast`` instead.

    Failing closed: a static read can be fooled by a file that LOOKS like it
    declares one policy but actually enforces another at runtime (a second
    reassignment of the name, a policy defined inside an ``if`` block instead
    of at module level, or a ``check=`` argument that doesn't reference
    ``POLICY`` at all). So this requires, together:

    - exactly one assignment to the bare name ``POLICY`` anywhere in the
      module (``ast.walk``, not just top-level statements — a second
      assignment anywhere, even one Python itself would never reach, means
      the file's real behavior can't be read off this one node with
      confidence);
    - that one assignment is a direct module-level statement (not nested in
      a function, class, or ``if``/``for``/``try`` block);
    - its value is a ``CheckPolicy(...)`` call with int-only literal
      keywords (already the v1 rule);
    - somewhere in the file, a ``check=`` keyword argument's value is the
      bare ``Name`` ``POLICY`` (i.e. something is actually handed this
      policy — matching how ``ci/vault_health.py`` builds its
      ``VaultConfig(..., check=POLICY)``);
    - no OTHER ``check=`` keyword argument appears anywhere with a different
      value (an inline ``CheckPolicy(...)``, a ``dataclasses.replace(POLICY,
      ...)``, or anything else) — that would mean the module can enforce a
      policy this parser never saw.

    Returns (kwargs, None) on success, or (None, reason) on any failure of
    the above.
    """
    gate_path = vault_root / "ci" / "vault_health.py"
    if not gate_path.is_file():
        return None, f"{gate_path} does not exist"

    try:
        source = gate_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(gate_path))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return None, f"could not parse {gate_path}: {exc}"

    assigns = _find_policy_assign_nodes(tree)
    if len(assigns) != 1:
        return None, (
            f"expected exactly one POLICY assignment in {gate_path}, found {len(assigns)}"
        )
    policy_node = assigns[0]
    if policy_node not in tree.body:
        return None, f"POLICY is not assigned at module level in {gate_path}"

    policy_value = getattr(policy_node, "value", None)
    if not isinstance(policy_value, ast.Call):
        return None, "POLICY is not assigned from a CheckPolicy(...) call"
    policy_call = policy_value

    func = policy_call.func
    func_name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if func_name != "CheckPolicy":
        return None, "POLICY is not assigned from a CheckPolicy(...) call"

    if policy_call.args:
        return None, "POLICY's CheckPolicy(...) call uses positional arguments, which is not supported"

    kwargs: dict[str, int] = {}
    for kw in policy_call.keywords:
        if kw.arg is None:
            return None, "POLICY's CheckPolicy(...) call uses **kwargs, which is not supported"
        try:
            value = ast.literal_eval(kw.value)
        except ValueError:
            return None, f"POLICY keyword {kw.arg!r} is not a literal"
        if not isinstance(value, int) or isinstance(value, bool):
            return None, f"POLICY keyword {kw.arg!r} is not an int literal"
        kwargs[kw.arg] = value

    check_values = _find_check_kwarg_values(tree)
    policy_refs = [v for v in check_values if isinstance(v, ast.Name) and v.id == "POLICY"]
    other_refs = [v for v in check_values if not (isinstance(v, ast.Name) and v.id == "POLICY")]
    if not policy_refs:
        return None, f"no check=POLICY keyword argument found anywhere in {gate_path}"
    if other_refs:
        return None, (
            f"a check= keyword argument in {gate_path} does not reference the bare POLICY name"
        )

    return kwargs, None


def _run_gate(vault_root: Path, graph: Any, cfg: Any, orphan_paths: list[str], claimed_set: set[str]) -> dict[str, Any]:
    """Replay the vault's own CI policy against the already-built graph.

    Reuses the same graph/config graph_cli.build() produced for
    unresolved_links/orphans, and the same orphan set check 4 already
    computed — only the policy differs, applied the same way
    ``ci/vault_health.py`` applies it (``check=`` on the VaultConfig).

    ``CheckPolicy(**kwargs)`` and ``run_check(...)`` are both caught broadly
    (not just the specific exception each happens to raise today): a defect
    here must degrade to "gate policy rejected" and let unresolved_links/
    orphans keep their own already-computed results — it must never escape
    to the caller's blanket ``except Exception`` around _run_graph_checks,
    which would mislabel this as "graphmark unavailable" and drop those too.
    """
    kwargs, error = _parse_gate_policy(vault_root)
    if error is not None:
        return {"not_run": error, "pass": None, "policy": None, "breach_lines": [], "orphans": [], "checks": []}

    import dataclasses  # noqa: PLC0415
    from graphmark.check import breach_lines, run_check  # noqa: PLC0415
    from graphmark.config import CheckPolicy  # noqa: PLC0415

    try:
        policy = CheckPolicy(**kwargs)
        gate_cfg = dataclasses.replace(cfg, check=policy)
        report = run_check(graph, gate_cfg)
    except Exception as exc:  # noqa: BLE001 - see docstring: must not masquerade as "graphmark unavailable"
        return {
            "not_run": f"gate policy rejected: {type(exc).__name__}: {exc}",
            "pass": None, "policy": kwargs, "breach_lines": [], "orphans": [], "checks": [],
        }

    lines: list[str] = [] if report["pass"] else breach_lines(report)
    orphans: list[dict[str, Any]] = []
    if not report["pass"]:
        for check in report["checks"]:
            if check["name"] == "max_orphans" and not check["pass"]:
                orphans = [
                    {"file": rel, "in_scope": rel in claimed_set}
                    for rel in sorted(orphan_paths)
                ]

    return {
        "not_run": None,
        "pass": report["pass"],
        "policy": kwargs,
        "breach_lines": lines,
        "orphans": orphans,
        # actual vs limit per check, always — not only on a breach (LOW-4).
        "checks": report["checks"],
    }


# ---------------------------------------------------------------------------
# new_orphans (item 3, round 3) — orphans this session's edits newly created
# ---------------------------------------------------------------------------

def _git_bytes(vault_root: Path, args: list[str]) -> bytes | None:
    """Like ``_git`` but returns raw bytes (for ``git archive``'s binary tar output)."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=vault_root, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _build_base_orphans(vault_root: Path, base: str) -> set[str]:
    """The vault-wide orphan set AT ``base`` (not the working tree).

    Extracts the tree at ``base`` with ``git archive | tar`` into a throwaway
    temp directory, then runs the SAME ``graph_cli.build`` used for the live
    graph on that copy. Chose ``git archive`` over ``git worktree add``:
    read-only against the real repo, no worktree registration (no risk of
    colliding with a live agent's own worktree — see the vault's
    git-worktree-hazards guidance), and no need to touch/restore HEAD.

    Scope config: pinned to the LIVE vault's resolved scope config (already
    in effect for the rest of this ``collect()`` call via ``_pin_vault_root``
    — ``graph_cli`` resolves ``GRAPH_NOTE_DIRS`` etc. from
    ``vault_scope_resolved`` at ITS import, not from anything under the
    extracted tree), not the base snapshot's own ``.vault/config/``. The
    question this check asks is "did this session's edits create a new
    orphan under the policy that governs the vault TODAY" — a base commit
    that predates an owner scope change (e.g. adding ``school/``) must not
    silently compare against the stale rule set that was in effect back then.
    """
    import graph_cli  # noqa: PLC0415

    archive = _git_bytes(vault_root, ["archive", base])
    if archive is None:
        raise RuntimeError(f"git archive {base} failed")

    tmp_dir = Path(tempfile.mkdtemp(prefix="wrap_up_audit_base_"))
    try:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
            tf.extractall(tmp_dir, filter="data")  # noqa: S202 - our own repo's own history
        graph, cfg = graph_cli.build(tmp_dir)
        return set(graph_cli.orphans(graph, cfg))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# checks 3, 4, gate, new_orphans — vault-wide, graphmark-backed
# ---------------------------------------------------------------------------

def _run_graph_checks(vault_root: Path, claimed_set: set[str], base: str, attempt_new_orphans: bool) -> dict[str, Any]:
    """Build the vault graph and derive unresolved_links / orphans / gate / new_orphans findings.

    Reuses ``graph_cli.build(vault_root)`` (plugins/workbench/machinery/engine/
    graph_cli.py:68-78) for the VaultConfig — same shape as the CI gate
    (``ci/vault_health.py``): scoped_folders=GRAPH_NOTE_DIRS,
    excluded_dirs=GRAPH_EXCLUDED_DIRS, rules_files=OPERATING_FILENAMES,
    transient_prefixes=TRANSIENT_PREFIXES. ``graph_cli`` also re-exports
    graphmark's ``orphans`` directly (identical to ``graphmark.check.orphans``).

    Imported here rather than at module scope: ``graph_cli`` imports
    ``graphmark`` eagerly at ITS module level, so a vault without graphmark
    installed must not lose the frontmatter/wikilink/index/scope checks over
    it — only this function's result degrades to ``not_run``.

    ``attempt_new_orphans`` is False when git itself is entirely unavailable
    (the scope check has already gone ``not_run`` for that same root cause);
    attempting — and failing — the base-tree build in that case would only
    add a redundant second not_run entry for the identical underlying
    problem, not new information.
    """
    import graph_cli  # noqa: PLC0415

    graph, cfg = graph_cli.build(vault_root)

    unresolved_findings: list[dict[str, Any]] = []
    for source_rel in sorted(graph.unresolved):
        in_scope = source_rel in claimed_set
        for target in graph.unresolved[source_rel]:
            unresolved_findings.append({
                "check": "unresolved_links",
                "file": source_rel,
                "detail": f"broken [[{target}]]",
                "in_scope": in_scope,
            })

    orphan_paths = graph_cli.orphans(graph, cfg)
    orphan_findings = [
        {"check": "orphans", "file": rel, "detail": "no links in or out (graph degree 0)"}
        for rel in sorted(orphan_paths)
        if rel in claimed_set
    ]

    gate = _run_gate(vault_root, graph, cfg, orphan_paths, claimed_set)

    new_orphans_findings: list[dict[str, Any]] = []
    new_orphans_error: str | None = None
    if attempt_new_orphans:
        try:
            base_orphans = _build_base_orphans(vault_root, base)
        except Exception as exc:  # noqa: BLE001 - degrade to not_run, never crash the whole audit
            new_orphans_error = f"could not build the base-tree graph at {base!r}: {type(exc).__name__}: {exc}"
        else:
            newly = set(orphan_paths) - base_orphans
            new_orphans_findings = [
                {
                    "check": "new_orphans",
                    "file": rel,
                    "detail": "orphan now; not an orphan at --base",
                    "in_scope": rel in claimed_set,
                }
                for rel in sorted(newly)
            ]

    return {
        "unresolved_links": unresolved_findings,
        "orphans": orphan_findings,
        "orphans_vault_wide_count": len(orphan_paths),
        "gate": gate,
        "new_orphans": new_orphans_findings,
        "new_orphans_error": new_orphans_error,
    }


# ---------------------------------------------------------------------------
# check 6 — handoff_sections (not pass/fail; evidence, never the deciding step)
# ---------------------------------------------------------------------------

def _extract_headings(text: str) -> list[tuple[int, str]]:
    """``## `` headings by 1-indexed line number, ignoring fenced code blocks."""
    headings: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        m = FENCE_RE.match(stripped)
        if m:
            marker = m.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        hm = HEADING_RE.match(line)
        if hm:
            headings.append((i, hm.group(1)))
    return headings


def _nearest_heading_at_or_before(headings: list[tuple[int, str]], line_no: int) -> str | None:
    result: str | None = None
    for hl, htext in headings:
        if hl <= line_no:
            result = htext
        else:
            break
    return result


def _parse_diff_hunks(diff_text: str) -> tuple[list[int], list[int]]:
    """Returns (new_side_lines, old_side_lines) touched by this -U0 diff.

    A pure addition (old_count==0) contributes only new-side lines; a pure
    deletion (new_count==0) contributes only old-side lines (mapped through
    the BASE file's headings by the caller); a replacement contributes both.
    """
    new_lines: list[int] = []
    old_lines: list[int] = []
    for line in diff_text.splitlines():
        m = HUNK_RE.match(line)
        if not m:
            continue
        old_start = int(m.group(1))
        old_count = int(m.group(2)) if m.group(2) is not None else 1
        new_start = int(m.group(3))
        new_count = int(m.group(4)) if m.group(4) is not None else 1
        if new_count > 0:
            new_lines.extend(range(new_start, new_start + new_count))
        if old_count > 0:
            old_lines.extend(range(old_start, old_start + old_count))
    return new_lines, old_lines


def _handoff_sections(vault_root: Path, base: str) -> dict[str, Any]:
    ctx = read_vault_context(vault_root)
    if ctx == "unknown":
        return {
            "file": None,
            "present": [],
            "touched": [],
            "not_run": "'.vault-context' is missing or invalid; cannot determine the handoff context",
        }

    handoff_rel = f".brain/handoff-{ctx}.md"
    handoff_path = vault_root / handoff_rel
    result: dict[str, Any] = {"file": handoff_rel, "present": [], "touched": [], "not_run": None}

    if not handoff_path.exists():
        result["not_run"] = f"{handoff_rel} does not exist"
        return result

    text = handoff_path.read_text(encoding="utf-8", errors="replace")
    new_headings = _extract_headings(text)
    result["present"] = [h for _, h in new_headings]

    tracked = _git(vault_root, ["ls-files", "--error-unmatch", handoff_rel]) is not None
    if not tracked:
        result["touched"] = list(result["present"])
        return result

    diff_out = _git(vault_root, ["diff", "-U0", base, "--", handoff_rel])
    if diff_out is None:
        result["not_run"] = f"git diff -U0 {base} -- {handoff_rel} failed"
        return result
    if diff_out.strip() == "":
        result["touched"] = []
        return result

    base_text = _git(vault_root, ["show", f"{base}:{handoff_rel}"])
    base_headings = _extract_headings(base_text) if base_text is not None else []

    new_lines, old_lines = _parse_diff_hunks(diff_out)
    new_file_lines = text.splitlines()
    base_file_lines = base_text.splitlines() if base_text is not None else []

    def _has_content(line_no: int, source_lines: list[str]) -> bool:
        # A blank separator line adjacent to a deleted/added heading maps
        # ambiguously to whichever section it is geometrically closer to
        # (e.g. the blank line right before a fully-deleted last section is
        # "nearest-at-or-before" the section ABOVE it) even though the
        # meaningful change is the section below. Ignoring content-free
        # lines avoids attributing the change to the wrong neighbor.
        idx = line_no - 1
        if 0 <= idx < len(source_lines):
            return source_lines[idx].strip() != ""
        return True

    touched_set: set[str] = set()
    for line_no in new_lines:
        if not _has_content(line_no, new_file_lines):
            continue
        touched_set.add(_nearest_heading_at_or_before(new_headings, line_no) or PREAMBLE)
    for line_no in old_lines:
        if not _has_content(line_no, base_file_lines):
            continue
        touched_set.add(_nearest_heading_at_or_before(base_headings, line_no) or PREAMBLE)

    order = [PREAMBLE] + [h for _, h in new_headings]
    for h in [h for _, h in base_headings]:
        if h not in order:
            order.append(h)
    result["touched"] = [h for h in order if h in touched_set]
    return result


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def _cap(findings: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    if limit <= 0 or len(findings) <= limit:
        return findings, 0
    return findings[:limit], len(findings) - limit


def collect(vault_root: Path, files: list[str] | None, base: str = "HEAD", limit: int = 20) -> dict[str, Any]:
    scope_config_source, restore_pin = _pin_vault_root(vault_root)
    try:
        return _collect_inner(vault_root, files, base, limit, scope_config_source)
    finally:
        restore_pin()


def _collect_inner(
    vault_root: Path, files: list[str] | None, base: str, limit: int, scope_config_source: str
) -> dict[str, Any]:
    scope = _compute_scope(vault_root, files, base)
    claimed_set = set(scope.claimed)
    not_run: list[dict[str, str]] = []

    for err in scope.errors:
        label = f"{err['file']}: {err['reason']}" if err["file"] else err["reason"]
        not_run.append({"check": "scope", "reason": label})

    scoped = _scoped_checks(vault_root, scope.claimed)

    graph_error: str | None = None
    try:
        graph_results = _run_graph_checks(vault_root, claimed_set, base, scope.git_ok)
    except Exception as exc:  # noqa: BLE001 - any import/build failure degrades to not_run
        graph_error = f"{type(exc).__name__}: {exc}"
        graph_results = None

    if graph_results is None:
        reason = f"graphmark unavailable: {graph_error}"
        not_run.append({"check": "unresolved_links", "reason": reason})
        not_run.append({"check": "orphans", "reason": reason})
        not_run.append({"check": "gate", "reason": reason})
        unresolved_findings: list[dict[str, Any]] = []
        orphan_findings: list[dict[str, Any]] = []
        new_orphans_findings: list[dict[str, Any]] = []
        orphans_vault_wide_count = None
        gate = {"not_run": reason, "pass": None, "policy": None, "breach_lines": [], "orphans": [], "checks": []}
        # new_orphans depends on the same graph; if we couldn't build it at
        # all, don't pile on a second near-identical not_run for it.
    else:
        unresolved_findings = graph_results["unresolved_links"]
        orphan_findings = graph_results["orphans"]
        orphans_vault_wide_count = graph_results["orphans_vault_wide_count"]
        gate = graph_results["gate"]
        if gate.get("not_run"):
            not_run.append({"check": "gate", "reason": gate["not_run"]})
        new_orphans_findings = graph_results["new_orphans"]
        if graph_results.get("new_orphans_error"):
            not_run.append({"check": "new_orphans", "reason": graph_results["new_orphans_error"]})

    handoff = _handoff_sections(vault_root, base)
    if handoff.get("not_run"):
        not_run.append({"check": "handoff_sections", "reason": handoff["not_run"]})

    frontmatter_findings, frontmatter_elided = _cap(scoped["frontmatter"], limit)
    no_wikilinks_findings, no_wikilinks_elided = _cap(scoped["no_wikilinks"], limit)
    index_findings, index_elided = _cap(scoped["index_membership"], limit)
    unresolved_capped, unresolved_elided = _cap(unresolved_findings, limit)
    orphan_capped, orphan_elided = _cap(orphan_findings, limit)
    new_orphan_capped, new_orphan_elided = _cap(new_orphans_findings, limit)

    gate_breach = bool(graph_results is not None and gate.get("pass") is False)

    total_findings = (
        len(scoped["frontmatter"])
        + len(scoped["no_wikilinks"])
        + len(unresolved_findings)
        + len(orphan_findings)
        + len(scoped["index_membership"])
        + len(new_orphans_findings)
        + (1 if gate_breach else 0)
    )

    if not_run:
        verdict = "INCOMPLETE"
    elif total_findings > 0:
        verdict = "FINDINGS"
    else:
        verdict = "CLEAN"

    skipped_capped, skipped_elided = _cap(scope.skipped, limit)
    unclaimed_capped = scope.unclaimed_dirty[:limit] if limit > 0 else scope.unclaimed_dirty
    unclaimed_elided = max(0, len(scope.unclaimed_dirty) - limit) if limit > 0 else 0

    return {
        "verdict": verdict,
        "vault_root": str(vault_root),
        "scope_config_source": scope_config_source,
        "scope": {
            "source": scope.source,
            "files": scope.claimed,
            "warnings": scope.warnings,
            "errors": scope.errors,
            "skipped": skipped_capped,
            "skipped_count": len(scope.skipped),
            "skipped_elided": skipped_elided,
            "unclaimed_dirty": unclaimed_capped,
            "unclaimed_dirty_count": len(scope.unclaimed_dirty),
            "unclaimed_dirty_elided": unclaimed_elided,
        },
        "checks": {
            "frontmatter": {
                "count": len(scoped["frontmatter"]),
                "findings": frontmatter_findings,
                "elided": frontmatter_elided,
            },
            "no_wikilinks": {
                "count": len(scoped["no_wikilinks"]),
                "findings": no_wikilinks_findings,
                "elided": no_wikilinks_elided,
            },
            "unresolved_links": {
                "count": len(unresolved_findings),
                "findings": unresolved_capped,
                "elided": unresolved_elided,
            },
            "orphans": {
                "count": len(orphan_findings),
                "findings": orphan_capped,
                "elided": orphan_elided,
                "vault_wide_count": orphans_vault_wide_count,
            },
            "new_orphans": {
                "count": len(new_orphans_findings),
                "findings": new_orphan_capped,
                "elided": new_orphan_elided,
            },
            "index_membership": {
                "count": len(scoped["index_membership"]),
                "findings": index_findings,
                "elided": index_elided,
            },
            "gate": gate,
            "handoff_sections": handoff,
        },
        "not_run": not_run,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _render_check(lines: list[str], title: str, node: dict[str, Any]) -> None:
    count = node["count"]
    if count == 0:
        lines.append(f"- {title}: clean")
        return
    lines.append(f"- {title} ({count}):")
    for f in node["findings"]:
        in_scope = f.get("in_scope")
        suffix = "" if in_scope is None else f" (in_scope: {str(in_scope).lower()})"
        lines.append(f"  - `{f['file']}`: {f['detail']}{suffix}")
    if node["elided"]:
        lines.append(f"  - ... {node['elided']} more")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"## Wrap-Up Audit — {report['verdict']}",
        "",
        f"- scope config: {report['scope_config_source']}",
        "",
        "### Scope",
        f"- source: {report['scope']['source']}",
        f"- files ({len(report['scope']['files'])}): "
        + (", ".join(f"`{f}`" for f in report["scope"]["files"]) or "(none)"),
    ]
    for w in report["scope"]["warnings"]:
        lines.append(f"- warning: {w}")
    if report["scope"]["errors"]:
        lines.append(f"- errors ({len(report['scope']['errors'])}):")
        for e in report["scope"]["errors"]:
            label = e["file"] or "(--files)"
            lines.append(f"  - `{label}`: {e['reason']}")
    if report["scope"]["skipped_count"]:
        lines.append(f"- skipped ({report['scope']['skipped_count']}):")
        for s in report["scope"]["skipped"]:
            lines.append(f"  - `{s['file']}`: {s['reason']}")
        if report["scope"]["skipped_elided"]:
            lines.append(f"  - ... {report['scope']['skipped_elided']} more")
    if report["scope"]["unclaimed_dirty_count"]:
        lines.append(f"- unclaimed dirty ({report['scope']['unclaimed_dirty_count']}, informational):")
        for u in report["scope"]["unclaimed_dirty"]:
            lines.append(f"  - `{u}`")
        if report["scope"]["unclaimed_dirty_elided"]:
            lines.append(f"  - ... {report['scope']['unclaimed_dirty_elided']} more")
    else:
        lines.append("- unclaimed dirty: none")
    lines.append("")

    lines.append("### Checks")
    checks = report["checks"]
    _render_check(lines, "Frontmatter", checks["frontmatter"])
    _render_check(lines, "No Wikilinks", checks["no_wikilinks"])
    _render_check(lines, "Unresolved Links (vault-wide)", checks["unresolved_links"])
    orphans_node = dict(checks["orphans"])
    vw = orphans_node["vault_wide_count"]
    orphans_title = "Orphans (in-scope)" + (f" — {vw} vault-wide" if vw is not None else "")
    _render_check(lines, orphans_title, orphans_node)
    _render_check(lines, "New Orphans (since --base)", checks["new_orphans"])
    _render_check(lines, "Index Membership", checks["index_membership"])

    gate = checks["gate"]
    if gate.get("not_run"):
        lines.append(f"- Gate: not run ({gate['not_run']})")
    else:
        status = "pass" if gate["pass"] else "FAIL"
        lines.append(f"- Gate: {status} ({gate['policy']}):")
        for c in gate.get("checks", []):
            mark = "ok" if c["pass"] else "FAIL"
            lines.append(f"  - {mark} {c['name']}: {c['actual']} (limit {c['limit']})")
        for bl in gate["breach_lines"]:
            lines.append(f"  - {bl}")
        for o in gate["orphans"]:
            lines.append(f"  - orphan `{o['file']}` (in_scope: {str(o['in_scope']).lower()})")
    lines.append("")

    handoff = checks["handoff_sections"]
    lines.append(f"### Handoff Sections (`{handoff['file']}`)")
    if handoff.get("not_run"):
        lines.append(f"- not run: {handoff['not_run']}")
    else:
        lines.append(f"- present: {', '.join(handoff['present']) or '(none)'}")
        lines.append(f"- touched: {', '.join(handoff['touched']) or '(none)'}")
    lines.append("")

    lines.append("### Not Run")
    if report["not_run"]:
        for nr in report["not_run"]:
            lines.append(f"- {nr['check']}: {nr['reason']}")
    else:
        lines.append("- (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic /wrap-up audit collector — returns a session VERDICT."
    )
    parser.add_argument("--vault-root", type=Path)
    parser.add_argument(
        "--files", nargs="*", default=None,
        help="The session's claimed files (vault-relative or absolute; quote each one). "
             "Omit to fall back to git status/diff evidence.",
    )
    parser.add_argument("--base", default="HEAD", help="Git ref to diff against (default HEAD).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--limit", type=int, default=20, help="Max finding rows per check.")
    args = parser.parse_args(argv)

    vault_root = args.vault_root.resolve() if args.vault_root else find_vault_root()
    if vault_root is None or not vault_root.is_dir():
        print("ERROR: vault root not found", file=sys.stderr)
        return VERDICT_EXIT_CODES["INCOMPLETE"]

    report = collect(vault_root, files=args.files, base=args.base, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(report))

    return VERDICT_EXIT_CODES[report["verdict"]]


def main(argv: list[str] | None = None) -> int:
    """Wraps ``_main`` so any uncaught exception exits 2 (INCOMPLETE), never 1 (FINDINGS).

    A crash silently read as "the audit ran and found issues" is worse than
    a crash read as "the audit didn't finish" — the caller must not treat
    the two the same way.
    """
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort guard; report and degrade, never crash-as-FINDINGS
        print(f"ERROR: wrap_up_audit crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return VERDICT_EXIT_CODES["INCOMPLETE"]


if __name__ == "__main__":
    raise SystemExit(main())
