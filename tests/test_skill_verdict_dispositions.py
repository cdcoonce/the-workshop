"""Every verdict-table row's disposition is reflected in the shipped tree.

#636 graded 79 skills and the owner adjudicated every row: 72 keep, 3 retire,
3 consolidate, 1 relocate. #650 then made "post-reorg shipped skill count is
73 -- workbench 67, workshop-maintainer 4, advisors 2" a structural acceptance
criterion. The reorg relocated every skill wholesale and executed none of the
dispositions, so the criterion was reported satisfied while all seven rows sat
unapplied -- see #659, which found workshop-maintainer shipping 7 skills
against an expected 4.

This is the same root cause as #640 and `test_plugins_flat_layout.py`: the
criterion existed only in an issue body, and nothing asserted it. A verdict
table nobody checks is a record of an intention, not of a state.

The table is the authority. This file only asserts the tree agrees with it, so
changing a disposition means editing the table -- which is the reviewable
artifact -- rather than quietly leaving a skill in place.

A `keep` row is asserted too. Deleting a skill the owner ruled `keep` is the
same class of silent divergence as failing to delete one ruled `retire`, and it
is the direction that actually loses work.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VERDICT_TABLE = REPO_ROOT / "docs/skill-review/2026-08-flat-reorg-verdicts.md"
PLUGINS = REPO_ROOT / "plugins"

# Rows look like `| slug | **verdict** | bucket | usage | notes |`, with the
# verdict bolded only when it is not a plain `keep`. Header and separator rows
# are dropped by requiring the verdict cell to match a known disposition.
ROW = re.compile(r"^\|\s*([a-z0-9-]+)\s*\|\s*\**([a-z-]+(?:-into-[a-z0-9-]+|-to-[a-z0-9-]+)?)\**\s*\|")

KNOWN_VERDICTS = ("keep", "retire", "shelve")
KNOWN_PREFIXES = ("consolidate-into-", "relocate-to-")


def _parse_table() -> dict[str, str]:
    """Read the verdict table into a `{slug: verdict}` map.

    Returns
    -------
    dict[str, str]
        Every graded skill slug mapped to its adjudicated disposition.
    """
    rows: dict[str, str] = {}
    for line in VERDICT_TABLE.read_text().splitlines():
        match = ROW.match(line.strip())
        if match is None:
            continue
        slug, verdict = match.group(1), match.group(2)
        if verdict in KNOWN_VERDICTS or verdict.startswith(KNOWN_PREFIXES):
            rows[slug] = verdict
    return rows


def _shipping_plugins(slug: str) -> list[str]:
    """Every plugin shipping a skill with this slug.

    Parameters
    ----------
    slug : str
        The skill slug to locate.

    Returns
    -------
    list[str]
        Plugin names owning a `skills/<slug>/SKILL.md`, possibly empty. More
        than one is itself a defect, caught by `test_plugin_skill_disjointness`.
    """
    return sorted(p.parents[2].name for p in PLUGINS.glob(f"*/skills/{slug}/SKILL.md"))


TABLE = _parse_table()


def test_table_parsed() -> None:
    """The parser found the graded roster, so an empty map cannot pass silently."""
    assert len(TABLE) >= 75, (
        f"parsed only {len(TABLE)} verdict rows from {VERDICT_TABLE.name}; the "
        "table graded 79. A regex that matches nothing passes every assertion "
        "below, which is the defect this file exists to catch."
    )


@pytest.mark.parametrize("slug", sorted(s for s, v in TABLE.items() if v == "keep"))
def test_keep_rows_still_ship(slug: str) -> None:
    """A skill ruled `keep` is still in the tree."""
    assert _shipping_plugins(slug), (
        f"`{slug}` is ruled `keep` in {VERDICT_TABLE.name} but ships from no "
        "plugin. Removing or renaming it needs the table changed first."
    )


@pytest.mark.parametrize("slug", sorted(s for s, v in TABLE.items() if v == "retire"))
def test_retired_rows_are_gone(slug: str) -> None:
    """A skill ruled `retire` no longer ships."""
    found = _shipping_plugins(slug)
    assert not found, (
        f"`{slug}` is ruled `retire` in {VERDICT_TABLE.name} but still ships "
        f"from {found}."
    )


@pytest.mark.parametrize(
    ("slug", "target"),
    sorted(
        (s, v.removeprefix("consolidate-into-"))
        for s, v in TABLE.items()
        if v.startswith("consolidate-into-")
    ),
)
def test_consolidated_rows_absorbed(slug: str, target: str) -> None:
    """A consolidated skill is gone and its absorbing target still ships."""
    assert not _shipping_plugins(slug), (
        f"`{slug}` is ruled `consolidate-into-{target}` in "
        f"{VERDICT_TABLE.name} but still ships as its own skill."
    )
    assert _shipping_plugins(target), (
        f"`{slug}` was consolidated into `{target}`, but `{target}` ships from "
        "no plugin -- the capability has nowhere to live."
    )


@pytest.mark.parametrize(
    ("slug", "plugin"),
    sorted(
        (s, v.removeprefix("relocate-to-"))
        for s, v in TABLE.items()
        if v.startswith("relocate-to-")
    ),
)
def test_relocated_rows_moved(slug: str, plugin: str) -> None:
    """A relocated skill ships from its destination plugin and nowhere else."""
    found = _shipping_plugins(slug)
    assert found == [plugin], (
        f"`{slug}` is ruled `relocate-to-{plugin}` in {VERDICT_TABLE.name} but "
        f"ships from {found or 'no plugin'}."
    )
