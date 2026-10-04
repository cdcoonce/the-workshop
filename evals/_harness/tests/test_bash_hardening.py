"""Regression rows for the false ``none`` / ``tests`` classes of the Bash write classifier (#1129).

Three adversarial passes proved shapes that ``classify_bash_command`` returned ``none`` or ``tests`` for while
real bash (or ``/bin/zsh``) wrote under ``src/``. T1 is a gate, so a wrong hit is far worse than a wrong miss, and
each class is closed by tightening toward fail-closed, not by growing a blocklist:

1. a heredoc body is data only for a QUOTED delimiter, and reaches an interpreter only through a bare ``cat``;
2. an environment prefix is accepted only for a short list of harmless names, and wrapper options are ``source``;
3. ``git -c`` is accepted only for presentation keys, and ``--exec-path`` / ``--git-dir`` / ``--work-tree`` are not;
4. ``xargs`` is read-only only over a child that cannot write whatever arguments arrive on stdin;
5. ``sed`` is read by a hand scanner over the script, with every option spelled exactly;
6. ``sort``, ``tree`` and ``uniq`` output forms are refused, in every spelling;
7. pytest, mypy, ruff, black and isort are read by an option ALLOW-LIST;
8. an inline python script is parsed with ``ast`` and read by an import and call ALLOW-LIST;
9. a python name is a ``tests`` literal only when it is bound exactly once, by a plain assignment;
10. a zsh-only ``${(`` expansion is ``source``;
11. ``[`` / ``test`` with an unresolved expansion is ``source`` unless it is a double-quoted operand;
13. no regex over user text backtracks (every timing shape below is under half a second).

None of these commands is ever run by a test; only the class is asserted.
"""

from __future__ import annotations

import time

import pytest

from evals._harness.bash_classify import bash_write_offset, classify_bash_command

# --------------------------------------------------------------------------- class 1: heredocs

HEREDOC_SOURCE = [
    "cat <<EOF\n$(cp a src/b)\nEOF",
    "cat <<EOF\n`cp a src/b`\nEOF",
    "python3 - <<EOF\nprint(1) # $(cp a src/b)\nEOF",
    "x='; cp a src/b'\nbash <<EOF\necho $x\nEOF",
    "x='\"); open(\"src/y\",\"w\").write(\"z\"); print(\"'\npython3 - <<EOF\nprint(\"$x\")\nEOF",
    "cat <<-EOF\n\t$(cp a src/b)\n\tEOF",
    "cat <<EOF\n$HOME\nEOF",
    "cat <<EOF > tests/test_x.py\n$x\nEOF",
    "cat <<EOF\n`date`\nEOF",
    # a backslash-newline joins lines in an unquoted body, so ``EO\\<newline>F`` ends the heredoc early in bash and zsh
    "cat <<EOF\nEO\\\nF\ncp a src/b\nEOF",
    "cat <<EOF\nhello \\n\nEOF",
    "cat <<-EOF\n\tEO\\\n\tF\ncp a src/b\n\tEOF",
    "cat <<'EOF' | sed 's/echo/cp/' | bash\necho a src/b\nEOF",
    "cat <<'EOF' | tee /dev/stdout | bash\ncp a src/b\nEOF",
    "cat <<'EOF' | head -5 | sh\ncp a src/b\nEOF",
    "cat <<'EOF' | cat -n | bash\ncp a src/b\nEOF",
    "cat <<'EOF' | tr a b | python3\nopen('src/x','w')\nEOF",
    "cat <<'EOF' | grep -v x | bash\necho hi\nEOF",
    "cat <<'EOF' | cat x | bash\necho hi\nEOF",
    "cat <<'EOF' > tests/test_x.py | bash\necho hi\nEOF",
    "cat <<'EOF' | cat - x | bash\necho hi\nEOF",
    "cat <<'EOF' > /tmp/y | bash\necho hi\nEOF",
    "cat <<'EOF' | python3\nopen('src/x','w').write('1')\nEOF",
]


@pytest.mark.parametrize("command", HEREDOC_SOURCE)
def test_class_1_an_expanding_heredoc_or_a_filtered_script_is_source(command):
    assert classify_bash_command(command) == "source", command
    assert bash_write_offset(command) is not None, command


HEREDOC_NONE = [
    "cat <<'EOF'\n$(cp a src/b)\nEOF",
    "cat <<'EOF'\nEO\\\nF\nEOF",
    'cat <<"EOF"\n$(cp a src/b)\nEOF',
    "cat <<\\EOF\n$(cp a src/b)\nEOF",
    "cat <<-'EOF'\n\t$(cp a src/b)\n\tEOF",
    'cat <<-"EOF"\n\t`cp a src/b`\n\tEOF',
    "cat <<EOF\nplain text, no expansion\nEOF",
    "cat <<EOF\nplain text with a (paren) and a {brace}\nEOF",
    "python3 - <<'EOF'\nprint(1)\nEOF",
    "cat <<'EOF' | python3\nprint(1)\nEOF",
    "cat <<'EOF' | cat | python3\nprint(1)\nEOF",
    "cat <<'EOF' | bash\nls src\nEOF",
    "cat <<'EOF'\nrm -rf src\nEOF",
    "cat <<'EOF' | wc -l\na\nb\nEOF",
]


@pytest.mark.parametrize("command", HEREDOC_NONE)
def test_class_1_a_quoted_heredoc_or_a_plain_unquoted_one_is_data(command):
    assert classify_bash_command(command) == "none", command
    assert bash_write_offset(command) is None, command


def test_class_1_a_plain_unquoted_heredoc_still_appends_a_test():
    command = "cat >> tests/test_cart.py <<EOF\ndef test_a():\n    assert 1\nEOF\nuv run pytest -q 2>&1 | tail -15"
    assert classify_bash_command(command) == "tests"


def test_class_1_the_audited_quoted_test_append_is_still_tests():
    command = "cat >> tests/test_cart.py <<'EOF'\ndef test_a():\n    assert 1 == $x\nEOF\nuv run pytest -q 2>&1 | tail -15"
    assert classify_bash_command(command) == "tests"


# --------------------------------------------------------------------------- class 2: environment and wrappers

ENV_SOURCE = [
    "PYTEST_ADDOPTS='--junitxml=src/x.xml' pytest -q",
    "PYTEST_ADDOPTS='--junitxml=src/x.xml' uv run pytest -q",
    "RUFF_OUTPUT_FILE=src/rx ruff check .",
    "GIT_TRACE=$PWD/src/trace git status",
    "GIT_TRACE=/abs/src/f git status",
    "GIT_EXTERNAL_DIFF='cp a src/b;true' git diff",
    "LESSOPEN='|cp a src/b;cat %s' less x",
    "PS4='$(cp a src/b)' bash -xc true",
    "env -S 'cp a src/b'",
    "env --split-string='cp a src/b'",
    "env -i cat x",
    "env -u HOME cat x",
    "env -C src ls",
    "env -0 cat x",
    "env -- cat x",
    "env PYTEST_ADDOPTS=x cat y",
    "env FOO=1 ls",
    "exec -a cat cp a src/b",
    "exec -c cat x",
    "BASH_ENV=tests/x.sh bash -c true",
    "PYTHONPATH=src uv run pytest -q",
    "FOO=1 uv run pytest -q",
    "LANG=C.UTF-8 FOO=1 cat x",
    "LANG=$X cat x",
    "LANG='a b' cat x",
    "LANG=a\\ b cat x",
    "TZ+=x cat x",
    "TZ=$(cp a src/b) cat x",
    "LANG=a;b cat x",
    "GIT_DIR=x git status",
    "time -p ls",
    "command -v git",
    "nohup -x ls",
    "nice -5 ls",
    "nice -n x ls",
    "nice -n 5 -x ls",
    "nice --adjustment=5 ls",
    "sudo -u x cat a",
    "sudo -n cat a",
    "env FOO=1 cp a src/b",
    "CI=1 cp a src/b",
    "PATH=/x; cat a",
    "HOME=/x; git status",
    "GIT_DIR=x; git status",
    "BASH_ENV=x; cat a",
    "PS4=x; cat a",
    "LD_PRELOAD=x; cat a",
    "PYTHONPATH=src; uv run pytest -q",
    # a ``for`` variable is a shell assignment too
    "for PATH in tests; do cat x; done",
    "for GIT_EXTERNAL_DIFF in 'cp a src/b;true'; do git diff; done",
    "for BASH_ENV in tests/x.sh; do bash -c true; done",
]


@pytest.mark.parametrize("command", ENV_SOURCE)
def test_class_2_an_unlisted_prefix_or_a_wrapper_option_is_source(command):
    assert classify_bash_command(command) == "source", command


ENV_NONE = [
    "LANG=C cat x",
    "LC_ALL=C sort x",
    "LC_CTYPE=en_US.UTF-8 cat x",
    "TZ=UTC date",
    "NO_COLOR=1 uv run pytest -q",
    "FORCE_COLOR=0 ls",
    "CI=1 PYTHONDONTWRITEBYTECODE=1 uv run pytest -q",
    "PYTHONUNBUFFERED=1 python3 -m pytest -q",
    "PYTHONHASHSEED=0 pytest -q",
    "TERM=dumb COLUMNS=200 LINES=50 ls",
    "env LANG=C cat x",
    "env CI=1 uv run pytest -q",
    "LC_ALL=en_US.UTF-8 cat x",
    "TZ=America/New_York,x date",
    "sudo cat x",
    "nohup ls",
    "time ls",
    "nice ls",
    "nice -n 5 ls",
    "command ls",
    "exec cat x",
    "X=$(ls); cat a",
    "x=1; cat a",
    "FILE=x; cat $FILE",
]


@pytest.mark.parametrize("command", ENV_NONE)
def test_class_2_a_listed_prefix_and_a_plain_wrapper_stay_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- class 3: git -c

GIT_SOURCE = [
    "git -c core.fsmonitor='cp a src/b;true' status",
    "git -c diff.external='cp a src/b;true' diff",
    "git -c core.x=1 log",
    "git -c core.pager='cp a src/b' log",
    "git -c core.pager=less log",
    "git -c color.ui=$X log",
    "git -c alias.x=!cp status",
    "git -ccolor.ui=always status",
    "git -c color.ui status",
    "git -c core.quotepath=$x status",
    "git -c core.quotepath='a b' status",
    "git --exec-path=src status",
    "git --exec-path status",
    "git --git-dir=src/.git status",
    "git --git-dir src status",
    "git --work-tree=src status",
    "git --work-tree src status",
    "git --config-env=core.pager=X log",
    "git -C src status",
    "git -C $d status",
    "git -C 's''rc' status",
    "git -C ./src/x diff",
    "git -C /abs/src/shop log",
    "git -C tests -c core.pager='cp a src/b' log",
    "git -C 'a*' status",
    "git --paginate log",
    "git -p log",
    "git --bare status",
    "git --namespace=x status",
    "git --diff.external=x diff",
    "git -C /w -c core.fsmonitor=x status",
    "git diff --outp=src/x",
    "git diff --output=src/x",
    "git log --out src/x",
    "git log --ou=src/x",
    "git show --output-indicator-new=+",
]


@pytest.mark.parametrize("command", GIT_SOURCE)
def test_class_3_a_git_config_or_location_option_is_source(command):
    assert classify_bash_command(command) == "source", command


GIT_NONE = [
    "git -c color.ui=always diff",
    "git -c core.pager=cat log",
    "git -c core.quotepath=false status",
    "git -c color.diff=never -c core.pager=cat diff",
    "git -C /abs/ws status",
    "git -C . log --oneline",
    "git -C /w/repo diff --stat",
    "git --no-pager log -5",
    "git --version",
    "git status --short | head",
    "git diff HEAD -- src/",
    "git log --oneline -5",
    "git show HEAD:src/shop/cart.py",
    "git diff --oneline",
]


@pytest.mark.parametrize("command", GIT_NONE)
def test_class_3_a_presentation_key_and_a_plain_directory_stay_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- class 4: xargs

XARGS_SOURCE = [
    "echo -delete | xargs find src",
    "echo src/x | xargs tee",
    "echo 'x src/ux' | xargs uniq",
    "echo '-o src/sx' | xargs sort x",
    "echo --output=src/x | xargs git diff",
    "echo --fix | xargs ruff check",
    "echo --junitxml=src/x | xargs pytest",
    "ls | xargs sed -i s/a/b/",
    "ls | xargs rm",
    "ls | xargs -P 4 cat",
    "ls | xargs -n 1 -P 2 cat",
    "ls | xargs -r cat",
    "ls | xargs -d x cat",
    "ls | xargs -I% cat %",
    "ls | xargs -I % cat %",
    "ls | xargs -n x cat",
    "ls | xargs -n1 cat",
    "ls | xargs -a f cat",
    "ls | xargs -L 1 cat",
    "ls | xargs -t cat",
    "ls | xargs env cat",
    "ls | xargs nohup cat",
    "ls | xargs sudo cat",
    "ls | xargs -I {} {} x",
    "ls | xargs bash -c 'cat'",
    "ls | xargs cp",
    "ls | xargs cat $x",
    "ls | xargs python3 -c 'print(1)'",
    "ls | xargs sort",
    "ls | xargs find",
    "ls | xargs git status",
    "ls | xargs diff a",
    "ls | xargs cut -f1",
    "ls | xargs tr a b",
    "ls | xargs jq .",
]


@pytest.mark.parametrize("command", XARGS_SOURCE)
def test_class_4_xargs_over_a_child_that_can_write_is_source(command):
    assert classify_bash_command(command) == "source", command


XARGS_NONE = [
    "ls | xargs cat",
    "ls | xargs grep -n x",
    "ls | xargs egrep x",
    "ls | xargs fgrep x",
    "ls | xargs wc -l",
    "find . -name '*.py' | xargs -n 1 head -3",
    "git ls-files | xargs -I {} cat {}",
    "find . -print0 | xargs -0 cat",
    "ls | xargs -0 -n 5 echo",
    "ls | xargs ls -l",
    "ls | xargs tail -n 3",
    "ls | xargs printf '%s\\n'",
    "ls | xargs",
    "ls | xargs /bin/cat",
    "ls | xargs head",
]


@pytest.mark.parametrize("command", XARGS_NONE)
def test_class_4_xargs_over_a_child_that_cannot_write_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- class 5: sed

SED_SOURCE = [
    "sed -n '/x/Iw src/f' x",
    "sed -n '/x/I w src/f' x",
    "sed -n '/x/Mw src/f' x",
    "sed -n '/x/IMw src/f' x",
    "sed -n '\\%x%w src/f' x",
    "sed -n '\\,x,w src/f' x",
    "sed -n '\\|x|Iw src/f' x",
    "sed --in 's/a/b/' src/shop/cart.py",
    "sed --i=.bak 's/a/b/' src/shop/cart.py",
    "sed --in-pl 's/a/b/' src/shop/cart.py",
    "sed --exp='w src/x' f",
    "sed --expression 'p' f",
    "sed --expr=p f",
    "sed --line-length=5 p f",
    "sed --debug p f",
    "sed --follow-symlinks p f",
    "sed --sandbox p f",
    "sed --quie p f",
    "sed --silen p f",
    "sed --regexp p f",
    "sed --null p f",
    "sed --version",
    "sed --help",
    "sed -n 'w src/f' x",
    "sed -n '1w src/f' x",
    "sed -n '1W src/f' x",
    "sed '1e cp a src/b' x",
    "sed '1r src/x' x",
    "sed '1R src/x' x",
    "sed F x",
    "sed z x",
    "sed 's/a/b/w src/f' x",
    "sed 's/a/b/e' x",
    "sed 's/a/b/gw src/f' x",
    "sed 's/a/b/ge' x",
    "sed 's/a/b/W' x",
    "sed -f script x",
    "sed --file=script x",
    "sed -nf script x",
    "sed -s -n '$w src/f' a b",
    "sed -n '/x/{w src/f}' x",
    "sed -n '/x/!w src/f' x",
    "sed -n '1,3w src/f' x",
    "sed 's/a/b/;w src/f' x",
    "sed -e 's/a/b/' -e 'w src/f' x",
    "sed -ne 'w src/f' x",
    "sed -n 's/a/b/;/x/w src/f' x",
    "sed 'y/abc/xyz/;w src/f' x",
    "sed -n '/x/Iwsrc/f' x",
    "sed -i 's/a/b/w src/f' tests/test_x.py",
    "sed 's/[/]/X/w src/f' x",
    "sed 'a\\foo' x",
    "sed 'h;x' x",
    "sed '$!N;P;D' x",
    "sed -n 's/a/b' x",
    "sed -n '/x' x",
    "sed '}' x",
    "sed '{p' x",
    "sed 'p p' x",
    "sed '#n' x",
    "sed -n 's/a/b/Q' x",
    "sed -l 5 p x",
    "sed -b p x",
    "sed -n \"$x\" f",
    "sed -n 's/a/b/\np;w src/f' x",
    "sed -n '/a\nb/p' x",
    "sed 's/a/b\nc/' x",
    "sed 's/a\\\nb/c/' x",
    "sed -n '0w src/f' x",
    "sed -f p x",
    "sed -nf p x",
    "sed -s -f p x",
    "sed --file=p x",
    "sed ,p x",
    "sed -n '1,p' x",
    "sed -n '/x/,w src/f' x",
    "sed 'y/a[b/c/' x",
    # the GNU reading (first unescaped delimiter) and the BSD reading (brackets hide it) end the part in different places
    "sed 's/[/]/g' x",
    "sed 'y/[/]/' x",
    "sed 's/[^/]*$//' x",
]


@pytest.mark.parametrize("command", SED_SOURCE)
def test_class_5_a_sed_the_scanner_cannot_prove_read_only_is_source(command):
    assert classify_bash_command(command) == "source", command


SED_NONE = [
    "sed -n '1,5p' x",
    "sed 's/a/b/' x",
    "sed -n 's/a/b/p' src/shop/cart.py | grep -i foo",
    "sed --silent -e 'p' x",
    "sed --quiet -n --expression=p x",
    "sed -n -e '/x/p' -e '/y/p' x",
    "sed -n '/x/I p' x",
    "sed -n '/x/Ip' x",
    "sed -n '\\%x%Ip' x",
    "sed -n '\\,x,p' x",
    "sed -n '/x/,/y/p' x",
    "sed -n '$p' x",
    "sed -n '2,${p}' x",
    "sed '1d' x",
    "sed '/^#/d' x",
    "sed '/^$/d' x",
    "sed -E 's/(a|b)+/c/g' x",
    "sed -n '/a/,+2p' x",
    "sed -n '/a/,~2p' x",
    "sed 's/a/b/gI' x",
    "sed -n 's/a/b/2p' x",
    "sed 's|a|b|' x",
    "sed 'y/abc/xyz/' x",
    "sed -n '3q;p' x",
    "sed '5q' x",
    "sed '5q5' x",
    "sed -n '$=' x",
    "sed -n l x",
    "sed -n 'l 5' x",
    "sed 's/a/b/;s/c/d/' x",
    "sed -n '/x/{p;q}' x",
    "sed -n '1~2p' x",
    "sed -s -n p a b",
    "sed -n p -",
    "sed 's/[a-z]*/X/' x",
    "sed 's/a\\/b/c/' x",
    "sed -e 's/a/b/' -- x",
    "sed -u -n p x",
    "sed -z 's/a/ /g' x",
    "sed --regexp-extended 's/a+/b/' x",
    "sed --posix p x",
    "sed --separate p x",
    "sed --null-data p x",
    "sed -r 's/a+/b/' x",
    "sed -nE '/a|b/p' x",
    "sed -n '/class\\ Foo/,/^$/p' x",
    "sed -n '/x/!p' x",
    "sed -n '/x/ ! p' x",
    "sed -n '1! p' x",
    "sed '1,3{s/a/b/;p}' x",
    "sed -n '{p}' x",
    "sed -n 'p;p' x",
    "sed -n 'p\np' x",
    "sed 's/a/b/\ns/c/d/' x",
    "sed 's,a,b,g' x",
    "sed -n '0,/x/p' x",
    "sed -n '/x/N;p' x",
    "sed n x",
    "sed 'N;N;s/a/b/' x",
    "sed -n 's/^\\(.*\\)$/\\1/p' x",
    "sed 's/&/and/' x",
    "sed -n \"/x/p\" x",
    "sed 's/[^\\/]*$//' x",
]


@pytest.mark.parametrize("command", SED_NONE)
def test_class_5_a_sed_script_of_read_commands_is_read_only(command):
    assert classify_bash_command(command) == "none", command
    assert bash_write_offset(command) is None, command


SED_TESTS = [
    "sed -i 's/a/b/' tests/test_cart.py",
    "sed -i '' 's/a/b/' tests/test_cart.py",
    "sed -i.bak 's/a/b/' tests/test_cart.py",
    "sed --in-place 's/a/b/' tests/test_cart.py",
    "sed --in-place=.bak 's/a/b/' tests/test_cart.py",
    "sed -ni '1d' tests/test_cart.py",
    "sed -i -e 's/a/b/' tests/test_cart.py",
]


@pytest.mark.parametrize("command", SED_TESTS)
def test_class_5_an_in_place_sed_of_a_tests_file_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# --------------------------------------------------------------------------- class 6: sort, tree, uniq

SORT_SOURCE = [
    "sort -uo src/so x",
    "sort -ro src/so x",
    "sort --ou=src/so x",
    "sort --out=src/so x",
    "sort --output=src/so x",
    "sort --o=src/x x",
    "sort -o src/so x",
    "sort -osrc/so x",
    "sort -nrk2 -o f x",
    "sort -nro f x",
    "sort --compress-program=./x -S 1 x",
    "sort --compress-program ./x x",
    "sort --comp=./x x",
    "sort -T src x",
    "sort -Tsrc x",
    "sort --temporary-directory=src x",
    "sort --temp=src x",
    "sort -S 1 x",
    "sort -m a b",
    "sort --parallel=2 x",
    "tree -ao src/t",
    "tree -o f",
    "tree --output=f",
    "tree --o f",
    "tree -R",
    "tree -aR src",
    "tree --fromfile x",
    "tree -Ho src/x",
    "uniq in out",
    "uniq -c in out",
    "uniq -f 1 in out",
    "uniq -s 1 -w 2 in out",
    "uniq in out extra",
    # BSD uniq does not permute: a word after the input file is the output file, even one that looks like a flag
    "uniq x -c",
    "uniq a -i",
    "uniq -c x --skip-fields=1",
    "uniq x -f1",
    "uniq -- in out",
    "uniq -- -c -d",
]


@pytest.mark.parametrize("command", SORT_SOURCE)
def test_class_6_an_output_form_of_sort_tree_or_uniq_is_source(command):
    assert classify_bash_command(command) == "source", command


SORT_NONE = [
    "sort x",
    "sort -u x",
    "sort -nr x",
    "sort -k2,2 -t, x",
    "sort -t, -k2 x",
    "sort -rn x | head",
    "sort -k2 x",
    "sort -f -b -d x",
    "sort -V x",
    "sort --unique --reverse x",
    "sort -h x",
    "sort -s -k1,1 x",
    "sort -z x",
    "sort -c x",
    "sort -C x",
    "sort -g x",
    "sort -M x",
    "sort -R x",
    "sort -i x",
    "sort -nrk2 x",
    "sort -t ',' -k 2 x",
    "sort --key=2 x",
    "sort --field-separator=, x",
    "sort -k1,1nr x",
    "sort - ",
    "sort -- x",
    "cat x | sort | uniq -c",
    "tree",
    "tree -a",
    "tree -L 2",
    "tree -I __pycache__ -L 2",
    "tree -d",
    "tree src -a --dirsfirst",
    "tree -C -L 2 src",
    "uniq x",
    "uniq -c x",
    "uniq -d x",
    "uniq",
    "uniq -f 1 x",
    "uniq -c -s 2 x",
    "uniq -c < x",
]


@pytest.mark.parametrize("command", SORT_NONE)
def test_class_6_a_read_form_of_sort_tree_or_uniq_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- class 7: option allow-lists

TOOL_SOURCE = [
    "uv run pytest --log-file=src/x.log",
    "uv run pytest --debug=src/d.log",
    "uv run pytest -o cache_dir=src/c",
    "uv run pytest -ocache_dir=src/c",
    "uv run pytest --json-report --json-report-file=src/x",
    "uv run pytest --json-report-file=src/x.json",
    "uv run pytest --junitx=src/x.xml",
    "uv run pytest --alluredir=src/x",
    "uv run pytest --cache-dir=src/c",
    "uv run pytest --basetemp=d",
    "uv run pytest --junitxml=r.xml",
    "pytest --pdb",
    "pytest --fixtures",
    "pytest -p x",
    "pytest -pno:cacheprovider",
    "pytest -p no:cacheprovider -p other",
    "pytest -c cfg",
    "pytest --rootdir=src",
    "pytest @args.txt",
    "pytest -- @args.txt",
    "pytest -q -- tests/a.py @args.txt",
    "pytest -q @args.txt",
    "pytest -rA --tb=weird",
    "pytest --tb=",
    "pytest --maxfail=x",
    "pytest --durations=x",
    "pytest -k",
    "pytest -m",
    "pytest -W",
    "pytest -qx --lf --foo",
    "pytest -v -x -s --trace",
    "pytest --pyargs shop",
    "pytest --import-mode=importlib",
    "pytest --no-cov",
    "pytest -n 4",
    "pytest -r",
    "python -m pytest -p tests.plugin",
    "python3 -m pytest --log-file=src/x",
    "uvx pytest --junitxml=src/x.xml",
    "uv run python -m pytest --log-file=src/x",
    "mypy --junit-xml src/x.xml .",
    "mypy --junit-xml=src/x.xml .",
    "mypy --cache-dir=src/c .",
    "mypy --cache-dir src/c .",
    "mypy --html-report src/r .",
    "mypy --any-exprs-report src/r .",
    "mypy -p shop",
    "mypy @flags",
    "mypy --python-version 3.12 --txt-report src/r .",
    "mypy --python-version",
    "mypy --config-file src/x .",
    "mypy -c 'x=1'",
    "ruff check -osrc/x .",
    "ruff check -o src/x .",
    "ruff check --cache-dir=src/c .",
    "ruff check --output-file=src/x .",
    "ruff check --output-file src/x .",
    "ruff check --add-noqa .",
    "ruff check --fix .",
    "ruff check --fix-only .",
    "ruff check --unsafe-fixes .",
    "ruff check --fix=1 .",
    "ruff check --fixx .",
    "ruff check --config x .",
    "ruff check --no-cache .",
    "ruff check --isolated .",
    "ruff check --exit-zero .",
    "ruff check --select",
    "ruff check --output-format=bogus .",
    "ruff check --output-format=json:src/x .",
    "ruff check --select 'E;cp' .",
    "ruff format -osrc/x .",
    "ruff format --cache-dir=src/c --check .",
    "ruff format --config x --check .",
    "ruff --config src/x format --check .",
    "ruff check --target-version py312 .",
    "ruff format .",
    "ruff format src",
    "black --check --diff --target-version py312 src",
    "black --check --workers 4 .",
    "black --check --diff --verbose src",
    "black .",
    "isort --diff --overwrite-in-place src/x.py",
    "isort --check --overwrite-in-place src/x.py",
    "isort --check --settings-path src .",
    "isort .",
    "isort -c --atomic .",
    "uv run ruff check --fix src",
    "python3 -m ruff check .",
    "python3 -m black --check .",
    "python3 -m mypy src",
    "uv run --directory src pytest",
    "uv run --directory pytest pytest",
    "uv run --project pytest pytest -q",
    "uv run --with-editable pytest pytest",
    "uv run --cache-dir pytest pytest",
    "uv run --env-file pytest pytest",
    "uv run --project src pytest",
    "uv run --with ./src pytest",
    "uv run --with-editable . pytest",
    "uv run --with-requirements r.txt pytest",
    "uv run --cache-dir src/c pytest",
    "uv run --env-file x pytest",
    "uv run --find-links src pytest",
]


@pytest.mark.parametrize("command", TOOL_SOURCE)
def test_class_7_an_option_off_the_allow_list_is_source(command):
    assert classify_bash_command(command) == "source", command


TOOL_NONE = [
    "pytest",
    "pytest -q",
    "pytest -q -x tests/test_a.py",
    "uv run pytest -q -x -s",
    "pytest -k 'a and b' -m slow",
    "pytest --tb=short --no-header",
    "pytest -rA",
    "pytest -rfE --no-summary",
    "pytest --co -q",
    "pytest --collect-only",
    "pytest --lf --ff",
    "pytest --maxfail=2 --durations=10",
    "pytest --disable-warnings -W error",
    "pytest -p no:cacheprovider",
    "pytest --strict-markers tests/test_a.py::test_x",
    "pytest -qq",
    "pytest -vv",
    "pytest -xvs",
    "pytest tests/ -q 2>&1 | tail -5",
    "pytest -- tests/test_a.py",
    "python -m pytest",
    "python3 -m pytest -x",
    "uv run python -m pytest -x",
    "uv run pytest",
    "uvx pytest -q",
    "uv run --with pytest python -m pytest -q",
    "uv run --python 3.12 pytest -q",
    "uv run --no-sync pytest -q",
    "uv run --with pytest --with jsonschema python -m pytest -q --co",
    "mypy src",
    "mypy --strict --ignore-missing-imports src tests",
    "mypy --python-version 3.12 --pretty src",
    "mypy --no-error-summary --show-error-codes --no-incremental --check-untyped-defs .",
    "uv run mypy src",
    "ruff check .",
    "ruff check src/",
    "ruff check --select E,F --ignore E501 src",
    "ruff check --select=E --ignore=E501 src",
    "ruff check --output-format=concise src",
    "ruff check --output-format=json .",
    "ruff check --output-format text .",
    "ruff check --statistics .",
    "ruff check --show-fixes src",
    "ruff check",
    "ruff --version",
    "ruff version",
    "ruff format --check .",
    "ruff format --diff src",
    "ruff format --check -q --line-length 100 .",
    "black --check .",
    "black --diff -q src",
    "black --check --line-length 100 src",
    "isort --check .",
    "isort --diff -q .",
    "isort --check --line-length 100 .",
    "black --check -",
]


@pytest.mark.parametrize("command", TOOL_NONE)
def test_class_7_an_option_on_the_allow_list_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


TOOL_TESTS = [
    "ruff format tests/test_cart.py",
    "black tests/test_cart.py",
    "uv run isort tests/test_cart.py",
    "ruff format -q tests/test_cart.py",
]


@pytest.mark.parametrize("command", TOOL_TESTS)
def test_class_7_a_formatter_of_one_tests_file_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# --------------------------------------------------------------------------- class 8: inline python allow-list


def _py(code: str) -> str:
    return "python3 -c " + "'" + code.replace("'", "'\\''") + "'"


PY_SOURCE_CODE = [
    "import posix; posix.system('cp a src/b')",
    "import os; o=os; o.system('cp a src/b')",
    "import os; vars(os)['system']('cp a src/b')",
    "import sys; sys.modules['os'].system('cp a src/b')",
    "import sqlite3; sqlite3.connect('src/x.db')",
    "import zipfile; zipfile.ZipFile('src/x.zip','w')",
    "import logging; logging.FileHandler('src/log.txt')",
    "import os; os.mkfifo('src/f')",
    "import gzip; print('x', file=gzip.open('src/shop.gz','wt'))",
    "print('x', file=__builtins__.open('src/shop.py','w'))",
    "import os; os.utime('src/x')",
    "import pandas as pd; pd.DataFrame([1]).to_csv('src/x.csv')",
    "import runpy; runpy.run_path('x.py')",
    "import importlib; importlib.import_module('os')",
    "__import__('os').system('cp a src/b')",
    "from os import path",
    "from . import x",
    "import os.path",
    "from typing import *",
    "import os",
    "import subprocess",
    "import shutil",
    "import tempfile",
    "import io",
    "import codecs",
    "import glob",
    "import time",
    "import pathlib as p, os as q",
    "import pathlib; pathlib.os.system('cp a src/b')",
    "import pathlib; pathlib.io.open('src/x', 'w')",
    "import json; json.codecs.open('src/x','w')",
    "import re; re.enum",
    "import sys; sys._getframe().f_builtins['open']('src/x','w')",
    "import sys; sys.meta_path[0].load_module('posix').system('cp a src/b')",
    "from pathlib import os; os.system('cp a src/b')",
    "from json import codecs",
    "from sys import modules",
    "from sys import _getframe",
    "import operator, pathlib; operator.methodcaller('system','cp a src/b')(operator.attrgetter('os')(pathlib))",
    "from operator import attrgetter",
    "import string, pathlib; string.Formatter().get_field('0.os',(pathlib,),{})[0].system('cp a src/b')",
    "import typing; typing.get_type_hints(f)",
    "import pathlib as m; x = m",
    "import pathlib; x = pathlib",
    "import json; print(json)",
    "import json; json = 1",
    "x = getattr",
    "getattr(1, 'x')",
    "setattr(x, 'a', 1)",
    "delattr(x, 'a')",
    "globals()",
    "locals()",
    "exec('1')",
    "eval('1')",
    "compile('1', 'f', 'eval')",
    "breakpoint()",
    "input()",
    "help()",
    "print(().__class__.__mro__)",
    "print(object.__subclasses__())",
    "print(print.__dict__)",
    "x = {}.__class__",
    "import sys; print(sys.modules)",
    "open('src/x', 'w')",
    "open('src/x', mode='w')",
    "open('src/x', 'a')",
    "open('src/x', 'x')",
    "open('src/x', 'r+')",
    "open('f', m)",
    "open('f', 'r', opener=f)",
    "open(*a)",
    "open(**k)",
    "w = open; w('src/x', 'w')",
    "print(open)",
    "f = open('src/x', 'w'); f.write('x')",
    "from pathlib import Path; Path('x').open('w')",
    "from pathlib import Path; Path('x').open(mode='wb')",
    "from pathlib import Path; Path('x').open(*a)",
    "from pathlib import Path; Path('x').write_text('y')",
    "from pathlib import Path; p = Path('tests/x'); p.write_text('y')",
    "from pathlib import Path; Path(a).write_bytes(b'y')",
    "from pathlib import Path; Path('x').touch()",
    "from pathlib import Path; Path('x').mkdir()",
    "from pathlib import Path; Path('x').rename('y')",
    "from pathlib import Path; Path('x').replace('src/y')",
    "from pathlib import Path; Path('x').unlink()",
    "from pathlib import Path; Path('x').rmdir()",
    "from pathlib import Path; Path('x').symlink_to('y')",
    "from pathlib import Path; Path('x').hardlink_to('y')",
    "from pathlib import Path; Path('x').chmod(0)",
    "from pathlib import Path; Path('x').copy('y')",
    "from pathlib import Path; Path('x').move('y')",
    "from pathlib import Path; Path('x').write",
    "x.truncate(0)",
    "x.writelines(['a'])",
    "a.write('x')",
    "print(1",
    "this is not = python",
    "echo hi",
    "def f(:",
    "x = 1 +",
    "import sys; sys.stdout = open('src/x', 'w')",
    "import sys; sys.settrace(f)",
    "import sys; sys.modules",
    "import sys; sys.addaudithook(f)",
    "print(__loader__)",
    "print(__spec__)",
    "print(__file__)",
    "__loader__.load_module('posix').system('touch src/f2')",
    "from pathlib import Path; f = Path('src/f').write_text; f('x')",
    "from pathlib import Path; list(map(Path.touch, [Path('src/f')]))",
    "from pathlib import Path; Path('x').write",
    "import functools; functools.partial(open, 'src/f', 'w')()",
    "import operator; operator.call(open, 'src/f', 'w')",
    "import sys; sys.stdout.write('x'); sys.stdout.writelines(['a']); x.write('y')",
    "import json; json.__dict__",
    "import collections.abc as c; c.sys",
]


def _heredoc_py(code: str) -> str:
    return f"python3 - <<'EOF'\n{code}\nEOF"


PY_SOURCE_ROWS = [_py(code) for code in PY_SOURCE_CODE] + [_heredoc_py(code) for code in PY_SOURCE_CODE]


@pytest.mark.parametrize("command", PY_SOURCE_ROWS)
def test_class_8_an_inline_script_off_the_allow_list_is_source(command):
    assert classify_bash_command(command) == "source", command


PY_SOURCE_COMMANDS = [
    "python3 -mpy_compile src/x.py",
    "python3 -mpy_compile - <<'EOF'\nsrc/shop/cart.py\nEOF",
    "python3 -m py_compile src/x.py",
    "python3 -m json.tool in out",
    "python3 -m json.tool in",
    "python3 -m json.tool --indent 2 in out",
    "python3 -m json.tool in.json",
    "python3 -m json.tool -",
    "python3 -m json.tool --bogus",
    "python3 -m json.tooI",
    "python3 -m http.server",
    "python3 -m compileall src",
    "python3 -m venv .v",
    "python3 -m pip install x",
    "python3 -m scripts.apply",
    "python3 -m",
    "python3 -mpytest",
    "python3 -Im pytest",
    "python3 -um pytest -q",
    "python3 -X importtime -c 'print(1)'",
    "python3 -Xdev -c 'print(1)'",
    "python3 -Wignore -c 'print(1)'",
    "python3 -Q -c 'print(1)'",
    "python3 -x f",
    "python3 -i -c 'print(1)'",
    "python3 -mjson.tool",
    "uv run python -m scripts.apply",
    "uv run python -mpy_compile x",
    "uv run python3 -m py_compile x",
]


@pytest.mark.parametrize("command", PY_SOURCE_COMMANDS)
def test_class_8_a_module_run_or_an_unlisted_interpreter_flag_is_source(command):
    assert classify_bash_command(command) == "source", command


PY_NONE_CODE = [
    "print(1)",
    "print(open('x').read())",
    "print(open('x', 'r').read())",
    "print(open('x', mode='rb').read())",
    "print(open('x', 'rt').read())",
    "import json,sys; print(json.dumps(json.load(sys.stdin)))",
    "import re, sys; print(re.sub('a','b',sys.stdin.read()))",
    "import sys; sys.stdout.write('x')",
    "import sys; sys.stderr.write('x')",
    "import sys; sys.stdout.buffer.write(b'x')",
    "import sys; print('x', file=sys.stderr)",
    "import sys; sys.exit(0)",
    "import sys; print(sys.argv, sys.version_info, sys.platform)",
    "from pathlib import Path; print(Path('x').read_text())",
    "from pathlib import Path; print(sorted(p.name for p in Path('.').glob('*.py')))",
    "import pathlib; print(pathlib.Path('x').exists())",
    "import pathlib; print([p for p in pathlib.Path('.').rglob('*.py')])",
    "from pathlib import Path; print(Path('src/x').open('r', encoding='utf-8').read())",
    "from pathlib import Path; print(Path('x').open().read())",
    "from pathlib import Path; print(Path('x').open('r').read())",
    "from pathlib import Path; print(Path('x').open(mode='rb').read())",
    "import collections, itertools, math; print(math.pi, collections.Counter('aab'))",
    "import datetime, textwrap, decimal, fractions, statistics, ast, re, json, sys, collections, itertools, math, pathlib",
    "import ast; print(ast.dump(ast.parse(open('x').read())))",
    "import collections.abc; print(collections.abc.Mapping)",
    "from collections import abc, Counter",
    "from collections.abc import Mapping",
    "from json import loads, dumps",
    "s = 'abc'\nprint(s.replace('a', 'b'))",
    "s = 'abc'\nprint(s.replace('a', 'b', 1))",
    "x = [1, 2]\nfor i in x:\n    print(i)",
    "print(__name__)",
    "print(1 if __name__ == '__main__' else 2)",
    "import datetime; print(datetime.datetime.now())",
    "def f(x):\n    return x + 1\nprint(f(1))",
    "try:\n    print(open('x').read())\nexcept OSError as e:\n    print(e)",
    "p = 'tests/test_a.py'\nprint(open(p).read())",
    "data = open('src/shop/cart.py').read()\nprint(len(data))",
]


PY_NONE_ROWS = [_py(code) for code in PY_NONE_CODE] + [_heredoc_py(code) for code in PY_NONE_CODE]


@pytest.mark.parametrize("command", PY_NONE_ROWS)
def test_class_8_an_inline_script_on_the_allow_list_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


PY_NONE_COMMANDS = [
    "python3 -m pytest -q",
    "python -m pytest",
    "python3 -m json.tool",
    "cat x | python3 -m json.tool",
    "python3 -m json.tool --sort-keys",
    "python3 -m json.tool --indent 2 --no-ensure-ascii",
    "python3 -u -c 'print(1)'",
    "python3 -B -c 'print(1)'",
    "python3 -W ignore -c 'print(1)'",
    "python3 -uB -m pytest -q",
    "uv run python -m pytest -x",
    "uv run python3 -c 'print(1)'",
    "python3 -",
]


@pytest.mark.parametrize("command", PY_NONE_COMMANDS)
def test_class_8_the_two_listed_modules_and_plain_flags_stay_read_only(command):
    expected = "source" if command == "python3 -" else "none"
    assert classify_bash_command(command) == expected, command


def test_class_8_more_than_fifty_open_calls_fail_closed():
    few = "python3 -c \"" + "open('a').read();" * 40 + "\""
    many = "python3 -c \"" + "open('a').read();" * 60 + "\""
    assert classify_bash_command(few) == "none"
    assert classify_bash_command(many) == "source"


def test_class_8_the_open_mode_is_read_from_the_right_positional():
    # open(path, mode): mode is index 1. A path literal with no write letter must not be mistaken for a read mode.
    assert classify_bash_command(_py("open('src/shop.py', 'w')")) == "source"
    assert classify_bash_command(_py("open('src/shop.py', 'r')")) == "none"
    assert classify_bash_command(_py("from pathlib import Path; Path('src/shop.py').open('w')")) == "source"
    assert classify_bash_command(_py("from pathlib import Path; Path('x').open('r')")) == "none"
    assert classify_bash_command(_py("import pathlib; pathlib.Path('x').open('w')")) == "source"
    assert classify_bash_command(_py("x.open('src/shop.py', 'w')")) == "source"
    assert classify_bash_command(_py("x.open('src/shop.py', mode='w')")) == "source"


PY_TESTS_COMMANDS = [
    "python3 - <<'EOF'\np='tests/test_cart.py'\ns=open(p).read()\ns=s.replace('a','b')\nopen(p,'w').write(s)\nEOF",
    "python3 - <<'EOF'\np='tests/test_cart.py'\nopen(p,'w').write('x')\nEOF",
    "python3 - <<'EOF'\np='tests/test_cart.py'\nopen(p,'a').write('x')\nEOF",
    "python3 - <<'EOF'\nfrom pathlib import Path\nPath('tests/test_a.py').write_text('x')\nEOF",
    "python3 -c \"open('tests/test_a.py','a').write('x')\"",
    "python3 - <<'EOF'\nwith open('tests/test_a.py', 'w') as f:\n    f.write('x')\nEOF",
    "python3 - <<'EOF'\np = 'tests/test_a.py'\nwith open(p) as f:\n    s = f.read()\nwith open(p, 'w') as f:\n    f.write(s.replace('a', 'b'))\nEOF",
    "python3 - <<'EOF'\nopen('tests/a.py','a').write('x')\nopen('tests/b.py','a').write('y')\nEOF",
]


@pytest.mark.parametrize("command", PY_TESTS_COMMANDS)
def test_class_8_an_inline_edit_of_a_literal_tests_file_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# --------------------------------------------------------------------------- class 9: python name rebinding

REBIND_SOURCE = [
    "p = 'tests/test_a.py'\np, q = 'sr' 'c/shop/cart.py', 1\nopen(p, 'w').write('x')",
    "p = 'tests/test_a.py'\n(p := 'sr' 'c/shop/cart.py')\nopen(p, 'w').write('x')",
    "p = 'tests'\np += '/../s'\np += 'rc/shop/cart.py'\nopen(p, 'w').write('x')",
    "p = 'tests/test_a.py'\nfor p in ['src/shop/cart.py']:\n    open(p, 'w').write('x')",
    "p = 'tests/test_a.py'\nwith open('src/x') as p:\n    pass\nopen(p, 'w').write('x')",
    "p = 'tests/test_a.py'\nimport json as p\nopen(p, 'w').write('x')",
    "p = 'tests/test_a.py'\nfrom json import loads as p\nopen(p, 'w').write('x')",
    "p = 'tests/test_a.py'\ndef f(p):\n    open(p, 'w').write('x')\nf('src/x')",
    "p = 'tests/test_a.py'\nf = lambda p: open(p, 'w')\nf('src/x')",
    "p = 'tests/test_a.py'\n[open(p, 'w') for p in ['src/x']]",
    "p = 'tests/test_a.py'\nglobal p\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\ndel p\np = 'src/x'\nopen(p, 'w').write('x')",
    "p: str = 'tests/test_a.py'\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\np = 'tests/b.py'\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\np = 'src/b.py'\nopen(p, 'w').write('x')",
    "p = 'sr' 'c/shop/cart.py'\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\ntry:\n    pass\nexcept Exception as p:\n    pass\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\nclass p: pass\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\ndef p(): pass\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\nq = p + '/x'\nopen(q, 'w').write('x')",
    "p = 'tests/a.py'\nopen(p + 'x', 'w').write('x')",
    "p = 'tests/a.py'\nopen(f'{p}', 'w').write('x')",
    "p = 'tests/a.py'\nopen(p.upper(), 'w').write('x')",
    "p = ['tests/a.py']\nopen(p[0], 'w').write('x')",
    "p = b'tests/a.py'\nopen(p, 'w').write('x')",
    "match 1:\n    case p:\n        pass\np = 'tests/a.py'\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\n(p, q) = ('src/x', 1)\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\n[p, q] = ['src/x', 1]\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\n*p, q = ['src/x', 1]\nopen(p, 'w').write('x')",
    "p = 'tests/a.py'\nfor q in [1]:\n    p = 'src/x'\nopen(p, 'w').write('x')",
]


REBIND_SOURCE_ROWS = [_heredoc_py(code) for code in REBIND_SOURCE]


@pytest.mark.parametrize("command", REBIND_SOURCE_ROWS)
def test_class_9_a_rebound_python_name_is_not_a_tests_literal(command):
    assert classify_bash_command(command) == "source", command


REBIND_TESTS = [
    "p = 'tests/test_a.py'\nopen(p, 'w').write('x')",
    "p = q = 'tests/test_a.py'\nopen(p, 'a').write('x')\nopen(q, 'a').write('y')",
    "p = 'tests/test_a.py'\nwith open(p, 'a') as f:\n    f.write('x')",
]


REBIND_TESTS_ROWS = [_heredoc_py(code) for code in REBIND_TESTS]


@pytest.mark.parametrize("command", REBIND_TESTS_ROWS)
def test_class_9_a_name_bound_once_to_a_tests_literal_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# --------------------------------------------------------------------------- class 10: zsh-only expansion flags

ZSH_SOURCE = [
    "x='$(cp a src/b)'; echo ${(e)x}",
    "echo ${(e)x}",
    'echo "${(e)x}"',
    "echo ${(@)x}",
    "echo ${(j:,:)x}",
    "echo '${(e)x}'",
    "bash -c 'echo ${(e)x}'",
    "cat <<'EOF'\n${(e)x}\nEOF",
    "for f in a; do echo ${(e)f}; done",
    "echo ${${(e)x}}",
]


@pytest.mark.parametrize("command", ZSH_SOURCE)
def test_class_10_a_zsh_expansion_flag_is_source(command):
    assert classify_bash_command(command) == "source", command


ZSH_NONE = [
    "echo ${x}",
    "echo ${x:-y}",
    "echo $(x)",
    "echo ${f%.py}",
]


@pytest.mark.parametrize("command", ZSH_NONE)
def test_class_10_a_plain_parameter_expansion_stays_read_only(command):
    expected = "none" if command != "echo $(x)" else "source"
    assert classify_bash_command(command) == expected, command


# --------------------------------------------------------------------------- class 11: [ and test operands

TEST_SOURCE = [
    "x='a -a -v b[$(cp q src/z)]'; [ -e $x ]",
    "x='a -a -v b[$(cp q src/z)]'; test -e $x",
    "x='a -a -v b[$(cp q src/z)]'; [ -e \"$x\" -a $x ]",
    "[ -f $f ]",
    "test -f $f",
    "[ ! -f $f ]",
    "[ -n a -a -f $f ]",
    "[ a = $x ]",
    "[ 1 -eq $x ]",
    "[ $x = a ]",
    '[ "$x" = a ]',
    '[ ! "$x" ]',
    '[ -f a -a "$x" ]',
    '[ -f a -o "$x" -a b ]',
    '[ "$x" "$y" ]',
    '[ a "$x" b ]',
    "[ -z $x ]",
    '[ ( "$x" ) ]',
    '[ \\( "$x" \\) ]',
    '[ $n -gt 0 ]',
    '[ "$n" -gt 0 ]',
    '[ 1 -eq "$x" ]',
    "[ 1 -eq 'a[$(cp q src/z)]' ]",
    "[ 'a[$(cp q src/z)]' -eq 1 ]",
    "test 1 -lt abc",
    "[ a -eq 1 ]",
    "[ -n x -a 2 -ne 'y' ]",
    '[ -f "$a" "$b" ]',
    '[ -f "$f"x ]',
    '[ -f x"$f" ]',
    '[ -f "a""$f" ]',
    '[ -f "a\\"$f" ]',
    '[ -f \'$f\'"$f" ]',
    '[ -v "$x" ]',
    '[ -R "$x" ]',
    '[ -a "$x" ]',
    '[ -o "$x" ]',
    '[ -t "$x" ]',
    "[ -e ${x} ]",
    '[ -f "${x}" -a "${y}" ]',
    '[ -f "a" ] && [ "$x" ]',
    "for f in a; do [ -f $f ] && cat $f; done",
    "test -f $(echo x)",
]


@pytest.mark.parametrize("command", TEST_SOURCE)
def test_class_11_an_unresolved_or_arithmetic_test_operand_outside_the_safe_shape_is_source(command):
    assert classify_bash_command(command) == "source", command


TEST_NONE = [
    '[ -f "$f" ]',
    'test -f "$f"',
    '[ ! -f "$f" ]',
    '[ -n a -a -f "$f" ]',
    '[ a = "$x" ]',
    '[ x != "$x" ]',
    "[ 1 -eq 1 ]",
    '[ -z "$x" ]',
    '[ -d "$d" ] && cat a',
    '[ -s "$f" ]',
    '[ a -nt "$f" ]',
    '[ x -ef "$f" ]',
    "[ 5 -gt 3 ]",
    "[ -1 -lt 0 ]",
    "[ +1 -ge 0 ]",
    'if [ -f "$f" ]; then cat "$f"; fi',
    "[ -f x ]",
    "[ -f x -a -d y ]",
    "test -f x",
    "[ a = b ]",
    '[ -L "$f" ]',
    '[ -e "${x}" ]',
    '[ -e "a$x" ]',
    '[ -n "$x" -a -f "$y" ]',
    '[ -n a -o -z "$y" ]',
    "[ a \\< b ]",
    "[ ! -f x ]",
]


@pytest.mark.parametrize("command", TEST_NONE)
def test_class_11_a_double_quoted_operand_after_a_literal_operator_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- an unresolved word in a write head

UNRESOLVED_WRITE_SOURCE = [
    # demonstrated against real bash and BSD sed: this wrote src/f2 and the baseline classified it ``tests``
    "x=$'b/\\nw s'$'rc/f2\\ns/a/b'; sed -i '' \"s/a/$x/\" tests/test_x.py",
    "x='b/;w src/f;s/a/b'; sed -i '' \"s/a/$x/\" tests/test_x.py",
    "x='b/;w src/f;s/a/b'; sed -i \"s/a/$x/\" tests/test_x.py",
    "sed -i `echo p` tests/test_x.py",
    "f='-t src'; cp $f tests/y",
    "x='-t src/'; cp $x tests/y",
    "x=src/f; tee tests/test_x.py $x",
    "x=src/f; touch tests/test_x.py $x",
    "x=src/f; rm tests/test_x.py $x",
    "x=src/f; mkdir tests/d $x",
    "x=-p; mkdir $x tests/d",
    "x=src/f; mv tests/a $x",
    "perl -pi -e \"s/a/$x/\" tests/test_x.py",
    "x=src/f.py; ruff format tests/test_x.py $x",
    "x=src/f.py; black tests/test_x.py $x",
    "x=src/f.py; uv run isort tests/test_x.py $x",
    "echo hi | tee tests/test_a.py $(echo src/f)",
]


@pytest.mark.parametrize("command", UNRESOLVED_WRITE_SOURCE)
def test_a_write_head_with_an_unresolved_word_is_not_a_recognised_write(command):
    assert classify_bash_command(command) == "source", command


UNRESOLVED_WRITE_TESTS = [
    "echo $x | tee tests/test_a.py",
    "cat $f | tee -a tests/test_a.py",
    "x=1; echo hi > tests/test_a.py",
    "echo \"$x\" >> tests/test_a.py",
]


@pytest.mark.parametrize("command", UNRESOLVED_WRITE_TESTS)
def test_an_unresolved_word_in_another_command_of_the_call_does_not_hide_a_tests_write(command):
    assert classify_bash_command(command) == "tests", command


# --------------------------------------------------------------------------- perl -i code is substitutions only

PERL_SOURCE = [
    "perl -pi -e 'use File::Copy; copy(\"a\", \"s\".\"rc/f2\")' tests/test_x.py",
    "perl -pi -e 'BEGIN{ syscall(0) }' tests/test_x.py",
    "perl -ni -e 'print unless /x/' tests/test_x.py",
    "perl -pi -e 'utime(1,1,\"s\".\"rc/f\")' tests/test_x.py",
    "perl -pi -e 's/a/@{[ mkdir(\"s\".\"rc/dd\") ]}/' tests/test_x.py",
    "perl -pi -e 's/a/${\\ system(\"x\")}/' tests/test_x.py",
    "perl -pi -e 's/(?{ system(1) })//' tests/test_x.py",
    "perl -pi -e 's/(??{ system(1) })//' tests/test_x.py",
    "perl -pi -e 's/a/system(1)/e' tests/test_x.py",
    "perl -pi -e 's/a/b/ee' tests/test_x.py",
    "perl -pi -e 's/a/b/r' tests/test_x.py",
    "perl -pi -e 's/a/b/; unlink q(x)' tests/test_x.py",
    "perl -pi -e 's{a}{b}' tests/test_x.py",
    "perl -pi -e 's)a)b)' tests/test_x.py",
    "perl -pi -e 's(a(b(' tests/test_x.py",
    "perl -pi -e 's/a/b' tests/test_x.py",
    "perl -pi -e 's/a/b/ if 1' tests/test_x.py",
    "perl -pi -e 's/a/b/' -e 'use POSIX' tests/test_x.py",
    "perl -pi --foo -e 's/a/b/' tests/test_x.py",
    "perl -F: -pi -e 's/a/b/' tests/test_x.py",
    "perl -Mstrict -pi -e 's/a/b/' tests/test_x.py",
    "perl -pi -e 's/a/b/' tests/test_x.py src/shop/cart.py",
    "perl -pi -e 's/a/b/'",
    "perl -pi",
    "perl -p -e 's/a/b/' tests/test_x.py",
    "perl -pie 's/a/b/' tests/test_x.py",
    "perl -pi -e \"s/a/$x/\" tests/test_x.py",
]


@pytest.mark.parametrize("command", PERL_SOURCE)
def test_perl_an_in_place_program_that_is_not_substitutions_only_is_source(command):
    assert classify_bash_command(command) == "source", command


PERL_TESTS = [
    "perl -pi -e 's/a/b/' tests/test_x.py",
    "perl -pi -e 's/a/b/g' tests/test_x.py",
    "perl -pi -E 's/a/b/g' tests/test_x.py",
    "perl -0pi -e 's/a/b/' tests/test_x.py",
    "perl -pi.bak -e 's/a/b/' tests/test_x.py",
    "perl -i.bak -pe 's/a/b/' tests/test_x.py",
    "perl -pi -e 's|a|b|gi; s,c,d,' tests/test_x.py",
    "perl -pi -e 's/a/b/x; s/c/d/g' tests/test_x.py",
    "perl -pi -e 's#a/b#c#' tests/test_x.py",
    "perl -pi -e 's/a\\/b/c/' tests/test_x.py",
]


@pytest.mark.parametrize("command", PERL_TESTS)
def test_perl_an_in_place_substitution_of_a_tests_file_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# --------------------------------------------------------------------------- class 12/14: awk, file, rg, less, uv, case

AWK_SOURCE = [
    "awk 'BEGIN{print \"a\",\n\"b\" > \"src/f\"}'",
    "awk 'BEGIN{print \"}\" > \"src/f\"}'",
    "awk 'BEGIN{print \";\" > \"src/f\"}'",
    "awk 'BEGIN{print \"x\" \\\n> \"src/f\"}'",
    "awk '{print > \"src/f\"}' x",
    "awk '{print >> \"src/f\"}' x",
    "awk '{ print $1 > \"/dev/stderr\" }' x",
    "awk 'BEGIN{print \"x\" | \"tee src/f\"}'",
    "awk 'BEGIN{printf \"x\" | \"cat\"}'",
    "awk '/\"/ {print \"a\" ; print \"b\" > \"src/f\"} /\"/' x",
    "awk 'BEGIN{system(\"cp a src/b\")}'",
    "awk 'BEGIN{ \"cmd\" | getline x }'",
    "awk '{close(\"x\")}' x",
    "awk -f prog x",
    "awk --file=prog x",
    "awk -i inplace '{print}' x",
    "awk -ifoo '{print}' x",
    "awk --include=x p",
    "awk -d p x",
    "awk -p p x",
    "awk -o p x",
    "awk --profile=src/x p x",
    "awk --dump-variables=src/x p x",
    "awk -E x",
    "awk -l x p",
    "awk '@include \"x\"' f",
    "awk '@load \"x\"' f",
    "gawk -i inplace '{print}' x",
    "awk -F, '{ if ($1 > 3) print $2 }' x",
    "awk '$1 > 3 {print}' x",
    "awk '{print $1}' > src/x",
]


@pytest.mark.parametrize("command", AWK_SOURCE)
def test_awk_a_program_with_an_output_form_or_an_unlisted_option_is_source(command):
    assert classify_bash_command(command) == "source", command


AWK_NONE = [
    "awk '{print $1}' x",
    "awk '{print $1, $2}' x",
    "awk '$1 >= 3' x",
    "awk '$1 > 3' x",
    "awk -F, '{print $1}' x",
    "awk -F ',' '{print $1}' x",
    "awk -v n=3 '{print $n}' x",
    "awk -vn=3 '{print $n}' x",
    "awk 'NR==1' x",
    "awk '/x/ {print}' x",
    "awk 'BEGIN{x=1; print x}'",
    "awk '{s+=$1} END{print s}' x",
    "awk '$1==1 || $2==2 {print}' x",
    "awk 'length > 3' x",
    "awk '{print $1}' x y",
    "awk -- '{print $1}' x",
    "cat x | awk '{print $1}'",
]


@pytest.mark.parametrize("command", AWK_NONE)
def test_awk_a_program_with_no_output_form_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


EXTRA_SOURCE = [
    "cat f | less -o src/x",
    "less -o src/x f",
    "less +'!cp a src/b' f",
    "less --log-file=src/x f",
    "more +/x f",
    "less -N x",
    "file -C -m src/magic",
    "file --compile x",
    "file --com x",
    "file -bC x",
    "rg --hostname-bin=./x foo",
    "rg --hostname-bin ./x foo",
    "rg --pre ./x foo",
    "rg --pre=./x foo",
    "cat > Src/test_x.py <<'EOF'\nx\nEOF",
    "cat > SRC/shop/cart.py <<'EOF'\nx\nEOF",
    "cd Src; echo hi > conftest.py",
    "cd SRC && cat > test_x.py <<'EOF'\nx\nEOF",
    "echo hi > Src/tests/x.py",
    "echo hi > tests/Src/x.py",
]


@pytest.mark.parametrize("command", EXTRA_SOURCE)
def test_other_programs_that_run_or_write_through_an_option_are_source(command):
    assert classify_bash_command(command) == "source", command


EXTRA_NONE = [
    "less x",
    "more x",
    "file x",
    "file -b x",
    "file -i x",
    "rg foo src",
    "rg -n foo",
    "rg -l --hidden foo",
    "git diff --stat",
    "git log -p --ext-diff -1",
    "git blame --contents x f",
    "git ls-files -o --exclude-from=x",
    "git remote show origin",
    "git branch -vv",
    "git describe --always",
    "git diff -Osrc/x",
    "git show --textconv HEAD:x",
    "git config --get --file x foo",
]


@pytest.mark.parametrize("command", EXTRA_NONE)
def test_other_programs_without_a_running_or_writing_option_stay_read_only(command):
    assert classify_bash_command(command) == "none", command


# --------------------------------------------------------------------------- class 13: bounded time

LIMIT = 0.5


def _timed(command: str) -> float:
    from evals._harness import bash_classify

    bash_classify._top_effect.cache_clear()
    started = time.perf_counter()
    classify_bash_command(command)
    bash_write_offset(command)
    return time.perf_counter() - started


@pytest.mark.parametrize("k", [24, 40, 200])
def test_class_13_a_sed_address_of_nested_quantifier_shape_is_fast(k):
    command = "sed -n '/class" + "\\.x" * k + "/p' f"
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "none"


def test_class_13_a_sed_script_over_the_size_cap_is_source_and_fast():
    command = "sed -n '/class" + "\\.x" * 3000 + "/p' f"
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "source"


@pytest.mark.parametrize("k", [36, 44, 500, 30_000])
def test_class_13_a_sed_substitution_of_backslashes_is_fast_and_source(k):
    command = "sed 's/" + "\\" * k + "' f"
    assert _timed(command) < LIMIT
    assert classify_bash_command(command) == "source"


@pytest.mark.parametrize(
    "command",
    [
        "sed 's/" + "\\\\" * 30 + "/x/' f",
        "sed 's/a/" + "\\\\" * 40 + "/' f",
        "sed -n '" + "{" * 5000 + "p" + "}" * 5000 + "' f",
        "sed -n '" + "1p;" * 20_000 + "' f",
        "sed -n '" + "/a/I,/b/I!{" * 2000 + "p" + "}" * 2000 + "' f",
        "sed 's/" + "[" * 20_000 + "/x/' f",
        "sed 's/" + "[a" * 10_000 + "/x/' f",
        "sed 'y/" + "a" * 40_000 + "/" + "b" * 40_000 + "/' f",
        "sed " + "-e p " * 15_000 + "f",
        "awk '" + "print " * 10_000 + "' f",
        "awk '" + "(" * 20_000 + "' f",
        "awk -v " + "x=1 -v " * 10_000 + "x=1 p",
        "xargs " + "-n 1 " * 15_000 + "cat",
        "git " + "-c color.ui=always " * 4_000 + "log",
        "pytest " + "-q " * 30_000,
        "sort " + "-u " * 30_000 + "x",
        "env " + "LANG=C " * 10_000 + "cat x",
        "LANG=C " * 10_000 + "cat x",
        "python3 -c '" + "1+" * 20_000 + "1'",
        "python3 -c '" + "(" * 20_000 + "1" + ")" * 20_000 + "'",
        "python3 -c '" + "x=1;" * 20_000 + "'",
        "python3 -c '" + "[" * 5_000 + "]" * 5_000 + "'",
        "python3 -c '" + "a." * 20_000 + "b'",
        "python3 -c '" + "not " * 20_000 + "1'",
        "python3 -c '" + "lambda:" * 5_000 + "1'",
        "python3 -c '" + "if 1:\\n" + "'",
        "python3 - <<'EOF'\n" + "p = 'tests/a.py'\n" * 5_000 + "EOF",
        "python3 - <<'EOF'\n" + "import json\n" * 8_000 + "EOF",
        "python3 - <<'EOF'\n" + "import os\n" * 8_000 + "EOF",
        "[ " + "-n a -a " * 10_000 + "-n b ]",
        "[ " + "\"$x\" = a " * 10_000 + "]",
        "cat <<EOF\n" + "$x\n" * 20_000 + "EOF",
        "cat <<EOF\n" + "x\n" * 40_000 + "EOF",
    ],
)
def test_class_13_adversarial_script_shapes_are_linear_not_exponential(command):
    assert len(command) <= 100_000
    assert _timed(command) < LIMIT


# --------------------------------------------------------------------------- round 4 (#1129): the fourth pass
#
# A fourth adversarial pass ran real bash 3.2, zsh, BSD sed and perl against the classifier and found classes
# that wrote under ``lib/`` or ``src/`` while the classifier said ``none`` or ``tests``. Every row below is a
# command the pass demonstrated (or the isolating variant of one rule), expected ``source``; the controls stay
# ``none`` / ``tests``. No row is ever run.

R4_PY_SOURCE_CODE = [
    # P1: singledispatch.register evals a STRING annotation (get_type_hints)
    "import functools\n@functools.singledispatch\ndef f(x): pass\n@f.register\ndef _(x: \"__import__('os').system('touch lib/hit')\"): pass",
    # P2: a string.Formatter subclass captures exec through a format string
    "import string\nL=[]\nclass F(string.Formatter):\n    def format_field(self, v, s):\n        L.append(v); return ''\ndef f(): pass\nF().format('{0.__globals__[__builtins__].exec}', f)\nL[0]('open(\"lib/hit\",\"w\")')",
    # the import allow-list lost string operator functools typing dataclasses enum
    "import functools",
    "import string",
    "import operator",
    "import typing",
    "import dataclasses",
    "import enum",
    "from functools import reduce",
    "from string import Formatter",
    "from typing import List",
    "from dataclasses import dataclass",
    "import enum as e",
    # a class of any kind is write-capable
    "class A: pass",
    "import json\nclass A(json.JSONEncoder): pass",
    "class A:\n    def f(self): return 1\nprint(A().f())",
    # a decorator on any function
    "def d(f): return f\n@d\ndef g(): pass",
    "import json\n@json.loads\ndef g(): pass",
    "def d(f): return f\n@d\nasync def g(): pass",
    # an annotation that is not a bare builtin name (a string annotation is evaluated by get_type_hints)
    "def f(x: \"int\"): pass",
    "def f(x) -> \"int\": pass",
    "x: \"int\" = 1",
    "def f(*a: \"int\"): pass",
    "def f(**k: \"int\"): pass",
    "def f(*, k: \"int\" = 1): pass",
    "import json\ndef f(x: json.JSONDecoder): pass",
    "def f(x: list[int]): pass",
    "def f(x: int | str): pass",
    "def f(x: object): pass",
    "def f(x: Foo): pass",
    "def f() -> object: pass",
    "x: list[str] = []",
    # P3: type() and object reach the class of a stream's raw object
    "import sys\ntype(sys.stdout.buffer.raw)('lib/hit','w')",
    "import sys\nF=type(sys.stdin.buffer.raw)\nF('lib/hit','w').write(b'x')\nfrom pathlib import Path\nPath('tests/test_a.py').write_text('')",
    "print(type(1))",
    "x = object()",
    "print(object)",
    # P3: a call whose func is a call, a subscript, a lambda or another expression
    "def f():\n    return print\nf()('x')",
    "x = [print]\nx[0]('a')",
    "print((lambda: 1)())",
    "(print if 1 else print)('x')",
    "import json\njson.loads('1')()",
    "d = {'k': print}\nd['k']('a')",
    "f = print\n(f)('x')\n(f or print)('y')",
    # P4: Path is pathlib's constructor only when bound once by an import
    "import pathlib\ndef Path(p): return pathlib.Path('lib/hit')\nPath('tests/test_a.py').write_text('x')",
    "import pathlib\nPath = lambda p: pathlib.Path('lib/hit')\nPath('tests/test_a.py').write_text('x')",
    "Path('tests/test_a.py').write_text('x')",
    "from json import loads as Path\nPath('tests/test_a.py').write_text('x')",
    "import json as Path\nPath('tests/test_a.py').write_text('x')",
    "from pathlib import Path\nfor Path in []:\n    pass\nPath('tests/test_a.py').write_text('x')",
    "from pathlib import Path\ndef f(Path): Path('tests/test_a.py').write_text('x')\nf(print)",
    "from pathlib import Path\nPath = 1",
    "from pathlib import Path\nfrom pathlib import Path\nPath('tests/test_a.py').write_text('x')",
    "from pathlib import PosixPath as Path\nPath('tests/test_a.py').write_text('x')",
    "import pathlib\ndef f(pathlib): pathlib.Path('tests/test_a.py').write_text('x')\nf(print)",
    "import pathlib\ndef pathlib(): pass\npathlib.Path('tests/test_a.py').write_text('x')",
    "import pathlib\nfor pathlib in []:\n    pass",
    "import pathlib\nimport json as pathlib\npathlib.Path('tests/test_a.py').write_text('x')",
    "import pathlib\npathlib.PosixPath('tests/test_a.py').write_text('x')",
    "import pathlib\n(Path := pathlib.Path)\nPath('tests/test_a.py').write_text('x')",
    "import pathlib\nwith open('x') as Path:\n    pass",
    # P5: sys.path decides what a later import loads; sys is read-only
    "open('tests/json.py','w').write('import os\\nos.system(\"touch lib/hit\")')\nimport sys\nsys.path.insert(0,'tests')\nimport json",
    "import sys\nprint(sys.path)",
    "from sys import path",
    "import sys\nsys.argv.append('x')",
    "import sys\nsys.argv[0] = 'x'",
    "import sys\nsys.stdout.encoding = 'x'",
    "import sys\ndel sys.argv[0]",
    "import sys\nsys.argv += ['x']",
    "import sys\nsys.argv.insert(0, 'x')",
    "import sys\nsys.argv.extend(['x'])",
    "import sys\nsys.argv.sort()",
    # PEP 695 forms are evaluated by the machinery too
    "type X = int",
    "def f[T](x): return x",
    # the honest cost: shapes that were read-only before this round and are source now
    "import sys; sys.path.insert(0, 'src/'); print(sys.path[0])",
    "import datetime, textwrap, decimal, fractions, statistics, string, operator, functools, typing, dataclasses, enum, ast",
    "from dataclasses import dataclass\n@dataclass\nclass A:\n    x: int\nprint(A(1))",
    "import operator; print(operator.itemgetter(0)([1]))",
    "import functools; print(functools.reduce(lambda a, b: a + b, [1, 2]))",
    "import typing; x: typing.List[int] = []",
    "import string; print(string.ascii_letters)",
]

R4_PY_SOURCE = [_heredoc_py(code) for code in R4_PY_SOURCE_CODE] + [_py(code) for code in R4_PY_SOURCE_CODE]


@pytest.mark.parametrize("command", R4_PY_SOURCE)
def test_round4_an_inline_python_shape_the_reader_cannot_prove_is_source(command):
    assert classify_bash_command(command) == "source", command


R4_PY_NONE_CODE = [
    "def f(x):\n    return x + 1\nprint(f(1))",
    "def f(x: int, y: str = 'a', *a: float, k: bool = True, **kw: dict) -> list:\n    return [x]\nprint(f(1))",
    "def f() -> None:\n    pass\nf()",
    "def f(x: bytes, y: set, z: tuple): pass",
    "x: int = 1\nprint(x)",
    "f = lambda x: x + 1\nprint(f(1))",
    "print(sorted(map(lambda x: x * 2, [3, 1])))",
    "import sys\nprint(sys.argv, sys.version_info, sys.platform, sys.maxsize)",
    "import sys\nsys.stdout.write('x')\nsys.stdout.flush()",
    "import sys\nprint(sys.stdin.read())",
    "print(open('x').read())",
    "print(','.join(['a', 'b']))",
    "import json\nprint(json.dumps({'a': 1}).encode())",
    "import json\nprint(json.load(open('x'))['a'].items())",
    "from pathlib import Path\nprint(Path('x').read_text())",
    "import pathlib\nprint(pathlib.Path('x').read_text())",
    "import re, json, ast, collections, itertools, math, textwrap, decimal, fractions, statistics, datetime, pathlib, sys",
    "from datetime import datetime\nprint(datetime.now())",
    "import collections\nprint(collections.Counter('aab').most_common(1))",
]
R4_PY_NONE = [_heredoc_py(code) for code in R4_PY_NONE_CODE] + [_py(code) for code in R4_PY_NONE_CODE]


@pytest.mark.parametrize("command", R4_PY_NONE)
def test_round4_the_plain_inline_python_shapes_stay_read_only(command):
    assert classify_bash_command(command) == "none", command


R4_PY_TESTS_CODE = [
    "from pathlib import Path\nPath('tests/test_a.py').write_text('x')",
    "import pathlib\npathlib.Path('tests/test_a.py').write_text('x')",
    "import pathlib as pl\npl.Path('tests/test_a.py').write_bytes(b'x')",
    "from pathlib import Path\ndef f(x: int) -> str:\n    return str(x)\nPath('tests/test_a.py').write_text(f(1))",
]
R4_PY_TESTS = [_heredoc_py(code) for code in R4_PY_TESTS_CODE]


@pytest.mark.parametrize("command", R4_PY_TESTS)
def test_round4_a_path_bound_once_by_its_import_still_writes_tests(command):
    assert classify_bash_command(command) == "tests", command


# Q: perl -i code and the backup suffix
R4_PERL_SOURCE = [
    "perl -i -pe 's/a/$#{[system(q(touch lib\\/hit))]}/' tests/f",
    "perl -i -pe 's/a/$#x/' tests/test_a.py",
    "perl -i -pe 's/a/$(touch x)/' tests/test_a.py",
    "perl -i -pe 's/a/$[/' tests/test_a.py",
    "perl -i -pe 's/a/${\\ system(q(touch lib\\/hit))}/' tests/test_a.py",
    "perl -i -pe 's/a/$x/' tests/test_a.py",
    "perl -i -pe 's/a$/b/' tests/test_a.py",
    "perl -i -pe 's/a/b$/' tests/test_a.py",
    "perl -i -pe 's/a/@x/' tests/test_a.py",
    "perl -i -pe 's/a/@{[system(q(touch lib\\/hit))]}/' tests/test_a.py",
    "perl -i -pe 's/a/%h/' tests/test_a.py",
    "perl -i -pe 's%a%b%' tests/test_a.py",
    "perl -i -pe 's/a/`touch lib\\/hit`/' tests/test_a.py",
    "perl -i -pe 's/(?{ system(1) })//' tests/test_a.py",
    "perl -i -pe 's/(??{ system(1) })//' tests/test_a.py",
    "perl -i -pe 's/a/\\e/' tests/test_a.py",
    "perl -i -pe 's/a/b/e' tests/test_a.py",
    "perl -pi'lib/*' -e 's/a/b/' test_a.py",
    "perl -pi'lib/x' -e 's/a/b/' tests/test_a.py",
    "perl -pi'*' -e 's/a/b/' tests/test_a.py",
    "perl -pi'../x' -e 's/a/b/' tests/test_a.py",
    "perl -i'a b' -pe 's/a/b/' tests/test_a.py",
    "perl -i'.bak/' -pe 's/a/b/' tests/test_a.py",
    "perl -pi'$x' -e 's/a/b/' tests/test_a.py",
    "perl -0777 -pi -e 's/\\n+$/\\n/' tests/test_x.py",
    "perl -pi'a;b' -e 's/a/b/' tests/test_a.py",
    "perl -i'a|b' -pe 's/a/b/' tests/test_a.py",
]


@pytest.mark.parametrize("command", R4_PERL_SOURCE)
def test_round4_a_perl_in_place_script_or_backup_suffix_outside_the_narrow_form_is_source(command):
    assert classify_bash_command(command) == "source", command


R4_PERL_TESTS = [
    "perl -i -pe 's/a/b/' tests/test_a.py",
    "perl -pi.bak -e 's/a/b/' tests/test_a.py",
    "perl -pi~ -e 's/a/b/' tests/test_a.py",
    "perl -pi_old-1 -e 's/a/b/' tests/test_a.py",
    "perl -i.orig -pe 's/a/b/g' tests/test_a.py",
    "perl -i -pe 's/(a)(b)/$2$1/g' tests/test_a.py",
    "perl -i -pe 's/a/<$&>/' tests/test_a.py",
]


@pytest.mark.parametrize("command", R4_PERL_TESTS)
def test_round4_the_narrow_perl_in_place_form_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# R: an @argfile through an option value or an attached value, for every allow-listed tool
R4_ARGFILE_SOURCE = [
    "printf -- 'x\\n--junitxml=lib/out.xml\\n' > tests/a.txt; pytest -q -k @tests/a.txt tests/",
    "pytest -k @tests/a.txt",
    "pytest -m @tests/a.txt",
    "pytest -W @tests/a.txt",
    "pytest -k=@tests/a.txt",
    "pytest --maxfail=@tests/a.txt",
    "pytest --tb=@tests/a.txt",
    "pytest --durations=@tests/a.txt",
    "pytest -p @tests/a.txt",
    "pytest -q @tests/a.txt",
    "pytest -q -- @tests/a.txt",
    "pytest -q tests/ @tests/a.txt",
    "py.test -k @tests/a.txt",
    "uv run pytest -k @tests/a.txt",
    "uv run --with pytest pytest -m @tests/a.txt",
    "python3 -m pytest -k @tests/a.txt",
    "uv run python -m pytest -W @tests/a.txt",
    "mypy @tests/a.txt",
    "mypy --python-version @tests/a.txt f",
    "mypy --python-version=@tests/a.txt f",
    "mypy --strict @tests/a.txt",
    "ruff check @tests/a.txt",
    "ruff check --select @tests/a.txt",
    "ruff check --select=@tests/a.txt",
    "ruff check --ignore=@tests/a.txt .",
    "ruff check --output-format=@tests/a.txt .",
    "ruff format --check @tests/a.txt",
    "ruff format --line-length=@tests/a.txt --check .",
    "black --check @tests/a.txt",
    "black --check --line-length=@tests/a.txt .",
    "black --diff @tests/a.txt",
    "isort --check @tests/a.txt",
    "isort --check --line-length @tests/a.txt .",
    "uv run ruff check @tests/a.txt",
    "uv run mypy @tests/a.txt",
]


@pytest.mark.parametrize("command", R4_ARGFILE_SOURCE)
def test_round4_an_argfile_word_or_option_value_is_source_for_every_allow_listed_tool(command):
    assert classify_bash_command(command) == "source", command


R4_ARGFILE_NONE = [
    "pytest -q -k foo tests/",
    "pytest -q -k 'a and not b' -m slow tests/",
    "pytest -W ignore tests/",
    "mypy --strict src/",
    "ruff check --select E,F .",
    "black --check --line-length 100 .",
    "isort --check .",
    "uv run pytest -q tests/test_cart.py -k test_x",
    "echo @x | cat",
]


@pytest.mark.parametrize("command", R4_ARGFILE_NONE)
def test_round4_a_plain_option_value_still_reads_only(command):
    assert classify_bash_command(command) == "none", command


# S: the shell scanner reads only what it can parse with certainty
R4_SHELL_SOURCE = [
    # S1: a heredoc delimiter with a mid-word quote
    "cat <<E\"O\"F\nEOF\ntouch lib/hit\nE",
    "cat <<E'O'F\nEOF\ntouch lib/hit\nE",
    "cat <<E\\OF\nEOF\ntouch lib/hit\nE",
    "cat <<'EOF'x\nEOFx\ntouch lib/hit\nEOF",
    "cat <<\"EOF\"x\nEOFx\ntouch lib/hit\nEOF",
    "cat <<x'EOF'\nxEOF\ntouch lib/hit\nEOF",
    # S2: a delimiter with a trailing non-word character
    "cat <<EOF#x\nEOF#x\ntouch lib/hit\nEOF",
    "cat <<EOF:x\nEOF:x\ntouch lib/hit\nEOF",
    "cat <<EOF=x\nEOF=x\ntouch lib/hit\nEOF",
    "cat <<EOF,x\nEOF,x\nrm -f x\nEOF",
    "cat <<EOF+x\nEOF+x\ntouch lib/hit\nEOF",
    "cat <<EOF@x\nEOF@x\ntouch lib/hit\nEOF",
    "cat <<EOF\\\nEOF\ntouch lib/hit",
    "cat <<EOF`x`\nEOFx\ntouch lib/hit\nEOF",
    "cat <<1\n1\ntouch lib/hit",
    "cat <<''\n\ntouch lib/hit",
    "cat <<'EO F'\nEO F\ntouch lib/hit",
    "cat <<1\nhello\n1",
    "cat <<'EO F'\nhello\nEO F",
    "cat <<'EOF$x'\nhello\nEOF$x",
    "cat <<''\nhello\n",
    "cat <<\"EO F\"\nhello\nEO F",
    "cat <<'EOF$x'\nEOF$x\ntouch lib/hit",
    "cat <<-'EOF'x\nEOFx\ntouch lib/hit",
    # S3: a file-descriptor duplication glued to a word
    "ls 2>&1#; echo x > src/cart.py",
    "echo hi >&2foo",
    "echo hi >&2foo; touch lib/hit",
    "ls 2>&1x",
    "ls 2>&-x",
    "cat <&0x",
    "echo >&1-x",
    "echo >&1#; touch lib/hit",
    "echo hi >&2src/x",
    "ls 2>&1\\x",
    "ls 2>&1\"x\"",
    "ls 2>&1$x",
    "ls 2>&1`x`",
    "echo >&out.txt",
    "echo >&lib/hit",
    # zsh takes ``>&1-`` for a file named ``1-``; only bash reads it as a descriptor move
    "ls >&1-",
    "ls 2>&1-",
    "cat <&0-",
    "echo hi >&2-; touch lib/hit",
    # S4: an ANSI-C or locale-translated quote
    "echo $'it\\'s' ; touch lib/hit # don't",
    "echo $'x'",
    "echo $\"x\"",
    "cat $'a\\nb'",
    "echo a$'b'",
    "echo $'\\x27'; touch lib/hit",
    # S5: a backslash in a command substitution body
    "echo \"$(echo \\) ; echo x > src/cart.py)\"",
    "echo $(echo \\x)",
    "echo `echo \\x`",
    "echo ${x:-\\}}; touch lib/hit",
    # S6: a comment in a command substitution body
    "echo \"$(echo a # )\ntouch lib/hit\n)\"",
    "echo $(echo a#b)",
    "echo $(echo a # b)",
    "echo `echo a#b`",
    "echo ${x#a}",
    "echo ${#x}",
    "echo ${x##*/}",
    "echo ${f#tests/}",
    "echo ${#f}",
    "echo ${f%.py#}",
    # S7: a quote in a command substitution or parameter expansion body
    "echo ${x:-\"}\"}; touch lib/hit # \"",
    "echo ${x:-'}'}; touch lib/hit # '",
    "echo ${x:-\"a\"}",
    "echo $(echo \"x\")",
    "echo $(echo 'x')",
    "echo $(grep -c '#' f)",
    "echo `echo \"x\"`",
    "echo `echo 'x'`",
    "ls $(git log --format=\"%h\" -1)",
    "echo \"$(echo \"x\")\"",
    # embedded newline and carriage return in a body
    "echo $(echo a\nb)",
    "echo `echo a\nb`",
    "echo ${x:-a\nb}",
    "echo \"$(echo a\ntouch lib/hit\n)\"",
    "echo $(echo a\r)",
    # S8: a carriage return or another control character anywhere
    "echo a\r# ; touch lib/hit",
    "echo a\rb",
    "ls\r",
    "ls\r\n",
    "cat x\x00y",
    "cat x\x07",
    "cat x\x1b[0m",
    "cat x\x0b",
    "cat x\x0c",
    "cat x\x01",
    "cat <<'EOF'\nx\ry\nEOF",
    "cat <<EOF\r\nx\r\nEOF\r",
    "echo 'a\rb'",
    "echo \"a\rb\"",
]


@pytest.mark.parametrize("command", R4_SHELL_SOURCE)
def test_round4_a_shell_shape_the_scanner_cannot_parse_with_certainty_is_source(command):
    assert classify_bash_command(command) == "source", command


R4_SHELL_NONE = [
    "cat <<EOF\nhello\nEOF",
    "cat <<'EOF'\nhello\nEOF",
    "cat <<\"EOF\"\n$x $(touch lib/hit)\nEOF",
    "cat <<'EOF'\n$x $(touch lib/hit)\nEOF",
    "cat <<\\EOF\n$x $(touch lib/hit)\nEOF",
    "cat <<-EOF\n\thello\n\tEOF",
    "cat <<-'EOF'\n\thello\n\tEOF",
    "cat <<EOF_1.x-y\nhello\nEOF_1.x-y",
    "cat <<_E\nhello\n_E",
    "cat <<EOF | head\nx\nEOF",
    "cat <<EOF;ls\nx\nEOF",
    "cat <<EOF&\nx\nEOF",
    "(cat <<EOF\nx\nEOF\n)",
    "cat << EOF\nx\nEOF",
    "cat <<'EOF' | wc -l\nx\nEOF",
    "ls 2>&1",
    "ls 2>&1 | head",
    "ls 2>&1; ls",
    "ls 2>&1\nls",
    "echo hi >&2",
    "echo hi 1>&2",
    "echo a >&2; echo b",
    "cat x 2>/dev/null",
    "ls 2>&-",
    "ls 2>&1 >/dev/null",
    "(ls 2>&1)",
    "cat <&0",
    "grep 'a$' f",
    "grep -E '^x$' f | head",
    "echo \"a$\"",
    "echo \"cost: \\$5\"",
    "echo $HOME",
    "echo ${HOME}",
    "echo \"${HOME}\"",
    "echo \"${HOME}/x\"",
    "echo ${HOME:-x}",
    "echo $(pwd)",
    "echo \"$(pwd)\"",
    "echo `pwd`",
    "ls $(git rev-parse --show-toplevel)",
    "cat \"$(git rev-parse --show-toplevel)/README.md\"",
    "echo $(echo a | tr a b)",
    "echo $(cat x | wc -l)",
    "cat\tx",
    "echo a\techo",
    "echo 'a\tb'",
]


@pytest.mark.parametrize("command", R4_SHELL_NONE)
def test_round4_the_plain_shell_shapes_stay_read_only(command):
    assert classify_bash_command(command) == "none", command


R4_SHELL_TESTS = [
    "echo hi >&tests/test_a.py",
    "echo hi > tests/test_a.py 2>&1",
    "cat > tests/test_a.py <<'EOF'\nx\nEOF",
    "cat >> tests/test_a.py <<EOF\nx\nEOF",
]


@pytest.mark.parametrize("command", R4_SHELL_TESTS)
def test_round4_a_plain_redirect_of_a_tests_file_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


# T: a path-qualified head, and the GNU target options of cp and mv
R4_HEAD_SOURCE = [
    "./cat f",
    "lib/cat f",
    "tests/cat f",
    "../cat f",
    "/tmp/cat f",
    "/usr/local/sbin/cat f",
    "/bin/../tmp/cat f",
    "//tmp/cat f",
    "/bin//cat f",
    "/usr/bin/./cat f",
    "/binx/cat f",
    "bin/cat f",
    "./ls",
    "./git status",
    "lib/git log",
    "./grep x f",
    "./env cat f",
    "lib/nohup cat f",
    "./time cat f",
    "/tmp/sudo cat f",
    "./nice cat f",
    "./command cat f",
    "xargs ./cat",
    "xargs lib/cat",
    "echo x | xargs /tmp/cat",
    "uv run lib/pytest",
    "uv run ./pytest -q",
    "uv run .venv/bin/pytest -q",
    ".venv/bin/pytest -q",
    "./pytest -q",
    "lib/python3 -c 'print(1)'",
    "/usr/bin/lib/cat f",
    "/bin/cat/ f",
    "./sed -n 1p f",
    "lib/awk '{print}' f",
]


@pytest.mark.parametrize("command", R4_HEAD_SOURCE)
def test_round4_a_path_qualified_head_outside_the_system_bin_directories_is_source(command):
    assert classify_bash_command(command) == "source", command


R4_HEAD_NONE = [
    "/bin/cat f",
    "/usr/bin/cat f",
    "/usr/local/bin/cat f",
    "/opt/homebrew/bin/cat f",
    "/usr/bin/grep -n x f",
    "/bin/ls -la",
    "/opt/homebrew/bin/jq . f",
    "/usr/bin/git status",
    "/usr/bin/env cat f",
    "xargs /bin/cat",
    "/usr/bin/python3 -c 'print(1)'",
    "/usr/bin/sort f | /usr/bin/uniq",
    "uv run /usr/bin/python3 -c 'print(1)'",
]


@pytest.mark.parametrize("command", R4_HEAD_NONE)
def test_round4_an_absolute_system_bin_head_with_a_listed_basename_stays_read_only(command):
    assert classify_bash_command(command) == "none", command


R4_CP_SOURCE = [
    "cp -rt lib tests/a tests/b",
    "cp --target-directory lib tests/a tests/b",
    "cp --target-directory=lib tests/a tests/b",
    "cp -t lib tests/a",
    "cp -t lib/ tests/test_a.py",
    "cp -Tr tests/a lib",
    "cp -T tests/a lib/b",
    "cp -rT tests/a lib",
    "cp -tlib tests/a",
    "cp -pt lib tests/a",
    "cp --tar lib tests/a",
    "cp --t lib tests/a",
    "cp --target lib tests/a",
    "cp -u tests/a tests/b",
    "cp -l tests/a lib/b",
    "cp -s tests/a lib/b",
    "cp --parents tests/a lib",
    "cp --force tests/a tests/b",
    "cp -x tests/a tests/b",
    "cp -L tests/a tests/b",
    "cp -H tests/a tests/b",
    "cp -d tests/a tests/b",
    "cp -b tests/a tests/b",
    "cp -S x tests/a tests/b",
    "cp -fz tests/a tests/b",
    "cp tests/a -t lib",
    "cp tests/a tests/b -t lib",
    "cp tests/a -rt lib",
    "cp --ff tests/a tests/b",
    "cp --a tests/a tests/b",
    "mv --ff tests/a tests/b",
    "cp -- tests/a -x",
    "mv -- tests/a -x",
    "touch -- tests/a -x",
    "mkdir -- tests/a -x",
    "rm -- tests/a -x",
    "tee -- tests/a -x",
    "mv -t lib tests/a",
    "mv --target-directory lib tests/a",
    "mv --target-directory=lib tests/a",
    "mv -T tests/a lib/b",
    "mv -u tests/a tests/b",
    "mv tests/a -t lib",
    "mv --force tests/a tests/b",
    "ln -t lib tests/a",
    "ln -s tests/a lib/b",
    "install -t lib tests/a",
    "install tests/a lib/b",
]


@pytest.mark.parametrize("command", R4_CP_SOURCE)
def test_round4_a_cp_or_mv_option_outside_the_short_read_set_is_source(command):
    assert classify_bash_command(command) == "source", command


R4_CP_TESTS = [
    "cp tests/a tests/b",
    "cp -r tests/a tests/b",
    "cp -R tests/a tests/b",
    "cp -p tests/a tests/b",
    "cp -a tests/a tests/b",
    "cp -f -v tests/a tests/b",
    "cp -fiv tests/a tests/b",
    "cp -n tests/a tests/b",
    "cp -rfp tests/a tests/b",
    "cp -- tests/a tests/b",
    "cp -v -- tests/a tests/b",
    "cp tests/test_a.py tests/test_b.py",
    "mv tests/a tests/b",
    "mv -f tests/a tests/b",
    "mv -iv tests/a tests/b",
    "mv -n tests/a tests/b",
]


@pytest.mark.parametrize("command", R4_CP_TESTS)
def test_round4_a_cp_or_mv_with_a_short_read_set_option_is_still_tests(command):
    assert classify_bash_command(command) == "tests", command


@pytest.mark.parametrize(
    "command",
    [
        "cat <<" + "a" * 50_000,
        "cat <<'" + "a" * 50_000 + "'",
        "echo $(" + "x" * 50_000 + ")",
        "echo `" + "x" * 50_000 + "`",
        "echo ${" + "x" * 50_000 + "}",
        "echo $(" + "echo " * 5_000 + ")",
        "echo " + "$'" * 5_000,
        "ls 2>&1" + "x" * 50_000,
        "echo " + "\r" * 50_000,
        "echo " + "$(echo a) " * 150,
        "cp " + "-f " * 20_000 + "tests/a tests/b",
        "perl -i -pe '" + "s/a/b/;" * 8_000 + "' tests/a",
        "perl -i -pe 's/a/" + "$1" * 20_000 + "/' tests/a",
        "python3 -c '" + "def f(x: int): pass\n" * 4_000 + "'",
        "python3 -c '" + "import sys\n" * 4_000 + "sys.path'",
    ],
)
def test_round4_the_new_scanners_are_linear(command):
    assert len(command) <= 100_000
    assert _timed(command) < LIMIT


# --------------------------------------------------------------------------- the audited shapes stay put

AUDITED = (
    'cd /w/repo && for f in pyproject.toml src/shop/*.py tests/*.py; do echo "=== $f"; cat $f; done;'
    " uv run pytest -q 2>&1 | tail -15"
)

AUDITED_NONE = [
    AUDITED,
    "git status --short | head",
    "find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50",
    "cat src/shop/*.py tests/*.py; uv run pytest -q 2>&1 | tail -5",
    "cd /w/repo && git diff && uv run pytest -q 2>&1 | tail -15",
    "git log --oneline -5",
    "git diff HEAD -- src/",
    "uv run pytest tests/test_cart.py -q 2>&1 | tail -20",
]


@pytest.mark.parametrize("command", AUDITED_NONE)
def test_the_audited_read_only_inspection_shapes_stay_none(command):
    assert classify_bash_command(command) == "none", command
    assert bash_write_offset(command) is None, command


def test_the_audited_test_append_is_tests_and_the_source_rewrite_is_source():
    append = "cat >> tests/test_cart.py <<'EOF'\n\ndef test_bulk():\n    assert f(1) == 2\nEOF\nuv run pytest -q 2>&1 | tail -15"
    assert classify_bash_command(append) == "tests"
    assert classify_bash_command("cd /w/repo && " + append) == "tests"
    rewrite = (
        "python3 - <<'EOF'\np='src/shop/cart.py'\ns=open(p).read()\ns=s.replace('a','b')\nopen(p,'w').write(s)\nEOF"
    )
    assert classify_bash_command(rewrite) == "source"
    test_edit = rewrite.replace("src/shop/cart.py", "tests/test_cart.py")
    assert classify_bash_command(test_edit) == "tests"
