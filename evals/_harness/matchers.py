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

``bash_write_offset(command, prefix) -> int | None`` / ``bash_may_write_under(command, prefix) -> bool``
    Conservative reading of a Bash command's text: might it write a file under
    ``prefix``? See ``bash_write_offset`` for the rule and its limits.

``is_possible_write_under(event, prefix) -> bool``
    ``bash_may_write_under`` for a ``Bash`` tool-call event.

``test_failed_before_first_source_write(events, *, source_prefix="src/") -> bool``
    The ordering predicate of ``test_failed_before_first_source_edit``, with a
    Bash call that might write under ``source_prefix`` counted as a source
    write as well. The old predicate keeps its Edit/Write-only meaning.

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


# ---------------------------------------------------------------- Bash write detection

# A path prefix counts only when no word character precedes it: ``src/`` in
# ``scratchpad/x/src/shop/cart.py`` and ``./src/x.py`` matches, ``resrc/`` does not.
_COMMAND_START = r"(?:^|[;&|(`{\n]|\$\(|\b(?:then|do|else)\b|-exec(?:dir)?)\s*"
_COMMAND_WRAPPERS = r"(?:(?:sudo|command|exec|time|nohup|xargs|env)\s+(?:-[-\w=]+\s+)*)*"
_ENV_ASSIGNMENTS = r"(?:\w+=\S*\s+)*"
_SHELL_WRITE_VERBS = re.compile(
    _COMMAND_START
    + _COMMAND_WRAPPERS
    + _ENV_ASSIGNMENTS
    + r"(?:mv|cp|rm|install|patch|touch|truncate|ln|rmdir|unlink|rsync)(?![\w./-])",
    re.MULTILINE,
)
_SNIPPET_MODE = r"[\"'][rbt]*[wax+][rwxabt+]*[\"']"
_WRITE_PATTERNS = (
    re.compile(r"(?<![\w./-])(?:tee|sponge)(?![\w-])"),
    re.compile(r"(?<![\w./-])sed(?![\w-])[^|;&\n]*?\s(?:-[A-Za-z]*i[A-Za-z.]*|--in-place(?:=\S*)?)(?=\s|$)"),
    re.compile(r"(?<![\w./-])perl(?![\w-])[^|;&\n]*?\s-[A-Za-z]*i[A-Za-z.]*(?=\s|$)"),
    re.compile(r"(?<![\w./-])dd\s[^|;&\n]*\bof="),
    re.compile(r"\s-delete(?=\s|$)"),
    re.compile(r"(?<![\w./-])(?:black|isort|autopep8|yapf)(?![\w-])(?![^|;&\n]*--check)"),
    re.compile(r"(?<![\w./-])ruff\s+format(?![\w-])(?![^|;&\n]*--check)"),
    re.compile(r"(?<![\w./-])ruff\s+check\s[^|;&\n]*--fix"),
    re.compile(
        r"(?<![\w./-])git\s+(?:-C\s+\S+\s+)?"
        r"(?:apply|restore|stash|rm|mv|clean|reset\s+--hard|checkout\s+(?:[^|;&\n]*\s)?--(?=\s|$))"
    ),
    _SHELL_WRITE_VERBS,
    # python / ruby / node snippets that open a file for writing or call a write method
    re.compile(
        "|".join(
            (
                r"\.write\(",
                r"write_text\(",
                r"write_bytes\(",
                r"\bwriteFile(?:Sync)?\(",
                r"\bappendFile(?:Sync)?\(",
                r"\bcreateWriteStream\(",
                rf"\bopen\s*\([^)\n]*,\s*(?:mode\s*=\s*)?{_SNIPPET_MODE}",
                rf"\bmode\s*=\s*{_SNIPPET_MODE}",
                rf"\.open\(\s*{_SNIPPET_MODE}",
                r"\bos\.(?:rename|replace|remove|unlink|rmdir|truncate)\(",
                r"\bshutil\.(?:copy|copy2|copyfile|copytree|move|rmtree)\(",
                r"\.(?:unlink|rename|touch|rmdir)\(",
            )
        )
    ),
)
_REDIRECT_TARGETS_THAT_WRITE_NOTHING = re.compile(r"/dev/(?:null|stderr|stdout|tty|fd/\d+)(?![\w/.-])")
_FD_DUP = re.compile(r"\d+-?|-")


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
        previous = command[position - 1] if position else ""
        end = position + 1
        if previous in ("-", "="):
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
        target = command[end:].lstrip(" \t")
        if _REDIRECT_TARGETS_THAT_WRITE_NOTHING.match(target):
            position = end
            continue
        return start


def bash_write_offset(command: str, prefix: str) -> int | None:
    """Locate the first write indicator of a Bash command that mentions a path under *prefix*.

    The command might write under *prefix* when it BOTH mentions a path under
    *prefix* (the prefix not preceded by a word character, so ``src/shop/cart.py``
    and ``scratchpad/x/src/cart.py`` mention ``src/`` and ``resrc/`` does not) AND
    contains a write indicator: a redirection to a file (``>``/``>>``, not an
    fd duplication such as ``2>&1`` and not ``>/dev/null``), ``tee``, ``sed -i`` or
    ``--in-place``, ``perl -i``, a python/ruby/node snippet that opens a file for
    writing or calls ``.write(``/``write_text``/``write_bytes``/``os.rename``/
    ``shutil.copy`` and the like, ``mv``, ``cp``, ``rm``, ``install``, ``patch``,
    ``touch``, ``git apply``/``checkout --``/``restore``/``stash``/``rm``, or a
    formatter that rewrites files.

    The rule over-approximates on purpose. The text is read as a whole: a write
    elsewhere plus a mere read of the prefix, a heredoc body that only mentions
    ``src/``, or ``a > b`` inside an inline script all count. A read-only call
    counted as a write can turn a test-first hit into a miss and never the
    reverse. It cannot see what the text does not spell out: a path built at run
    time (``os.path.join('src', ...)``, ``"$DIR/cart.py"``, a shell variable), a
    ``cd src`` followed by a bare file name, a script file written earlier and run
    later, an absolute binary such as ``/bin/rm``, a write through a tool this
    list does not name, and a verb used as an argument rather than a command.
    A write it misses is usually harmless to T1's ordering (no detected source
    write means nothing to order), but an undetected source write followed by a
    red run and then a detected write would credit a hit.

    Parameters
    ----------
    command : str
        The Bash tool call's ``command`` text.
    prefix : str
        A path prefix such as ``"src/"`` or ``"tests/"``.

    Returns
    -------
    int | None
        The smallest offset into *command* at which a write indicator starts, or
        ``None`` when the command does not mention *prefix* or shows no write.
        A caller ordering a write against a later word in the same command (a
        pytest run) compares offsets.
    """
    if not isinstance(command, str) or not prefix:
        return None
    if not re.search(rf"(?<!\w){re.escape(prefix)}", command):
        return None
    offsets = [match.start() for pattern in _WRITE_PATTERNS if (match := pattern.search(command))]
    redirect = _first_file_redirect(command)
    if redirect is not None:
        offsets.append(redirect)
    return min(offsets) if offsets else None


def bash_may_write_under(command: str, prefix: str) -> bool:
    """Return whether a Bash command might write a file under *prefix*; see ``bash_write_offset``."""
    return bash_write_offset(command, prefix) is not None


def is_possible_write_under(event: ToolCallEvent, prefix: str) -> bool:
    """Return whether *event* is a ``Bash`` call whose command might write under *prefix*.

    Edit-tool events are not looked at: ``Edit``, ``Write`` and ``NotebookEdit``
    name their path exactly and are judged by their own path.
    """
    if event.name != "Bash" or not isinstance(event.input, dict):
        return False
    command = event.input.get("command")
    return isinstance(command, str) and bash_may_write_under(command, prefix)


def test_failed_before_first_source_write(events: list[ToolCallEvent], *, source_prefix: str = "src/") -> bool:
    """Ordering predicate: a test failed before the first possible source write.

    Like ``test_failed_before_first_source_edit``, with one addition: a ``Bash``
    call that might write under *source_prefix* (``bash_write_offset``) is a
    source write as well as an ``Edit``/``Write``/``NotebookEdit`` of a non-test
    path. Ordering is by event ordinal, exactly as in ``precedes``: a Bash call
    that both writes the source and shows the red result shares one ordinal with
    itself, so that red result is not credited as coming first.

    Parameters
    ----------
    events : list[ToolCallEvent]
        The transcript's tool-call events.
    source_prefix : str
        The path prefix whose Bash writes count as source writes.

    Returns
    -------
    bool
        ``True`` only when a test-failure event's ordinal is strictly below the
        first source-write event's ordinal; ``False`` when either never occurs.
    """

    def is_source_write(event: ToolCallEvent) -> bool:
        return _is_source_edit(event) or is_possible_write_under(event, source_prefix)

    return precedes(events, _is_test_failure, is_source_write)


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
