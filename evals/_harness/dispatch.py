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
    interpolates ``acceptance.md``; it reads that file only to refuse a
    prompt that embeds any line of it (``AcceptanceLeakError``).

``build_no_skill_prompt(case_dir) -> str``
    The no-skill arm's prompt: the same prompt text with every reference to
    the rostered skill (the case's parent directory name) removed (the
    reference only, never the line around it), and a fixed
    do-not-invoke-any-skill instruction appended. The same
    ``AcceptanceLeakError`` guard applies.

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
import re
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from evals._harness.matchers import count_unmatched, extract_findings
from evals._harness.scorer import Attempt, classify_attempt
from evals._harness.transcript import Transcript, parse_transcript

_VALID_MODES = {"subagent", "inline"}
_NO_SKILL_INSTRUCTION = "Do not invoke any skill while completing this task."


class CaseContractError(ValueError):
    """A case directory violates the case-directory contract."""


class AcceptanceLeakError(CaseContractError):
    """A case's prompt embeds text from its private ``acceptance.md``."""


class PromptPathError(CaseContractError):
    """``case.toml``'s ``prompt`` names a file the dispatcher must not read."""


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
    """Parse and minimally validate *case_dir*'s ``case.toml``.

    Raises
    ------
    CaseContractError
        If ``mode`` is not the string ``"subagent"`` or ``"inline"``, if
        ``prompt`` is not a non-empty string, or if an ``[[items]]`` table
        lacks a string ``id`` or ``scorer`` or has a non-table ``params``.
    """
    case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
    mode = case_toml.get("mode")
    if not isinstance(mode, str) or mode not in _VALID_MODES:
        raise CaseContractError(
            f"{case_dir}: case.toml 'mode' must be one of {sorted(_VALID_MODES)}, got {mode!r}"
        )
    prompt = case_toml.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise CaseContractError(f"{case_dir}: case.toml must set a non-empty 'prompt' file name")
    items = case_toml.get("items", [])
    if not isinstance(items, list):
        raise CaseContractError(f"{case_dir}: case.toml 'items' must be an array of tables")
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise CaseContractError(f"{case_dir}: items[{position}] is not a table")
        for key in ("id", "scorer"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise CaseContractError(
                    f"{case_dir}: items[{position}] must set a non-empty string {key!r}"
                )
        if not isinstance(item.get("params", {}), dict):
            raise CaseContractError(f"{case_dir}: items[{position}] 'params' must be a table")
    return case_toml


_LIST_MARKER = re.compile(r"^(?:[-*+>]|\d+[.)])\s+")
_MIN_SUBSTRING_LEAK_CHARS = 24


def _normalize_line(line: str) -> str:
    """Collapse whitespace and drop one leading list/quote marker."""
    return _LIST_MARKER.sub("", " ".join(line.split()))


def _assert_no_acceptance_leak(case_dir: Path, text: str) -> None:
    """Raise ``AcceptanceLeakError`` if *text* carries any line of ``acceptance.md``.

    The comparison is per whole line, on whitespace- and bullet-normalised
    text, so a single leaked criterion is caught, not only a verbatim copy of
    the whole file. A line leaks when it equals a line of *text*, or (for
    lines of at least 24 characters) appears anywhere inside it. Lines with
    no letter or digit (rules, fences, bare bullets) carry no content and are
    ignored. ``acceptance.md`` is read here only to compare against; its text
    is never returned or interpolated.
    """
    acceptance_path = case_dir / "acceptance.md"
    if not acceptance_path.is_file():
        return
    text_lines = {_normalize_line(line) for line in text.splitlines()}
    flattened = " ".join(text.split())
    for number, raw_line in enumerate(
        acceptance_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = _normalize_line(raw_line)
        if not any(char.isalnum() for char in line):
            continue
        embedded = len(line) >= _MIN_SUBSTRING_LEAK_CHARS and line in flattened
        if line in text_lines or embedded:
            raise AcceptanceLeakError(
                f"{case_dir}: line {number} of acceptance.md appears in the dispatched "
                "prompt; acceptance.md is scorer-only and must never reach an agent"
            )


def _prompt_path(case_dir: Path, case_toml: dict) -> Path:
    """Resolve ``case.toml``'s ``prompt`` to a file inside *case_dir*.

    Raises
    ------
    PromptPathError
        If the path resolves (symlinks and ``..`` included) outside
        *case_dir*, names ``acceptance.md``, or is not an existing file.
    """
    prompt_name = case_toml["prompt"]
    root = case_dir.resolve()
    resolved = (case_dir / prompt_name).resolve()
    if not resolved.is_relative_to(root):
        raise PromptPathError(f"{case_dir}: prompt {prompt_name!r} resolves outside the case directory")
    if resolved == (root / "acceptance.md").resolve():
        raise PromptPathError(f"{case_dir}: prompt {prompt_name!r} names acceptance.md")
    if not resolved.is_file():
        raise PromptPathError(f"{case_dir}: prompt file {prompt_name!r} does not exist")
    return resolved


def _prompt_text(case_dir: Path, case_toml: dict) -> str:
    text = _prompt_path(case_dir, case_toml).read_text(encoding="utf-8")
    _assert_no_acceptance_leak(case_dir, text)
    return text


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
    except Exception as exc:
        raise CaseContractError(
            f"{case_dir}: predicates.py failed to import: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    return module


def _resolve_scorers(case_dir: Path, items: list[dict]) -> dict[str, Callable]:
    """Map every item id to its scorer function, or raise naming the defect."""
    if not items:
        return {}
    module = _load_predicates(case_dir)
    if module is None:
        raise CaseContractError(
            f"{case_dir}: case.toml declares items but the case has no predicates.py"
        )
    scorers: dict[str, Callable] = {}
    for item in items:
        scorer = getattr(module, item["scorer"], None)
        if not callable(scorer):
            raise CaseContractError(
                f"{case_dir}: item {item['id']!r} names scorer {item['scorer']!r}, which "
                "predicates.py does not define as a function"
            )
        scorers[item["id"]] = scorer
    return scorers


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
        verbatim. Never interpolates ``acceptance.md``.

    Raises
    ------
    AcceptanceLeakError
        If the prompt embeds any line of the case's ``acceptance.md``.
    """
    case_toml = _case_toml(case_dir)
    text = _prompt_text(case_dir, case_toml)
    _assert_no_acceptance_leak(case_dir, text)
    return text


def _remove_skill_references(text: str, skill: str) -> str:
    """Remove every whole-token reference to *skill* from *text*, keeping the rest.

    A reference is the skill name as a whole token (never a substring of a
    longer word: ``commit`` does not match ``commitment``), matched case
    insensitively, together with any namespace or path prefix glued to it
    (``/workbench:``, ``plugins/workbench/skills/``), any path suffix
    (``/SKILL.md``), a leading ``the`` and a trailing ``skill``. Only the
    reference is removed, never the line it sits on, so the task text
    around it survives.
    """
    segment = r"[\w@-]+(?:\.[\w@-]+)*"
    reference = re.compile(
        rf"(?:(?<![\w-])the[ \t]+)?"
        rf"(?<![\w-])(?:/?{segment}[/:])*{re.escape(skill)}(?![\w-])"
        rf"(?:/{segment})*/?"
        rf"(?:[ \t]+skill\b)?",
        re.IGNORECASE,
    )
    removed = reference.sub("", text)
    removed = re.sub(r"[ \t]+([:,;.!?])", r"\1", removed)
    return re.sub(r"[ \t]{2,}", " ", removed)


def build_no_skill_prompt(case_dir: Path) -> str:
    """Return the no-skill arm's prompt text.

    Parameters
    ----------
    case_dir : Path
        The case's ``evals/<skill>/<case>/`` directory.

    Returns
    -------
    str
        The same prompt text as ``build_dispatch_prompt``, with every
        reference to the rostered skill (``case_dir.parent.name``) removed
        (the reference only, never the line around it), and a fixed
        do-not-invoke-any-skill instruction appended.

    Raises
    ------
    AcceptanceLeakError
        If the prompt embeds any line of the case's ``acceptance.md``.
    """
    case_toml = _case_toml(case_dir)
    prompt_text = _prompt_text(case_dir, case_toml)
    stripped = _remove_skill_references(prompt_text, case_dir.parent.name).rstrip("\n")
    output = f"{stripped}\n\n{_NO_SKILL_INSTRUCTION}\n"
    _assert_no_acceptance_leak(case_dir, output)
    return output


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
    # ``errors="replace"``: a stray non-UTF-8 file (a ``.DS_Store``, a copied
    # binary) must not crash a re-score; it loads as replacement-character text.
    return {
        path.name: path.read_text(encoding="utf-8", errors="replace")
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
    CaseContractError
        If ``dest`` is a symlink or already holds a symlink at a name the
        snapshot would write (the snapshot never writes through a link), or if
        the case's ``predicates.py`` ``end_state`` function returns anything
        but a ``{name: text}`` mapping of strings, a name that is not a plain
        file name (empty, ``"."``/``".."``, containing a path separator or a
        NUL), or the name ``tests.md`` in any letter case. Every name is
        validated before any file is written.
    """
    if dest.is_symlink():
        raise CaseContractError(f"{case_dir}: snapshot dest {dest} is a symlink")
    dest.mkdir(parents=True, exist_ok=True)
    module = _load_predicates(case_dir)
    end_state_fn = getattr(module, "end_state", None) if module is not None else None
    if end_state_fn is None:
        return
    transcripts = [parse_transcript(path) for path in transcript_paths]
    snapshot = end_state_fn(workdir, case_dir, transcripts)
    if not isinstance(snapshot, dict):
        raise CaseContractError(f"{case_dir}: end_state must return a dict of name -> text")
    for name, text in snapshot.items():
        _check_snapshot_name(case_dir, name)
        if not isinstance(text, str):
            raise CaseContractError(f"{case_dir}: end_state text for {name!r} is not a string")
        if (dest / name).is_symlink():
            raise CaseContractError(f"{case_dir}: {dest / name} is a symlink; refusing to write")
    for name, text in snapshot.items():
        (dest / name).write_text(text, encoding="utf-8")


def _check_snapshot_name(case_dir: Path, name: object) -> None:
    unsafe = (
        not isinstance(name, str)
        or not name
        or name in (".", "..")
        or any(separator in name for separator in ("/", "\\", "\0"))
    )
    if unsafe:
        raise CaseContractError(f"{case_dir}: end_state returned an unsafe file name {name!r}")
    if name.casefold() == "tests.md":
        raise CaseContractError(f"{case_dir}: end_state may not write a file named tests.md")


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
        The skill's gated item ids, read by the conductor from the skill's
        ``checks.manifest`` and passed whole. The manifest is per skill, so
        the set routinely names items that belong to sibling cases; ids this
        case does not declare are ignored, and every item this case declares
        is scored regardless.
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
    CaseContractError
        If ``case.toml`` is malformed, the case has items but no
        ``predicates.py``, or an item names a scorer ``predicates.py`` does
        not define as a function. Checked before the transcripts are
        consulted, so a case defect is never disguised as harness breakage.
    """
    case_toml = _case_toml(case_dir)
    items = case_toml.get("items", [])
    # Resolved before anything else so a broken case surfaces as itself, never
    # disguised as harness breakage (which would burn a reserve draw).
    scorers = _resolve_scorers(case_dir, items)
    # ``gated_ids`` is the skill-wide manifest set, so it routinely names items
    # that live in sibling cases; nothing here depends on it. Gating applies
    # downstream, in ``compute_verdict``'s per-item ``gated`` flag.

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
        item_hits = {
            item["id"]: bool(scorers[item["id"]](evidence, **item.get("params", {})))
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


def find_invalid_modes(case_dirs: Iterable[Path]) -> list[tuple[Path, str]]:
    """Return every case whose ``case.toml`` does not declare a valid ``mode``.

    The committed-case test and its synthetic counterparts both call this, so a
    defect in the rule is caught by the synthetic cases, not only by a scan of
    ``evals/``.

    Parameters
    ----------
    case_dirs : Iterable[Path]
        Case directories (each holding a ``case.toml``) to check.

    Returns
    -------
    list[tuple[Path, str]]
        ``(case_dir, problem)`` for each case whose ``case.toml`` is
        unreadable, unparseable, or whose ``mode`` is missing or not the string
        ``"subagent"`` / ``"inline"``. Empty when every case is valid.
    """
    problems: list[tuple[Path, str]] = []
    for case_dir in case_dirs:
        try:
            case_toml = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            problems.append((case_dir, f"case.toml unreadable: {exc}"))
            continue
        mode = case_toml.get("mode")
        if not isinstance(mode, str) or mode not in _VALID_MODES:
            problems.append((case_dir, f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}"))
    return problems


def find_duplicate_item_ids(skill_dir: Path) -> set[str]:
    """Return every ``[[items]]`` id declared more than once under *skill_dir*.

    Item ids share one namespace per skill, because ``checks.manifest`` is per
    skill: an id repeated across two cases (or inside one) is ambiguous.

    Parameters
    ----------
    skill_dir : Path
        A skill's ``evals/<skill>/`` directory; every ``*/case.toml`` under it
        is read.

    Returns
    -------
    set[str]
        The ids that appear more than once; empty when all are unique.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case_toml_path in sorted(skill_dir.glob("*/case.toml")):
        case_toml = tomllib.loads(case_toml_path.read_text(encoding="utf-8"))
        for item in case_toml.get("items", []):
            item_id = item["id"]
            if item_id in seen:
                duplicates.add(item_id)
            seen.add(item_id)
    return duplicates
