"""Tests for tools/wiring_gen.py: agent frontmatter parsing and runtimes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parent.parent / "tools" / "wiring_gen.py"


@pytest.fixture(scope="module")
def wiring_gen():
    spec = importlib.util.spec_from_file_location("_wiring_gen_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _agent(path: Path, frontmatter: str, body: str = "Body.\n") -> Path:
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# #1075 - frontmatter close must be an anchored delimiter line
# ---------------------------------------------------------------------------


class TestFrontmatterClose:
    def test_parse_agent_md_ignores_dash_leading_value_line(
        self, wiring_gen, tmp_path: Path
    ) -> None:
        md = tmp_path / "AGENT.md"
        md.write_text(
            "---\nname: a\ndescription: >\n  first\n---not a delimiter\n"
            "runtimes: [claude]\n---\n\nreal body\n",
            encoding="utf-8",
        )
        name, desc, body = wiring_gen._parse_agent_md(md)
        assert name == "a"
        assert body == "real body"

    def test_agent_runtimes_sees_key_after_dash_leading_line(
        self, wiring_gen, tmp_path: Path
    ) -> None:
        md = tmp_path / "AGENT.md"
        md.write_text(
            "---\nname: a\ndescription: d\nnote: |\n  x\n---dashes\n"
            "runtimes: [claude, codex]\n---\n\nbody\n",
            encoding="utf-8",
        )
        assert wiring_gen._agent_runtimes(md) == ("claude", "codex")

    def test_close_delimiter_with_trailing_whitespace_still_closes(
        self, wiring_gen, tmp_path: Path
    ) -> None:
        md = tmp_path / "AGENT.md"
        md.write_text("---\nname: a\ndescription: d\n---  \n\nbody\n", encoding="utf-8")
        assert wiring_gen._parse_agent_md(md)[2] == "body"

    def test_unterminated_still_raises(self, wiring_gen, tmp_path: Path) -> None:
        md = tmp_path / "AGENT.md"
        md.write_text("---\nname: a\ndescription: d\n---x\nbody\n", encoding="utf-8")
        with pytest.raises(wiring_gen.WiringSpecError):
            wiring_gen._parse_agent_md(md)


# ---------------------------------------------------------------------------
# #771 - block-style runtimes list is rejected, never silently ()
# ---------------------------------------------------------------------------


class TestAgentRuntimes:
    def test_inline_list(self, wiring_gen, tmp_path: Path) -> None:
        md = _agent(tmp_path / "AGENT.md", "name: a\ndescription: d\nruntimes: [claude, codex]")
        assert wiring_gen._agent_runtimes(md) == ("claude", "codex")

    def test_absent_is_claude_only(self, wiring_gen, tmp_path: Path) -> None:
        md = _agent(tmp_path / "AGENT.md", "name: a\ndescription: d")
        assert wiring_gen._agent_runtimes(md) == ()

    def test_block_list_raises(self, wiring_gen, tmp_path: Path) -> None:
        md = _agent(
            tmp_path / "AGENT.md",
            "name: a\ndescription: d\nruntimes:\n  - claude\n  - codex",
        )
        with pytest.raises(wiring_gen.WiringSpecError, match="runtimes"):
            wiring_gen._agent_runtimes(md)

    def test_generate_surfaces_block_list_error(self, wiring_gen, tmp_path: Path) -> None:
        machinery = tmp_path / "plugin" / "machinery"
        (machinery / "wiring").mkdir(parents=True)
        real = TOOL_PATH.parent.parent / "wiring" / "hooks-spec.json"
        (machinery / "wiring" / "hooks-spec.json").write_text(
            real.read_text(encoding="utf-8"), encoding="utf-8"
        )
        engine_src = TOOL_PATH.parent.parent / "engine"
        (machinery / "engine").symlink_to(engine_src)
        agent_dir = tmp_path / "plugin" / "agents" / "blocky"
        agent_dir.mkdir(parents=True)
        _agent(
            agent_dir / "AGENT.md",
            "name: blocky\ndescription: d\nruntimes:\n  - claude\n  - codex",
        )
        with pytest.raises(wiring_gen.WiringSpecError, match="runtimes"):
            wiring_gen.generate(machinery, tmp_path / "out")

    def test_generate_renders_twin_for_inline_form(self, wiring_gen, tmp_path: Path) -> None:
        machinery = tmp_path / "plugin" / "machinery"
        (machinery / "wiring").mkdir(parents=True)
        real = TOOL_PATH.parent.parent / "wiring" / "hooks-spec.json"
        (machinery / "wiring" / "hooks-spec.json").write_text(
            real.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (machinery / "engine").symlink_to(TOOL_PATH.parent.parent / "engine")
        agent_dir = tmp_path / "plugin" / "agents" / "inline"
        agent_dir.mkdir(parents=True)
        _agent(agent_dir / "AGENT.md", "name: inline\ndescription: d\nruntimes: [claude, codex]")
        out = wiring_gen.generate(machinery, tmp_path / "out")
        assert (out / "codex-agents" / "inline.toml").is_file()
