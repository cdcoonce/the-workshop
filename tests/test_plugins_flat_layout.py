"""Guards that shipped plugin instructions describe the layout that exists.

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

Scope grew to `plugins/workbench/` in #661, which carried the same defect --
including five runnable `uv run python core/skills/.../*.py` commands that
could not resolve.

Note on writing the check: `git grep -E` silently matches NOTHING for `\\bcore/`
because git's ERE has no `\\b`. A guard written that way passes by matching
nothing -- the same defect class the reorg already fixed once in
`smoke_test.py`. This uses Python `re` with an explicit non-word lookbehind.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SCANNED_PLUGINS = ("workshop-maintainer", "workbench")

# Paths and tool names the flat reorg deleted. A leading non-word guard keeps
# `core/` from matching inside `score/`, which a bare substring search hits.
#
# These tokens only ever named THIS repo's tree, so any occurrence is a defect.
# `core/` is pinned to the subtrees that actually existed rather than left bare:
# `project-context` legitimately classifies modules as `core/leaf/orchestrator`,
# which is a taxonomy, not a path, and a bare `core/` cannot tell them apart.
# `dist/` is deliberately NOT here: it is a universal convention, and the
# shipped skills give generic guidance about other people's repos too.
STALE_LAYOUT = re.compile(
    r"(?<![A-Za-z0-9_])(core/(docs|hooks|skills|agents|settings-base)"
    r"|presets/|build_preset|build_docs)"
)

# `dist/` counts only where it names this repo's deleted generated tree. Three
# forms are legitimate and stay legitimate:
#   * a URL path -- `cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js`
#   * an explicitly relative path -- `gh release upload v1.0.0 ./dist/binary`
#   * an enumeration of generic build artifacts alongside `.venv/`,
#     `__pycache__/`, or `build/`, which is advice about any Python repo
# Rewriting correct content to satisfy a lint would be the wrong fix, so the
# exemptions live in the pattern where they can be read and tested, not in a
# per-path allowlist that hides which lines were waved through.
REPO_DIST = re.compile(r"(?<![A-Za-z0-9_./])dist/")
GENERIC_ARTIFACTS = re.compile(r"\.venv/|__pycache__/|build/")
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
            hit = STALE_LAYOUT.search(line) or (
                REPO_DIST.search(line) and not GENERIC_ARTIFACTS.search(line)
            )
            if hit:
                rel = path.relative_to(REPO_ROOT)
                findings.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    return findings


def test_plugins_ship_no_references_to_the_deleted_layout() -> None:
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
    # A taxonomy, not a path -- `project-context` classifies modules this way.
    assert not STALE_LAYOUT.search("classify modules (core/leaf/orchestrator)")
    assert STALE_LAYOUT.search("shared logic goes under `core/hooks/`")
    assert STALE_LAYOUT.search("run build_preset to compose")
    assert STALE_LAYOUT.search("edit presets/workbench/skills/foo")


def test_url_exemption_is_narrow() -> None:
    """URL lines are skipped, but a repo path on a URL-free line still fires."""
    assert URL.search("<script src='https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js'>")
    assert not URL.search("uv run python core/skills/blueprint/scripts/build_fixture.py")


def test_dist_counts_only_when_it_names_this_repos_tree() -> None:
    """`dist/` is ambiguous, so each exemption is pinned in both directions.

    The three legitimate forms must NOT fire, and a real reference to this
    repo's deleted generated tree must still fire -- otherwise the narrowing
    that lets correct generic guidance survive would also let the defect
    through.
    """
    # Legitimate: an explicitly relative path in generic `gh` usage.
    assert not REPO_DIST.search("gh release upload v1.0.0 ./dist/binary")
    # Legitimate: generic Python build artifacts to ignore in any repo.
    generic = "ignore `.venv/`, `__pycache__/`, `.eggs/`, `build/`, `dist/`."
    assert REPO_DIST.search(generic) and GENERIC_ARTIFACTS.search(generic)
    # Still a defect: this repo's own generated tree.
    real = "rebuilds every preset into dist/ and regenerates the marketplace"
    assert REPO_DIST.search(real) and not GENERIC_ARTIFACTS.search(real)
    assert REPO_DIST.search("never edit dist/ or an installed plugin cache")
