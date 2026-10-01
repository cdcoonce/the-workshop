"""Builds dispatch prompts and scores attempts for the eval-suite conductor.

The eval-suite conductor (``.claude/skills/eval-suite/SKILL.md``) documents
the fixture list, the retry loop, and the harness entry points it drives; this
module supplies the two entry points that issue #995 owns — turning a case
directory into a dispatchable prompt, and turning an attempt's raw
transcripts into a scored, retry-ready ``Attempt``. It never dispatches a
subagent, calls a model, or invokes the ``claude`` CLI.

Public contract
----------------
``build_dispatch_prompt(case_dir) -> str``
    The exact prompt text sent to a case-agent (``mode = "subagent"``) or to
    each lens agent (``mode = "inline"``): the case's ``prompt.md`` (or
    whatever file ``case.toml``'s ``prompt`` key names), read verbatim. Never
    reads ``acceptance.md``.

``build_no_skill_prompt(case_dir) -> str``
    The no-skill arm's prompt: the same prompt text with every line naming
    the rostered skill (the case's parent directory name) removed, and a
    fixed do-not-invoke-any-skill instruction appended. Never reads
    ``acceptance.md``.

``Evidence``
    Frozen dataclass a case's ``predicates.py`` scorers receive:
    ``transcripts`` (parsed ``Transcript``s — one for ``mode = "subagent"``,
    one per lens agent for ``mode = "inline"``), ``findings`` (the union of
    ``extract_findings`` over their final replies), ``workdir`` (the attempt's
    built fixture directory, or ``None`` when re-scoring from raws alone),
    and ``end_state`` (file name -> text, loaded from a prior
    ``snapshot_end_state`` call; empty when the case takes no snapshot).

``snapshot_end_state(case_dir, workdir, transcript_paths, dest) -> None``
    Creates ``dest`` and, when the case's ``predicates.py`` defines
    ``end_state``, writes each file it returns into ``dest``. Leaves ``dest``
    empty otherwise.

``score_attempt(case_dir, transcript_paths, workdir, gated_ids, transcript_status=None, end_state_dir=None) -> tuple[Attempt, int]``
    Parses every transcript, builds ``Evidence``, runs every item's scorer,
    and returns #991's ``classify_attempt`` result plus the trend unmatched-
    finding count (0 for a case without ``envelope = "findings"``).
    ``transcript_status`` defaults to the worst status among the parsed
    transcripts; the conductor overrides it with ``"dispatch_error"`` when an
    attempt never produced a transcript at all.

This module only imports #991's ``scorer.py``, #992's ``matchers.py`` and
``transcript.py`` — it never edits them, and it never reads
``evals/<skill>/checks.manifest`` itself (the conductor derives ``gated_ids``
from that file and passes the set in).
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from evals._harness.matchers import count_unmatched, extract_findings
from evals._harness.scorer import Attempt, classify_attempt
from evals._harness.transcript import Transcript, parse_transcript

_VALID_MODES = {"subagent", "inline"}
_NO_SKILL_INSTRUCTION = "Do not invoke any skill while completing this task."


@dataclass(frozen=True)
class Evidence:
    """Everything a case's scorers see about one attempt.

    Attributes
    ----------
    transcripts : list[Transcript]
        Every parsed transcript for the attempt.
    findings : list[dict]
        The union of ``extract_findings`` over every transcript's final
        reply.
    workdir : Path | None
        The attempt's built fixture directory, or ``None`` when re-scoring
        from raws alone.
    end_state : dict[str, str]
        File name -> text, loaded from a prior ``snapshot_end_state`` call;
        empty when the case takes no end-state snapshot.
    """

    transcripts: list[Transcript]
    findings: list[dict]
    workdir: Path | None
    end_state: dict[str, str]


def _case_toml(case_dir: Path) -> dict:
    """Parse and minimally validate *case_dir*'s ``case.toml``."""
    case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
    mode = case_toml.get("mode")
    if mode not in _VALID_MODES:
        raise ValueError(
            f"{case_dir}: case.toml 'mode' must be one of {sorted(_VALID_MODES)}, got {mode!r}"
        )
    prompt = case_toml.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError(f"{case_dir}: case.toml must set a non-empty 'prompt' file name")
    return case_toml


def _prompt_text(case_dir: Path, case_toml: dict) -> str:
    return (case_dir / case_toml["prompt"]).read_text(encoding="utf-8")


def _load_predicates(case_dir: Path) -> ModuleType | None:
    """Load *case_dir*'s ``predicates.py`` by file path, or ``None`` if absent.

    Loaded with bytecode caching disabled: a case directory can be scored
    from a read-only checkout, and the harness writes only where its own
    callers name explicitly — never a stray ``__pycache__/`` beside a case's
    ``predicates.py``.
    """
    predicates_path = case_dir / "predicates.py"
    if not predicates_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        f"_eval_suite_predicates_{case_dir.name}", predicates_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load predicates.py from {predicates_path}")
    module = importlib.util.module_from_spec(spec)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    return module


def build_dispatch_prompt(case_dir: Path) -> str:
    """Return the exact prompt text sent to a case-agent or lens agent.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.

    Returns
    -------
    str
        The content of the file ``case.toml``'s ``prompt`` key names, read
        verbatim. Never reads ``acceptance.md``.
    """
    case_toml = _case_toml(case_dir)
    return _prompt_text(case_dir, case_toml)


def build_no_skill_prompt(case_dir: Path) -> str:
    """Return the no-skill arm's prompt text.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.

    Returns
    -------
    str
        The same prompt text as ``build_dispatch_prompt``, with every line
        naming the rostered skill (``case_dir.parent.name``) removed, and a
        fixed do-not-invoke-any-skill instruction appended. Never reads
        ``acceptance.md``.
    """
    case_toml = _case_toml(case_dir)
    prompt_text = _prompt_text(case_dir, case_toml)
    skill = case_dir.parent.name
    kept_lines = [line for line in prompt_text.splitlines() if skill not in line]
    stripped = "\n".join(kept_lines).rstrip("\n")
    return f"{stripped}\n\n{_NO_SKILL_INSTRUCTION}\n"


def _combined_status(transcripts: list[Transcript]) -> str:
    if not transcripts:
        return "missing"
    for transcript in transcripts:
        if transcript.status != "complete":
            return transcript.status
    return "complete"


def _load_end_state(end_state_dir: Path | None) -> dict[str, str]:
    if end_state_dir is None or not end_state_dir.is_dir():
        return {}
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(end_state_dir.iterdir())
        if path.is_file()
    }


def snapshot_end_state(
    case_dir: Path,
    workdir: Path,
    transcript_paths: list[Path],
    dest: Path,
) -> None:
    """Snapshot end-state evidence for one attempt, before it is scored.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.
    workdir : Path
        The attempt's built fixture directory.
    transcript_paths : list[Path]
        Paths to the attempt's transcript JSONL files.
    dest : Path
        The attempt's ``end_state/`` directory to create and populate. #993's
        ledger copies this directory verbatim into the attempt's raw
        directory.

    Raises
    ------
    ValueError
        If the case's ``predicates.py`` ``end_state`` function returns a name
        that is not a plain file name (contains a path separator, or is
        ``"."``/``".."``).
    """
    dest.mkdir(parents=True, exist_ok=True)
    module = _load_predicates(case_dir)
    end_state_fn = getattr(module, "end_state", None) if module is not None else None
    if end_state_fn is None:
        return
    transcripts = [parse_transcript(path) for path in transcript_paths]
    snapshot = end_state_fn(workdir, case_dir, transcripts)
    for name, text in snapshot.items():
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"{case_dir}: end_state returned an unsafe file name {name!r}")
        (dest / name).write_text(text, encoding="utf-8")


def score_attempt(
    case_dir: Path,
    transcript_paths: list[Path],
    workdir: Path | None,
    gated_ids: set[str],
    transcript_status: str | None = None,
    end_state_dir: Path | None = None,
) -> tuple[Attempt, int]:
    """Score one attempt: parse its transcripts, run every item's scorer.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.
    transcript_paths : list[Path]
        Paths to the attempt's transcript JSONL files (one for
        ``mode = "subagent"``, one per lens agent for ``mode = "inline"``).
    workdir : Path | None
        The attempt's built fixture directory, or ``None`` when re-scoring
        from raws alone.
    gated_ids : set[str]
        The case's gated item ids, read by the conductor from the skill's
        ``checks.manifest``. Every id must name an item declared in this
        case's ``case.toml``.
    transcript_status : str | None
        Overrides the status derived from *transcript_paths* — the conductor
        passes ``"dispatch_error"`` when an attempt never produced a
        transcript at all. ``None`` derives the worst status among the
        parsed transcripts.
    end_state_dir : Path | None
        A directory of end-state snapshot files from a prior
        ``snapshot_end_state`` call, or ``None``/absent for a case that took
        no end-state snapshot.

    Returns
    -------
    tuple[Attempt, int]
        #991's ``classify_attempt`` result, and the trend unmatched-finding
        count (0 for a case without ``envelope = "findings"``).

    Raises
    ------
    ValueError
        If any id in *gated_ids* does not name an item in this case's
        ``case.toml``.
    """
    case_toml = _case_toml(case_dir)
    items = case_toml.get("items", [])
    item_ids = {item["id"] for item in items}
    unknown_gated_ids = gated_ids - item_ids
    if unknown_gated_ids:
        raise ValueError(
            f"{case_dir}: gated_ids {sorted(unknown_gated_ids)} name no item in case.toml"
        )

    transcripts = [parse_transcript(path) for path in transcript_paths]
    status = transcript_status if transcript_status is not None else _combined_status(transcripts)

    findings: list[dict] = []
    per_transcript_ok: list[bool] = []
    for transcript in transcripts:
        transcript_findings, ok = extract_findings(transcript.final_text)
        findings.extend(transcript_findings)
        per_transcript_ok.append(ok)

    uses_findings_envelope = case_toml.get("envelope") == "findings"
    envelope_parsed = all(per_transcript_ok) if uses_findings_envelope else True

    evidence = Evidence(
        transcripts=transcripts,
        findings=findings,
        workdir=workdir,
        end_state=_load_end_state(end_state_dir),
    )

    if status == "complete":
        module = _load_predicates(case_dir)
        item_hits = {
            item["id"]: bool(getattr(module, item["scorer"])(evidence, **item.get("params", {})))
            for item in items
        }
    else:
        item_hits = {item["id"]: False for item in items}

    attempt = classify_attempt(status, envelope_parsed, item_hits)

    if uses_findings_envelope:
        review_item_params = [
            item["params"]
            for item in items
            if isinstance(item.get("params"), dict)
            and "file_suffix" in item["params"]
            and "regex" in item["params"]
        ]
        unmatched = count_unmatched(findings, review_item_params)
    else:
        unmatched = 0

    return attempt, unmatched
