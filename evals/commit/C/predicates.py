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

# Words that wrap or introduce the real command word: shell grouping and
# control keywords, and prefixes such as ``time``/``env`` (which may carry options).
_KEYWORDS = frozenset({"{", "}", "!", "if", "then", "do", "else", "elif", "fi", "while", "until", "done"})
_WRAPPERS = frozenset(
    {"env", "command", "sudo", "time", "nohup", "exec", "builtin", "timeout", "nice", "ionice", "stdbuf", "xargs"}
)
_WRAPPER_VALUE_OPTIONS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "sudo": frozenset({"-u", "-g", "-D", "-R", "-C", "-h", "-p", "-T", "-U"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "ionice": frozenset({"-c", "-n", "-p", "-P", "-u", "--class", "--classdata", "--pid", "--pgid", "--uid"}),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
    "xargs": frozenset(
        {"-n", "-I", "-L", "-P", "-d", "-E", "-s", "-a", "--max-args", "--max-procs", "--delimiter",
         "--max-lines", "--arg-file", "--max-chars"}
    ),
}
# Positional arguments a wrapper takes before the command (``timeout 300 cmd``).
_WRAPPER_POSITIONAL = {"timeout": 1}
_UV_RUN_VALUE_OPTIONS = frozenset(
    {"--with", "--with-requirements", "--with-editable", "--python", "-p", "--directory",
     "--project", "--group", "--extra", "--env-file", "--package", "--index", "--index-url"}
)
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
_GIT_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
_MAKE_OPTIONS_WITH_VALUE = frozenset({"-C", "-f", "-I", "-o", "-W", "--directory", "--file"})
_STAGING = frozenset({"add", "stage"})
_SEGMENT_BUDGET = 1000
_MAX_DEPTH = 8
# Characters that end a bare heredoc delimiter word.
_DELIMITER_END = " \t\r\n'\"<>;&|()"


class _Statement:
    """One simple command as the lexer saw it."""

    def __init__(self) -> None:
        self.words: list[str] = []
        # Commands found inside `$(...)`, backticks and `<(...)`; they run before this one.
        self.pre: list[list[str]] = []
        self.heredocs: list[str] = []


class _Lexer:
    """A small bash lexer: words, statements, quotes, substitutions and heredocs.

    It exists so that what the gates read as a command is what bash would run,
    without a fallback that guesses. Quoted text is data (`'a << b'`,
    `$'it\\'s'`); an unterminated quote swallows the rest of the text as bash's
    syntax error would, so nothing in it is run; `$((...))` is arithmetic, not
    a heredoc; `\\`-newline joins lines; the text of `$(...)`, backticks and
    `<(...)` is read as commands; a heredoc body is data unless its command is
    a shell. A heredoc with no terminator line does NOT swallow the text after
    it, which is read as commands: failing toward seeing, not hiding.
    """

    def __init__(self, text: str, depth: int) -> None:
        self.text = text
        self.depth = depth
        self.i = 0
        self.statements: list[_Statement] = []
        self.stmt = _Statement()
        self.word: list[str] = []
        self.in_word = False
        self.pending: list[tuple[_Statement, str]] = []

    # -- word and statement bookkeeping

    def add(self, chunk: str) -> None:
        self.word.append(chunk)
        self.in_word = True

    def flush(self) -> None:
        if self.in_word:
            self.stmt.words.append("".join(self.word))
            self.word = []
            self.in_word = False

    def end_statement(self) -> None:
        self.flush()
        if self.stmt.words or self.stmt.pre:
            self.statements.append(self.stmt)
        self.stmt = _Statement()

    def substitute(self, inner: str, placeholder: str) -> None:
        self.stmt.pre.extend(_commands(inner, self.depth + 1))
        self.add(placeholder)

    # -- the main loop

    def run(self) -> list[_Statement]:
        text = self.text
        size = len(text)
        while self.i < size:
            i = self.i
            c = text[i]
            if c == "\\":
                following = text[i + 1 : i + 2]
                if following == "\n":
                    self.i += 2
                elif following:
                    self.add(following)
                    self.i += 2
                else:
                    self.i += 1
            elif c == "'":
                end = text.find("'", i + 1)
                self.add(text[i + 1 :] if end == -1 else text[i + 1 : end])
                self.i = size if end == -1 else end + 1
            elif c == '"':
                self.double_quoted()
            elif c == "$":
                self.dollar()
            elif c == "`":
                inner, self.i = self.backtick_body(i)
                self.substitute(inner, "`...`")
            elif c in "<>" and text[i + 1 : i + 2] == "(":
                inner, self.i = self.paren_body(i + 2)
                self.substitute(inner, "<(...)")
            elif text.startswith("<<", i) and not text.startswith("<<<", i) and self.heredoc():
                pass
            elif c in "<>" or (c == "&" and text[i + 1 : i + 2] == ">"):
                self.redirect()
            elif text.startswith("((", i) and not self.in_word and not self.stmt.words:
                self.i = self.arithmetic_end(i + 2)
            elif c in ";&|()":
                self.end_statement()
                self.i += 1
            elif c == "\n":
                self.newline()
            elif c in " \t\r":
                self.flush()
                self.i += 1
            elif c == "#" and not self.in_word:
                while self.i < size and text[self.i] != "\n":
                    self.i += 1
            else:
                self.add(c)
                self.i += 1
        self.end_statement()
        return self.statements

    # -- quoting and substitution

    def double_quoted(self) -> None:
        text = self.text
        size = len(text)
        j = self.i + 1
        chunk: list[str] = []
        self.add("")  # `""` is still a word
        while j < size:
            c = text[j]
            if c == '"':
                j += 1
                break
            if c == "\\" and j + 1 < size:
                following = text[j + 1]
                if following != "\n":
                    chunk.append(following if following in '"\\$`' else c + following)
                j += 2
            elif c == "$" and text.startswith("$((", j):
                end = self.arithmetic_end(j + 3)
                chunk.append(text[j:end])
                j = end
            elif c == "$" and text[j + 1 : j + 2] == "(":
                inner, j = self.paren_body(j + 2)
                self.stmt.pre.extend(_commands(inner, self.depth + 1))
                chunk.append("$(...)")
            elif c == "`":
                inner, j = self.backtick_body(j)
                self.stmt.pre.extend(_commands(inner, self.depth + 1))
                chunk.append("`...`")
            else:
                chunk.append(c)
                j += 1
        self.add("".join(chunk))
        self.i = j

    def dollar(self) -> None:
        text = self.text
        size = len(text)
        i = self.i
        following = text[i + 1 : i + 2]
        if text.startswith("$((", i):
            end = self.arithmetic_end(i + 3)
            self.add(text[i:end])
            self.i = end
        elif following == "(":
            inner, self.i = self.paren_body(i + 2)
            self.substitute(inner, "$(...)")
        elif following == "'":
            j = i + 2
            chunk: list[str] = []
            while j < size and text[j] != "'":
                if text[j] == "\\" and j + 1 < size:
                    chunk.append(text[j + 1])
                    j += 2
                else:
                    chunk.append(text[j])
                    j += 1
            self.add("".join(chunk))
            self.i = min(j + 1, size)
        elif following == "{":
            depth = 1
            j = i + 2
            while j < size and depth:
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            self.add(text[i:j])
            self.i = j
        else:
            self.add("$")
            self.i += 1

    def arithmetic_end(self, start: int) -> int:
        """The index after the `))` closing an arithmetic expansion whose `((` ended at *start*."""
        depth = 2
        for j in range(start, len(self.text)):
            depth += {"(": 1, ")": -1}.get(self.text[j], 0)
            if depth == 0:
                return j + 1
        return len(self.text)

    def paren_body(self, start: int) -> tuple[str, int]:
        """The text inside a `(...)` whose `(` ended at *start*, and the index after its `)`."""
        text = self.text
        size = len(text)
        depth = 1
        j = start
        while j < size:
            c = text[j]
            if c == "\\":
                j += 2
                continue
            if c == "'":
                end = text.find("'", j + 1)
                j = size if end == -1 else end + 1
                continue
            if c == '"':
                j += 1
                while j < size and text[j] != '"':
                    j += 2 if text[j] == "\\" else 1
                j += 1
                continue
            depth += {"(": 1, ")": -1}.get(c, 0)
            if depth == 0:
                return text[start:j], j + 1
            j += 1
        return text[start:], size

    def backtick_body(self, start: int) -> tuple[str, int]:
        """The text between a backtick at *start* and the next unescaped one, and the index after it."""
        text = self.text
        j = start + 1
        while j < len(text):
            if text[j] == "\\":
                j += 2
            elif text[j] == "`":
                return text[start + 1 : j].replace("\\`", "`"), j + 1
            else:
                j += 1
        return text[start + 1 :], len(text)

    # -- redirections and heredocs

    def redirect(self) -> None:
        text = self.text
        i = self.i
        self.flush()
        j = i + 1 if text[i] == "&" else i
        while text[j : j + 1] in ("<", ">"):
            j += 1
        if text[j : j + 1] == "&" and j > i and text[j - 1] in "<>":
            j += 1
        self.stmt.words.append(text[i:j])
        self.i = j

    def heredoc(self) -> bool:
        """Read a `<<DELIM` header; ``False`` when it is not one (then it is a plain redirect)."""
        text = self.text
        j = self.i + 2
        if text[j : j + 1] == "-":
            j += 1
        while text[j : j + 1] in (" ", "\t"):
            j += 1
        quote = text[j : j + 1]
        if quote in ("'", '"'):
            end = text.find(quote, j + 1)
            if end == -1:
                return False
            delimiter = text[j + 1 : end]
            j = end + 1
        else:
            if quote == "\\":
                j += 1
            start = j
            while j < len(text) and text[j] not in _DELIMITER_END:
                j += 1
            delimiter = text[start:j]
        if not delimiter:
            return False
        self.flush()
        self.pending.append((self.stmt, delimiter))
        self.i = j
        return True

    def newline(self) -> None:
        text = self.text
        self.flush()
        position = self.i + 1
        for owner, delimiter in self.pending:
            terminator = re.compile(rf"^[ \t]*{re.escape(delimiter)}[ \t]*$", re.MULTILINE).search(
                text, position
            )
            if terminator is None:
                break  # no terminator: keep everything after as commands
            owner.heredocs.append(text[position : terminator.start()])
            position = min(terminator.end() + 1, len(text))
        self.pending = []
        self.end_statement()
        self.i = position


def _commands(text: str, depth: int = 0) -> list[list[str]]:
    """Every simple command bash would run for *text*, in order, as lists of words."""
    if depth > _MAX_DEPTH:
        return []
    found: list[list[str]] = []
    for statement in _Lexer(text, depth).run():
        found.extend(_resolve(statement, depth))
    return found


def _resolve(statement: _Statement, depth: int) -> list[list[str]]:
    """The commands in one statement: its substitutions, then itself (looking through eval and shells)."""
    found = list(statement.pre)
    words = _without_prefixes(statement.words)
    if not words:
        return found
    name = _basename(words[0])
    if name == "eval":
        found.extend(_commands(" ".join(words[1:]), depth + 1))
        return found
    payload = _shell_payload(words)
    if payload is not None:
        found.extend(_commands(payload, depth + 1))
        return found
    if name in _SHELLS:
        for body in statement.heredocs:
            found.extend(_commands(body, depth + 1))
    found.append(words)
    return found


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
    """Every simple command in a Bash call's ``command`` text."""
    return _commands(command)


def _without_prefixes(words: list[str]) -> list[str]:
    """Drop what comes before the command word.

    That is ``VAR=value`` assignments, shell grouping and control keywords
    (``{``, ``!``, ``if``, ``then``, ``do``, ...), wrappers such as
    ``env``/``time``/``sudo``/``timeout``/``nice``/``xargs`` with their options
    and positional arguments, and ``uv run`` with its options.
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
            index += _WRAPPER_POSITIONAL.get(name, 0)
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


def _is_dry_run(argument: str) -> bool:
    """``make``'s ``-n`` family: the recipes are printed, not run."""
    if argument in ("--dry-run", "--just-print", "--recon"):
        return True
    if argument.startswith("-") and not argument.startswith("--"):
        for letter in argument[1:]:
            if letter == "n":
                return True
            if letter in "CfIoWjl":  # takes a value: the rest of the word is not flags
                return False
    return False


def _is_make_test(words: list[str]) -> bool:
    """``make`` with the ``test`` target among its arguments, and not a dry run."""
    if not words or _basename(words[0]) != "make":
        return False
    has_target = False
    index = 1
    while index < len(words):
        argument = words[index]
        if argument in _MAKE_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if _is_dry_run(argument):
            return False
        if not argument.startswith("-") and "=" not in argument and argument == "test":
            has_target = True
        index += 1
    return has_target


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


# An attribution trailer names an AI tool in the NAME part of its value, never in
# the email (a human at an AI vendor, or `jane@openai-fan.example`, is not attribution).
_TRAILER = re.compile(r"^\s*(?:co-authored-by|assisted-by|generated-by)\s*:\s*(.*)$", re.IGNORECASE)
_AI_TOOL_NAME = re.compile(
    r"(?<!\w)(?:claude[ _-]?code|claude|anthropic|copilot|chatgpt|openai|gpt|codex|ai)(?!\w)", re.IGNORECASE
)
# Tools that are also given names count only when they are the WHOLE name
# (`Devin <devin@cognition.ai>`, `Cursor Agent`, `devin[bot]`), so a human
# `Devin Smith` or `Gemini Rodriguez` is not attribution.
_AMBIGUOUS_TOOL_NAME = re.compile(
    r"^(?:devin|cursor|aider|gemini)(?:[ _-]?(?:ai|bot|agent))?(?:\[bot\])?$", re.IGNORECASE
)
_EMAIL = re.compile(r"<[^>]*>|\S+@\S+")
_GENERATED_WITH = re.compile(r"generated\s+(?:with|by)\b.*\b(?:claude|anthropic)\b", re.IGNORECASE)
_ROBOT = "\N{ROBOT FACE}"


def _is_ai_trailer(line: str) -> bool:
    """A `Co-Authored-By:`/`Assisted-by:`/`Generated-by:` trailer whose name part is an AI tool."""
    matched = _TRAILER.match(line)
    if matched is None:
        return False
    name = _EMAIL.sub("", matched.group(1)).strip()
    return bool(_AI_TOOL_NAME.search(name) or _AMBIGUOUS_TOOL_NAME.match(name))


def _carries_attribution(log: str) -> bool:
    lines = log.splitlines()[1:]  # the first line is the SHA
    return any(_is_ai_trailer(line) or _GENERATED_WITH.search(line) or _ROBOT in line for line in lines)


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
