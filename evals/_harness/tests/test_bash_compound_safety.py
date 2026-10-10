"""Regression rows from the adversarial review of the compound-construct reading (fix round 2).

The reviewer ran the real classifier and real bash and proved shapes that classified ``none`` or ``tests``
while real bash wrote ``src/``. T1 is a gate, so a wrong hit is far worse than a wrong miss, and the reading
was cut back to what the audited bug needs: ``[[ ]]`` and ``read`` are not read-only (both evaluate a
subscripted name as arithmetic, so a ``$(...)`` inside runs), an unresolved expansion in the arguments of a head
keeps the call read-only only for heads that cannot write or run code whatever they are given, a loop variable is
an opaque expansion like any other (no reading of a ``for`` word list, which ignored ``IFS``), and in a call
with a write every ``cd`` target must be a plain literal path outside ``src``. None of these commands is ever run
by a test; only the class is asserted.
"""

from __future__ import annotations

import time

import pytest

from evals._harness.bash_classify import BASH_COMMAND_CAP, bash_write_offset, classify_bash_command

# --------------------------------------------------------------------------- F1: [[ ]] evaluates arithmetic

F1_ROWS = [
    "[[ 'a[$(cp x src/shop/cart.py)]' -eq 1 ]]",
    "x='a[$(cp x src/shop/cart.py)]'; [[ $x -eq 1 ]]",
    "for f in 'a[$(cp x src/y)]'; do [[ $f -eq 1 ]]; done",
    "[[ -f a ]]",
    "[[ -f a ]] && cat a",
    "if [[ -f x ]]; then cat x; fi",
    "[[ $x =~ ^(a|b)$ ]] || echo no",
    "[[ a < b ]]",
    "while [[ -f x ]]; do cat x; done",
    "! [[ -f x ]]",
]


@pytest.mark.parametrize("command", F1_ROWS)
def test_f1_a_double_bracket_test_is_never_read_only(command):
    assert classify_bash_command(command) == "source", command
    assert bash_write_offset(command) == 0, command


# --------------------------------------------------------------------------- F2: read evaluates a subscripted name

F2_ROWS = [
    "read 'a[$(cp x src/shop/cart.py)]' <<< 1",
    "echo 1 | read 'a[$(cp x src/y)]'",
    "for f in 'a[$(cp x src/y)]'; do read $f <<< 1; done",
    "while read 'a[$(cp x src/y)]'; do cat a; done < f",
    "while read l; do echo $l; done < notes.txt",
    "read x < f",
    "read -r a b < f",
    "cat f | while read l; do echo $l; done",
]


@pytest.mark.parametrize("command", F2_ROWS)
def test_f2_read_is_not_read_only(command):
    assert classify_bash_command(command) == "source", command


# --------------------------------------------------------------------------- F3: an unresolved argument can carry a flag

F3_SOURCE_ROWS = [
    "for f in '-delete -name cart.py'; do find src/shop $f; done",
    "for f in '-i s/a/b/'; do sed $f src/shop/cart.py; done",
    "for f in '-i s/a/b/'; do sed ${f} src/shop/cart.py; done",
    "for f in -i; do sed \"$f\" s/a/b/ src/shop/cart.py; done",
    "for f in '-delete'; do find src/shop \"$f\"; done",
    "for f in $(echo -delete); do find src/shop $f; done",
    "for f in $(echo -i); do sed $f s/a/b/ src/shop/cart.py; done",
    "for f in -i a; do sed $f s/a/b/ src/shop/cart.py; done",
    "for f in -delete; do find src/shop $f; done",
    "for f in -delete 'x y'; do find src/shop $f; done",
    "for f in '-delete -name x'; do find src/shop $f; done",
    "x=-delete; find src $x",
    "x=-i; sed $x s/a/b/ src/shop/cart.py",
    "x='w src/y'; sed -n \"$x\" f",
    "x=-o; sort $x src/shop/cart.py",
    "x=-fprint; find src $x src/y",
    "x=-i; perl $x -e 1 f",
    "find src -name $(echo -delete)",
    "find src `echo -delete`",
    "sed -n $(echo 'w src/y') f",
    # every head outside the fixed safe list goes to source on an unresolved argument
    "sort $f",
    "uniq $f",
    "tree $d",
    "jq . $f",
    "git log $x",
    "git diff $x",
    "awk '{print}' $f",
    "xargs cat $f",
    "uv run pytest $x",
    "uv run pytest -q tests/$f",
    "pytest $x",
    "python3 -m pytest $x",
    "ruff check $f",
    "ruff format --check $f",
    "mypy $f",
    "black --check $f",
    "python3 -c \"print($x)\"",
    "cd $d",
    "cd $d; ls",
    "sleep $n",
    "date $x",
    "which $x",
    "type $x",
    "less $f",
    "more $f",
    "true $x",
    "pwd $x",
    "rg x $f",
    "file $f",
    "for f in -C; do file $f -m x; done",
    "for f in --pre=cp; do rg a $f; done",
    # printf: a format that is not a literal, or -v
    "printf $fmt a",
    "printf -v x a",
    "printf -vx a",
    "printf '%s' a; printf -v y b",
    "for f in a; do printf -v f /tmp; done",
    # test and [ : -v and -R evaluate a subscript; an unresolved word in operator position can be -v
    "test -v 'a[$(cmd)]'",
    "[ -v x ]",
    "[ -R x ]",
    "test -R 'a[$(cmd)]'",
    "[ -f a -a -v x ]",
    "[ $x 'a[$(cmd)]' ]",
    "[ ! $x a ]",
    "[ -f a -a $x a ]",
    "[ -f a -o $x a ]",
    "test $x a",
    "[ \\( $x a \\) ]",
    # an unquoted expansion in a test is split into words, any of which can be an operator (#1129)
    "test -f $f",
    "[ -f $f ]",
    "[ ! -f $f ]",
    "[ -n a -a -f $f ]",
    "[ a = $x ]",
    "[ 1 -eq $x ]",
    "FOO=1 uv run pytest -q",
]


@pytest.mark.parametrize("command", F3_SOURCE_ROWS)
def test_f3_an_unresolved_argument_to_a_head_that_could_take_a_write_flag_is_source(command):
    assert classify_bash_command(command) == "source", command
    assert bash_write_offset(command) is not None, command


F3_NONE_ROWS = [
    "cat $f",
    "echo $f",
    "echo \"=== $f\"",
    "echo $(date)",
    "echo `pwd`",
    "wc -l $f",
    "head -5 $f",
    "tail -n 3 $f",
    "ls $d",
    "ls -la $d | wc -l",
    "cut -d, -f1 $f",
    "tr a $x",
    "stat $f",
    "du -sh $f",
    "diff $a $b",
    "cmp $a $b",
    "grep -n x $f",
    "grep -rn $x src/",
    "egrep x $f",
    "fgrep $x f",
    "printf '%s\\n' $f",
    "printf '%s %s' $a $b",
    "for f in a b; do cat $f; done",
    "for f in a; do echo $f; wc -l $f; done",
    "for f in src/*.py; do wc -l $f; done",
    "for f in tests/*.py; do cat $f; done | tail -5",
    "for f in a; do ls $f; done",
    "for f in a; do grep -n x $f; done",
    "LANG=C uv run pytest -q",
    "X=$(ls); cat a",
    # test and [ : a double-quoted operand after a literal operator
    "test -f \"$f\"",
    "[ -f \"$f\" ]",
    "[ ! -f \"$f\" ]",
    "[ -n a -a -f \"$f\" ]",
    "[ a = \"$x\" ]",
]


@pytest.mark.parametrize("command", F3_NONE_ROWS)
def test_f3_an_unresolved_argument_to_a_head_that_cannot_write_is_still_read_only(command):
    assert classify_bash_command(command) == "none", command
    assert bash_write_offset(command) is None, command


# --------------------------------------------------------------------------- F4: a loop variable is opaque

F4_SOURCE_ROWS = [
    "IFS=X; for f in tests/ok.pyXsrc/shop/cart.py; do echo hi | tee $f; done",
    "IFS=: ; for f in tests/test_a.py:other; do echo hi | tee $f; done",
    "IFS=' ' read -r IFS <<< X; for f in tests/ok.pyXsrc/shop/cart.py; do echo hi | tee $f; done",
    "for f in tests/ok.pyXsrc/shop/cart.py; do IFS=X; echo hi | tee $f; done",
    "for f in tests/ok.pyXsrc/shop/cart.py; do IFS=X echo hi | tee $f; done",
    "for f in tests/ok.pyXsrc/shop/cart.py; do (IFS=X; echo hi | tee $f); done",
    "for f in tests/ok.pyXsrc/shop/cart.py; do IFS=X; cp x $f; done",
    "for f in 'tests/test_a.pyXsrc/shop/cart.py'; do IFS=X; echo hi > $f; done",
    "for f in 'tests/test_a.py src/shop/cart.py'; do echo hi | tee $f; done",
    "for f in a; do echo x > tests/$f; done",
    "for f in a b; do echo x >> tests/test_$f.py; done",
    "for f in a b; do rm tests/$f; done",
    "for f in a; do for g in b; do echo x > tests/$f/$g; done; done",
    "for f in a b; do echo x > tests/${f}; done",
    "for f in a b; do echo x > \"tests/$f\"; done",
    "for f in a; do tee $f < /dev/null; done",
    "for f in tests/x.py; do cp x $f; done",
    "for f in tests/x; do echo hi > $f; done",
    "set -- a b; for f in tests/x; do echo hi > $f; done",
    "for f in a; do cat >> tests/test_$f.py <<'EOF'\nx\nEOF\ndone",
    "for f in a; do echo x > tests/literal.py; echo y > tests/$f; done",
]


@pytest.mark.parametrize("command", F4_SOURCE_ROWS)
def test_f4_a_write_whose_target_contains_an_expansion_is_source(command):
    assert classify_bash_command(command) == "source", command


F4_TESTS_ROWS = [
    "for f in a; do echo x > tests/literal.py; done",
    "for f in a b; do echo x >> tests/test_cart.py; done",
    "for f in a; do cat $f; done > tests/out",
    "for f in a; do cat $f; echo x > tests/test_a.py; done",
]


@pytest.mark.parametrize("command", F4_TESTS_ROWS)
def test_f4_a_write_to_a_literal_tests_path_inside_a_loop_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# --------------------------------------------------------------------------- F5: cd into src

F5_SOURCE_ROWS = [
    "cd s''rc/shop; cat > test_cart.py <<'EOF'\nx\nEOF",
    "cd s''rc/shop && tee test_x.py",
    "cd s''rc/shop; echo hi > conftest.py",
    "cd s\\rc/shop; echo hi > conftest.py",
    "(cd s''rc/shop; echo hi > conftest.py)",
    "cd $(echo s)$(echo rc)/shop; echo hi > conftest.py",
    "for d in s; do for e in rc; do cd $d$e/shop; echo hi > conftest.py; done; done",
    "for f in tests/x; do cd ..; echo hi > $f; done",
    "for f in tests/x.py; do cd src; echo hi > $f; done",
    "for f in test_x.py; do cd s''rc/shop; tee $f; done",
    "cd src; echo hi > conftest.py",
    "cd src/shop && tee test_x.py",
    "cd; echo hi > tests/x",
    "cd -; echo hi > tests/x",
    "cd ..; echo hi > tests/x",
    "cd ../tests && echo hi > conftest.py",
    "cd \"tests\"; echo hi > conftest.py",
    "cd 'tests'; echo hi > conftest.py",
    "cd s*/shop; echo hi > conftest.py",
    "cd s?c; echo hi > conftest.py",
    "cd ~; echo hi > conftest.py",
    "cd -P tests; echo hi > conftest.py",
    "CDPATH=src; cd shop; echo hi > conftest.py",
    "CDPATH=/w/s''rc; cd shop; echo hi > conftest.py",
    "env CDPATH=/w/s''rc cd shop; echo hi > conftest.py",
    "cd tests/../src; echo hi > conftest.py",
    "cd a/src/b; echo hi > conftest.py",
    "pushd src; echo hi > conftest.py",
    "pushd tests; echo hi > conftest.py",
    "cd tests; cd ..; echo hi > conftest.py",
    "bash -c 'cd s\"\"rc; echo hi > conftest.py'",
    "eval 'cd s\"\"rc'; echo hi > conftest.py",
    "eval \"cd $x\"; echo hi > conftest.py",
    "cd tests; cp x /tmp/y",
]


@pytest.mark.parametrize("command", F5_SOURCE_ROWS)
def test_f5_in_a_call_with_a_write_a_cd_target_must_be_a_plain_literal_path_outside_src(command):
    assert classify_bash_command(command) == "source", command


F5_TESTS_ROWS = [
    "cd /w/repo && echo x > tests/x",
    "cd /work/shop && cat >> tests/test_cart.py <<'EOF'\nx\nEOF",
    "cd tests && echo x > conftest.py",
    "cd tests/unit && echo x > test_a.py",
    "cd /w/repo; cd tests; echo x > conftest.py",
    "cd ./tests && echo x > conftest.py",
]


@pytest.mark.parametrize("command", F5_TESTS_ROWS)
def test_f5_a_cd_to_a_plain_literal_path_keeps_a_tests_write_tests(command):
    assert classify_bash_command(command) == "tests", command


F5_NONE_ROWS = [
    "cd s''rc/shop; cat a",
    "cd src && ls",
    "cd ..; ls",
    "cd; ls",
    "cd -; ls",
    "cd /w/repo && for f in a; do cat $f; done",
    "cd tests && cat conftest.py",
]


@pytest.mark.parametrize("command", F5_NONE_ROWS)
def test_f5_a_cd_in_a_call_with_only_read_only_commands_stays_none(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- the colon and loop controls

COLON_SOURCE_ROWS = [
    ": $(ls)",
    ": $x",
    ": ${x:=y}",
    ": \"$x\"",
    ": 'a b'",
    ": `ls`",
    ": a[1]",
    ": $((x=1))",
    "while :; do break $n; done",
    "while :; do continue \"$n\"; done",
    "while :; do break 'x'; done",
    "until false; do : a[$(ls)]; done",
]


@pytest.mark.parametrize("command", COLON_SOURCE_ROWS)
def test_the_colon_break_and_continue_take_only_plain_literal_arguments(command):
    assert classify_bash_command(command) == "source", command


COLON_NONE_ROWS = [
    ":",
    ": a b",
    ": a_b.c/d=e-f",
    "while :; do break; done",
    "while :; do break 2; done",
    "while true; do cat a; continue; done",
    "until false; do :; done",
    "for f in a; do : x; done",
]


@pytest.mark.parametrize("command", COLON_NONE_ROWS)
def test_the_colon_break_and_continue_with_plain_literal_arguments_are_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- arithmetic contexts

ARITHMETIC_SOURCE_ROWS = [
    "x='a[$(cp x src/y)]'; ((n=x))",
    "((n=n+1))",
    "(( 1 ))",
    "for f in a; do ((n=n+1)); echo $n; done",
    "echo $((1+2))",
    "x='a[$(cp x src/y)]'; echo $((n=x))",
    "x='a[$(cp x src/y)]'; echo $[n=x]",
    "echo $[1+2]",
    "echo \"$[1+2]\"",
    "x='a[$(cp x src/y)]'; echo ${y:x}",
    "echo ${y:1:2}",
    "echo \"${y:1}\"",
    "echo ${a[$x]}",
    "echo ${!x}",
    "echo ${x@P}",
    "x='$(cp x src/y)'; echo ${x@P}",
]


@pytest.mark.parametrize("command", ARITHMETIC_SOURCE_ROWS)
def test_an_arithmetic_context_that_can_run_a_substitution_is_source(command):
    assert classify_bash_command(command) == "source", command


ARITHMETIC_NONE_ROWS = [
    "echo ${f}",
    "echo \"${f}\"",
    "echo ${f%.py}",
    "echo ${f:-default}",
    "echo ${f/a/b}",
    "for f in a; do echo ${f%.py}; done",
    "( cat a )",
    "( ( cat a ) )",
]


@pytest.mark.parametrize("command", ARITHMETIC_NONE_ROWS)
def test_a_parameter_expansion_that_does_no_arithmetic_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- brace expansion (same family as F3)

BRACE_SOURCE_ROWS = [
    "sed {-i,s/a/b/} src/shop/cart.py",
    "sed {-i,'s/a/b/'} f",
    "sed {-i,\"s/a/b/\"} f",
    "find src/shop {-delete,-name}",
    "sort {-o,src/x} src/y",
    "sed -n {1..3}p f",
    "awk {-i,inplace} f",
    "git log {-1,-2}",
    "uv run pytest {-x,-q}",
]


@pytest.mark.parametrize("command", BRACE_SOURCE_ROWS)
def test_an_unquoted_brace_expansion_argument_is_an_unresolved_expansion(command):
    assert classify_bash_command(command) == "source", command


BRACE_NONE_ROWS = [
    "echo {a,b}",
    "cat src/{a,b}.py",
    "ls {a,b}",
    "echo {1..3}",
    "awk '{print $1, $2}' f",
    "grep -E 'a{1,3}' f",
    "jq '{a: 1, b: 2}' f",
    "echo '{a,b}'",
    "sed -n '{p}' f",
    "sed 's/a{1,2}/b/' f",
    "find . -name x -print",
]


@pytest.mark.parametrize("command", BRACE_NONE_ROWS)
def test_a_quoted_brace_or_a_brace_argument_of_a_safe_head_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- the real read-only loops

AUDITED = (
    'cd /w/repo && for f in pyproject.toml src/shop/*.py tests/*.py; do echo "=== $f"; cat $f; done;'
    " uv run pytest -q 2>&1 | tail -15"
)
REAL_LOOPS = [
    AUDITED,
    'cd /w/repo && git diff && for f in src/greeter/shout.py tests/test_shout.py; do echo "=== $f"; cat $f; done;'
    " uv run pytest -q 2>&1 | tail -15",
    'git status --short | head; for f in src/greeter/*.py tests/*.py; do echo "=== $f"; cat $f; done',
    'cd /w/repo && for f in pyproject.toml docs/plan.md src/shop/cart.py; do echo "--- $f"; cat $f; done',
]


@pytest.mark.parametrize("command", REAL_LOOPS)
def test_the_real_read_only_inspection_loops_stay_none(command):
    assert classify_bash_command(command) == "none", command
    assert bash_write_offset(command) is None, command


# --------------------------------------------------------------------------- bounded time (heredoc memoisation)

LIMIT = 0.5


def _timed(command: str) -> float:
    from evals._harness import bash_classify

    bash_classify._top_effect.cache_clear()
    started = time.perf_counter()
    classify_bash_command(command)
    bash_write_offset(command)
    return time.perf_counter() - started


def test_a_heredoc_body_piped_through_6000_shells_is_not_a_script_for_the_later_shells():
    # A heredoc body reaches an interpreter only directly or through a bare ``cat`` (#1129): the second shell of
    # ``bash | bash`` reads the first one's output, not the body, so it has no script and the call is ``source``.
    body = "echo hi\n" * 4300
    command = "cat <<'EOF' | " + "bash | " * 5999 + "bash\n" + body + "EOF"
    assert 70_000 < len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "source"


def test_a_heredoc_body_piped_through_6000_bare_cats_is_analysed_once():
    body = "echo hi\n" * 4300
    command = "cat <<'EOF' | " + "cat | " * 5999 + "bash\n" + body + "EOF"
    assert 70_000 < len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "none"


def test_a_77_kb_heredoc_body_piped_through_a_hundred_shells_takes_well_under_half_a_second():
    body = "echo hello world\n" * 4500
    command = "cat <<'EOF' | " + "bash | " * 99 + "bash\n" + body + "EOF"
    assert 70_000 < len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT


def test_a_heredoc_body_piped_through_python_shells_is_not_a_script_for_the_later_ones():
    body = "print(1)\n" * 4000
    command = "cat <<'EOF' | " + "python3 | " * 3000 + "python3\n" + body + "EOF"
    assert len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "source"


def test_a_heredoc_body_piped_through_bare_cats_into_python_is_analysed_once():
    body = "print(1)\n" * 4000
    command = "cat <<'EOF' | " + "cat | " * 3000 + "python3\n" + body + "EOF"
    assert len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "none"


def test_a_write_in_a_heredoc_body_is_still_found_through_the_pipeline():
    command = "cat <<'EOF' | bash | cat\ncp a src/b\nEOF"
    assert classify_bash_command(command) == "source"
    many = "cat <<'EOF' | " + "bash | " * 59 + "bash\ncp a src/b\nEOF"
    assert classify_bash_command(many) == "source"


def test_a_pipeline_fed_by_more_heredocs_than_the_limit_fails_closed():
    one = "cat <<'E{n}' | "
    few = "".join(one.format(n=n) for n in range(10)) + "bash\n" + "".join(f"echo {n}\nE{n}\n" for n in range(10))
    assert classify_bash_command(few) == "none"
    many = "".join(one.format(n=n) for n in range(80)) + "bash\n" + "".join(f"echo {n}\nE{n}\n" for n in range(80))
    assert classify_bash_command(many) == "source"
