"""A preset whose shipped output changed must also carry a version bump.

This is the one failure mode the rest of the gate cannot see: everything is
green, the change merges and promotes, and it silently never reaches anyone.
`claude plugin update` decides there is something to offer by comparing the
manifest version — an unbumped preset ships into the void.

Hit for real on #401, caught by hand. The rule was previously a note in a design
doc ("bump workbench whenever a bundled core skill changes"), which is the kind
of discipline that holds until the once it doesn't.

Compares `dist/<preset>` — the actual shipped artifact, already tracked — rather
than trying to infer which source files feed which preset.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.check_version_bumps import find_level_violations, find_missing_bumps

REPO_ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _preset(repo: Path, name: str, version: str, payload: str) -> None:
    _write(
        repo / "presets" / name / "manifest.json",
        json.dumps({"name": name, "version": version}),
    )
    _write(repo / "dist" / name / "skills" / "s" / "SKILL.md", payload)
    _write(
        repo / "dist" / name / ".claude-plugin" / "plugin.json",
        json.dumps({"name": name, "version": version}),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with `main` holding one released preset."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    _preset(repo, "advisor", "0.1.0", "# v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release")
    git(repo, "checkout", "-q", "-b", "work")
    return repo


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


class TestMissingBumps:
    def test_changed_output_without_a_bump_is_flagged(self, repo: Path) -> None:
        _preset(repo, "advisor", "0.1.0", "# v2 — real change\n")
        commit(repo, "change advisor")

        assert find_missing_bumps(repo, "main") == ["advisor"]

    def test_changed_output_with_a_bump_passes(self, repo: Path) -> None:
        _preset(repo, "advisor", "0.1.1", "# v2 — real change\n")
        commit(repo, "change advisor and bump")

        assert find_missing_bumps(repo, "main") == []

    def test_untouched_preset_needs_no_bump(self, repo: Path) -> None:
        _write(repo / "README.md", "unrelated edit\n")
        commit(repo, "docs only")

        assert find_missing_bumps(repo, "main") == []

    def test_a_brand_new_preset_needs_no_bump(self, repo: Path) -> None:
        """There is no prior version to bump from."""
        _preset(repo, "newcomer", "0.1.0", "# hello\n")
        commit(repo, "add a preset")

        assert find_missing_bumps(repo, "main") == []

    def test_a_deleted_preset_is_not_flagged(self, repo: Path) -> None:
        subprocess.run(["rm", "-rf", str(repo / "dist" / "advisor")], check=True)
        subprocess.run(["rm", "-rf", str(repo / "presets" / "advisor")], check=True)
        commit(repo, "drop advisor")

        assert find_missing_bumps(repo, "main") == []

    def test_every_unbumped_preset_is_reported_not_just_the_first(
        self, repo: Path
    ) -> None:
        """Reporting one at a time turns one fix into three round trips."""
        _preset(repo, "second", "0.1.0", "# a\n")
        _preset(repo, "third", "0.1.0", "# a\n")
        commit(repo, "add two more")
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--ff-only", "work")
        git(repo, "checkout", "-q", "work")

        _preset(repo, "advisor", "0.1.0", "# changed\n")
        _preset(repo, "second", "0.1.0", "# changed\n")
        _preset(repo, "third", "0.2.0", "# changed\n")
        commit(repo, "change three, bump one")

        assert find_missing_bumps(repo, "main") == ["advisor", "second"]

    def test_a_version_only_change_is_fine(self, repo: Path) -> None:
        """Bumping alone rewrites dist's plugin.json — that must not self-flag."""
        _preset(repo, "advisor", "0.1.1", "# v1\n")
        commit(repo, "bump only")

        assert find_missing_bumps(repo, "main") == []


class TestUnavailableBase:
    def test_missing_base_ref_raises_rather_than_passing_silently(
        self, repo: Path
    ) -> None:
        """A gate that quietly does nothing is worse than no gate."""
        with pytest.raises(LookupError):
            find_missing_bumps(repo, "no-such-branch")


class TestCiWiring:
    def test_ci_checks_out_full_history(self) -> None:
        """The gate needs the base ref; checkout@v4 defaults to depth 1.

        Pinned here so a future workflow edit cannot silently defang the gate by
        removing the fetch depth — it would still 'pass', having compared nothing.
        """
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

        assert "fetch-depth: 0" in workflow


class TestBumpLevel:
    """The gate checks *which* part of the version moved, not just that it moved.

    A removed skill and a corrected typo are not the same event to someone with
    the plugin installed: removal changes the trigger surface, so invocations
    silently stop matching. Only the mechanically visible part is enforced —
    the component inventory. Behavioural breaks (a hook that now blocks where it
    did not) still need judgement, and the policy says so rather than pretending.
    """

    def _release(self, repo: Path, version: str, skills: list[str]) -> None:
        _write(
            repo / "presets" / "advisor" / "manifest.json",
            json.dumps({"name": "advisor", "version": version}),
        )
        for skill in skills:
            _write(repo / "dist" / "advisor" / "skills" / skill / "SKILL.md", f"# {skill}\n")
        _write(
            repo / "dist" / "advisor" / ".claude-plugin" / "plugin.json",
            json.dumps({"name": "advisor", "version": version}),
        )

    @pytest.fixture
    def released(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        self._release(repo, "1.2.0", ["alpha", "beta"])
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "release")
        git(repo, "checkout", "-q", "-b", "work")
        return repo

    def _drop_skill(self, repo: Path, skill: str) -> None:
        subprocess.run(
            ["rm", "-rf", str(repo / "dist" / "advisor" / "skills" / skill)], check=True
        )

    def test_removing_a_skill_demands_a_major_bump(self, released: Path) -> None:
        self._drop_skill(released, "beta")
        self._release(released, "1.2.1", ["alpha"])
        commit(released, "drop beta, patch bump")

        violations = find_level_violations(released, "main")

        assert violations == [("advisor", "major", "patch")]

    def test_removing_a_skill_with_a_major_bump_passes(self, released: Path) -> None:
        self._drop_skill(released, "beta")
        self._release(released, "2.0.0", ["alpha"])
        commit(released, "drop beta, major bump")

        assert find_level_violations(released, "main") == []

    def test_adding_a_skill_demands_at_least_a_minor_bump(self, released: Path) -> None:
        self._release(released, "1.2.1", ["alpha", "beta", "gamma"])
        commit(released, "add gamma, patch bump")

        assert find_level_violations(released, "main") == [("advisor", "minor", "patch")]

    def test_adding_a_skill_with_a_minor_bump_passes(self, released: Path) -> None:
        self._release(released, "1.3.0", ["alpha", "beta", "gamma"])
        commit(released, "add gamma, minor bump")

        assert find_level_violations(released, "main") == []

    def test_a_larger_bump_than_required_is_fine(self, released: Path) -> None:
        """Requirements are a floor, not an equality check."""
        self._release(released, "2.0.0", ["alpha", "beta", "gamma"])
        commit(released, "add gamma, major bump")

        assert find_level_violations(released, "main") == []

    def test_content_only_change_is_satisfied_by_a_patch(self, released: Path) -> None:
        self._release(released, "1.2.1", ["alpha", "beta"])
        _write(released / "dist" / "advisor" / "skills" / "alpha" / "SKILL.md", "# reworded\n")
        commit(released, "reword alpha")

        assert find_level_violations(released, "main") == []

    def test_pre_1_0_treats_a_minor_bump_as_the_breaking_bump(
        self, tmp_path: Path
    ) -> None:
        """In 0.x, 0.1.3 -> 0.2.0 is the break signal; demanding 1.0.0 would be wrong."""
        repo = tmp_path / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        self._release(repo, "0.1.3", ["alpha", "beta"])
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "release")
        git(repo, "checkout", "-q", "-b", "work")

        self._drop_skill(repo, "beta")
        self._release(repo, "0.2.0", ["alpha"])
        commit(repo, "drop beta on 0.x")

        assert find_level_violations(repo, "main") == []

    def test_pre_1_0_patch_bump_still_fails_a_removal(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        self._release(repo, "0.1.3", ["alpha", "beta"])
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "release")
        git(repo, "checkout", "-q", "-b", "work")

        self._drop_skill(repo, "beta")
        self._release(repo, "0.1.4", ["alpha"])
        commit(repo, "drop beta with a patch bump")

        assert find_level_violations(repo, "main") == [("advisor", "major", "patch")]

    def test_library_modules_are_not_components(self, released: Path) -> None:
        """Adding a shared hook helper is not a new capability for the owner."""
        _write(released / "dist" / "advisor" / "hooks" / "scripts" / "_shared.py", "x = 1\n")
        self._release(released, "1.2.1", ["alpha", "beta"])
        commit(released, "add a hook library module")

        assert find_level_violations(released, "main") == []
