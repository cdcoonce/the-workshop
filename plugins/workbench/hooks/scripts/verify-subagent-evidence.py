#!/usr/bin/env python3
"""SubagentStop hook: catch a subagent claiming a change it never made.

Pairs with snapshot-subagent-start.py (SubagentStart), which records the git
HEAD sha + working-tree content signature when the subagent begins. If the
subagent's final message claims it implemented/fixed/committed something but
neither the HEAD sha nor the working tree changed at all since the snapshot,
block it and ask for the actual evidence instead of trusting the claim — the
exact failure mode "never trust a subagent's done without reading the diff"
exists to catch (a tool call that silently no-oped, a hallucinated edit).

Only blocks on a real contradiction; anything ambiguous (no snapshot, not a
git repo, no completion-sounding claim in the message) fails open. Quoted
material (code spans and fences, double-quoted text, blockquote and table
lines) is someone else's words, so a claim found only there does not count.
"""

# Hook wiring declaration, read statically by scripts/stamp.py to build
# hooks/hooks.json.
WORKSHOP_HOOK = {"event": "SubagentStop"}

import json  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)

if not isinstance(data, dict):
    # Fail open: a payload that isn't a JSON object isn't ours to act on.
    sys.exit(0)

message = data.get("last_assistant_message")
if not isinstance(message, str):
    # Fail open on a malformed payload: only a string can carry a claim.
    message = ""
agent_id = data.get("agent_id")
cwd = Path(data.get("cwd") or ".").resolve()

if not agent_id:
    sys.exit(0)

# Conservative on purpose: only fire on a strong first-person completion
# claim, not any mention of these words in passing (e.g. "no fix needed").
# Every apostrophe also takes U+2019, which editors and models emit for it.
# A negator right before "all" ("not all done", "isn't all done") denies the
# claim instead of making it.
COMPLETION_CLAIM = re.compile(
    r"\bI(?:['\u2019]ve| have)\s+(?:implemented|fixed|added|updated|created|removed|"
    r"deleted|refactored|committed|resolved|written|wrote|applied)\b"
    r"|\b(?:changes? (?:are|is) complete|fix is (?:in place|complete|done)|"
    r"implementation is complete|committed the (?:fix|change)|"
    r"(?:I['\u2019]m|I am|(?<!\bnot\s|n['\u2019]t\s)all|it['\u2019]s|it is) done\.?\s*$)",
    re.IGNORECASE,
)

# A report that quotes a skill description, a grep hit, or the regex above is
# not claiming anything itself (2026-10-12: an audit quoting finish-branch's
# description was blocked on the quoted phrase). Spans never cross a line, so
# a stray quote cannot swallow a later claim. Code spans run before double
# quotes: a span can hold a `"` that would otherwise pair with a later quote.
QUOTED_MATERIAL = (
    # A fence: no backtick in the opener's info string (CommonMark's rule for
    # backtick fences, applied to tilde ones too), and the closer is the
    # opener's character, at least as long, with only spaces or tabs after it.
    re.compile(
        r"^[ \t]*(([`~])\2{2,})[^`\n]*\n.*?^[ \t]*\1\2*[ \t]*$", re.MULTILINE | re.DOTALL
    ),
    re.compile(r"^[ \t]*[>|].*$", re.MULTILINE),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\"[^\"\n]*\"|“[^”\n]*”"),
)
# Not "": a "done" before a stripped trailing quote must stay mid-message.
QUOTED_PLACEHOLDER = "[quoted]"


def _own_words(text: str) -> str:
    """Return ``text`` with each quoted span replaced by a placeholder."""
    for pattern in QUOTED_MATERIAL:
        text = pattern.sub(QUOTED_PLACEHOLDER, text)
    return text


try:
    from _git_baseline import git_dir, head_sha, working_tree_signature
except ImportError:
    # Fail open: the helper module ships alongside every hook, but a stale or
    # partial install must no-op rather than crash the user's tool path.
    sys.exit(0)


repo_git_dir = git_dir(cwd)
if repo_git_dir is None:
    sys.exit(0)

# agent_id comes from the hook payload: keep it a single path component.
safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(agent_id))
state_file = repo_git_dir / "the-workshop-subagent-gate" / f"{safe_id}.txt"
if not state_file.exists():
    sys.exit(0)  # no baseline to compare against — nothing we can prove

try:
    lines = state_file.read_text().splitlines()
except OSError:
    sys.exit(0)
lines += [""] * (2 - len(lines))
baseline_sha, baseline_signature = lines[0], lines[1]

# Consume the baseline whenever one exists, whether or not this message turns
# out to be a completion claim — otherwise every non-claiming subagent leaves
# a file behind in the gate directory.
try:
    state_file.unlink()
except OSError:
    pass

if not message or not COMPLETION_CLAIM.search(_own_words(message)):
    sys.exit(0)

# Normalized to match what the start hook serialized (None -> "").
current_sha = head_sha(cwd) or ""
current_signature = working_tree_signature(cwd) or ""

if current_sha != baseline_sha or current_signature != baseline_signature:
    sys.exit(0)  # something actually changed — claim is consistent

print(
    json.dumps(
        {
            "decision": "block",
            "reason": (
                "This message claims a change was made, but neither the git "
                "HEAD commit nor the working tree changed at all since this "
                "subagent started. Verify the edit/commit actually happened — "
                "re-check the tool result, don't just report success. If "
                "this task was not meant to change anything, say so and "
                "restate your full report in the same reply: your caller "
                "receives only your final message."
            ),
        }
    )
)
sys.exit(0)
