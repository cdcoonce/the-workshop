"""Behavioural coverage for the `mr_preflight.py sweep` command.

Exercised against real fixture repositories in temp dirs rather than mocks.
The sweep exists because a rename lands in one file while a runbook or a SQL
script elsewhere keeps the old name, and the only way to prove it catches that
is to build the repo where it happens and run the command the way `create-mr`
does. Every test drives the CLI and asserts on its exit code and output.
"""

from __future__ import annotations

import os
import resource
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


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("LoadCurves", "FetchPrices"),  # CamelCase alone: no `_`, no `.`
        ("ab_cde", "ab_xyz"),  # exactly the minimum length
    ],
)
def test_distinctive_tokens_at_each_rule_edge_are_chased(
    repo: Path, old: str, new: str
) -> None:
    write(repo, "a.py", f"value = {old}()\n")
    write(repo, "docs/notes.md", f"Call {old} first.\n")
    base = commit(repo, "initial")
    write(repo, "a.py", f"value = {new}()\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert f"docs/notes.md:1: {old} (renamed to {new} in a.py)" in result.stdout


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


def test_a_changed_sql_comment_in_the_same_hunk_does_not_hide_the_rename(
    repo: Path,
) -> None:
    """A removed `-- comment` reaches the diff as `--- comment`, which reads
    like a file header; the rename on the line above it must still be found."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n-- old header comment\n")
    write(repo, "sql/audit.sql", "USE SCHEMA LEGACY_SCHEMA;\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n-- new header comment\n")
    commit(repo, "rename and reword")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stdout


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


def test_a_path_with_a_colon_is_reported_whole(repo: Path) -> None:
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "sql/a:b.sql", "USE SCHEMA LEGACY_SCHEMA;\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    assert "sql/a:b.sql:1: LEGACY_SCHEMA" in result.stdout


def test_a_path_with_a_newline_is_reported_whole(repo: Path) -> None:
    """Under `-z` git prints a newline in a path raw, so the name field can
    hold one; splitting rows on `\\n` first would tear it off its NULs. The
    path is reported quoted, as git quotes it."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "docs/new\nline.md", "Build LEGACY_SCHEMA first.\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    assert '"docs/new\\nline.md":1: LEGACY_SCHEMA' in result.stdout
    # One file, one hit: a parser that ends the row at the path's newline
    # reports the whole path and then a phantom `line.md` beside it.
    assert "mr-preflight: 1 surviving reference(s)" in result.stdout
    assert "Traceback" not in result.stderr


def test_a_binary_file_holding_the_old_name_is_not_a_crash(repo: Path) -> None:
    """Binary content has no line to fix; it must neither crash the sweep
    nor stand in for a hit, while text hits are still reported."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "docs/runbook.md", "Build LEGACY_SCHEMA first.\n")
    (repo / "data").mkdir()
    (repo / "data" / "export.bin").write_bytes(b"\x00\x01LEGACY_SCHEMA\x00")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    assert "docs/runbook.md:1: LEGACY_SCHEMA" in result.stdout
    assert "export.bin" not in result.stdout
    assert "Traceback" not in result.stderr


def test_a_carriage_return_inside_a_hit_line_is_not_a_crash(repo: Path) -> None:
    """A committed log line `progress: 10%\\rLEGACY_SCHEMA loaded` is one line
    to git; reading it as two must not strand half a row without its NULs."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    (repo / "run.log").write_bytes(b"progress: 10%\rLEGACY_SCHEMA loaded\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    assert "run.log:1: LEGACY_SCHEMA" in result.stdout
    assert "Traceback" not in result.stderr


def test_a_carriage_return_before_a_rename_does_not_hide_it(repo: Path) -> None:
    """The diff side of the same trap: a `\\r` earlier on the renamed line
    must not cut the line in two before the old name is compared."""
    (repo / "config.txt").write_bytes(b"stage\rschema: LEGACY_SCHEMA\n")
    write(repo, "sql/audit.sql", "USE SCHEMA LEGACY_SCHEMA;\n")
    base = commit(repo, "initial")
    (repo / "config.txt").write_bytes(b"stage\rschema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stdout


def test_the_whole_repo_is_swept_from_a_subdirectory(repo: Path) -> None:
    """`create-mr` may run from anywhere inside the repo; a leftover at the
    root must not drop out of the search because the cwd is `sub/`."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "sql/audit.sql", "USE SCHEMA LEGACY_SCHEMA;\n")
    write(repo, "sub/notes.md", "nothing here\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo / "sub", base)

    assert result.returncode == HITS, result.stdout
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stdout


def test_an_unresolvable_base_is_a_setup_error(repo: Path) -> None:
    write(repo, "a.py", "x = 1\n")
    commit(repo, "initial")

    result = sweep(repo, "origin/no-such-branch")

    assert result.returncode == SETUP_ERROR
    assert "mr-preflight:" in result.stderr
    # Named as a setup error, not left to the crash guard's traceback.
    assert "Traceback" not in result.stderr


def test_a_crash_is_a_setup_error_never_hits(repo: Path) -> None:
    """Python exits 1 on an uncaught exception, which `create-mr` reads as
    unwaived references to fix or waive. Whatever breaks inside the sweep
    must exit 2 instead, naming the failure."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    # `mr_preflight` binds `sweep` by name at import, so patch it there. The
    # exception is a class no handler names, so only a catch-all can take it.
    crash = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "import mr_preflight\n"
        "class Unforeseen(Exception):\n"
        "    pass\n"
        "def boom(*args, **kwargs):\n"
        "    raise Unforeseen('unexpected git grep row')\n"
        "mr_preflight.sweep = boom\n"
        f"sys.argv = ['mr_preflight.py', 'sweep', '--base', {base!r}]\n"
        "sys.exit(mr_preflight.main())\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", crash], cwd=repo, capture_output=True, text=True
    )

    assert result.returncode == SETUP_ERROR, result.stderr
    assert "mr-preflight: internal error: Unforeseen: unexpected git grep row" in result.stderr


def test_a_crash_after_stdout_was_closed_still_exits_2(repo: Path) -> None:
    """A closed `sys.stdout` raises ValueError on flush, not OSError; the guard
    must not crash on its own cleanup and exit 1 after all."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    crash = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "import mr_preflight\n"
        "class Unforeseen(Exception):\n"
        "    pass\n"
        "def boom(*args, **kwargs):\n"
        "    sys.stdout.close()\n"
        "    raise Unforeseen('stdout closed under the sweep')\n"
        "mr_preflight.sweep = boom\n"
        f"sys.argv = ['mr_preflight.py', 'sweep', '--base', {base!r}]\n"
        "sys.exit(mr_preflight.main())\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", crash], cwd=repo, capture_output=True, text=True
    )

    assert result.returncode == SETUP_ERROR, result.stderr
    assert "mr-preflight: internal error: Unforeseen: stdout closed under the sweep" in result.stderr


def test_a_crash_on_a_closed_stdout_still_exits_2(repo: Path) -> None:
    """`sweep ... | head` closes stdout mid-report. The guard's own flush then
    hits the same broken pipe, and so does the interpreter's at exit, which
    turned exit 2 into 120 with the error line never printed."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "sql/big.sql", "USE SCHEMA LEGACY_SCHEMA;\n" * 5000)
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    # The read end closes before the sweep starts, so the first write fails.
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "sweep", "--base", base],
            cwd=repo,
            stdout=write_end,
            stderr=subprocess.PIPE,
            text=True,
        )
    finally:
        os.close(write_end)

    assert result.returncode == SETUP_ERROR, result.stderr
    assert "mr-preflight: internal error: BrokenPipeError" in result.stderr


# --- waivers from the description's sweep block ---------------------------

SWEEP_BEGIN = "<!-- mr-preflight:sweep:begin -->"
SWEEP_END = "<!-- mr-preflight:sweep:end -->"


def describe(repo: Path, body: str, prose: str = "## What this does\n\nRenames.\n\n") -> Path:
    """Write a description outside the repo, with ``body`` as its sweep block."""
    path = repo.parent / "description.md"
    path.write_text(f"{prose}{SWEEP_BEGIN}\n{body}{SWEEP_END}\n")
    return path


def two_renames(repo: Path) -> str:
    """Rename `LEGACY_SCHEMA` and `load_curves`, leaving references in a
    changelog, a same-named changelog elsewhere, and a SQL script."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "pipeline.py", "load_curves(path)\n")
    write(repo, "CHANGELOG.md", "- LEGACY_SCHEMA created\n- LEGACY_SCHEMA grown\n- load_curves added\n")
    write(repo, "docs/CHANGELOG.md", "- LEGACY_SCHEMA noted\n")
    write(repo, "sql/audit.sql", "USE SCHEMA LEGACY_SCHEMA;\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    write(repo, "pipeline.py", "fetch_prices(path)\n")
    commit(repo, "rename both")
    return base


def test_a_waiver_covers_every_hit_of_its_token_in_its_path_and_nothing_else(
    repo: Path,
) -> None:
    base = two_renames(repo)
    description = describe(repo, "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n")

    result = sweep(repo, base, "--description", str(description))

    lines = result.stdout.splitlines()
    assert result.returncode == HITS, result.stderr
    assert "waived: CHANGELOG.md:1: LEGACY_SCHEMA: historical entry" in lines
    assert "waived: CHANGELOG.md:2: LEGACY_SCHEMA: historical entry" in lines
    blocking = [line for line in lines if "(renamed to" in line]
    assert blocking == [
        "docs/CHANGELOG.md:1: LEGACY_SCHEMA (renamed to LEGACY_SCHEMA_RAW in dbt_project.yml)",
        "sql/audit.sql:1: LEGACY_SCHEMA (renamed to LEGACY_SCHEMA_RAW in dbt_project.yml)",
        "CHANGELOG.md:3: load_curves (renamed to fetch_prices in pipeline.py)",
    ]


def test_a_waiver_survives_edits_above_the_hit_and_clears_the_sweep(repo: Path) -> None:
    """Line numbers are not part of the key: a waiver written against line 1
    still holds once the changelog grows above it."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "CHANGELOG.md", "- LEGACY_SCHEMA created\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    description = describe(repo, "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n")
    assert sweep(repo, base, "--description", str(description)).returncode == CLEAN

    write(repo, "CHANGELOG.md", "## 2026-09-25\n\n- schema renamed\n\n- LEGACY_SCHEMA created\n")
    commit(repo, "grow the changelog above the old entry")
    result = sweep(repo, base, "--description", str(description))

    assert result.returncode == CLEAN, result.stdout
    assert "waived: CHANGELOG.md:5: LEGACY_SCHEMA: historical entry" in result.stdout.splitlines()


def test_a_malformed_waiver_line_is_reported_and_blocks(repo: Path) -> None:
    """Every real hit is waived; the typo alone must still stop the MR, since
    its author believes it waives something."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "CHANGELOG.md", "- LEGACY_SCHEMA created\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    description = describe(
        repo,
        "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n"
        "- waive LEGACY_SCHEMA docs/runbook.md historical too\n",
    )

    result = sweep(repo, base, "--description", str(description))

    assert result.returncode == HITS, result.stdout
    assert (
        "malformed waiver: - waive LEGACY_SCHEMA docs/runbook.md historical too"
        in result.stdout.splitlines()
    )


def test_a_description_with_broken_markers_is_a_setup_error(repo: Path) -> None:
    """An unclosed block could hold waivers the sweep never reads."""
    base = two_renames(repo)
    description = repo.parent / "description.md"
    description.write_text(f"Prose.\n\n{SWEEP_BEGIN}\n- waive LEGACY_SCHEMA CHANGELOG.md: x\n")

    result = sweep(repo, base, "--description", str(description))

    assert result.returncode == SETUP_ERROR, result.stdout
    assert "mr-preflight:sweep:end" in result.stderr
    # Named as a setup error, not left to the crash guard's traceback.
    assert "Traceback" not in result.stderr


def test_a_missing_description_file_is_a_setup_error(repo: Path) -> None:
    base = two_renames(repo)

    result = sweep(repo, base, "--description", str(repo.parent / "nope.md"))

    assert result.returncode == SETUP_ERROR, result.stdout
    assert "nope.md" in result.stderr
    # Named as a setup error, not left to the crash guard's traceback.
    assert "Traceback" not in result.stderr


RECORD = "<!-- mr-preflight:record:begin -->\nrecord body\n<!-- mr-preflight:record:end -->\n"


def test_update_rewrites_only_the_sweep_block(repo: Path) -> None:
    """The acceptance round trip: prose above, between and below the markers
    is byte-identical afterwards, and the record block is not the sweep's."""
    base = two_renames(repo)
    above = "## What this does\n\nRenames two things.  \n\n"
    between = "\n## Testing\n\n- ran it\n\n"
    below = "\nNo trailing newline"
    description = repo.parent / "description.md"
    description.write_text(
        f"{above}{SWEEP_BEGIN}\n"
        "stale text the sweep owns\n"
        "- [ ] `old.sql:9` `GONE_NAME`\n"
        "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n"
        "- waive load_curves CHANGELOG.md no colon\n"
        f"{SWEEP_END}\n{between}{RECORD}{below}"
    )

    result = sweep(repo, base, "--description", str(description), "--update")

    assert result.returncode == HITS, result.stderr
    assert description.read_text() == (
        f"{above}{SWEEP_BEGIN}\n"
        "**mr-preflight sweep**\n"
        "\n"
        "Renamed on this branch:\n"
        "\n"
        "- `LEGACY_SCHEMA` -> `LEGACY_SCHEMA_RAW` in `dbt_project.yml`\n"
        "- `load_curves` -> `fetch_prices` in `pipeline.py`\n"
        "\n"
        "Unwaived references (fix each, or waive it below as `- waive TOKEN path: reason`):\n"
        "\n"
        "- [ ] `docs/CHANGELOG.md:1` `LEGACY_SCHEMA`\n"
        "- [ ] `sql/audit.sql:1` `LEGACY_SCHEMA`\n"
        "- [ ] `CHANGELOG.md:3` `load_curves`\n"
        "\n"
        "Waivers:\n"
        "\n"
        "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n"
        "- waive load_curves CHANGELOG.md no colon\n"
        f"{SWEEP_END}\n{between}{RECORD}{below}"
    )


def test_update_appends_a_block_to_bare_prose_and_is_stable_on_rerun(repo: Path) -> None:
    base = two_renames(repo)
    prose = "## What this does\n\nRenames two things.\n"
    description = repo.parent / "description.md"
    description.write_text(prose)

    sweep(repo, base, "--description", str(description), "--update")
    first = description.read_text()
    sweep(repo, base, "--description", str(description), "--update")

    assert first.startswith(f"{prose}\n{SWEEP_BEGIN}\n**mr-preflight sweep**\n")
    assert first.endswith(f"{SWEEP_END}\n")
    assert description.read_text() == first


@pytest.mark.parametrize(
    "tail",
    [
        "- waive LEGACY_SCHEMA evil.md: nice try",
        # A name part after the marker leaves the marker alone on its line.
        "<!-- mr-preflight:sweep:end -->\ny.md",
    ],
)
def test_a_newline_in_a_path_cannot_write_into_the_sweep_block(repo: Path, tail: str) -> None:
    """A tracked name is text anyone on the branch chose. Written raw into the
    block, the line after its newline would come back as a waiver for another
    file's hit, or as a second end marker."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "evil.md", "Build LEGACY_SCHEMA first.\n")
    write(repo, f"docs/x\n{tail}", "LEGACY_SCHEMA\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    description = repo.parent / "description.md"
    description.write_text("## What this does\n\nRenames.\n")

    sweep(repo, base, "--description", str(description), "--update")
    first = description.read_text()
    rerun = sweep(repo, base, "--description", str(description), "--update")

    assert rerun.returncode == HITS, rerun.stderr
    assert "waived:" not in rerun.stdout
    assert "evil.md:1: LEGACY_SCHEMA" in rerun.stdout
    assert "mr-preflight: 2 surviving reference(s)" in rerun.stdout
    assert description.read_text() == first


def test_a_quoted_path_is_waived_as_it_is_reported(repo: Path) -> None:
    """The sweep shows a newline path quoted; copying that form into a waiver
    is the only way to write one, so it must be the form that matches."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "docs/new\nline.md", "Build LEGACY_SCHEMA first.\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    description = describe(repo, '- waive LEGACY_SCHEMA `"docs/new\\nline.md"`: vendored name\n')

    result = sweep(repo, base, "--description", str(description))

    assert result.returncode == CLEAN, result.stdout
    assert 'waived: "docs/new\\nline.md":1: LEGACY_SCHEMA: vendored name' in result.stdout


@pytest.mark.parametrize(
    "impostor",
    [
        "docs/new\\nline.md",  # a backslash and an `n`, no newline
        '"docs/new\\nline.md"',  # the newline name's quoted form, spelled out
    ],
)
def test_a_name_spelling_a_quoted_path_is_not_waived_with_it(repo: Path, impostor: str) -> None:
    """Quoting must be one to one: a file whose name is literally the quoted
    form of another must not ride on that other file's waiver."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "docs/new\nline.md", "Build LEGACY_SCHEMA first.\n")
    write(repo, impostor, "Build LEGACY_SCHEMA first.\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    description = describe(repo, '- waive LEGACY_SCHEMA `"docs/new\\nline.md"`: vendored name\n')

    result = sweep(repo, base, "--description", str(description))

    assert result.returncode == HITS, result.stdout
    assert result.stdout.count("waived:") == 1
    assert "mr-preflight: 1 surviving reference(s)" in result.stdout


def test_names_differing_only_in_invalid_utf8_are_waived_apart(repo: Path) -> None:
    """Decoded with replacement, `docs/x\\377evil.md` and `docs/x\\376evil.md`
    both read as `docs/x\\ufffdevil.md`, so one waiver cleared both files. The
    filesystem refuses such names, so they go straight into the index."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    git(repo, "add", "dbt_project.yml")
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo, input=b"Build LEGACY_SCHEMA first.\n", capture_output=True, check=True,
    ).stdout.decode().strip()
    for name in (b"docs/x\xffevil.md", b"docs/x\xfeevil.md"):
        subprocess.run(
            ["git", "update-index", "--add", "--index-info"],
            cwd=repo, input=b"100644 " + blob.encode() + b"\t" + name + b"\n", check=True,
        )
    git(repo, "commit", "-q", "-m", "initial")
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    git(repo, "add", "dbt_project.yml")
    git(repo, "commit", "-q", "-m", "rename")
    description = describe(repo, '- waive LEGACY_SCHEMA `"docs/x\\377evil.md"`: vendored name\n')

    result = sweep(repo, base, "--description", str(description))

    assert result.returncode == HITS, result.stdout
    assert 'waived: "docs/x\\377evil.md":1: LEGACY_SCHEMA' in result.stdout
    assert '"docs/x\\376evil.md":1: LEGACY_SCHEMA (renamed' in result.stdout
    assert "mr-preflight: 1 surviving reference(s)" in result.stdout


def test_a_control_character_is_shown_in_the_octal_form_git_prints(repo: Path) -> None:
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "docs/a\x01b.md", "Build LEGACY_SCHEMA first.\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    assert '"docs/a\\001b.md":1: LEGACY_SCHEMA' in result.stdout


def test_update_keeps_crlf_prose_byte_for_byte(repo: Path) -> None:
    """A description saved on Windows reaches GitLab as written; reading it
    with newline translation would rewrite every line of the author's prose."""
    base = two_renames(repo)
    above = b"## What this does\r\n\r\nRenames.\r\n\r\n"
    below = b"\r\n## Testing\r\n\r\nRan it.\r\n"
    description = repo.parent / "description.md"
    description.write_bytes(
        above + SWEEP_BEGIN.encode() + b"\r\nold\r\n" + SWEEP_END.encode() + b"\r\n" + below
    )

    sweep(repo, base, "--description", str(description), "--update")
    after = description.read_bytes()

    assert after.startswith(above + SWEEP_BEGIN.encode() + b"\r\n")
    assert after.endswith(SWEEP_END.encode() + b"\r\n" + below)


def test_update_leaves_a_description_alone_when_nothing_was_renamed(repo: Path) -> None:
    """Most branches rename nothing; their MR goes out exactly as written."""
    write(repo, "a.py", "x = 1\n")
    base = commit(repo, "initial")
    write(repo, "a.py", "x = 2\n")
    commit(repo, "no rename")
    prose = b"## What this does\r\n\r\nBumps x.\r\n"
    description = repo.parent / "description.md"
    description.write_bytes(prose)

    result = sweep(repo, base, "--description", str(description), "--update")

    assert result.returncode == CLEAN, result.stdout
    assert description.read_bytes() == prose


def test_update_still_refreshes_a_stale_block_when_nothing_was_renamed(repo: Path) -> None:
    """A block copied from an earlier run must not keep claiming old hits."""
    write(repo, "a.py", "x = 1\n")
    base = commit(repo, "initial")
    write(repo, "a.py", "x = 2\n")
    commit(repo, "no rename")
    description = describe(repo, "- [ ] `sql/audit.sql:1` `LEGACY_SCHEMA`\n", prose="Prose.\n\n")

    result = sweep(repo, base, "--description", str(description), "--update")

    assert result.returncode == CLEAN, result.stdout
    assert description.read_text() == (
        f"Prose.\n\n{SWEEP_BEGIN}\n**mr-preflight sweep**\n\n"
        f"No renamed identifiers on this branch.\n{SWEEP_END}\n"
    )


def test_an_update_that_fails_mid_write_leaves_the_description_intact(repo: Path) -> None:
    """A full disk while `--update` writes must not cost the author the prose
    it exists to preserve. A file-size limit makes the write fail partway."""
    base = two_renames(repo)
    description = repo.parent / "description.md"
    original = ("## What this does\n\n" + "Prose the author wrote. " * 40 + "\n").encode()
    description.write_bytes(original)
    limit = len(original) + 20  # room to read it, not to write the rendered block

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "sweep", "--base", base,
         "--description", str(description), "--update"],
        cwd=repo,
        capture_output=True,
        text=True,
        preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit)),
    )

    assert description.read_bytes() == original
    assert result.returncode == SETUP_ERROR, result.stderr
    assert "Traceback" not in result.stderr
    assert sorted(path.name for path in repo.parent.iterdir()) == ["description.md", "repo"]


def test_update_keeps_the_description_file_mode(repo: Path) -> None:
    """The replacement is a new file; it must not come back owner-only."""
    base = two_renames(repo)
    description = describe(repo, "")
    description.chmod(0o644)

    sweep(repo, base, "--description", str(description), "--update")

    assert description.stat().st_mode & 0o777 == 0o644


def test_a_failed_update_still_reports_the_hits_before_the_error(repo: Path) -> None:
    """`create-mr` reads stdout and stderr as one stream; the hits that explain
    the refusal must come before the write error, not after it."""
    base = two_renames(repo)
    locked = repo.parent / "locked"
    locked.mkdir()
    description = locked / "description.md"
    description.write_text("Prose.\n")
    locked.chmod(0o555)
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "sweep", "--base", base,
             "--description", str(description), "--update"],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    finally:
        locked.chmod(0o755)

    lines = result.stdout.splitlines()
    hit = lines.index("sql/audit.sql:1: LEGACY_SCHEMA (renamed to LEGACY_SCHEMA_RAW in dbt_project.yml)")
    error = next(i for i, line in enumerate(lines) if line.startswith("mr-preflight: could not update"))
    assert result.returncode == SETUP_ERROR
    assert hit < error


# --- the committed .mr-preflight.toml ignore list --------------------------


def configure(repo: Path, toml: str) -> None:
    """Write the repo's ignore list; the caller commits it."""
    write(repo, ".mr-preflight.toml", toml)


def test_ignore_paths_suppress_hits_in_those_paths_only(repo: Path) -> None:
    """The issue's own example: a changelog and an ADR directory are permanent
    noise, while the same name anywhere else still blocks."""
    configure(repo, 'ignore_paths = ["CHANGELOG.md", "docs/adr/**"]\n')
    write(repo, "docs/adr/0001-schema.md", "We chose LEGACY_SCHEMA.\n")
    write(repo, "docs/adr/archive/0000-origin.md", "LEGACY_SCHEMA was first.\n")
    base = two_renames(repo)

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    reported = [line.split(":", 1)[0] for line in result.stdout.splitlines()]
    assert "CHANGELOG.md" not in reported
    assert not any(path.startswith("docs/adr/") for path in reported)
    assert "docs/CHANGELOG.md:1: LEGACY_SCHEMA" in result.stdout
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stdout
    # Five of the seven hits were suppressed: the count is of those alone.
    assert "suppressed 5 hit(s) in ignored paths" in result.stdout


def test_an_ignored_token_is_never_chased(repo: Path) -> None:
    configure(repo, 'ignore_tokens = ["LEGACY_SCHEMA"]\n')
    base = two_renames(repo)

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stderr
    assert "LEGACY_SCHEMA" not in result.stdout
    assert "CHANGELOG.md:3: load_curves (renamed to fetch_prices in pipeline.py)" in result.stdout
    # A config of tokens alone suppresses no hits and must still say so.
    assert (
        "mr-preflight: .mr-preflight.toml suppressed 0 hit(s) in ignored paths"
        " and skipped 1 renamed token(s)."
    ) in result.stdout.splitlines()


def test_a_branch_whose_only_rename_is_ignored_renamed_nothing(repo: Path) -> None:
    """An ignored token leaves the rename set, not just the hit list, so its
    MR gains no sweep block claiming a rename the repo chose not to track."""
    configure(repo, 'ignore_tokens = ["LEGACY_SCHEMA"]\n')
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "sql/audit.sql", "USE SCHEMA LEGACY_SCHEMA;\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")
    description = repo.parent / "description.md"
    description.write_text("Prose only.\n")

    result = sweep(repo, base, "--description", str(description), "--update")

    assert result.returncode == CLEAN, result.stdout
    assert description.read_text() == "Prose only.\n"


def test_a_clean_run_still_reports_what_the_config_suppressed(repo: Path) -> None:
    """Allowlist creep is invisible exactly when the sweep passes, so the count
    prints on a clean run too: four path hits and one skipped token here."""
    configure(
        repo,
        'ignore_paths = ["CHANGELOG.md", "docs/**", "sql/*.sql"]\n'
        'ignore_tokens = ["load_curves"]\n',
    )
    base = two_renames(repo)

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stdout
    assert (
        "mr-preflight: .mr-preflight.toml suppressed 4 hit(s) in ignored paths"
        " and skipped 1 renamed token(s)."
    ) in result.stdout.splitlines()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b'ignore_paths = ["CHANGELOG.md"\n', id="unclosed-array"),
        pytest.param(b'ignore_paths = ["CHANGELOG.md"]\r', id="bare-carriage-return"),
        pytest.param(b'ignore_paths = ["\xff.md"]\n', id="not-utf8"),
        # A bare string would otherwise iterate into one-character globs.
        pytest.param(b'ignore_paths = "CHANGELOG.md"\n', id="string-not-list"),
        pytest.param(b"ignore_tokens = [1]\n", id="non-string-token"),
        # A misspelt key would otherwise ignore nothing, silently.
        pytest.param(b'ignore_path = ["CHANGELOG.md"]\n', id="unknown-key"),
    ],
)
def test_a_malformed_config_is_a_setup_error_naming_the_file(repo: Path, content: bytes) -> None:
    (repo / ".mr-preflight.toml").write_bytes(content)
    base = two_renames(repo)

    result = sweep(repo, base)

    assert result.returncode == SETUP_ERROR, result.stdout
    assert ".mr-preflight.toml" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_a_config_path_that_is_not_a_regular_file_is_a_setup_error(repo: Path, kind: str) -> None:
    """A committed symlink's blob is its target's path, which is not the file
    anyone meant and must never be parsed as the list."""
    write(repo, "real.toml", 'ignore_paths = ["CHANGELOG.md"]\n')
    if kind == "directory":
        write(repo, ".mr-preflight.toml/ignore.toml", 'ignore_paths = ["CHANGELOG.md"]\n')
    else:
        (repo / ".mr-preflight.toml").symlink_to("real.toml")
    base = two_renames(repo)

    result = sweep(repo, base)

    assert result.returncode == SETUP_ERROR, result.stdout
    assert ".mr-preflight.toml at HEAD: it is not a regular file" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("state", ["untracked", "staged"])
def test_only_the_committed_config_counts(repo: Path, state: str) -> None:
    """The sweep reads the head tree, so an ignore that exists only on the
    author's disk, or only in the index, cannot pass an MR whose reviewers
    never see it."""
    base = two_renames(repo)
    configure(repo, 'ignore_paths = ["**"]\n')
    if state == "staged":
        git(repo, "add", ".mr-preflight.toml")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stdout


def test_the_root_config_applies_from_a_subdirectory(repo: Path) -> None:
    configure(repo, 'ignore_paths = ["**"]\n')
    write(repo, "sub/notes.md", "nothing here\n")
    base = two_renames(repo)

    result = sweep(repo / "sub", base)

    assert result.returncode == CLEAN, result.stdout
    assert "suppressed 5 hit(s)" in result.stdout


def test_a_config_added_with_the_rename_hides_only_its_own_paths(repo: Path) -> None:
    """The branch that renames is the one that adds the ignore. The config's
    own lines naming the old token are not a use of it, so they cannot turn
    the rename into a move and hide the hit in a path nobody ignored."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "CHANGELOG.md", "- LEGACY_SCHEMA created\n")
    write(repo, "sql/audit.sql", "USE SCHEMA LEGACY_SCHEMA;\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    configure(repo, '# CHANGELOG keeps LEGACY_SCHEMA history\nignore_paths = ["CHANGELOG.md"]\n')
    commit(repo, "rename, and ignore the changelog")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    reported = [line.split(":", 1)[0] for line in result.stdout.splitlines()]
    assert "sql/audit.sql" in reported
    assert "CHANGELOG.md" not in reported
    assert "suppressed 1 hit(s) in ignored paths" in result.stdout


def test_dropping_an_ignored_token_is_not_a_rename_of_it(repo: Path) -> None:
    """Editing the list pairs its old and new lines; the token that left the
    list is still in use everywhere and must not start blocking."""
    configure(repo, 'ignore_tokens = ["old_thing_x", "LEGACY_SCHEMA"]\n')
    write(repo, "lib.py", "def old_thing_x():\n    pass\n")
    base = commit(repo, "initial")
    configure(repo, 'ignore_tokens = ["LEGACY_SCHEMA"]\n')
    commit(repo, "stop ignoring old_thing_x")

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stdout
    assert "old_thing_x" not in result.stdout


def test_the_config_is_never_a_hit_for_a_name_it_ignores(repo: Path) -> None:
    """A glob naming the renamed directory is the config doing its job, not a
    stale reference that needs a waiver of its own."""
    configure(repo, 'ignore_paths = ["migrations/LEGACY_SCHEMA/**"]\n')
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "migrations/LEGACY_SCHEMA/001.sql", "CREATE SCHEMA LEGACY_SCHEMA;\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stdout
    assert ".mr-preflight.toml" not in [line.split(":", 1)[0] for line in result.stdout.splitlines()]


@pytest.mark.parametrize("head", ["sha", ":/rename, and ignore the changelog"])
def test_the_config_comes_from_the_head_being_swept(repo: Path, head: str) -> None:
    """`--head` names the tree searched, so its ignore list is the one that
    applies, not the checked-out branch's, however the commit is spelt."""
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "CHANGELOG.md", "- LEGACY_SCHEMA created\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    configure(repo, 'ignore_paths = ["CHANGELOG.md"]\n')
    swept = commit(repo, "rename, and ignore the changelog")
    git(repo, "rm", "-q", ".mr-preflight.toml")
    commit(repo, "drop the ignore list")

    result = sweep(repo, base, "--head", swept if head == "sha" else head)

    assert result.returncode == CLEAN, result.stdout
    assert "suppressed 1 hit(s) in ignored paths" in result.stdout


def test_a_failed_update_still_reports_what_the_config_suppressed(repo: Path) -> None:
    configure(repo, 'ignore_paths = ["CHANGELOG.md"]\n')
    base = two_renames(repo)
    locked = repo.parent / "locked"
    locked.mkdir()
    description = locked / "description.md"
    description.write_text("Prose.\n")
    locked.chmod(0o555)
    try:
        result = sweep(repo, base, "--description", str(description), "--update")
    finally:
        locked.chmod(0o755)

    assert result.returncode == SETUP_ERROR, result.stdout
    assert "suppressed 3 hit(s) in ignored paths" in result.stdout


def sweep_without_tomllib(repo: Path, base: str) -> subprocess.CompletedProcess:
    """Run the sweep as Python 3.10 and older would: `import tomllib` fails."""
    shim = repo.parent / "no-tomllib"
    shim.mkdir(exist_ok=True)
    (shim / "tomllib.py").write_text("raise ModuleNotFoundError(\"No module named 'tomllib'\")\n")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "sweep", "--base", base],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(shim)},
    )


def test_a_repo_without_a_config_needs_no_tomllib(repo: Path) -> None:
    """`create-mr` runs whatever `python3` is on PATH, and an import failure
    there would refuse the MR as a setup error. With no config to parse, an old
    Python sweeps as before."""
    base = two_renames(repo)

    result = sweep_without_tomllib(repo, base)

    assert "Traceback" not in result.stderr
    assert result.returncode == HITS
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stdout


def test_a_config_on_a_python_without_tomllib_is_a_setup_error(repo: Path) -> None:
    configure(repo, 'ignore_paths = ["CHANGELOG.md"]\n')
    base = two_renames(repo)

    result = sweep_without_tomllib(repo, base)

    assert result.returncode == SETUP_ERROR, result.stderr
    assert ".mr-preflight.toml" in result.stderr
    assert "Python 3.11" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("token", ["SCHEMA", "legacy_schema", "LEGACY_SCHEMA_RAW"])
def test_ignore_tokens_match_the_whole_name_exactly(repo: Path, token: str) -> None:
    """A part of the name, another case of it, or its successor ignores nothing."""
    configure(repo, f'ignore_tokens = ["{token}"]\n')
    base = two_renames(repo)

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "sql/audit.sql:1: LEGACY_SCHEMA (renamed to LEGACY_SCHEMA_RAW" in result.stdout
    assert "skipped" not in result.stdout


def test_a_hit_in_an_ignored_path_is_suppressed_even_when_waived(repo: Path) -> None:
    """Ignored paths are dropped before waivers are read, so one hit is
    reported once, as suppressed, never also as waived."""
    configure(repo, 'ignore_paths = ["CHANGELOG.md"]\n')
    base = two_renames(repo)
    description = describe(repo, "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n")

    result = sweep(repo, base, "--description", str(description))

    assert not any(line.startswith("waived: CHANGELOG.md:") for line in result.stdout.splitlines())
    assert "suppressed 3 hit(s) in ignored paths" in result.stdout


def test_a_config_that_changed_nothing_says_nothing(repo: Path) -> None:
    """The count is for creep; a config that hid nothing adds no line to
    every sweep, and neither does a repo with no config."""
    configure(repo, 'ignore_paths = ["vendor/**"]\nignore_tokens = ["never_renamed"]\n')
    base = two_renames(repo)

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "suppressed" not in result.stdout


def test_an_unreadable_config_blob_is_a_setup_error_not_no_ignores(repo: Path) -> None:
    """The tree lists the file but its blob is gone, as in a partial clone that
    never fetched it; that is not the same as having no ignore list."""
    configure(repo, 'ignore_paths = ["**"]\n')
    base = two_renames(repo)
    blob = git(repo, "rev-parse", "HEAD:.mr-preflight.toml")
    (repo / ".git" / "objects" / blob[:2] / blob[2:]).unlink()

    result = sweep(repo, base)

    assert result.returncode == SETUP_ERROR, result.stdout
    assert ".mr-preflight.toml at HEAD:" in result.stderr
    assert "Traceback" not in result.stderr


def test_moving_the_config_away_does_not_hide_a_rename(repo: Path) -> None:
    """git pairs a moved file before anything filters it, so the config's
    lines never reappear as added content that reads as the token moving."""
    configure(repo, 'ignore_paths = ["migrations/LEGACY_SCHEMA/**"]\n')
    write(repo, "code.py", "x = LEGACY_SCHEMA\n")
    write(repo, "other.py", "LEGACY_SCHEMA\n")
    base = commit(repo, "initial")
    git(repo, "mv", ".mr-preflight.toml", ".mr-preflight.toml.bak")
    write(repo, "code.py", "x = NEW_SCHEMA\n")
    commit(repo, "rename, and retire the ignore list")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "other.py:1: LEGACY_SCHEMA (renamed to NEW_SCHEMA in code.py)" in result.stdout


@pytest.mark.parametrize(
    "variable", ["GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_ICASE_PATHSPECS", "GIT_NOGLOB_PATHSPECS"]
)
def test_pathspec_settings_in_the_environment_change_nothing(repo: Path, variable: str) -> None:
    """These re-read every pathspec git is given, so the sweep gives git none:
    the config added with the rename still hides only its own path."""
    write(repo, "code.py", "x = LEGACY_SCHEMA\n")
    write(repo, "other.py", "LEGACY_SCHEMA\n")
    write(repo, "CHANGELOG.md", "- LEGACY_SCHEMA created\n")
    base = commit(repo, "initial")
    write(repo, "code.py", "x = NEW_SCHEMA\n")
    configure(repo, '# keeps LEGACY_SCHEMA history\nignore_paths = ["CHANGELOG.md"]\n')
    commit(repo, "rename, and ignore the changelog")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "sweep", "--base", base],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, variable: "1"},
    )

    assert result.returncode == HITS, result.stderr
    assert "other.py:1: LEGACY_SCHEMA (renamed to NEW_SCHEMA in code.py)" in result.stdout
    assert "suppressed 1 hit(s) in ignored paths" in result.stdout


def test_only_the_root_config_is_left_out_of_the_sweep(repo: Path) -> None:
    """A nested `.mr-preflight.toml` or a file merely named like one is
    ordinary content: its references to the old name are hits."""
    configure(repo, 'ignore_paths = ["CHANGELOG.md"]\n')
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA\n")
    write(repo, "pkg/.mr-preflight.toml", "# LEGACY_SCHEMA\n")
    write(repo, "legacy.mr-preflight.toml", "# LEGACY_SCHEMA\n")
    base = commit(repo, "initial")
    write(repo, "dbt_project.yml", "schema: LEGACY_SCHEMA_RAW\n")
    commit(repo, "rename")

    result = sweep(repo, base)

    assert result.returncode == HITS, result.stdout
    assert "pkg/.mr-preflight.toml:1: LEGACY_SCHEMA" in result.stdout
    assert "legacy.mr-preflight.toml:1: LEGACY_SCHEMA" in result.stdout


def test_an_executable_config_is_still_a_regular_file(repo: Path) -> None:
    configure(repo, 'ignore_paths = ["**"]\n')
    (repo / ".mr-preflight.toml").chmod(0o755)
    base = two_renames(repo)
    assert git(repo, "ls-tree", "HEAD", ".mr-preflight.toml").startswith("100755 ")

    result = sweep(repo, base)

    assert result.returncode == CLEAN, result.stderr
    assert "suppressed 5 hit(s)" in result.stdout


def test_a_config_moved_and_edited_is_still_not_a_rename_source(repo: Path) -> None:
    """Moved with an edit, the config's hunks sit under its new name; they are
    still its own lines, so a token dropped from the list is not renamed."""
    # Long enough that git pairs the move (similarity over 50%) and shows the
    # edited line as a hunk under the new name.
    listing = '# Permanent noise.\nignore_paths = ["CHANGELOG.md", "docs/adr/**", "migrations/**"]\n'
    configure(repo, listing + 'ignore_tokens = ["old_thing_x"]\n')
    write(repo, "lib.py", "def old_thing_x():\n    pass\n")
    base = commit(repo, "initial")
    git(repo, "mv", ".mr-preflight.toml", "mr-preflight.old.toml")
    write(repo, "mr-preflight.old.toml", listing + 'ignore_tokens = ["new_thing_y"]\n')
    commit(repo, "retire the ignore list")
    assert "rename from .mr-preflight.toml" in git(repo, "diff", "-U0", base, "HEAD")

    result = sweep(repo, base)

    assert "old_thing_x" not in result.stdout, result.stdout
    assert result.returncode == CLEAN, result.stdout
