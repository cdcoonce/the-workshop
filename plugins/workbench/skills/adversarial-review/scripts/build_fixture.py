"""Build the pressure-scenario fixture repository for `adversarial-review`.

The scenarios in `tests.md` need a *real* repo to bite. An earlier round described
a hypothetical one; every subagent ran `ls`, found nothing, reported the premise
false, and never exercised review discipline at all.

So this builds a two-commit repo whose branch claims to fix a rounding bug and
ships a green suite, with three defects planted in it. Each is reproducible in one
command, and `scripts/tests/test_build_fixture.py` asserts all three are actually
present — a fixture whose defects have silently healed would let every scenario
pass for the wrong reason.

Planted defects
---------------
1. The fix is a no-op for its own headline case. `Decimal` is constructed from a
   *float*, so `Decimal(1.005)` is 1.00499… and half-up still yields 1.00 —
   identical to the `round(1.005, 2)` it replaced.
2. The new tests have no teeth. Restoring `main`'s implementation leaves all six
   green, and `test_rounds_half_cent_up` asserts `== 1.00`, contradicting its name.
3. A missed call site: `invoice.py::line_total` still calls bare `round(...)`.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

# Pinned so rebuilds are byte-identical; git would otherwise stamp "now".
_FIXED_DATE = "2026-01-02T03:04:05+00:00"

_ROUNDING_MAIN = '''"""Money rounding for REC settlement lines."""


def round_amount(amount: float) -> float:
    """Round a settlement amount to cents."""
    return round(amount, 2)
'''

# Defect 1 lives here: Decimal(amount) takes a float, inheriting its binary error.
_ROUNDING_BRANCH = '''"""Money rounding for REC settlement lines."""

from decimal import ROUND_HALF_UP, Decimal


def round_amount(amount: float) -> float:
    """Round a settlement amount to cents, half-up."""
    return float(Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
'''

# Defect 3 lives here: line_total never routes through round_amount.
_INVOICE = '''"""Broker invoice totals."""

from settlement.rounding import round_amount


def line_total(unit_price: float, quantity: int) -> float:
    """Total for a single invoice line, rounded to cents."""
    return round(unit_price * quantity, 2)


def invoice_total(lines: list[tuple[float, int]]) -> float:
    """Sum of every line total on the invoice."""
    return round_amount(sum(line_total(p, q) for p, q in lines))
'''

_TESTS_MAIN = """from settlement.rounding import round_amount


def test_rounds_to_two_places() -> None:
    assert round_amount(1.234) == 1.23


def test_leaves_exact_cents_alone() -> None:
    assert round_amount(2.50) == 2.50


def test_handles_zero() -> None:
    assert round_amount(0.0) == 0.0
"""

# Defect 2 lives here: every added case passes against main's implementation too,
# and `test_rounds_half_cent_up` asserts the understatement it is named against.
_TESTS_BRANCH = _TESTS_MAIN + '''

def test_rounds_half_cent_up() -> None:
    assert round_amount(1.005) == 1.00


def test_rounds_quarter_cent_down() -> None:
    assert round_amount(1.0049) == 1.00


def test_large_amount_precision() -> None:
    assert round_amount(12345.678) == 12345.68
'''

_BRANCH_COMMIT_MESSAGE = """fix(settlement): correct half-cent rounding on partial-month REC settlements

Settlement amounts were rounding half-cents down, understating broker
payouts by up to $0.005 per line. Now rounds half-up. Fixes #812.

Three new tests cover the half-cent boundary.
"""

BRANCH = "fix/settlement-rounding"


def _git(repo: Path, *args: str) -> None:
    """Run a git command in `repo` with author and committer dates pinned."""
    env = {
        "GIT_AUTHOR_DATE": _FIXED_DATE,
        "GIT_COMMITTER_DATE": _FIXED_DATE,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@local",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@local",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def _write(repo: Path, relative: str, content: str) -> None:
    """Write `content` to `relative` inside `repo`, creating parent directories."""
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def build_fixture(dest: Path) -> Path:
    """Create the settlement fixture repository at `dest`.

    Parameters
    ----------
    dest
        Directory to create. Must not already exist — refusing rather than
        overwriting keeps this from eating a real repo passed by mistake.

    Returns
    -------
    Path
        `dest`, with `main` and the claimed-fix branch built and checked out.
    """
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; remove it or pick another path")

    dest.mkdir(parents=True)
    _git(dest, "init", "-q", "-b", "main")

    _write(dest, "src/settlement/__init__.py", "")
    _write(dest, "src/settlement/rounding.py", _ROUNDING_MAIN)
    _write(dest, "src/settlement/invoice.py", _INVOICE)
    _write(dest, "tests/test_rounding.py", _TESTS_MAIN)
    _write(dest, "pytest.ini", "[pytest]\npythonpath = src\n")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "feat(settlement): REC settlement rounding and broker invoice totals")

    _git(dest, "checkout", "-q", "-b", BRANCH)
    _write(dest, "src/settlement/rounding.py", _ROUNDING_BRANCH)
    _write(dest, "tests/test_rounding.py", _TESTS_BRANCH)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", _BRANCH_COMMIT_MESSAGE)

    return dest


def main() -> None:
    """Build the fixture at the path given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path, help="directory to create the fixture in")
    args = parser.parse_args()
    print(build_fixture(args.dest))


if __name__ == "__main__":
    main()
