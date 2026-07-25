"""Wiring spec + generators for the vault machinery payload (W4).

Covers the four shipped pieces:

- ``machinery/wiring/hooks-spec.json`` — the single runtime-neutral
  description of the vault's hook wiring.
- ``machinery/tools/wiring_gen.py`` — renders the spec (plus the canonical
  agent ``.md`` files) into per-runtime adapter files under
  ``machinery/rendered/``.
- ``machinery/agents/*.md`` — the canonical agent definitions vendored from
  the vault (Claude-runtime source; the Codex TOMLs are generated twins).
- ``machinery/tools/vendor_map_gen.py`` — regenerates ``vendor-map.json``
  (schema 2) covering engine, agents, rendered surfaces, and both runtimes'
  skills trees.

Fidelity proof: ``tests/fixtures/vault_live_claude_settings.json`` and
``vault_live_codex_hooks.json`` are byte copies of the live vault's
``.claude/settings.json`` and ``.codex/hooks.json``. The generator output is
asserted equivalent to them, so the spec provably reproduces the wiring it
canonicalizes. No test reads or writes the real vault checkout.
"""

from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PRESET_DIR = REPO_ROOT / "presets" / "vault-ops"
MACHINERY_DIR = PRESET_DIR / "machinery"
TOOLS_DIR = MACHINERY_DIR / "tools"
WIRING_SPEC = MACHINERY_DIR / "wiring" / "hooks-spec.json"
RENDERED_DIR = MACHINERY_DIR / "rendered"
AGENTS_DIR = MACHINERY_DIR / "agents"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

AGENT_NAMES = ("brag-spotter", "cross-linker", "people-profiler")

FILE_WRITE_MATCHER = "write|edit|multiedit|multi_edit|Write|Edit|MultiEdit"
RUN_HOOK_PREFIX = 'bash "${CLAUDE_PROJECT_DIR:-.}"/.claude/scripts/run-hook.sh '


def _load_tool(name: str):
    path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_machinery_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def wiring_gen():
    return _load_tool("wiring_gen")


@pytest.fixture
def map_gen():
    return _load_tool("vendor_map_gen")


def _ordered(value) -> str:
    """Serialize preserving insertion order, so key order differences show."""
    return json.dumps(value, indent=2)


# ---------------------------------------------------------------------------
# hooks-spec.json
# ---------------------------------------------------------------------------


class TestHooksSpec:
    def test_versioned_envelope_and_entry_shape(self) -> None:
        data = json.loads(WIRING_SPEC.read_text(encoding="utf-8"))
        assert data["schema"] == 1
        entries = data["entries"]
        assert len(entries) == 7
        for entry in entries:
            assert isinstance(entry["event"], str)
            assert isinstance(entry["script"], str)
            assert isinstance(entry["args"], list)
            assert isinstance(entry["timeout_ms"], int)

    def test_matcher_is_semantic_intent_not_regex(self) -> None:
        data = json.loads(WIRING_SPEC.read_text(encoding="utf-8"))
        matchers = [e["matcher"] for e in data["entries"] if "matcher" in e]
        assert matchers == ["file-write"]
        assert "|" not in matchers[0]

    def test_every_spec_script_exists_in_engine(self) -> None:
        data = json.loads(WIRING_SPEC.read_text(encoding="utf-8"))
        for entry in data["entries"]:
            assert (MACHINERY_DIR / "engine" / entry["script"]).is_file(), (
                f"spec names {entry['script']} but engine/ does not ship it"
            )


# ---------------------------------------------------------------------------
# Canonical agents import
# ---------------------------------------------------------------------------


class TestAgentsImport:
    def test_three_canonical_agents_ship(self) -> None:
        assert sorted(p.name for p in AGENTS_DIR.glob("*.md")) == [
            f"{name}.md" for name in AGENT_NAMES
        ]

    def test_agent_frontmatter_names_match_files(self) -> None:
        for name in AGENT_NAMES:
            text = (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")
            assert text.startswith("---\n")
            assert f"name: {name}\n" in text.split("---")[1]


# ---------------------------------------------------------------------------
# wiring_gen: Claude settings hooks key
# ---------------------------------------------------------------------------


class TestClaudeSettingsHooksRender:
    def test_rendered_file_matches_live_vault_hooks_key(self) -> None:
        """Fidelity proof: the rendered hooks key is byte-equivalent (same
        key order, same JSON shape, same serializer) to the hooks key of the
        vault's live .claude/settings.json, captured as a fixture."""
        live = json.loads(
            (FIXTURES / "vault_live_claude_settings.json").read_text(
                encoding="utf-8"
            )
        )
        rendered_text = (RENDERED_DIR / "claude-settings-hooks.json").read_text(
            encoding="utf-8"
        )
        assert rendered_text == _ordered(live["hooks"]) + "\n"

    def test_render_function_reproduces_live_hooks_key(self, wiring_gen) -> None:
        live = json.loads(
            (FIXTURES / "vault_live_claude_settings.json").read_text(
                encoding="utf-8"
            )
        )
        spec = wiring_gen.load_spec(MACHINERY_DIR)
        rendered = wiring_gen.render_claude_settings_hooks(spec)
        assert _ordered(rendered) == _ordered(live["hooks"])

    def test_stop_chain_order_and_args_preserved(self, wiring_gen) -> None:
        spec = wiring_gen.load_spec(MACHINERY_DIR)
        rendered = wiring_gen.render_claude_settings_hooks(spec)
        stop_hooks = rendered["Stop"][0]["hooks"]
        assert [h["command"] for h in stop_hooks] == [
            RUN_HOOK_PREFIX + "notebook-update.py",
            RUN_HOOK_PREFIX + "graph_gardener.py",
            RUN_HOOK_PREFIX + "session-stop.py --explicit-sync",
        ]
        assert [h["timeout"] for h in stop_hooks] == [10000, 30000, 60000]

    def test_file_write_intent_expands_to_dual_convention_matcher(
        self, wiring_gen
    ) -> None:
        spec = wiring_gen.load_spec(MACHINERY_DIR)
        rendered = wiring_gen.render_claude_settings_hooks(spec)
        assert rendered["PostToolUse"][0]["matcher"] == FILE_WRITE_MATCHER

    def test_unknown_matcher_intent_is_an_error(
        self, wiring_gen, tmp_path: Path
    ) -> None:
        machinery = tmp_path / "machinery"
        (machinery / "wiring").mkdir(parents=True)
        (machinery / "engine").mkdir()
        (machinery / "engine" / "x.py").write_text("pass\n")
        (machinery / "wiring" / "hooks-spec.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "entries": [
                        {
                            "event": "PostToolUse",
                            "matcher": "not-a-known-intent",
                            "script": "x.py",
                            "args": [],
                            "timeout_ms": 1000,
                        }
                    ],
                }
            )
        )
        with pytest.raises(wiring_gen.WiringSpecError):
            wiring_gen.load_spec(machinery)

    def test_spec_script_missing_from_engine_is_an_error(
        self, wiring_gen, tmp_path: Path
    ) -> None:
        machinery = tmp_path / "machinery"
        (machinery / "wiring").mkdir(parents=True)
        (machinery / "engine").mkdir()
        (machinery / "wiring" / "hooks-spec.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "entries": [
                        {
                            "event": "Stop",
                            "script": "ghost.py",
                            "args": [],
                            "timeout_ms": 1000,
                        }
                    ],
                }
            )
        )
        with pytest.raises(wiring_gen.WiringSpecError):
            wiring_gen.load_spec(machinery)


# ---------------------------------------------------------------------------
# wiring_gen: Codex hooks file
# ---------------------------------------------------------------------------


class TestCodexHooksRender:
    def test_rendered_file_matches_live_vault_semantically(self) -> None:
        """The rendered .codex/hooks.json body carries exactly the live
        vault file's wiring (dict equality — event order is not semantic)."""
        live = json.loads(
            (FIXTURES / "vault_live_codex_hooks.json").read_text(
                encoding="utf-8"
            )
        )
        rendered = json.loads(
            (RENDERED_DIR / "codex-hooks.json").read_text(encoding="utf-8")
        )
        assert rendered == live

    def test_codex_body_is_full_file_with_hooks_envelope(
        self, wiring_gen
    ) -> None:
        spec = wiring_gen.load_spec(MACHINERY_DIR)
        rendered = wiring_gen.render_codex_hooks(spec)
        assert set(rendered) == {"hooks"}
        assert rendered["hooks"] == wiring_gen.render_claude_settings_hooks(spec)


# ---------------------------------------------------------------------------
# wiring_gen: Codex agent TOML twins
# ---------------------------------------------------------------------------


class TestCodexAgentTomlRender:
    def test_rendered_tomls_exist_and_parse(self) -> None:
        for name in AGENT_NAMES:
            path = RENDERED_DIR / "codex-agents" / f"{name}.toml"
            assert path.is_file()
            tomllib.loads(path.read_text(encoding="utf-8"))

    def test_toml_fields_come_from_canonical_md(self) -> None:
        """name/description from frontmatter; developer_instructions is the
        full .md body — including the Agent Contract paragraph the
        hand-written vault TOMLs had dropped (the .md is canonical)."""
        for name in AGENT_NAMES:
            md_text = (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")
            _, frontmatter, body = md_text.split("---", 2)
            parsed = tomllib.loads(
                (RENDERED_DIR / "codex-agents" / f"{name}.toml").read_text(
                    encoding="utf-8"
                )
            )
            assert parsed["name"] == name
            expected_description = next(
                line.split(":", 1)[1].strip()
                for line in frontmatter.splitlines()
                if line.startswith("description:")
            )
            assert parsed["description"] == expected_description
            assert parsed["developer_instructions"] == body.strip("\n")
            assert "Agent Contract.md" in parsed["developer_instructions"]

    def test_toml_escapes_quotes_and_backslashes(
        self, wiring_gen, tmp_path: Path
    ) -> None:
        md = tmp_path / "tricky.md"
        md.write_text(
            '---\nname: tricky\ndescription: says "hi" \\ there\n---\n\n'
            'Body with a trailing quote run: he said """x"""\n'
            "and a backslash: C:\\path\n"
            'ends with a quote"',
            encoding="utf-8",
        )
        rendered = wiring_gen.render_codex_agent_toml(md)
        parsed = tomllib.loads(rendered)
        assert parsed["name"] == "tricky"
        assert parsed["description"] == 'says "hi" \\ there'
        assert parsed["developer_instructions"].endswith('ends with a quote"')
        assert 'he said """x"""' in parsed["developer_instructions"]
        assert "C:\\path" in parsed["developer_instructions"]


# ---------------------------------------------------------------------------
# Rendered tree freshness + determinism
# ---------------------------------------------------------------------------


class TestRenderedTreeFreshness:
    def test_committed_rendered_tree_is_fresh_and_deterministic(
        self, wiring_gen, tmp_path: Path
    ) -> None:
        """Re-rendering the committed spec + agents byte-reproduces the
        committed rendered/ tree; two renders are byte-identical."""
        out_a = tmp_path / "a"
        out_b = tmp_path / "b"
        wiring_gen.generate(MACHINERY_DIR, out_dir=out_a)
        wiring_gen.generate(MACHINERY_DIR, out_dir=out_b)

        rel = sorted(
            p.relative_to(out_a).as_posix()
            for p in out_a.rglob("*")
            if p.is_file()
        )
        committed = sorted(
            p.relative_to(RENDERED_DIR).as_posix()
            for p in RENDERED_DIR.rglob("*")
            if p.is_file()
        )
        assert rel == committed
        for relative in rel:
            fresh = (out_a / relative).read_bytes()
            assert fresh == (out_b / relative).read_bytes()
            assert fresh == (RENDERED_DIR / relative).read_bytes(), (
                f"committed rendered/{relative} is stale — run make build"
            )


# ---------------------------------------------------------------------------
# vendor_map_gen: the generated schema-2 map
# ---------------------------------------------------------------------------


class TestVendorMapGeneration:
    def _map(self) -> dict:
        return json.loads(
            (MACHINERY_DIR / "vendor-map.json").read_text(encoding="utf-8")
        )

    def test_schema_is_2(self) -> None:
        assert self._map()["schema"] == 2

    def test_committed_map_is_fresh(self, map_gen) -> None:
        regenerated = map_gen.generate_map(MACHINERY_DIR)
        committed_text = (MACHINERY_DIR / "vendor-map.json").read_text(
            encoding="utf-8"
        )
        assert committed_text == json.dumps(regenerated, indent=2) + "\n"

    def test_agent_md_entries(self) -> None:
        entries = {
            e["source"]: e["target"]
            for e in self._map()["entries"]
            if e["source"].startswith("agents/")
        }
        assert entries == {
            f"agents/{name}.md": f".claude/agents/{name}.md"
            for name in AGENT_NAMES
        }

    def test_codex_agent_toml_entries(self) -> None:
        entries = {
            e["source"]: e["target"]
            for e in self._map()["entries"]
            if e["source"].startswith("rendered/codex-agents/")
        }
        assert entries == {
            f"rendered/codex-agents/{name}.toml": f".codex/agents/{name}.toml"
            for name in AGENT_NAMES
        }

    def test_codex_hooks_file_entry(self) -> None:
        matches = [
            e
            for e in self._map()["entries"]
            if e["target"] == ".codex/hooks.json"
        ]
        assert matches == [
            {
                "kind": "file",
                "source": "rendered/codex-hooks.json",
                "target": ".codex/hooks.json",
            }
        ]

    def test_settings_hooks_is_a_json_key_merge_not_a_file_copy(self) -> None:
        matches = [
            e
            for e in self._map()["entries"]
            if e["target"] == ".claude/settings.json"
        ]
        assert matches == [
            {
                "kind": "json-key",
                "source": "rendered/claude-settings-hooks.json",
                "target": ".claude/settings.json",
                "key": "hooks",
            }
        ]

    def test_skills_tree_mapped_to_both_runtimes_exactly(self) -> None:
        """Map <-> skills-tree consistency: every file of every preset skill
        is mapped to both runtimes' skill trees; no stale entries linger."""
        skills_root = PRESET_DIR / "skills"
        tree = {
            p.relative_to(skills_root).as_posix()
            for p in skills_root.rglob("*")
            if p.is_file() and not p.name == ".DS_Store"
        }
        assert tree, "expected a non-empty skills tree"

        skill_entries = [
            e
            for e in self._map()["entries"]
            if e["source"].startswith("skills/")
        ]
        assert all(e["kind"] == "file" for e in skill_entries)
        assert all(e.get("source_root") == "preset" for e in skill_entries)

        claude_targets = {
            e["source"].removeprefix("skills/")
            for e in skill_entries
            if e["target"].startswith(".claude/skills/")
        }
        codex_targets = {
            e["source"].removeprefix("skills/")
            for e in skill_entries
            if e["target"].startswith(".codex/skills/")
        }
        assert claude_targets == tree
        assert codex_targets == tree
        for entry in skill_entries:
            relative = entry["source"].removeprefix("skills/")
            assert entry["target"].endswith(f"/skills/{relative}")

    def test_engine_entries_still_follow_v1_rule(self) -> None:
        """Every engine file is mapped — except the scaffold-owned
        vault_scope.py, which init writes once and upgrade never touches."""
        engine_entries = [
            e
            for e in self._map()["entries"]
            if e["source"].startswith("engine/")
        ]
        engine_tree = {
            p.relative_to(MACHINERY_DIR).as_posix()
            for p in (MACHINERY_DIR / "engine").rglob("*")
            if p.is_file() and not p.name.endswith(".pyc")
        }
        assert {e["source"] for e in engine_entries} == engine_tree - {
            "engine/vault_scope.py"
        }
        for entry in engine_entries:
            relative = entry["source"].removeprefix("engine/")
            assert entry["target"] == f".claude/scripts/{relative}"

    def test_lifecycle_tools_are_vendored_into_scripts(self) -> None:
        """W5: the sync/check pair lands in the vault so hooks and afk Docker
        slices can run the drift check offline."""
        tools_entries = {
            e["source"]: e["target"]
            for e in self._map()["entries"]
            if e["source"].startswith("tools/")
        }
        assert tools_entries == {
            "tools/machinery_check.py": ".claude/scripts/machinery_check.py",
            "tools/machinery_sync.py": ".claude/scripts/machinery_sync.py",
        }

    def test_map_targets_are_unique(self) -> None:
        targets = [e["target"] for e in self._map()["entries"]]
        assert len(targets) == len(set(targets))

    def test_total_entry_count_accounts_for_every_section(self) -> None:
        entries = self._map()["entries"]
        engine = sum(1 for e in entries if e["source"].startswith("engine/"))
        tools = sum(1 for e in entries if e["source"].startswith("tools/"))
        skills = sum(1 for e in entries if e["source"].startswith("skills/"))
        agents = sum(1 for e in entries if e["source"].startswith("agents/"))
        rendered = sum(
            1 for e in entries if e["source"].startswith("rendered/")
        )
        assert engine >= 27
        assert tools == 2  # machinery_check + machinery_sync
        assert agents == 3
        assert rendered == 5  # 3 agent TOMLs + codex hooks + settings key
        assert skills % 2 == 0 and skills > 0
        assert len(entries) == engine + tools + skills + agents + rendered
