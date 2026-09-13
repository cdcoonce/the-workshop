#!/usr/bin/env python3
"""UserPromptSubmit hook: route a short alias for an explicit-invoke skill.

Part of the explicit-invoke skill slice: skills flagged
`disable-model-invocation: true` in their SKILL.md frontmatter are invisible to
the model and can only be launched by the user typing `/<slug>`. Several also
advertise a short alias in their description's "... invokes /X ..." phrase
(e.g. `vault-standup` answers to `/standup`), but Claude Code only recognizes
the literal slug as a slash command — typing the alias lands as ordinary chat
text. This hook recognizes that alias and tells Claude which SKILL.md to read
and follow, so the alias still routes correctly even though it never triggers
the skill loader itself.

Runs under the vault guard (``runner: "vault"`` below): ``run-vault-hook.sh``
exits before starting an interpreter unless the session is inside a vault
(#667) — the same guard the removed ``vault-user-prompt-classify.py`` ran
under, and for the same reason: this only means something inside Charles's
vault, so every other consumer of workbench must pay nothing for it.

Stdlib only, fail-open: any exception exits 0 with no output. The prompt-shape
check runs before any file I/O, so a plain-text prompt (the overwhelming
majority of turns) costs nothing beyond one regex match.
"""

from __future__ import annotations

# scripts/stamp.py statically reads this constant to build hooks/hooks.json.
WORKSHOP_HOOK = {"event": "UserPromptSubmit", "runner": "vault"}

import json  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

# Does the prompt open with a slash command at all? `(?![\w-])` closes the
# token off from a longer slug sharing the same prefix (`/write` must not
# claim to have matched inside `/write-a-prd`).
_SLASH_COMMAND_RE = re.compile(r"^/[a-z][\w-]*(?![\w-])")

# The frontmatter description phrase that advertises a skill's short alias,
# e.g. "Trigger when Charles invokes /standup, mentions /standup, ...".
_ALIAS_PHRASE_RE = re.compile(r"invokes /([a-z][\w-]*)")


def _read_frontmatter(text: str) -> dict[str, str]:
    """Minimal top-level YAML frontmatter reader: scalars and ``>``/``|`` blocks.

    Reimplemented rather than imported from ``scripts.smoke_test``: this hook
    ships as installed plugin payload, where the repo's top-level ``scripts/``
    package does not exist, so it must not depend on it.
    """
    if not text.startswith("---"):
        return {}
    closing = text.find("\n---", 3)
    if closing == -1:
        return {}
    block = text[3:closing]
    result: dict[str, str] = {}
    current_key: str | None = None
    in_block_scalar = False
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        is_indented = line != line.lstrip()
        if ":" in stripped and not is_indented:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value[:1] in (">", "|"):
                result[key] = ""
                current_key = key
                in_block_scalar = True
            else:
                result[key] = value.strip("\"'")
                current_key = None
                in_block_scalar = False
        elif current_key and is_indented and in_block_scalar:
            result[current_key] = f"{result[current_key]} {stripped}".strip()
    return result


def _is_flag_true(value: object) -> bool:
    """Strict truthiness for a frontmatter flag: only `true` (or real bool
    ``True``) counts. A naive ``bool(value)`` check would treat the non-empty
    string ``"false"`` as truthy, wrongly flagging a skill that explicitly
    opts out."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _alias_map(plugin_root: Path) -> dict[str, str]:
    """alias -> slug, for every skill flagged ``disable-model-invocation: true``.

    A skill whose alias equals its own slug (`vault-audit` answers only to
    `/vault-audit`) contributes nothing here — typing its real slug is not an
    alias lookup, it is the slug itself, and needs no routing help.
    """
    mapping: dict[str, str] = {}
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return mapping
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        slug = skill_md.parent.name
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter = _read_frontmatter(text)
        if not _is_flag_true(frontmatter.get("disable-model-invocation")):
            continue
        match = _ALIAS_PHRASE_RE.search(frontmatter.get("description", ""))
        if not match:
            continue
        alias = match.group(1)
        if alias != slug:
            mapping[alias] = slug
    return mapping


def _matched_alias(prompt: str, aliases: dict[str, str]) -> tuple[str, str] | None:
    """(alias, slug) if ``prompt`` opens with ``/<alias>`` as a whole token."""
    for alias, slug in aliases.items():
        if re.match(rf"^/{re.escape(alias)}(?![\w-])", prompt):
            return alias, slug
    return None


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0

    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return 0

    stripped = prompt.lstrip()
    if not _SLASH_COMMAND_RE.match(stripped):
        return 0  # not a slash command -- exit before any file I/O

    plugin_root = Path(__file__).resolve().parents[2]
    aliases = _alias_map(plugin_root)
    matched = _matched_alias(stripped, aliases)
    if matched is None:
        return 0

    alias, slug = matched
    skill_md = plugin_root / "skills" / slug / "SKILL.md"
    context = (
        f"`/{alias}` is the short alias for the explicit-invoke skill `{slug}` "
        f"(not auto-loaded). Read {skill_md} and follow it, including its "
        "references, before acting."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never let the alias-routing hook break a prompt.
        sys.exit(0)
