"""Guards that the afk gate exercises every skill-script suite.

Skill-script suites (e.g. ``core/skills/daa-code-review/scripts/tests``) live in
isolated subtrees with their own rootdir, a sibling ``scripts`` package, and
bare imports (``from models import ...``). They cannot share the root pytest
collection without a package-name collision, so they run as a separate gate
step. To keep any new suite from silently falling out of the gate, the step
DISCOVERS them automatically (``scripts.discover_skill_test_suites``) rather
than naming each one. These guards fail loudly if that wiring is dropped.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_RUNNER = "scripts.discover_skill_test_suites"


def test_makefile_test_target_runs_discovered_skill_suites() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert re.search(r"^test:", makefile, re.MULTILINE), (
        "Makefile must define a `test` target that runs the full gate"
    )
    assert DISCOVERY_RUNNER in makefile, (
        "the `test` target must run the auto-discovered skill-script suites via "
        f"`{DISCOVERY_RUNNER}`"
    )


def test_gate_lints_the_repos_own_python() -> None:
    """`make test` must lint, and the rule set must stay pinned explicitly.

    Ruff's implicit defaults differ by version and pull in a broad stylistic
    set when no config is present, so the selection lives in pyproject.toml.
    """
    repository_root = Path(__file__).resolve().parents[1]
    makefile = (repository_root / "Makefile").read_text()
    pyproject = (repository_root / "pyproject.toml").read_text()

    assert re.search(r"^lint:", makefile, re.MULTILINE), (
        "Makefile must define a `lint` target"
    )
    assert re.search(r"^test:\n\t\$\(MAKE\) lint", makefile, re.MULTILINE), (
        "the `test` gate must run `lint` first, so CI gates on it"
    )
    assert "[tool.ruff.lint]" in pyproject, (
        "the ruff rule set must be pinned in pyproject.toml, not left to defaults"
    )


def test_makefile_test_target_runs_vault_machinery_suite() -> None:
    """The vault machinery suite must not silently fall out of the gate.

    presets/vault-ops/machinery/tests is not a ``scripts/tests`` subtree, so
    the skill-suite discovery never finds it — it needs its own explicit step,
    and this guard keeps that step wired into ``make test``.
    """
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert re.search(r"^test-machinery:", makefile, re.MULTILINE), (
        "Makefile must define a `test-machinery` target running the vault "
        "machinery suite in its own rootdir"
    )
    assert "$(MAKE) test-machinery" in makefile, (
        "the `test` target must run `test-machinery`, or the vault engine "
        "suite silently falls out of the gate"
    )


def test_makefile_test_target_checks_teeth_spec_anchors() -> None:
    """Committed teeth specs must be resolved on every gate run, not on demand.

    A spec's anchors are exact source strings, so a refactor of the code they
    quote stales them with the suite still green. `--check-anchors` catches
    that in well under a second — but only when something runs it, and before
    this step nothing did (#941 found two stale anchors by hand).
    """
    makefile = (REPO_ROOT / "Makefile").read_text()
    target = re.search(r"^check-teeth-anchors:\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert target, "Makefile must define a `check-teeth-anchors` target"
    assert "scripts.check_teeth_anchors" in target.group(1), (
        "`check-teeth-anchors` must run the discovering gate, "
        "`scripts.check_teeth_anchors`, not a hand-kept list of specs"
    )
    test_recipe = re.search(r"^test:\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert test_recipe and "$(MAKE) check-teeth-anchors" in test_recipe.group(1), (
        "the `test` target must run `check-teeth-anchors`, or a stale teeth "
        "spec merges green"
    )


def _afk_config() -> dict:
    """`.afk/config.toml` parsed. It is afk's control plane, not ordinary config.

    The file is entry 14 of afk's own ``PROTECTED_DENY_SURFACE``, so an executor
    cannot edit it — every change here is hand-written, and these guards are the
    only thing standing between a hand edit and a silently weakened gate.
    """
    import tomllib

    return tomllib.loads((REPO_ROOT / ".afk" / "config.toml").read_text())


AFK_GATE_TARGET_NAME = "afk-test"


def test_afk_gate_invokes_the_afk_test_target() -> None:
    """afk's gate runs `make afk-test`, a plain command with no shell expansion.

    The executor agent also runs `test_command` inside its own headless session
    under a grant derived from the string. A `$` or backtick there is what the
    harness flags for interactive approval, which nobody is present to give, so
    the target branch is resolved inside the Makefile instead (#1512 upstream:
    afk exports AFK_GATE_TARGET to every gate run).
    """
    command = _afk_config()["test_command"]
    assert command == f"make {AFK_GATE_TARGET_NAME}", (
        f"test_command must be exactly `make {AFK_GATE_TARGET_NAME}`; got {command!r}"
    )
    assert "$" not in command and "`" not in command


def test_afk_test_target_runs_the_full_make_test_gate() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    recipe = re.search(
        rf"^{AFK_GATE_TARGET_NAME}:\n((?:\t.*\n)+)", makefile, re.MULTILINE
    )
    assert recipe, f"Makefile must define an `{AFK_GATE_TARGET_NAME}` target"
    assert "$(MAKE) test VERSION_BASE=" in recipe.group(1), (
        f"`{AFK_GATE_TARGET_NAME}` must run the whole `make test` gate with a "
        "VERSION_BASE override, so the gate covers the root suite and every "
        "skill-script suite"
    )


def _dry_run_version_base(gate_target: str | None) -> tuple[int, str]:
    """`make -n afk-test` under a clean env; return (rc, the --base it resolves).

    MAKEFLAGS/MAKELEVEL/VERSION_BASE are stripped so an outer `make test` (this
    suite runs inside one) cannot leak its own override into the dry run.
    """
    import os
    import subprocess

    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "VERSION_BASE", "AFK_GATE_TARGET"}
    }
    if gate_target is not None:
        env["AFK_GATE_TARGET"] = gate_target
    proc = subprocess.run(
        ["make", "-n", AFK_GATE_TARGET_NAME],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    match = re.search(r"check_version_bumps --base (\S+)", proc.stdout)
    return proc.returncode, match.group(1) if match else ""


def test_afk_gate_grades_against_the_exported_gate_target() -> None:
    """A slice aimed at an epic branch is version-checked against that branch.

    Grading an `afk/epic-N` slice against the staging branch lets two children
    of one epic, drained together, claim the same version (#1512 upstream).
    """
    rc, base = _dry_run_version_base("afk/epic-7")
    assert rc == 0
    assert base == "afk/epic-7"


def test_afk_gate_falls_back_to_the_integration_target() -> None:
    """With no AFK_GATE_TARGET (an older driver, the agent's own run, a hand
    run) the gate grades against the configured integration branch, as before.

    This is also the drift guard: retargeting `integration_target` without
    moving the Makefile fallback fails here.
    """
    rc, base = _dry_run_version_base(None)
    assert rc == 0
    assert base == _afk_config()["integration_target"]


def test_afk_gate_refuses_a_target_that_is_not_a_plain_afk_ref() -> None:
    """The target comes from issue-body text, and `verify-versions` splices
    VERSION_BASE into its recipe unquoted, so anything but `afk/<segment>` is
    refused before it reaches a shell line."""
    for hostile in ("afk/x;touch pwned", "afk/x y", "main", "afk/a/b", "afk/$(id)"):
        rc, base = _dry_run_version_base(hostile)
        assert rc != 0, f"{hostile!r} was accepted"
        assert base == "", f"{hostile!r} reached verify-versions as {base!r}"
    assert not (REPO_ROOT / "pwned").exists()


def test_scoped_checks_would_discard_the_version_base_override() -> None:
    """A `scoped_checks` table silently throws the override away.

    afk computes `select_scoped_command(paths, scoped_checks, test_command)` on
    both the build path and the merge-queue re-validation path, and passes the
    RESULT to the gate. When every changed path matches a rule, that result is
    assembled purely from the matched rules — `test_command`, and with it the
    `VERSION_BASE` override above, is discarded entirely.

    This repo defines no `scoped_checks`, so the override survives. This guard
    fails the moment one is added, which is the moment the override would stop
    taking effect without any other signal.
    """
    config = _afk_config()

    assert "scoped_checks" not in config, (
        "adding scoped_checks discards test_command — and with it the "
        "VERSION_BASE override — on every path where all changed files match a "
        "rule. Carry `VERSION_BASE=<integration_target>` into each scoped "
        "command, or keep verify-versions out of the scoped set, then update "
        "this guard to assert that instead."
    )
