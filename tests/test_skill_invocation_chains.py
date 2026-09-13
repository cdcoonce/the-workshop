"""Chain guard: a skill another skill routes to must stay model-invocable.

`disable-model-invocation: true` (Part 1) makes a skill invisible to the model —
Claude can never invoke it, only the user typing `/<slug>`. That is safe for a
skill nobody else's workflow depends on, and silently breaks one that another
skill's SKILL.md or references/ routes to mid-workflow (a "Run `/dispatch`
next" step that Claude can no longer act on).

This suite discovers every flagged skill, builds matchers for its slug and any
short alias advertised in its description ("... invokes /X ..."), and scans
every OTHER skill's SKILL.md and references/**/*.md for a hit. Every hit must
either be a documented, deliberate chain (the skill should not have been
flagged — caught by making the mention exist with no allowlist entry) or be
covered by `tests/data/skill_chain_allowlist.json`, which records mentions
that read as informational (a boundary line, a related-skill pointer, a
recommendation to Charles) rather than an actual invocation.

The allowlist is checked in both directions: an uncovered hit fails (something
new routes to a flagged skill, or the allowlist fell behind), and a stale entry
that matches no current hit also fails (the mention that justified it is gone,
so keeping the entry would hide a *future* real regression behind a reason
that no longer applies).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.smoke_test import _parse_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SKILLS = REPO_ROOT / "plugins" / "workbench" / "skills"
ALLOWLIST_PATH = Path(__file__).resolve().parent / "data" / "skill_chain_allowlist.json"

_SKIP_FILENAMES = {"tests.md", "CHANGELOG.md"}

# From the description phrase "... invokes /X ...".
_ALIAS_RE = re.compile(r"invokes /([a-z][\w-]*)")


@dataclass(frozen=True)
class Skill:
    slug: str
    plugin: str
    dir: Path
    frontmatter: dict


def _discover_skills() -> dict[str, Skill]:
    """Every `plugins/*/skills/*/SKILL.md`, parsed with the shared frontmatter reader."""
    skills: dict[str, Skill] = {}
    for skill_md in sorted(REPO_ROOT.glob("plugins/*/skills/*/SKILL.md")):
        slug = skill_md.parent.name
        plugin = skill_md.parents[2].name
        frontmatter = _parse_frontmatter(skill_md.read_text(encoding="utf-8")) or {}
        skills[slug] = Skill(
            slug=slug, plugin=plugin, dir=skill_md.parent, frontmatter=frontmatter
        )
    return skills


def _is_flagged(skill: Skill) -> bool:
    """Strict truthiness: only `true` (or real bool ``True``) counts. A naive
    ``bool(value)`` check would treat the non-empty string ``"false"`` as
    truthy, wrongly scanning an opted-out skill as flagged."""
    value = skill.frontmatter.get("disable-model-invocation")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _alias_for(skill: Skill) -> str | None:
    description = skill.frontmatter.get("description")
    if not isinstance(description, str):
        return None
    match = _ALIAS_RE.search(description)
    return match.group(1) if match else None


def slug_matcher(slug: str) -> re.Pattern:
    """`/slug` as a command, not a path segment: `alert-policy/sync.md` must not count."""
    return re.compile(rf"(?<![\w/.\-])/{re.escape(slug)}(?![\w\-])")


def backtick_matcher(slug: str) -> re.Pattern:
    return re.compile(rf"`{re.escape(slug)}`")


def alias_matcher(alias: str) -> re.Pattern:
    """Like `slug_matcher`, plus excluding a trailing `/` — short aliases are common
    substrings ("sync", "write") that also show up as directory names."""
    return re.compile(rf"(?<![\w/.\-])/{re.escape(alias)}(?![\w/\-])")


def _matchers_for(skill: Skill) -> list[tuple[str, re.Pattern]]:
    matchers = [
        (f"/{skill.slug}", slug_matcher(skill.slug)),
        (f"`{skill.slug}`", backtick_matcher(skill.slug)),
    ]
    alias = _alias_for(skill)
    if alias and alias != skill.slug:
        matchers.append((f"/{alias} (alias)", alias_matcher(alias)))
    return matchers


def _scannable_files(skill_dir: Path) -> list[Path]:
    files = [skill_dir / "SKILL.md"]
    references = skill_dir / "references"
    if references.is_dir():
        files.extend(sorted(references.rglob("*.md")))
    return [f for f in files if f.is_file() and f.name not in _SKIP_FILENAMES]


@dataclass(frozen=True)
class Hit:
    target: str
    in_path: str  # relative to WORKBENCH_SKILLS when possible, else to REPO_ROOT
    line_no: int
    label: str
    text: str

    def location(self) -> str:
        return f"{self.in_path}:{self.line_no}"


def _relative_in_path(path: Path) -> str:
    try:
        return str(path.relative_to(WORKBENCH_SKILLS))
    except ValueError:
        return str(path.relative_to(REPO_ROOT))


def _find_hits(skills: dict[str, Skill]) -> list[Hit]:
    """Every mention of a flagged skill's slug/alias inside an OTHER skill's files."""
    hits: list[Hit] = []
    flagged = {slug: s for slug, s in skills.items() if _is_flagged(s)}
    for target_slug, target in flagged.items():
        matchers = _matchers_for(target)
        for other_slug, other in skills.items():
            if other_slug == target_slug:
                continue
            for file_path in _scannable_files(other.dir):
                lines = file_path.read_text(encoding="utf-8").split("\n")
                for line_no, line in enumerate(lines, start=1):
                    for label, pattern in matchers:
                        if pattern.search(line):
                            hits.append(
                                Hit(
                                    target=target_slug,
                                    in_path=_relative_in_path(file_path),
                                    line_no=line_no,
                                    label=label,
                                    text=line.strip(),
                                )
                            )
    return hits


@dataclass(frozen=True)
class AllowlistEntry:
    target: str
    in_path: str
    reason: str

    def covers(self, hit: Hit) -> bool:
        return self.target == hit.target and self.in_path == hit.in_path


def _load_allowlist() -> list[AllowlistEntry]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return [
        AllowlistEntry(target=e["target"], in_path=e["in"], reason=e["reason"])
        for e in data["entries"]
    ]


# --------------------------------------------------------------------------- #
# Real-tree chain guard
# --------------------------------------------------------------------------- #


def test_no_uncovered_chain_hits() -> None:
    skills = _discover_skills()
    hits = _find_hits(skills)
    allowlist = _load_allowlist()

    uncovered = [h for h in hits if not any(e.covers(h) for e in allowlist)]
    if uncovered:
        lines = "\n".join(f"  {h.location()}: {h.text}" for h in uncovered)
        pytest.fail(
            "Uncovered mention(s) of an explicit-invoke skill found outside its "
            "own files:\n"
            f"{lines}\n"
            "Fix by either unflagging the target skill (it is a real routing "
            "chain — add it to `stay_model_invocable`) or adding an allowlist "
            "entry with a reason to tests/data/skill_chain_allowlist.json if "
            "the mention is merely informational."
        )


def test_no_stale_allowlist_entries() -> None:
    skills = _discover_skills()
    hits = _find_hits(skills)
    allowlist = _load_allowlist()

    stale = [e for e in allowlist if not any(e.covers(h) for h in hits)]
    if stale:
        lines = "\n".join(f"  target={e.target} in={e.in_path} ({e.reason})" for e in stale)
        pytest.fail(
            "Stale allowlist entry(ies) match no current hit — the mention "
            "that justified them is gone, so remove the entry:\n" + lines
        )


def test_chain_guard_actually_finds_something() -> None:
    """Guard the guard: a scan that discovers nothing would pass both tests above
    vacuously, whether or not the matchers still work."""
    skills = _discover_skills()
    hits = _find_hits(skills)
    assert hits, "the chain scan found no hits at all — matchers are likely broken"


# --------------------------------------------------------------------------- #
# Matcher unit tests
# --------------------------------------------------------------------------- #


class TestSlugMatcher:
    def test_write_a_prd_does_not_match_write(self) -> None:
        assert slug_matcher("write").search("/write-a-prd") is None

    def test_grill_me_does_not_match_grill(self) -> None:
        assert slug_matcher("grill").search("/grill-me") is None

    def test_plain_slug_reference_matches(self) -> None:
        assert slug_matcher("handoff").search("per /handoff —") is not None


class TestAliasMatcher:
    def test_write_a_prd_does_not_match_write(self) -> None:
        assert alias_matcher("write").search("/write-a-prd") is None

    def test_grill_me_does_not_match_grill(self) -> None:
        assert alias_matcher("grill").search("/grill-me") is None

    def test_path_segment_does_not_match(self) -> None:
        text = "references/cli/api/alert-policy/sync.md"
        assert alias_matcher("sync").search(text) is None

    def test_plain_alias_reference_matches(self) -> None:
        assert alias_matcher("handoff").search("per /handoff —") is not None

    def test_trailing_slash_does_not_match(self) -> None:
        """The alias matcher is stricter than the slug matcher on what follows:
        a directory-shaped mention ("docs/sync/report.md") must not count."""
        assert alias_matcher("sync").search("docs/sync/report.md") is None


class TestBacktickMatcher:
    def test_backticked_slug_matches(self) -> None:
        assert backtick_matcher("design-an-interface").search(
            "Module or API shape → `design-an-interface`"
        )

    def test_bare_mention_without_backticks_does_not_match(self) -> None:
        assert backtick_matcher("design-an-interface").search(
            "see design-an-interface for details"
        ) is None


class TestIsFlagged:
    def _skill_with(self, value) -> Skill:
        return Skill(
            slug="probe",
            plugin="workbench",
            dir=Path("."),
            frontmatter={"disable-model-invocation": value},
        )

    def test_string_false_is_not_flagged(self) -> None:
        """`bool("false")` is True -- a naive truthiness check would wrongly
        flag a skill whose frontmatter explicitly says `false`."""
        assert _is_flagged(self._skill_with("false")) is False

    def test_string_true_is_flagged(self) -> None:
        assert _is_flagged(self._skill_with("true")) is True


class TestAliasExtraction:
    def test_extracts_alias_from_description(self) -> None:
        skill = Skill(
            slug="vault-dispatch",
            plugin="workbench",
            dir=Path("."),
            frontmatter={
                "description": (
                    "Run Charles's vault /dispatch workflow. Trigger when Charles "
                    "invokes /dispatch, mentions /dispatch, or asks by name."
                )
            },
        )
        assert _alias_for(skill) == "dispatch"

    def test_no_alias_phrase_returns_none(self) -> None:
        skill = Skill(
            slug="create-hook",
            plugin="workbench",
            dir=Path("."),
            frontmatter={"description": "Create and register Claude Code hooks."},
        )
        assert _alias_for(skill) is None
