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


# --- round 3: heredoc delimiters, quoting, line continuation, substitutions -------


@pytest.mark.parametrize(
    "command",
    [
        "cat <<END-MSG\nbody\nEND-MSG\ngit add -A",
        "cat <<EOF.X\nbody\nEOF.X\ngit add -A",
        "cat <<'END-MSG'\nbody\nEND-MSG\ngit add -A",
        'cat <<"END_MSG"\nbody\nEND_MSG\ngit add -A',
        "cat <<-EOF\n\tbody\n\tEOF\ngit add -A",
        "cat <<A <<B\nx\nA\ny\nB\ngit add -A",
        "git commit -F - <<EOF\nfeat: x\nEOF\ngit add -A",
        "cat <<EOF && git add -A\nbody\nEOF",
        "echo $((1<<2))\ngit add -A",
        "echo $((1<<2)) && git add -A",
        "((x = 1<<2))\ngit add -A",
        "git commit -m 'a << b'\ngit add -A",
        'git commit -m "a << b"\ngit add -A',
        "echo a<<b\ngit add -A",  # a heredoc delimited by `b`, with no terminator
    ],
)
def test_a_blanket_add_after_a_heredoc_like_construct_is_seen(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        "cat <<EOF\ngit add -A",
        "cat <<EOF\nbody\ngit add -A\n",
        "cat <<END-MSG\nbody\nEND_MSG\ngit add -A",
    ],
)
def test_an_unterminated_heredoc_does_not_hide_the_text_after_it(predicates, tmp_path, command):
    """No terminator: fail toward seeing, so the rest is still read as commands."""
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        "cat <<END-MSG\ngit add -A\nEND-MSG",
        "cat <<EOF.X\ngit add .\nEOF.X",
        "cat <<EOF\nbody\nEOF\ngit add invoice/pricing.py",
        "echo 'a << b' && git add invoice/pricing.py",
        "echo $((1<<2)) && git add invoice/pricing.py",
        "git add invoice/pricing.py <<< 'git add -A'",
    ],
)
def test_heredoc_text_and_shift_operators_are_not_blanket_staging(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


@pytest.mark.parametrize(
    "command",
    [
        "bash <<'EOF'\ngit add -A\nEOF",
        "sh <<EOF\nmake test\ngit add .\nEOF",
        "bash -s <<EOF\ngit add -A\nEOF",
        "/bin/zsh <<-EOF\n\tgit add --all\n\tEOF",
    ],
)
def test_a_heredoc_fed_to_a_shell_carries_commands(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


def test_a_heredoc_fed_to_a_shell_counts_for_the_ordering(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["bash <<'EOF'\nmake test\ngit add a\nEOF"]) is True
    assert _tests_first(predicates, tmp_path, ["bash <<'EOF'\ngit add a\nEOF", "make test", "git add b"]) is False


def test_a_heredoc_fed_to_cat_is_data_not_commands(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["cat <<EOF\ngit add a\nEOF", "make test", "git add b"]) is True


# sudo's value options, and line continuations


def test_sudo_with_a_user_option_still_reaches_the_command(predicates, tmp_path):
    assert _blanket_ok(predicates, tmp_path, "sudo -u x git add -A") is False
    assert _tests_first(predicates, tmp_path, ["sudo -u x make test", "git add a"]) is True
    assert _tests_first(predicates, tmp_path, ["sudo -u x git add a", "make test", "git add b"]) is False


@pytest.mark.parametrize(
    "command",
    [
        "make test && \\\ngit add -A",
        "git add \\\n  -A",
        "git \\\n add -A",
        "echo hi && \\\n   git add --all",
    ],
)
def test_a_blanket_add_across_a_line_continuation_is_seen(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


def test_line_continuations_are_joined_for_the_ordering(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["make test && \\\n  git add a"]) is True
    assert _tests_first(predicates, tmp_path, ["git add a && \\\n  make test", "git add b"]) is False
    assert _tests_first(predicates, tmp_path, ["make \\\n test && git add a"]) is True


# the unparseable-command fallback is gone: ANSI-C quotes are parsed, unterminated quotes are literal


def test_a_make_test_inside_an_ansi_c_quote_is_not_a_test_run(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["echo $'don\\'t ; make test'; git add a"]) is False


def test_a_git_add_inside_an_ansi_c_quote_is_not_staging(predicates, tmp_path):
    assert _blanket_ok(predicates, tmp_path, "git commit -m $'fix: don\\'t; git add -A'") is True


def test_an_unterminated_quote_swallows_the_rest_as_bash_does(predicates, tmp_path):
    """bash reports a syntax error and runs none of the quoted tail."""
    assert _blanket_ok(predicates, tmp_path, 'echo "unterminated; git add -A') is True
    assert _blanket_ok(predicates, tmp_path, 'git add -A && echo "unterminated') is False
    assert _tests_first(predicates, tmp_path, ["echo 'oops; make test", "git add a"]) is False


# wrappers with their own arguments, dry runs, xargs, eval


@pytest.mark.parametrize(
    "tests",
    [
        "timeout 300 make test && git add a",
        "timeout -s KILL 300 make test && git add a",
        "timeout --signal=KILL 5m make test && git add a",
        "timeout -k 5 300 make test && git add a",
        "nice make test && git add a",
        "nice -n 5 make test && git add a",
        "nice -5 make test && git add a",
        "ionice -c 2 -n 7 make test && git add a",
        "stdbuf -oL make test && git add a",
        "stdbuf -o L -e0 make test && git add a",
        "builtin command make test && git add a",
        "eval make test && git add a",
        'eval "make test && git add a"',
        "make -j4 test && git add a",
        "make -k test && git add a",
        "make test -j4 && git add a",
    ],
)
def test_make_test_behind_a_wrapper_with_its_own_arguments_counts(predicates, tmp_path, tests):
    assert _tests_first(predicates, tmp_path, [tests]) is True


@pytest.mark.parametrize(
    "dry_run",
    ["make -n test", "make --dry-run test", "make --just-print test", "make --recon test", "make -ns test", "make -nk test", "make test -n", "make -n -s test", "make test --dry-run"],
)
def test_a_dry_run_is_not_running_the_tests(predicates, tmp_path, dry_run):
    assert _tests_first(predicates, tmp_path, [dry_run, "git add a"]) is False


@pytest.mark.parametrize(
    "command",
    [
        "nice -n 5 git add -A",
        "timeout 5 git add -A",
        "ionice -c 3 git add --all",
        "stdbuf -oL git add .",
        "eval 'git add -A'",
        "eval git add -A",
        'eval "make test; git add ."',
        "git ls-files | xargs git add -A",
        "xargs -0 git add -A",
        "x=$(git add -A)",
        'echo "$(git add -A)"',
        "echo `git add -A`",
        "echo $(echo $(git add -A))",
        'git commit -m "$(git add -A; echo msg)"',
        "diff <(git add -A) /dev/null",
        "cat <(echo hi) <(git add .)",
    ],
)
def test_blanket_staging_behind_wrappers_eval_and_substitutions_is_seen(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        "git ls-files -m | xargs git add",
        "xargs -n 1 git add",
        "xargs -I {} git add {}",
        'echo "$(git status --short)"',
        "x=$(git rev-parse HEAD) && git add invoice/pricing.py",
        "echo `date`",
    ],
)
def test_stdin_fed_or_unrelated_commands_are_not_blanket_staging(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


def test_xargs_git_add_is_an_add_for_the_ordering(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["git ls-files -m | xargs git add", "make test", "git add b"]) is False
    assert _tests_first(predicates, tmp_path, ["make test", "git ls-files -m | xargs git add"]) is True


def test_substitutions_run_before_the_command_that_contains_them(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ['git add "$(make test)"']) is True
    assert _tests_first(predicates, tmp_path, ["x=$(make test); git add a"]) is True
    assert _tests_first(predicates, tmp_path, ["git add a", "echo $(make test)"]) is False
    assert _tests_first(predicates, tmp_path, ["echo `make test` && git add a"]) is True


# quoted `<<`, arithmetic and `((` hide nothing even when a terminator-looking line follows


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'a << b'\ngit add -A\nb",
        'git commit -m "a << b"\ngit add -A\nb',
        "echo $((1<<2))\ngit add -A\n2",
        "((x = 1<<2))\ngit add -A\n2",
        "echo a\\<<b\ngit add -A\nb",
        'echo "`git add -A`"',
        'echo "$(git add -A)"',
    ],
)
def test_quoted_shift_and_arithmetic_text_never_swallow_a_following_add(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


def test_a_substitution_argument_runs_before_its_command(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["git add $(make test)"]) is True
    assert _tests_first(predicates, tmp_path, ["git add a <(make test)"]) is True


def test_xargs_options_with_values_are_skipped(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["xargs -n 1 git add", "make test", "git add b"]) is False
    assert _tests_first(predicates, tmp_path, ["git ls-files | xargs -I {} git add {}", "make test"]) is False


def test_a_make_directory_that_starts_with_n_is_not_a_dry_run(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["make -Cnode test", "git add a"]) is True
    assert _tests_first(predicates, tmp_path, ["make -C node test", "git add a"]) is True


@pytest.mark.parametrize(
    "command",
    [
        "git add invoice/pricing.py # ; git add -A",
        "git add invoice/pricing.py  # && git add .",
        "echo ok\n# note; git add -A\nls",
    ],
)
def test_a_comment_hides_nothing_but_is_not_a_command_either(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


# --- round 4: redirections, limits, shell options, heredoc substitutions, abbreviations ----


@pytest.mark.parametrize(
    "command",
    [
        "2>&1 git add -A",
        ">/dev/null git add -A",
        "> /dev/null git add -A",
        "</dev/null git add -A",
        "&>/dev/null git add -A",
        "&> /dev/null git add -A",
        "git 2>/dev/null add -A",
        "git add -A 2>&1",
        "git add >/dev/null -A",
        "1>out 2>err git add --all",
        ">>log git add .",
        "git add . <<< 'x'",
        "git add -A >& /dev/null",
        "git add -A <&0",
        "3<file git add -A",
    ],
)
def test_redirections_are_not_command_words(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        "git add invoice/pricing.py 2>&1",
        "2>&1 git add invoice/pricing.py",
        "git add a.py >/dev/null",
    ],
)
def test_redirected_named_adds_are_not_blanket(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


@pytest.mark.parametrize(
    "lint",
    [
        "make lint > test",
        "make check >test",
        "make lint 2> test",
        "make lint >> test",
        "make lint &> test",
        "make lint < test",
        "make lint >& test",
    ],
)
def test_a_redirection_target_named_test_is_not_the_make_target(predicates, tmp_path, lint):
    assert _tests_first(predicates, tmp_path, [lint, "git add a"]) is False


@pytest.mark.parametrize(
    "tests",
    [
        "2>&1 make test",
        ">/dev/null make test",
        "make 2>/dev/null test",
        "make test 2>&1 | tail -5",
        "make test > out.log 2>&1",
    ],
)
def test_make_test_with_redirections_still_counts(predicates, tmp_path, tests):
    assert _tests_first(predicates, tmp_path, [tests, "git add a"]) is True


# limits: never silently drop commands


def test_a_thousand_statements_before_a_blanket_add_are_all_read(predicates, tmp_path):
    assert _blanket_ok(predicates, tmp_path, "true;" * 1000 + "git add -A") is False
    assert _tests_first(predicates, tmp_path, ["true;" * 1500 + "git add a", "make test"]) is False


def test_ordinary_nesting_is_read(predicates, tmp_path):
    nested = "$(" * 20 + "git add -A" + ")" * 20
    assert _blanket_ok(predicates, tmp_path, f"echo {nested}") is False


def test_an_absurd_nesting_raises_instead_of_silently_dropping(predicates, tmp_path):
    nested = "$(" * 1000 + "git add -A" + ")" * 1000
    with pytest.raises(ValueError, match="nested"):
        _blanket_ok(predicates, tmp_path, f"echo {nested}")


def test_deeply_nested_eval_raises_too(predicates, tmp_path):
    with pytest.raises(ValueError, match="nested"):
        _blanket_ok(predicates, tmp_path, "eval " * 60 + "git add -A")


def test_a_command_with_too_many_statements_raises(predicates, tmp_path):
    with pytest.raises(ValueError, match="statements"):
        _blanket_ok(predicates, tmp_path, "true;" * 100_001 + "git add -A")


# shell option forms


@pytest.mark.parametrize(
    "command",
    [
        "bash -o pipefail -c 'git add -A'",
        "bash -euo pipefail -c 'git add -A'",
        "bash -O extglob -c 'git add -A'",
        "bash -c -- 'git add -A'",
        "bash -euc 'git add -A'",
        "bash --norc -c 'git add -A'",
        "bash --rcfile /dev/null -c 'git add -A'",
        "bash --init-file /dev/null -ic 'git add -A'",
        "sh -c 'git add -A' sh arg",
        "bash <<<'git add -A'",
        "bash <<< 'make test; git add .'",
        'bash -s <<<"git add --all"',
        "zsh -c 'git add .'",
    ],
)
def test_shell_option_forms_still_reach_the_script(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        "bash -o pipefail -c 'git add invoice/pricing.py'",
        "bash -euo pipefail script.sh",
        "bash script.sh 'git add -A'",
        "bash -c 'echo hi'",
        "bash <<<'git add invoice/pricing.py'",
        "cat <<<'git add -A'",
    ],
)
def test_shell_forms_that_do_not_stage_everything(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


def test_shell_options_count_for_the_ordering(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["bash -euo pipefail -c 'make test && git add a'"]) is True
    assert _tests_first(predicates, tmp_path, ["bash -o pipefail -c 'git add a'", "make test", "git add b"]) is False
    assert _tests_first(predicates, tmp_path, ["bash <<<'make test; git add a'"]) is True


# substitutions inside an UNQUOTED heredoc body run; a quoted delimiter keeps the body inert


@pytest.mark.parametrize(
    "command",
    [
        "cat <<EOF\n$(git add -A)\nEOF",
        "cat <<EOF\n`git add -A`\nEOF",
        "cat <<-EOF\n\tmessage $(git add --all) tail\n\tEOF",
        "cat <<EOF\nline one\nname: $(git add .)\nEOF\nls",
        "git commit -F - <<EOF\nfeat: x\n\n$(git add -A)\nEOF",
        "cat <<EOF\n$(echo $(git add -A))\nEOF",
    ],
)
def test_substitutions_in_an_unquoted_heredoc_are_read(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'EOF'\n$(git add -A)\nEOF",
        'cat <<"EOF"\n$(git add -A)\nEOF',
        "cat <<\\EOF\n$(git add -A)\nEOF",
        "cat <<'EOF'\n`git add -A`\nEOF",
        "cat <<EOF\n\\$(git add -A)\nEOF",
        "cat <<EOF\n\\`git add -A\\`\nEOF",
        "cat <<EOF\n$((1 + 2))\nEOF",
        "cat <<EOF\nplain text git add -A\nEOF",
    ],
)
def test_a_quoted_or_escaped_heredoc_body_stays_inert(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is True


def test_a_heredoc_substitution_counts_for_the_ordering(predicates, tmp_path):
    assert _tests_first(predicates, tmp_path, ["cat <<EOF\n$(git add a)\nEOF", "make test", "git add b"]) is False
    assert _tests_first(predicates, tmp_path, ["cat <<'EOF'\n$(git add a)\nEOF", "make test", "git add b"]) is True


# long-option abbreviations and the other make modes that run no recipe


@pytest.mark.parametrize("flag", ["--all", "--al"])
def test_unambiguous_abbreviations_of_all_are_blanket(predicates, tmp_path, flag):
    assert _blanket_ok(predicates, tmp_path, f"git add {flag}") is False


@pytest.mark.parametrize("flag", ["--a", "--allow", "--alx", "--no-all", "--ignore-errors", "--update"])
def test_other_long_options_are_not_blanket(predicates, tmp_path, flag):
    assert _blanket_ok(predicates, tmp_path, f"git add {flag} invoice/pricing.py") is True


@pytest.mark.parametrize(
    "no_recipe",
    ["make -q test", "make -t test", "make --question test", "make --touch test", "make -kq test", "make -st test", "make test -q"],
)
def test_make_modes_that_run_no_recipe_are_not_running_the_tests(predicates, tmp_path, no_recipe):
    assert _tests_first(predicates, tmp_path, [no_recipe, "git add a"]) is False


@pytest.mark.parametrize(
    "command",
    [
        "git add &> out -A",
        "bash -c -- '-x; git add -A'",
        "<<EOF\n$(git add -A)\nEOF",
        "git add -A &>/dev/null",
    ],
)
def test_odd_redirect_and_option_spellings_still_reach_the_add(predicates, tmp_path, command):
    assert _blanket_ok(predicates, tmp_path, command) is False
