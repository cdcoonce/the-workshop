"""`make bump` moves a plugin's version in the one hand-written file and stamps the rest.

Releases were hand-edited across six files (#1114). Only
`plugins/<n>/.claude-plugin/plugin.json` is hand-written; the codex and cortex
manifests, both marketplaces, the README and `docs/reference/plugins.md` are
stamper output. These tests run the bump against a temp repo and assert the end
state the gates care about: the released version at the base ref advanced by the
level the change needs, every generated copy agrees, and the version-bump and
`stamp --check` gates pass with nothing further edited.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts import bump_version, check_version_bumps, stamp
from scripts.bump_version import BumpError, bump, next_version

REPO_ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest_path(repo: Path, plugin: str) -> Path:
    return repo / "plugins" / plugin / ".claude-plugin" / "plugin.json"


def _plugin(repo: Path, name: str, version: str, payload: str, *, skills=("main",)) -> None:
    _write(
        _manifest_path(repo, name),
        json.dumps({"name": name, "version": version, "description": "d"}, indent=2) + "\n",
    )
    for skill in skills:
        _write(
            repo / "plugins" / name / "skills" / f"{name}-{skill}" / "SKILL.md",
            f"---\nname: {name}-{skill}\ndescription: exercises the bump tests\n---\n{payload}",
        )


def _released(repo: Path, version: str) -> None:
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    _plugin(repo, "advisor", version, "# v1\n")
    stamp.stamp(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release")
    git(repo, "checkout", "-q", "-b", "work")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _released(repo, "1.2.3")
    return repo


def _version(repo: Path, plugin: str = "advisor") -> str:
    return json.loads(_manifest_path(repo, plugin).read_text())["version"]


def _generated_versions(repo: Path, plugin: str = "advisor") -> set[str]:
    return {
        json.loads((repo / "plugins" / plugin / d / "plugin.json").read_text())["version"]
        for d in (".codex-plugin", ".cortex-plugin")
    }


class TestNextVersion:
    @pytest.mark.parametrize(
        ("released", "level", "expected"),
        [
            ("1.2.3", "patch", "1.2.4"),
            ("1.2.3", "minor", "1.3.0"),
            ("1.2.3", "major", "2.0.0"),
            ("0.1.3", "patch", "0.1.4"),
            ("0.1.3", "minor", "0.2.0"),
            # Pre-1.0 the minor position is the breaking signal, so a required
            # `major` lands on the next minor, not 1.0.0 (see actual_level).
            ("0.1.3", "major", "0.2.0"),
        ],
    )
    def test_levels(self, released: str, level: str, expected: str) -> None:
        assert next_version(released, level) == expected

    @pytest.mark.parametrize("bad", ["1.2", "1.2.3-rc1", "x.y.z", ""])
    def test_an_unparseable_version_is_refused(self, bad: str) -> None:
        with pytest.raises(BumpError, match="semver"):
            next_version(bad, "patch")

    def test_an_unknown_level_is_refused(self) -> None:
        with pytest.raises(BumpError, match="level"):
            next_version("1.2.3", "huge")


class TestBump:
    def test_a_content_change_gets_a_patch_bump_and_the_gates_pass(self, repo: Path) -> None:
        _plugin(repo, "advisor", "1.2.3", "# v2 — real change\n")

        result = bump(repo, "advisor", "main")

        assert (result.released, result.new, result.level) == ("1.2.3", "1.2.4", "patch")
        assert _version(repo) == "1.2.4"
        assert _generated_versions(repo) == {"1.2.4"}
        assert check_version_bumps.find_missing_bumps(repo, "main") == []
        assert stamp.check(repo) == []

    def test_an_added_skill_defaults_to_a_minor_bump(self, repo: Path) -> None:
        _plugin(repo, "advisor", "1.2.3", "# v1\n", skills=("main", "extra"))

        assert bump(repo, "advisor", "main").new == "1.3.0"
        assert check_version_bumps.find_level_violations(repo, "main") == []

    def test_a_removed_skill_defaults_to_a_major_bump(self, repo: Path) -> None:
        subprocess.run(
            ["rm", "-rf", str(repo / "plugins" / "advisor" / "skills" / "advisor-main")],
            check=True,
        )
        _write(
            repo / "plugins" / "advisor" / "skills" / "advisor-other" / "SKILL.md",
            "---\nname: advisor-other\ndescription: replaces main\n---\n",
        )

        result = bump(repo, "advisor", "main")

        assert result.level == "major"
        assert result.new == "2.0.0"
        assert check_version_bumps.find_level_violations(repo, "main") == []

    def test_an_explicit_level_overrides_the_default(self, repo: Path) -> None:
        _plugin(repo, "advisor", "1.2.3", "# v2\n")

        assert bump(repo, "advisor", "main", level="minor").new == "1.3.0"

    def test_only_the_version_line_changes_in_the_hand_written_manifest(self, repo: Path) -> None:
        path = _manifest_path(repo, "advisor")
        before = path.read_text()
        _plugin(repo, "advisor", "1.2.3", "# v2\n")
        _write(path, before.replace('  "name"', '    "name"'))  # odd indentation survives
        odd = path.read_text()

        bump(repo, "advisor", "main")

        assert path.read_text() == odd.replace('"1.2.3"', '"1.2.4"')

    def test_running_it_twice_changes_nothing_the_second_time(self, repo: Path) -> None:
        _plugin(repo, "advisor", "1.2.3", "# v2\n")
        bump(repo, "advisor", "main")
        manifest_bytes = _manifest_path(repo, "advisor").read_bytes()

        again = bump(repo, "advisor", "main")

        assert again.changed is False
        assert _version(repo) == "1.2.4"
        assert _manifest_path(repo, "advisor").read_bytes() == manifest_bytes

    def test_a_version_already_bumped_far_enough_by_hand_is_left_alone(self, repo: Path) -> None:
        _plugin(repo, "advisor", "1.2.9", "# v2\n")

        result = bump(repo, "advisor", "main")

        assert result.changed is False
        assert _version(repo) == "1.2.9"

    def test_a_hand_bump_smaller_than_the_change_needs_is_raised(self, repo: Path) -> None:
        _plugin(repo, "advisor", "1.2.4", "# v1\n", skills=("main", "extra"))

        assert bump(repo, "advisor", "main").new == "1.3.0"

    def test_it_repairs_generated_copies_a_hand_edit_left_stale(self, repo: Path) -> None:
        _plugin(repo, "advisor", "1.2.3", "# v2\n")
        bump(repo, "advisor", "main")
        codex = repo / "plugins" / "advisor" / ".codex-plugin" / "plugin.json"
        codex.write_text(codex.read_text().replace("1.2.4", "1.2.3"))

        bump(repo, "advisor", "main")

        assert stamp.check(repo) == []


class TestRefusals:
    def test_an_unknown_plugin_is_refused_and_writes_nothing(self, repo: Path) -> None:
        before = git(repo, "status", "--porcelain")

        with pytest.raises(BumpError, match="no plugin named"):
            bump(repo, "nope", "main")

        assert git(repo, "status", "--porcelain") == before

    def test_an_unresolvable_base_is_refused(self, repo: Path) -> None:
        with pytest.raises(BumpError, match="no-such-ref"):
            bump(repo, "advisor", "no-such-ref")

    def test_a_plugin_absent_from_the_base_has_nothing_to_bump(self, repo: Path) -> None:
        _plugin(repo, "newcomer", "0.1.0", "# hi\n")

        with pytest.raises(BumpError, match="not released"):
            bump(repo, "newcomer", "main")

    def test_a_manifest_with_two_version_fields_is_refused(self, repo: Path) -> None:
        path = _manifest_path(repo, "advisor")
        _plugin(repo, "advisor", "1.2.3", "# v2\n")
        doubled = path.read_text().replace('"version": "1.2.3",', '"version": "1.2.3", "version": "1.2.3",')
        _write(path, doubled)

        with pytest.raises(BumpError, match="exactly one"):
            bump(repo, "advisor", "main")

        assert path.read_text() == doubled

    def test_a_manifest_with_no_version_to_replace_fails_loudly(self, repo: Path) -> None:
        path = _manifest_path(repo, "advisor")
        original = path.read_text()
        _plugin(repo, "advisor", "1.2.3", "# v2\n")
        broken = original.replace('"version"', '"versoin"')
        _write(path, broken)

        with pytest.raises(BumpError, match="version"):
            bump(repo, "advisor", "main")

        assert path.read_text() == broken


class TestCli:
    def test_main_reports_the_change_and_returns_zero(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _plugin(repo, "advisor", "1.2.3", "# v2\n")

        rc = bump_version.main(["advisor", "--repo", str(repo), "--base", "main"])

        out = capsys.readouterr().out
        assert rc == 0
        assert "1.2.3 -> 1.2.4" in out
        assert "plugins/advisor/.codex-plugin/plugin.json" in out

    def test_main_returns_nonzero_and_names_the_cause_on_refusal(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = bump_version.main(["nope", "--repo", str(repo), "--base", "main"])

        assert rc == 1
        assert "no plugin named" in capsys.readouterr().err


class TestMakefileWiring:
    makefile = (REPO_ROOT / "Makefile").read_text()

    def test_make_bump_is_a_target_that_runs_the_script_against_version_base(self) -> None:
        recipe = re.search(r"^bump:\n((?:\t.*\n)+)", self.makefile, re.MULTILINE)
        assert recipe, "Makefile must define a `bump` target"
        assert "scripts.bump_version" in recipe.group(1)
        assert "$(VERSION_BASE)" in recipe.group(1)
        assert "PLUGIN" in recipe.group(1)

    def test_verify_versions_runs_right_after_lint_in_make_test(self) -> None:
        """Lint stays first (test_gate_wiring pins it); a missed bump must fail
        before the long suites, not after them (#1114)."""
        recipe = re.search(r"^test:\n((?:\t.*\n)+)", self.makefile, re.MULTILINE)
        assert recipe
        steps = [line.strip() for line in recipe.group(1).splitlines()]
        assert steps[:2] == ["$(MAKE) lint", "$(MAKE) verify-versions"]
