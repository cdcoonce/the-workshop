"""Tests for the Bash-aware write classification in ``evals._harness.matchers``.

``classify_bash_command`` fails closed. A Bash call is ``none`` only when it shows no write
indicator at all; a call with a write indicator is ``tests`` only when it literally names a tests
path and ``src`` appears nowhere in it as a path-ish token, and ``source`` otherwise. A write the
reader cannot place is therefore a source write, which can only cost a T1 hit, never credit one.
``test_failed_before_first_source_write`` is the ordering predicate built on it.
"""

from __future__ import annotations

import time

import pytest

from evals._harness.matchers import (
    BASH_COMMAND_CAP,
    bash_write_offset,
    classify_bash_command,
    classify_write_event,
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


def _event(name: str, tool_input: dict, ordinal: int, *, content: str | None = None) -> ToolCallEvent:
    result = None if content is None else ToolResult(content=content, is_error=False)
    return ToolCallEvent(name=name, input=tool_input, result=result, ordinal=ordinal, timestamp=None)


def _bash(command: str, ordinal: int, content: str | None = None) -> ToolCallEvent:
    return _event("Bash", {"command": command}, ordinal, content=content)


# --------------------------------------------------------------------------- the reviewer's rows

# Every one of these is a write the first version let through (or a write idiom of the same families).
# A write is "source" unless the call names a tests path and has no src token, so each is "source".
SOURCE_ROWS = [
    "sed -i'' 's/a/b/' src/shop/cart.py",
    "sed -i\"\" 's/a/b/' src/shop/cart.py",
    "sed -ri 's/a/b/' src/shop/cart.py",
    "sed -i -e 's/a/b/' src/shop/cart.py",
    "sed -i.bak 's/a/b/' src/shop/cart.py",
    "sed --in-place 's/a/b/' src/shop/cart.py",
    "perl -pi -e 's/a/b/' src/shop/cart.py",
    "perl -0pi -e 's/a/b/' src/shop/cart.py",
    "perl -0777 -pi -e 's/a/b/' src/shop/cart.py",
    "perl -i.bak -pe 's/a/b/' src/shop/cart.py",
    "perl -pi.bak -e 's/a/b/' src/shop/cart.py",
    "ruby -pi -e 'gsub(/a/,\"b\")' src/shop/cart.py",
    "awk -i inplace '{print}' src/shop/cart.py",
    "gawk -i inplace '{print}' src/shop/cart.py",
    "ed -s src/shop/cart.py <<'EOF'\nw\nEOF",
    "ex -sc '%s/a/b/|x' src/shop/cart.py",
    "vim -es -c '%s/a/b/g' -c wq src/shop/cart.py",
    "git apply <<'EOF'\n--- a/src/shop/cart.py\nEOF",
    "git am src.patch",
    "git checkout feature-branch",
    "git cherry-pick abc",
    "git reset --hard HEAD",
    "git revert HEAD",
    "git merge other",
    "git pull",
    "git stash pop",
    "curl -o src/shop/cart.py http://x",
    "wget -O src/shop/cart.py http://x",
    "python3 -c \"import subprocess; subprocess.run(['sed','-i','s/a/b/','src/shop/cart.py'])\"",
    "python3 -c \"import os; fd=os.open('src/shop/cart.py', os.O_WRONLY); os.write(fd,b'x')\"",
    "uv run python - <<'EOF'\nimport pathlib\npathlib.Path('src/shop/cart.py').write_bytes(b'x')\nEOF",
    "node -e \"require('fs').writeFileSync('src/a.js','x')\"",
    "ruff check src/ --fix",
    "ruff check --fix --unsafe-fixes src/",
    "uv run ruff check --fix .",
    "uv run ruff format .",
    "isort src/",
    "python3 -m black src/",
    "python3 -m isort src/shop",
    "echo 'x' | python3 -c \"import sys; open('src/shop/cart.py','w').write(sys.stdin.read())\"",
    "python3 -c \"p='src/shop/cart.py'; f=open(p, 'w'); f.write('x')\"",
    "python3 -c \"p='src/shop/cart.py'; f=open(p, \\\"w\\\")\"",
    "python3 -c \"p='src/shop/cart.py'; f=open(p, 'wb')\"",
    "python3 -c \"p='src/shop/cart.py'; f=open(p, 'w+')\"",
    "python3 -c \"p='src/shop/cart.py'; f=open(p, mode = 'w')\"",
    "python3 -c \"p='src/shop/cart.py'; f=open(p, encoding='utf-8', mode='w')\"",
    "python3 -c \"p='src/shop/cart.py'; f=open(p, 'w', encoding=chr(1))\"",
    "python3 - <<'EOF'\nimport io\nio.open('src/a.py','w').write('x')\nEOF",
    "python3 - <<'EOF'\nimport pathlib\nwith pathlib.Path('src/a.py').open('w') as f:\n    print('x', file=f)\nEOF",
    "python3 - <<'EOF'\nwith open('src/a.py', 'w') as f:\n    print('x', file=f)\nEOF",
    "python3 - <<'EOF'\nfrom pathlib import Path\nPath('src/a.py').open(mode='w')\nEOF",
    "python3 - <<'EOF'\nimport codecs\ncodecs.open('src/a.py','w','utf8')\nEOF",
    "python3 - <<'EOF'\nimport shutil\nshutil.copyfile('/tmp/a','src/a.py')\nEOF",
    "cp -r /tmp/new src/shop",
    "cat /tmp/new.py>src/shop/cart.py",
    "echo hi 1>src/shop/cart.py",
    "cat /tmp/new.py | install -m644 /dev/stdin src/shop/cart.py",
    "exec 3>src/shop/cart.py",
    "{ echo x; } >src/shop/cart.py",
    "mkdir -p src/pkg && echo x > src/pkg/__init__.py",
    "cat <<'EOF' | tee src/shop/cart.py >/dev/null\nx\nEOF",
    "env FOO=1 mv /tmp/c src/shop/cart.py",
    "mv /tmp/c src/shop/cart.py",
    "command mv /tmp/c src/shop/cart.py",
    "sudo -u x cp /tmp/c src/shop/cart.py",
    "python3 -c \"import os; os.system('cp /tmp/c src/shop/cart.py')\"",
    "for f in /tmp/*.py; do cp $f src/shop/; done",
    "git -C . apply x.patch src/",
    "rsync -a /tmp/new/ src/shop/",
    "ln -sf /tmp/c src/shop/cart.py",
    # the first-round table, kept
    "cd src && cat > shop/cart.py <<'EOF'\nx=1\nEOF",
    "python3 - <<'EOF'\nfrom pathlib import Path\np=Path('src')/'shop'/'cart.py'\np.write_text(p.read_text().replace('a','b'))\nEOF",
    "python3 - <<'EOF'\nimport os\np=os.path.join('src','shop','cart.py')\nopen(p,'w').write('x')\nEOF",
    "D=src; sed -i '' 's/a/b/' $D/shop/cart.py",
    "find src -name '*.py' -exec sed -i '' 's/a/b/' {} +",
    "uv run ruff format src",
    "python3 -c \"import fileinput\nfor l in fileinput.input('src/shop/cart.py',inplace=True): print(l)\"",
    "ed -s src/shop/cart.py <<'EOF'\nw\nEOF",
    "sed -i'' 's/a/b/' src/shop/cart.py",
    "sed -i\"\" 's/a/b/' src/shop/cart.py",
    "perl -0pi -e 's/a/b/' src/shop/cart.py",
    "sudo -u x cp /tmp/c src/shop/cart.py",
    # one indicator per row, so removing any one indicator from the reader turns exactly its rows red
    "python3 -c \"import fileinput\nfor l in fileinput.input('shop/cart.py', backup='.b'): pass\"",
    "python3 -c \"f = open('shop/cart.py'); f.write('x')\"",
    "python3 -c \"import pathlib; pathlib.Path('shop/cart.py').rename('shop/old.py')\"",
    "python3 -c \"import os; os.replace('a', 'shop/cart.py')\"",
    "python3 -c \"import shutil; shutil.copytree('a', 'shop')\"",
    "node -e \"require('fs').appendFileSync('shop/a.js', 'x')\"",
    "ruby -e \"File.write('shop/a.rb', 'x')\"",
    "uv run isort .",
    "uv run ruff check --fix .",
    "uv run ruff format .",
    "curl --output shop/cart.py http://x",
    "ex -sc 'wq' shop/cart.py",
    "vim -es -c 'wq' shop/cart.py",
    "git stash",
    "xargs rm < files.txt",
    "find . -name '*.pyc' -delete",
    # the same write families with no src spelled out at all: still a source write (fail closed)
    "perl -0pi -e 's/a/b/' shop/cart.py",
    "sed -i'' 's/a/b/' shop/cart.py",
    "awk -i inplace '{print}' shop/cart.py",
    "curl -sSLo shop/cart.py http://x",
    "wget http://x/cart.py",
    "ruby -pi -e 'gsub(/a/,\"b\")' shop/cart.py",
    "uv run black .",
    "perl -ne 'print if /x/' src/shop/cart.py",
    "prettier --check src",
    "curl -sS http://example.invalid/x",
    "git checkout feature-branch",
    "echo hi > /tmp/notes.txt",
    "uv run pytest -q 2>&1 | tee /tmp/out.txt",
    # documented over-counts: a write verb or a src token anywhere costs the hit
    "cat >> tests/test_cart.py <<'EOF'\n# covers src/shop/cart.py\ndef test_x():\n    assert 1\nEOF",
    "cd /Users/x/src/shop && cat >> tests/test_cart.py <<'EOF'\ndef test_x():\n    assert 1\nEOF",
    "PYTHONPATH=src uv run pytest -q > tests/out.txt",
]


@pytest.mark.parametrize("command", SOURCE_ROWS)
def test_a_write_the_reviewer_found_or_any_unplaceable_write_is_a_source_write(command):
    assert classify_bash_command(command) == "source"


@pytest.mark.parametrize("command", SOURCE_ROWS)
def test_an_undetected_first_write_can_not_be_followed_by_a_credited_red(command):
    # The reviewer's end-to-end shape: a first source write, then tests appended and a real red run in one
    # call, then a later source write, then green. The first write is classified, so nothing is credited.
    events = [
        _bash(command, 0, ""),
        _bash(f"{TEST_APPEND}\nuv run pytest -q 2>&1 | tail -5", 1, RED),
        _bash(PYTHON_REWRITE, 2, ""),
        _bash("uv run pytest -q", 3, GREEN),
    ]
    assert _failed_before_first_source_write(events) is False


# --------------------------------------------------------------------------- none / tests / source


@pytest.mark.parametrize(
    "command",
    [
        "cat src/shop/*.py",
        "cat src/shop/cart.py tests/test_cart.py pyproject.toml",
        "uv run pytest",
        "uv run pytest -q 2>&1 | tail -5",
        "uv run pytest tests/test_cart.py -q 2>&1 | tail -20",
        "ls src",
        "ls -R src/shop",
        "git status",
        "git status --short | head",
        "git diff HEAD -- src/",
        "git log --oneline -- src/shop/cart.py",
        "sed -n 's/a/b/p' src/shop/cart.py | grep -i foo",
        "grep -rn 'install' src/",
        "cat src/shop/cart.py | grep -n patch",
        "grep -rn x src/",
        "grep -rn x tests/ src/ | head",
        "grep -n 'def f() -> int' src/shop/cart.py",
        "awk '$1 >= 3' src/shop/data.txt",
        "cat src/shop/cart.py 2>&1",
        "cat src/shop/cart.py >/dev/null",
        "cat src/shop/cart.py > /dev/null 2>&1",
        "cat src/shop/cart.py 2>/dev/null",
        "cat src/shop/cart.py >&2",
        "cat src/shop/cart.py 1>&2",
        "cat src/shop/cart.py >&-",
        "cat src/shop/cart.py > /dev/stderr",
        "head -50 src/shop/cart.py",
        "sed -n '1,20p' src/shop/cart.py",
        "sed --silent -e 'p' src/shop/cart.py",
        "python3 -c \"print(open('src/shop/cart.py').read())\"",
        "python3 -c \"print(open('src/shop/cart.py', 'r').read())\"",
        "python3 -c \"print(open('src/shop/cart.py', mode='rb').read())\"",
        "find . -path ./.venv -prune -o -type f -print | head -50; cat src/shop/cart.py",
        "cd /work/shop && cat docs/plan.md",
        "black --check src/",
        "uv run ruff format --check src",
        "ruff format --diff src",
        "ruff check src/",
        "uv run ruff check src --output-format=concise",
        "git diff --stat",
        "",
    ],
)
def test_a_command_with_no_write_indicator_is_none(command):
    assert classify_bash_command(command) == "none"


@pytest.mark.parametrize(
    "command",
    [
        TEST_APPEND,
        "cd /work/shop && " + TEST_APPEND,
        f"{TEST_APPEND}\nuv run pytest -q 2>&1 | tail -5",
        "sed -i 's/a/b/' tests/test_cart.py",
        "sed -i'' 's/a/b/' tests/test_cart.py",
        "cat > tests/test_new.py <<'EOF'\nx\nEOF",
        "rm tests/test_old.py",
        "python3 - <<'EOF'\np='tests/test_cart.py'\nopen(p,'w').write('x')\nEOF",
        "perl -0pi -e 's/a/b/' tests/test_cart.py",
        "mv tests/test_a.py tests/test_b.py",
        "sed -i 's/a/b/' test_cart.py",
        "cat >> conftest.py <<'EOF'\nx\nEOF",
        "cat >> shop/cart_test.py <<'EOF'\nx\nEOF",
    ],
)
def test_a_write_that_names_a_tests_path_and_no_src_token_is_a_tests_write(command):
    assert classify_bash_command(command) == "tests"


@pytest.mark.parametrize(
    "command",
    [
        "sed -i 's/a/b/' tests/test_cart.py src/shop/cart.py",
        "cd src && sed -i 's/a/b/' ../tests/test_cart.py",
        "cat >> tests/test_cart.py <<'EOF'\nimport os\np = os.path.join('src', 'x')\nEOF",
        "D=src; cat >> tests/test_cart.py <<'EOF'\nx\nEOF",
        "cat >> tests/test_cart.py <<'EOF'\n# the src/ package\nEOF",
        "cp tests/test_cart.py src/shop/",
    ],
)
def test_a_src_token_anywhere_in_a_write_call_makes_it_a_source_write(command):
    assert classify_bash_command(command) == "source"


@pytest.mark.parametrize(
    "command",
    [
        "echo hi > notes.txt",
        "cat > docs/plan.md <<'EOF'\nx\nEOF",
        "touch scratch.txt",
        "sed -i 's/a/b/' pyproject.toml",
    ],
)
def test_a_write_that_names_neither_tests_nor_src_is_a_source_write_not_nothing(command):
    assert classify_bash_command(command) == "source"


def test_a_resrc_or_mysrc_token_is_not_a_src_token():
    assert classify_bash_command("cat >> tests/test_cart.py <<'EOF'\n# see resrc/ and mysrc/x and src_old\nEOF") == "tests"


def test_a_command_over_the_cap_is_a_source_write_without_being_scanned():
    assert BASH_COMMAND_CAP == 100_000
    read_only = "ls " + "a" * (BASH_COMMAND_CAP - 3)
    assert len(read_only) == BASH_COMMAND_CAP
    assert classify_bash_command(read_only) == "none"
    assert classify_bash_command(read_only + "b") == "source"
    assert bash_write_offset(read_only + "b") == 0


# --------------------------------------------------------------------------- the offset


def test_the_offset_is_where_the_first_write_capable_command_starts():
    command = f"{TEST_APPEND}\nuv run pytest -q"
    offset = bash_write_offset(command)
    assert offset == 0
    assert offset < command.rfind("pytest")


def test_the_offset_of_a_write_after_the_test_run_is_after_it():
    command = "uv run pytest -q; sed -i 's/a/b/' src/shop/cart.py"
    offset = bash_write_offset(command)
    assert offset is not None
    assert offset > command.rfind("pytest")


def test_the_offset_is_the_earliest_of_several_write_capable_commands():
    command = "cat a; echo x > notes.txt; sed -i s/a/b/ src/x.py"
    assert bash_write_offset(command) == command.index("echo")


def test_the_offset_is_none_when_nothing_writes():
    assert bash_write_offset("cat src/shop/cart.py") is None
    assert bash_write_offset("") is None


# --------------------------------------------------------------------------- the edit tools


@pytest.mark.parametrize(
    ("tool", "path", "expected"),
    [
        ("Edit", "/work/shop/src/shop/cart.py", "source"),
        ("Write", "src/shop/new_module.py", "source"),
        ("NotebookEdit", "/work/shop/src/nb.ipynb", "source"),
        ("MultiEdit", "/work/shop/src/shop/cart.py", "source"),
        ("Edit", "/Users/x/tests/ws/src/shop/cart.py", "source"),
        ("Edit", "/work/shop/tests/test_cart.py", "tests"),
        ("Write", "/work/shop/tests/helpers.py", "tests"),
        ("MultiEdit", "/work/shop/tests/test_cart.py", "tests"),
        ("Edit", "/work/shop/test_cart.py", "tests"),
        ("Edit", "/work/shop/conftest.py", "tests"),
        ("Edit", "/work/shop/pkg/cart_test.py", "tests"),
        ("Edit", "/work/shop/src/shop/test_helpers.py", "tests"),
        ("Write", "/work/shop/scratch_plan.md", "none"),
        ("Write", "/work/shop/docs/plan.md", "none"),
        ("Edit", "/work/shop/pyproject.toml", "none"),
        ("Edit", "/work/shopsrc/x.md", "none"),
        ("Edit", "/work/resrc/x.md", "none"),
        ("Edit", "/work/shop/src_old/x.md", "none"),
        # a script path is a source write even outside src/ (it can author a script that writes src/)
        ("Edit", "/work/shopsrc/x.py", "source"),
        ("Edit", "/work/resrc/x.py", "source"),
        ("Edit", "/work/shop/src_old/x.py", "source"),
        ("Edit", "", "none"),
    ],
)
def test_an_edit_tool_write_is_classified_by_its_path_segments(tool, path, expected):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    assert classify_write_event(_event(tool, {key: path}, 0)) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/Users/x/tests/ws/src/shop/cart.py", "source"),
        ("/work/tests/proj/pkg/cart.py", "tests"),
        ("/home/dev/tests-sandbox/src/a.py", "source"),
        ("src/shop/cart.py", "source"),
    ],
)
def test_a_tests_directory_above_the_project_does_not_decide_an_edit_path(path, expected):
    # The #1131 table: one rule, ``classify_write_event``, decides every write path.
    assert classify_write_event(_event("Edit", {"file_path": path}, 0)) == expected


def test_an_edit_tool_event_without_a_path_is_none():
    assert classify_write_event(_event("Edit", {"old_string": "a"}, 0)) == "none"
    assert classify_write_event(_event("Edit", "not a dict", 0)) == "none"


def test_other_tools_are_none_and_a_bash_event_is_read_by_its_command():
    assert classify_write_event(_event("Read", {"file_path": "/w/src/x.py"}, 0)) == "none"
    assert classify_write_event(_event("Skill", {"skill": "workbench:tdd"}, 0)) == "none"
    assert classify_write_event(_bash("sed -i s/a/b/ src/x.py", 0)) == "source"
    assert classify_write_event(_bash(TEST_APPEND, 0)) == "tests"
    assert classify_write_event(_bash("cat src/x.py", 0)) == "none"


@pytest.mark.parametrize("tool_input", [{}, {"command": None}, {"command": 3}, {"command": ["cat", ">", "src/x.py"]}, "sed -i src/"])
def test_a_bash_event_without_a_command_string_is_none(tool_input):
    assert classify_write_event(_event("Bash", tool_input, 0)) == "none"


# --------------------------------------------------------------------------- ordering predicate


def test_a_red_run_in_the_call_that_writes_the_tests_precedes_a_later_source_write():
    events = [
        _bash("cat src/shop/*.py tests/*.py", 0, GREEN),
        _bash(f"{TEST_APPEND}\nuv run pytest -q", 1, RED),
        _bash(f"{PYTHON_REWRITE}\nuv run pytest -q", 2, GREEN),
    ]
    assert _failed_before_first_source_write(events) is True


def test_a_red_run_after_a_separate_test_write_call_is_credited():
    events = [
        _bash(TEST_APPEND, 0, ""),
        _bash("uv run pytest -q", 1, RED),
        _bash(PYTHON_REWRITE, 2, ""),
    ]
    assert _failed_before_first_source_write(events) is True


def test_a_source_write_before_any_failure_is_not_test_first():
    events = [
        _bash(f"{PYTHON_REWRITE}\nuv run pytest -q", 0, GREEN),
        _bash(f"{TEST_APPEND}\nuv run pytest -q", 1, RED),
    ]
    assert _failed_before_first_source_write(events) is False


def test_a_red_result_and_a_source_write_in_one_call_share_an_ordinal_and_are_not_credited():
    events = [_bash(f"{TEST_APPEND}\n{PYTHON_REWRITE}\nuv run pytest -q", 0, RED)]
    assert _failed_before_first_source_write(events) is False
    events = [_bash(f"{TEST_APPEND}\n{PYTHON_REWRITE}\nuv run pytest -q", 0, RED), _bash("uv run pytest -q", 1, GREEN)]
    assert _failed_before_first_source_write(events) is False


def test_a_test_written_in_an_earlier_call_does_not_credit_a_red_that_comes_with_the_source_write():
    events = [
        _bash(TEST_APPEND, 0, ""),
        _bash(f"{PYTHON_REWRITE}\nuv run pytest -q", 1, RED),
        _bash("uv run pytest -q", 2, GREEN),
    ]
    assert _failed_before_first_source_write(events) is False


def test_a_second_red_in_a_later_call_does_not_rescue_a_source_write_that_came_with_the_first():
    events = [
        _bash(f"{TEST_APPEND}\n{PYTHON_REWRITE}\nuv run pytest -q", 0, RED),
        _bash("uv run pytest -q", 1, RED),
    ]
    assert _failed_before_first_source_write(events) is False


def test_a_call_that_only_reads_the_source_is_not_a_source_write():
    events = [
        _bash("cat src/shop/cart.py; ls src", 0, GREEN),
        _bash(f"{TEST_APPEND}\nuv run pytest -q 2>&1 | tail -5", 1, RED),
        _bash(PYTHON_REWRITE, 2),
    ]
    assert _failed_before_first_source_write(events) is True


def test_a_write_to_the_tests_is_not_a_source_write():
    events = [
        _bash(TEST_APPEND, 0),
        _bash("uv run pytest -q", 1, RED),
        _bash(PYTHON_REWRITE, 2),
    ]
    assert _failed_before_first_source_write(events) is True


def test_an_edit_tool_test_write_then_red_then_a_source_edit_is_credited():
    events = [
        _event("Write", {"file_path": "/w/tests/test_new.py", "content": "x"}, 0),
        _bash("uv run pytest -q", 1, RED),
        _event("Edit", {"file_path": "/w/src/shop/cart.py"}, 2),
    ]
    assert _failed_before_first_source_write(events) is True
    events[2] = _event("MultiEdit", {"file_path": "/w/src/shop/cart.py", "edits": []}, 2)
    assert _failed_before_first_source_write(events) is True


def test_a_multiedit_on_the_source_first_is_a_source_write():
    events = [
        _event("MultiEdit", {"file_path": "/w/src/shop/cart.py", "edits": []}, 0),
        _bash(f"{TEST_APPEND}\nuv run pytest -q", 1, RED),
        _bash(PYTHON_REWRITE, 2),
    ]
    assert _failed_before_first_source_write(events) is False


def test_an_edit_whose_absolute_path_has_a_tests_directory_above_src_is_still_a_source_write():
    events = [
        _event("Edit", {"file_path": "/Users/x/tests/ws/src/shop/cart.py", "old_string": "a", "new_string": "b"}, 0),
        _bash(f"{TEST_APPEND}\nuv run pytest -q", 1, RED),
        _bash(PYTHON_REWRITE, 2),
    ]
    assert _failed_before_first_source_write(events) is False


def test_an_edit_tool_write_to_a_scratch_file_is_not_a_source_write():
    events = [
        _event("Write", {"file_path": "/w/scratch_plan.md", "content": "x"}, 0),
        _bash(f"{TEST_APPEND}\nuv run pytest -q", 1, RED),
        _bash(PYTHON_REWRITE, 2),
    ]
    assert _failed_before_first_source_write(events) is True


def test_a_red_result_with_no_test_write_before_it_is_not_credited():
    events = [
        _bash("echo 'FAILED tests/x'", 0, "FAILED tests/x\n"),
        _bash(PYTHON_REWRITE, 1),
    ]
    assert _failed_before_first_source_write(events) is False
    events = [_bash("uv run pytest -q", 0, RED), _bash(PYTHON_REWRITE, 1)]
    assert _failed_before_first_source_write(events) is False


def test_a_test_write_after_the_red_result_does_not_make_it_a_credited_red():
    events = [
        _bash("uv run pytest -q", 0, RED),
        _bash(TEST_APPEND, 1, ""),
        _bash(PYTHON_REWRITE, 2),
    ]
    assert _failed_before_first_source_write(events) is False


def test_a_test_write_in_the_same_call_as_a_real_red_is_credited():
    events = [_bash(f"{TEST_APPEND}\nuv run pytest -q", 0, RED), _bash(PYTHON_REWRITE, 1)]
    assert _failed_before_first_source_write(events) is True


def test_there_must_be_both_a_red_run_and_a_source_write():
    assert _failed_before_first_source_write([_bash(PYTHON_REWRITE, 0, GREEN)]) is False
    assert _failed_before_first_source_write([_bash(f"{TEST_APPEND}\nuv run pytest -q", 0, RED)]) is False
    assert _failed_before_first_source_write([]) is False


def test_a_bash_source_write_before_the_red_result_is_not_credited_even_with_a_later_edit():
    events = [
        _bash(PYTHON_REWRITE, 0),
        _bash("uv run pytest -q", 1, RED),
        _event("Edit", {"file_path": "src/shop/cart.py"}, 2),
    ]
    assert _failed_before_first_source_write(events) is False


# --------------------------------------------------------------------------- bounded time

# Sizes are literals, not the imported cap, so a mutated cap cannot inflate the shapes.
SHAPE_SIZE = 100_000
REALISTIC = (
    "cd /work/shop && cat >> tests/test_cart.py <<'EOF'\n"
    + "".join(f"\n\ndef test_case_{i}():\n    assert line_total_cents(LineItem('A', {i}, 10)) > 0\n" for i in range(3000))
)[:99_999]

SLOW_SHAPES = {
    "newlines then src": "\n" * (SHAPE_SIZE - 5) + "src/x",
    "newlines": "\n" * SHAPE_SIZE,
    "open( repeated": "open(" * (SHAPE_SIZE // 5),
    "newline and two spaces": "\n  " * (SHAPE_SIZE // 3),
    "assignments and blank lines": "x=1\n\n" * (SHAPE_SIZE // 5),
    "spaces then src": " " * (SHAPE_SIZE - 5) + "src/x",
    "sed repeated": "sed " * (SHAPE_SIZE // 4),
    "git repeated": "git " * (SHAPE_SIZE // 4),
    "redirect arrows": ">=" * (SHAPE_SIZE // 2),
    "redirects repeated": "> " * (SHAPE_SIZE // 2),
    "open( then spaces": "open(" + " " * (SHAPE_SIZE - 10) + ",'w'",
    "quotes repeated": "'" * SHAPE_SIZE,
    "commas and equals": ",=" * (SHAPE_SIZE // 2),
    "ruff repeated": "ruff format " * (SHAPE_SIZE // 12),
    "realistic 99_999 character command": REALISTIC,
}


def test_the_realistic_command_is_99_999_characters_long():
    assert len(REALISTIC) == 99_999


@pytest.mark.parametrize("shape", sorted(SLOW_SHAPES))
def test_classifying_a_shape_that_was_quadratic_takes_well_under_half_a_second(shape):
    command = SLOW_SHAPES[shape]
    assert len(command) <= SHAPE_SIZE
    started = time.perf_counter()
    classify_bash_command(command)
    bash_write_offset(command)
    assert time.perf_counter() - started < 0.5
