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
import re
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


def ci_version_base(base_ref: str) -> str:
    """The `VERSION_BASE` CI hands the gate for a PR targeting `base_ref`.

    Reads the real workflow instead of restating what it ought to say, so
    reverting the base plumbing to a hardcoded `origin/main` turns the tests
    that call this red rather than leaving them green against a fiction.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    # Both spellings the workflow could use: the expression inline, or bound to
    # an env var the shell then expands.
    workflow = re.sub(r"\$\{\{\s*github\.base_ref\s*\}\}", base_ref, workflow)
    match = re.search(r"VERSION_BASE=(\S+)", workflow)
    if match is None:
        raise AssertionError("ci.yml exports no VERSION_BASE for the gate")
    value = match.group(1).rstrip('"')
    return value.replace("${BASE_REF}", base_ref).replace("$BASE_REF", base_ref)


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

    def test_machinery_only_change_needs_no_bump(self, repo: Path) -> None:
        """dist/<preset>/machinery is engine payload, not owner-facing surface."""
        _write(
            repo / "dist" / "advisor" / "machinery" / "engine" / "vault_utils.py",
            "# synced engine module\n",
        )
        commit(repo, "sync machinery payload")

        assert find_missing_bumps(repo, "main") == []

    def test_machinery_change_does_not_mask_a_real_change(self, repo: Path) -> None:
        """A skill edit alongside machinery churn still requires a bump."""
        _write(
            repo / "dist" / "advisor" / "machinery" / "engine" / "vault_utils.py",
            "# synced engine module\n",
        )
        _preset(repo, "advisor", "0.1.0", "# v2 — real change\n")
        commit(repo, "sync machinery and change a skill")

        assert find_missing_bumps(repo, "main") == ["advisor"]


@pytest.fixture
def dev_ahead_of_main(tmp_path: Path) -> Path:
    """The #568 shape: `dev` a version ahead of `main`, a slice cut off `dev`.

    `main` ships advisor 1.0.0. A sibling slice already bumped `dev` to 1.1.0
    and merged. This branch changes advisor again but still says 1.1.0 —
    byte-identical to `dev`'s manifest line, so the rebase was clean and
    nothing warned.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    _preset(repo, "advisor", "1.0.0", "# v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release 1.0.0 on main")

    git(repo, "checkout", "-q", "-b", "dev")
    _preset(repo, "advisor", "1.1.0", "# v2 — the sibling slice\n")
    commit(repo, "bump advisor on dev")

    # CI resolves `origin/<base>`, not a local branch.
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "update-ref", "refs/remotes/origin/dev", "dev")

    git(repo, "checkout", "-q", "-b", "work")
    _preset(repo, "advisor", "1.1.0", "# v3 — this slice, no-op bump\n")
    commit(repo, "change advisor again, forgetting dev already claimed 1.1.0")
    return repo


class TestBaseFollowsPrTarget:
    """The gate's base must follow the PR's target branch (#568).

    Two sibling slices, both cut when `dev` was at one version, can otherwise
    ship different component sets under the same version string: the second
    one's bump is a no-op against `dev` but still looks like a bump against the
    older `main`. Observed on #565/#567 — corrected by hand before merge.
    """

    def test_the_base_ci_derives_for_a_pr_into_dev_catches_the_no_op_bump(
        self, dev_ahead_of_main: Path
    ) -> None:
        """End-to-end: the base CI actually computes, fed to the real gate.

        Reads the base out of `ci.yml`, so hardcoding `VERSION_BASE=origin/main`
        back into the workflow turns this red.
        """
        base = ci_version_base("dev")

        assert find_missing_bumps(dev_ahead_of_main, base) == ["advisor"]

    def test_the_same_tree_slips_past_a_main_based_gate(
        self, dev_ahead_of_main: Path
    ) -> None:
        """The escape being closed: against `main`, 1.0.0 -> 1.1.0 looks bumped."""
        assert find_missing_bumps(dev_ahead_of_main, "origin/main") == []


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

    def test_ci_derives_the_gate_base_from_the_pr_target(self) -> None:
        """Whatever branch the PR targets is the branch the gate compares to."""
        assert ci_version_base("dev") == "origin/dev"
        assert ci_version_base("main") == "origin/main"

    def test_the_base_ref_env_var_is_bound_to_the_pr_target(self) -> None:
        """The shell expansion above is only honest if BASE_REF is that target."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

        assert re.search(r"BASE_REF:\s*\$\{\{\s*github\.base_ref\s*\}\}", workflow)

    def test_the_base_resolution_is_scoped_to_pull_request_events(self) -> None:
        """On push, base_ref is empty — `origin/` alone would fail to resolve.

        Leaving VERSION_BASE unset there hands the Makefile's own `origin/main`
        default to the gate, which is what a push to dev or main wants anyway.
        """
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

        assert "if: github.event_name == 'pull_request'" in workflow


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
