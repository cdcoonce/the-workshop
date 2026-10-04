"""Conjunctive review matching and ordering predicates over a parsed transcript.

Public contract
----------------
``review_match(finding, *, file_suffix, regex, line_window) -> bool``
    A gated review item requires BOTH its location (a line window, or a
    file-suffix-only match when there is no window) AND its regex to hit. A
    match on only one never credits the item — this retires the disjunctive
    ``in_window or regex.search(...)`` rule from the terse-lens-contract A/B
    experiment's ``score_arm.py``.

``extract_findings(final_text) -> (findings, ok)``
    Pulls the ``findings`` list out of the first JSON object in the agent's
    final reply that has one. ``ok`` is ``False`` (with an empty list) when
    no such object parses.

``count_unmatched(findings, items) -> int``
    Trend count of findings that credit no item; never gates a verdict.

``precedes(events, first, then) -> bool``
    Generic ordering predicate: ``True`` iff some event satisfying ``first``
    has an ordinal strictly below the first event satisfying ``then``.
    Hard-codes no event kind.

``test_failed_before_first_source_edit(events) -> bool``
    Ordering predicate instance: a test failed before the first source-file
    edit.

``classify_bash_command(command) -> "none" | "tests" | "source"``
    Fail-closed reading of a Bash command's text. ``none`` only when no write
    indicator is found; ``tests`` only when a write indicator is found, the call
    names a tests path, and ``src`` appears nowhere in it; ``source`` otherwise.
    See ``classify_bash_command`` for the indicators and their limits.

``bash_write_offset(command) -> int | None``
    Where the first write indicator starts, for a caller ordering a write against
    a later word in the same command.

``classify_write_event(event) -> "none" | "tests" | "source"``
    ``classify_bash_command`` for a ``Bash`` event; a path-segment rule for an
    ``Edit``/``Write``/``NotebookEdit``/``MultiEdit`` event.

``test_failed_before_first_source_write(events) -> bool``
    The ordering predicate of ``test_failed_before_first_source_edit`` built on
    those classifications: a red result written for by a test write at or before
    it, strictly before the first source write. The old predicate keeps its
    Edit/Write-only meaning.

``skill_triggered_first(transcript, skill) -> bool``
    Triggering predicate: the rostered skill's ``Skill`` call precedes every
    other tool call (except ``Skill``/``ToolSearch`` calls) and the final
    assistant text block.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from evals._harness.transcript import ToolCallEvent, Transcript

_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_SOURCE_EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
_TRIGGERING_EXEMPT_TOOLS = ("Skill", "ToolSearch")


def review_match(
    finding: dict,
    *,
    file_suffix: str,
    regex: str,
    line_window: list[int] | None,
) -> bool:
    """Decide whether a finding credits a gated review item.

    Parameters
    ----------
    finding : dict
        A parsed finding with ``file``, ``line``, and ``description`` keys.
    file_suffix : str
        The item's file, matched with ``str.endswith``.
    regex : str
        Pattern matched (case-insensitively) against the finding's
        description.
    line_window : list[int] | None
        ``[start, end]`` inclusive line range for a line-level item; ``None``
        for a file-level item, where location is satisfied by the file
        suffix alone.

    Returns
    -------
    bool
        ``True`` only when both the location and the regex hit.
    """
    file_str = str(finding.get("file", ""))
    description = str(finding.get("description", ""))
    regex_hit = bool(re.search(regex, description, re.IGNORECASE))

    if line_window is None:
        location_hit = file_str.endswith(file_suffix)
    elif not file_str.endswith(file_suffix):
        location_hit = False
    else:
        line = finding.get("line")
        location_hit = isinstance(line, (int, float)) and not isinstance(line, bool) and (
            line_window[0] <= line <= line_window[1]
        )

    return location_hit and regex_hit


def extract_findings(final_text: str) -> tuple[list[dict], bool]:
    """Pull the ``findings`` list from the first JSON object in ``final_text``.

    Tries a fenced ```json block first, then the span from the first ``{``
    to the last ``}``.

    Parameters
    ----------
    final_text : str
        The agent's final reply text.

    Returns
    -------
    tuple[list[dict], bool]
        ``(findings, True)`` for the first candidate that parses and holds a
        ``findings`` list; ``([], False)`` when none does.
    """
    candidates = list(_FENCED_JSON.findall(final_text))
    brace_start = final_text.find("{")
    if brace_start != -1:
        candidates.append(final_text[brace_start : final_text.rfind("}") + 1])

    for candidate in candidates:
        try:
            envelope = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, dict):
            continue
        findings = envelope.get("findings")
        if isinstance(findings, list):
            return [f for f in findings if isinstance(f, dict)], True
    return [], False


def count_unmatched(findings: list[dict], items: list[dict]) -> int:
    """Count findings that credit no item (a trend field; never gates).

    Parameters
    ----------
    findings : list[dict]
        Findings extracted by ``extract_findings``.
    items : list[dict]
        Item specs, each with ``file_suffix``, ``regex``, and
        ``line_window`` keys matching ``review_match``'s parameters.

    Returns
    -------
    int
        How many findings match no item.
    """
    unmatched = 0
    for finding in findings:
        if not any(
            review_match(
                finding,
                file_suffix=item["file_suffix"],
                regex=item["regex"],
                line_window=item.get("line_window"),
            )
            for item in items
        ):
            unmatched += 1
    return unmatched


def precedes(
    events: list[ToolCallEvent],
    first: Callable[[ToolCallEvent], bool],
    then: Callable[[ToolCallEvent], bool],
) -> bool:
    """Generic ordering predicate over tool-call events.

    Parameters
    ----------
    events : list[ToolCallEvent]
        The events to search.
    first : Callable[[ToolCallEvent], bool]
        Matcher for the event that must come first.
    then : Callable[[ToolCallEvent], bool]
        Matcher for the event that must come after.

    Returns
    -------
    bool
        ``True`` iff some event satisfying ``first`` has an ordinal strictly
        below the first event satisfying ``then``. ``False`` if either never
        occurs.
    """
    first_ordinals = [event.ordinal for event in events if first(event)]
    then_ordinals = [event.ordinal for event in events if then(event)]
    if not first_ordinals or not then_ordinals:
        return False
    return min(first_ordinals) < min(then_ordinals)


def _is_test_path(file_path: str) -> bool:
    parts = file_path.split("/")
    name = parts[-1] if parts else file_path
    if name == "conftest.py":
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return "tests" in parts


def _is_source_edit(event: ToolCallEvent) -> bool:
    if event.name not in _SOURCE_EDIT_TOOLS:
        return False
    file_path = event.input.get("file_path", "") if isinstance(event.input, dict) else ""
    return not _is_test_path(str(file_path))


def _result_text(event: ToolCallEvent) -> str:
    if event.result is None:
        return ""
    content = event.result.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return "" if content is None else str(content)


def _is_test_failure(event: ToolCallEvent) -> bool:
    if event.name != "Bash":
        return False
    text = _result_text(event)
    if "error during collection" in text:
        return True
    return any(line.startswith("FAILED ") or line.startswith("ERROR ") for line in text.splitlines())


def test_failed_before_first_source_edit(events: list[ToolCallEvent]) -> bool:
    """Ordering predicate: a new/changed test failed before the first source edit.

    A source-edit event is an ``Edit``/``Write``/``NotebookEdit`` call whose
    ``input.file_path`` is not a test-file path (``test_*.py``, ``*_test.py``,
    ``conftest.py``, or any path with a ``tests/`` segment). A test-failure
    event is a ``Bash`` call whose matched result content contains a pytest
    failure marker (a line starting ``FAILED `` or ``ERROR ``, or the
    substring ``error during collection``).

    Parameters
    ----------
    events : list[ToolCallEvent]
        The transcript's tool-call events.

    Returns
    -------
    bool
        ``True`` only when a test-failure event's ordinal is strictly below
        the first source-edit event's ordinal. ``False`` (not indeterminate)
        when either kind never occurs — indeterminate is reserved for
        harness breakage, decided by the caller from ``Transcript.status``.
    """
    return precedes(events, _is_test_failure, _is_source_edit)


# ---------------------------------------------------------------- Bash write classification

# A command longer than this is classified "source" without being scanned (fail closed, bounded cost).
BASH_COMMAND_CAP = 100_000

_EDIT_FAMILY = ("Edit", "Write", "NotebookEdit", "MultiEdit")

# Every pattern below is a flat literal or a simple class with no nested quantifier, and the
# tokenizer is one non-backtracking alternation, so the scan is linear in the command's length.
_TOKEN = re.compile(r"[;&|\n]|[^\s;&|<>(){}\[\]`$\"'=,]+")
_SEPARATORS = frozenset(";&|\n")
# Any token that is one of these is a write (or can write): no command-position test, so a verb used
# as an argument over-counts and a verb behind sudo/env/xargs/-exec/a path is still seen.
_WRITE_VERBS = frozenset(
    {
        "mv", "cp", "rm", "rmdir", "unlink", "install", "rsync", "ln", "touch", "truncate", "dd", "patch",
        "tee", "sponge", "ed", "ex", "vi", "vim", "nvim", "wget", "tar", "unzip", "scp", "-delete",
    }
)
_GIT_WRITES = frozenset(
    {
        "apply", "restore", "stash", "rm", "mv", "clean", "am", "cherry-pick", "revert", "merge",
        "pull", "rebase", "switch", "checkout", "reset", "read-tree",
    }
)
_FORMATTERS = frozenset({"black", "isort", "autopep8", "yapf", "prettier"})
_CHECK_ONLY = frozenset({"--check", "--diff"})
# sed/perl/ruby in-place flag clusters in any spelling; a quote after the flag (-i'' or -i"") ends the token.
_IN_PLACE_CLUSTER = re.compile(r"-[A-Za-z0-9]*i[A-Za-z0-9.]*")
_CURL_OUTPUT_CLUSTER = re.compile(r"-[A-Za-z0-9]*[oO][A-Za-z0-9]*")

_SNIPPET_WRITES = re.compile(
    r"\.write\(|write_text\(|write_bytes\(|writeFile|appendFile|createWriteStream|fileinput"
    r"|O_(?:WRONLY|RDWR|CREAT|APPEND|TRUNC|EXCL)"
    r"|os\.(?:rename|replace|remove|unlink|rmdir|removedirs|truncate|makedirs|link|symlink)\("
    r"|shutil\.(?:copy\w*|move|rmtree|make_archive|unpack_archive)"
    r"|\.(?:unlink|rename|touch|rmdir|symlink_to|hardlink_to)\("
)
_OPEN_CALL = re.compile(r"open\s*\(")
_MODE = r"[rbtU]*[wax+][rwxabtU+]*"
_FIRST_ARG_MODE = re.compile(rf"\s*\\*[\"']{_MODE}\\*[\"']")
_LATER_ARG_MODE = re.compile(rf"[,=]\s*\\*[\"']{_MODE}\\*[\"']")
_OPEN_WINDOW = 200
_REDIRECT_WRITES_NOTHING = re.compile(r"[ \t]*/dev/(?:null|stderr|stdout|tty|fd/\d+)(?![\w/.-])")
_FD_DUP = re.compile(r"\d+-?|-")

_TESTS_MENTION = re.compile(r"(?<!\w)tests/|(?<![\w/-])test_[\w.-]*\.py|\w_test\.py|conftest\.py")
_SRC_TOKEN = re.compile(r"(?<!\w)src(?!\w)")


def _first_file_redirect(command: str) -> int | None:
    """Return the offset of the first ``>``/``>>`` that sends output to a file, else ``None``.

    File-descriptor duplication (``2>&1``, ``>&2``, ``>&-``), redirection to
    ``/dev/null``, ``/dev/stderr``, ``/dev/stdout``, ``/dev/tty`` or ``/dev/fd/N``,
    and ``->``, ``=>`` and ``>=`` are not file redirections. ``&>file``, ``>&file``
    and ``>|file`` are.
    """
    position = 0
    while True:
        position = command.find(">", position)
        if position == -1:
            return None
        start = position
        end = position + 1
        if position and command[position - 1] in ("-", "="):
            position = end
            continue
        if end < len(command) and command[end] == ">":
            end += 1
        if end < len(command) and command[end] == "=":
            position = end
            continue
        if end < len(command) and command[end] == "&":
            duplicate = _FD_DUP.match(command, end + 1)
            if duplicate:
                position = duplicate.end()
                continue
            return start
        if end < len(command) and command[end] == "|":
            end += 1
        if _REDIRECT_WRITES_NOTHING.match(command, end):
            position = end
            continue
        return start


def _token_write_offsets(command: str) -> list[int]:
    """Offsets of every write indicator found by reading the command word by word."""
    offsets: list[int] = []
    active: set[str] = set()
    formatter_at: int | None = None
    check_only = False

    def close_segment() -> None:
        nonlocal formatter_at, check_only
        if formatter_at is not None and not check_only:
            offsets.append(formatter_at)
        formatter_at = None
        check_only = False

    for match in _TOKEN.finditer(command):
        token = match.group()
        start = match.start()
        if token in _SEPARATORS:
            close_segment()
            continue
        word = token.rsplit("/", 1)[-1]
        if word in _WRITE_VERBS:
            offsets.append(start)
        if "inplace" in token or token == "--in-place" or token.startswith("--in-place"):
            offsets.append(start)
        if word in ("sed", "perl", "ruby", "curl", "git", "awk", "gawk", "mawk"):
            active.add(word)
        elif word in _FORMATTERS:
            formatter_at = start if formatter_at is None else formatter_at
        elif word == "ruff":
            active.add("ruff")
        if token in _CHECK_ONLY:
            check_only = True
        if "sed" in active and (_IN_PLACE_CLUSTER.fullmatch(token) or token == "--in-place"):
            offsets.append(start)
        if ("perl" in active or "ruby" in active) and _IN_PLACE_CLUSTER.fullmatch(token):
            offsets.append(start)
        if "curl" in active and (
            _CURL_OUTPUT_CLUSTER.fullmatch(token)
            or token in ("--remote-name", "--remote-name-all", "--create-dirs")
            or token.startswith("--output")
        ):
            offsets.append(start)
        if "git" in active and token in _GIT_WRITES:
            offsets.append(start)
        if "ruff" in active and (token == "format" or token.startswith("--fix") or token == "--unsafe-fixes"):
            formatter_at = start if formatter_at is None else formatter_at
    close_segment()
    return offsets


def _open_write_offset(command: str) -> int | None:
    """Offset of the first ``open(`` call whose next 200 characters carry a write/append/exclusive mode."""
    for call in _OPEN_CALL.finditer(command):
        end = call.end()
        window_end = end + _OPEN_WINDOW
        if _FIRST_ARG_MODE.match(command, end, window_end) or _LATER_ARG_MODE.search(command, end, window_end):
            return call.start()
    return None


def bash_write_offset(command: str) -> int | None:
    """Locate the first write indicator in a Bash command's text.

    Parameters
    ----------
    command : str
        The Bash tool call's ``command`` text.

    Returns
    -------
    int | None
        The smallest offset into *command* at which a write indicator starts, or
        ``None`` when none is found. A command longer than ``BASH_COMMAND_CAP`` is
        not scanned and answers ``0``. A caller ordering a write against a later
        word in the same command (a pytest run) compares offsets.
    """
    if not isinstance(command, str):
        return None
    if len(command) > BASH_COMMAND_CAP:
        return 0
    offsets = _token_write_offsets(command)
    snippet = _SNIPPET_WRITES.search(command)
    if snippet:
        offsets.append(snippet.start())
    opened = _open_write_offset(command)
    if opened is not None:
        offsets.append(opened)
    redirect = _first_file_redirect(command)
    if redirect is not None:
        offsets.append(redirect)
    return min(offsets) if offsets else None


def classify_bash_command(command: str) -> str:
    """Classify a Bash command as ``"none"``, ``"tests"`` or ``"source"``, failing closed.

    ``none`` only when the text shows no write indicator: a redirection to a file
    (not ``2>&1``, not ``>/dev/null``), ``tee``, ``sed`` with an in-place flag in any
    spelling, ``perl``/``ruby`` with a flag cluster holding ``i``, ``awk -i inplace``,
    ``ed``/``ex``/``vi``/``vim``, a python/node/ruby snippet with a write API
    (``open`` with a write, append or exclusive mode in any quoting, ``.write(``,
    ``write_text``, ``fileinput``, ``shutil.copy``/``move``, ``os.replace``/``rename``/
    ``remove``, ``Path.rename``/``unlink``/``touch`` and the like), ``curl -o``/``-O``,
    ``wget``, ``mv``, ``cp``, ``rm``, ``install``, ``rsync``, ``ln``, ``touch``,
    ``truncate``, ``dd``, ``patch``, ``git apply``/``checkout``/``restore``/``stash``/
    ``reset``/``clean``/``am``/``cherry-pick`` and the other tree-changing git verbs, or a
    formatter or fixer run without ``--check``/``--diff`` (``ruff format``,
    ``ruff check --fix``, ``black``, ``isort``, ``autopep8``, ``yapf``, ``prettier``).

    A call with an indicator is ``tests`` only when it literally names a tests path
    (``tests/…``, ``test_*.py``, ``*_test.py``, ``conftest.py``) AND ``src`` appears
    nowhere in it as a path-ish token (``\bsrc\b``: ``src/x``, ``cd src``,
    ``os.path.join('src', …)``, ``D=src``, ``find src``). Every other write is
    ``source``, including one that names neither directory. A command longer than
    ``BASH_COMMAND_CAP`` is ``source`` without being scanned.

    The only way to over-credit is a write that matches no indicator at all: a tool
    or idiom this list does not name, an in-place edit by a program that is not in
    it, or a script file that was never written through the transcript's own tools
    and is run later. A read-only call that holds a write verb as an argument, any
    ``src`` token (a heredoc body, a comment, a workdir path with a ``src`` segment),
    or a write elsewhere over-counts, which can only cost a hit.
    """
    offset = bash_write_offset(command)
    if offset is None:
        return "none"
    if len(command) > BASH_COMMAND_CAP:
        return "source"
    if _TESTS_MENTION.search(command) and not _SRC_TOKEN.search(command):
        return "tests"
    return "source"


def _is_test_basename(name: str) -> bool:
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py") or name == "conftest.py"


def _classify_edit_path(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return "none"
    directories = segments[:-1]
    if _is_test_basename(segments[-1]):
        return "tests"
    if "src" in directories:
        return "source"
    if "tests" in directories:
        return "tests"
    return "none"


def classify_write_event(event: ToolCallEvent) -> str:
    """Classify a tool-call event as ``"none"``, ``"tests"`` or ``"source"``.

    A ``Bash`` event is read by its command (``classify_bash_command``). An
    ``Edit``, ``Write``, ``NotebookEdit`` or ``MultiEdit`` event is read by its
    path's segments: a test file's basename (``test_*.py``, ``*_test.py``,
    ``conftest.py``) is ``tests``; otherwise a ``src`` directory segment makes it
    ``source`` and a ``tests`` directory segment ``tests``; a path with neither is
    ``none`` (a scratch file is not a source write). Segments, not substrings, so
    ``/work/resrc/x.py`` is ``none`` and ``/Users/x/tests/ws/src/shop/cart.py`` is
    ``source``. Every other tool is ``none``.
    """
    if not isinstance(event.input, dict):
        return "none"
    if event.name == "Bash":
        command = event.input.get("command")
        return classify_bash_command(command) if isinstance(command, str) else "none"
    if event.name in _EDIT_FAMILY:
        path = event.input.get("file_path") or event.input.get("notebook_path") or ""
        return _classify_edit_path(str(path))
    return "none"


def test_failed_before_first_source_write(events: list[ToolCallEvent]) -> bool:
    """Ordering predicate: a test, written for, failed before the first source write.

    A source write is an event ``classify_write_event`` calls ``source``; a test
    write is one it calls ``tests``. A credited red result is a ``Bash`` event with a
    pytest failure marker (as in ``test_failed_before_first_source_edit``) such that
    some test write sits at an ordinal at or below it (the same call is allowed: the
    agent appends the test and runs pytest in one Bash call) and its ordinal is
    strictly below the first source write's. A Bash call that writes the source and
    shows the red result shares one ordinal with itself, so it is not credited.

    Parameters
    ----------
    events : list[ToolCallEvent]
        The transcript's tool-call events.

    Returns
    -------
    bool
        ``True`` only when a credited red result precedes the first source write;
        ``False`` when there is no source write, no red result, or no test write
        at or before any red result that comes first.
    """
    source_ordinals = []
    test_ordinals = []
    for event in events:
        kind = classify_write_event(event)
        if kind == "source":
            source_ordinals.append(event.ordinal)
        elif kind == "tests":
            test_ordinals.append(event.ordinal)
    if not source_ordinals or not test_ordinals:
        return False
    first_source = min(source_ordinals)
    first_test = min(test_ordinals)
    return any(
        _is_test_failure(event) and first_test <= event.ordinal < first_source for event in events
    )


def skill_triggered_first(transcript: Transcript, skill: str) -> bool:
    """Triggering predicate: the rostered skill's ``Skill`` call ran first.

    Met when a ``Skill`` tool-call event naming ``skill`` has an ordinal
    position earlier than every other tool-call event in the transcript
    EXCEPT ``Skill``/``ToolSearch`` calls (the exemption applies to every
    such call, not only the rostered skill's own), and earlier than the
    ordinal position of the final assistant text block.

    Parameters
    ----------
    transcript : Transcript
        The parsed transcript.
    skill : str
        The rostered skill's name, matched against the ``Skill`` call's
        ``input["skill"]``.

    Returns
    -------
    bool
        ``True`` when met; ``False`` (unmet, not indeterminate) when no such
        ``Skill`` call occurs at all, or when it is preceded by a
        non-exempt tool call or by the final assistant text block.
    """
    skill_ordinals = [
        event.ordinal
        for event in transcript.events
        if event.name == "Skill"
        and isinstance(event.input, dict)
        and event.input.get("skill") == skill
    ]
    if not skill_ordinals:
        return False
    trigger_ordinal = min(skill_ordinals)

    other_ordinals = [
        event.ordinal for event in transcript.events if event.name not in _TRIGGERING_EXEMPT_TOOLS
    ]
    if other_ordinals and trigger_ordinal >= min(other_ordinals):
        return False

    if transcript.final_text_ordinal is not None and trigger_ordinal >= transcript.final_text_ordinal:
        return False

    return True
