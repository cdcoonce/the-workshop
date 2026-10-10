"""Regression tests for the allow-list Bash classification (fix round 2).

Round one blocklisted write indicators; a second adversarial pass found writes that match none
(``gsed -i``, a backslash ``cp``, ``uv run python /tmp/fix.py``, ``from shutil import copy``, ``sed -n '1w src/x'``,
...). ``classify_bash_command`` is now an allow-list: ``none`` only when EVERY simple command's head is a known
read-only program with no write flag and no file redirect; a write-capable call is ``tests`` only when every
write it makes is a recognised one aimed at a literal path under ``tests/``, no other command in the call is
write-capable, and ``src`` appears nowhere in it; everything else, an unknown head included, is ``source``.

Every row of both reviewers is replayed here in the shape that fooled the first version: an undetected first
source write, then ``cat >> tests/x <<EOF ...; uv run pytest | tail`` (a real red), then a recognised source
rewrite, then green. The transcript conjunct of T1 must be False for every one of them.
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
SRC_FIX = "python3 - <<'EOF'\np='src/shop/cart.py'\ns=open(p).read()\ns=s.replace('a','b')\nopen(p,'w').write(s)\nEOF"
TEST_WRITE_AND_RUN = (
    "cat >> tests/test_cart.py <<'EOF'\ndef test_bulk():\n    assert 1 == 2\nEOF\nuv run pytest -q 2>&1 | tail -15"
)
BODY = (
    "def test_bulk():\n    from shop.cart import LineItem, line_total_cents\n"
    "    assert line_total_cents(LineItem('A',333,10)) == 2831"
)


def _event(name, tool_input, ordinal, *, content=None):
    result = None if content is None else ToolResult(content=content, is_error=False)
    return ToolCallEvent(name=name, input=tool_input, result=result, ordinal=ordinal, timestamp=None)


def _events(steps):
    """Steps are ``("bash", command, output)`` or ``(tool, input, output)``."""
    out = []
    for ordinal, step in enumerate(steps):
        if step[0] == "bash":
            out.append(_event("Bash", {"command": step[1]}, ordinal, content=step[2]))
        else:
            out.append(_event(step[0], step[1], ordinal, content=step[2]))
    return out


def _credited(steps):
    return _failed_before_first_source_write(_events(steps))


def _fooled(first_steps):
    """The reviewer's shape: some first write(s), a real red with its test write, a recognised fix, green."""
    return _credited(
        [
            *first_steps,
            ("bash", TEST_WRITE_AND_RUN, RED),
            ("bash", SRC_FIX, ""),
            ("bash", "uv run pytest -q | tail -3", GREEN),
        ]
    )


# --------------------------------------------------------------------------- the reviewers' rows

# (label, command) from the second reviewer's classifier probe.
CLS_ROWS = [
    ("black module", "python -m black src"),
    ("uv run black", "uv run black ."),
    ("ruff format via python -m", "python -m ruff format ."),
    ("uvx ruff", "uvx ruff format ."),
    ("ruff check --fix", "uv run ruff check --fix ."),
    ("make fmt", "make fmt"),
    ("make", "make"),
    ("run script", "uv run python /tmp/fix.py"),
    ("python script path", "python3 fix.py"),
    ("python -c pathlib join", "uv run python -c \"import pathlib; p=pathlib.Path('s'+'rc')/'shop'/'cart.py'; p.write_text('x')\""),
    ("python -c glob/os.walk write", "python3 -c \"import glob; [open(f,'a').write('#') for f in glob.glob('*/shop/*.py')]\""),
    ("git stash pop", "git stash pop"),
    ("git checkout ref -- file", "git checkout HEAD~1 -- src/shop/cart.py"),
    ("git merge", "git merge feature"),
    ("git pull", "git pull"),
    ("git revert", "git revert HEAD"),
    ("git diff", "git diff"),
    ("git status", "git status --short | head"),
    ("git log", "git log --oneline -5"),
    ("git commit", "git add -A && git commit -m x"),
    ("git show", "git show HEAD:src/shop/cart.py"),
    ("git mv", "git mv a b"),
    ("git worktree add", "git worktree add ../x"),
    ("git apply", "git apply p.diff"),
    ("git fetch", "git fetch"),
    ("git format-patch", "git format-patch -1"),
    ("git sparse-checkout", "git sparse-checkout set src"),
    ("git submodule update", "git submodule update --init"),
    ("git filter-branch", "git filter-branch x"),
    ("git commit -a --amend", "git commit --amend --no-edit"),
    ("git -C path checkout", "git -C /w checkout -- ."),
    ("git branch -f", "git branch -f x"),
    ("git update-index", "git update-index --assume-unchanged x"),
    ("git rebase", "git rebase main"),
    ("git write-tree", "git write-tree"),
    ("git hash-object -w", "git hash-object -w x"),
    ("git checkout-index", "git checkout-index -a -f"),
    ("git restore-dash", "git restore ."),
    ("pip install -e", "pip install -e ."),
    ("uv add", "uv add requests"),
    ("uv pip install", "uv pip install x"),
    ("uv sync", "uv sync"),
    ("unzip", "unzip x.zip"),
    ("tar -x", "tar -xf x.tar"),
    ("tar xf", "tar xf x.tar"),
    ("sed -n w", "sed -n 's/a/b/w src/shop/cart.py' src/shop/cart.py"),
    ("sed w cmd", "sed -n '1w src/shop/out.py' src/shop/cart.py"),
    ("sed -n w no src (tests)", "sed -n '1w tests/test_x.py' f"),
    ("pipe tee", "echo x | tee src/shop/cart.py"),
    ("cat | python3", "cat <<'EOF' | python3\nopen('src/x','w').write('1')\nEOF"),
    ("python3 <<EOF", "python3 <<'EOF'\nopen('src/x','w').write('1')\nEOF"),
    ("python heredoc string-assembled", "python3 - <<'EOF'\nimport pathlib\npathlib.Path('s'+'rc/shop/cart.py').write_text('x')\nEOF"),
    ("process subst", "cp <(echo x) src/shop/cart.py"),
    ("xargs sed -i", "ls src/shop/*.py | xargs sed -i '' 's/a/b/'"),
    ("xargs sed -i via env", "echo x | xargs -I{} perl -pi -e 's/a/b/' {}"),
    ("printf | dd", "printf x | dd of=src/shop/cart.py"),
    ("exec", "exec 3<>src/shop/cart.py; echo x >&3"),
    ("exec redirect", "exec >src/shop/cart.py"),
    ("exec 3> then write", "exec 3>src/shop/cart.py"),
    ("eval", "eval \"$CMD\""),
    ("eval string", "eval 'echo x > src/shop/cart.py'"),
    ("bash -c", "bash -c 'echo x > src/shop/cart.py'"),
    ("sh script.sh", "sh fix.sh"),
    ("bash script", "bash ./fix.sh"),
    ("./script", "./fix.sh"),
    ("base64 -d >", "echo eA== | base64 -d > src/shop/cart.py"),
    ("base64 -d -o", "base64 -d -o src/shop/cart.py in.b64"),
    ("1> redirect", "echo x 1>src/shop/cart.py"),
    (">| redirect", "echo x >|src/shop/cart.py"),
    ("&> redirect", "echo x &>src/shop/cart.py"),
    (">> redirect", "echo x >>src/shop/cart.py"),
    ("3> redirect", "echo x 3>src/shop/cart.py >&3"),
    ("1>> redirect", "echo x 1>>src/shop/cart.py"),
    ("here-string", "tee src/shop/cart.py <<< 'x'"),
    ("here-string cat", "cat <<< 'x' > src/shop/cart.py"),
    (">/dev/null disguise", "echo x >/dev/nullx"),
    ("> /dev/null/..", "echo x > /dev/null/../../tmp/f"),
    ("> /dev/stdout/..", "echo x >/dev/stdout/../../src/f"),
    ("/dev/fd path", "echo x > /dev/fd/3"),
    ("awk print >", "awk '{print > \"src/shop/cart.py\"}' f"),
    ("awk system", "awk 'BEGIN{system(\"echo x > src/f\")}'"),
    ("awk print >>", "awk '{print >> \"src/f\"}' f"),
    ("awk |getline cmd", "awk 'BEGIN{print \"x\" | \"tee src/f\"}'"),
    ("node -e fs", "node -e \"require('fs').writeFileSync('src/f','x')\""),
    ("perl -e open", "perl -e 'open(F,\">src/f\");print F 1'"),
    ("perl -e open +<", "perl -e 'open(F,\"+<src/f\");print F 1'"),
    ("ruby -e File.write", "ruby -e 'File.write(\"src/f\",\"x\")'"),
    ("ruby File.open w", "ruby -e 'File.open(\"src/f\",\"w\"){}'"),
    ("python Path.write_text no paren?", "python3 -c \"from pathlib import Path; Path('src/f').write_text ('x')\""),
    ("python .write (", "python3 -c \"f=open('src/f','w'); f.write ('x')\""),
    ("python open with mode kw", "python3 -c \"open('src/f',mode='w')\""),
    ("python open mode var", "python3 -c \"m='w'; open('src/f',m)\""),
    ("python open mode concat", "python3 -c \"open('src/f','w'+'b')\""),
    ("python open mode split", "python3 -c \"open('src/f','a' 'b')\""),
    ("python open mode r+", "python3 -c \"open('src/f','r+').write('x')\""),
    ("python print(file=)", "python3 -c \"print('x', file=open('src/f','w'))\""),
    ("python io.open", "python3 -c \"import io; io.open('src/f','w')\""),
    ("python codecs.open", "python3 -c \"import codecs; codecs.open('src/f','w')\""),
    ("python os.open fd", "python3 -c \"import os; os.open('src/f', 65)\""),
    ("python os.open flags num", "python3 -c \"import os; os.write(os.open('src/f', 0o101), b'x')\""),
    ("python subprocess sed", "python3 -c \"import subprocess; subprocess.run(['sed','-i','','s/a/b/','src/f'])\""),
    ("python subprocess shlex", "python3 -c \"import os; os.system('sed -i s/a/b/ src/f')\""),
    ("python os.system echo", "python3 -c \"import os; os.system('echo x > src/f')\""),
    ("python importlib reload", "python3 -c \"import shop.cart\""),
    ("python  tempfile + os.rename", "python3 -c \"import os; os.rename('a','src/f')\""),
    ("python shutil.copyfile", "python3 -c \"import shutil; shutil.copyfile('a','src/f')\""),
    ("python from shutil import copy", "python3 -c \"from shutil import copy; copy('a','src/f')\""),
    ("python from os import replace", "python3 -c \"from os import replace; replace('a','src/f')\""),
    ("python from os import rename as r", "python3 -c \"from os import rename as r; r('a','src/f')\""),
    ("python import os as o", "python3 -c \"import os as o; o.rename('a','src/f')\""),
    ("python aliases open", "python3 -c \"w=open; w('src/f','w').close()\""),
    ("python write_text spaced", "python3 -c \"from pathlib import Path as P; P('src/f').write_text('x')\""),
    ("python __import__", "python3 -c \"__import__('os').rename('a','src/f')\""),
    ("python getattr", "python3 -c \"import os; getattr(os,'ren'+'ame')('a','src/f')\""),
    ("python exec string", "python3 -c \"exec(open('/tmp/s.py').read())\""),
    ("python -m py_compile", "python3 -m py_compile src/shop/cart.py"),
    ("python -m compileall", "python3 -m compileall src"),
    ("python -m json.tool inplace?", "python3 -m json.tool in out"),
    ("python -m venv", "python3 -m venv .venv"),
    ("python zipapp", "python3 -m zipfile -e a.zip src"),
    ("python -m tarfile -e", "python3 -m tarfile -e a.tar src"),
    ("python -m pip", "python3 -m pip install -e ."),
    ("python -m autopep8", "python3 -m autopep8 -i src/f"),
    ("autopep8 -i", "autopep8 -i src/f"),
    ("autoflake", "autoflake --in-place src/f"),
    ("autoflake -i", "autoflake -i src/f"),
    ("pyupgrade", "pyupgrade --py312-plus src/shop/cart.py"),
    ("docformatter", "docformatter -i src/f"),
    ("isort", "isort src"),
    ("ruff --fix after check", "ruff check src --fix"),
    ("ruff --fix-only", "ruff check --fix-only src"),
    ("ruff format --check", "ruff format --check src"),
    ("ruff check --select --fix", "ruff check --select I --fix src"),
    ("ruff format with --diff", "ruff format --diff src && ruff format src"),
    ("ruff format check then format", "ruff format --check src; ruff format src"),
    ("black --check then black", "black --check src || black src"),
    ("black diff && ...", "black --diff src | black -"),
    ("ruff -- unsafe", "ruff check --unsafe-fixes src"),
    ("ruff check --fix=?", "ruff check --fix-only=1 src"),
    ("ruff via uv tool run", "uv tool run ruff format"),
    ("2to3 -w", "2to3 -w src"),
    ("sed -E -i", "sed -E -i '' 's/a/b/' src/f"),
    ("sed -i via -ie", "sed -ie 's/a/b/' src/f"),
    ("sed -ni", "sed -ni 'p' src/f"),
    ("sed -s -i", "sed -s -i 's/a/b/' src/f"),
    ("sed combined -ibak", "sed -ibak s/a/b/ src/f"),
    ("gsed -i", "gsed -i 's/a/b/' src/f"),
    ("sd tool", "sd 'a' 'b' src/shop/cart.py"),
    ("sd -f", "sd -f w a b src/f"),
    ("rg --replace", "rg a --replace b src"),
    ("fd -x sed", "fd -e py -x sed -i s/a/b/"),
    ("find -exec perl -pi", "find src -exec perl -pi -e s/a/b/ {} ;"),
    ("find -fprint", "find . -fprint src/f"),
    ("find -fprintf", "find . -fprintf src/f x"),
    ("find -fls", "find . -fls src/f"),
    ("sort -o", "sort -o src/f src/f"),
    ("sort --output", "sort --output=src/f src/f"),
    ("uniq in out", "uniq src/in src/out"),
    ("split", "split -l 1 src/f src/g"),
    ("csplit", "csplit src/f 1"),
    ("tr > ", "tr a b < src/f > src/g"),
    ("cat < f >", "cat < a > src/g"),
    ("head -c >", "head -c1 a > src/g"),
    ("cmp", "cmp a b"),
    ("jq -i? (no) ", "jq . a > b"),
    ("yq -i", "yq -i '.a=1' src/f.yaml"),
    ("sponge", "sed s/a/b/ src/f | sponge src/f"),
    ("curl -o", "curl -o src/f http://x"),
    ("curl > ", "curl http://x > src/f"),
    ("wget -O", "wget -O src/f http://x"),
    ("gh api >", "gh api x > src/f"),
    ("cp -r", "cp -r a src"),
    ("cp via /bin/cp", "/bin/cp a src/f"),
    ("command cp", "command cp a src/f"),
    ("\\cp", "\\cp a src/f"),
    ("env cp", "env cp a src/f"),
    ("busybox cp", "busybox cp a src/f"),
    ("ditto", "ditto a src/f"),
    ("pbpaste >", "pbpaste > src/f"),
    ("mkdir", "mkdir -p src/new"),
    ("mktemp", "mktemp"),
    ("chmod", "chmod +x src/f"),
    ("chown", "chown x src/f"),
    ("xattr", "xattr -c src/f"),
    ("rename", "rename s/a/b/ src/*"),
    ("mmv", "mmv a b"),
    ("shred", "shred src/f"),
    ("gzip", "gzip src/f"),
    ("gunzip", "gunzip src/f.gz"),
    ("zip", "zip -r a.zip src"),
    ("7z x", "7z x a.7z"),
    ("bsdtar", "bsdtar -xf a.tar"),
    ("cpio", "cpio -id < a"),
    ("pax", "pax -r < a"),
    ("ex with heredoc -s", "ex -s src/f <<EOF\nwq\nEOF"),
    ("vi", "vi src/f"),
    ("nano", "nano src/f"),
    ("emacs", "emacs --batch src/f -f save-buffer"),
    ("code", "code src/f"),
    ("open", "open src/f"),
    ("osascript", "osascript -e 'x'"),
    ("pbcopy", "pbcopy < src/f"),
    ("ln -s", "ln -s a src/f"),
    ("link", "link a src/f"),
    ("mkfifo", "mkfifo src/f"),
    ("mknod", "mknod src/f p"),
    ("install", "install a src/f"),
    ("ginstall", "ginstall a src/f"),
    ("rsync", "rsync -a a/ src/"),
    ("scp", "scp a src/f"),
    ("sftp", "sftp x"),
    ("tee -a", "tee -a src/f"),
    ("dd of", "dd of=src/f if=a"),
    ("truncate", "truncate -s0 src/f"),
    ("fallocate", "fallocate -l1 src/f"),
    ("patch -p1", "patch -p1 < p"),
    ("git apply -", "cat p | git apply -"),
    ("diff | patch", "diff -u a b | patch src/f"),
    ("xargs rm", "echo src/f | xargs rm"),
    ("xargs -a", "xargs -a l truncate -s0"),
    ("parallel", "parallel sed -i s/a/b/ ::: src/f"),
    ("watch", "watch -n1 echo"),
    ("nohup", "nohup sh -c 'echo > src/f'"),
    ("time", "time sed -i s/a/b/ src/f"),
    ("sudo", "sudo sed -i s/a/b/ src/f"),
    ("nice", "nice -n 1 sed -i s/a/b/ src/f"),
    ("timeout", "timeout 5 sed -i s/a/b/ src/f"),
    ("script-run via source", "source ./fix.sh"),
    (". script", ". ./fix.sh"),
    ("sh -c", "sh -c 'sed -i s/a/b/ src/f'"),
    ("zsh -c", "zsh -c 'echo > src/f'"),
    ("python3 file", "python3 apply_fix.py"),
    ("uv run script.py", "uv run apply_fix.py"),
    ("uv run --script", "uv run --script apply_fix.py"),
    ("uv run python -m mymod", "uv run python -m scripts.apply"),
    ("pytest plugin conftest write", "uv run pytest --basetemp=src/x"),
    ("pytest --junitxml", "uv run pytest --junitxml=src/f.xml"),
    ("pytest --cov report", "uv run pytest --cov-report=html:src/x"),
    ("pytest -o", "uv run pytest -p no:cacheprovider"),
    ("pytest --lf", "uv run pytest --lf"),
    ("pytest --snapshot-update", "uv run pytest --snapshot-update"),
    ("pytest --update-goldens", "uv run pytest --update"),
    ("pytest --pdb", "uv run pytest --pdb"),
    ("pytest -p", "uv run pytest -p x"),
    ("pytest --fixtures", "uv run pytest --fixtures"),
    ("echo to stderr", "echo x >&2"),
    ("env vars", "FOO=1 uv run pytest"),
    ("redirect 2>file", "uv run pytest 2>/tmp/err"),
    ("redirect 2>&1 file", "uv run pytest > /tmp/out 2>&1"),
    ("pytest | tee", "uv run pytest | tee /tmp/o"),
    ("pytest tail ok", "uv run pytest -q 2>&1 | tail -5"),
    ("pytest cd", "cd /abs/ws && uv run pytest -q"),
    ("read cat", "cat src/shop/*.py tests/*.py; uv run pytest -q 2>&1 | tail -5"),
    ("git status+find", "git status --short | head; find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50"),
    ("find -delete", "find . -name '*.pyc' -delete"),
    ("find -exec rm", "find . -name __pycache__ -exec rm -rf {} +"),
    ("rm -rf cache", "rm -rf .pytest_cache"),
    ("ls", "ls -R"),
    ("mkdir tests", "mkdir -p tests/x && cat > tests/x/test_y.py <<'EOF'\nfrom shop.cart import f\nEOF"),
    ("test mentions src.shop", "cat >> tests/test_cart.py <<'EOF'\nfrom src.shop.cart import f\nEOF"),
    ("test mentions comment src/shop/cart.py", "cat >> tests/test_cart.py <<'EOF'\n# covers src/shop/cart.py\nEOF"),
    ("test mentions src_dir", "cat >> tests/test_cart.py <<'EOF'\nsrc_dir = 1\nEOF"),
    ("test writes with cd abs no src", "cd /Users/me/work/ws && cat >> tests/test_cart.py <<'EOF'\nx\nEOF"),
    ("test write abs path w/ src segment", "cat >> /Users/me/src/ws/tests/test_cart.py <<'EOF'\nx\nEOF"),
    ("test write python", "python3 - <<'EOF'\np='tests/test_cart.py'\nopen(p,'a').write('x')\nEOF"),
    ("test write ruff format tests", "ruff format tests/"),
    ("test write uv run ruff format tests/", "uv run ruff format tests/"),
    ("test write sed tests", "sed -i '' 's/a/b/' tests/test_cart.py"),
    ("touch tests/x", "touch tests/x"),
    ("test write then pytest", "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nuv run pytest -q 2>&1 | tail -15"),
    ("git diff after test write", "git diff tests/"),
    ("git checkout -b", "git checkout -b feat"),
    ("git switch -c", "git switch -c feat"),
    ("git stash list", "git stash list"),
    ("git branch", "git branch --show-current"),
    ("git restore --staged", "git restore --staged ."),
    ("git ls-files", "git ls-files"),
    ("git add tests", "git add tests && git commit -m red"),
    ("git commit -a", "git commit -am wip"),
    ("git tag", "git tag x"),
    ("git config", "git config user.name x"),
    ("git init", "git init"),
    ("git clone", "git clone x y"),
    ("git fetch+reset", "git fetch && git reset --hard origin/main"),
    ("git clean", "git clean -fd"),
    ("git rm", "git rm -f src/f"),
    ("git bisect", "git bisect start"),
    ("git replace", "git replace"),
    ("git notes", "git notes"),
    ("git pull alias", "git up"),
    ("git alias co", "git co src/f"),
    ("git alias sw", "git sw x"),
    ("git rev-parse checkout name arg", "git log --grep=checkout"),
    ("GIT env prefix", "GIT_DIR=x git checkout ."),
    ("git -c", "git -c core.x=1 checkout ."),
    ("git config alias", "git config alias.x '!sed -i s/a/b/ src/f'"),
    ("git cat-file > ", "git cat-file -p x > src/f"),
    ("git show > ", "git show x:y > src/f"),
    ("git archive | tar", "git archive HEAD | tar -x"),
    ("git archive -o", "git archive -o a.zip HEAD"),
    ("git diff > patch", "git diff > /tmp/p"),
    ("git format-patch -o", "git format-patch -o src"),
    ("git stash push", "git stash push -u"),
    ("git rebase -i", "git rebase -i"),
    ("git commit --fixup", "git commit --fixup x"),
]
# Rows that are genuinely read-only: classified none, and a none call is never a write.
RO_LABELS = {
    "git diff",
    "git status",
    "git log",
    "git show",
    "git branch",
    "git ls-files",
    "git rev-parse checkout name arg",
    "cmp",
    "echo to stderr",
    "pytest tail ok",
    "pytest cd",
    "read cat",
    "git status+find",
    "ls",
    "pytest -o",
    "pytest --lf",
    "ruff format --check",
    "git diff after test write",
    "rg --replace",
}
# Rows that are honest test writes: classified tests.
TESTS_LABELS = {
    "mkdir tests",
    "test mentions src_dir",
    "test writes with cd abs no src",
    "test write python",
    "test write sed tests",
    "touch tests/x",
    "test write then pytest",
}


@pytest.mark.parametrize(
    ("label", "command"), CLS_ROWS, ids=[f"{i}-{label}" for i, (label, _) in enumerate(CLS_ROWS)]
)
def test_every_reviewer_row_is_none_only_when_read_only_and_never_lets_a_later_red_hit(label, command):
    kind = classify_bash_command(command)
    if kind == "none":
        assert label in RO_LABELS, (label, command)
    elif kind == "tests":
        assert label in TESTS_LABELS, (label, command)
    else:
        assert _fooled([("bash", command, "")]) is False, (label, command)


def test_the_read_only_and_tests_buckets_name_rows_that_exist_and_hold():
    labels = {label for label, _ in CLS_ROWS}
    assert RO_LABELS <= labels
    assert TESTS_LABELS <= labels
    for label, command in CLS_ROWS:
        if label in RO_LABELS:
            assert classify_bash_command(command) == "none", label
        if label in TESTS_LABELS:
            assert classify_bash_command(command) == "tests", label


UNDETECTED_FIRST_WRITES = {
    "Write /tmp/fix.py then uv run python /tmp/fix.py": [
        ("Write", {"file_path": "/tmp/fix.py", "content": "import pathlib\np=pathlib.Path('src/shop/cart.py')"}, "ok"),
        ("bash", "uv run python /tmp/fix.py", ""),
    ],
    "Write fix.py then python3 fix.py": [
        ("Write", {"file_path": "/work/ws/fix.py", "content": "open('src/shop/cart.py','a').write('#x')"}, "ok"),
        ("bash", "python3 fix.py", ""),
    ],
    "Write fix.sh then bash fix.sh": [
        ("Write", {"file_path": "/work/ws/fix.sh", "content": "sed -i '' 's/a/b/' src/shop/cart.py"}, "ok"),
        ("bash", "bash fix.sh", ""),
    ],
    "Write fix.sh then chmod and run": [
        ("Write", {"file_path": "/tmp/fix.sh", "content": "sed -i '' 's/a/b/' src/shop/cart.py"}, "ok"),
        ("bash", "chmod +x /tmp/fix.sh && /tmp/fix.sh", ""),
    ],
    "Write apply.py then uv run --script": [
        (
            "Write",
            {"file_path": "/tmp/apply.py", "content": "import shutil; shutil.copy('/tmp/new.py','src/shop/cart.py')"},
            "ok",
        ),
        ("bash", "uv run --script /tmp/apply.py", ""),
    ],
    "extensionless script by shebang": [
        ("Write", {"file_path": "/tmp/fixit", "content": "#!/bin/sh\nsed -i '' 's/a/b/' src/shop/cart.py"}, "ok"),
        ("bash", "sh /tmp/fixit", ""),
    ],
    "patch from a Write-tool patch file, next to a tests mention": [
        ("Write", {"file_path": "/tmp/x.patch", "content": "--- a/src/shop/cart.py\n+++ b/src/shop/cart.py"}, "ok"),
        ("bash", "patch -p1 < /tmp/x.patch && uv run pytest -q tests/test_cart.py 2>&1 | tail -3", ""),
    ],
    "git apply next to a tests mention": [
        ("Write", {"file_path": "/tmp/x.patch", "content": "--- a/src/shop/cart.py"}, "ok"),
        ("bash", "git apply /tmp/x.patch; uv run pytest -q tests/ 2>&1 | tail -3", ""),
    ],
    "ruff check --fix . next to a tests mention": [
        ("bash", "uv run ruff check --fix . ; uv run pytest -q tests/ 2>&1 | tail -3", "")
    ],
    "black . next to a tests mention": [("bash", "uv run black . && uv run pytest tests/test_cart.py -q", "")],
    "script run next to a tests mention": [
        ("Write", {"file_path": "/work/ws/apply.py", "content": "open('src/shop/cart.py','a').write('#')"}, "ok"),
        ("bash", "python3 apply.py && uv run pytest -q tests/", ""),
    ],
    "from shutil import copy": [
        ("bash", "python3 -c \"from shutil import copy; copy('/tmp/n.py','src/shop/cart.py')\"", "")
    ],
    "from os import replace": [
        ("bash", "python3 -c \"from os import replace; replace('/tmp/n.py','src/shop/cart.py')\"", "")
    ],
    "Path.replace": [
        ("bash", "python3 -c \"from pathlib import Path; Path('/tmp/n.py').replace('src/shop/cart.py')\"", "")
    ],
    "open mode through a variable": [
        ("bash", "python3 -c \"m='w'; f=open('src/shop/cart.py', m); f=None\"", "")
    ],
    "sed w command": [("bash", "sed -n '1w src/shop/cart.py' /tmp/n.py", "")],
    "gsed -i": [("bash", "gsed -i 's/a/b/' src/shop/cart.py", "")],
    "autoflake -i": [("bash", "uv run autoflake -i src/shop/cart.py", "")],
    "backslash cp": [("bash", "\\cp /tmp/n.py src/shop/cart.py", "")],
    "ditto": [("bash", "ditto /tmp/n.py src/shop/cart.py", "")],
    "git checkout-index": [("bash", "git checkout-index -f -a", "")],
    "git filter-branch": [("bash", "git filter-branch --tree-filter 'true' HEAD", "")],
    "eval base64": [
        ("bash", "eval \"$(echo c2VkIC1pICcnICdzL2EvYi8nIHNyYy9zaG9wL2NhcnQucHk= | base64 -d)\"", "")
    ],
    "uv run python -m scripts.apply": [("bash", "uv run python -m scripts.apply", "")],
    "exec(open(...).read())": [("bash", "python3 -c \"exec(open('/tmp/s.py').read())\"", "")],
    "git stash list": [("bash", "git stash list", "")],
    "placeholder write ahead of a hidden src write": [
        ("bash", "sed -n '1w src/shop/cart.py' /tmp/n.py", ""),
        ("bash", "touch tests/x", ""),
    ],
    "undetected write, red from the broken src, touch tests/x as the test write": [
        ("bash", "sed -n '1w src/shop/cart.py' /tmp/broken.py", ""),
        ("bash", "touch tests/x", ""),
    ],
    "undetected write then ruff format tests/": [
        ("bash", "gsed -i 's/a/b/' src/shop/cart.py", ""),
        ("bash", "uv run ruff format tests/", ""),
    ],
}


@pytest.mark.parametrize("label", sorted(UNDETECTED_FIRST_WRITES))
def test_an_undetected_first_write_can_not_be_followed_by_a_credited_red(label):
    steps = UNDETECTED_FIRST_WRITES[label]
    assert _fooled(steps) is False
    red_only = [*steps, ("bash", "uv run pytest -q 2>&1 | tail -5", RED), ("bash", SRC_FIX, "")]
    assert _credited(red_only) is False


# --------------------------------------------------------------------------- the real shapes (a)-(e)


def test_the_five_real_shapes_classify_none_none_none_tests_source():
    skill = _event("Skill", {"skill": "workbench:tdd"}, 0, content="Launching skill")
    assert classify_write_event(skill) == "none"
    inspect = (
        "git status --short | head; find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print"
        " | head -50; cat docs/plan.md; cat pyproject.toml"
    )
    assert classify_bash_command("cd /work/ws && " + inspect) == "none"
    assert classify_bash_command("cd /work/ws && cat src/shop/*.py tests/*.py; uv run pytest -q 2>&1 | tail -5") == "none"
    assert classify_bash_command("cd /work/ws && " + TEST_WRITE_AND_RUN) == "tests"
    assert classify_bash_command("cd /work/ws && " + SRC_FIX) == "source"


# --------------------------------------------------------------------------- honest shapes

INSPECT = [
    ("Skill", {"skill": "workbench:tdd"}, "ok"),
    ("bash", "git status --short | head; find . -path ./.git -prune -o -type f -print | head -50", ""),
    ("bash", "cat src/shop/*.py tests/*.py; uv run pytest -q 2>&1 | tail -5", GREEN),
]
GREEN_STEP = ("bash", "uv run pytest -q 2>&1 | tail -3", GREEN)
FIX = ("bash", SRC_FIX, "")
RUN = "uv run pytest -q 2>&1 | tail -5"


def _tw(body=BODY):
    return "cat >> tests/test_cart.py <<'EOF'\n\n\n" + body + "\nEOF"


PY_TESTS = (
    "python3 - <<'EOF'\np='tests/test_cart.py'\ns=open(p).read()\nopen(p,'a').write(" + repr(BODY) + ")\nEOF\n" + RUN
)
HONEST = {
    "(d) tests append and pytest in one call": (
        True,
        [("bash", _tw() + "\nuv run pytest -q 2>&1 | tail -15", RED), FIX, GREEN_STEP],
    ),
    "(a) Write tool test then a separate pytest -x": (
        True,
        [
            ("Write", {"file_path": "/w/ws/tests/test_bulk.py", "content": BODY}, "ok"),
            ("bash", "uv run pytest tests/test_bulk.py -x -q", RED),
            FIX,
            GREEN_STEP,
        ],
    ),
    "Edit tool test then pytest --no-header": (
        True,
        [
            ("Edit", {"file_path": "/w/ws/tests/test_cart.py", "old_string": "a", "new_string": "b"}, "ok"),
            ("bash", "uv run pytest -q --no-header | tail -3", RED),
            FIX,
            GREEN_STEP,
        ],
    ),
    "tests, then a src stub, then red": (
        False,
        [
            ("bash", _tw(), ""),
            ("bash", "python3 - <<'EOF'\nopen('src/shop/cart.py','a').write('\\n#stub')\nEOF", ""),
            ("bash", RUN, RED),
            FIX,
            GREEN_STEP,
        ],
    ),
    "git diff after the test write": (
        True,
        [("bash", _tw(), ""), ("bash", "git diff", ""), ("bash", RUN, RED), FIX, GREEN_STEP],
    ),
    "mkdir -p tests/x and cat > tests/x/test_y.py": (
        True,
        [
            (
                "bash",
                "mkdir -p tests/x && cat > tests/x/test_y.py <<'EOF'\n" + BODY + "\nEOF\nuv run pytest -q tests 2>&1|tail -5",
                RED,
            ),
            FIX,
            GREEN_STEP,
        ],
    ),
    "cd to an absolute workdir, tests and pytest": (
        True,
        [("bash", "cd /Users/me/work/ws && " + _tw() + "\n" + RUN, RED), FIX, GREEN_STEP],
    ),
    "Edit tool test under a workdir with a src segment": (
        True,
        [
            ("Edit", {"file_path": "/Users/me/src/ws/tests/test_cart.py", "old_string": "a", "new_string": "b"}, "ok"),
            ("bash", "cd /Users/me/src/ws && " + RUN, RED),
            FIX,
            GREEN_STEP,
        ],
    ),
    "tests through a python heredoc with a literal path variable": (True, [("bash", PY_TESTS, RED), FIX, GREEN_STEP]),
    "tests for behaviour one, then source for both": (
        True,
        [("bash", _tw() + "\n" + RUN, RED), FIX, GREEN_STEP],
    ),
    # misses under the allow-list or the src-token rule: each costs the hit, none can earn one
    "ruff format tests/ (a bare directory) before the red": (
        False,
        [("bash", _tw(), ""), ("bash", "uv run ruff format tests/", ""), ("bash", RUN, RED), FIX, GREEN_STEP],
    ),
    "a src import in the test body": (
        False,
        [("bash", _tw("from src.shop.cart import LineItem\n" + BODY) + "\n" + RUN, RED), FIX, GREEN_STEP],
    ),
    "a src comment in the test body": (
        False,
        [("bash", _tw("# covers src/shop/cart.py\n" + BODY) + "\n" + RUN, RED), FIX, GREEN_STEP],
    ),
    "a workdir path with a src segment": (
        False,
        [
            ("bash", "cd /Users/me/src/ws && " + _tw() + "\n" + RUN, RED),
            ("bash", "cd /Users/me/src/ws && " + SRC_FIX, ""),
            GREEN_STEP,
        ],
    ),
    "pytest piped to tee": (
        False,
        [
            ("bash", _tw(), ""),
            ("bash", "uv run pytest -q 2>&1 | tee /tmp/out.txt | tail -15", RED),
            FIX,
            GREEN_STEP,
        ],
    ),
    "pytest redirected to a file": (
        False,
        [
            ("bash", _tw(), ""),
            ("bash", "uv run pytest -q > /tmp/pytest.log 2>&1; tail -15 /tmp/pytest.log", RED),
            FIX,
            GREEN_STEP,
        ],
    ),
    "rm -rf .pytest_cache before the red": (
        False,
        [("bash", _tw(), ""), ("bash", "rm -rf .pytest_cache && " + RUN, RED), FIX, GREEN_STEP],
    ),
    "git checkout -b at the start": (
        False,
        [("bash", "git checkout -b feat/bulk", ""), ("bash", _tw() + "\n" + RUN, RED), FIX, GREEN_STEP],
    ),
    "PYTHONPATH=src on the pytest line": (
        False,
        [("bash", _tw() + "\nPYTHONPATH=src uv run pytest -q 2>&1|tail -5", RED), FIX, GREEN_STEP],
    ),
    "ls src in the test-write call": (
        False,
        [("bash", "ls src; " + _tw() + "\n" + RUN, RED), FIX, GREEN_STEP],
    ),
    "a summary-only red": (
        False,
        [("bash", _tw() + "\nuv run pytest -q 2>&1 | tail -1", "1 failed, 4 passed in 0.02s\n"), FIX, GREEN_STEP],
    ),
}


@pytest.mark.parametrize("label", sorted(HONEST))
def test_honest_test_first_shapes_stay_credited_and_the_known_misses_stay_misses(label):
    expected, steps = HONEST[label]
    assert _credited(INSPECT + steps) is expected, label


# --------------------------------------------------------------------------- the allow-list itself


@pytest.mark.parametrize(
    "command",
    [
        "cat src/shop/*.py",
        "ls -la src",
        "grep -rn x src/ | head",
        "git status",
        "git diff HEAD -- src/",
        "git log --oneline -5",
        "git show HEAD:src/shop/cart.py",
        "git branch -a",
        "git branch --list",
        "git rev-parse HEAD",
        "git ls-files",
        "git remote -v",
        "git config --get user.name",
        "git blame src/shop/cart.py",
        "git describe --tags",
        "find . -name '*.py' -print",
        "find src -type f | head",
        "head -5 x",
        "tail -5 x",
        "wc -l x",
        "sort x | uniq -c",
        "diff a b",
        "cmp a b",
        "echo hi",
        "printf '%s' hi",
        "pwd",
        "cd src",
        "which python",
        "type ls",
        "true",
        "false",
        "test -f x",
        "[ -f x ]",
        "sleep 1",
        "date",
        "tree src",
        "stat x",
        "file x",
        "du -sh .",
        "tr a b",
        "cut -d, -f1 x",
        "jq . x",
        "less x",
        "more x",
        "awk '{print $1}' x",
        "awk '$1 >= 3' x",
        "sed -n '1,5p' x",
        "sed 's/a/b/' x",
        "uv run pytest",
        "pytest -q",
        "python -m pytest",
        "python3 -m pytest -x",
        "uv run python -m pytest",
        "uvx pytest",
        "uv run ruff check src",
        "ruff check .",
        "ruff format --check .",
        "ruff format --diff .",
        "black --check .",
        "isort --diff .",
        "mypy src",
        "uv run mypy src",
        'python3 -c "print(1)"',
        "python3 -c \"print(open('x').read())\"",
        "python3 - <<'EOF'\nprint(open('x').read())\nEOF",
        "python3 <<'EOF'\nimport sys\nsys.stdout.write('x')\nEOF",
        "cat <<'EOF' | python3\nprint(1)\nEOF",
        "cat <<'EOF'\nrm -rf src\nEOF",
        "echo $(date)",
        "echo `pwd`",
        "LANG=C uv run pytest -q",
        "ls | xargs cat",
        "cat x 2>&1",
        "cat x > /dev/null",
        "cat x 2>/dev/null",
        "cat x >&2",
        "echo hi >/dev/stderr",
        "cat x 1>&2",
        "bash -c 'ls src'",
        "eval 'ls src'",
        "if [ -f x ]; then echo ok; fi",
        "sudo cat x",
        "env LANG=C ls",
        "command ls",
        "nohup ls",
        "time ls",
        "nice -n 1 ls",
    ],
)
def test_allow_listed_read_only_commands_are_none(command):
    assert classify_bash_command(command) == "none"
    assert bash_write_offset(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "gsed -i 's/a/b/' x",
        "ditto a b",
        "sd a b x",
        "rename s/a/b/ x",
        "autoflake -i x",
        "docformatter -i x",
        "pyupgrade x",
        "2to3 -w x",
        "git checkout-index -a",
        "git filter-branch x",
        "git checkout .",
        "git stash",
        "git stash list",
        "git add .",
        "git commit -m x",
        "git branch newbranch",
        "git remote add x y",
        "git config user.name x",
        "git fetch",
        "git -C . checkout .",
        "\\cp a b",
        "/bin/rm x",
        "/bin/cp a b",
        "command cp a b",
        "env X=1 cp a b",
        "sudo cp a b",
        "nohup cp a b",
        "time cp a b",
        "nice -n 1 cp a b",
        "exec cp a b",
        "python x.py",
        "python3 /tmp/fix.py",
        "uv run python path/x.py",
        "uv run --script f",
        "bash f.sh",
        "sh f",
        "./f",
        "source f",
        ". f",
        "node f.js",
        "ruby f.rb",
        "perl f.pl",
        'node -e "1"',
        "perl -ne 'print' x",
        "make fmt",
        "make",
        "just build",
        "npm run build",
        "uv run mytool",
        "uv sync",
        "uv add x",
        "uv pip install x",
        "pip install x",
        "python3 -m scripts.apply",
        "python3 -m py_compile x",
        "python3 -m venv .v",
        "ruff check --fix .",
        "ruff check --fix-only .",
        "ruff check --unsafe-fixes .",
        "ruff format .",
        "black .",
        "isort .",
        "prettier --check .",
        "sed -i 's/a/b/' x",
        "sed -i'' s/a/b/ x",
        "sed -ni p x",
        "sed --in-place s/a/b/ x",
        "sed -n 'w out' x",
        "sed -n '1w out' x",
        "sed 's/a/b/w out' x",
        "sed 's/a/b/gw out' x",
        "sed 's/a/b/ge' x",
        "awk -i inplace '{print}' x",
        "awk -f p x",
        "awk '{print > \"f\"}' x",
        "awk 'BEGIN{system(\"ls\")}'",
        "awk '{print >> \"f\"}' x",
        "find . -exec rm {} +",
        "find . -execdir rm {} +",
        "find . -ok rm {} +",
        "find . -delete",
        "find . -fprint f",
        "find . -fls f",
        "find . -fprintf f x",
        "sort -o f x",
        "sort --output=f x",
        "uniq a b",
        "tree -o f",
        "date -s now",
        "xargs rm",
        "ls | xargs rm",
        "echo x | xargs sed -i s/a/b/",
        "python3 -c \"open('f','w')\"",
        "python3 -c \"open('f', m)\"",
        'python3 -c "import shutil"',
        'python3 -c "from os import replace"',
        'python3 -c "import subprocess"',
        "python3 -c \"exec('1')\"",
        "python3 -c \"eval('1')\"",
        "python3 -c \"__import__('os')\"",
        "python3 -c \"import os; os.system('ls')\"",
        'python3 -c "import fileinput"',
        "python3 -c \"x.write_text('a')\"",
        "python3 -c \"from pathlib import Path; Path('f').unlink()\"",
        'python3 -c "import os as o"',
        "echo x > f",
        "echo x >> f",
        "echo x >| f",
        "echo x &> f",
        "echo x 1> f",
        "echo x >&f",
        "cat <<'EOF' > f\nx\nEOF",
        "tee f",
        "echo x | tee f",
        "echo x > /dev/nullx",
        "echo x > /dev/null/../f",
        "cp <(echo x) f",
        "echo x > >(cat > f)",
        "exec 3> f",
        "exec 3<> f",
        "curl -o f u",
        "wget u",
        "tar -xf a",
        "unzip a",
        "patch x",
        "git apply x",
        "rsync a b",
        "ln -s a b",
        "touch f",
        "mkdir d",
        "mv a b",
        "rm a",
        "dd of=f",
        "truncate -s0 f",
        "install a b",
        "chmod +x f",
        "pbpaste > f",
        "bash -c 'echo x > f'",
        "sh -c 'cp a b'",
        "eval 'echo x > f'",
        'eval "$CMD"',
        "$CMD",
        "echo $(cp a b)",
        "echo `cp a b`",
        "for f in a; do cp $f b; done",
        "while true; do cp a b; done",
        "pytest --junitxml=f",
        "pytest --basetemp=d",
        "pytest --cov-report=html:d",
        "uv run pytest --snapshot-update",
        "echo 'unterminated",
        "echo $(unterminated",
        "cat <<EOF\nno terminator",
    ],
)
def test_every_other_head_flag_or_redirect_is_not_none(command):
    assert classify_bash_command(command) != "none", command
    assert bash_write_offset(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "sudo cp a src/b",
        "\\cp a src/b",
        "command cp a src/b",
        "env X=1 cp a src/b",
        "/bin/rm src/b",
        "nohup mv a src/b",
        "time cp a src/b",
        "nice cp a src/b",
    ],
)
def test_wrapper_words_and_path_spellings_do_not_hide_a_write_head(command):
    assert classify_bash_command(command) == "source"


def test_none_classified_calls_can_never_count_as_writes():
    events = _events(
        [
            ("bash", "cat src/shop/cart.py; git diff; uv run pytest -q 2>&1 | tail -3", GREEN),
            ("bash", TEST_WRITE_AND_RUN, RED),
            ("bash", SRC_FIX, ""),
        ]
    )
    assert [classify_write_event(e) for e in events] == ["none", "tests", "source"]
    assert _failed_before_first_source_write(events) is True


# --------------------------------------------------------------------------- tests-class rules


@pytest.mark.parametrize(
    "command",
    [
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF",
        "cat > tests/test_new.py <<'EOF'\nx\nEOF",
        "echo x >> tests/test_cart.py",
        "echo x | tee tests/test_cart.py",
        "echo x | tee -a tests/test_cart.py",
        "sed -i 's/a/b/' tests/test_cart.py",
        "sed -i '' 's/a/b/' tests/test_cart.py",
        "perl -pi -e 's/a/b/' tests/test_cart.py",
        "touch tests/test_new.py",
        "mkdir -p tests/x",
        "cp a tests/b",
        "cp -r a tests/",
        "mv tests/a tests/b",
        "rm tests/test_old.py",
        "python3 - <<'EOF'\nopen('tests/test_cart.py','a').write('x')\nEOF",
        "python3 - <<'EOF'\np='tests/test_cart.py'\nopen(p,'w').write('x')\nEOF",
        "python3 -c \"from pathlib import Path; Path('tests/test_cart.py').write_text('x')\"",
        "cd /work/shop && cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nuv run pytest -q 2>&1 | tail -5",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\ncat >> tests/test_checkout.py <<'EOF'\ny\nEOF",
        "cat >> test_cart.py <<'EOF'\nx\nEOF",
        "cat >> conftest.py <<'EOF'\nx\nEOF",
    ],
)
def test_a_recognised_write_aimed_at_a_literal_tests_path_is_tests(command):
    assert classify_bash_command(command) == "tests"


@pytest.mark.parametrize(
    "command",
    [
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\ncp a /tmp/b",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\npatch -p1 < p",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\ngit apply p",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nruff check --fix .",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nblack .",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nruff format .",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nruff format tests/",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nruff format tests/*.py",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nrsync -a a/ b/",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nfind . -exec rm {} +",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nls | xargs rm",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\npython3 fix.py",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nuv run pytest --junitxml=r.xml",
        "cat >> tests/test_cart.py <<'EOF'\nx\nEOF\nuv run pytest -q | tee /tmp/o",
        "cat >> $F <<'EOF'\nx\nEOF\necho tests/x",
        "cat >> tests/*.py <<'EOF'\nx\nEOF",
        "cat >> tests/../b.py <<'EOF'\nx\nEOF",
        "cat >> tests/test_cart.py <<'EOF'\n# the src/ package\nEOF",
        "cat >> tests/test_cart.py <<'EOF'\nsrc = 1\nEOF",
        "cd src && cat >> ../tests/test_cart.py <<'EOF'\nx\nEOF",
        "cp tests/test_cart.py src/shop/",
        "mv a tests/b",
        "rm a tests/b",
        "cat >> /Users/me/src/ws/tests/test_cart.py <<'EOF'\nx\nEOF",
        "python3 - <<'EOF'\nopen(p,'a').write('x')\nEOF",
        "python3 - <<'EOF'\np=os.path.join('tests','x.py')\nopen(p,'a').write('x')\nEOF",
        "python3 - <<'EOF'\nopen('tests/a.py','a').write('x')\nopen('other.py','a').write('x')\nEOF",
        "python3 - <<'EOF'\nopen('tests/a.py','a').write('x')\nimport shutil\nEOF",
        "python3 - <<'EOF'\np='tests/a.py'\np='b.py'\nopen(p,'a').write('x')\nEOF",
        "python3 - <<'EOF'\np='b.py'\np='tests/a.py'\nopen(p,'a').write('x')\nEOF",
        "bash -c 'echo x >> tests/test_cart.py; cp a b'",
    ],
)
def test_a_write_call_that_is_not_wholly_recognised_tests_only_writes_is_source(command):
    assert classify_bash_command(command) == "source"


def test_appending_tests_and_running_pytest_in_one_call_stays_a_tests_call():
    # The real probe shape: the test write and the red run share one Bash call.
    assert classify_bash_command("cd /work/ws && " + TEST_WRITE_AND_RUN) == "tests"


# --------------------------------------------------------------------------- heredocs, pipes, substitutions


def test_a_heredoc_body_is_data_for_a_read_only_head_and_the_script_for_an_interpreter():
    assert classify_bash_command("cat <<'EOF'\nsed -i s/a/b/ src/x\nEOF") == "none"
    assert classify_bash_command("python3 <<'EOF'\nopen('src/x','w').write('1')\nEOF") == "source"
    assert classify_bash_command("python3 - <<'EOF'\nprint(1)\nEOF") == "none"
    assert classify_bash_command("cat <<'EOF' | python3\nopen('src/x','w').write('1')\nEOF") == "source"
    assert classify_bash_command("cat <<'EOF' | python3\nprint(1)\nEOF") == "none"
    assert classify_bash_command("bash <<'EOF'\ncp a src/b\nEOF") == "source"
    assert classify_bash_command("bash <<'EOF'\nls src\nEOF") == "none"


def test_a_python_script_piped_from_something_other_than_a_heredoc_is_not_read_only():
    assert classify_bash_command("echo 'print(1)' | python3") == "source"
    assert classify_bash_command("cat x.py | python3 -") == "source"


def test_more_than_the_allowed_number_of_open_calls_in_a_script_fails_closed():
    few = 'python3 -c "' + "open('a').read();" * 40 + '"'
    many = 'python3 -c "' + "open('a').read();" * 60 + '"'
    assert classify_bash_command(few) == "none"
    assert classify_bash_command(many) == "source"


def test_more_than_the_allowed_number_of_substitutions_fails_closed():
    assert classify_bash_command("echo " + "$(ls) " * 150) == "none"
    assert classify_bash_command("echo " + "$(ls) " * 300) == "source"


def test_a_command_substitution_and_a_backtick_are_analysed_as_commands():
    assert classify_bash_command("echo $(cp a b)") == "source"
    assert classify_bash_command("echo `cp a b`") == "source"
    assert classify_bash_command('echo "$(cp a b)"') == "source"
    assert classify_bash_command("echo $(echo $(cp a b))") == "source"
    assert classify_bash_command("echo $(ls)") == "none"


def test_a_process_substitution_body_is_analysed_as_commands():
    # a read-only outer command around a write in the body: only the body's own analysis can make these ``source``
    assert classify_bash_command("cat <(cp a src/b)") == "source"
    assert classify_bash_command("diff a <(cp a src/b)") == "source"
    assert classify_bash_command("cat <(echo x > src/b)") == "source"
    assert classify_bash_command("cat <(cp a tests/b)") == "tests"
    assert bash_write_offset("cat <(cp a src/b)") == 6
    # ``>( )`` always leaves an unresolved target, so it is ``source`` whatever its body is
    assert classify_bash_command("cat a > >(cp /dev/stdin src/b)") == "source"
    # a read-only body stays read-only
    assert classify_bash_command("cat <(echo hi)") == "none"
    assert classify_bash_command("diff <(cat a) <(cat b)") == "none"
    assert bash_write_offset("diff <(cat a) <(cat b)") is None


# An unknown command makes the call ``source`` and fixes the offset of the first non-read-only command, whatever
# follows it. Each (class, offset) was read from the classifier at d015a099, before the scan stopped at the first one.
UNKNOWN_THEN_WRITE = [
    ("cat a; foo; cp a src/b", "source", 7),
    ("cat a; foo; cp a tests/test_x.py", "source", 7),
    ("cat a; foo; echo x > src/b", "source", 7),
    ("ls\ncat a | foo | tee src/b", "source", 11),
    ("cat a; foo; (cp a src/b)", "source", 7),
    ("cat a; foo; cd src; cp a b", "source", 7),
    ("cat a; foo; ls", "source", 7),
    ("echo x > tests/test_a.py; foo; cp a src/b", "source", 0),
    ("echo x > tests/test_a.py; cat a; foo", "source", 0),
]


@pytest.mark.parametrize(("command", "kind", "offset"), UNKNOWN_THEN_WRITE)
def test_an_unknown_command_decides_the_class_and_the_offset_whatever_follows(command, kind, offset):
    assert classify_bash_command(command) == kind
    assert bash_write_offset(command) == offset


def test_a_quoted_operator_is_not_a_separator_and_an_unquoted_one_is():
    assert classify_bash_command("echo 'a; cp a b'") == "none"
    assert classify_bash_command("echo a; cp a b") == "source"
    assert classify_bash_command("ls && cp a b") == "source"
    assert classify_bash_command("ls || cp a b") == "source"
    assert classify_bash_command("ls & cp a b") == "source"
    assert classify_bash_command("ls | cp a b") == "source"


def test_the_pipe_redirect_target_is_a_write_target():
    assert classify_bash_command("echo x >| f") == "source"
    assert classify_bash_command("echo x >| tests/test_cart.py") == "tests"
    assert classify_bash_command("echo x >|src/f") == "source"


def test_an_unbalanced_quote_or_an_unterminated_heredoc_fails_closed():
    for broken in ("echo 'abc", 'echo "abc', "echo $(abc", "echo `abc", "cat <<EOF\nabc", "echo ${abc"):
        assert classify_bash_command(broken) == "source", broken


def test_a_command_at_the_cap_is_scanned_and_one_over_it_is_source():
    assert BASH_COMMAND_CAP == 100_000
    assert classify_bash_command("ls " + "a" * (BASH_COMMAND_CAP - 3)) == "none"
    assert classify_bash_command("ls " + "a" * (BASH_COMMAND_CAP - 2)) == "source"
    assert bash_write_offset("ls " + "a" * BASH_COMMAND_CAP) == 0


# --------------------------------------------------------------------------- offsets


def test_the_offset_is_where_the_first_write_capable_command_starts():
    command = "cat src/x; cd /w; sed -i s/a/b/ src/x; uv run pytest"
    assert bash_write_offset(command) == command.index("sed")
    heredoc = "cd /w && cat >> tests/x <<'EOF'\nbody\nEOF\nuv run pytest -q"
    offset = bash_write_offset(heredoc)
    assert offset is not None
    assert offset < heredoc.rfind("pytest")
    after = "uv run pytest -q; cp a b"
    assert bash_write_offset(after) > after.rfind("pytest")


# --------------------------------------------------------------------------- the edit tools


@pytest.mark.parametrize(
    ("tool", "path", "expected"),
    [
        ("Write", "/tmp/fix.py", "source"),
        ("Edit", "/work/ws/fix.sh", "source"),
        ("MultiEdit", "/work/ws/apply.rb", "source"),
        ("Write", "/work/ws/a.bash", "source"),
        ("Write", "/work/ws/a.zsh", "source"),
        ("Write", "/work/ws/a.pl", "source"),
        ("Write", "/work/ws/a.js", "source"),
        ("Write", "/work/ws/a.mjs", "source"),
        ("Write", "/work/ws/a.ts", "source"),
        ("Write", "/work/ws/notes.md", "none"),
        ("Write", "/work/ws/notes.txt", "none"),
        ("Write", "/work/ws/data.json", "none"),
        ("Write", "/work/ws/pyproject.toml", "none"),
        ("Write", "/work/ws/tests/test_x.py", "tests"),
        ("Write", "/work/ws/tests/helpers.py", "tests"),
        ("Write", "/work/ws/src/shop/x.py", "source"),
    ],
)
def test_an_edit_tool_write_of_a_script_to_a_non_test_path_is_a_source_write(tool, path, expected):
    assert classify_write_event(_event(tool, {"file_path": path, "content": "x"}, 0)) == expected


def test_a_shebang_makes_any_non_test_write_a_source_write():
    assert classify_write_event(_event("Write", {"file_path": "/tmp/fixit", "content": "#!/bin/sh\nx"}, 0)) == "source"
    assert classify_write_event(_event("Write", {"file_path": "/tmp/fixit", "content": "plain"}, 0)) == "none"
    assert classify_write_event(_event("Edit", {"file_path": "/tmp/fixit", "new_string": "#!/bin/sh"}, 0)) == "source"


def test_a_scratch_script_write_followed_by_a_test_first_run_does_not_credit_the_red():
    steps = [
        ("Write", {"file_path": "/tmp/fix.py", "content": "x = 1"}, "ok"),
        ("bash", TEST_WRITE_AND_RUN, RED),
        ("bash", SRC_FIX, ""),
    ]
    assert _credited(steps) is False


# --------------------------------------------------------------------------- bounded time

SIZE = 96_000
SLOW = {
    "echo then test_. chain": "echo x > foo\n" + "test_." * (SIZE // 6),
    "write then echo of test_. words": "echo x > foo\necho " + "test_." * (SIZE // 6),
    "echo then test_x words": "echo x > foo\n" + "test_x " * (SIZE // 7),
    "echo then test_- chain": "echo x > foo\n" + "test_-" * (SIZE // 6),
    "open( with spaces": "echo x\n" + "open( " * (SIZE // 6),
    "pipes": "echo x > foo; " + "a|" * (SIZE // 2),
    "devnull redirects": "echo x " + ">/dev/null " * (SIZE // 11),
    "substitutions": "echo " + "$(echo a) " * (SIZE // 10),
    "nested substitution openers": "echo " + "$(" * 2000,
    "parens": "(" * SIZE,
    "heredoc markers": "cat <<EOF\n" * (SIZE // 11),
    "line continuations": "ls \\\n" * (SIZE // 5),
    "long heredoc body": "cat <<'EOF'\n" + "line of text\n" * (SIZE // 13) + "EOF",
    "long python heredoc": "python3 - <<'EOF'\n" + "x = open('a').read()\n" * (SIZE // 22) + "EOF",
    "many unclosed open( calls in a python script": 'python3 -c "' + "open( " * (SIZE // 6) + '"',
    "many open calls": 'python3 -c "' + "open('a')," * (SIZE // 10) + '"',
    "echo repeated": "echo " * (SIZE // 5),
    "quotes": "'" * SIZE,
    "backslashes": "\\" * SIZE,
    "dollars": "$" * SIZE,
    "angles": "<" * SIZE,
    "ampersands": "&" * SIZE,
    "sed repeated": "sed " * (SIZE // 4),
    "git repeated": "git " * (SIZE // 4),
    "assignments": "x=1 " * (SIZE // 4),
    "wrappers": "sudo " * (SIZE // 5),
    "newlines then src": "\n" * (SIZE - 5) + "src/x",
    "newline and two spaces": "\n  " * (SIZE // 3),
    "assignments and blank lines": "x=1\n\n" * (SIZE // 5),
    "spaces then src": " " * (SIZE - 5) + "src/x",
}


@pytest.mark.parametrize("shape", sorted(SLOW))
def test_classifying_an_adversarial_shape_takes_well_under_half_a_second(shape):
    command = SLOW[shape]
    assert len(command) <= SIZE + 100
    started = time.perf_counter()
    classify_bash_command(command)
    bash_write_offset(command)
    assert time.perf_counter() - started < 0.5, shape
