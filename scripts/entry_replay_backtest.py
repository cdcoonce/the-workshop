"""Measure the entry-replay fallback against real concurrent vault history.

``entry_replay.py`` is /sync's fail-closed fallback for hub-file conflicts, and
a green unit suite says nothing about how often it accepts the conflicts real
sessions produce. This rig replays them: it runs a *baseline* copy of the
module (read from a git ref) and the *working-tree* copy side by side over the
same inputs and tabulates accept / refuse for each, plus the line-multiset
invariant on every accept (nothing either side added is lost, nothing is
invented -- the same check as ``entry_replay.py --verify``).

Usage, from the workshop repository root::

    uv run python -m scripts.entry_replay_backtest \\
        --vault /path/to/the-vault --since 2026-09-21 [--baseline-ref origin/dev]

The vault is only ever read (``git show``, ``git merge-file`` on temp copies).

Two measurements, both run in the vault repository:

1. **Reflog events.** Every ``rebase ... (start)`` line in
   ``<git-common-dir>/logs/HEAD``, ``worktrees/*/logs/HEAD`` and
   ``logs/refs/heads/**`` is a real concurrent sync: the old sha is the
   session tip, the new sha is what it was rebased onto, and their merge-base
   is the session base. Each file changed on both sides whose three-way
   ``git merge-file`` conflicts is merged by both modules. An *event* passes
   only when every conflicting file is a hub file and every one is accepted.
2. **Pairs.** Consecutive first-parent commits A, B on ``--ref`` that touch
   the same hub file with ``B^:f == A:f`` are replayed as if concurrent: base
   ``A^``, origin ``A``, tip = B's change applied to ``A^``. The expected
   result is ``B:f``; pairs are stratified by whether plain
   ``git merge-file`` of the same three versions conflicts.

The two modules are loaded as isolated instances under distinct module names
(the baseline from ``git show <ref>:...`` into a temp dir); nothing is
monkeypatched, so neither measurement can contaminate the other.
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS_REL = "plugins/workbench/skills/vault-sync/scripts"
MODULE_FILES = ("entry_replay.py", "sync_target.py")
LEDGERS = ("brain/Gotchas.md", "brain/Key Decisions.md", "perf/Brag Doc.md")
_REFLOG_RE = re.compile(r"^([0-9a-f]{40}) ([0-9a-f]{40}) .*? (\d{9,11}) [+-]\d{4}\t(.*)$")


# ---------------------------------------------------------------------------
# Isolated module instances
# ---------------------------------------------------------------------------


def load_isolated(name: str, source_dir: Path) -> ModuleType:
    """Import ``source_dir/entry_replay.py`` as module ``name``, in isolation.

    ``entry_replay`` does a bare ``from sync_target import ...``; the shared
    module name is cleared before and after the import so two instances never
    see each other's helper, and ``sys.path`` is restored.
    """
    saved = sys.modules.pop("sync_target", None)
    sys.path.insert(0, str(source_dir))
    try:
        spec = importlib.util.spec_from_file_location(name, source_dir / "entry_replay.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {source_dir / 'entry_replay.py'}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(source_dir))
        sys.modules.pop("sync_target", None)
        if saved is not None:
            sys.modules["sync_target"] = saved
    return module


def load_baseline(ref: str, workdir: Path) -> ModuleType:
    """The module as committed at ``ref`` in the workshop repository."""
    for filename in MODULE_FILES:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"{ref}:{SKILL_SCRIPTS_REL}/{filename}"],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"cannot read {filename} at {ref!r}: {proc.stderr.decode(errors='replace').strip()}"
            )
        (workdir / filename).write_bytes(proc.stdout)
    return load_isolated("entry_replay_baseline", workdir)


def load_candidate() -> ModuleType:
    return load_isolated("entry_replay_candidate", REPO_ROOT / SKILL_SCRIPTS_REL)


# ---------------------------------------------------------------------------
# Vault git access (read-only)
# ---------------------------------------------------------------------------


@dataclass
class Vault:
    root: Path

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, check=False
        )

    def blob(self, rev: str, path: str) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(self.root), "cat-file", "blob", f"{rev}:{path}"],
            capture_output=True,
            check=False,
        )
        return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else None

    def has(self, rev: str) -> bool:
        return self.git("cat-file", "-e", f"{rev}^{{commit}}").returncode == 0

    def common_dir(self) -> Path:
        out = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        return Path(out)

    def changed(self, a: str, b: str) -> set[str]:
        out = self.git("diff", "--name-only", "--no-renames", a, b).stdout
        return {line for line in out.split("\n") if line}


def merge_file_conflicts(ours: str, base: str, theirs: str) -> tuple[bool, str]:
    """``git merge-file -p``: ``(conflicted, merged_text)`` on temp copies."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            path = os.path.join(tmp, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            paths.append(path)
        proc = subprocess.run(
            ["git", "merge-file", "-p", *paths], capture_output=True, text=True, check=False
        )
    return proc.returncode != 0, proc.stdout


# ---------------------------------------------------------------------------
# Running a module on one file
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    """One module's verdict on one file."""

    status: str  # "accept" | "refuse" | "crash"
    merged: str = ""
    reason: str = ""


def run_merge(module: ModuleType, path: str, base: str, tip: str, origin: str) -> Outcome:
    merge = module.ledger_merge if path in module.LEDGER_FILES else module.handoff_merge
    try:
        merged, _detail = merge(base, tip, origin, path)
    except module.RefusalError as exc:
        return Outcome("refuse", reason=str(exc).split(": ", 1)[-1])
    except Exception as exc:  # noqa: BLE001 -- a crash is a measurement, not a stop
        return Outcome("crash", reason=f"{type(exc).__name__}: {exc}")
    return Outcome("accept", merged=merged)


def nonblank(text: str) -> Counter[str]:
    return Counter(line for line in text.splitlines() if line.strip())


def violations(checker: ModuleType, base: str, tip: str, origin: str, merged: str) -> bool:
    """True when the merge lost or invented a line (the --verify invariant)."""
    verdict = checker.compare_texts(base, tip, origin, merged)
    return bool(verdict["missing"] or verdict["extra"])


# ---------------------------------------------------------------------------
# Measurement 1: reflog events
# ---------------------------------------------------------------------------


def rebase_events(vault: Vault, since_epoch: int) -> set[tuple[str, str]]:
    """``(session_tip, onto)`` for every logged ``rebase (start)`` since the cutoff."""
    common = vault.common_dir()
    logs = [str(common / "logs" / "HEAD")]
    logs += glob.glob(str(common / "worktrees" / "*" / "logs" / "HEAD"))
    logs += glob.glob(str(common / "logs" / "refs" / "heads" / "**" / "*"), recursive=True)
    events: set[tuple[str, str]] = set()
    for log in logs:
        if not os.path.isfile(log):
            continue
        with open(log, errors="replace") as handle:
            for line in handle:
                m = _REFLOG_RE.match(line.rstrip("\n"))
                if m is None or "rebase" not in m.group(4) or "(start)" not in m.group(4):
                    continue
                if int(m.group(3)) >= since_epoch:
                    events.add((m.group(1), m.group(2)))
    return events


@dataclass
class Tally:
    """Per-module counters for the reflog measurement."""

    event_pass: int = 0
    files_accept: int = 0
    files_refuse: int = 0
    files_crash: int = 0
    invariant_violations: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


def measure_reflog(
    vault: Vault, since_epoch: int, modules: dict[str, ModuleType], checker: ModuleType
) -> tuple[Counter[str], dict[str, Tally], list[str]]:
    counts: Counter[str] = Counter()
    tallies = {label: Tally() for label in modules}
    notes: list[str] = []
    for tip, onto in sorted(rebase_events(vault, since_epoch)):
        counts["rebase-starts"] += 1
        if not vault.has(tip) or not vault.has(onto):
            counts["missing-objects"] += 1
            continue
        base = vault.git("merge-base", tip, onto).stdout.strip()
        if not base or base in (tip, onto):
            counts["no-divergence"] += 1
            continue
        conflicting: list[tuple[str, str, str, str]] = []
        for path in sorted(vault.changed(base, tip) & vault.changed(base, onto)):
            b, t, o = vault.blob(base, path), vault.blob(tip, path), vault.blob(onto, path)
            if b is None or t is None or o is None or t == o:
                continue
            if merge_file_conflicts(o, b, t)[0]:
                conflicting.append((path, b, t, o))
        if not conflicting:
            counts["git-would-merge-cleanly"] += 1
            continue
        counts["conflicting-events"] += 1
        if any(not checker.is_allowlisted(path) for path, *_rest in conflicting):
            counts["with-non-hub-conflict"] += 1
            continue
        counts["hub-only-events"] += 1
        for label, module in modules.items():
            tally = tallies[label]
            accepted_all = True
            for path, b, t, o in conflicting:
                outcome = run_merge(module, path, b, t, o)
                if outcome.status == "accept":
                    tally.files_accept += 1
                    if violations(checker, b, t, o, outcome.merged):
                        tally.invariant_violations += 1
                        notes.append(f"INVARIANT {label} {tip[:8]}..{onto[:8]} {path}")
                else:
                    accepted_all = False
                    tally.files_refuse += outcome.status == "refuse"
                    tally.files_crash += outcome.status == "crash"
                    tally.reasons[outcome.reason[:90]] += 1
            tally.event_pass += accepted_all
    return counts, tallies, notes


# ---------------------------------------------------------------------------
# Measurement 2: consecutive-commit pairs
# ---------------------------------------------------------------------------


def hub_files(vault: Vault, ref: str, checker: ModuleType) -> list[str]:
    listed = vault.git("ls-tree", "-r", "--name-only", ref).stdout.split("\n")
    return sorted({p for p in listed if p and checker.is_allowlisted(p)} | set(LEDGERS))


def measure_pairs(
    vault: Vault, ref: str, since: str, modules: dict[str, ModuleType], checker: ModuleType
) -> tuple[Counter[str], list[str]]:
    counts: Counter[str] = Counter()
    wrong: list[str] = []
    for path in hub_files(vault, ref, checker):
        revs = vault.git(
            "log", "--first-parent", "--format=%H", "--since", since, ref, "--", path
        ).stdout.split()[::-1]
        for a_rev, b_rev in zip(revs, revs[1:], strict=False):
            a_par, a = vault.blob(a_rev + "^", path), vault.blob(a_rev, path)
            b_par, b = vault.blob(b_rev + "^", path), vault.blob(b_rev, path)
            if a_par is None or a is None or b_par is None or b is None or b_par != a:
                counts["skipped-non-adjacent"] += 1
                continue
            dependent, tip = merge_file_conflicts(a_par, b_par, b)
            if dependent:
                counts["skipped-dependent"] += 1
                continue
            git_conflict, git_merged = merge_file_conflicts(a, a_par, tip)
            stratum = "git-conflict" if git_conflict else "git-clean"
            if not git_conflict and git_merged != b:
                stratum = "git-clean-but-wrong"
            counts["pairs"] += 1
            counts[f"{stratum}"] += 1
            for label, module in modules.items():
                outcome = run_merge(module, path, a_par, tip, a)
                if outcome.status != "accept":
                    counts[f"{stratum}:{label}-{outcome.status}"] += 1
                    continue
                counts[f"{stratum}:{label}-accept"] += 1
                if outcome.merged == b:
                    counts[f"{label}-exact"] += 1
                elif nonblank(outcome.merged) == nonblank(b):
                    counts[f"{label}-same-lines"] += 1
                else:
                    counts[f"{label}-WRONG"] += 1
                    wrong.append(f"{label} {path} {a_rev[:8]}..{b_rev[:8]}")
    return counts, wrong


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(
    since: str,
    counts: Counter[str],
    tallies: dict[str, Tally],
    notes: list[str],
    pair_counts: Counter[str],
    wrong: list[str],
    labels: list[str],
) -> None:
    hub = counts["hub-only-events"]
    print(f"== reflog events since {since} ==")
    for key in (
        "rebase-starts",
        "missing-objects",
        "no-divergence",
        "git-would-merge-cleanly",
        "conflicting-events",
        "with-non-hub-conflict",
        "hub-only-events",
    ):
        print(f"  {key:26} {counts[key]}")
    header = "".join(f"{label:>12}" for label in labels)
    print(f"\n  {'hub-only conflicts':26}{header}")
    rows = (
        ("events accepted", lambda t: f"{t.event_pass}/{hub}"),
        ("files accepted", lambda t: str(t.files_accept)),
        ("files refused", lambda t: str(t.files_refuse)),
        ("files crashed", lambda t: str(t.files_crash)),
        ("invariant violations", lambda t: str(t.invariant_violations)),
    )
    for name, cell in rows:
        print(f"  {name:26}" + "".join(f"{cell(tallies[label]):>12}" for label in labels))
    for label in labels:
        if tallies[label].reasons:
            print(f"\n  top refusal reasons ({label}):")
            for reason, n in tallies[label].reasons.most_common(6):
                print(f"    {n:3}  {reason}")
    for note in notes:
        print(f"  !! {note}")

    print(f"\n== consecutive-commit pairs since {since} ==")
    for key in ("pairs", "git-clean", "git-conflict", "git-clean-but-wrong",
                "skipped-non-adjacent", "skipped-dependent"):
        print(f"  {key:26} {pair_counts[key]}")
    print(f"\n  {'accepted / pairs':26}{header}")
    for stratum in ("git-clean", "git-conflict"):
        cells = "".join(
            f"{pair_counts[f'{stratum}:{label}-accept']}/{pair_counts[stratum]}".rjust(12)
            for label in labels
        )
        print(f"  {stratum:26}{cells}")
    for kind in ("exact", "same-lines", "WRONG"):
        cells = "".join(f"{pair_counts[f'{label}-{kind}']:>12}" for label in labels)
        print(f"  {'accepted ' + kind:26}{cells}")
    for item in wrong[:10]:
        print(f"  !! WRONG {item}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest entry_replay against vault history.")
    parser.add_argument("--vault", required=True, type=Path, help="path to the vault repository")
    parser.add_argument("--since", required=True, help="YYYY-MM-DD cutoff for both measurements")
    parser.add_argument(
        "--baseline-ref",
        default="origin/dev",
        help="workshop git ref holding the baseline entry_replay (default: origin/dev)",
    )
    parser.add_argument(
        "--ref", default="origin/main", help="vault ref whose first-parent history feeds the pairs"
    )
    args = parser.parse_args(argv)

    vault = Vault(args.vault.resolve())
    if vault.git("rev-parse", "--git-dir").returncode != 0:
        print(f"error: {args.vault} is not a git repository", file=sys.stderr)
        return 2
    ref = args.ref if vault.has(args.ref) else "HEAD"
    try:
        since_epoch = int(
            datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        )
    except ValueError:
        print(f"error: --since {args.since!r} is not YYYY-MM-DD", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        baseline = load_baseline(args.baseline_ref, Path(tmp))
        candidate = load_candidate()
    modules = {"baseline": baseline, "candidate": candidate}
    counts, tallies, notes = measure_reflog(vault, since_epoch, modules, candidate)
    pair_counts, wrong = measure_pairs(vault, ref, args.since, modules, candidate)
    print_report(args.since, counts, tallies, notes, pair_counts, wrong, list(modules))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
