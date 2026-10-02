"""Guard: a change to scoring code that flips a recorded verdict must be declared.

Fires only when the diff ``$(VERSION_BASE)...HEAD`` (the ``ctx.base`` ref the
runner passes, with ``--no-renames``) changes a file that decides re-scored
outcomes: ``evals/_harness/scorer.py``, ``matchers.py``, ``transcript.py`` or
``dispatch.py``, or any case's ``predicates.py``. A diff that changes none of
them passes without re-scoring anything.

When it fires, it re-scores every committed raw referenced by every committed
run file, for every skill, with direct library calls (never a model):
``dispatch.score_attempt(case_dir, <raw>/*.jsonl, workdir=None, gated_ids=<the
case's recorded gated_items>, end_state_dir=<raw>/end_state)`` per attempt, then
``scorer.compute_verdict``. An item's verdict is not stored per item in a run
file, so each side of a comparison is derived the same way, from every attempt
recorded for the item's case: ``compute_verdict({item: (True, outcomes)})``,
with ``outcomes`` read from the run file's recorded per-attempt item outcomes
(``old_verdict``) or from the recomputed ``Attempt.item_hits`` (``new_verdict``).
Never the run file's top-level ``verdict``, and never a single attempt.

Every item whose verdict flips needs a matching entry in
``evals/<skill>/rescore-declarations.json`` as that file stands at HEAD (an
entry already present at the base still counts: run files are immutable, so a
flip declared once recurs identically on every later scoring-code change). An
entry matches only with exactly the keys ``run_file`` (the run file's
repo-relative path), ``item``, ``old_verdict`` and ``new_verdict``, and values
exactly equal to what this guard computed; one missing a key, carrying an extra
key, or holding any different value matches nothing.

It fails closed, whatever is declared, when an attempt recorded ``counted`` has
no raw directory, when a recorded case has no case directory, or when
``score_attempt`` raises (``CaseContractError``). An attempt recorded
``indeterminate`` whose raw directory is absent is not a failure: the conductor
writes no raw files for a ``dispatch_error`` attempt, and it re-scores to
``indeterminate`` for every item, as recorded.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from evals._harness.dispatch import discover_skill_dirs, score_attempt
from evals._harness.guards import GuardContext, Result
from evals._harness.scorer import compute_verdict

_GUARD_NAME = "rescore"
_SCORING_HARNESS_FILES = frozenset(
    f"evals/_harness/{name}.py" for name in ("scorer", "matchers", "transcript", "dispatch")
)
# A case's predicates.py sits at evals/<skill>/<case>/predicates.py; a `_`-prefixed
# directory under evals/ is the harness, never a skill.
_CASE_PREDICATES = re.compile(r"^evals/(?!_)[^/]+/[^/]+/predicates\.py$")


def _fail(message: str) -> Result:
    return Result(level="fail", guard=_GUARD_NAME, message=message)


def _scoring_code_changed(repo_root: Path, base: str) -> bool:
    output = subprocess.run(
        [
            "git", "-C", str(repo_root), "diff", "--no-renames", "--name-only", "-z",
            f"{base}...HEAD",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return any(
        path in _SCORING_HARNESS_FILES or _CASE_PREDICATES.match(path)
        for path in output.split("\0")
        if path
    )


def _load_declarations(skill_dir: Path) -> list:
    try:
        entries = json.loads((skill_dir / "rescore-declarations.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return entries if isinstance(entries, list) else []


def _is_declared(declarations: list, run_rel: str, item: str, old: str, new: str) -> bool:
    expected = {"run_file": run_rel, "item": item, "old_verdict": old, "new_verdict": new}
    # Dict equality is the exact-match rule: a missing or extra key, or any
    # differing value, makes an entry unequal to `expected`.
    return any(entry == expected for entry in declarations)


def _verdict(outcomes: list[str]) -> str:
    # The item as a singleton gated mapping: compute_verdict is the one verdict rule.
    return compute_verdict({"item": (True, outcomes)})


def _rescore_case(
    repo_root: Path,
    skill_dir: Path,
    run_path: Path,
    run_rel: str,
    recorded_case: dict,
    declarations: list,
) -> list[Result]:
    case = recorded_case["case"]
    label = f"{run_rel} case {case!r}"
    case_dir = skill_dir / case
    if not case_dir.is_dir():
        return [_fail(f"{label}: its case directory {case_dir.relative_to(repo_root)} is missing")]

    gated_ids = set(recorded_case["gated_items"])
    old_outcomes: dict[str, list[str]] = {}
    new_outcomes: dict[str, list[str]] = {}
    for attempt in recorded_case["attempts"]:
        raw_dir = run_path.parent / attempt["raw"]
        recorded_items = attempt["items"]
        if raw_dir.is_dir():
            try:
                rescored, _unmatched = score_attempt(
                    case_dir,
                    sorted(raw_dir.glob("*.jsonl")),
                    workdir=None,
                    gated_ids=gated_ids,
                    end_state_dir=raw_dir / "end_state",
                )
            except (ValueError, OSError) as exc:
                return [
                    _fail(
                        f"{label} attempt {attempt['attempt']}: re-scoring raised "
                        f"{type(exc).__name__}: {exc}"
                    )
                ]
            rescored_items = dict(rescored.item_hits)
        elif attempt["classification"] == "indeterminate":
            # The conductor writes no raw for a dispatch_error attempt: it re-scores
            # to indeterminate for every item, exactly as recorded.
            rescored_items = {item: "indeterminate" for item in recorded_items}
        else:
            return [
                _fail(
                    f"{label} attempt {attempt['attempt']}: recorded counted but its raw "
                    f"directory {attempt['raw']} is missing, so it cannot be re-scored"
                )
            ]
        for item, outcome in recorded_items.items():
            old_outcomes.setdefault(item, []).append(outcome)
        for item, outcome in rescored_items.items():
            new_outcomes.setdefault(item, []).append(outcome)

    results: list[Result] = []
    for item in sorted(set(old_outcomes) | set(new_outcomes)):
        old = _verdict(old_outcomes.get(item, []))
        new = _verdict(new_outcomes.get(item, []))
        if old != new and not _is_declared(declarations, run_rel, item, old, new):
            results.append(
                _fail(
                    f"{label}: item {item!r} re-scores {old} -> {new} but "
                    f"{skill_dir.relative_to(repo_root).as_posix()}/rescore-declarations.json "
                    "holds no matching entry"
                )
            )
    return results


def _rescore_run(repo_root: Path, skill_dir: Path, run_path: Path, declarations: list) -> list[Result]:
    run_rel = run_path.relative_to(repo_root).as_posix()
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [_fail(f"{run_rel}: not readable as JSON ({exc}), so it cannot be re-scored")]
    results: list[Result] = []
    try:
        for recorded_case in run["cases"]:
            results.extend(
                _rescore_case(repo_root, skill_dir, run_path, run_rel, recorded_case, declarations)
            )
    except (KeyError, TypeError, AttributeError) as exc:
        results.append(
            _fail(f"{run_rel}: does not hold the recorded fields re-scoring needs ({type(exc).__name__}: {exc})")
        )
    return results


def check(ctx: GuardContext) -> list[Result]:
    """Fail every undeclared verdict flip a scoring-code change causes.

    Parameters
    ----------
    ctx : GuardContext
        ``ctx.base`` is the ref to diff against; ``ctx.repo_root`` is the work
        tree, checked out at HEAD, whose run files, raws, case directories and
        ``rescore-declarations.json`` files are read.

    Returns
    -------
    list[Result]
        Empty when the diff changes no scoring code, or every flip it causes is
        declared. Otherwise one ``fail`` per undeclared flip, and one per
        fail-closed condition (a missing raw of a ``counted`` attempt, a missing
        case directory, a re-scoring error, an unreadable run file).
    """
    if not _scoring_code_changed(ctx.repo_root, ctx.base):
        return []
    evals_root = ctx.repo_root / "evals"
    if not evals_root.is_dir():
        return []
    results: list[Result] = []
    for skill_dir in discover_skill_dirs(evals_root):
        declarations = _load_declarations(skill_dir)
        for run_path in sorted((skill_dir / "runs").glob("*.json")):
            results.extend(_rescore_run(ctx.repo_root, skill_dir, run_path, declarations))
    return results
