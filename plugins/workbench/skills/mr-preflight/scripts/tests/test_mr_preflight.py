"""Behavioural coverage for the `mr_preflight.py sweep` command.

Exercised against real fixture repositories in temp dirs rather than mocks.
The sweep exists because a rename lands in one file while a runbook or a SQL
script elsewhere keeps the old name, and the only way to prove it catches that
is to build the repo where it happens and run the command the way `create-mr`
does. Every test drives the CLI and asserts on its exit code and output.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "mr_preflight.py"

CLEAN = 0
HITS = 1
SETUP_ERROR = 2


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def write(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def sweep(repo: Path, base: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "sweep", "--base", base, *extra],
        cwd=repo,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    work.mkdir()
    git(work, "init", "-q", "-b", "dev")
    return work


def test_paired_rename_reports_every_leftover_and_exits_one(repo: Path) -> None:
    """The motivating case: config renamed, a SQL script and a runbook were not."""
    write(repo, "dbt_project.yml", "models:\n  schema: LEGACY_SCHEMA\n")
    write(repo, "sql/01_tables.sql", "CREATE SCHEMA IF NOT EXISTS LEGACY_SCHEMA;\nUSE SCHEMA LEGACY_SCHEMA;\n")
    write(repo, "docs/runbook.md", "Run `01_tables.sql` to build LEGACY_SCHEMA.\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "models:\n  schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename the schema")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    assert "sql/01_tables.sql:1: LEGACY_SCHEMA" in result.stdout
    assert "sql/01_tables.sql:2: LEGACY_SCHEMA" in result.stdout
    assert "docs/runbook.md:1: LEGACY_SCHEMA" in result.stdout
    assert "renamed to LEGACY_SCHEMA_RAW in dbt_project.yml" in result.stdout


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("rows", "records"),  # plain word: no `_`, `.` or internal capital
        ("a_b", "a_c"),  # has `_` but shorter than 6
        ("__init__", "__main__"),  # stoplisted
    ],
)
def test_non_distinctive_tokens_are_never_chased(repo: Path, old: str, new: str) -> None:
    """A common word replaced in one line must not flag every other use of it."""
    write(repo, "a.py", f"value = {old}\n")
    write(repo, "b.py", f"other = {old}\n")
    base = commit(repo, "initial")
    write(repo, "a.py", f"value = {new}\n")
    commit(repo, "swap")

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stdout
    assert "b.py" not in result.stdout


def test_a_token_the_diff_adds_elsewhere_moved_rather_than_renamed(repo: Path) -> None:
    """`load_curves` left one call site but the diff adds it on another line.

    The name is still in use, so its surviving references are correct.
    """
    write(repo, "pipeline.py", "result = load_curves(path)\n")
    write(repo, "jobs.py", "def run():\n    pass\n")
    write(repo, "report.py", "from curves import load_curves\n")
    base = commit(repo, "initial")
    write(repo, "pipeline.py", "result = fetch_prices(path)\n")
    write(repo, "jobs.py", "def run():\n    load_curves(path)\n")
    commit(repo, "move the call")

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stdout
    assert "load_curves" not in result.stdout


def test_a_rename_inside_qualified_names_chases_the_bare_schema(repo: Path) -> None:
    """The diff only touches `LEGACY_SCHEMA.prices`; the audit script still says
    `USE SCHEMA LEGACY_SCHEMA` and reads `LEGACY_SCHEMA.trades`."""
    write(repo, "models/prices.sql", "select * from LEGACY_SCHEMA.prices\n")
    write(repo, "sql/audit.sql", "USE SCHEMA LEGACY_SCHEMA;\nselect * from LEGACY_SCHEMA.trades;\n")
    base = commit(repo, "initial")
    write(repo, "models/prices.sql", "select * from LEGACY_SCHEMA_RAW.prices\n")
    commit(repo, "requalify")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stdout
    assert "sql/audit.sql:2: LEGACY_SCHEMA" in result.stdout


def test_the_new_name_is_never_a_hit_for_the_old_one(repo: Path) -> None:
    """`LEGACY_SCHEMA_RAW` contains `LEGACY_SCHEMA`; only whole words count."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "docs/ok.md", "Tables live in LEGACY_SCHEMA_RAW now.\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stdout
    assert "docs/ok.md" not in result.stdout
    assert "dbt_project.yml" not in result.stdout


def test_a_deleted_line_with_no_replacement_is_not_a_rename(repo: Path) -> None:
    """Deleting one call is not renaming the function it calls."""
    write(repo, "pipeline.py", "setup()\ncleanup_legacy_rows()\n")
    write(repo, "tasks.py", "def cleanup_legacy_rows():\n    pass\n")
    base = commit(repo, "initial")
    write(repo, "pipeline.py", "setup()\n")
    commit(repo, "drop the cleanup call")

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stdout


def test_an_uncommitted_fix_does_not_clear_the_hit(repo: Path) -> None:
    """The MR ships commits, not the working tree: a local, uncommitted fix to
    the runbook would not reach review, so the committed reference still counts."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "docs/runbook.md", "Build LEGACY_SCHEMA first.\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    write(repo, "docs/runbook.md", "Build LEGACY_SCHEMA_RAW first.\n")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "docs/runbook.md:1: LEGACY_SCHEMA" in result.stdout


def test_an_unresolvable_base_is_a_setup_error(repo: Path) -> None:
    write(repo, "a.py", "x = 1\n")
    commit(repo, "initial")

    result = sweep(repo, "origin/no-such-branch")

    assert result.returncode == SETUP_ERROR
    assert "mr-preflight:" in result.stderr
