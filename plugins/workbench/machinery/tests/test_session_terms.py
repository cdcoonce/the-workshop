import importlib.util
import subprocess
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "session_terms", Path(__file__).resolve().parent.parent / "engine" / "session_terms.py"
)
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "seed.md").write_text("seed\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def test_no_commit_this_session_returns_empty(tmp_path):
    repo = _init_repo(tmp_path)
    pre = _head(repo)  # no new commit after this
    assert st.changed_files_since(repo, pre) == []  # the fix: no-op session → no terms


def test_session_commit_lists_its_files(tmp_path):
    repo = _init_repo(tmp_path)
    pre = _head(repo)
    (repo / "a.md").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "session work")
    assert st.changed_files_since(repo, pre) == ["a.md"]


def test_blank_presha_returns_empty(tmp_path):
    repo = _init_repo(tmp_path)
    assert st.changed_files_since(repo, "") == []
