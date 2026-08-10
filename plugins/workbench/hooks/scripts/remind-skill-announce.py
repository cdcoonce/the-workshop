#!/usr/bin/env python3
"""PostToolUse hook: remind Claude to announce a skill it just invoked.

The using-workflow router's Announce Convention ("Before following a skill,
announce it: 'Using [skill] to [purpose].'") is prose the model must choose
to obey every turn, and it loses that choice under an active terse/no-preamble
persona, which reads the announce line as exactly the preamble it was told to
cut. Transcript audits of real sessions confirm the miss: `Skill` tool calls
land with no announce-line text anywhere nearby.

This hook fires after every `Skill` tool call and re-asserts the convention as
`additionalContext` on the next model turn, naming the specific skill that ran
and stating explicitly that the announce line is a protocol marker exempt from
any terse-persona rule — the same exemption added to the router's SKILL.md,
restated here so the reminder survives even if the router body scrolled out of
context. A prompt-level fix cannot be verified to hold on every turn; this
hook is the deterministic backstop.

Only fires when `tool_input.skill` is a non-empty string — there is no skill
name to announce otherwise. Fails open on anything else: malformed stdin, a
non-dict payload, a `tool_name` other than `Skill` (defensive; the PostToolUse
matcher normally filters this before the script ever runs, but Codex-style
hosts may not honor matchers), or a missing/blank skill name.
"""

# Declares this hook's wiring for scripts/stamp.py to fold into hooks/hooks.json.
WORKSHOP_HOOK = {"event": "PostToolUse", "matcher": "^(Skill|skill)$"}

import json  # noqa: E402
import sys  # noqa: E402

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)

if not isinstance(data, dict):
    sys.exit(0)

if data.get("tool_name") != "Skill":
    sys.exit(0)

tool_input = data.get("tool_input")
skill = tool_input.get("skill") if isinstance(tool_input, dict) else None

if not isinstance(skill, str) or not skill.strip():
    sys.exit(0)

skill = skill.strip()

print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f'You just invoked the "{skill}" skill. Per the '
                    "using-workflow Announce Convention, state "
                    f'"Using {skill} to [purpose]" in your next reply. This '
                    "is a protocol marker, not preamble — it applies even "
                    "under a terse/no-preamble persona."
                ),
            }
        }
    )
)
sys.exit(0)
