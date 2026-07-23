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

from scripts.check_version_bumps import find_missing_bumps

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
