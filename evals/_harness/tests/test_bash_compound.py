"""Shell compound constructs in ``classify_bash_command``.

The first owner-audited hand-run of the redesigned ``T`` fixture found a read-only inspection call,
``cd /w/repo && for f in ...; do echo "=== $f"; cat $f; done; uv run pytest -q 2>&1 | tail -15``,
scored as a SOURCE write: ``for`` was an unknown head. A shell compound whose every simple command is
read-only is read-only, and a write anywhere inside one classifies exactly as the same write does
outside it (worst of its parts: ``source`` > ``tests`` > ``none``).

Structured: ``for/while/until ... do ... done``, ``if ... then ... [elif ...] [else ...] fi``, ``{ ...; }``,
``( ... )`` and the negation word ``!``. Fail closed (``source``): ``case``, ``select``, function
definitions, ``coproc``, ``time``-wrapped compounds, unbalanced or mismatched openers and closers,
a reserved word where the grammar does not allow it, nesting past ``_MAX_COMPOUND_DEPTH`` (32).
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

from evals._harness.bash_classify import BASH_COMMAND_CAP, bash_write_offset, classify_bash_command

HERE = Path(__file__).resolve().parent

AUDITED = (
    'cd /w/repo && for f in pyproject.toml src/shop/*.py tests/*.py; do echo "=== $f"; cat $f; done;'
    " uv run pytest -q 2>&1 | tail -15"
)

# --------------------------------------------------------------------------- read-only compounds

NONE_ROWS = [
    AUDITED,
    "for f in src/*.py; do wc -l $f; done",
    "for f in a b c; do echo $f; done",
    "if [ -f x ]; then cat x; fi",
    "if grep -q x y; then echo yes; else echo no; fi",
    "{ cat a; cat b; }",
    "( cd src && ls )",
    "for f in tests/*.py; do cat $f; done | tail -5",
    "for a in 1 2; do for b in 3 4; do echo $a $b; done; done",
    "for f in a b; do cat $f; done 2>&1 | tail",
    "X=1; cat a",
    "while :; do break; done",
    # the other forms the grammar names
    "until false; do :; done",
    "if ! grep -q x y; then echo no; fi",
    "if grep -q a f; then echo 1; elif grep -q b f; then echo 2; elif grep -q c f; then echo 3; else echo 4; fi",
    "! grep -q x y",
    "for f in a; do cat $f; done >/dev/null",
    "for f in a; do cat $f; done 2>/dev/null",
    "for f in a; do cat $f; done > /dev/stderr",
    "{ cat a; } 2>&1 | tail -3",
    "( ls ) | wc -l",
    "( ls ) 2>&1",
    "{ cat a; cat b; } < input",
    "for f in a; do cat $f; done < input",
    "for f in a b; do\n  cat $f\ndone",
    "for f in a b # a comment\ndo\n  cat $f # another\ndone",
    "for f in a b\ndo cat $f; done",
    "for f; do cat $f; done",
    "for f in do done then fi; do cat $f; done",
    "while true; do cat a; continue; done",
    "while cat a; do cat b; done",
    "if cat a | grep -q x; then cat b; fi",
    "X=1 Y=2; cat a",
    "X=$(ls); cat a",
    "for f in $(ls); do cat $f; done",
    "for f in a; do cat $f; done; for g in b; do cat $g; done",
    "bash -c 'for f in a; do cat $f; done'",
    "echo $(for f in a; do cat $f; done)",
    "cd /w/repo && for f in a; do cat $f; done; uv run pytest -q 2>&1 | tail -15",
    "{ { cat a; }; }",
    "( ( cat a ) )",
    "if true; then if true; then cat a; fi; fi",
    ": ",
    "while true; do break 2; done",
    "while true; do case_name=1; echo $case_name; done",
    "echo done; echo fi; echo '}' ; echo do",
]


@pytest.mark.parametrize("command", NONE_ROWS)
def test_a_compound_whose_simple_commands_are_all_read_only_is_none(command):
    assert classify_bash_command(command) == "none", command
    assert bash_write_offset(command) is None, command


# --------------------------------------------------------------------------- a write inside stays a write

SOURCE_ROWS = [
    "for f in src/*.py; do sed -i 's/a/b/' $f; done",
    "for f in a b; do cp $f /tmp/x; done",
    "if true; then cp a b; fi",
    "while true; do rm -f x; done",
    "{ cp a b; }",
    "( rm x )",
    "while cp a b; do :; done",
    "until cp a b; do :; done",
    "if cp a b; then echo ok; fi",
    "if true; then echo ok; elif cp a b; then echo no; fi",
    "if true; then echo ok; else cp a b; fi",
    "if ! cp a b; then echo no; fi",
    "for f in a; do cat $f; done > src/out",
    "if true; then cat a; fi >> src/y",
    "{ cat a; } > notes.txt",
    "( cat a ) >> src/y",
    "for f in a; do cat $f; done; cp a b",
    "cp a b; for f in a; do cat $f; done",
    "for f in a; do for g in b; do cp $f $g; done; done",
    "for f in a; do ( cp $f b ); done",
    "for f in $(cp a b); do cat $f; done",
    "for f in `cp a b`; do cat $f; done",
    "for f in a; do echo $(cp a b); done",
    "while read l; do echo $l > out; done < f",
    "for f in a; do echo x > $f; done",
    "for f in tests/*.py; do rm $f; done",
    "for c in rm; do $c x; done",
    "$CMD",
    "X=$(cp a b)",
    "X=`cp a b`; cat a",
    "[[ $(cp a b) ]]",
    "[[ -f <(cp a b) ]]",
    "[[ -f a ]] > out",
    "for f in a; do echo x > tests/$f; done; cp a b",
    "for f in a; do cat $f; done > tests/x; cp a /tmp/x",
    "for f in ../src/x; do echo x > tests/$f; done",
    "for f in ..; do echo x > tests/$f/y; done",
    # the no-op and the builtins keep their redirects
    ": > src/x",
    ": > notes.txt",
    ": $(cp a b)",
]


@pytest.mark.parametrize("command", SOURCE_ROWS)
def test_a_write_inside_a_compound_is_a_source_write(command):
    assert classify_bash_command(command) == "source", command
    assert bash_write_offset(command) is not None, command


TESTS_ROWS = [
    "for f in a; do echo x > tests/literal.py; done",
    "{ cat a; } > tests/x",
    "if true; then echo x > tests/x; fi",
    "( echo x > tests/x )",
    "while true; do echo x >> tests/x; done",
    "for f in a; do cat $f; done > tests/out",
    "if true; then cat a; fi >> tests/y",
    "( cat a ) > tests/x",
    "for f in a; do cat $f; done 2>&1 > tests/out",
    "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nfor f in a; do cat $f; done",
    "for f in a; do cat >> tests/test_a.py <<'EOF'\nx\nEOF\ndone",
]


@pytest.mark.parametrize("command", TESTS_ROWS)
def test_a_compound_whose_only_writes_are_literal_tests_paths_is_a_tests_write(command):
    assert classify_bash_command(command) == "tests", command
    assert bash_write_offset(command) is not None, command


def test_a_src_token_in_a_write_capable_compound_is_source_and_in_a_read_only_one_is_not():
    assert classify_bash_command("for f in src/a; do echo x > tests/$f; done") == "source"
    assert classify_bash_command("for f in src/a; do cat $f; done") == "none"
    assert classify_bash_command("for f in a; do echo x > tests/$f; done; ls src") == "source"


def test_the_offset_inside_a_compound_is_where_the_first_write_capable_simple_command_starts():
    command = "for f in a; do cat $f; cp $f b; done; cp x y"
    assert bash_write_offset(command) == command.index("cp $f")
    command = "for f in a; do cat $f; done > out"
    assert bash_write_offset(command) is not None
    assert bash_write_offset("for f in a; do cat $f; done") is None


# --------------------------------------------------------------------------- redirects on the construct

REDIRECT_ROWS = [
    ("for f in a; do cat $f; done > src/out", "source"),
    ("{ cat a; } > tests/x", "tests"),
    ("if true; then cat a; fi >> src/y", "source"),
    ("for f in a; do cat $f; done < input", "none"),
    ("( cat a ) >> src/y", "source"),
    ("( cat a ) >> tests/y", "tests"),
    ("{ cat a; } >| tests/y", "tests"),
    ("{ cat a; } &> src/y", "source"),
    ("for f in a; do cat $f; done 2>&1 | tail", "none"),
    ("for f in a; do cat $f; done 2>/dev/null", "none"),
    ("for f in a; do cat $f; done >&2", "none"),
    ("for f in a; do cat $f; done 2> err.txt", "source"),
    ("for f in a; do cat $f; done | tee out.txt", "source"),
    ("while true; do cat a; done < notes.txt > out.txt", "source"),
    ("while true; do cat a; done < notes.txt > tests/out.txt", "tests"),
]


@pytest.mark.parametrize(("command", "expected"), REDIRECT_ROWS)
def test_a_redirect_on_the_construct_is_read_like_one_on_a_simple_command(command, expected):
    assert classify_bash_command(command) == expected, command


# --------------------------------------------------------------------------- fail closed

FAIL_CLOSED_ROWS = [
    "case x in a) cat f;; esac",
    "case x in esac",
    "f() { cat x; }; f",
    "f() { cat x; }",
    "function f { cat x; }",
    "function f() { cat x; }; f",
    "for f in a; do cat $f",
    "done",
    "fi",
    "then",
    "do",
    "else",
    "elif",
    "}",
    ")",
    "in",
    "coproc cat",
    "select x in a b; do cat $x; done",
    "time for f in a; do cat $f; done",
    "time { cat a; }",
    "time ( cat a )",
    "for ((i=0; i<3; i++)); do echo $i; done",
    "for f in a; do cat $f; fi",
    "if true; then cat a; done",
    "while true; do cat a; }",
    "{ cat a; )",
    "( cat a; }",
    "( cat a",
    "{ cat a",
    "{ cat a }",
    "if true; then cat a",
    "if true; cat a; fi",
    "if true; then; fi",
    "if ; then cat a; fi",
    "if true; then cat a; else cat b; else cat c; fi",
    "if true; then cat a; else cat b; elif true; then cat c; fi",
    "if true; then cat a; fi fi",
    "for f in a; do done",
    "for f in a; do cat $f; done done",
    "for f in a; cat $f; do cat $f; done",
    "for f in a; ; do cat $f; done",
    "for f in a | b; do cat $f; done",
    "for f in a > b; do cat $f; done",
    "for f in a && b; do cat $f; done",
    "for 1x in a; do cat; done",
    "for $f in a; do cat; done",
    "for f; ; do cat; done",
    "for f in a; do cat $f; done cat b",
    "{ cat a; } cat b",
    "( cat a ) cat b",
    "fi cat b",
    "cat a; done",
    "cat a )",
    "echo a (b)",
    "x=(a b)",
    "while true do cat a; done",
    "while true; do cat a; done; done",
    "cat a;; cat b",
    "{ cat a; }; }",
    "[[ -f a",
    "[[ -f a ; ]]",
    "[[ -f a\n]]",
    "[[ -f a ]] cat b",
    "[[ -f a ]] ]]",
    "esac",
    "select",
    "function",
    "for f in a; do; cat $f; done",
    "{ ; cat a; }",
    "if true; then; cat a; fi",
    "( )",
    "{ }",
    "if true; then cat a; done; fi",
    "while true; do cat a; fi; done",
    "{ cat a; done; }",
    "if true; then cat a; then cat b; fi",
    "for f in a\ncat $f\ndo cat $f; done",
    "for f in a; ; do cat $f; done",
]


@pytest.mark.parametrize("command", FAIL_CLOSED_ROWS)
def test_a_construct_that_is_not_confidently_structured_is_source(command):
    assert classify_bash_command(command) == "source", command
    assert bash_write_offset(command) == 0, command


def test_a_quoted_or_escaped_reserved_word_is_not_a_reserved_word():
    assert classify_bash_command("for f in a; do cat $f; 'done'") == "source"
    assert classify_bash_command("for f in a; do cat $f; \\done") == "source"
    assert classify_bash_command("\"for\" f in a; do cat $f; done") == "source"
    assert classify_bash_command("echo 'done' \"fi\" \\}") == "none"


def test_a_reserved_word_in_argument_position_is_a_plain_word():
    assert classify_bash_command("echo for in do done if then fi { } !") == "none"
    assert classify_bash_command("grep -n do src/x") == "none"
    assert classify_bash_command("cat done") == "none"


def _braces(depth: int) -> str:
    return "{ " * depth + "cat a" + "; }" * depth


def _parens(depth: int) -> str:
    return "( " * depth + "cat a" + " )" * depth


def _fors(depth: int) -> str:
    return "for f in a; do " * depth + "cat $f" + "; done" * depth


def _ifs(depth: int) -> str:
    return "if true; then " * depth + "cat a" + "; fi" * depth


@pytest.mark.parametrize("build", [_braces, _parens, _fors, _ifs])
def test_nesting_to_the_depth_limit_is_structured_and_one_past_it_is_source(build):
    assert classify_bash_command(build(32)) == "none"
    assert classify_bash_command(build(33)) == "source"
    assert classify_bash_command(build(1000)) == "source"


def test_a_write_at_the_depth_limit_is_still_a_write():
    assert classify_bash_command(_braces(32).replace("cat a", "cp a b")) == "source"
    assert classify_bash_command(_fors(32).replace("cat $f", "echo x > tests/$f")) == "source"


def test_mixed_nesting_counts_every_open_frame():
    assert classify_bash_command("{ ( " * 16 + "cat a" + " ); }" * 16) == "none"
    assert classify_bash_command("{ ( " * 17 + "cat a" + " ); }" * 17) == "source"


def test_the_over_cap_rule_still_holds_for_a_compound():
    body = "for f in a; do cat $f; done\n"
    command = body * (BASH_COMMAND_CAP // len(body))
    assert len(command) <= BASH_COMMAND_CAP
    assert classify_bash_command(command) == "none"
    assert classify_bash_command(command + "x" * (BASH_COMMAND_CAP - len(command) + 1)) == "source"


# --------------------------------------------------------------------------- the wrapper guard

WRAPPERS = {
    "for": lambda command: f"for x in 1; do {command}\ndone",
    "if": lambda command: f"if true; then {command}\nfi",
    "brace": lambda command: "{ " + command + "\n}",
    "subshell": lambda command: "( " + command + "\n)",
}


def _marks(function):
    return [mark for mark in getattr(function, "pytestmark", []) if mark.name == "parametrize"]


def _table_rows(module_file: str) -> list[str]:
    """Every command string a module's parametrized tests feed ``classify_bash_command``.

    The module is loaded from its file and the rows are read off its ``parametrize`` marks, so a row
    added to an existing table later is guarded without anyone remembering to list it here.
    """
    path = HERE / module_file
    spec = importlib.util.spec_from_file_location(f"_rows_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows: list[str] = []
    for function in vars(module).values():
        for mark in _marks(function):
            names = [name.strip() for name in mark.args[0].split(",")] if isinstance(mark.args[0], str) else list(mark.args[0])
            if "command" not in names:
                continue
            position = names.index("command")
            for value in mark.args[1]:
                if isinstance(value, str):
                    rows.append(value)
                elif isinstance(value, (tuple, list)) and position < len(value) and isinstance(value[position], str):
                    rows.append(value[position])
    return rows


def _guarded_rows() -> dict[str, str]:
    """``{command: class}`` for every row of the three classifier tables whose class is fixed today."""
    rows: dict[str, str] = {}
    for module_file in ("test_bash_writes.py", "test_bash_allowlist.py", "test_bash_hardening.py"):
        for command in _table_rows(module_file):
            if command.strip():
                rows[command] = classify_bash_command(command)
    # the label tables of test_bash_allowlist.py name a row's command in a (label, command) pair
    return rows


GUARDED = _guarded_rows()
# `source` rows that are `source` only because the construct is broken stay `source` wrapped; the
# classes below are read off the UNWRAPPED command, so any change a wrapper makes is a regression.


def test_the_wrapper_guard_covers_the_existing_tables():
    classes = list(GUARDED.values())
    assert classes.count("source") >= 500
    assert classes.count("tests") >= 30
    assert classes.count("none") >= 130
    assert set(classes) == {"none", "tests", "source"}


@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_wrapping_an_existing_row_in_a_compound_never_changes_its_class(wrapper):
    wrap = WRAPPERS[wrapper]
    changed = {command: (before, classify_bash_command(wrap(command))) for command, before in GUARDED.items()}
    changed = {command: pair for command, pair in changed.items() if pair[0] != pair[1]}
    assert not changed, changed


@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_wrapping_a_write_row_keeps_it_write_capable_at_an_offset(wrapper):
    wrap = WRAPPERS[wrapper]
    for command, before in GUARDED.items():
        if before == "none":
            assert bash_write_offset(wrap(command)) is None, command
        else:
            assert bash_write_offset(wrap(command)) is not None, command


def test_a_wrapped_row_is_classified_through_two_wrappers_too():
    for command, before in list(GUARDED.items())[::7]:
        both = WRAPPERS["for"](WRAPPERS["subshell"](WRAPPERS["brace"](command)))
        assert classify_bash_command(both) == before, command


# --------------------------------------------------------------------------- bounded time

LIMIT = 0.5


def _timed(command: str) -> float:
    started = time.perf_counter()
    classify_bash_command(command)
    bash_write_offset(command)
    return time.perf_counter() - started


def test_a_thousand_nested_for_loops_take_well_under_half_a_second():
    command = "for f in a; do " * 1000 + "cat $f" + "; done" * 1000
    assert len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT


def test_twenty_thousand_do_and_done_tokens_in_a_word_list_take_well_under_half_a_second():
    command = "for x in " + "do done " * 10_000 + "; do cat $x; done"
    assert len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "none"


def test_twenty_thousand_stray_do_and_done_tokens_take_well_under_half_a_second():
    command = "do done " * 10_000
    assert len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "source"


def test_a_long_run_of_closed_loops_is_one_pass():
    command = "for a in b;do :;done;" * 4700
    assert len(command) < BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "none"


@pytest.mark.parametrize(
    "command",
    [
        "{ " * 40_000,
        "( " * 40_000,
        "} " * 40_000,
        "fi " * 33_000,
        "if " * 33_000,
        "! " * 50_000,
        "[[ " * 33_000,
        "for f in " * 11_000,
        "while " * 16_000,
        "then do else elif " * 5_000,
        "[[ " + "a " * 49_000 + "]]",
        "[[ " + "( " * 49_000 + "]]",
    ],
)
def test_adversarial_compound_shapes_take_well_under_half_a_second(command):
    assert len(command) <= BASH_COMMAND_CAP
    assert _timed(command) < LIMIT
