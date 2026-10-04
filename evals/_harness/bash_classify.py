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
write-capable, so the only way a hit is wrongly credited is a write hidden inside
an allow-listed head's own arguments that the per-head rules below do not name.

Pytest spellings are allow-listed even though they execute code: running the tests
is what a test-first attempt does, and a ``none`` call can never count as a write.
A call that appends a test AND runs pytest on it stays a ``tests`` call.

Cost: one pass over the text with a hand-written scanner, no backtracking regex
over the command. Bounded work is enforced by the cap, a limit on command
substitutions, a limit on analysed ``open(`` calls, and bounded windows in the
python scan.
"""

from __future__ import annotations

import functools
import re

# A command longer than this is classified "source" without being scanned (fail closed).
BASH_COMMAND_CAP = 100_000

_MAX_DEPTH = 4
_MAX_SUBSTITUTIONS = 200
_MAX_OPEN_CALLS = 50
_OPEN_WINDOW = 300
_MAX_SCRIPT = 4_000

# --------------------------------------------------------------------------- the scanner

_WORD_RUN = re.compile(r"[^ \t\r\n|&;<>()'\"\\`$]+")
_PAREN = re.compile(r"[()]")
_HEREDOC_DELIM = re.compile(r"""-?[ \t]*(?:'([^'\n]*)'|"([^"\n]*)"|\\?([\w.-]+))""")
_DQ_SPECIAL = re.compile(r'[^"\\$`]+')
_PARAM_NAME = re.compile(r"\w+|[@*#?!$-]")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*\+?=")
_DEV_OK = re.compile(r"/dev/(?:null|stderr|stdout)")
_FD_DUP = re.compile(r"\d+-?|-")
_UNRESOLVED = "\x00"


class _Cmd:
    __slots__ = ("words", "targets", "bodies", "offset", "piped")

    def __init__(self, offset: int, piped: bool) -> None:
        self.words: list[str] = []
        self.targets: list[str] = []
        self.bodies: list[str] = []
        self.offset = offset
        self.piped = piped


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
    if text.startswith("${", i):
        close = text.find("}", i + 2)
        if close == -1 or "$(" in text[i + 2 : close] or "`" in text[i + 2 : close]:
            ctx.broken = True
            return len(text)
        return close + 1
    if text[i] == "`":
        close = text.find("`", i + 1)
        if close == -1:
            ctx.broken = True
            return len(text)
        _scan(text[i + 1 : close], base + i + 1, ctx, depth + 1)
        return close + 1
    level = 0
    for match in _PAREN.finditer(text, i + 1):
        level += 1 if match.group() == "(" else -1
        if level == 0:
            _scan(text[i + 2 : match.start()], base + i + 2, ctx, depth + 1)
            return match.end()
    ctx.broken = True
    return len(text)


def _read_word(text: str, i: int, ctx: _Ctx, depth: int, base: int) -> tuple[str, int]:
    """Read one shell word starting at ``text[i]``: quotes removed, expansions made opaque."""
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
        elif c == "`" or text.startswith("$(", i) or text.startswith("${", i):
            i = _subst(text, i, ctx, depth, base)
            parts.append(_UNRESOLVED)
        elif c == "$":
            match = _PARAM_NAME.match(text, i + 1)
            i = match.end() if match else i + 1
            parts.append(_UNRESOLVED)
        else:
            match = _WORD_RUN.match(text, i)
            parts.append(match.group())
            i = match.end()
    return "".join(parts), i


def _scan(text: str, base: int, ctx: _Ctx, depth: int) -> None:
    """Split *text* into simple commands, appending them to ``ctx.cmds``.

    Heredoc bodies are attached to the command that opened them. Anything the
    scanner cannot place sets ``ctx.broken``.
    """
    if depth > _MAX_DEPTH:
        ctx.broken = True
        return
    n = len(text)
    i = 0
    cmd: _Cmd | None = None
    next_piped = False
    pending: list[tuple[_Cmd, str, bool]] = []
    last_word_end = -1

    def current(at: int) -> _Cmd:
        nonlocal cmd
        if cmd is None:
            cmd = _Cmd(base + at, next_piped)
            ctx.cmds.append(cmd)
        return cmd

    while i < n and not ctx.broken:
        c = text[i]
        if c in " \t\r":
            i += 1
        elif c == "\n":
            cmd = None
            next_piped = False
            i += 1
            for owner, delimiter, dash in pending:
                body: list[str] = []
                found = False
                while i < n:
                    end = text.find("\n", i)
                    stop = n if end == -1 else end
                    line = text[i:stop]
                    i = stop + 1
                    if (line.lstrip("\t") if dash else line).rstrip("\r") == delimiter:
                        found = True
                        break
                    body.append(line)
                if not found:
                    ctx.broken = True
                owner.bodies.append("\n".join(body))
            pending = []
        elif c == "#":
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif c == ";":
            cmd = None
            next_piped = False
            i += 1
        elif c in "()":
            cmd = None
            next_piped = False
            i += 1
        elif c == "|":
            cmd = None
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
            else:
                cmd = None
                next_piped = False
                i += 2 if text.startswith("&&", i) else 1
        elif c == "<":
            if text.startswith("<<<", i):
                _, i = _read_target(text, i + 3, ctx, depth, base)
            elif text.startswith("<<", i):
                match = _HEREDOC_DELIM.match(text, i + 2)
                if not match:
                    ctx.broken = True
                    break
                dash = text.startswith("<<-", i)
                delimiter = next(g for g in match.groups() if g is not None)
                pending.append((current(i), delimiter, dash))
                i = match.end()
            elif text.startswith("<(", i):
                i = _subst(text, i, ctx, depth, base)
            elif text.startswith("<>", i):
                _drop_fd_word(current(i), last_word_end, i)
                target, i = _read_target(text, i + 2, ctx, depth, base)
                _add_target(current(i), target)
            elif text.startswith("<&", i):
                _, i = _read_target(text, i + 2, ctx, depth, base)
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
                dup = _FD_DUP.match(text, i + 2)
                if dup:
                    i = dup.end()
                    continue
                j = i + 2
            elif text.startswith(">(", i):
                _add_target(owner, _UNRESOLVED)
                i = _subst(text, i, ctx, depth, base)
                continue
            target, i = _read_target(text, j, ctx, depth, base)
            _add_target(owner, target)
        else:
            owner = current(i)
            word, i = _read_word(text, i, ctx, depth, base)
            owner.words.append(word)
            last_word_end = i
    if pending and not ctx.broken:
        ctx.broken = True


def _drop_fd_word(owner: _Cmd, last_word_end: int, at: int) -> None:
    """A redirect written ``2>file`` reads ``2`` as a word first; take it back."""
    if last_word_end == at and owner.words and owner.words[-1].isdigit():
        owner.words.pop()


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

_WRAPPER_VALUE_OPTIONS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-U", "-T"},
    "env": {"-u", "-C", "-S"},
    "nice": {"-n"},
}
_KEYWORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{", "}", "fi", "done", "esac"})
_READ_ONLY_HEADS = frozenset(
    {
        "cat", "ls", "grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "sort", "uniq", "diff", "cmp", "echo",
        "printf", "pwd", "cd", "which", "type", "true", "false", "test", "[", "sleep", "date", "tree", "stat", "file",
        "du", "tr", "cut", "jq", "less", "more",
    }
)
_FIND_WRITES = frozenset(
    {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
)
_GIT_READ_ONLY = frozenset({"status", "diff", "log", "show", "rev-parse", "ls-files", "blame", "describe"})
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
_GIT_BRANCH_READ = frozenset({"-a", "-r", "--list", "-l", "-v", "-vv", "--show-current", "--all", "--remotes"})
_PYTEST_WRITING_FLAGS = re.compile(
    r"--(?:junit-?xml|basetemp|html|self-contained-html|result-?log|report-log|cov-report|snapshot|update|regen|generate)"
)
_RUFF_CHECK_WRITES = frozenset({"--fix", "--fix-only", "--unsafe-fixes", "--add-noqa", "--output-file", "-o"})
_PYTHON_HEAD = re.compile(r"python(?:\d+(?:\.\d+)*)?")
_UV_VALUE_OPTIONS = frozenset(
    {"--with", "--python", "-p", "--project", "--directory", "--extra", "--group", "--with-requirements", "--env-file",
     "--index", "--find-links", "--with-editable"}
)
_INLINE_PROGRAMS = frozenset({"pytest", "py.test", "ruff", "black", "isort", "mypy"})
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})


def _positionals(args: list[str], value_options: frozenset[str] | set[str] = frozenset()) -> list[str]:
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in value_options:
            skip = True
        elif arg == "--":
            continue
        elif not arg.startswith("-") or arg == "-":
            out.append(arg)
    return out


def _strip_wrappers(words: list[str]) -> list[str]:
    i = 0
    n = len(words)
    while i < n:
        word = words[i].lstrip("\\")
        base = word.rsplit("/", 1)[-1]
        if _ASSIGNMENT.match(word) or word in _KEYWORDS:
            i += 1
        elif base in ("command", "nohup", "time", "exec", "env", "sudo", "nice"):
            i += 1
            values = _WRAPPER_VALUE_OPTIONS.get(base, set())
            while i < n and (words[i].startswith("-") or (base == "env" and _ASSIGNMENT.match(words[i]))):
                i += 2 if words[i] in values else 1
        else:
            break
    return words[i:]


def _combine(parts: list[_Effect]) -> _Effect:
    targets: list[str] = []
    for kind, found in parts:
        if kind == _UNKNOWN:
            return _UNKNOWN, []
        targets.extend(found)
    return (_WRITE, targets) if targets else (_RO, [])


def _text_effect(text: str, depth: int) -> tuple[_Effect, int | None, bool]:
    """Scan *text* and combine its commands: ``(effect, first non-read-only offset, broken)``."""
    ctx = _Ctx()
    _scan(text, 0, ctx, depth)
    if ctx.broken:
        return (_UNKNOWN, []), 0, True
    parts: list[_Effect] = []
    first: int | None = None
    for index, cmd in enumerate(ctx.cmds):
        effect = _command_effect(cmd, ctx.cmds, index, depth)
        if effect[0] != _RO and first is None:
            first = cmd.offset
        parts.append(effect)
    return _combine(parts), first, False


@functools.lru_cache(maxsize=64)
def _top_effect(command: str) -> tuple[_Effect, int | None, bool]:
    """``_text_effect`` of a whole command, cached: the classifier and the offset both ask."""
    return _text_effect(command, 0)


def _stdin_scripts(cmds: list[_Cmd], index: int) -> list[str]:
    """Heredoc bodies that feed command *index*: its own, then those earlier in its pipeline."""
    bodies = list(cmds[index].bodies)
    j = index
    while cmds[j].piped and j > 0:
        j -= 1
        bodies = cmds[j].bodies + bodies
    return bodies


def _command_effect(cmd: _Cmd, cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    redirects: _Effect = (_WRITE, list(cmd.targets)) if cmd.targets else (_RO, [])
    words = _strip_wrappers(cmd.words)
    if not words:
        return redirects
    head = words[0].lstrip("\\")
    if _UNRESOLVED in head:
        return _UNKNOWN, []
    effect = _head_effect(head.rsplit("/", 1)[-1], words[1:], cmds, index, depth)
    return _combine([redirects, effect])


# --------------------------------------------------------------------------- heads


def _head_effect(base: str, args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    if base in _READ_ONLY_HEADS:
        return _read_only_head(base, args)
    if base == "find":
        return (_UNKNOWN, []) if any(arg in _FIND_WRITES for arg in args) else (_RO, [])
    if base == "xargs":
        return _xargs(args, cmds, index, depth)
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


def _program(base: str, args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    """A program run directly or through ``uv run`` / ``python -m``: only the allow-listed ones."""
    if base in ("pytest", "py.test"):
        return (_UNKNOWN, []) if any(_PYTEST_WRITING_FLAGS.match(arg) for arg in args) else (_RO, [])
    if _PYTHON_HEAD.fullmatch(base):
        return _python(args, cmds, index, depth)
    if base == "ruff":
        return _ruff(args)
    if base in ("black", "isort"):
        return _formatter(args)
    if base == "mypy":
        return _RO, []
    return _UNKNOWN, []


def _read_only_head(base: str, args: list[str]) -> _Effect:
    if base == "sort" and any(arg == "-o" or arg.startswith("-o") or arg.startswith("--output") for arg in args):
        return _UNKNOWN, []
    if base == "uniq" and len(_positionals(args)) > 1:
        return _UNKNOWN, []
    if base == "tree" and any(arg == "-o" or arg.startswith("-o") for arg in args):
        return _UNKNOWN, []
    if base == "date" and any(arg in ("-s", "--set") or arg.startswith("--set=") for arg in args):
        return _UNKNOWN, []
    if base == "rg" and any(arg.startswith("--pre") for arg in args):
        return _UNKNOWN, []
    return _RO, []


def _xargs(args: list[str], cmds: list[_Cmd], index: int, depth: int) -> _Effect:
    values = {"-I", "-n", "-P", "-L", "-s", "-d", "-a", "-E", "-l", "-i"}
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in values else 1
    rest = _strip_wrappers(args[i:])
    if not rest:
        return _RO, []
    head = rest[0].lstrip("\\")
    if _UNRESOLVED in head:
        return _UNKNOWN, []
    kind, _ = _head_effect(head.rsplit("/", 1)[-1], rest[1:], cmds, index, depth)
    return (_RO, []) if kind == _RO else (_UNKNOWN, [])


_AWK_WRITES = re.compile(r"system\s*\(|\bprint(?:f)?\b[^;}\n]*>(?!=)|>>|\|\s*[\"'(\w]|getline|\bclose\s*\(")


def _awk(args: list[str]) -> _Effect:
    for arg in args:
        if arg.startswith("-f") or arg.startswith("--file") or arg.startswith("-i") or "inplace" in arg:
            return _UNKNOWN, []
        if len(arg) > _MAX_SCRIPT or _AWK_WRITES.search(arg):
            return _UNKNOWN, []
    return _RO, []


_SED_WRITING_COMMAND = re.compile(r"(?:^|[;{}\n]|(?<=[0-9$/!]))\s*[wWeE](?:\s|/|$)")
_SED_S_FLAGS = re.compile(r"s(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1([A-Za-z0-9]*)")


def _sed_script_writes(script: str) -> bool:
    if len(script) > _MAX_SCRIPT or _SED_WRITING_COMMAND.search(script):
        return True
    return any(set(match.group(2)) & {"w", "e", "W", "E"} for match in _SED_S_FLAGS.finditer(script))


def _sed(args: list[str]) -> _Effect:
    in_place = False
    scripts: list[str] = []
    operands: list[str] = []
    i = 0
    explicit = False
    while i < len(args):
        arg = args[i]
        if arg in ("-e", "--expression"):
            explicit = True
            scripts.extend(args[i + 1 : i + 2])
            i += 2
            continue
        if arg in ("-f", "--file") or arg.startswith("--file=") or arg.startswith("-f"):
            return _UNKNOWN, []
        if arg.startswith("--expression="):
            explicit = True
            scripts.append(arg.split("=", 1)[1])
        elif arg.startswith("--in-place"):
            in_place = True
        elif arg.startswith("--"):
            pass
        elif arg.startswith("-") and arg != "-":
            for position, letter in enumerate(arg[1:], start=1):
                if letter == "i":
                    in_place = True
                    break
                if letter == "f":
                    return _UNKNOWN, []
                if letter == "e":
                    explicit = True
                    if position == len(arg) - 1:
                        scripts.extend(args[i + 1 : i + 2])
                        i += 1
                    else:
                        scripts.append(arg[position + 1 :])
                    break
        else:
            operands.append(arg)
        i += 1
    if in_place:
        operands = [operand for operand in operands if operand != ""]
    if not explicit and operands:
        scripts.append(operands.pop(0))
    if any(_sed_script_writes(script) for script in scripts):
        return _UNKNOWN, []
    if in_place:
        return (_WRITE, operands) if operands else (_UNKNOWN, [])
    return _RO, []


_PERL_DANGEROUS = re.compile(
    r"\b(?:system|exec|open|unlink|rename|qx|eval|require|do|sysopen|truncate|mkdir|rmdir|link|symlink|chmod|chown)\b|`"
)


def _perl(args: list[str]) -> _Effect:
    in_place = False
    code: list[str] = []
    operands: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-e", "-E"):
            code.extend(args[i + 1 : i + 2])
            i += 2
            continue
        if arg.startswith("-") and arg != "-" and not arg.startswith("--"):
            cluster = arg[1:]
            if "i" in cluster:
                in_place = True
            if cluster.endswith("e") or cluster.endswith("E"):
                code.extend(args[i + 1 : i + 2])
                i += 2
                continue
        elif not arg.startswith("-"):
            operands.append(arg)
        i += 1
    if not in_place or not code or any(len(c) > _MAX_SCRIPT or _PERL_DANGEROUS.search(c) for c in code):
        return _UNKNOWN, []
    return (_WRITE, operands) if operands else (_UNKNOWN, [])


def _git(args: list[str]) -> _Effect:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in _GIT_VALUE_OPTIONS else 1
    if i >= len(args):
        return _RO, []
    sub, rest = args[i], args[i + 1 :]
    if any(arg.startswith("--output") for arg in rest):
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


def _file_writer(base: str, args: list[str]) -> _Effect:
    if base == "cp":
        for position, arg in enumerate(args):
            if arg == "-t":
                return (_WRITE, args[position + 1 : position + 2]) if position + 1 < len(args) else (_UNKNOWN, [])
            if arg.startswith("--target-directory="):
                return _WRITE, [arg.split("=", 1)[1]]
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
        i += 2 if args[i] in _UV_VALUE_OPTIONS else 1
    if i >= len(args):
        return _UNKNOWN, []
    program = args[i].lstrip("\\").rsplit("/", 1)[-1]
    if program not in _INLINE_PROGRAMS and not _PYTHON_HEAD.fullmatch(program):
        return _UNKNOWN, []
    return _program(program, args[i + 1 :], cmds, index, depth)


def _ruff(args: list[str]) -> _Effect:
    operands = _positionals(args, {"--config", "--select", "--ignore", "--output-format", "--target-version", "--line-length"})
    sub = operands[0] if operands else ""
    if sub == "check":
        for arg in args:
            if arg in _RUFF_CHECK_WRITES or arg.startswith("--fix") or arg.startswith("--output-file"):
                return _write_operands(operands[1:])
        return _RO, []
    if sub == "format":
        if "--check" in args or "--diff" in args:
            return _RO, []
        return _write_operands(operands[1:])
    if args == ["--version"] or args == ["version"]:
        return _RO, []
    return _UNKNOWN, []


def _formatter(args: list[str]) -> _Effect:
    if "--check" in args or "--diff" in args:
        return _RO, []
    return _write_operands(_positionals(args))


def _write_operands(operands: list[str]) -> _Effect:
    """A formatter that rewrites its operands: a ``.py`` file is a known target, anything else is not."""
    if not operands:
        return _WRITE, [_UNRESOLVED]
    return _WRITE, [operand if operand.endswith(".py") else _UNRESOLVED for operand in operands]


# --------------------------------------------------------------------------- python

_PY_DANGEROUS = re.compile(
    r"\b(?:subprocess|shutil|fileinput|inplace|importlib|getattr|setattr|ctypes|tempfile)\b"
    r"|(?<![\w.])(?:exec|eval|compile)\s*\(|__import__"
    r"|\bos\s*\.\s*(?:system|popen|spawn\w*|exec\w*|rename|replace|remove|unlink|rmdir|removedirs|makedirs|"
    r"truncate|chmod|chown|link|symlink|write|open|mkdir|fdopen)\b"
    r"|\b(?:io|codecs)\s*\.\s*open\b"
    r"|\bfrom\s+(?:os|shutil|subprocess|fileinput|io|codecs|tempfile)\s+import\b"
    r"|\bfrom\s+pathlib\s+import\b(?!\s+Path\s*(?:[;\n]|$))"
    r"|(?<![\w.])open\b(?!\s*\()"
    r"|\bimport\s+(?:os|shutil|pathlib|subprocess|io|codecs)\s+as\b"
    r"|\.(?:unlink|rename|touch|rmdir|symlink_to|hardlink_to|mkdir|chmod)\s*\("
)
_PATH_WORD = re.compile(r"\bPath\b|\bpathlib\b")
_REPLACE_CALL = re.compile(r"\.replace\s*\(")
_OPEN_CALL = re.compile(r"(?<![\w.])open\s*\(")
_METHOD_OPEN = re.compile(r"\.open\s*\(")
_DOT_WRITE = re.compile(r"\.write\s*\(")
_STD_WRITE = re.compile(r"\bsys\s*\.\s*std(?:out|err)\s*\.\s*write\s*\(")
_PATH_WRITE = re.compile(r"\bPath\(\s*(?:'([^'\n]*)'|\"([^\"\n]*)\"|(\w+))\s*\)\s*\.\s*write_(?:text|bytes)\s*\(")
_ANY_PATH_WRITE = re.compile(r"write_(?:text|bytes)\s*\(")
_LITERAL = re.compile(r"""\s*(?:'([^'\n]*)'|"([^"\n]*)")\s*""")
_MODE_WRITES = re.compile(r"[wax+]")
_KEYWORD_ARG = re.compile(r"\s*(\w+)\s*=(?!=)(.*)", re.DOTALL)
_ASSIGN = re.compile(r"(?<![\w.])(\w+)\s*=(?!=)")
_LITERAL_ASSIGN = re.compile(r"""(?:^|[;\n])[ \t]*(\w+)[ \t]*=[ \t]*(?:'([^'\n;]*)'|"([^"\n;]*)")[ \t]*(?=$|[;\n#])""")


def _bindings(code: str) -> dict[str, str]:
    """Names assigned exactly once in *code*, and to a string literal."""
    counts: dict[str, int] = {}
    for match in _ASSIGN.finditer(code):
        counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    bound: dict[str, str] = {}
    for match in _LITERAL_ASSIGN.finditer(code):
        value = match.group(2) if match.group(2) is not None else match.group(3)
        if counts.get(match.group(1)) == 1:
            bound[match.group(1)] = value
    return bound


def _split_args(text: str) -> list[str] | None:
    """Split the arguments of a call whose ``(`` has just been consumed; ``None`` if it does not close in view."""
    args: list[str] = []
    level = 0
    quote = ""
    start = 0
    for position, ch in enumerate(text[:_OPEN_WINDOW]):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            level += 1
        elif ch in ")]}":
            if level == 0:
                args.append(text[start:position])
                return args
            level -= 1
        elif ch == "," and level == 0:
            args.append(text[start:position])
            start = position + 1
    return None


def _literal(text: str) -> str | None:
    match = _LITERAL.fullmatch(text)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _resolve(arg: str, bound: dict[str, str]) -> str:
    value = _literal(arg)
    if value is not None:
        return value
    name = arg.strip()
    return bound[name] if name.isidentifier() and name in bound else _UNRESOLVED


def _call_mode(args: list[str], mode_position: int) -> tuple[list[str], str]:
    """Split call arguments into positional ones and the mode text (``""`` when none is given)."""
    positional: list[str] = []
    keywords: dict[str, str] = {}
    for arg in args:
        keyword = _KEYWORD_ARG.fullmatch(arg)
        if keyword:
            keywords[keyword.group(1)] = keyword.group(2)
        else:
            positional.append(arg)
    if len(positional) > mode_position:
        return positional, positional[mode_position]
    return positional, keywords.get("mode", "")


def _python_effect(code: str) -> _Effect:
    """Effect of an inline python script: read-only, writes to literal targets, or unknown."""
    if len(code) > BASH_COMMAND_CAP or _PY_DANGEROUS.search(code):
        return _UNKNOWN, []
    if _PATH_WORD.search(code) and _REPLACE_CALL.search(code):
        return _UNKNOWN, []
    for match in _METHOD_OPEN.finditer(code):
        # Path(...).open(...), obj.open(...): only a literal read mode is read-only.
        args = _split_args(code[match.end() : match.end() + _OPEN_WINDOW])
        if args is None:
            return _UNKNOWN, []
        _, mode_text = _call_mode(args, 0)
        mode = _literal(mode_text) if mode_text.strip() else ""
        if mode is None or _MODE_WRITES.search(mode):
            return _UNKNOWN, []
    bound = _bindings(code)
    targets: list[str] = []
    opens = list(_OPEN_CALL.finditer(code))
    if len(opens) > _MAX_OPEN_CALLS:
        return _UNKNOWN, []
    for match in opens:
        args = _split_args(code[match.end() : match.end() + _OPEN_WINDOW])
        if args is None:
            return _UNKNOWN, []
        positional, mode_text = _call_mode(args, 1)
        if not mode_text.strip():
            continue
        mode = _literal(mode_text)
        if mode is None:
            return _UNKNOWN, []
        if _MODE_WRITES.search(mode):
            targets.append(_resolve(positional[0], bound) if positional else _UNRESOLVED)
    path_writes = list(_PATH_WRITE.finditer(code))
    if len(_ANY_PATH_WRITE.findall(code)) != len(path_writes):
        return _UNKNOWN, []
    for match in path_writes:
        if match.group(1) is not None:
            targets.append(match.group(1))
        elif match.group(2) is not None:
            targets.append(match.group(2))
        else:
            targets.append(bound.get(match.group(3), _UNRESOLVED))
    if len(_DOT_WRITE.findall(code)) > len(_STD_WRITE.findall(code)) and not targets:
        return _UNKNOWN, []
    return (_WRITE, targets) if targets else (_RO, [])


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
            if module not in _INLINE_PROGRAMS:
                return _UNKNOWN, []
            return _program(module, args[i + 2 :], cmds, index, depth)
        if arg == "-":
            break
        if arg in ("-W", "-X", "-Q", "-O"):
            i += 2 if arg != "-O" else 1
            continue
        if arg.startswith("-"):
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
_SRC_TOKEN = re.compile(r"(?<!\w)src(?!\w)")
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
    ``wc``, ``sort`` without ``-o``, ``uniq``, ``diff``, ``echo``, ``cd`` and the
    like, ``awk`` and ``sed`` without a write, ``git`` with a read-only subcommand,
    pytest in its spellings, ``ruff check`` without ``--fix``, ``ruff format``,
    ``black`` and ``isort`` only with ``--check``/``--diff``, ``mypy``, and an
    inline python script (``-c``, ``-``, or a heredoc) with no write API. Command
    substitutions, backticks, ``bash -c``, ``eval`` payloads and heredoc scripts
    are analysed as commands of their own; a heredoc body is data for a read-only
    head. ``none`` calls can never count as writes.

    ``tests``: the call is write-capable, every write in it is a recognised one
    (a file redirect, ``tee``, ``sed -i``, ``perl -i``, ``touch``, ``mkdir``,
    ``cp``, ``mv``, ``rm``, or an inline python script that opens or
    ``Path.write_text``s a string literal) aimed at a literal path under ``tests/``
    (or a test file's name), no other command in it is write-capable, and ``src``
    appears nowhere in it as a path-ish token. Appending a test and running
    pytest on it in one call is the real probe shape and stays ``tests``.

    ``source``: everything else, including running any file (``python x.py``,
    ``bash f.sh``, ``./f``, ``make``), any head not on the list (``gsed``,
    ``ditto``, ``/bin/rm``, ``autoflake``), wrapper words are stripped first
    (``sudo``, ``env``, ``command``, ``nohup``, ``time``, ``nice``, ``exec``, a
    leading backslash), a target built at run time, an unbalanced quote or an
    unterminated heredoc, and a command over ``BASH_COMMAND_CAP``.

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
