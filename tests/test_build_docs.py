"""Tests for build_docs.py — the living-documentation generator.

Covers parsing into the model, hook event/wiring cross-validation, fail-fast on
malformed metadata, marker rewriting (idempotency + stale-marker detection),
rendering, and the --check drift gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_docs import (
    DocsError,
    SkillDoc,
    build_model,
    check_docs,
    generate,
    render_preset_readme,
    rewrite_markers,
    write_docs,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _base_settings(hooks: dict) -> str:
    return json.dumps({"hooks": hooks})


@pytest.fixture
def docs_repo(tmp_path: Path) -> Path:
    """A minimal but valid repo tree for build_docs (hooks have docstrings, etc.)."""
    root = tmp_path

    # Core skills.
    for name, desc in [
        ("alpha", "Alpha skill. Use when you need alpha."),
        ("beta", "Beta skill for beta work."),
    ]:
        _write(
            root / "core" / "skills" / name / "SKILL.md",
            f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n",
        )

    # Core agent.
    _write(
        root / "core" / "agents" / "impl" / "AGENT.md",
        "---\nname: impl\ndescription: Implements things.\nrole: implementer\n"
        "skills:\n  add: [alpha]\n  remove: []\n---\n\n# impl\n",
    )

    # Core hook with a docstring that names its real event, wired to PreToolUse.
    _write(
        root / "core" / "hooks" / "guard.py",
        '"""PreToolUse hook: guard risky edits.\n\nMore detail here.\n"""\n',
    )
    # A hook whose docstring uses a descriptive prefix, not an event name.
    _write(
        root / "core" / "hooks" / "formatter.py",
        '"""Post-edit hook: format files after writes."""\n',
    )
    _write(
        root / "core" / "settings-base.json",
        _base_settings(
            {
                "PreToolUse": [
                    {
                        "matcher": "Edit|Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT:-.}"/hooks/run-hook.sh guard.py',
                            }
                        ],
                    }
                ],
                "PostToolUse": [
                    {
                        "matcher": "Edit|Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT:-.}"/hooks/run-hook.sh formatter.py',
                            }
                        ],
                    }
                ],
            }
        ),
    )

    # Methodology docs (project.md must be excluded from the catalog).
    _write(root / "core" / "docs" / "tdd.md", "# TDD\n\nWrite the test first.\n")
    _write(root / "core" / "docs" / "project.md", "# Project\n\nProject-specific.\n")

    # One project preset shipping all core skills + a preset skill + conventions.
    _write(
        root / "presets" / "demo" / "manifest.json",
        json.dumps(
            {
                "name": "demo",
                "description": "Demo preset.",
                "version": "1.0.0",
                "core": {
                    "skills": "all",
                    "agents": "all",
                    "hooks": ["guard.py", "formatter.py"],
                },
                "conventions": ["Lowercase SQL", "Idempotent stages"],
                "exclude": [],
                "preset_skills": ["gamma"],
                "preset_hooks": [],
                "preset_agents": [],
            }
        ),
    )
    _write(root / "presets" / "demo" / "settings-preset.json", "{}")
    _write(
        root / "presets" / "demo" / "skills" / "gamma" / "SKILL.md",
        "---\nname: gamma\ndescription: Gamma preset skill.\n---\n\n# gamma\n",
    )

    return root


class TestBuildModel:
    def test_parses_core_and_preset_skills(self, docs_repo: Path) -> None:
        model = build_model(docs_repo)
        names = {s.name for s in model.skills}
        assert names == {"alpha", "beta", "gamma"}
        gamma = next(s for s in model.skills if s.name == "gamma")
        assert gamma.source == "demo"

    def test_agent_parsed_with_role_and_skills(self, docs_repo: Path) -> None:
        model = build_model(docs_repo)
        agent = next(a for a in model.agents if a.name == "impl")
        assert agent.role == "implementer"
        assert agent.skills_add == ("alpha",)

    def test_hook_events_derived_from_wiring(self, docs_repo: Path) -> None:
        model = build_model(docs_repo)
        guard = next(h for h in model.hooks if h.name == "guard.py")
        assert guard.events == ("PreToolUse",)
        assert guard.summary == "PreToolUse hook: guard risky edits."

    def test_descriptive_prefix_hook_does_not_fail(self, docs_repo: Path) -> None:
        """A 'Post-edit hook:' prefix is prose, not a claimed event — must pass."""
        model = build_model(docs_repo)
        formatter = next(h for h in model.hooks if h.name == "formatter.py")
        assert formatter.events == ("PostToolUse",)

    def test_excluded_hook_is_not_documented_as_shipped(self, docs_repo: Path) -> None:
        """`exclude` must bind for hooks as it already does for skills and agents.

        Otherwise the generated hooks/presets tables and the dist README claim a
        preset ships a hook the build never copies.
        """
        manifest_path = docs_repo / "presets" / "demo" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclude"] = ["hooks/scripts/formatter.py"]
        manifest_path.write_text(json.dumps(manifest))

        model = build_model(docs_repo)

        demo = next(p for p in model.presets if p.name == "demo")
        assert "formatter.py" not in demo.hooks
        assert "guard.py" in demo.hooks
        formatter = next(h for h in model.hooks if h.name == "formatter.py")
        assert "demo" not in formatter.presets

    def test_methodology_excludes_project_doc(self, docs_repo: Path) -> None:
        model = build_model(docs_repo)
        filenames = {d.filename for d in model.methodology}
        assert "tdd.md" in filenames
        assert "project.md" not in filenames

    def test_preset_conventions_parsed(self, docs_repo: Path) -> None:
        model = build_model(docs_repo)
        demo = next(p for p in model.presets if p.name == "demo")
        assert demo.conventions == ("Lowercase SQL", "Idempotent stages")
        assert not demo.is_persona


class TestCrossValidation:
    def test_docstring_event_contradicting_wiring_fails(self, docs_repo: Path) -> None:
        # guard.py claims Stop in its docstring but is wired to PreToolUse.
        _write(
            docs_repo / "core" / "hooks" / "guard.py",
            '"""Stop hook: pretend to run at stop."""\n',
        )
        with pytest.raises(DocsError, match="claims event 'Stop'"):
            build_model(docs_repo)

    def test_matching_event_passes(self, docs_repo: Path) -> None:
        _write(
            docs_repo / "core" / "hooks" / "guard.py",
            '"""PreToolUse hook: still correct."""\n',
        )
        build_model(docs_repo)  # no raise


class TestFailFast:
    def test_skill_missing_description_fails(self, docs_repo: Path) -> None:
        _write(
            docs_repo / "core" / "skills" / "alpha" / "SKILL.md",
            "---\nname: alpha\n---\n\n# alpha\n",
        )
        with pytest.raises(DocsError, match="'description'"):
            build_model(docs_repo)

    def test_hook_missing_docstring_fails(self, docs_repo: Path) -> None:
        _write(docs_repo / "core" / "hooks" / "guard.py", "x = 1\n")
        with pytest.raises(DocsError, match="no module docstring"):
            build_model(docs_repo)

    def test_hook_syntax_error_fails(self, docs_repo: Path) -> None:
        _write(docs_repo / "core" / "hooks" / "guard.py", "def (:\n")
        with pytest.raises(DocsError, match="not parseable Python"):
            build_model(docs_repo)

    def test_agent_missing_role_fails(self, docs_repo: Path) -> None:
        _write(
            docs_repo / "core" / "agents" / "impl" / "AGENT.md",
            "---\nname: impl\ndescription: x\n---\n\n# impl\n",
        )
        with pytest.raises(DocsError, match="'role'"):
            build_model(docs_repo)

    def test_skill_no_frontmatter_fails(self, docs_repo: Path) -> None:
        _write(
            docs_repo / "core" / "skills" / "alpha" / "SKILL.md",
            "# alpha\n\nNo frontmatter here.\n",
        )
        with pytest.raises(DocsError, match="no valid frontmatter"):
            build_model(docs_repo)

    def test_skill_missing_skill_md_fails(self, docs_repo: Path) -> None:
        (docs_repo / "core" / "skills" / "alpha" / "SKILL.md").unlink()
        with pytest.raises(DocsError, match="has no SKILL.md"):
            build_model(docs_repo)

    def test_agent_missing_agent_md_fails(self, docs_repo: Path) -> None:
        (docs_repo / "core" / "agents" / "impl" / "AGENT.md").unlink()
        with pytest.raises(DocsError, match="has no AGENT.md"):
            build_model(docs_repo)

    def test_skill_dir_holding_only_build_artifacts_is_skipped(
        self, docs_repo: Path
    ) -> None:
        """Git leaves ignored files behind on a branch switch; that is not a skill.

        Switching off a branch that added a skill removes its tracked files but
        keeps `__pycache__/`, because git will not delete ignored content. The
        leftover directory used to fail `make docs` on a clean checkout, naming a
        skill that does not exist on that branch.
        """
        _write(
            docs_repo / "core" / "skills" / "gone" / "scripts" / "__pycache__" / "x.pyc",
            "",
        )

        model = build_model(docs_repo)

        assert "gone" not in {s.name for s in model.skills}

    def test_preset_skill_dir_holding_only_build_artifacts_is_skipped(
        self, docs_repo: Path
    ) -> None:
        _write(
            docs_repo / "presets" / "demo" / "skills" / "gone" / "__pycache__" / "x.pyc",
            "",
        )

        model = build_model(docs_repo)

        assert "gone" not in {s.name for s in model.skills}

    def test_agent_dir_holding_only_build_artifacts_is_skipped(
        self, docs_repo: Path
    ) -> None:
        _write(docs_repo / "core" / "agents" / "gone" / "__pycache__" / "x.pyc", "")

        model = build_model(docs_repo)

        assert "gone" not in {a.name for a in model.agents}

    def test_skill_dir_with_real_files_but_no_skill_md_still_fails(
        self, docs_repo: Path
    ) -> None:
        """The genuinely malformed case must keep failing loudly."""
        _write(docs_repo / "core" / "skills" / "broken" / "scripts" / "run.py", "x = 1\n")

        with pytest.raises(DocsError, match="has no SKILL.md"):
            build_model(docs_repo)

    def test_non_string_description_fails(self, docs_repo: Path) -> None:
        # A mapping value for description must fail loudly, not ship a dict repr.
        _write(
            docs_repo / "core" / "skills" / "alpha" / "SKILL.md",
            "---\nname: alpha\ndescription:\n  add: [x]\n---\n\n# alpha\n",
        )
        with pytest.raises(DocsError, match="non-string field 'description'"):
            build_model(docs_repo)

    def test_invalid_manifest_json_fails(self, docs_repo: Path) -> None:
        _write(
            docs_repo / "presets" / "demo" / "manifest.json",
            '{"name": "demo", "core": {"skills": "all"},}',  # trailing comma
        )
        with pytest.raises(DocsError, match="Invalid JSON"):
            build_model(docs_repo)

    def test_unwired_hook_claiming_event_fails(self, docs_repo: Path) -> None:
        # A hook whose docstring claims a real event but is wired to nothing.
        _write(
            docs_repo / "core" / "hooks" / "loose.py",
            '"""Stop hook: never wired anywhere."""\n',
        )
        with pytest.raises(DocsError, match="not wired to any event"):
            build_model(docs_repo)

    def test_conventions_non_list_fails(self, docs_repo: Path) -> None:
        manifest = json.loads(
            (docs_repo / "presets" / "demo" / "manifest.json").read_text()
        )
        manifest["conventions"] = "Lowercase SQL"  # string, not list
        _write(docs_repo / "presets" / "demo" / "manifest.json", json.dumps(manifest))
        with pytest.raises(DocsError, match="conventions must be a list"):
            build_model(docs_repo)


class TestOverrideSemantics:
    def test_preset_shadowing_core_skill_marked_override(self, docs_repo: Path) -> None:
        _write(
            docs_repo / "presets" / "demo" / "skills" / "alpha" / "SKILL.md",
            "---\nname: alpha\ndescription: Overriding alpha.\n---\n\n# alpha\n",
        )
        model = build_model(docs_repo)
        override = next(
            s for s in model.skills if s.name == "alpha" and s.source == "demo"
        )
        assert override.overrides_core is True
        page = build_model_skills_page(docs_repo)
        assert "*(override)*" in page
        assert "overrides the core skill" in page


def build_model_skills_page(root: Path) -> str:
    from scripts.build_docs import render_skills_page

    return render_skills_page(build_model(root))


class TestPersonaAndUnwiredRendering:
    def test_base_settings_false_preset_hooks_render(self, tmp_path: Path) -> None:
        # A persona-style preset (base_settings false, preset-only settings) that
        # wires its own hook exercises the _merged_settings_for preset-only branch.
        root = tmp_path
        _write(
            root / "core" / "settings-base.json",
            _base_settings({}),
        )
        _write(
            root / "core" / "hooks" / "inject.py",
            '"""SessionStart hook: inject a persona."""\n',
        )
        _write(
            root / "core" / "skills" / "a" / "SKILL.md",
            "---\nname: a\ndescription: A.\n---\n",
        )
        _write(
            root / "presets" / "persona-x" / "manifest.json",
            json.dumps(
                {
                    "name": "persona-x",
                    "description": "Persona.",
                    "version": "1.0.0",
                    "base_settings": False,
                    "core": {"skills": [], "agents": [], "hooks": ["inject.py"]},
                    "preset_skills": [],
                }
            ),
        )
        _write(
            root / "presets" / "persona-x" / "settings-preset.json",
            _base_settings(
                {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'uv run "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/inject.py"',
                                }
                            ]
                        }
                    ]
                }
            ),
        )
        model = build_model(root)
        inject = next(h for h in model.hooks if h.name == "inject.py")
        assert inject.events == ("SessionStart",)
        persona = next(p for p in model.presets if p.name == "persona-x")
        assert persona.is_persona is True


class TestFirstSentenceAndEscaping:
    def test_first_sentence_keeps_abbreviations(self) -> None:
        from scripts.build_docs import _first_sentence

        assert (
            _first_sentence("Deploy the service, e.g. AWS Lambda. Use when shipping.")
            == "Deploy the service, e.g. AWS Lambda."
        )

    def test_first_sentence_keeps_bare_number(self) -> None:
        from scripts.build_docs import _first_sentence

        assert _first_sentence("Targets Python 3. Modern syntax.").startswith(
            "Targets Python 3."
        )

    def test_preset_readme_escapes_name_and_role(self) -> None:
        from scripts.build_docs import AgentDoc

        agents = [
            AgentDoc(
                name="a|b", description="x.", role="r|s", skills_add=(), source="dist"
            )
        ]
        out = render_preset_readme(name="d", description="", skills=[], agents=agents)
        assert "a\\|b" in out
        assert "r\\|s" in out


class TestMarkerIntegrity:
    def test_block_containing_own_end_marker_raises(self) -> None:
        text = "<!-- BEGIN GENERATED: x -->\n<!-- END GENERATED: x -->\n"
        bad = "line1\n<!-- END GENERATED: x -->\nline2"
        with pytest.raises(DocsError, match="its own END marker"):
            rewrite_markers(text, {"x": bad})

    def test_orphaned_begin_marker_raises(self) -> None:
        text = "<!-- BEGIN GENERATED: x -->\nbody\n"  # no END
        with pytest.raises(DocsError, match="Unpaired or id-mismatched"):
            rewrite_markers(text, {"x": "C"})

    def test_id_mismatched_markers_raise(self) -> None:
        text = "<!-- BEGIN GENERATED: counts -->\n<!-- END GENERATED: countz -->\n"
        with pytest.raises(DocsError, match="Unpaired or id-mismatched"):
            rewrite_markers(text, {"counts": "C"})


class TestRewriteMarkers:
    def test_fills_empty_marker(self) -> None:
        text = "a\n<!-- BEGIN GENERATED: x -->\n<!-- END GENERATED: x -->\nb\n"
        out = rewrite_markers(text, {"x": "CONTENT"})
        assert "<!-- BEGIN GENERATED: x -->\nCONTENT\n<!-- END GENERATED: x -->" in out
        assert out.startswith("a\n")
        assert out.endswith("b\n")

    def test_replaces_existing_content(self) -> None:
        text = "<!-- BEGIN GENERATED: x -->\nOLD\n<!-- END GENERATED: x -->\n"
        out = rewrite_markers(text, {"x": "NEW"})
        assert "OLD" not in out
        assert "NEW" in out

    def test_idempotent(self) -> None:
        text = "<!-- BEGIN GENERATED: x -->\n<!-- END GENERATED: x -->\n"
        once = rewrite_markers(text, {"x": "C"})
        twice = rewrite_markers(once, {"x": "C"})
        assert once == twice

    def test_unknown_marker_id_raises(self) -> None:
        text = "<!-- BEGIN GENERATED: y -->\n<!-- END GENERATED: y -->\n"
        with pytest.raises(DocsError, match="marker 'y' has no registered content"):
            rewrite_markers(text, {"x": "C"})

    def test_multiple_markers_do_not_bleed(self) -> None:
        text = (
            "<!-- BEGIN GENERATED: a -->\n<!-- END GENERATED: a -->\n"
            "middle\n"
            "<!-- BEGIN GENERATED: b -->\n<!-- END GENERATED: b -->\n"
        )
        out = rewrite_markers(text, {"a": "AAA", "b": "BBB"})
        assert "AAA" in out and "BBB" in out and "middle" in out


class TestRenderPresetReadme:
    def test_includes_name_conventions_and_skills(self) -> None:
        skills = [SkillDoc(name="alpha", description="Alpha. Use it.", source="dist")]
        out = render_preset_readme(
            name="demo",
            description="Demo preset.",
            skills=skills,
            agents=[],
            conventions=("Lowercase SQL",),
        )
        assert "# demo" in out
        assert "Lowercase SQL" in out
        assert "`/alpha`" in out
        assert "## CLAUDE.md Template" in out

    def test_escapes_pipes_in_descriptions(self) -> None:
        skills = [SkillDoc(name="a", description="uses a | b pipe.", source="dist")]
        out = render_preset_readme(name="d", description="", skills=skills, agents=[])
        assert "a \\| b pipe" in out


class TestGenerateAndCheck:
    def test_generate_writes_reference_pages(self, docs_repo: Path) -> None:
        written = write_docs(docs_repo)
        names = {p.name for p in written}
        assert {
            "skills.md",
            "agents.md",
            "hooks.md",
            "presets.md",
            "methodology.md",
        } <= names
        assert (docs_repo / "docs" / "reference" / "skills.md").exists()

    def test_check_clean_after_write(self, docs_repo: Path) -> None:
        write_docs(docs_repo)
        assert check_docs(docs_repo) == []

    def test_check_detects_stale_after_component_change(self, docs_repo: Path) -> None:
        write_docs(docs_repo)
        # Change a skill description; the generated skills page is now stale.
        _write(
            docs_repo / "core" / "skills" / "alpha" / "SKILL.md",
            "---\nname: alpha\ndescription: A COMPLETELY NEW description.\n---\n\n# alpha\n",
        )
        stale = check_docs(docs_repo)
        assert any(p.name == "skills.md" for p in stale)

    def test_generated_pages_carry_do_not_edit_banner(self, docs_repo: Path) -> None:
        write_docs(docs_repo)
        skills_md = (docs_repo / "docs" / "reference" / "skills.md").read_text()
        assert "do not edit" in skills_md.lower()

    def test_marker_hybrid_readme_regenerated(self, docs_repo: Path) -> None:
        _write(
            docs_repo / "README.md",
            "# Demo\n\n<!-- BEGIN GENERATED: counts -->\n<!-- END GENERATED: counts -->\n",
        )
        outputs = generate(docs_repo)
        readme = outputs[docs_repo / "README.md"]
        assert "universal skills" in readme


class TestSharedHookModules:
    """A private module under core/hooks/ is a library, not a hook."""

    def test_underscore_module_is_not_documented_as_a_hook(
        self, docs_repo: Path
    ) -> None:
        """Hook discovery globs *.py and demands an event-naming docstring.

        A shared helper module has no event, so without this exclusion adding
        one fails `make docs` outright.
        """
        _write(
            docs_repo / "core" / "hooks" / "_git_baseline.py",
            '"""Shared git helpers for hook scripts."""\n',
        )

        model = build_model(docs_repo)

        assert "_git_baseline.py" not in {h.name for h in model.hooks}
