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
    empty otherwise. Validates every returned name before writing any, and
    never writes a ``tests.md`` or through a symlink.

``score_attempt(case_dir, transcript_paths, workdir, gated_ids, transcript_status=None, end_state_dir=None) -> tuple[Attempt, int]``
    Parses every transcript, builds ``Evidence``, runs every item's scorer,
    and returns #991's ``classify_attempt`` result plus the trend unmatched-
    finding count (0 for a case without ``envelope = "findings"``).
    ``transcript_status`` defaults to the worst status among the parsed
    transcripts; the conductor overrides it with ``"dispatch_error"`` when an
    attempt never produced a transcript at all.

``find_invalid_modes(case_dirs)`` / ``find_duplicate_item_ids(skill_dir)``
    The ``mode`` and per-skill item-id rules the tests apply to committed
    cases and to synthetic ones alike.

Every case-contract violation raises ``CaseContractError`` (a ``ValueError``);
``AcceptanceLeakError`` and ``PromptPathError`` are its subclasses.

This module only imports #991's ``scorer.py``, #992's ``matchers.py`` and
``transcript.py`` — it never edits them, and it never reads
``evals/<skill>/checks.manifest`` itself (the conductor derives ``gated_ids``
from that file and passes the set in).
"""

from __future__ import annotations

import functools
import importlib.util
import re
import sys
import tomllib
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from evals._harness.matchers import count_unmatched, extract_findings
from evals._harness.scorer import Attempt, classify_attempt
from evals._harness.transcript import Transcript, parse_transcript

_VALID_MODES = {"subagent", "inline"}
# Mirrors ``calibration._VALID_KINDS`` and ``activation._ID_PATTERN``; a test pins
# both against the siblings so they cannot drift.
_ITEM_KINDS = {"gate-candidate", "triggering", "trend"}
_ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROMPT_SUFFIXES = {".md", ".txt"}
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
        ``prompt`` is not a non-empty string, if ``envelope`` is set to
        anything but ``"findings"``, or if an ``[[items]]`` table lacks a
        string ``id`` (matching the id grammar, unique within the case),
        ``scorer`` or known ``kind``, or has a non-table ``params``.
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
        if not _ITEM_ID.match(item["id"]):
            raise CaseContractError(
                f"{case_dir}: items[{position}] id {item['id']!r} does not match {_ITEM_ID.pattern}"
            )
        if item.get("kind") not in _ITEM_KINDS:
            raise CaseContractError(
                f"{case_dir}: item {item['id']!r} kind must be one of {sorted(_ITEM_KINDS)}, "
                f"got {item.get('kind')!r}"
            )
        if not isinstance(item.get("params", {}), dict):
            raise CaseContractError(f"{case_dir}: items[{position}] 'params' must be a table")
    ids = [item["id"] for item in items]
    repeated = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if repeated:
        raise CaseContractError(f"{case_dir}: item id(s) {repeated} are declared more than once")
    if case_toml.get("envelope", "findings") != "findings":
        raise CaseContractError(
            f"{case_dir}: case.toml 'envelope' may only be \"findings\", got "
            f"{case_toml['envelope']!r}"
        )
    return case_toml


# A leak is a run of at least this many consecutive tokens shared between the
# prompt and acceptance.md. Below it, shared words are boilerplate ("Context",
# "Steps:", a "```python" fence, "Done.") and never count.
LEAK_MIN_TOKENS = 4

# Words that make up generic headings and boilerplate. A line made only of these
# never counts as a leak however long it is.
_GENERIC_TOKENS = frozenset(
    "acceptance criteria context steps step done notes note summary overview task tasks goal "
    "goals background requirements requirement expected result results output input example "
    "examples description setup instructions checklist details section the a an and or of for "
    "to in is are".split()
)

_LINE_PREFIX = re.compile(r"^\s*(?:(?:[-*+>]|#{1,6}|\d+[.)])\s+|\[[ xX]\]\s*)+")
_TOKEN = re.compile(r"[^\W_]+")


def _tokens(text: str) -> list[str]:
    """Casefolded NFKC alphanumeric tokens of *text*, ignoring markdown and invisibles.

    Format characters (zero-width spaces, joiners) are dropped before
    tokenising, so they cannot split a word; every other non-alphanumeric
    character, markdown syntax and quote style included, is only a separator.
    """
    normalized = unicodedata.normalize("NFKC", text).casefold()
    visible = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    return _TOKEN.findall(visible)


def _line_tokens(line: str) -> list[str]:
    return _tokens(_LINE_PREFIX.sub("", line))


def _countable(tokens: list[str]) -> bool:
    return len(tokens) >= LEAK_MIN_TOKENS and not set(tokens) <= _GENERIC_TOKENS


def _windows(lines: list[list[str]]) -> list[tuple[int, list[str]]]:
    """Each countable token window of *lines*, as ``(line number, tokens)``.

    A line of at least ``LEAK_MIN_TOKENS`` tokens is its own window. A shorter
    one is widened with the following consecutive lines until the window
    reaches that many tokens, so a terse list ("Tests pass" / "No
    regressions" / ...) cannot hide by being short line by line. A window that
    never reaches the threshold, or is made only of generic words, is dropped.
    """
    windows: list[tuple[int, list[str]]] = []
    for index, tokens in enumerate(lines):
        if not tokens:
            continue
        window = list(tokens)
        following = index + 1
        while len(window) < LEAK_MIN_TOKENS and following < len(lines):
            window.extend(lines[following])
            following += 1
        if _countable(window):
            windows.append((index + 1, window))
    return windows


def _haystack(stream: list[str]) -> str:
    """The token stream as one NUL-delimited string, searchable in linear time."""
    return "\0" + "\0".join(stream) + "\0"


def _contains_run(haystack: str, run: list[str]) -> bool:
    return "\0" + "\0".join(run) + "\0" in haystack


def _read_acceptance(case_dir: Path) -> str | None:
    acceptance_path = case_dir / "acceptance.md"
    if not acceptance_path.is_file():
        return None
    try:
        return acceptance_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CaseContractError(
            f"{case_dir}: acceptance.md is unreadable ({type(exc).__name__}); cannot prove the "
            "prompt does not leak it"
        ) from exc


def find_acceptance_leaks(case_dir: Path, text: str) -> list[str]:
    """Return a description of every way *text* carries ``acceptance.md``'s content.

    Both directions are checked on token lists (see ``_tokens``), with the
    lines of each side joined first so a re-wrapped line is still caught: a
    prompt line that is a contiguous piece of acceptance.md's token stream,
    and an acceptance line found anywhere in the prompt's token stream. A line
    needs ``LEAK_MIN_TOKENS`` tokens; a shorter one is widened with the
    following lines until it has them (so a terse pasted list is caught), and
    a line that never gets there, generic-word headings, fences and
    punctuation-only lines never count (a sole line like "All tests pass." is
    too generic to flag). ``acceptance.md`` is read here only to compare; its text is never
    returned.

    Parameters
    ----------
    case_dir : Path
        The case directory, which may hold an ``acceptance.md``.
    text : str
        Prompt text about to be dispatched.

    Returns
    -------
    list[str]
        One description per leak (line numbers, no acceptance text); empty
        when there is no ``acceptance.md`` or nothing leaks.

    Raises
    ------
    CaseContractError
        If ``acceptance.md`` exists but cannot be read as UTF-8 text.
    """
    acceptance = _read_acceptance(case_dir)
    if acceptance is None:
        return []
    acceptance_lines = [_line_tokens(line) for line in acceptance.splitlines()]
    prompt_lines = [_line_tokens(line) for line in text.splitlines()]
    acceptance_haystack = _haystack([token for tokens in acceptance_lines for token in tokens])
    prompt_haystack = _haystack([token for tokens in prompt_lines for token in tokens])
    leaks: list[str] = []
    for number, window in _windows(prompt_lines):
        if _contains_run(acceptance_haystack, window):
            leaks.append(f"prompt line {number} reproduces acceptance.md")
    for number, window in _windows(acceptance_lines):
        if _contains_run(prompt_haystack, window):
            leaks.append(f"acceptance.md line {number} appears in the prompt")
    return leaks


def _assert_no_acceptance_leak(case_dir: Path, text: str) -> None:
    """Raise ``AcceptanceLeakError`` if *text* carries acceptance.md's content."""
    leaks = find_acceptance_leaks(case_dir, text)
    if leaks:
        raise AcceptanceLeakError(
            f"{case_dir}: {'; '.join(leaks)}; acceptance.md is scorer-only and must never "
            "reach an agent"
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
    for candidate in (Path(prompt_name), resolved):
        if candidate.suffix.casefold() not in _PROMPT_SUFFIXES:
            raise PromptPathError(
                f"{case_dir}: prompt {prompt_name!r} must be a .md or .txt file; case.toml, "
                "predicates.py, provenance.toml and calibration.json hold scorer material"
            )
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


_PATH_SEGMENT = r"\.?[\w@-]+(?:\.[\w@-]+)*"


@functools.cache
def _plugin_namespaces() -> tuple[str, ...]:
    """Plugin names a skill can be namespaced under (``workbench:commit``)."""
    plugins_dir = Path(__file__).resolve().parents[2] / "plugins"
    found = {path.name for path in plugins_dir.iterdir() if path.is_dir()} if plugins_dir.is_dir() else set()
    return tuple(sorted(found | {"workbench"}))


def _skill_reference_pattern(skill: str) -> re.Pattern[str]:
    """Match the unambiguous ways a prompt can *name the rostered skill*.

    Only these forms count, because a skill is often named like an ordinary
    word or directory (``commit``, ``tdd``): ``skills/<name>/...`` and
    ``plugins/<ns>/skills/<name>/...`` paths; ``/<ns>:<name>`` and
    ``<plugin>:<name>`` (a bare ``scope:commit`` is not a skill); the
    ``/<name>`` slash form at a token start (not ``~/commit`` or
    ``--dir=/commit``); the phrases ``the <name> skill``, ``<name> skill`` and
    ``<Name>-Skill``; ``skill=<name>``, ``"skill": "<name>"``,
    ``Skill(<name>)``, ``Skill(skill: <name>)`` and ``Skill: <name>``;
    ``the skill called|named <name>``; and ``the Skill tool with <name>``. The
    name may sit in quotes or backticks in the phrase and keyword forms. A
    hyphenated name (``adversarial-review``) is never an ordinary word, so it
    is also matched bare, unless it sits inside a path. Every form needs a
    left word boundary, so ``recommit`` never matches ``commit``.
    """
    name = re.escape(skill)
    quote = r"[\"'`]?"
    quoted = rf"{quote}{name}{quote}"
    no_left = r"(?<![\w@./:=~-])"
    the = r"(?:(?<![\w-])the[ \t]+)?"
    namespaces = "|".join(re.escape(namespace) for namespace in _plugin_namespaces())
    forms = [
        rf"(?<![\w@./-])(?:/?{_PATH_SEGMENT}/)*skills/{name}(?![\w-])(?:/{_PATH_SEGMENT})*/?",
        rf"{no_left}/{_PATH_SEGMENT}:{name}(?![\w-])(?!/)",
        rf"{no_left}(?:{namespaces}):{name}(?![\w-])(?!/)",
        rf"{no_left}/{name}(?![\w-])(?!/)(?!\.\w)",
        rf"{the}{no_left}{quoted}[ \t]+skill\b",
        rf"{the}{no_left}{name}-skill(?![\w-])",
        rf"\bskill[ \t]*=[ \t]*{quoted}(?![\w-])",
        rf"[\"']skill[\"'][ \t]*:[ \t]*[\"']{name}[\"']",
        rf"\bSkill\([ \t]*(?:skill[ \t]*[:=][ \t]*)?{quoted}[ \t]*\)",
        rf"\bSkill:[ \t]*{quoted}(?![\w-])",
        rf"{the}\bskill[ \t]+(?:called|named)[ \t]+{quoted}(?![\w-])",
        rf"{the}\bSkill[ \t]+tool[ \t]+with[ \t]+{quoted}(?![\w-])",
    ]
    if "-" in skill:
        forms.append(rf"{no_left}{name}(?![\w-])(?!/)(?!\.\w)")
    return re.compile("|".join(forms), re.IGNORECASE)


def _remove_skill_references(text: str, skill: str) -> str:
    """Remove every unambiguous reference to *skill* from *text*, keeping the rest.

    Only the reference is removed, never the line it sits on, so the task
    text around it survives; spacing left behind is tidied.
    """
    removed = _skill_reference_pattern(skill).sub("", text)
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
        do-not-invoke-any-skill instruction appended. Only the unambiguous
        reference forms listed in ``_skill_reference_pattern`` are removed;
        bare ordinary words (``commit``, ``tdd``) and unrelated path
        segments (``src/commit/``) are left alone.

    Raises
    ------
    AcceptanceLeakError
        If the prompt embeds any line of the case's ``acceptance.md``.
    CaseContractError
        If the prompt is nothing but a reference to the skill, so removing it
        leaves no task.
    """
    case_toml = _case_toml(case_dir)
    prompt_text = _prompt_text(case_dir, case_toml)
    skill = case_dir.parent.name
    if prompt_text.strip().casefold() == skill.casefold():
        stripped = ""
    else:
        stripped = _remove_skill_references(prompt_text, skill).strip()
    if not stripped:
        raise CaseContractError(
            f"{case_dir}: the prompt is nothing but a reference to the skill {skill!r}, so "
            "removing it leaves no task for the no-skill arm"
        )
    _assert_no_acceptance_leak(case_dir, stripped)
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
        If ``dest`` is a symlink or already holds any file (each attempt
        snapshots into its own fresh ``end_state/``, so stale evidence from an
        earlier snapshot never mixes in), or if
        the case's ``predicates.py`` ``end_state`` function returns anything
        but a ``{name: text}`` mapping of strings, a name that is not a plain
        file name (empty, ``"."``/``".."``, containing a path separator or a
        NUL), or the name ``tests.md`` in any letter case. Every name is
        validated before any file is written.
    """
    if dest.is_symlink():
        raise CaseContractError(f"{case_dir}: snapshot dest {dest} is a symlink")
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise CaseContractError(
            f"{case_dir}: snapshot dest {dest} is not empty; each attempt snapshots into its "
            "own fresh end_state/ directory, so stale files cannot pass for this attempt's evidence"
        )
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


def _run_scorer(case_dir: Path, item: dict, scorer: Callable, evidence: Evidence) -> bool:
    try:
        return bool(scorer(evidence, **item.get("params", {})))
    except Exception as exc:
        raise CaseContractError(
            f"{case_dir}: scorer {item['scorer']!r} for item {item['id']!r} raised "
            f"{type(exc).__name__}: {exc}"
        ) from exc


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
        ``None`` (the default) derives the status from *transcript_paths*:
        the first non-complete transcript's status, ``"missing"`` when there
        are none. The only override is ``"dispatch_error"``, which the
        conductor passes when an attempt never produced a transcript at all;
        any other value is refused, because a real attempt's status comes
        from its transcripts. Scorers run only for a complete attempt that
        has transcripts.
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
        If *transcript_status* is neither ``None`` nor ``"dispatch_error"``.
    CaseContractError
        If a scorer or the unmatched-finding count raises (naming the case
        and item), if ``case.toml`` is malformed, the case has items but no
        ``predicates.py``, or an item names a scorer ``predicates.py`` does
        not define as a function. Checked before the transcripts are
        consulted, so a case defect is never disguised as harness breakage.
    """
    if transcript_status not in (None, "dispatch_error"):
        raise ValueError(
            f"transcript_status may only be None or 'dispatch_error' (the status of a real "
            f"attempt is derived from its transcripts), got {transcript_status!r}"
        )
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
            item["id"]: _run_scorer(case_dir, item, scorers[item["id"]], evidence)
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
        try:
            unmatched = count_unmatched(findings, review_item_params)
        except Exception as exc:
            raise CaseContractError(
                f"{case_dir}: counting unmatched findings failed ({type(exc).__name__}: {exc}); "
                "check the review items' file_suffix/regex params"
            ) from exc
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

    Raises
    ------
    CaseContractError
        If a case's ``case.toml`` cannot be parsed or an item has no string
        ``id``; the error names the case.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case_toml_path in sorted(skill_dir.glob("*/case.toml")):
        case_name = case_toml_path.parent.name
        try:
            case_toml = tomllib.loads(case_toml_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise CaseContractError(f"{case_toml_path}: case.toml unreadable: {exc}") from exc
        items = case_toml.get("items", [])
        if not isinstance(items, list):
            raise CaseContractError(f"{case_name}: case.toml 'items' must be an array of tables")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise CaseContractError(f"{case_name}: an [[items]] table has no string 'id'")
            item_id = item["id"]
            if item_id in seen:
                duplicates.add(item_id)
            seen.add(item_id)
    return duplicates


def discover_case_dirs(evals_root: Path) -> list[Path]:
    """Return every ``<evals_root>/<skill>/<case>/`` directory that holds a ``case.toml``.

    Skill directories whose name starts with ``_`` (the ``_harness`` package)
    are skipped, and so is anything nested deeper than a case (a fixture
    tree's own ``case.toml``, a ``runs/`` raw directory).

    Parameters
    ----------
    evals_root : Path
        The ``evals/`` directory.

    Returns
    -------
    list[Path]
        The case directories, sorted.
    """
    return sorted(
        path.parent
        for path in evals_root.glob("*/*/case.toml")
        if not path.parent.parent.name.startswith("_")
    )


def discover_skill_dirs(evals_root: Path) -> list[Path]:
    """Return every skill directory under *evals_root*, skipping ``_``-prefixed ones.

    Parameters
    ----------
    evals_root : Path
        The ``evals/`` directory.

    Returns
    -------
    list[Path]
        The ``evals/<skill>/`` directories, sorted. A skill with no cases yet
        is still a skill.
    """
    return sorted(
        path
        for path in evals_root.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    )
