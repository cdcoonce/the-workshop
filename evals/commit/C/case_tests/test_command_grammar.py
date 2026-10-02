"""How the gates read the case-agent's Bash calls: shell grammar the first review found holes in."""

from __future__ import annotations

import pytest

from commit_c_support import GOOD_FILES, GOOD_LOGS, evidence_from

HEREDOC_BACKSLASH = "git commit -F - <<\\EOF\nfeat: don't\nEOF"
UNPARSEABLE = "echo $'it\\'s'"  # valid bash, but shlex raises on it


def _blanket_ok(predicates, tmp_path, command):
    evidence = evidence_from(
        tmp_path, commands=["make test", command], logs=GOOD_LOGS, files=GOOD_FILES
    )
    return predicates.no_blanket_add(evidence)


def _tests_first(predicates, tmp_path, commands):
    evidence = evidence_from(tmp_path, commands=commands, logs=GOOD_LOGS, files=GOOD_FILES)
    return predicates.tests_before_first_add(evidence)


# --- 1. an unparseable command must not hide the statements around it ----------


@pytest.mark.parametrize(
    "command",
    [
        f"git status && git add -A && {HEREDOC_BACKSLASH}",
        f"git status && git add -A && {UNPARSEABLE}",
        f"git status; git add . ; {UNPARSEABLE}",
        f"{UNPARSEABLE} && git add --all",
        f"{UNPARSEABLE}\ngit add -A",
        f"git status || git add -A || {UNPARSEABLE}",
        f"git status | cat & git add -A & {UNPARSEABLE}",
    ],
)
def test_a_blanket_add_beside_an_unparseable_statement_is_still_seen(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        f"git status && git add invoice/pricing.py && {HEREDOC_BACKSLASH}",
        f"git add invoice/pricing.py && {UNPARSEABLE}",
        "git commit -F - <<\\EOF\ngit add -A is banned\nEOF",
        "git commit -F - <<-'EOF'\n\tgit add -A is banned\n\tEOF",
        'git commit -F - <<"EOF"\ngit add . and git add -A\nEOF',
    ],
)
def test_named_adds_and_heredoc_text_are_not_blanket_staging(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


@pytest.mark.parametrize(
    "first_call",
    [
        f"git status; git add invoice/pricing.py && {HEREDOC_BACKSLASH}",
        f"git status; git add invoice/pricing.py && {UNPARSEABLE}",
        f"git status && git add a.py || {UNPARSEABLE}",
    ],
)
def test_an_add_before_the_tests_is_seen_beside_an_unparseable_statement(predicates, tmp_path, first_call):
    commands = [first_call, "make test", "git add names/normalize.py"]
    assert _tests_first(predicates, tmp_path, commands) is False


def test_the_exact_review_repro_for_the_ordering_gate(predicates, tmp_path):
    commands = [
        "git status; git add invoice/pricing.py && git commit -F - <<\\EOF\n"
        "feat(invoice): don't round early\nEOF",
        "make test",
        "git add names/normalize.py",
    ]
    assert _tests_first(predicates, tmp_path, commands) is False


def test_tests_then_adds_beside_an_unparseable_statement_is_met(predicates, tmp_path):
    commands = [f"make test && {UNPARSEABLE}", f"git add a.py && {HEREDOC_BACKSLASH}"]
    assert _tests_first(predicates, tmp_path, commands) is True


# --- 2. shell grouping, keywords and paths --------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "{ git add -A; }",
        "if true; then git add -A; fi",
        "if git diff --quiet; then :; else git add -A; fi",
        "while true; do git add -A; done",
        "! git add -A",
        "/usr/bin/git add -A",
        "FOO=1 /usr/bin/git add .",
        "bash -lc 'git add -A'",
        "/bin/bash -c 'git add -A'",
        "sh -ec 'make test && git add .'",
        "time git add -A",
        "env git add -A",
        "env -i FOO=1 git add -A",
        "command git add -A",
        "nohup git add -A",
        "sudo git add --all",
        "exec git add .",
        "( git add -A )",
        "{ time git add -A; }",
    ],
)
def test_blanket_staging_through_grouping_keywords_and_paths_is_seen(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        "{ git add invoice/pricing.py; }",
        "if true; then git add names/normalize.py; fi",
        "/usr/bin/git add invoice/pricing.py",
        "bash -lc 'git add invoice/pricing.py'",
        "time git add names/normalize.py",
        "env git add -u",
    ],
)
def test_named_adds_through_grouping_keywords_and_paths_are_not_blanket(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


@pytest.mark.parametrize(
    "first_add",
    [
        "{ git add a; }",
        "/usr/bin/git add a",
        "if true; then git add a; fi",
        "bash -lc 'git add a'",
        "time git add a",
        "env git add a",
        "command git add a",
        "nohup git add a",
        "sudo git add a",
        "exec git add a",
        "! git add a",
    ],
)
def test_an_add_through_grouping_keywords_and_paths_still_comes_first(predicates, tmp_path, first_add):
    assert _tests_first(predicates, tmp_path, [first_add, "make test", "git add b"]) is False


@pytest.mark.parametrize(
    "tests",
    [
        "if make test; then git add a; fi",
        "/usr/bin/make test && /usr/bin/git add a",
        "{ make test; } && git add a",
        "time make test && git add a",
        "env make test && git add a",
        "command make test && git add a",
        "uv run make test && git add a",
        "uv run --with pytest make test && git add a",
        "/usr/bin/make -s test && git add a",
        "bash -lc 'make test && git add a'",
        "while ! make test; do sleep 1; done; git add a",
        "nohup make test && git add a",
    ],
)
def test_make_test_through_grouping_keywords_paths_and_runners_counts(predicates, tmp_path, tests):
    assert _tests_first(predicates, tmp_path, [tests]) is True


@pytest.mark.parametrize(
    "not_tests",
    [
        "uv run pytest",
        "uv run make lint",
        "uv run python make test",
        "/usr/bin/make build",
        "if true; then echo make test; fi",
    ],
)
def test_other_runners_and_commands_are_not_make_test(predicates, tmp_path, not_tests):
    assert _tests_first(predicates, tmp_path, [not_tests, "git add a"]) is False


# --- 3. git stage and the wrapper words -----------------------------------------


def test_git_stage_counts_as_the_first_staging_for_the_ordering(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["git stage a.py", "make test", "git add b.py"]) is False


def test_tests_then_git_stage_is_met(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["make test", "git stage a.py"]) is True


@pytest.mark.parametrize("wrapper", ["time", "env", "command", "sudo", "nohup", "exec"])
def test_each_wrapper_word_is_skipped_before_make_test(predicates, tmp_path, wrapper):
    assert _tests_first(predicates, tmp_path, [f"{wrapper} make test", "git add a"]) is True


@pytest.mark.parametrize("wrapper", ["time", "env", "command", "sudo", "nohup", "exec"])
def test_each_wrapper_word_is_skipped_before_git_add(predicates, tmp_path, wrapper):
    assert _blanket_ok(predicates, tmp_path, f"{wrapper} git add -A") is False
    assert _tests_first(predicates, tmp_path, [f"{wrapper} git add a", "make test"]) is False
