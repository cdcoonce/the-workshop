"""Guards that shipped maintainer instructions describe the layout that exists.

The flat reorg (#656) deleted `core/`, `presets/`, `dist/`, `build_preset.py`,
and `build_docs.py`. #650 made "zero stale-layout references under
`plugins/workshop-maintainer/`" a structural acceptance criterion, but nothing
asserted it, so the criterion was reported satisfied while 54 references
survived across 17 files -- see #640.

These are not stale comments. `add-the-workshop-hook` told the reader to put
shared logic in `core/hooks/`, register it in `core/settings-base.json`, and run
`build_preset` to compose into `dist/`. Every one of those paths is gone, so
following the skill start to finish produced nothing. A skill that reads
authoritative and is wrong is worse than a missing one.

Scope is `plugins/workshop-maintainer/` because that is what #640 covers.
`plugins/workbench/` carries the same defect -- including five runnable
`uv run python core/skills/.../*.py` commands that cannot resolve -- tracked
separately in #661. When that lands, add workbench to `SCANNED_PLUGINS` rather
than writing a second copy of this test.

Note on writing the check: `git grep -E` silently matches NOTHING for `\\bcore/`
because git's ERE has no `\\b`. A guard written that way passes by matching
nothing -- the same defect class the reorg already fixed once in
`smoke_test.py`. This uses Python `re` with an explicit non-word lookbehind.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SCANNED_PLUGINS = ("workshop-maintainer",)

# Paths and tool names the flat reorg deleted. A leading non-word guard keeps
# `core/` from matching inside `score/`, which a bare substring search hits.
STALE_LAYOUT = re.compile(r"(?<![A-Za-z0-9_])(core/|presets/|dist/|build_preset|build_docs)")

# `dist/` is also a normal path in the wider world -- npm CDN URLs
# (`cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js`) and `gh release upload
# ./dist/binary` are correct as written and say nothing about this repo's
# layout. Skip lines that are carrying a URL rather than a repo path.
URL = re.compile(r"https?://")

TEXT_SUFFIXES = {".md", ".py", ".sh", ".json", ".toml", ".txt", ".yml", ".yaml"}


def _scan(plugin: str) -> list[str]:
    """Return `path:line: text` for every stale-layout reference in a plugin."""
    root = REPO_ROOT / "plugins" / plugin
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if URL.search(line):
                continue
            if STALE_LAYOUT.search(line):
                rel = path.relative_to(REPO_ROOT)
                findings.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    return findings


def test_maintainer_ships_no_references_to_the_deleted_layout() -> None:
    """Every scanned plugin's shipped text describes the tree that exists."""
    findings: list[str] = []
    for plugin in SCANNED_PLUGINS:
        findings.extend(_scan(plugin))

    assert not findings, (
        f"{len(findings)} reference(s) to the deleted layout "
        f"(core/, presets/, dist/, build_preset, build_docs) survive in "
        f"{', '.join(SCANNED_PLUGINS)}. These are shipped instructions that "
        "cannot resolve -- rewrite them for the flat tree rather than "
        "excluding the path:\n  " + "\n  ".join(findings)
    )


def test_stale_layout_pattern_does_not_fire_on_lookalikes() -> None:
    """The guard must not pass by over-matching, nor miss a real reference.

    Without the lookbehind, `core/` matches inside `score/` and the check
    fails on innocent text; without a check at all, `\\bcore/` under `git grep
    -E` matches nothing and the guard passes vacuously. Pin both directions.
    """
    assert not STALE_LAYOUT.search("see docs/skill-score/summary.md")
    assert not STALE_LAYOUT.search("the hardcore/soft split")
    assert STALE_LAYOUT.search("shared logic goes under `core/hooks/`")
    assert STALE_LAYOUT.search("run build_preset to compose")
    assert STALE_LAYOUT.search("edit presets/workbench/skills/foo")


def test_url_exemption_is_narrow() -> None:
    """URL lines are skipped, but a repo path on a URL-free line still fires."""
    assert URL.search("<script src='https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js'>")
    assert not URL.search("uv run python core/skills/blueprint/scripts/build_fixture.py")
