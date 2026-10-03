"""Build the working-tree fixture repository for the `commit/C-trig` triggering case.

The case-agent is asked to save the changes in a repository's working tree. Giving
it the-workshop checkout would let it commit to the real repo, so this builds a
throwaway one: a `git init`ed directory holding a single commit, followed by
uncommitted work, with no remote.

Run as `python build_fixture.py <dest>`, into a `<dest>` that does not exist yet.

The commit pins author and committer name, email and date, and every git setting
that could leak in from the machine is shut out: inherited GIT_* variables are dropped
and the global and system config files are replaced by an empty one (that takes hooks,
templates, signing and the default branch name with it), so two
builds give the same commit id and the same `builder_output_fingerprint`, which
hashes the full built working tree plus `git log --all --format=%H%x00%s`.

Uncommitted state left behind
-----------------------------
- `src/greeter/format.py` and `tests/test_format.py` are modified: a whitespace fix.
- `src/greeter/shout.py` and `tests/test_shout.py` are new and untracked: a feature.
- `README.md` is modified: documentation for the feature.

Nothing is staged.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

_PINNED_DATE = "2026-01-02T03:04:05+00:00"
_PINNED_NAME = "Fixture"
_PINNED_EMAIL = "fixture@local"

_README_BASE = """# greeter

A tiny greeting library.

```python
from greeter import greet

greet("Ada")  # "Hello, Ada!"
```
"""

_README_WORKING = _README_BASE + """
## Shouting

`shout(name)` returns the greeting in capitals: `shout("Ada")` is `"HELLO, ADA!"`.
"""

_INIT_BASE = '''"""A tiny greeting library."""

from greeter.format import greet

__all__ = ["greet"]
'''

_INIT_WORKING = '''"""A tiny greeting library."""

from greeter.format import greet
from greeter.shout import shout

__all__ = ["greet", "shout"]
'''

_FORMAT_BASE = '''"""Greeting text."""


def greet(name: str) -> str:
    """Return a greeting for *name*."""
    return f"Hello, {name}!"
'''

_FORMAT_WORKING = '''"""Greeting text."""


def greet(name: str) -> str:
    """Return a greeting for *name*, ignoring whitespace around it."""
    return f"Hello, {name.strip()}!"
'''

_SHOUT = '''"""Loud greetings."""

from greeter.format import greet


def shout(name: str) -> str:
    """Return the greeting for *name* in capitals."""
    return greet(name).upper()
'''

_TEST_FORMAT_BASE = """from greeter import greet


def test_greets_by_name():
    assert greet("Ada") == "Hello, Ada!"
"""

_TEST_FORMAT_WORKING = _TEST_FORMAT_BASE + """

def test_ignores_whitespace_around_the_name():
    assert greet("  Ada ") == "Hello, Ada!"
"""

_TEST_SHOUT = """from greeter import shout


def test_shouts_the_greeting():
    assert shout("Ada") == "HELLO, ADA!"
"""

_PYTEST_INI = "[pytest]\npythonpath = src\n"


def _git_env() -> dict[str, str]:
    """Return a clean environment: no inherited GIT_* variable, no machine git config."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": _PINNED_NAME,
            "GIT_AUTHOR_EMAIL": _PINNED_EMAIL,
            "GIT_AUTHOR_DATE": _PINNED_DATE,
            "GIT_COMMITTER_NAME": _PINNED_NAME,
            "GIT_COMMITTER_EMAIL": _PINNED_EMAIL,
            "GIT_COMMITTER_DATE": _PINNED_DATE,
        }
    )
    return env


def _git(repo: Path, *args: str) -> None:
    """Run a git command in *repo* under the pinned environment."""
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=_git_env(), capture_output=True)


def _write(repo: Path, relative: str, content: str) -> None:
    """Write *content* to *relative* inside *repo*, creating parent directories."""
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def build_fixture(dest: Path) -> Path:
    """Create the fixture repository at *dest*.

    Parameters
    ----------
    dest : Path
        Directory to create. Must not exist: refusing rather than overwriting
        keeps this from eating a real repository passed by mistake.

    Returns
    -------
    Path
        *dest*, a repository on `main` with one commit and uncommitted changes.

    Raises
    ------
    FileExistsError
        If *dest* already exists.
    """
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; remove it or pick another path")

    dest.mkdir(parents=True)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "config", "user.name", _PINNED_NAME)
    _git(dest, "config", "user.email", _PINNED_EMAIL)

    _write(dest, "README.md", _README_BASE)
    _write(dest, "pytest.ini", _PYTEST_INI)
    _write(dest, "src/greeter/__init__.py", _INIT_BASE)
    _write(dest, "src/greeter/format.py", _FORMAT_BASE)
    _write(dest, "tests/test_format.py", _TEST_FORMAT_BASE)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "Add the greeting library")

    _write(dest, "README.md", _README_WORKING)
    _write(dest, "src/greeter/__init__.py", _INIT_WORKING)
    _write(dest, "src/greeter/format.py", _FORMAT_WORKING)
    _write(dest, "src/greeter/shout.py", _SHOUT)
    _write(dest, "tests/test_format.py", _TEST_FORMAT_WORKING)
    _write(dest, "tests/test_shout.py", _TEST_SHOUT)
    return dest


def main() -> None:
    """Build the fixture at the path given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path, help="directory to create the fixture in")
    args = parser.parse_args()
    print(build_fixture(args.dest))


if __name__ == "__main__":
    main()
