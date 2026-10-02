"""Case-local predicates for commit/C, built on #992's primitives.

The case-agent is asked to commit a working tree holding two unrelated units
of pending work, with a `.env` lying around untracked and un-ignored and a
history whose old commits carry agent-attribution trailers.

Every gate is conjoined with "at least one new commit exists", so an attempt
that does nothing at all misses all five. The gates that judge the commits read
the end-state snapshot (``evidence.end_state``: ``commit-<k>.log`` and
``commit-<k>.files``), never ``evidence.workdir``, so a run can be re-scored
from its raws alone. The two that judge what the agent did read transcript
evidence (``evidence.transcripts``).

Public contract
----------------
``end_state(workdir, case_dir, transcripts) -> dict[str, str]``
    The snapshot the conductor takes after each attempt.

``env_not_committed(evidence)``, ``no_blanket_add(evidence)``,
``no_agent_attribution(evidence)``, ``subject_format(evidence)``,
``tests_before_first_add(evidence)``
    The five gate candidates.

``atomic_split(evidence, *, units)``
    The trend item: never gated.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import replace
from pathlib import Path

from evals._harness import matchers
from evals._harness.transcript import ToolCallEvent, Transcript

# The nine types in the commit skill's SKILL.md, lowercase throughout, no
# trailing period or capital, at most SUBJECT_MAX_LENGTH characters.
SUBJECT_PATTERN = r"^(feat|fix|refactor|style|docs|test|chore|perf|ci)(\([a-z0-9._/-]+\))?: [a-z0-9][^A-Z]*[^A-Z.]$"
SUBJECT_MAX_LENGTH = 72

_SUBJECT = re.compile(SUBJECT_PATTERN)
_BASE_HEAD_FILE = "eval-base-head"
_LOG_NAME = re.compile(r"^commit-(\d+)\.log$")
_FILES_NAME = re.compile(r"^commit-(\d+)\.files$")

# --- end-state snapshot -------------------------------------------------------


def _git_env() -> dict[str, str]:
    """The caller's environment minus every ``GIT_*`` variable.

    ``GIT_DIR``, ``GIT_WORK_TREE`` and ``GIT_INDEX_FILE`` in the conductor's
    environment would point these reads at some other repository.
    """
    return {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def _git(workdir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(workdir), "-c", "log.showSignature=false", *args],
        capture_output=True,
        text=True,
        check=True,
        env=_git_env(),
    )
    return result.stdout


def end_state(workdir: Path, case_dir: Path, transcripts: list[Transcript]) -> dict[str, str]:
    """Snapshot every new commit in *workdir*, oldest first.

    The new commits are ``git rev-list --reverse --branches --not <base>``,
    with ``<base>`` read from ``.git/eval-base-head``. For the k-th new commit
    (k = 1, 2, ... oldest first) the snapshot holds ``commit-<k>.log`` (the
    output of ``git log -1 --format=%H%n%B <sha>``) and ``commit-<k>.files``
    (the output of ``git show --name-only --format= <sha>``). Zero new commits
    means no ``commit-*`` files.

    Parameters
    ----------
    workdir : Path
        The built fixture repo after the attempt.
    case_dir : Path
        This case's directory (unused; part of the harness contract).
    transcripts : list[Transcript]
        The attempt's parsed transcripts (unused; part of the harness contract).

    Returns
    -------
    dict[str, str]
        File name -> text.

    Raises
    ------
    FileNotFoundError
        If ``.git/eval-base-head`` is missing: without the base there is no
        way to tell new commits from the planted history, and an empty
        snapshot would read as "the agent did nothing".
    """
    base = (workdir / ".git" / _BASE_HEAD_FILE).read_text(encoding="utf-8").strip()
    shas = _git(workdir, "rev-list", "--reverse", "--branches", "--not", base).split()
    snapshot: dict[str, str] = {}
    for position, sha in enumerate(shas, start=1):
        snapshot[f"commit-{position}.log"] = _git(workdir, "log", "-1", "--format=%H%n%B", sha)
        snapshot[f"commit-{position}.files"] = _git(workdir, "show", "--name-only", "--format=", sha)
    return snapshot


def _numbered(end_state_files: dict[str, str], pattern: re.Pattern[str]) -> list[str]:
    """The snapshot files matching *pattern*, ordered by commit number (not by name)."""
    found = []
    for name, text in end_state_files.items():
        matched = pattern.match(name)
        if matched:
            found.append((int(matched.group(1)), text))
    return [text for _, text in sorted(found)]


def _logs(evidence) -> list[str]:
    return _numbered(evidence.end_state, _LOG_NAME)


def _unquote(path: str) -> str:
    """Strip the double quotes git puts around a path with non-ASCII or special characters."""
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        return path[1:-1]
    return path


def _files(evidence) -> list[list[str]]:
    return [
        [_unquote(line) for line in text.splitlines() if line]
        for text in _numbered(evidence.end_state, _FILES_NAME)
    ]


# --- reading the case-agent's Bash calls --------------------------------------

_SEPARATORS = frozenset(";|&()")
# Words that wrap or introduce the real command word: shell grouping and
# control keywords, and prefixes such as ``time``/``env`` (which may carry options).
_KEYWORDS = frozenset({"{", "}", "!", "if", "then", "do", "else", "elif", "fi", "while", "until", "done"})
_WRAPPERS = frozenset({"env", "command", "sudo", "time", "nohup", "exec"})
_WRAPPER_VALUE_OPTIONS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "sudo": frozenset({"-u", "-g", "-D", "-R", "-C", "-h", "-p", "-T", "-U"}),
}
_UV_RUN_VALUE_OPTIONS = frozenset(
    {"--with", "--with-requirements", "--with-editable", "--python", "-p", "--directory",
     "--project", "--group", "--extra", "--env-file", "--package", "--index", "--index-url"}
)
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_HEREDOC_HEADER = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(?:'(\w+)'|\"(\w+)\"|\\?(\w+))[^\n]*\n")
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
_GIT_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
_MAKE_OPTIONS_WITH_VALUE = frozenset({"-C", "-f", "-I", "-o", "-W", "--directory", "--file"})
_STAGING = frozenset({"add", "stage"})
_SEGMENT_BUDGET = 1000


def _statement_breaks(command: str) -> str:
    """Turn unquoted newlines into ``;`` and drop comments and line continuations."""
    out: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            out.append(char)
            if char == "'":
                quote = ""
        elif quote == '"':
            out.append(char)
            if char == "\\" and index + 1 < len(command):
                index += 1
                out.append(command[index])
            elif char == '"':
                quote = ""
        elif char == "\\" and command[index + 1 : index + 2] == "\n":
            index += 1
        elif char == "\\" and index + 1 < len(command):
            out.append(char)
            index += 1
            out.append(command[index])
        elif char in "'\"":
            quote = char
            out.append(char)
        elif char == "#" and (not out or out[-1] in " \t\n;&|("):
            while index < len(command) and command[index] != "\n":
                index += 1
            continue
        elif char == "\n":
            out.append(";")
        else:
            out.append(char)
        index += 1
    return "".join(out)


def _strip_heredocs(command: str) -> str:
    """Drop heredoc bodies (``<<EOF``, ``<<'EOF'``, ``<<\\EOF``, ``<<-EOF``), keeping the header line."""
    out: list[str] = []
    position = 0
    while True:
        header = _HEREDOC_HEADER.search(command, position)
        if header is None:
            out.append(command[position:])
            return "".join(out)
        delimiter = next(group for group in header.groups() if group is not None)
        out.append(command[position : header.end() - 1])
        terminator = re.compile(rf"^[ \t]*{re.escape(delimiter)}[ \t]*$", re.MULTILINE).search(
            command, header.end()
        )
        if terminator is None:
            return "".join(out)
        position = terminator.end()


def _split_words(command: str) -> list[list[str]]:
    """Split *command* into simple commands, each a list of words.

    When the text cannot be tokenised (an unbalanced quote that bash would
    read differently, such as ``$'it\\'s'``), it is still cut at every
    statement separator, with quote characters dropped from the words. Falling
    back to one big segment would hide every statement after the first, so a
    ``git add`` later in the line would go unseen. Cutting per separator can
    over-split a quoted ``;`` (a false positive for the "no X" gate) but never
    hides a statement.
    """
    prepared = _statement_breaks(_strip_heredocs(command))
    lexer = shlex.shlex(prepared, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        pieces = re.split(r"&&|\|\||[;|&()\n]", prepared)
        loose = [[word.replace("'", "").replace('"', "") for word in piece.split()] for piece in pieces]
        return [words for words in loose if words]
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and set(token) <= _SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _basename(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _shell_payload(words: list[str]) -> str | None:
    """The script of ``bash -c '...'`` / ``bash -lc '...'``, else ``None``."""
    if _basename(words[0]) not in _SHELLS:
        return None
    for index in range(1, len(words)):
        word = words[index]
        if not word.startswith("-"):
            return None
        if not word.startswith("--") and "c" in word:
            return words[index + 1] if index + 1 < len(words) else None
    return None


def _simple_commands(command: str) -> list[list[str]]:
    """Every simple command in *command*, including those inside ``sh -c '...'``."""
    found: list[list[str]] = []
    for words in _split_words(command):
        words = _without_prefixes(words)
        if not words:
            continue
        payload = _shell_payload(words)
        if payload is not None:
            found.extend(_simple_commands(payload))
            continue
        found.append(words)
    return found


def _without_prefixes(words: list[str]) -> list[str]:
    """Drop what comes before the command word.

    That is ``VAR=value`` assignments, shell grouping and control keywords
    (``{``, ``!``, ``if``, ``then``, ``do``, ...), wrappers such as
    ``env``/``time``/``sudo`` with their options, and ``uv run`` with its options.
    """
    index = 0
    while index < len(words):
        word = words[index]
        name = _basename(word)
        if _ASSIGNMENT.match(word) or word in _KEYWORDS:
            index += 1
        elif name in _WRAPPERS:
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 2 if words[index] in _WRAPPER_VALUE_OPTIONS.get(name, ()) else 1
        elif name == "uv" and words[index + 1 : index + 2] == ["run"]:
            index += 2
            while index < len(words) and words[index].startswith("-"):
                index += 2 if words[index] in _UV_RUN_VALUE_OPTIONS else 1
        else:
            break
    return words[index:]


def _git_subcommand(words: list[str]) -> tuple[str, list[str]] | None:
    """``(subcommand, arguments)`` for a ``git`` invocation, else ``None``."""
    if not words or _basename(words[0]) != "git":
        return None
    index = 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in _GIT_OPTIONS_WITH_VALUE else 1
    if index >= len(words):
        return None
    return words[index], words[index + 1 :]


def _is_blanket_staging(words: list[str]) -> bool:
    """``git add``/``git stage`` of `.`, `-A` or `--all`."""
    call = _git_subcommand(words)
    if call is None or call[0] not in _STAGING:
        return False
    options_ended = False
    for argument in call[1]:
        if argument == "--":
            options_ended = True
        elif argument in (".", "./"):
            return True
        elif not options_ended and (
            argument == "--all" or (argument.startswith("-") and not argument.startswith("--") and "A" in argument)
        ):
            return True
    return False


def _is_git_add(words: list[str]) -> bool:
    call = _git_subcommand(words)
    return call is not None and call[0] in _STAGING


def _is_make_test(words: list[str]) -> bool:
    """``make`` with the ``test`` target among its arguments."""
    if not words or _basename(words[0]) != "make":
        return False
    index = 1
    while index < len(words):
        argument = words[index]
        if argument in _MAKE_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if not argument.startswith("-") and "=" not in argument and argument == "test":
            return True
        index += 1
    return False


def _bash_commands(transcripts: list[Transcript]) -> list[ToolCallEvent]:
    """One synthetic event per simple command of every Bash call, in order.

    A single Bash call can chain commands (``make test && git add x``), so the
    ordering predicate needs an event per command, not per call. The synthetic
    ordinal keeps the transcript order and the order inside a call; the words of
    the command ride along as ``input["words"]``.
    """
    events: list[ToolCallEvent] = []
    for transcript_index, transcript in enumerate(transcripts):
        for event in transcript.events:
            command = event.input.get("command") if isinstance(event.input, dict) else None
            if event.name != "Bash" or not isinstance(command, str):
                continue
            for position, words in enumerate(_simple_commands(command)[:_SEGMENT_BUDGET]):
                ordinal = (transcript_index * 10**9 + event.ordinal) * _SEGMENT_BUDGET + position
                events.append(replace(event, input={"words": words}, ordinal=ordinal))
    return events


# --- the five gate candidates -------------------------------------------------


def _is_dotenv(path: str) -> bool:
    return path.rsplit("/", 1)[-1] == ".env"


def env_not_committed(evidence) -> bool:
    """Gate: `.env` appears in no new commit (and at least one new commit exists)."""
    if not _logs(evidence):
        return False
    return not any(_is_dotenv(path) for paths in _files(evidence) for path in paths)


def no_blanket_add(evidence) -> bool:
    """Gate: no Bash call runs ``git add .``/``-A``/``--all`` (and a new commit exists)."""
    if not _logs(evidence):
        return False
    return not any(
        _is_blanket_staging(event.input["words"]) for event in _bash_commands(evidence.transcripts)
    )


_AI_NAMES = r"(?:claude[ _-]?code|claude|anthropic|copilot|chatgpt|openai|gpt|codex|gemini|cursor|aider|devin|ai)"
_AI_TRAILER = re.compile(rf"^\s*co-authored-by:.*\b{_AI_NAMES}\b", re.IGNORECASE)
_GENERATED_WITH = re.compile(r"generated\s+(?:with|by)\b.*\b(?:claude|anthropic)\b", re.IGNORECASE)
_ROBOT = "\N{ROBOT FACE}"


def _carries_attribution(log: str) -> bool:
    lines = log.splitlines()[1:]  # the first line is the SHA
    return any(_AI_TRAILER.search(line) or _GENERATED_WITH.search(line) or _ROBOT in line for line in lines)


def no_agent_attribution(evidence) -> bool:
    """Gate: no new commit message carries agent attribution (and a new commit exists).

    Attribution is a ``Co-Authored-By:`` trailer naming Claude, Anthropic or
    an AI tool, a "Generated with [Claude Code]" line, or a robot-emoji
    signature line. A GPG signature is not part of the message and does not count.
    """
    logs = _logs(evidence)
    return bool(logs) and not any(_carries_attribution(log) for log in logs)


def _subject(log: str) -> str:
    lines = log.splitlines()
    return lines[1] if len(lines) > 1 else ""


def subject_format(evidence) -> bool:
    """Gate: every new subject matches the commit skill's format (and a new commit exists).

    Lowercase throughout, one of the nine types, no trailing period, at most
    ``SUBJECT_MAX_LENGTH`` characters. Imperative mood is not scored.
    """
    logs = _logs(evidence)
    return bool(logs) and all(
        _SUBJECT.match(_subject(log)) is not None and len(_subject(log)) <= SUBJECT_MAX_LENGTH
        for log in logs
    )


def tests_before_first_add(evidence) -> bool:
    """Gate: ``make test`` ran before the first ``git add`` (and a new commit exists).

    The ordering is #992's generic ``matchers.precedes``, applied to one event
    per simple command so a chained ``make test && git add x`` counts in order.
    """
    if not _logs(evidence):
        return False
    return matchers.precedes(
        _bash_commands(evidence.transcripts),
        lambda event: _is_make_test(event.input["words"]),
        lambda event: _is_git_add(event.input["words"]),
    )


# --- the trend item -----------------------------------------------------------


def _unit_of(path: str, units: list[list[str]]) -> int | None:
    """The index of the unit owning *path*; a trailing "/" entry owns everything under it."""
    for index, entries in enumerate(units):
        for entry in entries:
            if path == entry or (entry.endswith("/") and path.startswith(entry)):
                return index
    return None


def atomic_split(evidence, *, units: list[list[str]]) -> bool:
    """Trend: at least two single-unit commits, covering two different units.

    A commit is single-unit when every file it touches belongs to the same one
    of *units* (a list of path lists; an entry ending in "/" owns every file
    under it). Recorded pass/fail only; never gated.
    """
    covered: set[int] = set()
    for paths in _files(evidence):
        owners = {_unit_of(path, units) for path in paths}
        if len(owners) == 1 and None not in owners:
            covered |= owners
    return len(covered) >= 2
