"""Tests for the marketplace index the stamper renders.

`build_marketplace` composed presets into `dist/` and wrote two
`marketplace.json` files from that build. The flat tree has no build and no
`dist/`: `scripts/stamp.py` renders both marketplace indexes straight from the
plugin manifests it reads out of `plugins/*/.claude-plugin/plugin.json`, and
every plugin is served in place at `./plugins/<directory>` rather than a built
copy.

`tests/test_stamp.py` already covers the Codex/Claude shape difference end to
end (the `interface` block, the structured `source`/`policy`/`category`), so
that is not re-asserted here. This file covers what is specific to the Claude
index's own fields, plus the plugin-selection logic (`build_model` walking
`plugins/`) that both renderers share.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import stamp

# --------------------------------------------------------------------------
# Rendering from a hand-built model -- no filesystem involved
# --------------------------------------------------------------------------


def _plugin_doc(
    name: str, directory_name: str, *, version: str = "1.0.0", description: str = "A plugin."
) -> stamp.PluginDoc:
    """Build a minimal PluginDoc for exercising render_marketplace in isolation.

    Real PluginDocs come from `stamp.build_model` walking `plugins/`; this
    skips that walk for tests that only care about the render, not discovery.
    """
    return stamp.PluginDoc(
        name=name,
        directory=Path(directory_name),
        version=version,
        description=description,
        conventions=(),
        manifest={"name": name, "version": version, "description": description},
        skills=(),
        agents=(),
        hooks=(),
        hooks_json=None,
        is_persona=False,
        wants_run_hook=False,
    )


def test_marketplace_has_name_and_owner() -> None:
    """The Claude index carries the marketplace identity -- name and owner.

    Owner in particular is a Claude-only field; Codex's index has no such
    concept (see test_stamp.py's shape-difference coverage).
    """
    model = stamp.StampModel(plugins=[_plugin_doc("demo", "demo")])
    data = json.loads(stamp.render_marketplace(model))
    assert data["name"] == stamp.MARKETPLACE_NAME
    assert data["owner"]["name"]


def test_marketplace_lists_every_plugin() -> None:
    """Every plugin in the model gets an entry -- none silently dropped."""
    model = stamp.StampModel(
        plugins=[
            _plugin_doc("alpha", "alpha"),
            _plugin_doc("beta", "beta"),
            _plugin_doc("gamma", "gamma"),
        ]
    )
    data = json.loads(stamp.render_marketplace(model))
    names = {p["name"] for p in data["plugins"]}
    assert names == {"alpha", "beta", "gamma"}


def test_marketplace_plugin_has_required_fields() -> None:
    """Each entry carries name, version, description, and a source path.

    source points at the served directory (`./plugins/<dir>`) now, not a
    built copy under `./dist/<dir>` -- there is no build.
    """
    model = stamp.StampModel(
        plugins=[_plugin_doc("demo", "demo", version="2.3.1", description="Does demo things.")]
    )
    entry = json.loads(stamp.render_marketplace(model))["plugins"][0]
    assert entry["name"] == "demo"
    assert entry["version"] == "2.3.1"
    assert entry["description"] == "Does demo things."
    assert entry["source"] == "./plugins/demo"


def test_marketplace_plugins_have_no_duplicate_names() -> None:
    """Distinct plugins render as distinct entries.

    render_marketplace trusts each PluginDoc's name without deduplicating --
    nothing re-checks it at render time (`_check_slug_uniqueness` guards skill
    slugs, not plugin names; see test below for what that means for a real
    collision). This locks in that ordinary, distinctly-named plugins never
    collide in the render.
    """
    model = stamp.StampModel(plugins=[_plugin_doc("alpha", "alpha"), _plugin_doc("beta", "beta")])
    names = [p["name"] for p in json.loads(stamp.render_marketplace(model))["plugins"]]
    assert len(names) == len(set(names))


# --------------------------------------------------------------------------
# Plugin discovery -- via build_model over a real directory tree
# --------------------------------------------------------------------------


def test_marketplace_plugins_sorted_by_directory_name(flat_repo: Path, make_plugin) -> None:
    """Entries come out in directory order, so the index reads consistently.

    render_marketplace does no sorting of its own -- it walks `model.plugins`
    in whatever order `build_model` produced, which is `_plugin_dirs`' sorted
    directory walk. A plugin's directory name conventionally matches its
    manifest name, so in practice this reads as "sorted by name".
    """
    make_plugin(flat_repo, "alpha-plugin")
    make_plugin(flat_repo, "zulu-plugin")
    model = stamp.build_model(flat_repo)
    names = [p["name"] for p in json.loads(stamp.render_marketplace(model))["plugins"]]
    assert names == sorted(names)


def test_marketplace_skips_plugin_dir_without_manifest(flat_repo: Path) -> None:
    """A plugins/ directory with no .claude-plugin/plugin.json is not a plugin.

    `_plugin_dirs` is what decides what counts as a served plugin; a bare
    directory (an in-progress plugin, leftover debris) must not show up in
    the index.
    """
    (flat_repo / "plugins" / "not-a-plugin").mkdir()
    model = stamp.build_model(flat_repo)
    names = {p.name for p in model.plugins}
    assert "not-a-plugin" not in names
    assert "demo" in names  # flat_repo's own fixture plugin


def test_marketplace_skips_non_directory_entries_under_plugins(flat_repo: Path) -> None:
    """A stray file directly under plugins/ (e.g. a README) is not a plugin."""
    (flat_repo / "plugins" / "NOTES.md").write_text("# notes\n")
    model = stamp.build_model(flat_repo)
    names = {p.name for p in model.plugins}
    assert "NOTES.md" not in names
    assert "demo" in names


def test_marketplace_source_uses_directory_name_not_manifest_name(
    flat_repo: Path, make_plugin
) -> None:
    """source is derived from the plugin's directory, not its declared name.

    A plugin is served at `./plugins/<directory>`. If its manifest 'name'
    ever diverges from its directory, the source path has to follow the
    directory -- what is actually on disk -- or `/plugin install` resolves
    nothing.
    """
    diverging = make_plugin(flat_repo, "dir-name", description="Name differs from directory.")
    manifest_path = diverging / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["name"] = "manifest-name"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    model = stamp.build_model(flat_repo)
    entry = next(
        p
        for p in json.loads(stamp.render_marketplace(model))["plugins"]
        if p["name"] == "manifest-name"
    )
    assert entry["source"] == "./plugins/dir-name"


def test_malformed_manifest_raises_a_clear_error(flat_repo: Path) -> None:
    """A plugin.json that is not valid JSON fails loudly, naming the file.

    The old build_marketplace raised ValueError naming the offending preset.
    stamp.py's `_read_json` raises StampError naming the path instead -- same
    intent (fail fast, name the file), different exception type and a path
    rather than a preset name to point at.
    """
    manifest_path = flat_repo / "plugins" / "demo" / ".claude-plugin" / "plugin.json"
    manifest_path.write_text("{not valid json")

    with pytest.raises(stamp.StampError, match="plugin.json"):
        stamp.build_model(flat_repo)


def test_manifest_missing_name_is_a_build_failure(flat_repo: Path, make_plugin) -> None:
    """The raise the old build_marketplace had, restored after the rewrite dropped it.

    `_build_plugin` briefly defaulted to the directory name. That is worse than
    it looks: `name` is what the marketplace advertises and what
    `/plugin install <name>@the-workshop` resolves, so a manifest that forgot
    the field would install under a name its own file never mentions, and the
    mismatch would surface on a machine rather than in CI. The detailed
    assertion on the message lives in tests/test_stamp.py; this one exists so
    the marketplace renderer's own suite notices if the guard disappears again.
    """
    nameless = make_plugin(flat_repo, "nameless-plugin")
    manifest_path = nameless / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["name"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    with pytest.raises(stamp.StampError, match="nameless-plugin"):
        stamp.build_model(flat_repo)
