"""Ownership and trigger-shape contract for the warehouse-SQL skills.

Two capabilities that had no home under a narrower plugin:

* proving warehouse SQL by executing it, rather than asserting on its text;
* checking a live schema before deploying view or DDL files at it.

Both are universal (any Snowflake/BigQuery/Redshift repo), so they belong in
`workbench` rather than a narrower plugin. Plugin membership follows from
directory presence — a plugin ships exactly the skills in its own `skills/`
directory — these tests pin the part that does not: that each skill states when
to fire in a form the router can act on.

A skill nobody routes to does not run (see `test_skill_cross_routing`). The same is
true of one whose description does not say when it applies: it becomes a skill the
user has to remember, which is the failure these were extracted to prevent.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("warehouse-sql-test-harness", "sql-deploy-precheck")


def _skill_text(slug: str) -> str:
    return (REPO_ROOT / "plugins" / "workbench" / "skills" / slug / "SKILL.md").read_text()


def _description(slug: str) -> str:
    """The frontmatter description — the only thing the router matches on."""
    text = _skill_text(slug)
    assert text.startswith("---"), f"{slug}: no frontmatter"
    frontmatter = text.split("---", 2)[1]
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"{slug}: frontmatter has no description")


@pytest.mark.parametrize("slug", SKILLS)
def test_skill_is_owned_by_core(slug: str) -> None:
    """Universal capability, so workbench is the canonical owner; plugin
    membership follows from directory presence, not a manifest edit."""
    assert (REPO_ROOT / "plugins" / "workbench" / "skills" / slug / "SKILL.md").is_file()


@pytest.mark.parametrize("slug", SKILLS)
def test_description_names_the_condition_that_fires_it(slug: str) -> None:
    """The router acts on the description alone. A summary of what the skill *is*
    leaves the user to remember it; a statement of when it applies does not."""
    description = _description(slug).lower()
    assert "use when" in description or "trigger" in description, (
        f"{slug}: description describes the skill but never says when it fires"
    )


@pytest.mark.parametrize("slug", SKILLS)
def test_description_names_a_warehouse(slug: str) -> None:
    """Scopes the trigger. Without a named engine these fire on ordinary
    application SQL — SQLite, an ORM migration — where neither applies."""
    description = _description(slug).lower()
    assert any(
        engine in description
        for engine in ("snowflake", "bigquery", "redshift", "warehouse")
    ), f"{slug}: description does not scope itself to a warehouse"


def test_the_harness_skill_names_the_execution_engine() -> None:
    """The whole point is executing the committed SQL, not asserting on its text.
    A reader who does not learn that from the skill will write string assertions."""
    text = _skill_text("warehouse-sql-test-harness").lower()
    assert "duckdb" in text
    assert "sqlglot" in text


def test_the_harness_skill_records_the_dialect_gaps() -> None:
    """Three translation gaps cost real time to rediscover; the skill exists partly
    to carry them."""
    text = _skill_text("warehouse-sql-test-harness").lower()
    assert "update set" in text, "qualified UPDATE SET is rejected by DuckDB"
    assert "equal_null" in text
    assert "placeholder" in text or "bind" in text


def test_the_precheck_skill_warns_about_star_view_invalidation() -> None:
    """`ALTER TABLE ADD COLUMN` invalidates every deployed `SELECT *` view over that
    table. The ALTER succeeding tells you nothing about whether the schema still
    works — that is the trap this skill is mostly for."""
    text = _skill_text("sql-deploy-precheck").lower()
    assert "select *" in text
    assert "alter table" in text


def test_the_precheck_skill_requires_a_live_check_not_only_fixtures() -> None:
    """A fixture harness builds its tables from the same file it is testing, so it
    is structurally unable to see deployment drift. Both skills must say so, or
    someone runs the harness and believes they have checked."""
    for slug in SKILLS:
        text = _skill_text(slug).lower()
        assert "drift" in text, f"{slug}: never mentions deployment drift"
