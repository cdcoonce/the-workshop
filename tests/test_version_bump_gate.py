"""A plugin whose shipped output changed must also carry a version bump.

This is the one failure mode the rest of the gate cannot see: everything is
green, the change merges and promotes, and it silently never reaches anyone.
`claude plugin update` decides there is something to offer by comparing the
manifest version — an unbumped plugin ships into the void.

Hit for real on #401, caught by hand. The rule was previously a note in a
design doc ("bump workbench whenever a bundled core skill changes"), which is
the kind of discipline that holds until the once it doesn't.

Compares `plugins/<name>` — the real served directory under the flat plugin
tree, there is no `dist/` any more — against a base ref, with every
stamper-owned path (`scripts.stamp.owned_paths()`) excluded and nothing else.

`machinery/` used to be excluded too, which hid every engine-only change from
the gate: unlike stamper output, the engine is hand-authored and has no source
elsewhere in the tree to trip the gate on its behalf, so excluding it removed
the only signal there was (#694). `TestExclusionsDeriveFromTheStamperMap` is
what keeps a second hand-kept list from growing back.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts import check_version_bumps
from scripts.check_version_bumps import find_level_violations, find_missing_bumps
from scripts.stamp import owned_paths

REPO_ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(repo: Path, plugin: str, version: str, *, description: str = "") -> None:
    _write(
        repo / "plugins" / plugin / ".claude-plugin" / "plugin.json",
        json.dumps({"name": plugin, "version": version, "description": description}),
    )


def _skill(repo: Path, plugin: str, skill: str, body: str) -> None:
    """Write a skill with real frontmatter — `scripts.stamp` refuses one without."""
    _write(
        repo / "plugins" / plugin / "skills" / skill / "SKILL.md",
        f"---\nname: {skill}\ndescription: exercises {skill} for the gate tests\n"
        f"---\n{body}",
    )


def _hook(repo: Path, plugin: str, name: str, body: str) -> None:
    """Write a hook script with a real WORKSHOP_HOOK declaration.

    A plugin that ships hook scripts is the only kind for which the stamper
    owns `hooks/hooks.json` — which puts a generated file in the *same
    directory tree* as the hand-authored scripts that produced it, so the
    generated/hand-authored split cannot be made by top-level directory.
    """
    _write(
        repo / "plugins" / plugin / "hooks" / "scripts" / f"{name}.py",
        f'"""{name}."""\n\nWORKSHOP_HOOK = {{"event": "Stop", "matcher": "never"}}\n'
        f"\n{body}",
    )


def _plugin(repo: Path, name: str, version: str, payload: str) -> None:
    """Write one plugin at `version`, shipping a single skill with `payload`.

    The skill slug is namespaced by plugin name — `scripts.stamp` refuses two
    plugins shipping the same slug — so fixtures that create several plugins
    in one repo (see `TestMissingBumps.test_every_unbumped_plugin_...`) don't
    collide with each other.
    """
    _manifest(repo, name, version)
    _skill(repo, name, f"{name}-skill", payload)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with `main` holding one released plugin."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    _plugin(repo, "advisor", "0.1.0", "# v1\n")
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
        _plugin(repo, "advisor", "0.1.0", "# v2 — real change\n")
        commit(repo, "change advisor")

        assert find_missing_bumps(repo, "main") == ["advisor"]

    def test_changed_output_with_a_bump_passes(self, repo: Path) -> None:
        _plugin(repo, "advisor", "0.1.1", "# v2 — real change\n")
        commit(repo, "change advisor and bump")

        assert find_missing_bumps(repo, "main") == []

    def test_untouched_plugin_needs_no_bump(self, repo: Path) -> None:
        _write(repo / "README.md", "unrelated edit\n")
        commit(repo, "docs only")

        assert find_missing_bumps(repo, "main") == []

    def test_a_brand_new_plugin_needs_no_bump(self, repo: Path) -> None:
        """There is no prior version to bump from."""
        _plugin(repo, "newcomer", "0.1.0", "# hello\n")
        commit(repo, "add a plugin")

        assert find_missing_bumps(repo, "main") == []

    def test_a_deleted_plugin_is_not_flagged(self, repo: Path) -> None:
        subprocess.run(["rm", "-rf", str(repo / "plugins" / "advisor")], check=True)
        commit(repo, "drop advisor")

        assert find_missing_bumps(repo, "main") == []

    def test_every_unbumped_plugin_is_reported_not_just_the_first(
        self, repo: Path
    ) -> None:
        """Reporting one at a time turns one fix into three round trips."""
        _plugin(repo, "second", "0.1.0", "# a\n")
        _plugin(repo, "third", "0.1.0", "# a\n")
        commit(repo, "add two more")
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--ff-only", "work")
        git(repo, "checkout", "-q", "work")

        _plugin(repo, "advisor", "0.1.0", "# changed\n")
        _plugin(repo, "second", "0.1.0", "# changed\n")
        _plugin(repo, "third", "0.2.0", "# changed\n")
        commit(repo, "change three, bump one")

        assert find_missing_bumps(repo, "main") == ["advisor", "second"]

    def test_a_version_only_change_is_fine(self, repo: Path) -> None:
        """Bumping alone rewrites the manifest — that must not self-flag."""
        _plugin(repo, "advisor", "0.1.1", "# v1\n")
        commit(repo, "bump only")

        assert find_missing_bumps(repo, "main") == []

    def test_engine_only_change_demands_a_bump(self, repo: Path) -> None:
        """`machinery/engine` is hand-authored and shipped — nothing else covers it.

        The stamper exclusion is safe because generated content is a pure
        function of hand-authored content, so the source always appears in the
        diff too. `machinery/engine` has no such upstream inside this repo: it
        IS the source. Excluding it removed the only signal there was, and an
        engine fix could merge green, promote green, and reach zero installed
        vaults — the exact failure the gate exists to prevent (#694).
        """
        _write(
            repo / "plugins" / "advisor" / "machinery" / "engine" / "vault_utils.py",
            "# a real engine fix\n",
        )
        commit(repo, "fix the engine, forget the bump")

        assert find_missing_bumps(repo, "main") == ["advisor"]

    def test_engine_change_with_a_bump_passes(self, repo: Path) -> None:
        _write(
            repo / "plugins" / "advisor" / "machinery" / "engine" / "vault_utils.py",
            "# a real engine fix\n",
        )
        _manifest(repo, "advisor", "0.1.1")
        commit(repo, "fix the engine and bump")

        assert find_missing_bumps(repo, "main") == []

    def test_machinery_change_does_not_mask_a_real_change(self, repo: Path) -> None:
        """A skill edit alongside an engine edit is still one report, not two.

        Both halves now demand a bump on their own (see
        `test_engine_only_change_demands_a_bump`), so what this pins is that
        the plugin is named once — the exclusion's removal must not turn a
        two-file diff into a duplicated line.
        """
        _write(
            repo / "plugins" / "advisor" / "machinery" / "engine" / "vault_utils.py",
            "# synced engine module\n",
        )
        _plugin(repo, "advisor", "0.1.0", "# v2 — real change\n")
        commit(repo, "sync machinery and change a skill")

        assert find_missing_bumps(repo, "main") == ["advisor"]

    def test_change_confined_to_a_stamper_owned_path_does_not_demand_a_bump(
        self, repo: Path
    ) -> None:
        """Generated content is a pure function of hand-authored content.

        `plugins/advisor/README.md` is entirely `stamp.py` output (see
        `render_plugin_readme`). Hand-editing it in place — standing in for a
        `stamp.py` rendering tweak that reflows every plugin's README on the
        next `make stamp` — must not read as a real, owner-facing change: the
        underlying skill/agent/hook inventory that produced it is unchanged,
        so nothing an owner can invoke actually moved. Requiring a bump here
        would mean a pure formatting change demands nine simultaneous bumps
        for zero semantic content.
        """
        _write(
            repo / "plugins" / "advisor" / "README.md",
            "# advisor\n\nregenerated by a hypothetical stamp.py tweak\n",
        )
        commit(repo, "hand-edit a stamper-owned file to simulate stamp.py drift")

        assert find_missing_bumps(repo, "main") == []

    def test_change_to_a_hand_written_manifest_field_demands_a_bump(
        self, repo: Path
    ) -> None:
        """`.claude-plugin/plugin.json` is explicitly never stamper-owned.

        `scripts.stamp.owned_paths()` deliberately excludes it — a stamper
        that both read and wrote it could rewrite the only declaration of a
        plugin's version from a bad render — so editing it (here, its
        description) is hand-written work like any other and must not be
        swallowed by the exclusion set.
        """
        manifest_path = repo / "plugins" / "advisor" / ".claude-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["description"] = "now with an actual description"
        _write(manifest_path, json.dumps(manifest))
        commit(repo, "edit hand-written plugin.json description, no bump")

        assert find_missing_bumps(repo, "main") == ["advisor"]


@pytest.fixture
def repo_with_hooks(tmp_path: Path) -> Path:
    """A released plugin shipping a hook script *and* its generated hooks.json.

    This puts a stamper-owned file (`hooks/hooks.json`) and hand-authored
    payload (`hooks/scripts/guard.py`) under one directory. A fix that split
    generated from hand-authored by top-level directory would pass every other
    test here and fail this one.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    _manifest(repo, "advisor", "0.1.0")
    _skill(repo, "advisor", "advisor-skill", "# v1\n")
    _hook(repo, "advisor", "guard", "pass\n")
    _write(repo / "plugins" / "advisor" / "hooks" / "hooks.json", '{"hooks": {}}\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release")
    git(repo, "checkout", "-q", "-b", "work")
    return repo


class TestGeneratedOutputStillExcluded:
    """Narrowing the exclusion must not swallow the reason it existed.

    Generated content is a pure function of hand-authored content, so a real
    change already trips the gate through its source; demanding a bump for the
    re-rendered bytes too would make a cosmetic `stamp.py` tweak require nine
    simultaneous bumps for zero semantic change.
    """

    def test_generated_output_beside_hand_authored_payload_needs_no_bump(
        self, repo_with_hooks: Path
    ) -> None:
        """`hooks/hooks.json` is generated; `hooks/scripts/` beside it is not."""
        _write(
            repo_with_hooks / "plugins" / "advisor" / "hooks" / "hooks.json",
            '{"hooks": {"Stop": []}}\n',
        )
        commit(repo_with_hooks, "re-render hooks.json only")

        assert find_missing_bumps(repo_with_hooks, "main") == []

    def test_the_hand_authored_script_in_that_same_directory_does_demand_one(
        self, repo_with_hooks: Path
    ) -> None:
        """The discriminating half: same directory, opposite answer.

        Without this, `test_generated_output_beside_hand_authored_payload_...`
        would still pass if the fix excluded all of `hooks/`.
        """
        _hook(repo_with_hooks, "advisor", "guard", "pass  # now with a real fix\n")
        commit(repo_with_hooks, "change the hook script only")

        assert find_missing_bumps(repo_with_hooks, "main") == ["advisor"]

    def test_a_plugin_changed_in_both_categories_is_reported_once(
        self, repo_with_hooks: Path
    ) -> None:
        """One plugin, one line — a diff spanning both must not double-count."""
        _write(
            repo_with_hooks / "plugins" / "advisor" / "hooks" / "hooks.json",
            '{"hooks": {"Stop": []}}\n',
        )
        _hook(repo_with_hooks, "advisor", "guard", "pass  # real fix\n")
        _write(
            repo_with_hooks
            / "plugins"
            / "advisor"
            / "machinery"
            / "engine"
            / "vault_utils.py",
            "# engine fix too\n",
        )
        commit(repo_with_hooks, "change generated and hand-authored together")

        assert find_missing_bumps(repo_with_hooks, "main") == ["advisor"]


class TestExclusionsDeriveFromTheStamperMap:
    """The exclusion set must BE the stamper's path map, not a copy of it.

    A second literal list — `:(exclude)plugins/<n>/machinery` was one — is
    exactly how this drifts back: it excludes paths the stamper never claimed,
    silently and with the gate still reporting success.
    """

    def test_the_gate_applies_no_exclusion_the_stamper_does_not_own(
        self, repo_with_hooks: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Captured from the real `git diff` invocation, not from reading source.

        Re-adding any hardcoded `:(exclude)` pathspec turns this red, because
        the added path is not one `owned_paths()` returns.
        """
        captured: list[str] = []
        real_run_git = check_version_bumps.run_git

        def spy(repo: Path, *args: str) -> subprocess.CompletedProcess:
            if args and args[0] == "diff":
                captured.extend(args)
            return real_run_git(repo, *args)

        monkeypatch.setattr(check_version_bumps, "run_git", spy)
        find_missing_bumps(repo_with_hooks, "main")

        applied = {
            arg.removeprefix(":(exclude)")
            for arg in captured
            if arg.startswith(":(exclude)")
        }
        owned = {
            path.relative_to(repo_with_hooks).as_posix()
            for path in owned_paths(repo_with_hooks)
        }

        assert applied, "the gate applied no exclusions at all — spy never fired"
        assert applied <= owned


class TestStamperExclusionIsWired:
    def test_the_exclusion_set_is_non_empty_against_the_real_repo(self) -> None:
        """Prove the mechanism is actually wired, not silently matching nothing.

        An exclusion list that resolves to an empty set would make the gate
        demand a version bump on every routine `make stamp` run across every
        plugin in this repo — the failure mode the exclusion exists to avoid.
        Resolving `owned_paths()` against this repo's real, valid plugin tree
        (not a synthetic fixture) proves it returns real paths.
        """
        owned = owned_paths(REPO_ROOT)

        assert len(owned) > 0
        assert all(REPO_ROOT in path.parents for path in owned)


class TestCrossPluginMove:
    """A skill/agent/hook moving between plugins is newly reachable post-reorg.

    The flat tree makes it possible to move a component from one plugin's
    `skills/`/`agents/`/`hooks/scripts/` directory into another's. An owner
    who only has the losing plugin installed experiences that exactly like a
    deletion — the thing they could invoke is gone.
    """

    def test_moving_a_skill_to_another_plugin_demands_a_major_bump_for_the_loser(
        self, tmp_path: Path
    ) -> None:
        """The per-plugin component inventory already catches this as a removal.

        `_components_at` scopes its listing to one plugin's own subtree, at
        two points in time. A move makes the component vanish from the losing
        plugin's own `before` set with nothing in `after` to match — the same
        `before - after` check that flags any other removal — regardless of
        where the component reappears. No special-case "moved" tracking is
        needed; this pins that the reorg's dist/ -> plugins/ repoint kept it
        true.
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        _manifest(repo, "alpha", "1.0.0")
        _skill(repo, "alpha", "shared", "# lives in alpha\n")
        _manifest(repo, "beta", "1.0.0")
        _skill(repo, "beta", "own", "# beta's own skill\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "release")
        git(repo, "checkout", "-q", "-b", "work")

        subprocess.run(
            ["rm", "-rf", str(repo / "plugins" / "alpha" / "skills" / "shared")],
            check=True,
        )
        _skill(repo, "beta", "shared", "# now lives in beta\n")
        _manifest(repo, "alpha", "1.0.1")  # patch — too small for a removal
        commit(repo, "move shared from alpha to beta, patch-bump the loser")

        violations = find_level_violations(repo, "main")

        assert ("alpha", "major", "patch") in violations

    def test_moving_a_skill_with_a_major_bump_on_the_loser_passes(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        _manifest(repo, "alpha", "1.0.0")
        _skill(repo, "alpha", "shared", "# lives in alpha\n")
        _manifest(repo, "beta", "1.0.0")
        _skill(repo, "beta", "own", "# beta's own skill\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "release")
        git(repo, "checkout", "-q", "-b", "work")

        subprocess.run(
            ["rm", "-rf", str(repo / "plugins" / "alpha" / "skills" / "shared")],
            check=True,
        )
        _skill(repo, "beta", "shared", "# now lives in beta\n")
        _manifest(repo, "alpha", "2.0.0")
        commit(repo, "move shared from alpha to beta, major-bump the loser")

        assert find_level_violations(repo, "main") == []


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
    _plugin(repo, "advisor", "1.0.0", "# v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release 1.0.0 on main")

    git(repo, "checkout", "-q", "-b", "dev")
    _plugin(repo, "advisor", "1.1.0", "# v2 — the sibling slice\n")
    commit(repo, "bump advisor on dev")

    # CI resolves `origin/<base>`, not a local branch.
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "update-ref", "refs/remotes/origin/dev", "dev")

    git(repo, "checkout", "-q", "-b", "work")
    _plugin(repo, "advisor", "1.1.0", "# v3 — this slice, no-op bump\n")
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
        _manifest(repo, "advisor", version)
        for skill in skills:
            _skill(repo, "advisor", skill, f"# {skill}\n")

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
            ["rm", "-rf", str(repo / "plugins" / "advisor" / "skills" / skill)],
            check=True,
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
        _skill(released, "advisor", "alpha", "# reworded\n")
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
        _write(
            released / "plugins" / "advisor" / "hooks" / "scripts" / "_shared.py",
            "x = 1\n",
        )
        self._release(released, "1.2.1", ["alpha", "beta"])
        commit(released, "add a hook library module")

        assert find_level_violations(released, "main") == []


def afk_version_base() -> str:
    """The `VERSION_BASE` afk's gate is configured to use.

    Read from `.afk/config.toml` rather than restated, so retargeting the
    override turns the tests that call this red instead of leaving them green
    against a fiction.
    """
    import tomllib

    config = tomllib.loads((REPO_ROOT / ".afk" / "config.toml").read_text())
    match = re.search(r"VERSION_BASE=(\S+)", config["test_command"])
    if match is None:
        raise AssertionError(".afk/config.toml sets no VERSION_BASE for the gate")
    return match.group(1)


@pytest.fixture
def second_slice_on_advanced_staging(tmp_path: Path) -> Path:
    """Two slices in one drain, both claiming the same version (#603).

    `main` and `dev` both ship advisor 1.0.0. Slice A bumps to 1.1.0 and lands
    on the integration branch, which afk's merge queue then trial-merges slice
    B onto. Slice B changes advisor again but still declares 1.1.0 — a no-op
    against the branch it is landing on, yet a real bump against `dev`.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    _plugin(repo, "advisor", "1.0.0", "# v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release 1.0.0")

    git(repo, "checkout", "-q", "-b", "dev")
    git(repo, "checkout", "-q", "-b", "afk/staging")

    # Slice A lands on the integration branch.
    _plugin(repo, "advisor", "1.1.0", "# v2 — slice A\n")
    commit(repo, "slice A: bump advisor to 1.1.0")

    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "update-ref", "refs/remotes/origin/dev", "dev")

    # Slice B is trial-merged onto the now-advanced integration branch.
    git(repo, "checkout", "-q", "-b", "trial/slice-b")
    _plugin(repo, "advisor", "1.1.0", "# v3 — slice B, same version\n")
    commit(repo, "slice B: change advisor, still declaring 1.1.0")
    return repo


class TestSecondSliceInADrain:
    """A drain's second slice must be graded against what already landed (#603).

    afk re-runs `test_command` on a trial-merged workspace, so the tree it
    grades accumulates as slices land. Grading against the trunk instead lets
    two slices in one batch ship different component sets under one version —
    #568's collision, reproduced inside a single drain.
    """

    def test_the_configured_base_catches_the_second_slices_no_op_bump(
        self, second_slice_on_advanced_staging: Path
    ) -> None:
        base = afk_version_base()

        assert find_missing_bumps(second_slice_on_advanced_staging, base) == ["advisor"]

    def test_the_same_tree_slips_past_a_trunk_based_gate(
        self, second_slice_on_advanced_staging: Path
    ) -> None:
        """The escape being closed: against `dev`, 1.0.0 -> 1.1.0 looks bumped.

        This is why `origin/dev` is not sufficient — it is the mutation the
        single-slice criterion could not distinguish from a correct fix.
        """
        assert find_missing_bumps(second_slice_on_advanced_staging, "origin/dev") == []
