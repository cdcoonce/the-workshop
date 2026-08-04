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


def test_afk_gate_invokes_make_test() -> None:
    config = (REPO_ROOT / ".afk" / "config.toml").read_text()
    assert "make test" in config, (
        ".afk/config.toml test_command must run `make test` so the gate covers "
        "both the root suite and every skill-script suite"
    )


def _afk_config() -> dict:
    """`.afk/config.toml` parsed. It is afk's control plane, not ordinary config.

    The file is entry 14 of afk's own ``PROTECTED_DENY_SURFACE``, so an executor
    cannot edit it — every change here is hand-written, and these guards are the
    only thing standing between a hand edit and a silently weakened gate.
    """
    import tomllib

    return tomllib.loads((REPO_ROOT / ".afk" / "config.toml").read_text())


def test_afk_gate_compares_versions_against_the_integration_branch() -> None:
    """afk's own gate must use the base the slice will actually land against.

    `Makefile:81` defaults `VERSION_BASE` to `origin/main`, deliberately (#568).
    afk runs `test_command` verbatim as a shell string, so without an override
    the executor grades a slice against `main` while landing it on the
    integration branch. Between two promotions the trunk runs several versions
    ahead, and in that window the executor cannot see an unbumped preset at all
    — #583 shipped three of them and only CI caught it.
    """
    config = _afk_config()
    target = config["integration_target"]

    assert f"VERSION_BASE={target}" in config["test_command"], (
        f"test_command must pass VERSION_BASE={target} so afk's gate compares "
        f"against the branch slices land on; got {config['test_command']!r}. "
        "origin/main cannot see a trunk that has moved ahead, and origin/dev "
        "cannot see slices already queued on the integration branch."
    )


def test_version_base_override_names_the_configured_integration_target() -> None:
    """The two keys must not drift apart in the same file.

    Retargeting `integration_target` without moving the override would leave
    the gate silently grading against a branch nothing lands on.
    """
    config = _afk_config()

    match = re.search(r"VERSION_BASE=(\S+)", config["test_command"])
    assert match, "test_command carries no VERSION_BASE override"
    assert match.group(1) == config["integration_target"], (
        f"VERSION_BASE={match.group(1)!r} does not match "
        f"integration_target={config['integration_target']!r}"
    )


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
