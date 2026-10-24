#!/usr/bin/env python3
"""PreToolUse hook (Bash): refuse `gh pr merge` / `glab mr merge` on a recorded hold.

Three written rules about checking for holds existed on 2026-09-26 and none was
consulted before three agent PRs merged against holds recorded in PR comments
and a notes vault. A hook is the one place that does not depend on the session
remembering. It runs the `hold-scan` scanner (it never reimplements it) and
denies (exit 2, reason on stderr) when the scan finds a hold. This is a
deliberate speed bump with a durable record, not a security boundary: an agent
could post the acknowledgement itself, so the refusal tells it to ask the human
first. `gh api` merges, the web UI and afk's local fast-forward are not covered.

Only merges that start a command count (beginning of line, or after `;`, `&&`,
`||`, `|`, a newline, `do`, `then`, `(`, `$(`); text inside quotes is not a
merge. Shape rules refuse a command no string hook can resolve, before any
scan: more than one merge, a merge in a loop or fed by `xargs`, and a merge
whose number is not a literal integer or a PR/MR URL. A repo comes from
`-R`/`--repo`, a PR/MR URL, or the `origin` of the payload `cwd` as moved by a
literal `cd`.

The scanner's `acknowledgement` field is the only acknowledgement input; the
hook makes no GitHub or GitLab call. An acknowledgement clears `thread` hits
older than itself and all `vault` hits, never a `label` hit, and never a hit of
any other source.

Residual bypasses, kept on purpose (quoted text is not a merge, and this is a speed
bump): `bash -c '...'` (the likeliest agent form), `sh -c`, `eval`, a `$cmd`
expansion, a shell alias or function, and `python3 -c "os.system(...)"`.

Fails open on input it cannot understand (malformed or empty stdin, a non-Bash
tool, a non-string command). Fails closed once it has a merge it must scan: a
scanner error, an unparseable result or a timeout exits 2. Codex sends hooks no
payload, so the hook is inert there. `bash` as the Cortex Bash tool ID is an
unverified guess.
"""

# scripts/stamp.py reads this declaration to generate hooks/hooks.json.
WORKSHOP_HOOK = {"event": "PreToolUse", "matcher": "Bash|bash|shell"}

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

TOOLS = {"Bash", "bash", "shell"}
# A harness timeout does not block the tool, so the hook must fail closed first.
SCAN_TIMEOUT = 45
ACK_INSTRUCTION = (
    "Ask the human whether to merge anyway. If they say yes, post a PR comment whose first "
    "line is `hold-scan: acknowledged` followed by their reason, then retry."
)

_PUNCT = ";&|()\n"
_PRE_WORDS = {"do", "then", "else", "elif", "!", "{", "time", "env", "command", "sudo", "nohup", "exec"}
_LOOP_OPEN = {"for", "while", "until"}
_VALUE_FLAGS = {
    "-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email",
    "--match-head-commit", "-m", "--message", "--sha", "--squash-message",
}
_MERGE_PHRASE = re.compile(r"\b(gh\s+pr\s+merge|glab\s+mr\s+merge)\b")


class Refuse(Exception):
    """Raised to deny with a reason."""


class Merge:
    """One detected merge command."""

    def __init__(self, tool: str, args: list[str], cwd: str | None, looped: bool) -> None:
        self.tool, self.args, self.cwd, self.looped = tool, args, cwd, looped


def default_plugin_root() -> Path:
    """The plugin root derived from this hook's own path (hooks/scripts/<this>)."""
    return Path(__file__).resolve().parents[2]


def _tokens(command: str) -> list[list[str]]:
    """Split a command line into simple commands; a lone ``\\n`` token is kept as a separator."""
    command = re.sub(r"\\\r?\n", "", command)  # a backslash-newline continuation joins lines
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCT)
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token and set(token) <= set(_PUNCT):
            segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def _strip(words: list[str]) -> list[str]:
    i = 0
    while i < len(words):
        w = words[i]
        if w in _PRE_WORDS or ("=" in w and not w.startswith("-") and w.split("=", 1)[0].isidentifier()):
            i += 1
        else:
            break
    return words[i:]


def _resolve_cd(cwd: str | None, words: list[str]) -> str | None:
    """Apply a ``cd`` segment to *cwd*; None when the target is not a literal."""
    if len(words) != 2 or cwd is None:
        return None
    target = words[1]
    if re.search(r"[$`*?\[]", target) or target == "-":
        return None
    return str(Path(cwd, os.path.expanduser(target)))


def find_merges(command: str, cwd: str | None) -> list[Merge]:
    """Return every merge that starts a command, with the literal-cd-adjusted cwd."""
    merges: list[Merge] = []
    depth = 0
    for raw in _tokens(command):
        words = _strip(raw)
        if not words:
            continue
        head = words[0]
        if head in _LOOP_OPEN:
            depth += 1
            continue
        if head == "done":
            depth = max(0, depth - 1)
            continue
        if head == "cd":
            cwd = _resolve_cd(cwd, words)
            continue
        fed = False
        if os.path.basename(head) == "xargs":
            rest = [i for i, w in enumerate(words) if os.path.basename(w) in ("gh", "glab")]
            if not rest:
                continue
            words, fed = words[rest[0]:], True
            head = words[0]
        tool = os.path.basename(head)
        if tool == "gh" and words[1:3] == ["pr", "merge"] or tool == "glab" and words[1:3] == ["mr", "merge"]:
            args = words[3:]
            if "--disable-auto" in args:
                continue
            merges.append(Merge(tool, args, cwd, depth > 0 or fed))
    return merges


def _parse_args(tool: str, args: list[str]) -> tuple[str | None, str | None]:
    """Return (positional, repo-from-flag) for a merge's args."""
    positional = repo = None
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-"):
            if a.startswith("--repo="):
                repo = a.split("=", 1)[1]
            elif a in ("-R", "--repo"):
                repo = args[i + 1] if i + 1 < len(args) else None
                i += 1
            elif "=" not in a and a in _VALUE_FLAGS:
                i += 1
        elif positional is None:
            positional = a
        i += 1
    return positional, repo


def _from_url(tool: str, value: str) -> tuple[str, int] | None:
    """Return (repo, number) for a PR/MR URL argument."""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return None
    pattern = r"^/(.+?)/-/merge_requests/(\d+)(?:/.*)?$" if tool == "glab" else r"^/([^/]+/[^/]+)/pull/(\d+)(?:/.*)?$"
    m = re.match(pattern, parsed.path)
    return (m.group(1), int(m.group(2))) if m else None


def _origin(tool: str, cwd: str | None) -> str | None:
    if not cwd:
        return None
    try:
        proc = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    url = proc.stdout.strip()
    if proc.returncode != 0 or not url:
        return None
    if "://" in url:
        path = urlparse(url).path
    else:
        path = url.split(":", 1)[1] if ":" in url else ""
    parts = [p for p in path.strip("/").removesuffix(".git").split("/") if p]
    if len(parts) < 2:
        return None
    return "/".join(parts) if tool == "glab" else "/".join(parts[-2:])


def _scanner_args(merge: Merge) -> list[str]:
    positional, repo = _parse_args(merge.tool, merge.args)
    url = _from_url(merge.tool, positional) if positional else None
    if url is not None:
        repo, number = url
    elif positional and re.fullmatch(r"\d+", positional):
        number = int(positional)
    else:
        raise Refuse(
            "Refusing merge: no literal PR/MR number or PR/MR URL in the command. "
            "A hook cannot resolve `$P`, `$(...)` or a branch name. Run the merge with the literal number."
        )
    if repo is None:
        repo = _origin(merge.tool, merge.cwd)
    if repo is None:
        raise Refuse(
            "Refusing merge: cannot tell which repo this merge targets (no `origin` remote for the "
            "working directory, or a non-literal `cd`). Pass `-R OWNER/NAME`."
        )
    if merge.tool == "glab":
        return ["--gitlab", repo, "--mr", str(number)]
    return ["--repo", repo, "--pr", str(number)]


def _ts(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _remaining(hits: list[dict], acknowledgement: dict | None) -> list[dict]:
    """Return the hits an acknowledgement does not clear."""
    ack_ts = _ts(acknowledgement.get("timestamp")) if isinstance(acknowledgement, dict) else None
    left = []
    for h in hits:
        source = h.get("source")
        if source == "vault" and acknowledgement:
            continue
        if source == "thread" and ack_ts is not None:
            hit_ts = _ts(h.get("timestamp"))
            if hit_ts is not None and hit_ts < ack_ts:
                continue
        left.append(h)
    return left


def _run_scanner(plugin_root: Path, args: list[str]) -> dict:
    script = plugin_root / "skills" / "hold-scan" / "scripts" / "hold_scan.py"
    argv = [sys.executable, str(script), *args, "--json"]
    call = f"hold_scan.py {' '.join(args)}"
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=SCAN_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise Refuse(f"Refusing merge: {call} timed out after {SCAN_TIMEOUT}s, so the hold check is unknown.")
    except OSError as exc:
        raise Refuse(f"Refusing merge: could not run {call}: {exc}")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise Refuse(f"Refusing merge: {call} gave unparseable output (exit {proc.returncode}): {proc.stderr.strip()[:200]}")
    if not isinstance(out, dict) or out.get("verdict") not in ("HOLD-FOUND", "NO-HOLD-FOUND", "SCAN-ERROR"):
        raise Refuse(f"Refusing merge: {call} gave an unrecognised result.")
    return out


def evaluate(payload: object, plugin_root: Path | None = None) -> tuple[int, str]:
    """Return (exit_code, stderr message) for one hook payload."""
    if not isinstance(payload, dict) or payload.get("tool_name") not in TOOLS:
        return 0, ""
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0, ""
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    try:
        try:
            merges = find_merges(command, cwd)
        except ValueError:
            if _MERGE_PHRASE.search(command):
                raise Refuse("Refusing merge: the command cannot be parsed. Run the merge as its own call.")
            return 0, ""
        if not merges:
            return 0, ""
        if len(merges) > 1 or merges[0].looped:
            raise Refuse(
                "Refusing merge: one merge per call. A loop, `xargs` or a second merge cannot be checked "
                "one PR at a time. Run each merge as its own command with a literal number."
            )
        args = _scanner_args(merges[0])
        out = _run_scanner(plugin_root or _plugin_root(), args)
        verdict = out["verdict"]
        if verdict == "NO-HOLD-FOUND":
            return 0, ""
        if verdict == "SCAN-ERROR":
            failed = [e.get("name", "?") for e in out.get("scanned", []) if isinstance(e, dict) and e.get("status") == "failed"]
            raise Refuse("Refusing merge: the hold scan could not finish. Failed call(s): " + ("; ".join(failed) or "unknown") + ".")
        left = _remaining([h for h in out.get("hits", []) if isinstance(h, dict)], out.get("acknowledgement"))
        if not left:
            return 0, ""
        lines = ["Refusing merge: hold-scan found a recorded hold."]
        lines += [f"- [{h.get('source')}] {h.get('url_or_path')}: {h.get('quote')}" for h in left]
        if any(h.get("source") == "label" for h in left):
            lines.append("A label hold is never cleared by an acknowledgement: remove the `afk:hold` label from the issue.")
        lines.append(ACK_INSTRUCTION)
        raise Refuse("\n".join(lines))
    except Refuse as refusal:
        return 2, str(refusal)


def _plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(env) if env else default_plugin_root()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0
    try:
        code, message = evaluate(payload)
    except Exception:  # noqa: BLE001 - a broken hook must never block a session
        return 0
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
