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


def test_afk_gate_invokes_make_test() -> None:
    config = (REPO_ROOT / ".afk" / "config.toml").read_text()
    assert "make test" in config, (
        ".afk/config.toml test_command must run `make test` so the gate covers "
        "both the root suite and every skill-script suite"
    )
