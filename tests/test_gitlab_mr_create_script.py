"""Behavioural coverage for the `gitlab-mr-create` wrapper.

The script owns the title of every merge request the toolkit opens, across
every Clearway GitLab repo, and until now nothing executed it. The boundary
suite next door asserts prose (`test_gitlab_skill_boundaries.py`); the archive
note that specified this skill asked for a build test and what landed checked
that the file existed. So the one guard standing between a hand-typed title and
production had no teeth at all.

That matters because its failure mode is silent rather than loud. A release
commit subject — `chore(release): v0.7.2` — satisfies the conventional-commit
gate, so on a promotion the script did not refuse: it ran, and titled a
production promotion after the release bot's chore commit. Nothing errored.
Every test here that covers the promotion hop therefore uses a HEAD subject
that *passes* the regex, because a test built on a subject the regex already
rejects would pass under both the old behaviour and the new one and prove
nothing.

`git` and `jq` run for real. Only `glab` is stubbed, and it records the exact
bytes it was handed so a test can assert the title itself rather than the fact
that some title was delivered.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CREATE_MR = REPO_ROOT / "plugins/workbench/skills/gitlab-mr-create/scripts/create-mr"

# Exit codes the wrapper uses, following sysexits as the original did.
USAGE = 64
PRECONDITION = 65
NO_INPUT = 66
VERIFY_FAILED = 1

# A glab stub that answers the three calls the wrapper makes and records the
# title and description it was given, byte for byte, so the assertions can be
# about the value rather than the delivery. `passthrough` captures everything
# else so a test can prove the wrapper's own flags never reach glab.
GLAB_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
if [[ ${1-} == "mr" && ${2-} == "create" ]]; then
  shift 2
  : > "$STUB_DIR/passthrough"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --title) printf '%s' "$2" > "$STUB_DIR/title"; shift 2 ;;
      --description) printf '%s' "$2" > "$STUB_DIR/description"; shift 2 ;;
      *) printf '%s\n' "$1" >> "$STUB_DIR/passthrough"; shift ;;
    esac
  done
  touch "$STUB_DIR/created"
  echo "https://gitlab.example.com/group/project/-/merge_requests/7"
  exit 0
fi
if [[ ${1-} == "api" ]]; then
  if [[ "$2" == "projects/:id" ]]; then
    printf '{"default_branch":"%s"}\n' "${STUB_DEFAULT_BRANCH:-dev}"
    exit 0
  fi
  jq -n \
    --rawfile t "$STUB_DIR/title" \
    --rawfile d "$STUB_DIR/description" \
    --arg override "${STUB_READBACK_TITLE-}" \
    '{title: (if $override == "" then $t else $override end), description: $d}'
  exit 0
fi
echo "unexpected glab call: $*" >&2
exit 99
"""


@pytest.fixture
def repo(tmp_path: Path):
    """A real git repo with a stubbed `glab` ahead of it on PATH.

    Returns a callable that commits a subject, then runs the wrapper.
    """
    work = tmp_path / "repo"
    work.mkdir()
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    glab = bin_dir / "glab"
    glab.write_text(GLAB_STUB)
    glab.chmod(0o755)

    subprocess.run(["git", "init", "-q", "-b", "dev"], cwd=work, check=True)

    # The dev hop sweeps from the merge-base with `origin/dev`, so the repo
    # needs a real remote whose `dev` is the base the branch diverged from.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=work, check=True)

    def seed(files: dict[str, str]) -> None:
        """Commit files and publish them as `origin/dev`: the sweep's base."""
        for path, content in files.items():
            target = work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=work, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
             "commit", "-q", "--allow-empty", "-m", "chore: seed"],
            cwd=work,
            check=True,
        )
        subprocess.run(["git", "push", "-q", "origin", "dev"], cwd=work, check=True)

    seed({"seed.txt": "base\n"})

    def run(
        subject: str,
        *args: str,
        description: str = "## What this does\n\nReal newlines.\n",
        default_branch: str = "dev",
        readback_title: str = "",
        description_name: str = "",
        close_stderr: bool = False,
        broken_stderr: bool = False,
    ) -> subprocess.CompletedProcess:
        (work / "file.txt").write_text(subject)
        subprocess.run(["git", "add", "-A"], cwd=work, check=True)
        subprocess.run(
            [
                "git",
                "-c", "user.name=t",
                "-c", "user.email=t@example.com",
                "commit", "-q", "--allow-empty", "-m", subject,
            ],
            cwd=work,
            check=True,
        )
        # A bare relative name is how a caller spells a file whose name
        # starts with `-`; the default is an absolute path.
        description_file = work / (description_name or "description.md")
        description_file.write_text(description)
        description_arg = description_name or str(description_file)

        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_DIR": str(stub_dir),
            "STUB_DEFAULT_BRANCH": default_branch,
            "STUB_READBACK_TITLE": readback_title,
        }
        command = ["bash", str(CREATE_MR), description_arg, *args]
        if close_stderr:
            # A caller that closed fd 2, as `2>&-` does: every write to it fails.
            command = ["bash", "-c", 'exec 2>&-; exec "$@"', "bash", *command]
        if broken_stderr:
            # A pipe whose reader has gone: a write raises SIGPIPE, which
            # `|| true` cannot catch.
            read_end, write_end = os.pipe()
            os.close(read_end)
            try:
                return subprocess.run(
                    command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=write_end, text=True
                )
            finally:
                os.close(write_end)
        return subprocess.run(
            command,
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )

    run.stub_dir = stub_dir  # type: ignore[attr-defined]
    run.work = work  # type: ignore[attr-defined]
    run.seed = seed  # type: ignore[attr-defined]
    return run


def _title(repo) -> str:
    return (repo.stub_dir / "title").read_text()


def _created(repo) -> bool:
    return (repo.stub_dir / "created").exists()


# --- the hop into dev: HEAD by default, a gated title file when it lies --


def test_dev_hop_titles_the_mr_with_the_head_subject(repo) -> None:
    """A one-commit branch: its subject is its concern, so HEAD titles it."""
    result = repo("feat(reports): #175 add the wind speed row", "--target-branch", "dev")

    assert result.returncode == 0, result.stderr
    assert _title(repo) == "feat(reports): #175 add the wind speed row"


def test_dev_hop_still_rejects_a_non_conventional_head_subject(repo) -> None:
    result = repo("added some stuff", "--target-branch", "dev")

    assert result.returncode == PRECONDITION
    assert not _created(repo)


def test_dev_hop_titles_a_multi_commit_branch_from_the_title_file(repo) -> None:
    """The 2026-09-23 gap: IQ !82 ended on a test-only commit.

    A test-first branch lands one commit per behaviour, then review fixes,
    then a committed mutation spec, so its HEAD subject names the last slice
    rather than the concern: `test(pjm): commit the conformance mutation
    spec` titled a feature MR. That subject is a valid conventional commit, so
    the dev hop accepted it, and amending it would have relabelled a real
    commit whose SHA the description cited. The concern's title has to be
    suppliable without rewriting history.
    """
    title_file = repo.work / "title.txt"
    title_file.write_text("feat(pjm): conform pjm vocabulary in staging\n")
    result = repo(
        "test(pjm): commit the conformance mutation spec",
        "--target-branch", "dev",
        "--title-file", str(title_file),
    )

    assert result.returncode == 0, result.stderr
    assert _title(repo) == "feat(pjm): conform pjm vocabulary in staging"


def test_dev_hop_title_file_must_still_be_a_conventional_commit(repo) -> None:
    """The title file supplies the concern, not an exemption from the gate.

    Into `dev` the convention is a conventional-commit title, whichever
    source it comes from; a prose title is refused as a precondition, the
    same answer a prose HEAD subject gets.
    """
    title_file = repo.work / "title.txt"
    title_file.write_text("Something I would rather call it\n")
    result = repo(
        "feat(reports): #175 add the wind speed row",
        "--target-branch", "dev",
        "--title-file", str(title_file),
    )

    assert result.returncode == PRECONDITION
    assert not _created(repo)


@pytest.mark.parametrize(
    "content",
    ["feat(pjm): conform pjm vocabulary\nin staging\n", "\n"],
    ids=["multi-line", "blank"],
)
def test_dev_hop_title_file_gets_the_same_shape_checks(repo, content) -> None:
    title_file = repo.work / "title.txt"
    title_file.write_text(content)
    result = repo(
        "test(pjm): commit the conformance mutation spec",
        "--target-branch", "dev",
        "--title-file", str(title_file),
    )

    assert result.returncode in (NO_INPUT, PRECONDITION)
    assert not _created(repo)


@pytest.mark.parametrize(
    "flags",
    [("--title-file", ""), ("--title-file=",), ("--title-file",)],
    ids=["space", "equals", "trailing"],
)
def test_an_empty_title_file_argument_is_refused_not_ignored(repo, flags) -> None:
    """An unset variable must not fall back to HEAD's slice subject.

    Each command runs in a fresh shell, so `--title-file "$TITLE_FILE"` can
    arrive empty. Into `dev` an empty value used to read as "no title file"
    and title the MR from HEAD, the IQ !82 mis-title reached by accident.
    """
    result = repo(
        "test(pjm): commit the conformance mutation spec",
        "--target-branch", "dev",
        *flags,
    )

    assert result.returncode == USAGE
    assert not _created(repo)


def test_dev_read_back_covers_the_title_file(repo) -> None:
    """IQ !82's retitle ran through `glab mr update`, outside any read-back."""
    title_file = repo.work / "title.txt"
    title_file.write_text("feat(pjm): conform pjm vocabulary in staging\n")
    result = repo(
        "test(pjm): commit the conformance mutation spec",
        "--target-branch", "dev",
        "--title-file", str(title_file),
        readback_title="test(pjm): commit the conformance mutation spec",
    )

    assert result.returncode == VERIFY_FAILED
    assert "title differs" in result.stderr


# --- the hop into main: the defect this suite exists for -----------------


def test_promotion_refuses_a_release_subject_that_passes_the_regex(repo) -> None:
    """The reported defect, as a regression test.

    `chore(release): v0.7.2` is a valid conventional commit, so the old script
    accepted it and would have titled ERG !116 — eleven merge requests, moving
    published availability and curtailment numbers at every site — after the
    release bot's chore. The refusal has to happen on *this* subject; a subject
    the regex already rejects would prove nothing.
    """
    result = repo("chore(release): v0.7.2", "--target-branch", "main")

    assert result.returncode == PRECONDITION
    assert not _created(repo), "a promotion MR was opened with no reviewed title"
    assert "--title-file" in result.stderr


def test_promotion_uses_the_title_file_verbatim(repo) -> None:
    title_file = repo.work / "title.txt"
    title_file.write_text("Promote ERG v0.7.2 to main\n")
    result = repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(title_file),
    )

    assert result.returncode == 0, result.stderr
    assert _title(repo) == "Promote ERG v0.7.2 to main"


def test_promotion_title_need_not_be_a_conventional_commit(repo) -> None:
    """6 of 6 merge requests into `main` across every repo are prose."""
    title_file = repo.work / "title.txt"
    title_file.write_text("Prod cutover — promote dev → main (first deploy)\n")
    result = repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(title_file),
    )

    assert result.returncode == 0, result.stderr
    assert _title(repo) == "Prod cutover — promote dev → main (first deploy)"


def test_promotion_title_file_survives_gitlab_reference_syntax(repo) -> None:
    """ERG !104's title was corrupted by exactly this text.

    Its commit subject read `fix: resolve MR !99 review findings (P1 PTC
    wiring + 4x P2)`; the title that reached GitLab had `!99` replaced by a
    stray `uv run python scripts/backfill_pinnacle.py --start 2026-01-01` and
    a newline. `!NNN` is GitLab's own merge-request reference syntax, so it is
    the most natural thing to write in a promotion title. Reading the title
    from a file keeps it out of any shell that could expand it.
    """
    title_file = repo.work / "title.txt"
    title_file.write_text("Promote dev to main (carries !105, !106 and !113)\n")
    result = repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(title_file),
    )

    assert result.returncode == 0, result.stderr
    assert _title(repo) == "Promote dev to main (carries !105, !106 and !113)"


def test_promotion_rejects_a_multi_line_title_file(repo) -> None:
    """A newline in the title is the shape !104's corruption arrived in."""
    title_file = repo.work / "title.txt"
    title_file.write_text("Promote ERG v0.7.2 to main\nand also this\n")
    result = repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(title_file),
    )

    assert result.returncode == PRECONDITION
    assert not _created(repo)


def test_promotion_rejects_an_empty_title_file(repo) -> None:
    title_file = repo.work / "title.txt"
    title_file.write_text("\n")
    result = repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(title_file),
    )

    assert result.returncode in (NO_INPUT, PRECONDITION)
    assert not _created(repo)


def test_promotion_rejects_a_missing_title_file(repo) -> None:
    result = repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(repo.work / "nope.txt"),
    )

    assert result.returncode == NO_INPUT
    assert not _created(repo)


# --- the hop into staging: the refresh MR --------------------------------
#
# Some repos run a dev -> staging -> main cadence (see gitlab-promotion-flow's
# staging-cadence reference). The refresh MR's source branch is `dev` itself,
# so HEAD is whatever last landed on dev — a merge commit, or where a release
# bot commits after every merge, its `chore(release): vX.Y.Z`. Neither
# describes the refresh, and the bot's subject *passes* the conventional-commit
# regex, so deriving the title is the same silent failure the main hop had.


def test_staging_hop_refuses_a_head_subject_that_passes_the_regex(repo) -> None:
    """The discriminating case: a conventional subject at dev's head.

    Where a release bot commits to `dev` after every merge, the refresh MR's
    HEAD subject is `chore(release): vX.Y.Z` — valid conventional commit, so
    the old script accepted it and titled a staging refresh after the bot's
    chore. A merge-commit subject would prove nothing here: the regex already
    rejects it, so old and new behaviour agree on that input.
    """
    result = repo("chore(release): v0.8.0", "--target-branch", "staging")

    assert result.returncode == PRECONDITION
    assert not _created(repo), "a refresh MR was opened with an underived title"
    assert "--title-file" in result.stderr


def test_staging_hop_names_the_remedy_on_a_merge_commit_head(repo) -> None:
    """The 2026-09-22 gap: dev's head is `Merge branch 'X' into 'dev'`.

    The old script refused this subject too — but as "not a conventional
    commit", pointing at amending HEAD, which cannot be done to a protected
    branch's merge commit. The refusal must name `--title-file` instead; the
    refresh that surfaced this had to fall back to a raw `glab api` POST.
    """
    result = repo(
        "Merge branch 'feat/wind-speed-row' into 'dev'",
        "--target-branch", "staging",
    )

    assert result.returncode == PRECONDITION
    assert not _created(repo)
    assert "--title-file" in result.stderr


def test_staging_refresh_uses_the_title_file_verbatim(repo) -> None:
    title_file = repo.work / "title.txt"
    title_file.write_text("Refresh staging from dev (carries !117, !118 and !121)\n")
    result = repo(
        "Merge branch 'feat/wind-speed-row' into 'dev'",
        "--target-branch", "staging",
        "--title-file", str(title_file),
    )

    assert result.returncode == 0, result.stderr
    assert _title(repo) == "Refresh staging from dev (carries !117, !118 and !121)"


@pytest.mark.parametrize(
    "flags",
    [
        ("--target-branch", "staging"),
        ("--target-branch=staging",),
        ("-b", "staging"),
        ("-bstaging",),
    ],
    ids=["long-space", "long-equals", "short-space", "short-attached"],
)
def test_every_target_branch_spelling_reaches_the_staging_rule(repo, flags) -> None:
    result = repo("chore(release): v0.8.0", *flags)

    assert result.returncode == PRECONDITION
    assert not _created(repo)


def test_staging_read_back_still_catches_a_title_that_did_not_survive(repo) -> None:
    """The refresh hop keeps the same verification as every other hop."""
    title_file = repo.work / "title.txt"
    title_file.write_text("Refresh staging from dev\n")
    result = repo(
        "Merge branch 'feat/wind-speed-row' into 'dev'",
        "--target-branch", "staging",
        "--title-file", str(title_file),
        readback_title="Refresh staging from dev ",
    )

    assert result.returncode == VERIFY_FAILED
    assert "title differs" in result.stderr


# --- resolving which hop this is ----------------------------------------


@pytest.mark.parametrize(
    "flags",
    [
        ("--target-branch", "main"),
        ("--target-branch=main",),
        ("-b", "main"),
        ("-bmain",),
    ],
    ids=["long-space", "long-equals", "short-space", "short-attached"],
)
def test_every_target_branch_spelling_reaches_the_promotion_rule(repo, flags) -> None:
    """glab accepts four spellings; missing one would silently skip the rule."""
    result = repo("chore(release): v0.7.2", *flags)

    assert result.returncode == PRECONDITION
    assert not _created(repo)


def test_an_omitted_target_falls_back_to_the_project_default_branch(repo) -> None:
    """Without `--target-branch`, glab targets the project default.

    A repo whose default branch is `main` would otherwise route a promotion
    down the dev path and title it from HEAD — the original defect, reached by
    leaving a flag off.
    """
    result = repo("chore(release): v0.7.2", default_branch="main")

    assert result.returncode == PRECONDITION
    assert not _created(repo)


def test_an_omitted_target_still_works_where_the_default_is_dev(repo) -> None:
    result = repo("feat(reports): #175 add the wind speed row", default_branch="dev")

    assert result.returncode == 0, result.stderr
    assert _title(repo) == "feat(reports): #175 add the wind speed row"


def test_the_wrappers_own_flag_never_reaches_glab(repo) -> None:
    title_file = repo.work / "title.txt"
    title_file.write_text("Promote ERG v0.7.2 to main\n")
    repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(title_file),
        "--yes",
    )

    passthrough = (repo.stub_dir / "passthrough").read_text().split()
    assert "--title-file" not in passthrough
    assert str(title_file) not in passthrough
    assert "--yes" in passthrough, "real glab flags must still be forwarded"


# --- the reference sweep on the dev hop ---------------------------------
#
# A rename lands in one file while a SQL script or runbook elsewhere keeps the
# old name, and review is where it used to be caught. Into `dev` the wrapper
# now runs `mr-preflight`'s sweep first and refuses while any reference to a
# renamed identifier survives at HEAD.


def test_dev_hop_refuses_while_a_renamed_identifier_survives(repo) -> None:
    repo.seed({
        "dbt_project.yml": "schema: LEGACY_SCHEMA\n",
        "sql/audit.sql": "USE SCHEMA LEGACY_SCHEMA;\n",
    })
    (repo.work / "dbt_project.yml").write_text("schema: LEGACY_SCHEMA_RAW\n")

    result = repo("feat(dbt): move models to the raw schema", "--target-branch", "dev")

    assert result.returncode == PRECONDITION
    assert "sql/audit.sql:1: LEGACY_SCHEMA" in result.stderr
    assert not _created(repo)


def test_dev_hop_refuses_when_the_sweep_has_no_base(repo) -> None:
    """Fail closed: a gate that skips when it cannot run guards nothing."""
    subprocess.run(["git", "remote", "remove", "origin"], cwd=repo.work, check=True)

    result = repo("feat(reports): #175 add the wind speed row", "--target-branch", "dev")

    assert result.returncode == PRECONDITION
    assert "origin/dev" in result.stderr
    assert not _created(repo)


def test_other_targets_are_not_swept(repo) -> None:
    """The sweep is the `dev` hop's gate only. An MR into any other
    non-promotion target behaves as before: no sweep, and no refusal for a
    missing `origin/<target>`, even with a surviving rename on the branch."""
    repo.seed({
        "dbt_project.yml": "schema: LEGACY_SCHEMA\n",
        "sql/audit.sql": "USE SCHEMA LEGACY_SCHEMA;\n",
    })
    (repo.work / "dbt_project.yml").write_text("schema: LEGACY_SCHEMA_RAW\n")

    result = repo(
        "fix(dbt): hotfix the schema name", "--target-branch", "hotfix-thing"
    )

    assert result.returncode == 0, result.stderr
    assert _created(repo)



def test_dev_hop_shows_what_the_repo_ignore_list_suppressed(repo) -> None:
    """A clean sweep still reports the hits `.mr-preflight.toml` suppressed,
    so the author sees allowlist creep on the path that enforces the gate."""
    repo.seed({
        ".mr-preflight.toml": 'ignore_paths = ["CHANGELOG.md"]\n',
        "dbt_project.yml": "schema: LEGACY_SCHEMA\n",
        "CHANGELOG.md": "- LEGACY_SCHEMA created\n",
    })
    (repo.work / "dbt_project.yml").write_text("schema: LEGACY_SCHEMA_RAW\n")

    result = repo("feat(dbt): move models to the raw schema", "--target-branch", "dev")

    assert result.returncode == 0, result.stderr
    assert _created(repo)
    assert (
        "mr-preflight: .mr-preflight.toml suppressed 1 hit(s) in ignored paths"
        " and skipped 0 renamed token(s)."
    ) in result.stderr.splitlines()



@pytest.mark.parametrize("stderr", ["closed", "broken pipe"])
def test_dev_hop_still_opens_the_mr_when_stderr_is_closed(repo, stderr) -> None:
    """The passing sweep's output is information, not a gate: failing to show
    it must not stop an MR that the sweep let through."""
    repo.seed({
        ".mr-preflight.toml": 'ignore_paths = ["CHANGELOG.md"]\n',
        "dbt_project.yml": "schema: LEGACY_SCHEMA\n",
        "CHANGELOG.md": "- LEGACY_SCHEMA created\n",
    })
    (repo.work / "dbt_project.yml").write_text("schema: LEGACY_SCHEMA_RAW\n")

    result = repo(
        "feat(dbt): move models to the raw schema",
        "--target-branch",
        "dev",
        close_stderr=stderr == "closed",
        broken_stderr=stderr == "broken pipe",
    )

    assert result.returncode == 0
    assert _created(repo)


SWEEP_BEGIN = "<!-- mr-preflight:sweep:begin -->"
SWEEP_END = "<!-- mr-preflight:sweep:end -->"


def test_dev_hop_ships_the_waiver_it_accepted_in_the_description(repo) -> None:
    """Refused while the changelog's old name is unwaived; created once the
    description waives it, with the rendered block and its reason in the MR."""
    repo.seed({
        "dbt_project.yml": "schema: LEGACY_SCHEMA\n",
        "CHANGELOG.md": "- LEGACY_SCHEMA created\n",
    })
    (repo.work / "dbt_project.yml").write_text("schema: LEGACY_SCHEMA_RAW\n")
    subject = "feat(dbt): move models to the raw schema"
    prose = "## What this does\n\nMoves the models.\n\n"

    refused = repo(subject, "--target-branch", "dev", description=prose)
    assert refused.returncode == PRECONDITION
    assert "CHANGELOG.md:1: LEGACY_SCHEMA" in refused.stderr
    assert f"--description {repo.work / 'description.md'} --update" in refused.stderr
    assert not _created(repo)

    waived = (
        f"{prose}{SWEEP_BEGIN}\n"
        "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry\n"
        f"{SWEEP_END}\n"
    )
    result = repo(subject, "--target-branch", "dev", description=waived)

    assert result.returncode == 0, result.stderr
    sent = (repo.stub_dir / "description").read_text()
    assert sent.startswith(f"{prose}{SWEEP_BEGIN}\n**mr-preflight sweep**\n")
    assert "- `LEGACY_SCHEMA` -> `LEGACY_SCHEMA_RAW` in `dbt_project.yml`" in sent
    assert "- waive LEGACY_SCHEMA CHANGELOG.md: historical entry" in sent
    assert sent.endswith(SWEEP_END)
    assert (repo.work / "description.md").read_text() == waived



@pytest.mark.parametrize(
    ("target", "subject", "title"),
    [
        # Reaches the `dev` check itself: only `dev` may gain a block.
        ("hotfix-thing", "fix(dbt): hotfix the schema name", ""),
        # A promotion never reaches that check; pinned as it was before.
        ("main", "chore(release): v0.7.2", "Promote ERG v0.7.2 to main\n"),
    ],
)
def test_other_hops_send_the_description_as_written(repo, target, subject, title) -> None:
    """A renamed identifier is on the branch, so a sweep would have rendered
    a block; any hop but `dev` must still send the author's text unchanged."""
    repo.seed({"dbt_project.yml": "schema: LEGACY_SCHEMA\n"})
    (repo.work / "dbt_project.yml").write_text("schema: LEGACY_SCHEMA_RAW\n")
    title_args: list[str] = []
    if title:
        (repo.work / "title.txt").write_text(title)
        title_args = ["--title-file", str(repo.work / "title.txt")]
    body = "## What ships\n\n- !101\n"

    result = repo(subject, "--target-branch", target, *title_args, description=body)

    assert result.returncode == 0, result.stderr
    assert (repo.stub_dir / "description").read_text() == body.rstrip("\n")



def test_a_description_file_named_like_a_flag_still_reaches_the_sweep(repo) -> None:
    """`cp -desc.md` reads the name as options; the copy must take it as a path."""
    body = "## What this does\n\nAdds a row.\n"

    result = repo(
        "feat(reports): #175 add the wind speed row",
        "--target-branch", "dev",
        description=body,
        description_name="-desc.md",
    )

    assert result.returncode == 0, result.stderr
    assert (repo.stub_dir / "description").read_text() == body.rstrip("\n")


def test_broken_markers_are_refused_without_the_update_hint(repo) -> None:
    """`--update` cannot repair a broken block, so suggesting it misleads:
    the refusal names the markers instead."""
    body = f"## What this does\n\n{SWEEP_BEGIN}\nno end marker\n"

    result = repo("feat(reports): #175 add the wind speed row", "--target-branch", "dev", description=body)

    assert result.returncode == PRECONDITION
    assert "mr-preflight:sweep:end" in result.stderr
    assert "--update" not in result.stderr
    assert not _created(repo)


# --- the guards that already existed ------------------------------------


@pytest.mark.parametrize(
    "flag",
    ["--title", "--title=x", "-t", "-tx", "--description", "--description=x", "-d", "-dx"],
)
def test_a_caller_supplied_title_or_description_is_still_refused(repo, flag) -> None:
    result = repo("feat(reports): #175 add the wind speed row", "--target-branch", "dev", flag)

    assert result.returncode == USAGE
    assert not _created(repo)


def test_the_description_keeps_its_real_newlines(repo) -> None:
    body = "## Heading\n\n- one\n- two\n"
    result = repo(
        "feat(reports): #175 add the wind speed row",
        "--target-branch", "dev",
        description=body,
    )

    # Nothing was renamed, so no sweep block is added: the MR carries the
    # author's description exactly.
    assert result.returncode == 0, result.stderr
    assert (repo.stub_dir / "description").read_text() == body.rstrip("\n")
    assert "\\n" not in (repo.stub_dir / "description").read_text()


def test_read_back_still_catches_a_title_that_did_not_survive(repo) -> None:
    """The verification must cover the title file's value too, not just HEAD."""
    title_file = repo.work / "title.txt"
    title_file.write_text("Promote ERG v0.7.2 to main\n")
    result = repo(
        "chore(release): v0.7.2",
        "--target-branch", "main",
        "--title-file", str(title_file),
        readback_title="Promote ERG v0.7.2 to main ",
    )

    assert result.returncode == VERIFY_FAILED
    assert "title differs" in result.stderr
