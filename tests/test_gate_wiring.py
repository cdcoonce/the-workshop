"""Guards that the afk gate exercises the daa-code-review analyzer suite (#141).

The analyzer tests live in an isolated subtree
(``core/skills/daa-code-review/scripts/tests``) with their own rootdir, a
sibling ``scripts`` package, and bare imports (``from models import ...``).
They cannot share the root pytest collection without a package-name collision,
so they run as a second gate step in their native rootdir. These guards fail
loudly if that wiring is ever dropped, so the analyzer suite can't silently
fall out of the gate again.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYZER_SUITE = "core/skills/daa-code-review/scripts"


def test_makefile_test_target_runs_analyzer_suite() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert re.search(r"^test:", makefile, re.MULTILINE), (
        "Makefile must define a `test` target that runs the full gate"
    )
    assert ANALYZER_SUITE in makefile, (
        "the `test` target must run the daa-code-review analyzer suite in its "
        "own rootdir"
    )


def test_afk_gate_invokes_make_test() -> None:
    config = (REPO_ROOT / ".afk" / "config.toml").read_text()
    assert "make test" in config, (
        ".afk/config.toml test_command must run `make test` so the gate covers "
        "both the root suite and the analyzer suite"
    )
