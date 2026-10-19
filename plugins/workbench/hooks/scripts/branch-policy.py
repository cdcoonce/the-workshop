#!/usr/bin/env python3
"""PreToolUse hook (Bash): enforce the branch policy at the moment of action.

Policy: feature branches are cut from a fetched `origin/<integration-branch>`
and their pull requests target that branch; the promotion-only branch (`main`)
is reached by promoting the integration branch, never by a feature PR (#542).
The rule was written down three times and still got broken, so this hook makes
it mechanical. It denies (exit 2, reason on stderr):

- `git checkout -b` / `git switch -c` (and `-B` / `-C` / `--create`) with no
  `origin/<branch>` start point, which cuts from whatever stale HEAD is checked
  out and drags unmerged commits (or a stale base) into the PR;
- `gh pr create` / `gh pr merge` with `--base main` when the head branch is not
  the integration branch (the `dev` -> `main` promotion PR stays allowed).

The integration branch is the top-level `trunk_branch` key of the target repo's
`.afk/config.toml`, the same key warn-off-trunk reads. A repo without that file
or key is not enrolled and gets nothing; so does one whose trunk is `main`
(nothing to protect). Fails open everywhere else: a broken hook must never block
a session, so an unparseable payload, a command that will not tokenise, no git,
no TOML parser or a missing sibling module all exit 0 silently.

The guard reads the command text, so it catches the direct forms only. It does
not resolve a `gh pr merge` base through the network, and it does not follow
shell aliases, functions or `eval`.
"""

# scripts/stamp.py reads this declaration to generate hooks/hooks.json.
WORKSHOP_HOOK = {"event": "PreToolUse", "matcher": "Bash|bash"}

import json  # noqa: E402
import shlex  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

# tomllib is stdlib only from 3.11; fall back to the tomli backport, else skip
# the check rather than crash at import (the headless executor can be older).
try:
    import tomllib  # noqa: E402
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # noqa: E402
    except ModuleNotFoundError:
        tomllib = None

PROMOTION_BRANCH = "main"

_SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "\n"}
_WRAPPERS = {"env", "command", "sudo", "nohup", "time", "exec"}
_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
_CREATE_FLAGS = {
    "checkout": {"-b", "-B"},
    "switch": {"-c", "-C", "--create", "--force-create"},
}
_BASE_FLAGS = {"--base", "-B"}
_HEAD_FLAGS = {"--head", "-H"}


def _segments(command: str) -> list[list[str]]:
    """Split a shell command line into simple commands (a list of words each)."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in _SEPARATORS or (token and set(token) <= set("&|;()")):
            segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def _command_words(words: list[str]) -> list[str]:
    """Drop leading `VAR=val` assignments and wrappers like `env` / `sudo`."""
    i = 0
    while i < len(words):
        word = words[i]
        if "=" in word and not word.startswith("-") and word.split("=", 1)[0].isidentifier():
            i += 1
        elif word in _WRAPPERS:
            i += 1
        else:
            break
    return words[i:]


def _git_subcommand(words: list[str]) -> tuple[str, list[str]] | None:
    """For `git [global opts] <sub> args...` return (sub, args)."""
    i = 1
    while i < len(words):
        word = words[i]
        if word in _GIT_GLOBAL_WITH_VALUE:
            i += 2
        elif word.startswith("-"):
            i += 1
        else:
            return word, words[i + 1 :]
    return None


def _branch_cut_without_origin_start(sub: str, args: list[str]) -> bool:
    """True for `checkout -b` / `switch -c` forms with no `origin/<x>` start point."""
    flags = _CREATE_FLAGS.get(sub)
    if flags is None:
        return False
    positionals: list[str] = []
    creating = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            break
        if arg in flags:
            creating = True
            i += 2  # the flag's value is the new branch name
            continue
        if not arg.startswith("--") and arg[:2] in flags and len(arg) > 2:
            creating = True  # `-bname`
        elif arg in {"-t", "--track", "-f", "--force", "--no-track", "-q", "--quiet"}:
            pass
        elif arg.startswith("-"):
            pass
        else:
            positionals.append(arg)
        i += 1
    if not creating:
        return False
    return not (positionals and positionals[0].startswith("origin/"))


def _flag_value(args: list[str], flags: set[str]) -> str | None:
    for i, arg in enumerate(args):
        if arg in flags and i + 1 < len(args):
            return args[i + 1]
        for flag in flags:
            if flag.startswith("--") and arg.startswith(flag + "="):
                return arg[len(flag) + 1 :]
            if not flag.startswith("--") and arg.startswith(flag) and len(arg) > len(flag):
                return arg[len(flag) :]
    return None


def _violation(words: list[str], integration: str, current_branch) -> str | None:
    """Return the denial message for one simple command, or None."""
    if not words:
        return None
    program = Path(words[0]).name
    if program == "git":
        parsed = _git_subcommand(words)
        if parsed and _branch_cut_without_origin_start(*parsed):
            return (
                "Blocked: cut feature branches from a fetched integration branch, "
                f"not from whatever HEAD is checked out. Run `git fetch origin`, then "
                f"`git checkout -b <branch> origin/{integration}` "
                f"(or `git switch -c <branch> origin/{integration}`)."
            )
    elif program == "gh" and len(words) > 2 and words[1] == "pr" and words[2] in {"create", "merge"}:
        args = words[3:]
        if _flag_value(args, _BASE_FLAGS) == PROMOTION_BRANCH:
            head = _flag_value(args, _HEAD_FLAGS) or current_branch()
            if head != integration:
                return (
                    f"Blocked: '{PROMOTION_BRANCH}' is promotion-only. Feature branches merge into "
                    f"'{integration}' (`--base {integration}`, branch cut from origin/{integration}); "
                    f"promote '{integration}' to '{PROMOTION_BRANCH}' separately."
                )
    return None


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    tool_name = data.get("tool_name")
    if isinstance(tool_name, str) and tool_name.lower() != "bash":
        return 0
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return 0
    raw_cwd = data.get("cwd")
    cwd = Path(raw_cwd if isinstance(raw_cwd, str) and raw_cwd else ".").resolve()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from _git_baseline import _run_git
    except ImportError:
        return 0  # stale or partial install: no-op rather than break the tool path

    if tomllib is None:
        return 0
    repo_root = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if repo_root is None:
        return 0
    config_path = Path(repo_root) / ".afk" / "config.toml"
    if not config_path.is_file():
        return 0
    with config_path.open("rb") as f:
        integration = tomllib.load(f).get("trunk_branch")
    if not isinstance(integration, str) or not integration or integration == PROMOTION_BRANCH:
        return 0

    def current_branch() -> str | None:
        return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)

    try:
        segments = _segments(command)
    except ValueError:
        return 0  # unbalanced quotes etc.: not ours to judge
    for words in segments:
        message = _violation(_command_words(words), integration, current_branch)
        if message:
            print(message, file=sys.stderr)
            return 2
    return 0


try:
    sys.exit(main())
except SystemExit:
    raise
except Exception:
    sys.exit(0)
