"""Allow-list classification of a Bash tool call: does it write, and where?

``classify_bash_command(command) -> "none" | "tests" | "source"``
    ``none`` only when EVERY simple command's head is a known read-only program with
    no write flag and the call has no file redirect. A call that is write-capable is
    ``tests`` only when every write it makes is a recognised one aimed at a literal
    path under ``tests/``, no other command in it is write-capable, and ``src``
    appears nowhere in it as a path-ish token. Everything else is ``source``: an
    unknown head, a script run, a write whose target cannot be read off the text, a
    parse that fails, or a command over ``BASH_COMMAND_CAP`` characters.

``bash_write_offset(command) -> int | None``
    Where the first write-capable simple command starts, for a caller ordering a
    write against a later word in the same command. ``None`` exactly when the call
    is ``none``; ``0`` for an over-cap or unparsable command.

The shape is an allow-list on purpose. A blocklist of write idioms is open-ended
(``gsed -i``, ``\\cp``, ``uv run python /tmp/fix.py``, ``from shutil import copy``,
``sed -n '1w src/x'`` all slipped past one), and a write the reader misses can
credit a source-first run as test-first. Here a command nobody listed is
write-capable, and so is any option or construct a reader below does not name:
environment prefixes (only ``LANG``, ``LC_ALL``, ``LC_CTYPE``, ``TZ``, ``NO_COLOR``,
``FORCE_COLOR``, ``TERM``, ``COLUMNS``, ``LINES``, ``CI``, ``PYTHONDONTWRITEBYTECODE``,
``PYTHONUNBUFFERED`` and ``PYTHONHASHSEED`` with a literal value), wrapper options
(``env`` and ``exec`` with any option), ``git -c`` (presentation keys only),
``xargs`` (a child that cannot write whatever arrives on stdin, ``-n N``, ``-I {}``
and ``-0`` only), ``sed`` (a hand scanner over the script and exact option
spellings), ``sort``/``tree``/``uniq`` output forms, an option ALLOW-LIST for pytest,
mypy, ruff, black and isort, and an inline python script that is parsed with
``ast`` and may import only a short list of modules and open files only for
reading (or for writing a string literal under ``tests/``). A heredoc body is data
only when its delimiter is quoted, and it reaches an interpreter only directly or
through a bare ``cat``. Pre-existing shapes the reading still does not see are
code run from agent-authored ``tests/`` (a pytest ``conftest``, ``sitecustomize``),
state carried across calls (a ``cd`` or a symlink made earlier), the deep object
graph of the allow-listed python modules, and variables an earlier call exported;
they are listed in ``docs/experiments/2026-10-03-tdd-t-redesign/README.md``. The
classifier is a heuristic, not a proof, and a T1 hit is only as trustworthy as
the owner audit behind it.

Pytest spellings are allow-listed even though they execute code: running the tests
is what a test-first attempt does, and a ``none`` call can never count as a write.
A call that appends a test AND runs pytest on it stays a ``tests`` call.

Shell compound constructs are structure, not commands: ``for``/``while``/``until ... do ...
done``, ``if ... then ... [elif ...] [else ...] fi``, brace groups ``{ ...; }``, subshell groups
``( ... )`` and the negation ``!``. Their reserved words are never heads, every simple command in
a condition, body or group is classified by the same rules as outside it, and the call is the
worst of its parts (``source`` > ``tests`` > ``none``); a redirect written after a construct
(``done > F``, ``fi >> F``, ``} > F``, ``) >> F``) applies to it. The words after ``for NAME in``
are data. ``case``, ``select``, function definitions, ``coproc``, ``[[ ]]``, ``(( ))``, ``$(( ))``,
``read``, a ``time`` wrapped around a construct, unbalanced or mismatched openers and closers, a
reserved word the grammar does not allow where it stands, and nesting past
``_MAX_COMPOUND_DEPTH`` open constructs all fail closed to ``source``. ``[[``, ``read``, ``((``,
``$((``, ``$[`` and the arithmetic forms of ``${...}`` evaluate their operands as arithmetic, where a
subscript such as ``a[$(cmd)]`` runs ``cmd``; ``test``/``[`` with ``-v`` or ``-R`` and ``printf -v`` do
the same through a variable name.

A loop variable is an opaque expansion like any other (the word list is not read: ``IFS`` splits
it), so a write whose target contains an expansion is ``source``. An unresolved expansion
(``$NAME``, ``${...}``, a command substitution, a backtick, an unquoted ``{a,b}`` brace group) among
the arguments of a head keeps the call read-only only for a head that cannot write or run code
whatever it is given (``cat``, ``echo``, ``wc``, ``head``, ``tail``, ``ls``, ``cut``, ``tr``,
``stat``, ``du``, ``diff``, ``cmp``, ``grep`` and kin, ``test``/``[`` with the expansion as an
operand, ``printf`` with a literal format); every other head is ``source``.

In a call with a write, every ``cd`` target must be a plain literal path (no quote, escape, glob or
expansion) that is absolute or relative without ``src`` or ``..`` segments, and the call has no
``eval`` and no ``CDPATH`` assignment (refused as an exported name): a ``cd`` that can land in ``src`` leaves a write's place unknown. That
rule applies only to calls with a write; a literal ``cd`` in a read-only call is unaffected, but a
``cd`` whose target is an expansion (``cd $d``) is ``source`` anyway, because ``cd`` is not on the
safe-head list above.

Cost: one pass over the text with a hand-written scanner and a stack of open
constructs with O(1) work per token. The work the code bounds is the cap, a limit
on command substitutions, a limit on analysed ``open(`` calls, a limit on open
constructs, a limit on heredoc bodies feeding one command and a cap on the size of
a ``sed`` script, an ``awk`` program and a python syntax tree. A heredoc body is
analysed once however many bare ``cat`` commands it is piped through (the analysis
is memoised). No
regular expression runs over user text with a nested or overlapping quantifier:
the ``sed``, ``awk``, option and python readers are hand scanners, so no input
shape makes the classifier slow.
"""

from __future__ import annotations

import ast
import functools
import importlib
import pathlib
import re
import sys
import types
import warnings

# A command longer than this is classified "source" without being scanned (fail closed).
BASH_COMMAND_CAP = 100_000

_MAX_DEPTH = 4
# Open compound constructs (``for``/``while``/``until``/``if``/``{``/``(``) at once; one more fails closed.
_MAX_COMPOUND_DEPTH = 32
_MAX_SUBSTITUTIONS = 200
# A command fed by more heredoc bodies than this (through a pipeline) is not analysed: fail closed.
_MAX_FEED = 50
_MAX_OPEN_CALLS = 50
_MAX_SCRIPT = 4_000

# --------------------------------------------------------------------------- the scanner

_WORD_RUN = re.compile(r"[^ \t\r\n|&;<>()'\"\\`$]+")
_PAREN = re.compile(r"[()]")
# A heredoc delimiter is read only in the shapes below; every other shape (a mid-word quote, an expansion, a
# trailing character that bash would glue into the word) is a scan failure, so the call is ``source``.
_HEREDOC_BODY = re.compile(r"[A-Za-z0-9_.-]+")
_HEREDOC_BARE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
# What may follow the delimiter word: a blank, a newline, an operator or the end of the text.
_HEREDOC_END = " \t\n;|&<>)"
# Control characters other than a newline and a tab (a carriage return is a blank to this scanner, not to bash).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f]")
# What may not appear in the body of ``$( ... )``, a backtick pair or ``${ ... }``: the scanner finds the close by
# counting, which a backslash, a comment, a quote or a newline in the body can make disagree with the shell.
_SUBST_BODY_BAD = re.compile(r"""[\\#'"\r\n]""")
_DQ_SPECIAL = re.compile(r'[^"\\$`]+')
_PARAM_NAME = re.compile(r"\w+|[@*#?!$-]")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*\+?=")
_DEV_OK = re.compile(r"/dev/(?:null|stderr|stdout)")
_FD_DUP = re.compile(r"\d+-?|-")
_UNRESOLVED = "\x00"
# Words that must be plain literals: the arguments of ``:``, ``break`` and ``continue``.
_PLAIN_ARG = re.compile(r"[A-Za-z0-9_./=-]+")
_CD_GLOB = frozenset("*?[{~")
# A ``${...}`` that evaluates arithmetic or re-expands its value: an array subscript, indirection (``!``), a
# substring offset (``NAME:`` not followed by ``-``, ``=``, ``+`` or ``?``), or ``@`` (``${x@P}`` runs a ``$(...)``).
_ARITHMETIC_EXPANSION = re.compile(r"^!|\[|@|^\w+:(?![-=+?])")
# Heads that cannot write or run code whatever their arguments are, so an unresolved expansion
# (``$NAME``, ``$(...)``, a backtick) among their arguments leaves a call read-only. ``test``, ``[`` and
# ``printf`` have their own rules (``_expansion_safe``); every other head goes to ``source`` on one.
_EXPANSION_SAFE_HEADS = frozenset(
    {"cat", "echo", "wc", "head", "tail", "ls", "cut", "tr", "stat", "du", "diff", "cmp", "grep", "egrep", "fgrep"}
)
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


class _Cmd:
    __slots__ = ("words", "plain", "raw", "targets", "bodies", "offset", "piped", "feed")

    def __init__(self, offset: int, piped: bool) -> None:
        self.words: list[str] = []
        # ``plain[i]`` is True when ``words[i]`` was written exactly as it reads: no quote, escape or expansion.
        self.plain: list[bool] = []
        # ``raw[i]`` is the text of ``words[i]`` exactly as written, quotes and all.
        self.raw: list[str] = []
        self.targets: list[str] = []
        self.bodies: list[str] = []
        self.offset = offset
        self.piped = piped
        # The heredoc bodies that feed this command's stdin (its own and those earlier in its pipeline), or
        # ``None`` when there are more than ``_MAX_FEED``. Filled in once the scan is done.
        self.feed: list[str] | None = []


class _Ctx:
    __slots__ = ("cmds", "broken", "substitutions")

    def __init__(self) -> None:
        self.cmds: list[_Cmd] = []
        self.broken = False
        self.substitutions = 0


def _subst(text: str, i: int, ctx: _Ctx, depth: int, base: int) -> int:
    """Analyse the command substitution, backtick or parameter expansion opening at ``text[i]``.

    Returns the index after it. The inner text is scanned as commands of its own; a
    substitution that never closes breaks the scan (fail closed).
    """
    ctx.substitutions += 1
    if ctx.substitutions > _MAX_SUBSTITUTIONS:
        ctx.broken = True
        return len(text)
    if text.startswith("$((", i):
        # arithmetic expansion: a variable it names is itself evaluated, and a subscript in that value can run a command
        ctx.broken = True
        return len(text)
    if text.startswith("${", i):
        close = text.find("}", i + 2)
        inner = text[i + 2 : close]
        if (
            close == -1
            or "$(" in inner
            or "`" in inner
            or _ARITHMETIC_EXPANSION.search(inner)
            or _SUBST_BODY_BAD.search(inner)
        ):
            ctx.broken = True
            return len(text)
        return close + 1
    if text[i] == "`":
        close = text.find("`", i + 1)
        if close == -1 or _SUBST_BODY_BAD.search(text, i + 1, close):
            ctx.broken = True
            return len(text)
        _scan(text[i + 1 : close], base + i + 1, ctx, depth + 1)
        return close + 1
    level = 0
    for match in _PAREN.finditer(text, i + 1):
        level += 1 if match.group() == "(" else -1
        if level == 0:
            if _SUBST_BODY_BAD.search(text, i + 2, match.start()):
                break
            _scan(text[i + 2 : match.start()], base + i + 2, ctx, depth + 1)
            return match.end()
    ctx.broken = True
    return len(text)


def _has_brace_expansion(raw: str) -> bool:
    """Does the word as written have an unquoted ``{a,b}`` or ``{1..3}`` group?"""
    open_groups: list[bool] = []  # one flag per open brace: has a ``,`` or ``..`` been seen inside it
    quote = ""
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if quote:
            if c == quote:
                quote = ""
            elif c == "\\" and quote == '"':
                i += 1
        elif c == "\\":
            i += 1
        elif c in "'\"":
            quote = c
        elif c == "{":
            open_groups.append(False)
        elif c == "}" and open_groups:
            if open_groups.pop():
                return True
        elif open_groups and (c == "," or raw.startswith("..", i)):
            open_groups[-1] = True
        i += 1
    return False


def _read_word(text: str, i: int, ctx: _Ctx, depth: int, base: int) -> tuple[str, int]:
    """Read one shell word starting at ``text[i]``: quotes removed, expansions made opaque.

    A word with an unquoted brace expansion (``{-i,x}`` becomes two arguments) ends in ``_UNRESOLVED``.
    """
    word, end = _read_word_parts(text, i, ctx, depth, base)
    if "{" in text[i:end] and not ctx.broken and _has_brace_expansion(text[i:end]):
        word += _UNRESOLVED
    return word, end


def _read_word_parts(text: str, i: int, ctx: _Ctx, depth: int, base: int) -> tuple[str, int]:
    parts: list[str] = []
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n|&;<>()":
            break
        if c == "'":
            close = text.find("'", i + 1)
            if close == -1:
                ctx.broken = True
                return "".join(parts), n
            parts.append(text[i + 1 : close])
            i = close + 1
        elif c == '"':
            i += 1
            while True:
                match = _DQ_SPECIAL.match(text, i)
                if match:
                    parts.append(match.group())
                    i = match.end()
                if i >= n:
                    ctx.broken = True
                    return "".join(parts), n
                d = text[i]
                if d == '"':
                    i += 1
                    break
                if d == "\\":
                    nxt = text[i + 1 : i + 2]
                    parts.append(nxt if nxt in ('"', "\\", "$", "`") else "\\" + nxt)
                    i += 2
                elif text.startswith("$[", i):
                    ctx.broken = True
                    return "".join(parts), n
                elif d == "`" or text.startswith("$(", i) or text.startswith("${", i):
                    i = _subst(text, i, ctx, depth, base)
                    parts.append(_UNRESOLVED)
                else:
                    parts.append(_UNRESOLVED)
                    i += 1
        elif c == "\\":
            nxt = text[i + 1 : i + 2]
            if nxt == "\n":
                i += 2
                continue
            parts.append(nxt)
            i += 2
        elif text.startswith("$[", i):
            ctx.broken = True
            return "".join(parts), n
        elif c == "`" or text.startswith("$(", i) or text.startswith("${", i):
            i = _subst(text, i, ctx, depth, base)
            parts.append(_UNRESOLVED)
        elif c == "$":
            if text.startswith(("$'", '$"'), i):
                # an ANSI-C or locale-translated quote: its escapes (``\'``) hide the real end of the quote
                ctx.broken = True
                return "".join(parts), n
            match = _PARAM_NAME.match(text, i + 1)
            i = match.end() if match else i + 1
            parts.append(_UNRESOLVED)
        else:
            match = _WORD_RUN.match(text, i)
            parts.append(match.group())
            i = match.end()
    return "".join(parts), i


_COMPOUND_WORDS = frozenset({"if", "then", "elif", "else", "fi", "while", "until", "do", "done", "for", "{", "}", "!"})
# The words that open a frame: ``[kind, phase]`` (a ``for`` opens its frame once its header is read).
_OPENERS = {"if": ("if", "cond"), "while": ("loop", "cond"), "until": ("loop", "cond"), "{": ("brace", "")}


def _skip_blanks(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i] in " \t\r":
        i += 1
    return i


def _for_header(text: str, i: int, ctx: _Ctx, depth: int, base: int) -> int | None:
    """Read ``NAME in WORD... ;`` (or ``NAME ;``) after ``for``: the index after the terminator.

    The words are data, not commands (a command substitution among them is still scanned). ``None`` when the
    header is anything else: an arithmetic ``for ((``, a name that is not a plain identifier, an operator in the
    list, no terminator.
    """
    n = len(text)
    i = _skip_blanks(text, i)
    start = i
    name, i = _read_word(text, i, ctx, depth, base)
    if ctx.broken or text[start:i] != name or not _IDENTIFIER.fullmatch(name) or _EXPORTED_NAMES.fullmatch(name):
        return None
    i = _skip_blanks(text, i)
    if i < n and text[i] in ";\n":
        return None if text.startswith((";;", ";&"), i) else i + 1
    start = i
    word, i = _read_word(text, i, ctx, depth, base)
    if ctx.broken or word != "in" or text[start:i] != "in":
        return None
    while True:
        i = _skip_blanks(text, i)
        if i >= n:
            return None
        c = text[i]
        if c == ";":
            return None if text.startswith((";;", ";&"), i) else i + 1
        if c == "\n":
            return i + 1
        if c == "#":
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif c in "|&<>()":
            return None
        else:
            _, i = _read_word(text, i, ctx, depth, base)
            if ctx.broken:
                return None


def _scan(text: str, base: int, ctx: _Ctx, depth: int) -> None:
    """Split *text* into simple commands, appending them to ``ctx.cmds``.

    Heredoc bodies are attached to the command that opened them. Compound constructs are tracked with a stack
    of open frames; their reserved words (``for``, ``do``, ``done``, ``if``, ``then``, ``fi``, ``{``, ``}``, ...)
    are structure, not commands, and are recognised only as the first, unquoted word of a command. Anything the
    scanner cannot place sets ``ctx.broken``: an unterminated construct, a reserved word the grammar does not
    allow there, a ``case``/``select``/function/``coproc``, nesting past ``_MAX_COMPOUND_DEPTH``.
    """
    if depth > _MAX_DEPTH:
        ctx.broken = True
        return
    n = len(text)
    i = 0
    cmd: _Cmd | None = None
    next_piped = False
    pending: list[tuple[_Cmd, str, bool, bool]] = []
    last_word_end = -1
    # Open constructs, innermost last: [kind, phase]. Kinds and phases: "if" (cond, then, else),
    # "loop" (head: a ``for`` header was read and only ``do`` may follow; cond: a ``while``/``until`` condition;
    # body), "brace", "paren".
    frames: list[list] = []
    expect = False  # a command must come next: after ``if``, ``then``, ``do``, ``{``, ``!``, ``&&``, ``||``, ``|``
    closed = False  # a construct just closed: only a redirect, a separator or another ``)`` may follow

    def current(at: int) -> _Cmd:
        nonlocal cmd, expect
        if cmd is None:
            cmd = _Cmd(base + at, next_piped)
            ctx.cmds.append(cmd)
        expect = False
        return cmd

    while i < n and not ctx.broken:
        c = text[i]
        if c in " \t\r":
            i += 1
        elif c == "\n":
            cmd = None
            next_piped = False
            closed = False
            i += 1
            for owner, delimiter, dash, quoted in pending:
                body: list[str] = []
                found = False
                while i < n:
                    end = text.find("\n", i)
                    stop = n if end == -1 else end
                    line = text[i:stop]
                    i = stop + 1
                    if (line.lstrip("\t") if dash else line) == delimiter:
                        found = True
                        break
                    body.append(line)
                if not found:
                    ctx.broken = True
                joined = "\n".join(body)
                if not quoted and ("$" in joined or "`" in joined or "\\" in joined):
                    # an unquoted delimiter: bash expands ``$(...)``, backticks and ``$NAME`` in the body, and a
                    # backslash-newline joins lines (so ``EO\<newline>F`` ends the heredoc early)
                    ctx.broken = True
                owner.bodies.append(joined)
            pending = []
        elif c == "#":
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif c == ";":
            if text.startswith((";;", ";&"), i) or expect or (frames and frames[-1][1] == "head"):
                ctx.broken = True
                break
            cmd = None
            next_piped = False
            closed = False
            i += 1
        elif c == "(":
            if text.startswith("((", i) or cmd is not None or closed or (frames and frames[-1][1] == "head"):
                ctx.broken = True
                break
            frames.append(["paren", ""])
            expect = True
            i += 1
            if len(frames) > _MAX_COMPOUND_DEPTH:
                ctx.broken = True
        elif c == ")":
            if not frames or frames[-1][0] != "paren" or expect:
                ctx.broken = True
                break
            frames.pop()
            cmd = None
            next_piped = False
            closed = True
            i += 1
        elif c == "|":
            cmd = None
            closed = False
            expect = True
            if text.startswith("||", i):
                next_piped = False
                i += 2
            else:
                next_piped = True
                i += 2 if text.startswith("|&", i) else 1
        elif c == "&":
            if text.startswith("&>", i):
                i += 3 if text.startswith("&>>", i) else 2
                target, i = _read_target(text, i, ctx, depth, base)
                _add_target(current(i), target)
            elif text.startswith("&&", i):
                cmd = None
                next_piped = False
                closed = False
                expect = True
                i += 2
            else:
                if expect or (frames and frames[-1][1] == "head"):
                    ctx.broken = True
                    break
                cmd = None
                next_piped = False
                closed = False
                i += 1
        elif c == "<":
            if text.startswith("<<<", i):
                _, i = _read_target(text, i + 3, ctx, depth, base)
            elif text.startswith("<<", i):
                dash = text.startswith("<<-", i)
                read = _heredoc_delimiter(text, i + (3 if dash else 2))
                if read is None:
                    ctx.broken = True
                    break
                delimiter, quoted, end = read
                pending.append((current(i), delimiter, dash, quoted))
                i = end
            elif text.startswith("<(", i):
                i = _subst(text, i, ctx, depth, base)
            elif text.startswith("<>", i):
                _drop_fd_word(current(i), last_word_end, i)
                target, i = _read_target(text, i + 2, ctx, depth, base)
                _add_target(current(i), target)
            elif text.startswith("<&", i):
                end = _dup_end(text, i + 2)
                if end is None:
                    ctx.broken = True
                    break
                i = end
            else:
                _drop_fd_word(current(i), last_word_end, i)
                _, i = _read_target(text, i + 1, ctx, depth, base)
        elif c == ">":
            owner = current(i)
            _drop_fd_word(owner, last_word_end, i)
            j = i + 1
            if text.startswith(">>", i) or text.startswith(">|", i):
                j = i + 2
            elif text.startswith(">&", i):
                if _FD_DUP.match(text, i + 2):
                    end = _dup_end(text, i + 2)
                    if end is None:
                        ctx.broken = True
                        break
                    i = end
                    continue
                j = i + 2
            elif text.startswith(">(", i):
                _add_target(owner, _UNRESOLVED)
                i = _subst(text, i, ctx, depth, base)
                continue
            target, i = _read_target(text, j, ctx, depth, base)
            _add_target(owner, target)
        elif cmd is not None:
            owner = current(i)
            start = i
            word, i = _read_word(text, i, ctx, depth, base)
            owner.words.append(word)
            owner.plain.append(text[start:i] == word)
            owner.raw.append(text[start:i])
            last_word_end = i
        else:
            # The first word of a command: a reserved word (read as structure) or the head of a simple command.
            start = i
            word, i = _read_word(text, i, ctx, depth, base)
            if ctx.broken:
                break
            top = frames[-1] if frames else None
            if closed and not (word.isdigit() and i < n and text[i] in "<>"):
                ctx.broken = True
                break
            if top is not None and top[1] == "head" and word != "do":
                ctx.broken = True
                break
            if text[start:i] != word or (word not in _COMPOUND_WORDS and word not in _REJECTED_WORDS):
                owner = current(start)
                owner.words.append(word)
                owner.plain.append(text[start:i] == word)
                owner.raw.append(text[start:i])
                last_word_end = i
                continue
            if word in _REJECTED_WORDS:
                ctx.broken = True
            elif word == "!":
                expect = True
            elif word in _OPENERS:
                frames.append(list(_OPENERS[word]))
                expect = True
                if len(frames) > _MAX_COMPOUND_DEPTH:
                    ctx.broken = True
            elif word == "for":
                end = _for_header(text, i, ctx, depth, base)
                if end is None:
                    ctx.broken = True
                    break
                i = end
                frames.append(["loop", "head"])
                expect = False
                if len(frames) > _MAX_COMPOUND_DEPTH:
                    ctx.broken = True
            elif top is None:
                ctx.broken = True
            elif word == "then" and top[0] == "if" and top[1] == "cond" and not expect:
                top[1] = "then"
                expect = True
            elif word == "elif" and top[0] == "if" and top[1] == "then" and not expect:
                top[1] = "cond"
                expect = True
            elif word == "else" and top[0] == "if" and top[1] == "then" and not expect:
                top[1] = "else"
                expect = True
            elif word == "fi" and top[0] == "if" and top[1] in ("then", "else") and not expect:
                frames.pop()
                closed = True
            elif word == "do" and top[0] == "loop" and top[1] in ("cond", "head") and not expect:
                top[1] = "body"
                expect = True
            elif word == "done" and top[0] == "loop" and top[1] == "body" and not expect:
                frames.pop()
                closed = True
            elif word == "}" and top[0] == "brace" and not expect:
                frames.pop()
                closed = True
            else:
                ctx.broken = True
    if (pending or frames) and not ctx.broken:
        ctx.broken = True


def _heredoc_delimiter(text: str, i: int) -> tuple[str, bool, int] | None:
    """Read the delimiter word of a heredoc starting at ``text[i]``: ``(delimiter, quoted, end)`` or ``None``.

    Only three shapes are read: a bare word (``[A-Za-z_][A-Za-z0-9_.-]*``), one fully quoted word (``'WORD'``,
    ``"WORD"``) and a backslash-prefixed word (``\\WORD``), with the body made of ``[A-Za-z0-9_.-]``. A mid-word
    quote, any other character, or a word that runs into a character the shell would glue onto it
    (``EOF#x``, ``EOF:x``) is ``None``: the scanner cannot tell what delimiter bash reads.
    """
    n = len(text)
    while i < n and text[i] in " \t":
        i += 1
    if i >= n:
        return None
    c = text[i]
    if c in "'\"":
        close = text.find(c, i + 1)
        if close == -1 or _HEREDOC_BODY.fullmatch(text, i + 1, close) is None:
            return None
        word, quoted, end = text[i + 1 : close], True, close + 1
    elif c == "\\":
        match = _HEREDOC_BODY.match(text, i + 1)
        if match is None:
            return None
        word, quoted, end = match.group(), True, match.end()
    else:
        match = _HEREDOC_BARE.match(text, i)
        if match is None:
            return None
        word, quoted, end = match.group(), False, match.end()
    if end < n and text[end] not in _HEREDOC_END:
        return None
    return word, quoted, end


def _dup_end(text: str, i: int) -> int | None:
    """The end of the file-descriptor duplication operand at ``text[i]`` (``1``, ``1-``, ``-``), or ``None``.

    ``None`` when there is none or when something is glued to it (``>&1#``, ``>&2foo``): bash then reads the
    whole word as a file name, which the scanner would otherwise take for a duplication followed by more text.
    """
    dup = _FD_DUP.match(text, i)
    if dup is None:
        return None
    end = dup.end()
    return end if end >= len(text) or text[end] in " \t\n;|&<>()" else None


def _drop_fd_word(owner: _Cmd, last_word_end: int, at: int) -> None:
    """A redirect written ``2>file`` reads ``2`` as a word first; take it back."""
    if last_word_end == at and owner.words and owner.words[-1].isdigit():
        owner.words.pop()
        owner.plain.pop()
        owner.raw.pop()


def _read_target(text: str, i: int, ctx: _Ctx, depth: int, base: int) -> tuple[str, int]:
    n = len(text)
    while i < n and text[i] in " \t":
        i += 1
    return _read_word(text, i, ctx, depth, base)


def _add_target(owner: _Cmd, target: str) -> None:
    if _DEV_OK.fullmatch(target):
        return
    owner.targets.append(target if target else _UNRESOLVED)


# --------------------------------------------------------------------------- effects of one command

_RO, _WRITE, _UNKNOWN = "ro", "write", "unknown"
_Effect = tuple[str, list[str]]

# The only names a leading ``NAME=value`` (and ``env NAME=value``) may set: presentation and determinism, never a
# path, a program, an option string or a config. The value must be a plain literal.
_SAFE_ENV_NAMES = frozenset(
    {
        "LANG", "LC_ALL", "LC_CTYPE", "TZ", "NO_COLOR", "FORCE_COLOR", "TERM", "COLUMNS", "LINES", "CI",
        "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "PYTHONHASHSEED",
    }
)
_SAFE_ENV_VALUE = re.compile(r"[A-Za-z0-9_./:=,-]*")
# A bare ``NAME=value;`` statement sets a shell variable, which only reaches a later command when the variable is
# already exported. These are the names whose export every later command reads, so they are never accepted.
_EXPORTED_NAMES = re.compile(
    r"(?:PATH|HOME|SHELL|TMPDIR|BASH_ENV|ENV|PS4|PROMPT_COMMAND|SHELLOPTS|BASHOPTS|CDPATH|PAGER|EDITOR|VISUAL"
    r"|LD_\w*|DYLD_\w*|GIT_\w*|PYTHON\w*|PYTEST_\w*|RUFF_\w*|MYPY\w*|UV_\w*|LESS\w*|XDG_\w*|BLACK_\w*|ISORT_\w*)"
)
_WRAPPERS = frozenset({"command", "nohup", "time", "exec", "env", "sudo", "nice"})
# Words that are never read as structure or as a command: the scan breaks (``source``). ``[[ ]]`` is here on
# purpose: it evaluates its operands as arithmetic, so a ``$(...)`` in a subscript runs.
_REJECTED_WORDS = frozenset({"case", "esac", "select", "function", "coproc", "in", "[["})
_READ_ONLY_HEADS = frozenset(
    {
        "cat", "ls", "grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "sort", "uniq", "diff", "cmp", "echo",
        "printf", "pwd", "cd", "which", "type", "true", "false", "test", "[", "sleep", "date", "tree", "stat", "file",
        "du", "tr", "cut", "jq", "less", "more",
        # shell builtins the compound forms need, only with plain literal arguments (``_command_effect``): the
        # no-op and the loop controls. ``read`` and ``[[`` are not here: both evaluate a subscripted name as
        # arithmetic, so a ``$(...)`` inside it runs.
        ":", "break", "continue",
    }
)
_FIND_WRITES = frozenset(
    {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
)
_GIT_READ_ONLY = frozenset({"status", "diff", "log", "show", "rev-parse", "ls-files", "blame", "describe"})
_GIT_BRANCH_READ = frozenset({"-a", "-r", "--list", "-l", "-v", "-vv", "--show-current", "--all", "--remotes"})
_GIT_FLAGS = frozenset({"--no-pager", "--no-optional-locks", "--no-replace-objects", "--literal-pathspecs"})
_LITERAL_VALUE = re.compile(r"[A-Za-z0-9_./:=,-]*")
_COLOR_KEY = re.compile(r"color\.[A-Za-z0-9.-]+")
_PYTHON_HEAD = re.compile(r"python(?:\d+(?:\.\d+)*)?")
# ``uv run`` options that take a value and cannot name a path or a project (a ``--with`` value is checked apart).
_UV_VALUE_OPTIONS = frozenset({"--python", "-p", "--extra", "--group"})
# ``uv run`` options that point it at another project, a cache, a requirements file or an index: ``uv run`` syncs
# the environment it finds there, which writes (``.venv``, ``uv.lock``, an ``egg-info``) wherever that is.
_UV_BLOCKED_OPTIONS = frozenset(
    {
        "--directory", "--project", "--cache-dir", "--with-editable", "--with-requirements", "--env-file",
        "--find-links", "--index", "--default-index", "--index-url", "--extra-index-url", "--config-file",
    }
)
_INLINE_PROGRAMS = frozenset({"pytest", "py.test", "ruff", "black", "isort", "mypy"})
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
_INTEGER = re.compile(r"[0-9]+")
_SIGNED_INTEGER = re.compile(r"[-+]?[0-9]+")


# The directories a path-qualified command word may name: the system program directories. A head written
# ``./cat``, ``lib/cat`` or ``/tmp/cat`` runs whatever file is there, whatever its name.
_SYSTEM_BIN_DIRS = frozenset({"/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"})


def _head_base(word: str) -> str | None:
    """The program name a command word runs: the word itself, or the basename of an absolute system path.

    ``None`` for every other path-qualified word (``./cat``, ``lib/cat``, ``/tmp/cat``, ``/bin//cat``): only the
    basename of such a word was ever looked at, so a file named like a read-only program passed for it.
    """
    word = word.lstrip("\\")
    if "/" not in word:
        return word
    directory, _, base = word.rpartition("/")
    return base if base and directory in _SYSTEM_BIN_DIRS else None


def _positionals(args: list[str], value_options: frozenset[str] | set[str] = frozenset()) -> list[str]:
    out: list[str] = []
    skip = False
    ended = False
    for arg in args:
        if skip:
            skip = False
        elif ended:
            out.append(arg)
        elif arg in value_options:
            skip = True
        elif arg == "--":
            ended = True
        elif not arg.startswith("-") or arg == "-":
            out.append(arg)
    return out


def _env_assignment_ok(word: str) -> bool:
    name, _, value = word.partition("=")
    return name in _SAFE_ENV_NAMES and _SAFE_ENV_VALUE.fullmatch(value) is not None


def _strip_wrappers(words: list[str]) -> list[str] | None:
    """The words of the command that a prefix and its wrappers lead to, or ``None`` when they are not provably harmless.

    A ``NAME=value`` prefix is accepted only for ``_SAFE_ENV_NAMES`` with a plain literal value. ``env`` and ``exec``
    take no option, ``sudo``, ``nohup``, ``time`` and ``command`` take none either, and ``nice`` only a literal
    ``-n N``: a wrapper option can run, redirect or reconfigure what follows (``env -S``, ``exec -a``, ``sudo -u``).
    A command that is only assignments (``X=1; ...``) is a shell variable, refused only for the names whose export
    every later command reads.
    """
    i = 0
    n = len(words)
    assigns: list[str] = []
    wrapped = False
    while i < n:
        word = words[i].lstrip("\\")
        base = _head_base(word)
        if _ASSIGNMENT.match(word):
            assigns.append(word)
            i += 1
        elif base in _WRAPPERS:
            wrapped = True
            i += 1
            if base == "nice" and i + 1 < n and words[i] == "-n" and _INTEGER.fullmatch(words[i + 1]):
                i += 2
            elif i < n and words[i].startswith("-"):
                return None
        else:
            break
    if i >= n and not wrapped:
        for word in assigns:
            if _EXPORTED_NAMES.fullmatch(word.split("=", 1)[0].rstrip("+")):
                return None
        return []
    if not all(_env_assignment_ok(word) for word in assigns):
        return None
    return words[i:]


def _combine(parts: list[_Effect]) -> _Effect:
    targets: list[str] = []
    for kind, found in parts:
        if kind == _UNKNOWN:
            return _UNKNOWN, []
        targets.extend(found)
    return (_WRITE, targets) if targets else (_RO, [])


def _bad_cd(cmds: list[_Cmd]) -> bool:
    """In a call with a write: a ``cd`` whose target is not a plain literal path outside ``src``.

    A write's target is classified by its text, so a ``cd`` that can land in ``src`` (a quote-glued name, an
    expansion, ``..``, ``-``, no argument, a ``src`` segment) or an ``eval`` (which can run a ``cd`` the scan
    never sees) leaves the write's place unknown. ``CDPATH`` can do the same to a plain relative name; an
    assignment to it is refused earlier, by ``_strip_wrappers`` (a prefix) and as an exported name (a bare one).
    """
    for cmd in cmds:
        words = _strip_wrappers(cmd.words)
        if not words:
            continue
        head = _head_base(words[0])
        if head == "eval":
            return True
        if head not in ("cd", "pushd"):
            continue
        args = words[1:]
        plain = cmd.plain[len(cmd.words) - len(args) :]
        if len(args) != 1 or not plain[0]:
            return True
        target = args[0]
        segments = target.split("/")
        if (
            not target
            or target.startswith("-")
            or _UNRESOLVED in target
            or any(ch in _CD_GLOB for ch in target)
            or ".." in segments
            or (not target.startswith("/") and _SRC_TOKEN.search(target))
        ):
            return True
    return False


def _is_bare_cat(cmd: _Cmd) -> bool:
    """Is *cmd* a ``cat`` with no operand and no file redirect: a command that passes its stdin through unchanged?"""
    if cmd.targets:
        return False
    words = _strip_wrappers(cmd.words)
    return words is not None and len(words) == 1 and _head_base(words[0]) == "cat"


def _feeds(cmds: list[_Cmd]) -> None:
    """Fill in ``Cmd.feed``: a command's own heredoc bodies after those of the bare ``cat`` piped into it.

    A heredoc body reaches an interpreter's stdin only directly or through ``cat`` with no operand: any other
    command between them (``sed``, ``tr``, ``tee``, ``cat -n``, ``cat x``) can change the script the classifier
    reads, so nothing is inherited through it and the interpreter, with no script to read, is ``source``.
    """
    previous: list[str] | None = []
    passes = False
    for cmd in cmds:
        inherited = previous if cmd.piped and passes else []
        if inherited is None or len(inherited) + len(cmd.bodies) > _MAX_FEED:
            cmd.feed = None
        else:
            cmd.feed = inherited + cmd.bodies if inherited else cmd.bodies
        previous = cmd.feed
        passes = _is_bare_cat(cmd)


@functools.lru_cache(maxsize=256)
def _text_effect(text: str, depth: int) -> tuple[_Effect, int | None, bool]:
    """Scan *text* and combine its commands: ``(effect, first non-read-only offset, broken)``.

    Cached: the same heredoc body is analysed once however many shells it is piped into.
    """
    if _CONTROL_CHARS.search(text):
        # a carriage return or any other control character: the scanner and the shell can read it differently
        return (_UNKNOWN, []), 0, True
    if "${(" in text:
        # a zsh parameter-expansion flag (``${(e)x}`` evaluates its value as a command line): the Bash tool can run under zsh
        return (_UNKNOWN, []), 0, True
    ctx = _Ctx()
    _scan(text, 0, ctx, depth)
    if ctx.broken:
        return (_UNKNOWN, []), 0, True
    _feeds(ctx.cmds)
    parts: list[_Effect] = []
    first: int | None = None
    for index, cmd in enumerate(ctx.cmds):
        effect = _command_effect(cmd, ctx.cmds, index, depth)
        if effect[0] != _RO and first is None:
            first = cmd.offset
        parts.append(effect)
    combined = _combine(parts)
    if combined[0] == _WRITE and _bad_cd(ctx.cmds):
        combined = (_UNKNOWN, [])
    return combined, first, False


@functools.lru_cache(maxsize=64)
def _top_effect(command: str) -> tuple[_Effect, int | None, bool]:
    """``_text_effect`` of a whole command, cached: the classifier and the offset both ask."""
    return _text_effect(command, 0)


def _stdin_scripts(cmds: list[_Cmd], index: int) -> list[str] | None:
    """Heredoc bodies that feed command *index* (its own, then those of a bare ``cat`` before it); ``None`` if too many."""
    return cmds[index].feed


def _command_effect(cmd: _Cmd, cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    redirects: _Effect = (_WRITE, list(cmd.targets)) if cmd.targets else (_RO, [])
    words = _strip_wrappers(cmd.words)
    if words is None:
        return _UNKNOWN, []
    if not words:
        return redirects
    head = words[0].lstrip("\\")
    if _UNRESOLVED in head:
        return _UNKNOWN, []
    base = _head_base(head)
    if base is None:
        return _UNKNOWN, []
    args = words[1:]
    if base in (":", "break", "continue"):
        plain = cmd.plain[len(cmd.words) - len(args) :]
        if not all(ok and _PLAIN_ARG.fullmatch(arg) for ok, arg in zip(plain, args)):
            return _UNKNOWN, []
    effect = _head_effect(base, args, cmds, index, depth)
    if effect[0] != _UNKNOWN and any(_UNRESOLVED in arg for arg in args):
        # An unresolved word can carry a flag or a second target (``sed -i "s/a/$x/" tests/f`` with ``x='b/;w src/f;s/a/b'``,
        # ``cp $f tests/y`` with ``f='-t src'``): read-only only for a head that cannot write whatever it is
        # given, and a write head with one is not a recognised write at all.
        raws = cmd.raw[len(cmd.words) - len(args) :]
        if effect[0] != _RO or not _expansion_safe(base, args, raws):
            return _UNKNOWN, []
    return _combine([redirects, effect])


# ``test``/``[`` words that are an operator whose NEXT word is a plain operand (never itself an operator):
# the unary file and string tests and the binary comparisons. ``-a``, ``-o``, ``!`` and ``(`` are not here: the
# word after them starts a new expression, where an expansion could become an operator. ``-v`` and ``-R`` are not
# here either (they evaluate a subscript), and neither is ``-t``.
_TEST_OPERAND_AFTER = frozenset(
    {
        "-e", "-f", "-d", "-r", "-w", "-x", "-s", "-L", "-h", "-p", "-S", "-b", "-c", "-g", "-k", "-u", "-G", "-N",
        "-O", "-z", "-n", "=", "==", "!=", "<", ">", "-eq", "-ne", "-lt", "-le", "-gt", "-ge", "-nt", "-ot", "-ef",
    }
)
_TEST_ARITHMETIC = frozenset({"-eq", "-ne", "-lt", "-le", "-gt", "-ge"})


def _is_double_quoted(raw: str) -> bool:
    """Is the word written as one double-quoted string, with no other quote in it?"""
    return len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"' and '"' not in raw[1:-1]


def _expansion_safe(base: str, args: list[str], raws: list[str]) -> bool:
    """May a call stay read-only with an unresolved expansion among *args* of this head?

    Only for a head that cannot write or run code whatever it is given. ``test`` and ``[`` can when an
    unresolved word is split into, or lands in the place of, an operator such as ``-v`` (which evaluates a
    subscript): an unresolved word is allowed only when it is one double-quoted string (so it cannot be split) and
    the word before it is a literal operator that takes a plain operand. ``printf`` only when its format is a literal.
    """
    if base in _EXPANSION_SAFE_HEADS:
        return True
    if base in ("test", "["):
        return all(
            _UNRESOLVED not in arg
            or (k > 0 and _is_double_quoted(raws[k]) and args[k - 1] in _TEST_OPERAND_AFTER)
            for k, arg in enumerate(args)
        )
    if base == "printf":
        return bool(args) and _UNRESOLVED not in args[0]
    return False


# --------------------------------------------------------------------------- heads


def _head_effect(base: str, args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    if base in _READ_ONLY_HEADS:
        return _read_only_head(base, args)
    if base == "find":
        return (_UNKNOWN, []) if any(arg in _FIND_WRITES for arg in args) else (_RO, [])
    if base == "xargs":
        return _xargs(args)
    if base in ("awk", "gawk", "mawk"):
        return _awk(args)
    if base == "sed":
        return _sed(args)
    if base == "git":
        return _git(args)
    if base == "perl":
        return _perl(args)
    if base in ("tee", "touch", "mkdir", "cp", "mv", "rm", "rmdir"):
        return _file_writer(base, args)
    if base in ("uv", "uvx"):
        return _uv(base, args, cmds, index, depth)
    if base in _SHELLS:
        return _shell(args, cmds, index, depth)
    if base == "eval":
        text = " ".join(args)
        if _UNRESOLVED in text or depth >= _MAX_DEPTH:
            return _UNKNOWN, []
        return _text_effect(text, depth + 1)[0]
    return _program(base, args, cmds, index, depth)


# The tools whose command line reads ``@file`` as more arguments (argparse ``fromfile_prefix_chars``), so a word
# that starts with ``@``, or an option value that does, can bring any option the text never shows.
_ARGFILE_TOOLS = frozenset({"pytest", "py.test", "ruff", "black", "isort", "mypy"})
_ARGFILE_VALUE = re.compile(r"-[-A-Za-z0-9]*=?@")


def _argfile_word(arg: str) -> bool:
    return arg.startswith("@") or _ARGFILE_VALUE.match(arg) is not None


def _program(base: str, args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    """A program run directly or through ``uv run`` / ``python -m``: only the allow-listed ones."""
    if base in _ARGFILE_TOOLS and any(_argfile_word(arg) for arg in args):
        return _UNKNOWN, []
    if base in ("pytest", "py.test"):
        return (_RO, []) if _pytest_options_ok(args) else (_UNKNOWN, [])
    if _PYTHON_HEAD.fullmatch(base):
        return _python(args, cmds, index, depth)
    if base == "ruff":
        return _ruff(args)
    if base in ("black", "isort"):
        return _formatter(args)
    if base == "mypy":
        return (_RO, []) if _mypy_options_ok(args) else (_UNKNOWN, [])
    return _UNKNOWN, []


def _read_only_head(base: str, args: list[str]) -> _Effect:
    if base == "sort" and not _sort_ok(args):
        return _UNKNOWN, []
    if base == "uniq" and not _uniq_ok(args):
        return _UNKNOWN, []
    if base == "tree" and not _tree_ok(args):
        return _UNKNOWN, []
    if base == "date" and any(arg in ("-s", "--set") or arg.startswith("--set=") for arg in args):
        return _UNKNOWN, []
    if base == "rg" and any(arg.startswith(("--pre", "--hostname")) for arg in args):
        return _UNKNOWN, []
    if base in ("less", "more") and any(arg.startswith(("-", "+")) and arg != "-" for arg in args):
        # ``less -o FILE`` logs its input, ``+!cmd`` runs a command: only a plain file operand is read-only
        return _UNKNOWN, []
    if base == "file" and any(_file_compiles(arg) for arg in args):
        return _UNKNOWN, []
    if base == "printf" and any(arg.startswith("-v") for arg in args):
        return _UNKNOWN, []
    if base in ("test", "["):
        if any(arg in ("-v", "-R") for arg in args):
            return _UNKNOWN, []
        for k, arg in enumerate(args):
            if arg in _TEST_ARITHMETIC and not (
                0 < k < len(args) - 1
                and _SIGNED_INTEGER.fullmatch(args[k - 1])
                and _SIGNED_INTEGER.fullmatch(args[k + 1])
            ):
                # an arithmetic comparison evaluates its operands as arithmetic on some shells: literal integers only
                return _UNKNOWN, []
    return _RO, []


def _file_compiles(arg: str) -> bool:
    """``file -C`` compiles a magic file (it writes ``FILE.mgc``)."""
    if arg.startswith("--"):
        return arg.startswith("--c")
    return arg.startswith("-") and "C" in arg


_UNIQ_VALUE_OPTIONS = frozenset({"-f", "-s", "-w", "--skip-fields", "--skip-chars", "--check-chars"})


def _uniq_ok(args: list[str]) -> bool:
    """``uniq IN OUT`` writes ``OUT``: at most one operand, counting every word after the first operand as one.

    BSD ``uniq`` (macOS) does not permute its arguments, so a ``-c`` written after the input file is the output
    file's name; GNU ``uniq`` reads it as a flag. Counting every later word covers both.
    """
    operands = 0
    i = 0
    n = len(args)
    while i < n:
        arg = args[i]
        i += 1
        if operands == 0:
            if arg == "--":
                operands = n - i
                break
            if arg in _UNIQ_VALUE_OPTIONS:
                i += 1
            elif not arg.startswith("-") or arg == "-":
                operands = 1
        else:
            operands += 1
    return operands <= 1
_SORT_FLAGS = frozenset("unrfbdghVszcCiMR")
_SORT_LONG = frozenset(
    {
        "--unique", "--numeric-sort", "--reverse", "--ignore-case", "--ignore-leading-blanks", "--dictionary-order",
        "--general-numeric-sort", "--human-numeric-sort", "--version-sort", "--stable", "--zero-terminated", "--check",
        "--month-sort", "--random-sort", "--ignore-nonprinting", "--key", "--field-separator",
    }
)


def _sort_ok(args: list[str]) -> bool:
    """Only read flags: every long option spelled in full, no ``-o``/``--output``/``-T``/``--compress-program`` in any form."""
    i = 0
    n = len(args)
    while i < n:
        arg = args[i]
        i += 1
        if arg == "--":
            return True
        if arg == "-" or not arg.startswith("-"):
            continue
        if arg.startswith("--"):
            if arg.split("=", 1)[0] not in _SORT_LONG:
                return False
            continue
        for position in range(1, len(arg)):
            letter = arg[position]
            if letter in _SORT_FLAGS:
                continue
            if letter in "kt":
                if position == len(arg) - 1:
                    i += 1  # the key definition or separator is the next word
                break
            return False
    return True


def _tree_ok(args: list[str]) -> bool:
    """``tree -o FILE`` writes its listing, and ``-R`` rewrites HTML files: refuse ``o`` and ``R`` in any cluster."""
    for arg in args:
        if arg == "--":
            return True
        if arg.startswith("--"):
            if arg.startswith(("--o", "--fromfile")):
                return False
        elif arg.startswith("-") and arg != "-" and ("o" in arg or "R" in arg):
            return False
    return True


# A child that cannot write or run anything whatever extra words arrive on its command line (``xargs`` appends
# its stdin to the child's arguments, so the arguments are not the text's to know).
_XARGS_CHILDREN = frozenset({"cat", "grep", "egrep", "fgrep", "wc", "ls", "head", "tail", "echo", "printf"})


def _xargs(args: list[str]) -> _Effect:
    i = 0
    n = len(args)
    while i < n and args[i].startswith("-"):
        if args[i] == "-0":
            i += 1
        elif args[i] == "-n" and i + 1 < n and _INTEGER.fullmatch(args[i + 1]):
            i += 2
        elif args[i] == "-I" and i + 1 < n and args[i + 1] == "{}":
            i += 2
        else:
            return _UNKNOWN, []
    if i >= n:
        return _RO, []
    return (_RO, []) if _head_base(args[i]) in _XARGS_CHILDREN else (_UNKNOWN, [])


# --------------------------------------------------------------------------- awk

_AWK_BAD_WORDS = ("system", "getline", "close", "fflush", "inplace", "@")


def _awk(args: list[str]) -> _Effect:
    """``awk`` with only ``-F`` and ``-v`` and a program that has no output redirection, pipe or command.

    A ``>`` or ``|`` in a program that prints is a redirect or a pipe (a quote inside a regex can hide it from any
    scan that tracks strings, so the whole text is searched); a program with no ``print`` has none.
    """
    i = 0
    n = len(args)
    while i < n:
        arg = args[i]
        if arg == "--":
            i += 1
            break
        if not arg.startswith("-") or arg == "-":
            break
        if arg in ("-F", "-v"):
            i += 2
        elif arg.startswith(("-F", "-v")):
            i += 1
        else:
            return _UNKNOWN, []
    if i >= n:
        return _UNKNOWN, []
    program = args[i]
    if len(program) > _MAX_SCRIPT or any(word in program for word in _AWK_BAD_WORDS):
        return _UNKNOWN, []
    if "print" in program:
        # ``>=`` and ``||`` are comparison and logic; a lone ``>`` or ``|`` in a printing program is a redirect or a pipe
        bare = program.replace(">=", "").replace("||", "")
        if ">" in bare or "|" in bare:
            return _UNKNOWN, []
    return _RO, []


# --------------------------------------------------------------------------- sed

_SED_LONG = frozenset({"--quiet", "--silent", "--regexp-extended", "--separate", "--null-data", "--posix"})
_SED_FLAG_LETTERS = frozenset("nErszu")
_SED_ADDRESS_FLAGS = frozenset("IM")
_SED_S_FLAGS = frozenset("gpiImM0123456789")
_DIGITS = frozenset("0123456789")


def _sed_delimiter_ok(delim: str) -> bool:
    return len(delim) == 1 and ord(delim) < 128 and not delim.isalnum() and delim not in " \t\r\n\\["


def _sed_skip_bracket(script: str, j: int) -> int:
    """The index after the bracket expression opening at ``script[j]`` (the BSD reading), or ``-1``."""
    n = len(script)
    k = j + 1
    if k < n and script[k] == "^":
        k += 1
    if k < n and script[k] == "]":
        k += 1
    while k < n:
        c = script[k]
        if c == "]":
            return k + 1
        if c == "\n":
            return -1
        if c == "[" and k + 1 < n and script[k + 1] in ".=:":
            end = script.find(script[k + 1] + "]", k + 2)
            if end < 0:
                return -1
            k = end + 2
        else:
            k += 1
    return -1


def _sed_bracket_end(script: str, start: int, delim: str) -> int:
    """Where a delimited part ends when ``[...]`` hides the delimiter (BSD sed), or ``-1``."""
    n = len(script)
    j = start
    while j < n:
        c = script[j]
        if c == "[":
            j = _sed_skip_bracket(script, j)
            if j < 0:
                return -1
        elif c == "\\":
            j += 2
        elif c == delim:
            return j
        elif c == "\n":
            return -1
        else:
            j += 1
    return -1


def _sed_delimited(script: str, start: int, delim: str, replacement: bool) -> int | None:
    """The index after the closing *delim* of the part that starts at *start*; ``None`` if unreadable or ambiguous.

    GNU sed ends a part at the first unescaped delimiter, BSD sed skips bracket expressions first. A part is read
    only when both readings agree, so a ``[`` that hides the delimiter from one of them makes the script ``source``.
    """
    n = len(script)
    j = start
    while j < n:
        c = script[j]
        if c == "\\":
            if j + 1 >= n or (script[j + 1] == "\n" and not replacement):
                return None
            j += 2
        elif c == "\n":
            return None
        elif c == delim:
            break
        else:
            j += 1
    else:
        return None
    if replacement or _sed_bracket_end(script, start, delim) == j:
        return j + 1
    return None


def _sed_address(script: str, i: int) -> int | None:
    """The index after the address at *i* (``i`` itself when there is none), or ``None`` when it is malformed."""
    n = len(script)
    if i >= n:
        return i
    c = script[i]
    if c in _DIGITS:
        j = i
        while j < n and script[j] in _DIGITS:
            j += 1
        if j < n and script[j] == "~":
            k = j + 1
            while k < n and script[k] in _DIGITS:
                k += 1
            if k == j + 1:
                return None
            j = k
        return j
    if c == "$":
        return i + 1
    if c == "/":
        end = _sed_delimited(script, i + 1, "/", False)
    elif c == "\\":
        if i + 1 >= n or not _sed_delimiter_ok(script[i + 1]):
            return None
        end = _sed_delimited(script, i + 2, script[i + 1], False)
    else:
        return i
    if end is None:
        return None
    while end < n and script[end] in _SED_ADDRESS_FLAGS:
        end += 1
    return end


def _sed_blanks(script: str, i: int) -> int:
    n = len(script)
    while i < n and script[i] in " \t":
        i += 1
    return i


def _sed_end(script: str, i: int) -> int | None:
    """After a command: blanks, then a separator, a closing brace or the end."""
    i = _sed_blanks(script, i)
    return i if i >= len(script) or script[i] in ";\n}" else None


def _sed_script_ok(script: str) -> bool:
    """Is *script* only ``p d n N = q Q l y s`` commands (with the ``s`` flags ``g p i I m M`` and digits)?

    Everything else, in particular ``w W e E r R F z`` and the ``s`` flags ``w`` and ``e``, and anything the scanner
    cannot parse, is not read-only.
    """
    if len(script) > _MAX_SCRIPT:
        return False
    n = len(script)
    i = 0
    depth = 0
    while True:
        while i < n and script[i] in " \t\n;":
            i += 1
        if i >= n:
            return depth == 0
        j = _sed_address(script, i)
        if j is None:
            return False
        has_address = j > i
        i = j
        if has_address:
            i = _sed_blanks(script, i)
            if i < n and script[i] == ",":
                i = _sed_blanks(script, i + 1)
                if i < n and script[i] in "+~":
                    j = i + 1
                    while j < n and script[j] in _DIGITS:
                        j += 1
                    if j == i + 1:
                        return False
                else:
                    j = _sed_address(script, i)
                    if j is None or j == i:
                        return False
                i = j
            i = _sed_blanks(script, i)
            while i < n and script[i] == "!":
                i = _sed_blanks(script, i + 1)
        if i >= n:
            return False
        c = script[i]
        if c == "{":
            depth += 1
            if depth > _MAX_COMPOUND_DEPTH:
                return False
            i += 1
        elif c == "}":
            depth -= 1
            if has_address or depth < 0:
                return False
            end = _sed_end(script, i + 1)
            if end is None:
                return False
            i = end
        elif c in "pdnN=":
            end = _sed_end(script, i + 1)
            if end is None:
                return False
            i = end
        elif c in "qQl":
            j = _sed_blanks(script, i + 1)
            while j < n and script[j] in _DIGITS:
                j += 1
            end = _sed_end(script, j)
            if end is None:
                return False
            i = end
        elif c in "ys":
            if i + 1 >= n or not _sed_delimiter_ok(script[i + 1]):
                return False
            delim = script[i + 1]
            j = _sed_delimited(script, i + 2, delim, False)
            if j is None:
                return False
            j = _sed_delimited(script, j, delim, c == "s")
            if j is None:
                return False
            if c == "s":
                while j < n and script[j] in _SED_S_FLAGS:
                    j += 1
            end = _sed_end(script, j)
            if end is None:
                return False
            i = end
        else:
            return False


def _sed(args: list[str]) -> _Effect:
    in_place = False
    explicit = False
    scripts: list[str] = []
    operands: list[str] = []
    i = 0
    n = len(args)
    options_done = False
    while i < n:
        arg = args[i]
        i += 1
        if options_done or arg == "-" or not arg.startswith("-"):
            operands.append(arg)
        elif arg == "--":
            options_done = True
        elif arg.startswith("--"):
            name, equals, value = arg.partition("=")
            if name == "--expression" and equals:
                explicit = True
                scripts.append(value)
            elif name == "--in-place":
                in_place = True
            elif arg not in _SED_LONG:
                return _UNKNOWN, []
        else:
            position = 1
            while position < len(arg):
                letter = arg[position]
                if letter == "i":
                    in_place = True
                    break
                if letter == "e":
                    explicit = True
                    if position == len(arg) - 1:
                        if i >= n:
                            return _UNKNOWN, []
                        scripts.append(args[i])
                        i += 1
                    else:
                        scripts.append(arg[position + 1 :])
                    break
                if letter not in _SED_FLAG_LETTERS:
                    return _UNKNOWN, []
                position += 1
    if in_place:
        operands = [operand for operand in operands if operand != ""]
    if not explicit:
        if not operands:
            return _UNKNOWN, []
        scripts.append(operands.pop(0))
    if not _sed_script_ok("\n".join(scripts)):
        return _UNKNOWN, []
    if in_place:
        return (_WRITE, operands) if operands else (_UNKNOWN, [])
    return _RO, []


_PERL_FLAG_LETTERS = frozenset("pnlaw0123456789")
_PERL_S_FLAGS = frozenset("gimsx")
# In an in-place script no code may be spelled: ``(?{``, ``(??{`` and ``\\e`` are refused whole, a ``@``, ``%`` or
# backtick anywhere is refused, and a ``$`` only when a digit or ``&`` follows it (``$1``, ``$&``).
_PERL_CODE_MARKERS = ("(?{", "(??{", "\\e")
_PERL_VARIABLE_AFTER_DOLLAR = frozenset("0123456789&")
# The text glued to ``-i`` is the backup suffix; a ``/`` or ``*`` in it moves the backup file elsewhere.
_PERL_SUFFIX = re.compile(r"\.?[A-Za-z0-9_~-]*")


def _perl_part_end(code: str, start: int, delim: str) -> int | None:
    """The index after the closing *delim* of a substitution part, or ``None``; code in a part is refused."""
    n = len(code)
    j = start
    while j < n:
        c = code[j]
        if c == "\\":
            if j + 1 >= n:
                return None
            j += 2
        elif c == "\n":
            return None
        elif c == delim:
            return j + 1
        else:
            j += 1
    return None


def _perl_text_ok(code: str) -> bool:
    """No ``@``, ``%`` or backtick, no ``$`` but ``$digit`` and ``$&``, and none of the listed code markers."""
    if any(marker in code for marker in _PERL_CODE_MARKERS):
        return False
    for position, ch in enumerate(code):
        if ch in "@%`":
            return False
        if ch == "$":
            following = code[position + 1 : position + 2]
            if not following or following not in _PERL_VARIABLE_AFTER_DOLLAR:
                return False
    return True


def _perl_code_ok(code: str) -> bool:
    """Is *code* only ``s/RE/REPLACEMENT/gimsx`` substitutions? A ``use``, a function call, an ``e`` flag, a
    ``@{[ ... ]}`` or a ``(?{ ... })`` inside the pattern can run anything (``use File::Copy; copy(...)`` writes), so
    every other program is not read as an in-place edit."""
    if len(code) > _MAX_SCRIPT or not _perl_text_ok(code):
        return False
    n = len(code)
    i = 0
    while True:
        while i < n and code[i] in " \t\n;":
            i += 1
        if i >= n:
            return True
        if code[i] != "s" or i + 1 >= n:
            return False
        delim = code[i + 1]
        if delim.isalnum() or delim in " \t\r\n\\;()[]{}<>" or ord(delim) >= 128:
            return False
        j = _perl_part_end(code, i + 2, delim)
        if j is None:
            return False
        j = _perl_part_end(code, j, delim)
        if j is None:
            return False
        while j < n and code[j] in _PERL_S_FLAGS:
            j += 1
        if j < n and code[j] not in " \t\n;":
            return False
        i = j


def _perl(args: list[str]) -> _Effect:
    """``perl -i`` with substitution-only code, aimed at its operands; anything else is not modelled."""
    in_place = False
    code: list[str] = []
    operands: list[str] = []
    i = 0
    n = len(args)
    options_done = False
    while i < n:
        arg = args[i]
        i += 1
        if options_done or arg == "-" or not arg.startswith("-"):
            operands.append(arg)
        elif arg == "--":
            options_done = True
        elif arg.startswith("--"):
            return _UNKNOWN, []
        else:
            position = 1
            while position < len(arg):
                letter = arg[position]
                if letter == "i":
                    if _PERL_SUFFIX.fullmatch(arg, position + 1) is None:
                        return _UNKNOWN, []
                    in_place = True
                    break
                if letter in "eE":
                    if position != len(arg) - 1 or i >= n:
                        return _UNKNOWN, []
                    code.append(args[i])
                    i += 1
                    break
                if letter not in _PERL_FLAG_LETTERS:
                    return _UNKNOWN, []
                position += 1
    if not in_place or not code or not all(_perl_code_ok(c) for c in code):
        return _UNKNOWN, []
    return (_WRITE, operands) if operands else (_UNKNOWN, [])


# --------------------------------------------------------------------------- git


def _git_config_ok(setting: str) -> bool:
    """A ``git -c key=value`` that only changes how output looks: ``color.*``, ``core.pager=cat``, ``core.quotepath``."""
    key, equals, value = setting.partition("=")
    if not equals or not _LITERAL_VALUE.fullmatch(value):
        return False
    if key == "core.pager":
        return value == "cat"
    return key == "core.quotepath" or _COLOR_KEY.fullmatch(key) is not None


def _git_directory_ok(directory: str) -> bool:
    return (
        bool(directory)
        and _UNRESOLVED not in directory
        and not directory.startswith("-")
        and not any(ch in _CD_GLOB for ch in directory)
        and not _SRC_TOKEN.search(directory)
    )


def _output_option(arg: str) -> bool:
    """``--output``, any unique-prefix abbreviation of it (``--outp=f``), and ``--output-indicator-*``."""
    name = arg.split("=", 1)[0]
    return name.startswith("--output") or (len(name) >= 4 and "--output".startswith(name))


def _git(args: list[str]) -> _Effect:
    i = 0
    n = len(args)
    if args == ["--version"]:
        return _RO, []
    while i < n and args[i].startswith("-"):
        arg = args[i]
        if arg in _GIT_FLAGS:
            i += 1
        elif arg == "-c" and i + 1 < n and _git_config_ok(args[i + 1]):
            i += 2
        elif arg == "-C" and i + 1 < n and _git_directory_ok(args[i + 1]):
            i += 2
        else:
            return _UNKNOWN, []
    if i >= n:
        return _RO, []
    sub, rest = args[i], args[i + 1 :]
    if any(_output_option(arg) for arg in rest):
        return _UNKNOWN, []
    if sub in _GIT_READ_ONLY:
        return _RO, []
    if sub == "branch":
        return (_RO, []) if all(arg in _GIT_BRANCH_READ for arg in rest) else (_UNKNOWN, [])
    if sub == "remote":
        return (_RO, []) if not rest or rest == ["-v"] or rest[:1] == ["show"] else (_UNKNOWN, [])
    if sub == "config":
        return (_RO, []) if rest[:1] in (["--get"], ["--get-all"], ["--list"], ["-l"]) else (_UNKNOWN, [])
    return _UNKNOWN, []


# The only options ``cp`` and ``mv`` may carry: -f -i -n -p -r -R -v -a. Every long option, ``-t``/``-T`` (GNU target
# directory forms) and anything else makes the target unreadable from the text.
_CP_MV_FLAGS = frozenset("finpRrva")


def _cp_mv_options_ok(args: list[str]) -> bool:
    for arg in args:
        if arg == "--":
            return True
        if arg == "-" or not arg.startswith("-"):
            continue
        if arg.startswith("--") or any(letter not in _CP_MV_FLAGS for letter in arg[1:]):
            return False
    return True


def _file_writer(base: str, args: list[str]) -> _Effect:
    if base in ("cp", "mv") and not _cp_mv_options_ok(args):
        return _UNKNOWN, []
    if base == "cp":
        operands = _positionals(args)
        return (_WRITE, operands[-1:]) if operands else (_UNKNOWN, [])
    operands = _positionals(args, {"-m", "--mode"} if base == "mkdir" else set())
    if base == "tee":
        return (_WRITE, operands) if operands else (_RO, [])
    return (_WRITE, operands) if operands else (_UNKNOWN, [])


def _shell(args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    if depth >= _MAX_DEPTH:
        return _UNKNOWN, []
    positional: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if re.fullmatch(r"-[A-Za-z]*c", arg):
            payload = args[i + 1] if i + 1 < len(args) else ""
            if not payload or _UNRESOLVED in payload:
                return _UNKNOWN, []
            return _text_effect(payload, depth + 1)[0]
        if arg in ("-o", "+o"):
            i += 2
            continue
        if not arg.startswith(("-", "+")) or arg == "-":
            positional.append(arg)
        i += 1
    if [arg for arg in positional if arg != "-"]:
        return _UNKNOWN, []
    scripts = _stdin_scripts(cmds, index)
    if not scripts:
        return _UNKNOWN, []
    return _combine([_text_effect(script, depth + 1)[0] for script in scripts])


def _uv(base: str, args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    if base == "uv":
        if not args or args[0] != "run":
            return _UNKNOWN, []
        args = args[1:]
    i = 0
    while i < len(args) and args[i].startswith("-"):
        arg = args[i]
        name, equals, value = arg.partition("=")
        if name in _UV_BLOCKED_OPTIONS:
            return _UNKNOWN, []
        if name == "--with":
            if not equals:
                if i + 1 >= len(args):
                    return _UNKNOWN, []
                value = args[i + 1]
            # a package name, not a path, a URL or a flag: ``--with ./src`` builds the directory it names
            if "/" in value or value.startswith(("-", ".", "~")):
                return _UNKNOWN, []
            i += 1 if equals else 2
        elif arg in _UV_VALUE_OPTIONS:
            i += 2
        else:
            i += 1
    if i >= len(args):
        return _UNKNOWN, []
    program = _head_base(args[i])
    if program is None or (program not in _INLINE_PROGRAMS and not _PYTHON_HEAD.fullmatch(program)):
        return _UNKNOWN, []
    return _program(program, args[i + 1 :], cmds, index, depth)


# --------------------------------------------------------------------------- pytest, mypy, ruff, black, isort

_PYTEST_FLAGS = frozenset(
    {"-x", "-s", "--no-header", "--no-summary", "--co", "--collect-only", "--lf", "--ff", "--disable-warnings",
     "--strict-markers"}
)
_PYTEST_CLUSTER = re.compile(r"-[qvxs]+")
_PYTEST_TB = re.compile(r"--tb=(?:auto|long|short|line|native|no)")
_PYTEST_REPORT = re.compile(r"-r[A-Za-z]+")
_PYTEST_COUNT = re.compile(r"--(?:maxfail|durations)=[0-9]+")


def _pytest_options_ok(args: list[str]) -> bool:
    """Only the listed pytest options and test path operands: every other option can write or load code."""
    i = 0
    n = len(args)
    while i < n:
        arg = args[i]
        i += 1
        if arg == "--":
            return not any(rest.startswith("@") for rest in args[i:])
        if arg in _PYTEST_FLAGS or _PYTEST_CLUSTER.fullmatch(arg):
            continue
        if arg in ("-k", "-m", "-W"):
            if i >= n:
                return False
            i += 1
        elif arg == "-p":
            if i >= n or args[i] != "no:cacheprovider":
                return False
            i += 1
        elif _PYTEST_TB.fullmatch(arg) or _PYTEST_REPORT.fullmatch(arg) or _PYTEST_COUNT.fullmatch(arg):
            continue
        elif (arg.startswith("-") and arg != "-") or arg.startswith("@"):
            return False
    return True


_MYPY_FLAGS = frozenset(
    {"--strict", "--ignore-missing-imports", "--no-error-summary", "--show-error-codes", "--no-incremental",
     "--check-untyped-defs", "--pretty"}
)
_PY_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*")


def _mypy_options_ok(args: list[str]) -> bool:
    i = 0
    n = len(args)
    while i < n:
        arg = args[i]
        i += 1
        if arg in _MYPY_FLAGS:
            continue
        if arg == "--python-version":
            if i >= n or not _PY_VERSION.fullmatch(args[i]):
                return False
            i += 1
        elif arg.startswith("--python-version="):
            if not _PY_VERSION.fullmatch(arg.split("=", 1)[1]):
                return False
        elif (arg.startswith("-") and arg != "-") or arg.startswith("@"):
            return False
    return True


_RULE_LIST = re.compile(r"[A-Za-z0-9,._-]+")
_RUFF_FORMATS = frozenset({"concise", "full", "grouped", "json", "text", "pylint", "github"})


def _ruff(args: list[str]) -> _Effect:
    if args in (["--version"], ["version"]):
        return _RO, []
    if not args or args[0] not in ("check", "format"):
        return _UNKNOWN, []
    sub, rest = args[0], args[1:]
    i = 0
    n = len(rest)
    operands: list[str] = []
    checked = False
    while i < n:
        arg = rest[i]
        i += 1
        name, equals, value = arg.partition("=")
        if sub == "check" and arg in ("--statistics", "--show-fixes"):
            continue
        if sub == "check" and name in ("--select", "--ignore"):
            if not equals:
                if i >= n:
                    return _UNKNOWN, []
                value = rest[i]
                i += 1
            if not _RULE_LIST.fullmatch(value):
                return _UNKNOWN, []
        elif sub == "check" and name == "--output-format":
            if not equals:
                if i >= n:
                    return _UNKNOWN, []
                value = rest[i]
                i += 1
            if value not in _RUFF_FORMATS:
                return _UNKNOWN, []
        elif sub == "format" and arg in ("--check", "--diff"):
            checked = True
        elif sub == "format" and arg == "-q":
            continue
        elif sub == "format" and name == "--line-length":
            if not equals:
                if i >= n:
                    return _UNKNOWN, []
                value = rest[i]
                i += 1
            if not _INTEGER.fullmatch(value):
                return _UNKNOWN, []
        elif arg.startswith("-") and arg != "-":
            return _UNKNOWN, []
        else:
            operands.append(arg)
    if sub == "check" or checked:
        return _RO, []
    return _write_operands(operands)


def _formatter(args: list[str]) -> _Effect:
    """``black`` / ``isort``: ``--check`` or ``--diff`` (read-only), ``-q``, ``--line-length N`` and path operands."""
    i = 0
    n = len(args)
    operands: list[str] = []
    checked = False
    while i < n:
        arg = args[i]
        i += 1
        name, equals, value = arg.partition("=")
        if arg in ("--check", "--diff"):
            checked = True
        elif arg == "-q":
            continue
        elif name == "--line-length":
            if not equals:
                if i >= n:
                    return _UNKNOWN, []
                value = args[i]
                i += 1
            if not _INTEGER.fullmatch(value):
                return _UNKNOWN, []
        elif arg.startswith("-") and arg != "-":
            return _UNKNOWN, []
        else:
            operands.append(arg)
    return (_RO, []) if checked else _write_operands(operands)


def _write_operands(operands: list[str]) -> _Effect:
    """A formatter that rewrites its operands: a ``.py`` file is a known target, anything else is not."""
    if not operands:
        return _WRITE, [_UNRESOLVED]
    return _WRITE, [operand if operand.endswith(".py") else _UNRESOLVED for operand in operands]


# --------------------------------------------------------------------------- python

# Modules an inline script may import. ``string``, ``operator``, ``functools``, ``typing``, ``dataclasses`` and
# ``enum`` are not here: each can reach code by a name or a string (``Formatter`` walks attributes out of a format
# string, ``singledispatch.register`` evaluates a string annotation, ``attrgetter`` and ``get_type_hints`` do both).
# The reachable object graph of what is left is not proven closed; it is only the part nobody has found a way out of.
_PY_IMPORTS = frozenset(
    {
        "json", "re", "sys", "ast", "collections", "itertools", "math", "textwrap", "decimal", "fractions",
        "statistics", "datetime", "pathlib",
    }
)
# What a script may read off ``sys``: the standard streams, the arguments and plain facts. Not ``path`` (it decides
# what a later import loads), ``modules``, ``meta_path``, ``_getframe`` and the rest of the interpreter's internals.
_PY_SYS_ATTRS = frozenset(
    {
        "stdout", "stderr", "stdin", "argv", "exit", "version", "version_info", "platform", "maxsize",
        "byteorder", "getsizeof", "getrecursionlimit", "float_info", "flags", "executable", "getdefaultencoding",
        "getfilesystemencoding",
    }
)
# The ``sys`` attributes a script may call a method on (``sys.stdout.write``); a method of any other (``argv.append``) mutates.
_PY_SYS_STREAMS = frozenset({"stdout", "stderr", "stdin"})
# Names that reach builtins, namespaces or code by a string, or the class of an object (``type(x)`` is how a stream's
# raw object becomes a file constructor): any reference is write-capable.
_PY_BAD_NAMES = frozenset(
    {
        "__builtins__", "__import__", "vars", "globals", "locals", "getattr", "setattr", "delattr", "exec", "eval",
        "compile", "breakpoint", "input", "help", "type", "object",
    }
)
# The only annotations a script may write: a bare builtin name or ``None``. Any other (a string, an attribute, a
# subscript) is evaluated by something (``get_type_hints``) or is code.
_PY_ANNOTATION_NAMES = frozenset({"int", "str", "float", "bool", "bytes", "list", "dict", "set", "tuple"})
_PY_OK_DUNDERS = frozenset({"__name__", "__doc__"})
# Attributes that reach another namespace, a frame or code by a name or a string.
_PY_BAD_ATTRS = frozenset(
    {
        "modules", "attrgetter", "methodcaller", "get_field", "get_type_hints", "ForwardRef", "evaluate_forward_ref",
        "load_module", "exec_module", "create_module", "find_spec", "import_module", "meta_path", "path_hooks",
        "path_importer_cache", "f_globals", "f_locals", "f_builtins", "f_back", "f_code", "gi_frame", "gi_code",
        "cr_frame", "cr_code", "ag_frame", "ag_code", "tb_frame", "tb_next", "func_globals",
    }
)
# Methods that write, create, move or delete whatever they are called on, and the two ways to open a handle.
_PY_WRITE_ATTRS = frozenset(
    {
        "unlink", "rmdir", "rename", "symlink_to", "hardlink_to", "link_to", "chmod", "lchmod", "touch", "mkdir",
        "copy", "copy_into", "move", "move_into", "truncate",
    }
)
_PY_CALL_ONLY_ATTRS = _PY_WRITE_ATTRS | {"write", "writelines", "write_text", "write_bytes", "open", "replace"}
_PY_WRITE_MODE = frozenset("wax+")
_MAX_AST_NODES = 200_000


def _py_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _py_attr_ok(module, attr: str) -> bool:
    """May a script use ``module.attr``? Not a private name, an unknown one, another module, or a listed internal."""
    if attr.startswith("_") or attr in _PY_BAD_ATTRS:
        return False
    if module is sys and attr not in _PY_SYS_ATTRS:
        return False
    member = getattr(module, attr, None)
    if member is None and not hasattr(module, attr):
        return False
    if isinstance(member, types.ModuleType):
        return module.__name__ == "collections" and attr == "abc"
    return True


def _py_is_std_stream(node: ast.AST, aliases: dict) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "buffer":
        node = node.value
    return (
        isinstance(node, ast.Attribute)
        and node.attr in ("stdout", "stderr")
        and isinstance(node.value, ast.Name)
        and aliases.get(node.value.id) is sys
    )


def _py_annotation_ok(node: ast.AST | None) -> bool:
    """Is this annotation absent, ``None`` or a bare builtin type name?"""
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return node.value is None
    return isinstance(node, ast.Name) and node.id in _PY_ANNOTATION_NAMES


def _py_chain_root(node: ast.AST) -> ast.AST:
    """The expression an attribute and subscript chain starts from."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node


def _py_root_is_alias(node: ast.AST, aliases: dict) -> bool:
    root = _py_chain_root(node)
    return isinstance(root, ast.Name) and root.id in aliases


def _py_sys_mutator(func: ast.Attribute, aliases: dict) -> bool:
    """Is *func* a method of a ``sys`` attribute that is not a standard stream (``sys.argv.append``)?"""
    chain: list[str] = []
    node: ast.AST = func
    while isinstance(node, ast.Attribute):
        chain.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or aliases.get(node.id) is not sys or len(chain) < 2:
        return False
    return chain[-1] not in _PY_SYS_STREAMS


def _py_write_mode(node: ast.AST | None) -> bool | None:
    """Is this ``mode`` node a literal that writes (``True``), one that reads (``False``), or neither (``None``)?"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return any(ch in _PY_WRITE_MODE for ch in node.value)
    return None


def _python_tree_effect(tree: ast.AST) -> _Effect:
    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_AST_NODES:
        return _UNKNOWN, []
    aliases: dict[str, types.ModuleType] = {}
    counts: dict[str, int] = {}
    literals: dict[str, str] = {}
    callees: set[int] = set()
    receivers: set[int] = set()
    path_imported = False

    def bind(name: str, times: int = 1) -> None:
        counts[name] = counts.get(name, 0) + times

    # pass 1: imports, every binding of a name, which nodes are called and which are attribute receivers
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if alias.name not in _PY_IMPORTS and alias.name != "collections.abc":
                    return _UNKNOWN, []
                module = _py_module(alias.name if alias.asname else top)
                if module is None:
                    return _UNKNOWN, []
                aliases[alias.asname or top] = module
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None:
                return _UNKNOWN, []
            if node.module not in _PY_IMPORTS and node.module != "collections.abc":
                return _UNKNOWN, []
            module = _py_module(node.module)
            if module is None:
                return _UNKNOWN, []
            for alias in node.names:
                if alias.name == "*" or not _py_attr_ok(module, alias.name):
                    return _UNKNOWN, []
                if node.module == "pathlib" and alias.name == "Path" and alias.asname is None:
                    path_imported = True
        elif isinstance(node, ast.Call):
            callees.add(id(node.func))
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                receivers.add(id(node.value))
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bind(node.id)
        elif isinstance(node, ast.ClassDef):
            # a class body runs at definition, its methods are called by name from the machinery (a ``Formatter``
            # subclass captures what the format string walks to): no class is read
            return _UNKNOWN, []
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list or getattr(node, "type_params", None) or not _py_annotation_ok(node.returns):
                return _UNKNOWN, []
            bind(node.name)
        elif isinstance(node, ast.arg):
            if not _py_annotation_ok(node.annotation):
                return _UNKNOWN, []
            bind(node.arg)
        elif isinstance(node, ast.AnnAssign):
            if not _py_annotation_ok(node.annotation):
                return _UNKNOWN, []
        elif type(node).__name__ == "TypeAlias":
            return _UNKNOWN, []
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                bind(node.name)
        elif isinstance(node, ast.alias):
            bind(node.asname or node.name.split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                bind(name, 2)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
            if node.name:
                bind(node.name)
        elif isinstance(node, ast.MatchMapping):
            if node.rest:
                bind(node.rest)
        elif isinstance(node, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)):
            bind(node.name, 2)
        elif isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        literals[target.id] = node.value.value
    if counts.get("open"):
        return _UNKNOWN, []
    # ``Path`` is pathlib's constructor only when it is bound once, by ``from pathlib import Path``; ``pathlib`` (under
    # any name) only when bound once, by its import. A def, class, assignment, loop, ``with``, walrus or parameter
    # that binds either name makes ``Path(...)`` something else.
    if counts.get("Path") and not (path_imported and counts["Path"] == 1):
        return _UNKNOWN, []
    for alias_name, alias_module in aliases.items():
        if alias_module is pathlib and counts.get(alias_name) != 1:
            return _UNKNOWN, []

    def is_path_constructor(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id == "Path" and path_imported and counts.get("Path") == 1
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "Path"
            and isinstance(node.value, ast.Name)
            and aliases.get(node.value.id) is pathlib
        )

    # pass 2: module attribute chains, children before parents
    module_of: dict[int, types.ModuleType] = {}
    for node in reversed(nodes):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        module = aliases.get(value.id) if isinstance(value, ast.Name) else module_of.get(id(value))
        if module is None:
            continue
        if not isinstance(node.ctx, ast.Load) or not _py_attr_ok(module, node.attr):
            return _UNKNOWN, []
        member = getattr(module, node.attr)
        if isinstance(member, types.ModuleType):
            module_of[id(node)] = member

    # pass 3: names, attributes and calls
    targets: list[str] = []
    opens = 0
    dot_writes = 0

    def resolve(node: ast.AST | None) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and counts.get(node.id) == 1 and node.id in literals:
            return literals[node.id]
        return _UNRESOLVED

    for node in nodes:
        if isinstance(node, ast.Name):
            if node.id in _PY_BAD_NAMES or (
                node.id.startswith("__") and node.id.endswith("__") and node.id not in _PY_OK_DUNDERS
            ):
                return _UNKNOWN, []
            if node.id in aliases and (isinstance(node.ctx, (ast.Store, ast.Del)) or id(node) not in receivers):
                return _UNKNOWN, []
            if node.id == "open" and id(node) not in callees:
                return _UNKNOWN, []
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("_") or attr in _PY_BAD_ATTRS:
                return _UNKNOWN, []
            if attr in _PY_CALL_ONLY_ATTRS and id(node) not in callees:
                return _UNKNOWN, []
            if not isinstance(node.ctx, ast.Load) and _py_root_is_alias(node, aliases):
                return _UNKNOWN, []
        elif isinstance(node, ast.Subscript):
            if not isinstance(node.ctx, ast.Load) and _py_root_is_alias(node, aliases):
                return _UNKNOWN, []
        elif isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, (ast.Name, ast.Attribute)):
                # a call of a call, of a subscript, of a lambda or of any other expression: nothing says what it runs
                return _UNKNOWN, []
            if isinstance(func, ast.Attribute) and _py_sys_mutator(func, aliases):
                return _UNKNOWN, []
            starred = any(isinstance(arg, ast.Starred) for arg in node.args) or any(
                keyword.arg is None for keyword in node.keywords
            )
            keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None}
            if isinstance(func, ast.Name) and func.id == "open":
                opens += 1
                if starred or "opener" in keywords:
                    return _UNKNOWN, []
                mode = node.args[1] if len(node.args) > 1 else keywords.get("mode")
                if mode is None:
                    continue
                writes = _py_write_mode(mode)
                if writes is None:
                    return _UNKNOWN, []
                if writes:
                    targets.append(resolve(node.args[0] if node.args else keywords.get("file")))
            elif isinstance(func, ast.Attribute):
                attr = func.attr
                if attr == "open":
                    # Path.open(mode) reads its mode at index 0 and io.open / codecs.open / gzip.open at index 1:
                    # every positional and the keyword must be a literal that cannot be a write mode or a path
                    opens += 1
                    if starred or "opener" in keywords:
                        return _UNKNOWN, []
                    candidates = [*node.args, *([keywords["mode"]] if "mode" in keywords else [])]
                    for candidate in candidates:
                        if not isinstance(candidate, ast.Constant) or _py_write_mode(candidate):
                            return _UNKNOWN, []
                elif attr in ("write_text", "write_bytes"):
                    receiver = func.value
                    if (
                        isinstance(receiver, ast.Call)
                        and is_path_constructor(receiver.func)
                        and len(receiver.args) == 1
                        and not receiver.keywords
                        and not isinstance(receiver.args[0], ast.Starred)
                    ):
                        targets.append(resolve(receiver.args[0]))
                    else:
                        return _UNKNOWN, []
                elif attr in ("write", "writelines"):
                    if not _py_is_std_stream(func.value, aliases):
                        dot_writes += 1
                elif attr in _PY_WRITE_ATTRS:
                    return _UNKNOWN, []
                elif attr == "replace" and (len(node.args) < 2 or starred):
                    # str.replace takes two arguments; Path.replace(target) and os.replace-like calls do not
                    return _UNKNOWN, []
    if opens > _MAX_OPEN_CALLS or (dot_writes and not targets):
        return _UNKNOWN, []
    return (_WRITE, targets) if targets else (_RO, [])


@functools.lru_cache(maxsize=256)
def _python_effect(code: str) -> _Effect:
    """Effect of an inline python script: read-only, writes to literal targets, or unknown (anything not parsed or allowed)."""
    if len(code) > BASH_COMMAND_CAP:
        return _UNKNOWN, []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(code)
    except Exception:  # a syntax error, a NUL byte, a script nested too deep: not python we can read
        return _UNKNOWN, []
    return _python_tree_effect(tree)


_PYTHON_FLAGS = re.compile(r"-[uBEsSIOq]+")
_JSON_TOOL_FLAGS = frozenset({"--sort-keys", "--compact", "--no-ensure-ascii", "--json-lines", "--tab", "--no-indent"})


def _json_tool_ok(args: list[str]) -> bool:
    """``python -m json.tool`` reading stdin: its own flags only, no file operand (``json.tool in out`` writes ``out``)."""
    i = 0
    n = len(args)
    while i < n:
        arg = args[i]
        i += 1
        if arg in _JSON_TOOL_FLAGS:
            continue
        if arg == "--indent":
            if i >= n or not _INTEGER.fullmatch(args[i]):
                return False
            i += 1
        elif not (arg.startswith("--indent=") and _INTEGER.fullmatch(arg.split("=", 1)[1])):
            return False
    return True


def _python(args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    i = 0
    code: str | None = None
    while i < len(args):
        arg = args[i]
        if arg == "-c":
            if i + 1 >= len(args):
                return _UNKNOWN, []
            code = args[i + 1]
            break
        if arg == "-m":
            if i + 1 >= len(args):
                return _UNKNOWN, []
            module = args[i + 1]
            if module in ("pytest", "py.test"):
                return _program("pytest", args[i + 2 :], cmds, index, depth)
            if module == "json.tool" and _json_tool_ok(args[i + 2 :]):
                return _RO, []
            return _UNKNOWN, []
        if arg == "-":
            break
        if arg == "-W":
            if i + 1 >= len(args):
                return _UNKNOWN, []
            i += 2
            continue
        if _PYTHON_FLAGS.fullmatch(arg):
            i += 1
            continue
        return _UNKNOWN, []
    if code is not None:
        return _python_effect(code)
    scripts = _stdin_scripts(cmds, index)
    if not scripts:
        return _UNKNOWN, []
    return _combine([_python_effect(script) for script in scripts])


# --------------------------------------------------------------------------- classification

# A cheap prefilter: the call names something test-like at all. The path rules in ``_target_is_tests`` decide.
_TESTS_MENTION = re.compile(r"tests|test_|_test\.py|conftest\.py")
_SRC_TOKEN = re.compile(r"(?<!\w)src(?!\w)", re.IGNORECASE)
_GLOB_CHARS = frozenset("*?[{~$`\x00")


def _is_test_basename(name: str) -> bool:
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py") or name == "conftest.py"


def _target_is_tests(target: str) -> bool:
    if not target or any(ch in _GLOB_CHARS for ch in target):
        return False
    segments = [segment for segment in target.split("/") if segment and segment != "."]
    if not segments or ".." in segments or "src" in segments:
        return False
    return "tests" in segments or _is_test_basename(segments[-1])


def bash_write_offset(command: str) -> int | None:
    """Locate the first write-capable simple command of a Bash command.

    Parameters
    ----------
    command : str
        The Bash tool call's ``command`` text.

    Returns
    -------
    int | None
        The offset at which the first write-capable simple command (or the first
        command with a file redirect) starts, ``None`` when the call is read-only,
        and ``0`` for a command over ``BASH_COMMAND_CAP`` characters or one that
        does not parse. A caller ordering a write against a later word in the
        same command (a pytest run) compares offsets.
    """
    if not isinstance(command, str):
        return None
    if len(command) > BASH_COMMAND_CAP:
        return 0
    effect, first, _ = _top_effect(command)
    if effect[0] == _RO:
        return None
    return first if first is not None else 0


def classify_bash_command(command: str) -> str:
    """Classify a Bash command as ``"none"``, ``"tests"`` or ``"source"`` by an allow-list.

    ``none``: every simple command's head is allow-listed and read-only as called,
    and no file is redirected to. The allow-list is ``cat``, ``ls``, ``grep`` and its
    kin, ``find`` without ``-exec``/``-delete``/``-fprint*``, ``head``, ``tail``,
    ``wc``, ``sort`` and ``tree`` and ``uniq`` without an output form, ``diff``,
    ``echo``, ``cd`` and the like, ``awk`` with no output redirection or command,
    ``sed`` with a script of read commands only, ``git`` with a read-only subcommand
    (and ``-c`` only for presentation keys), ``xargs`` over ``cat``, ``grep``, ``wc``,
    ``ls``, ``head``, ``tail``, ``echo`` and ``printf``, pytest, mypy, ``ruff check``
    and the formatters with the listed options only (``ruff format``, ``black`` and
    ``isort`` only with ``--check``/``--diff``), and an inline python script
    (``-c``, ``-``, or a heredoc) that imports only the listed modules and opens
    files only to read. Command substitutions, backticks, ``bash -c``, ``eval``
    payloads and heredoc scripts are analysed as commands of their own. A heredoc
    body is data for a read-only head only when its delimiter is quoted
    (``<<'EOF'``); an unquoted body that contains ``$``, a backtick or a backslash
    makes the whole call ``source`` (bash expands it, and joins lines in it), and a
    body reaches an interpreter's stdin only directly or through a bare ``cat``.
    ``none`` calls can never count as writes by the classifier's reading, which is
    a heuristic and has known gaps (see the module docstring).

    ``tests``: the call is write-capable, every write in it is a recognised one
    (a file redirect, ``tee``, ``sed -i``, ``perl -i``, ``touch``, ``mkdir``,
    ``cp``, ``mv``, ``rm``, a formatter on a ``.py`` file, or an inline python
    script that opens or ``Path.write_text``s a string literal, or a name bound
    once by a plain assignment to one) aimed at a literal path under ``tests/``
    (or a test file's name), no other command in it is write-capable, and ``src``
    (in any letter case) appears nowhere in it as a path-ish token. Appending a
    test and running pytest on it in one call is the real probe shape and stays
    ``tests``.

    Shell compound constructs (``for``/``while``/``until``, ``if``, ``{ }``, ``( )``) are read
    structurally, worst of their parts; ``case``, ``select``, functions, ``coproc``, ``[[ ]]``,
    ``read``, arithmetic contexts, a zsh ``${(`` flag and anything unbalanced or nested past 32 open
    constructs are ``source``. An unresolved expansion among a head's arguments is read-only only
    for the fixed list of heads that cannot write whatever they are given (``test``/``[`` take
    one only as a double-quoted operand after a literal operator); a write whose target contains
    an expansion is ``source``.

    ``source``: everything else, including running any file (``python x.py``,
    ``bash f.sh``, ``./f``, ``make``), any head not on the list (``gsed``,
    ``ditto``, ``/bin/rm``, ``autoflake``), any environment prefix other than the
    short list in the module docstring, a wrapper with an option (``env -S``,
    ``exec -a``, ``sudo -u``), a target built at run time, an unbalanced quote or
    an unterminated heredoc, and a command over ``BASH_COMMAND_CAP``. A leading
    backslash and the ``sudo``, ``nohup``, ``time``, ``nice -n N`` and ``command``
    wrappers without options are stripped and the head they lead to is classified.

    Parameters
    ----------
    command : str
        The Bash tool call's ``command`` text.

    Returns
    -------
    str
        ``"none"``, ``"tests"`` or ``"source"``.
    """
    if not isinstance(command, str):
        return "none"
    if len(command) > BASH_COMMAND_CAP:
        return "source"
    (kind, targets), _, broken = _top_effect(command)
    if broken or kind == _UNKNOWN:
        return "source"
    if kind == _RO:
        return "none"
    if (
        _TESTS_MENTION.search(command)
        and targets
        and all(_target_is_tests(target) for target in targets)
        and not _SRC_TOKEN.search(command)
    ):
        return "tests"
    return "source"
