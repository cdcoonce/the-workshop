"""Tests for the Bash-aware write detection in ``evals._harness.matchers``.

``bash_write_offset`` / ``bash_may_write_under`` read a Bash command's text and answer
"might this write a file under a path prefix?". The rule over-approximates on purpose: a
read-only call counted as a write can only turn a hit into a miss, never the reverse.
``test_failed_before_first_source_write`` is the ordering predicate built on it, and the old
Edit/Write-only ``test_failed_before_first_source_edit`` keeps its meaning for every other caller.
"""

from __future__ import annotations

import pytest

from evals._harness.matchers import (
    bash_may_write_under,
    bash_write_offset,
    is_possible_write_under,
    test_failed_before_first_source_edit as _failed_before_first_source_edit,
    test_failed_before_first_source_write as _failed_before_first_source_write,
)
from evals._harness.transcript import ToolCallEvent, ToolResult

RED = "F\nFAILED tests/test_cart.py::test_x - assert 1 == 2\n1 failed, 4 passed in 0.02s\n"
GREEN = ".....\n5 passed in 0.01s\n"

PYTHON_REWRITE = (
    "python3 - <<'EOF'\n"
    "p='src/shop/cart.py'\n"
    "s=open(p).read()\n"
    "s=s.replace('a','b')\n"
    "open(p,'w').write(s)\n"
    "EOF"
)
TEST_APPEND = "cat >> tests/test_cart.py <<'EOF'\n\n\ndef test_new():\n    assert True\nEOF"


def _event(
    name: str,
    tool_input: dict,
    ordinal: int,
    *,
    content: str | None = None,
) -> ToolCallEvent:
    result = None if content is None else ToolResult(content=content, is_error=False)
    return ToolCallEvent(name=name, input=tool_input, result=result, ordinal=ordinal, timestamp=None)


def _bash(command: str, ordinal: int, content: str | None = None) -> ToolCallEvent:
    return _event("Bash", {"command": command}, ordinal, content=content)


# --------------------------------------------------------------------------- detection table


@pytest.mark.parametrize(
    ("command", "prefix"),
    [
        # heredoc and redirection writes
        (TEST_APPEND, "tests/"),
        ("cd /work/shop && " + TEST_APPEND, "tests/"),
        ("cat > src/shop/cart.py <<'EOF'\nx = 1\nEOF", "src/"),
        ("echo hi >> src/shop/cart.py", "src/"),
        ("echo hi >src/shop/cart.py", "src/"),
        ("echo hi > ./src/shop/cart.py", "src/"),
        ("echo hi &> src/shop/cart.py", "src/"),
        ("echo hi >| src/shop/cart.py", "src/"),
        ("echo hi 2> src/err.log", "src/"),
        ("uv run pytest 2>&1 | tee src/run.log", "src/"),
        # python / node / ruby snippets
        (PYTHON_REWRITE, "src/"),
        ("python3 -c \"open('src/x.py', 'w').write('1')\"", "src/"),
        ("python3 -c \"open('src/x.py', mode='a').write('1')\"", "src/"),
        ("python3 -c \"f = open('src/x.py', 'w'); f.close()\"", "src/"),
        ("python3 -c \"f = open('src/x.py', mode='a'); f.close()\"", "src/"),
        ("python3 -c \"from pathlib import Path; Path('src/x.py').write_text('1')\"", "src/"),
        ("python3 -c \"from pathlib import Path; Path('src/x.py').write_bytes(b'1')\"", "src/"),
        ("python3 -c \"from pathlib import Path; Path('src/x.py').open('w')\"", "src/"),
        ("python3 -c \"import os; os.rename('src/a.py', 'src/b.py')\"", "src/"),
        ("python3 -c \"import shutil; shutil.copy('a.py', 'src/b.py')\"", "src/"),
        ("python3 -c \"import os; os.remove('src/a.py')\"", "src/"),
        ("node -e \"require('fs').writeFileSync('src/x.js','1')\"", "src/"),
        ("ruby -e \"File.write('src/x.rb', '1')\"", "src/"),
        # absolute and nested paths
        ("python3 -c \"open('/tmp/w/src/shop/cart.py','w').write('x')\"", "src/"),
        ("cat > /private/tmp/scratchpad/x/src/shop/cart.py <<'EOF'\nx\nEOF", "src/"),
        # in-place editors
        ("sed -i 's/a/b/' src/shop/cart.py", "src/"),
        ("sed -i '' 's/a/b/' src/shop/cart.py", "src/"),
        ("sed -i.bak 's/a/b/' src/shop/cart.py", "src/"),
        ("sed -ni 's/a/b/p' src/shop/cart.py", "src/"),
        ("sed -E -i 's/a/b/' src/shop/cart.py", "src/"),
        ("sed --in-place 's/a/b/' src/shop/cart.py", "src/"),
        ("sed --in-place=.bak 's/a/b/' src/shop/cart.py", "src/"),
        ("perl -pi -e 's/a/b/' src/shop/cart.py", "src/"),
        ("perl -i.bak -pe 's/a/b/' src/shop/cart.py", "src/"),
        # tee and file-system verbs
        ("tee src/shop/cart.py < new.py", "src/"),
        ("echo x | tee -a src/shop/cart.py", "src/"),
        ("mv src/a.py src/b.py", "src/"),
        ("cp tests/a.py src/a.py", "src/"),
        ("rm src/shop/old.py", "src/"),
        ("rm -rf src/shop/__pycache__", "src/"),
        ("install -m 644 a.py src/a.py", "src/"),
        ("patch src/shop/cart.py fix.diff", "src/"),
        ("touch src/shop/new.py", "src/"),
        ("cd /w && rm src/old.py && uv run pytest", "src/"),
        ("find src -name '*.pyc' -exec rm {} \\; # src/", "src/"),
        ("sudo cp a.py src/a.py", "src/"),
        ("FOO=1 cp a.py src/a.py", "src/"),
        # git
        ("git apply fix.diff && cat src/shop/cart.py", "src/"),
        ("git checkout -- src/shop/cart.py", "src/"),
        ("git checkout HEAD -- src/shop/cart.py", "src/"),
        ("git restore src/shop/cart.py", "src/"),
        ("git stash push src/", "src/"),
        ("git rm src/shop/old.py", "src/"),
        # the same helper, prefix tests/
        ("sed -i 's/a/b/' tests/test_cart.py", "tests/"),
        ("cat > tests/test_new.py <<'EOF'\nx\nEOF", "tests/"),
        ("rm tests/test_old.py", "tests/"),
        # deliberate over-approximation: a write elsewhere plus a read of the prefix
        ("cat tests/a.py > /tmp/out.txt && cat src/shop/cart.py", "src/"),
        ("python3 -c \"import sys; print(1 > 0)\" # reads src/", "src/"),
    ],
)
def test_a_command_that_may_write_under_the_prefix_is_detected(command, prefix):
    assert bash_may_write_under(command, prefix) is True


@pytest.mark.parametrize(
    ("command", "prefix"),
    [
        ("cat src/shop/*.py", "src/"),
        ("cat src/shop/cart.py tests/test_cart.py pyproject.toml", "src/"),
        ("uv run pytest", "src/"),
        ("uv run pytest -q 2>&1 | tail -5", "src/"),
        ("uv run pytest tests/test_cart.py -q 2>&1 | tail -20", "tests/"),
        ("ls src", "src/"),
        ("ls -R src/shop", "src/"),
        ("git status", "src/"),
        ("git status --short | head", "src/"),
        ("git diff HEAD -- src/", "src/"),
        ("git log --oneline -- src/shop/cart.py", "src/"),
        ("git checkout main", "src/"),
        ("git checkout main && cat src/shop/cart.py", "src/"),
        ("grep -rn x src/", "src/"),
        ("grep -rn 'install' src/", "src/"),
        ("grep -rn rm src/shop/cart.py", "src/"),
        ("cat src/shop/cart.py | grep -n patch", "src/"),
        ("grep -n 'def f() -> int' src/shop/cart.py", "src/"),
        ("awk '$1 >= 3' src/shop/data.txt", "src/"),
        ("cat src/shop/cart.py 2>&1", "src/"),
        ("cat src/shop/cart.py >/dev/null", "src/"),
        ("cat src/shop/cart.py > /dev/null 2>&1", "src/"),
        ("cat src/shop/cart.py 2>/dev/null", "src/"),
        ("cat src/shop/cart.py >&2", "src/"),
        ("cat src/shop/cart.py 1>&2", "src/"),
        ("cat src/shop/cart.py >&-", "src/"),
        ("cat src/shop/cart.py > /dev/stderr", "src/"),
        ("head -50 src/shop/cart.py", "src/"),
        ("sed -n '1,20p' src/shop/cart.py", "src/"),
        ("sed -n 's/a/b/p' src/shop/cart.py | grep -i foo", "src/"),
        ("sed --silent -e 'p' src/shop/cart.py", "src/"),
        ("perl -ne 'print if /x/' src/shop/cart.py", "src/"),
        ("python3 -c \"print(open('src/shop/cart.py').read())\"", "src/"),
        ("python3 -c \"print(open('src/shop/cart.py', 'r').read())\"", "src/"),
        ("python3 -c \"print(open('src/shop/cart.py', mode='rb').read())\"", "src/"),
        ("python3 -c \"import sys; sys.path.insert(0, 'src/'); import shop\"", "src/"),
        ("find . -path ./.venv -prune -o -type f -print | head -50; cat src/shop/cart.py", "src/"),
        ("cd /work/shop && cat docs/plan.md", "src/"),
        # a prefix preceded by a word character is some other directory
        ("echo hi > resrc/shop/cart.py", "src/"),
        ("cat >> mysrc/x.py <<'EOF'\nx\nEOF", "src/"),
        ("rm resrc/old.py", "src/"),
        ("rm attests/old.py", "tests/"),
        # a write that never mentions the prefix
        ("echo hi > notes.txt", "src/"),
        ("cat > docs/plan.md <<'EOF'\nx\nEOF", "src/"),
        ("", "src/"),
    ],
)
def test_a_read_only_command_or_another_directory_is_not_a_write_under_the_prefix(command, prefix):
    assert bash_may_write_under(command, prefix) is False


def test_a_prefix_is_matched_per_call_not_in_general():
    command = "sed -i 's/a/b/' src/shop/cart.py"
    assert bash_may_write_under(command, "src/") is True
    assert bash_may_write_under(command, "tests/") is False


def test_the_offset_is_where_the_first_write_indicator_starts():
    command = f"{TEST_APPEND}\nuv run pytest -q"
    offset = bash_write_offset(command, "tests/")
    assert offset is not None
    assert command[offset:].startswith(">>")
    assert offset < command.rfind("pytest")


def test_the_offset_is_the_earliest_of_several_write_indicators():
    command = "echo x > notes.txt && sed -i 's/a/b/' src/x.py"
    assert bash_write_offset(command, "src/") == command.index(">")


def test_the_offset_of_a_write_after_the_test_run_is_after_it():
    command = "uv run pytest -q; sed -i 's/a/b/' src/shop/cart.py"
    offset = bash_write_offset(command, "src/")
    assert offset is not None
    assert offset > command.rfind("pytest")


def test_the_offset_is_none_when_nothing_writes():
    assert bash_write_offset("cat src/shop/cart.py", "src/") is None
    assert bash_write_offset("echo hi > notes.txt", "src/") is None


# --------------------------------------------------------------------------- event helper


def test_only_a_bash_event_can_be_a_possible_write():
    assert is_possible_write_under(_bash("sed -i s/a/b/ src/x.py", 0), "src/") is True
    assert is_possible_write_under(_event("Edit", {"file_path": "src/x.py"}, 0), "src/") is False
    assert is_possible_write_under(_event("Write", {"file_path": "src/x.py", "content": "x"}, 0), "src/") is False
    assert is_possible_write_under(_event("Read", {"file_path": "src/x.py"}, 0), "src/") is False


@pytest.mark.parametrize("tool_input", [{}, {"command": None}, {"command": 3}, {"command": ["cat", ">", "src/x.py"]}, "sed -i src/"])
def test_a_bash_event_without_a_command_string_is_not_a_write(tool_input):
    assert is_possible_write_under(_event("Bash", tool_input, 0), "src/") is False


# --------------------------------------------------------------------------- ordering predicate


def test_a_red_run_in_the_call_that_writes_the_tests_precedes_a_later_source_write():
    events = [
        _bash("cat src/shop/*.py tests/*.py", 0, GREEN),
        _bash(f"{TEST_APPEND}\nuv run pytest -q", 1, RED),
        _bash(f"{PYTHON_REWRITE}\nuv run pytest -q", 2, GREEN),
    ]
    assert _failed_before_first_source_write(events) is True


def test_a_source_write_before_any_failure_is_not_test_first():
    events = [
        _bash(f"{PYTHON_REWRITE}\nuv run pytest -q", 0, GREEN),
        _bash(f"{TEST_APPEND}\nuv run pytest -q", 1, RED),
    ]
    assert _failed_before_first_source_write(events) is False


def test_a_red_result_and_a_source_write_in_one_call_share_an_ordinal_and_are_not_credited():
    events = [_bash(f"{PYTHON_REWRITE}\nuv run pytest -q", 0, RED)]
    assert _failed_before_first_source_write(events) is False
    events = [_bash(f"{TEST_APPEND}\n{PYTHON_REWRITE}\nuv run pytest -q", 0, RED), _bash("uv run pytest -q", 1, GREEN)]
    assert _failed_before_first_source_write(events) is False


def test_a_second_red_in_a_later_call_does_not_rescue_a_source_write_that_came_with_the_first():
    events = [
        _bash(f"{PYTHON_REWRITE}\nuv run pytest -q", 0, RED),
        _bash("uv run pytest -q", 1, RED),
    ]
    assert _failed_before_first_source_write(events) is False


def test_a_call_that_only_reads_the_source_is_not_a_source_write():
    events = [
        _bash("cat src/shop/cart.py; uv run pytest -q 2>&1 | tail -5", 0, RED),
        _bash(PYTHON_REWRITE, 1),
    ]
    assert _failed_before_first_source_write(events) is True


def test_a_write_to_the_tests_is_not_a_source_write():
    events = [
        _bash(TEST_APPEND, 0),
        _bash("uv run pytest -q", 1, RED),
        _bash(PYTHON_REWRITE, 2),
    ]
    assert _failed_before_first_source_write(events) is True


def test_an_edit_tool_source_edit_still_counts_as_a_source_write():
    red = _bash("uv run pytest -q", 0, RED)
    edit = _event("Edit", {"file_path": "src/shop/cart.py"}, 1)
    assert _failed_before_first_source_write([red, edit]) is True
    assert _failed_before_first_source_write([edit, _bash("uv run pytest -q", 2, RED)]) is False


def test_an_edit_tool_edit_of_a_test_file_is_not_a_source_write():
    events = [
        _event("Edit", {"file_path": "tests/test_cart.py"}, 0),
        _bash("uv run pytest -q", 1, RED),
        _event("Edit", {"file_path": "src/shop/cart.py"}, 2),
    ]
    assert _failed_before_first_source_write(events) is True


def test_there_must_be_both_a_red_run_and_a_source_write():
    assert _failed_before_first_source_write([_bash(PYTHON_REWRITE, 0, GREEN)]) is False
    assert _failed_before_first_source_write([_bash("uv run pytest -q", 0, RED)]) is False
    assert _failed_before_first_source_write([]) is False


def test_the_source_prefix_is_a_parameter():
    events = [
        _bash("uv run pytest -q", 0, RED),
        _bash("cat > lib/shop/cart.py <<'EOF'\nx\nEOF", 1),
    ]
    assert _failed_before_first_source_write(events) is False  # no write under src/
    assert _failed_before_first_source_write(events, source_prefix="lib/") is True


def test_the_old_edit_only_predicate_does_not_see_bash_writes():
    # Other callers keep the Edit/Write-only meaning: the Bash source write at ordinal 0 is invisible to it.
    events = [
        _bash(PYTHON_REWRITE, 0),
        _bash("uv run pytest -q", 1, RED),
        _event("Edit", {"file_path": "src/shop/cart.py"}, 2),
    ]
    assert _failed_before_first_source_edit(events) is True
    assert _failed_before_first_source_write(events) is False
