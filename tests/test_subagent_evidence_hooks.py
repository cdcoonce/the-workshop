"""Tests for the snapshot-subagent-start / verify-subagent-evidence hook pair.

Drives both hooks as real subprocesses against a scratch git repo: the start
hook records a baseline, the stop hook compares against it.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
START_HOOK = REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts" / "snapshot-subagent-start.py"
STOP_HOOK = REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts" / "verify-subagent-evidence.py"
GIT_BASELINE = REPO_ROOT / "plugins" / "workbench" / "hooks" / "scripts" / "_git_baseline.py"

_spec = importlib.util.spec_from_file_location("_git_baseline", GIT_BASELINE)
_git_baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_git_baseline)
working_tree_signature = _git_baseline.working_tree_signature


def run(hook_path: Path, payload) -> subprocess.CompletedProcess[str]:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def start(cwd: Path, agent_id: str) -> None:
    result = run(START_HOOK, {"cwd": str(cwd), "agent_id": agent_id})
    assert result.returncode == 0


@pytest.mark.parametrize("payload", ["", "not json", "{ broken"])
def test_start_hook_fails_open_on_malformed_stdin(payload: str) -> None:
    result = run(START_HOOK, payload)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("payload", ["", "not json", "{ broken"])
def test_stop_hook_fails_open_on_malformed_stdin(payload: str) -> None:
    result = run(STOP_HOOK, payload)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_no_completion_claim_never_checks_git(tmp_path: Path) -> None:
    # No git repo at all — if the hook tried to shell out to git it would
    # still fail open, but this also proves the message-gate short-circuits.
    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "a1",
            "last_assistant_message": "Here's what I found during exploration.",
        },
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_no_baseline_snapshot_fails_open(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    # No start hook ran for this agent_id — nothing to compare against.
    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "never-started",
            "last_assistant_message": "I've implemented the fix.",
        },
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_claim_with_no_git_change_is_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-1")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-1",
            "last_assistant_message": "I've fixed the bug and all tests pass.",
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "reason" in payload


def test_claim_with_real_working_tree_change_is_not_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-2")
    (tmp_path / "fix.py").write_text("def fixed(): return True\n")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-2",
            "last_assistant_message": "I've implemented the fix.",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_claim_with_new_commit_is_not_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-3")
    (tmp_path / "fix.py").write_text("def fixed(): return True\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fix"], cwd=tmp_path, check=True)

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-3",
            "last_assistant_message": "I've committed the fix.",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_state_file_is_consumed_after_stop_check(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-4")
    state_file = tmp_path / ".git" / "the-workshop-subagent-gate" / "agent-4.txt"
    assert state_file.exists()

    run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-4",
            "last_assistant_message": "I've fixed the bug.",
        },
    )

    assert not state_file.exists()


def test_mention_of_verb_without_first_person_claim_not_blocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    start(tmp_path, "agent-5")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-5",
            "last_assistant_message": "No fix needed — the existing behavior is correct.",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_snapshot_serializes_empty_strings_not_none(tmp_path: Path) -> None:
    """The pair must agree on how a failed git read is written to disk.

    The helpers return None on failure; the start hook writes those values into
    a state file and the stop hook reads them back as strings and compares. If
    None ever reached the file as the literal "None", the comparison could never
    match and the evidence check would silently stop blocking.
    """
    _init_git_repo(tmp_path)
    start(tmp_path, "agent-none")

    state_file = tmp_path / ".git" / "the-workshop-subagent-gate" / "agent-none.txt"
    assert "None" not in state_file.read_text()


def test_hooks_fail_open_when_the_shared_helper_is_missing(tmp_path: Path) -> None:
    """A stale or partial install must no-op, not crash the user's tool path.

    The helper ships alongside every hook, so this should never happen — but a
    hook that raises ImportError on a real event surfaces an error on unrelated
    work, which is exactly what fail-open exists to prevent.
    """
    _init_git_repo(tmp_path)
    isolated = tmp_path / "hooks"
    isolated.mkdir()
    for hook in (START_HOOK, STOP_HOOK):
        shutil.copy2(hook, isolated / hook.name)  # deliberately without _git_baseline.py

    result = run(
        isolated / STOP_HOOK.name,
        {"cwd": str(tmp_path), "agent_id": "a1", "message": "Done. I fixed it."},
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_signature_changes_for_edits_inside_an_already_untracked_directory(
    tmp_path: Path,
) -> None:
    """`git status --porcelain` collapses an untracked dir to one `?? dir/` line.

    Without `--untracked-files=all`, adding a second file inside a directory
    that is already untracked produces the identical porcelain line, so the
    signature never changes even though real content was added.
    """
    _init_git_repo(tmp_path)
    untracked_dir = tmp_path / "scratch"
    untracked_dir.mkdir()
    (untracked_dir / "first.txt").write_text("one\n")

    before = working_tree_signature(tmp_path)

    (untracked_dir / "second.txt").write_text("two\n")

    after = working_tree_signature(tmp_path)

    assert before != after


@pytest.mark.parametrize(
    "name",
    ["café.txt", 'quo"te.txt', "tab\tname.txt", "back\\slash.txt"],
    ids=["non-ascii", "double-quote", "tab", "backslash"],
)
def test_signature_changes_when_a_specially_named_untracked_file_is_edited(
    tmp_path: Path, name: str
) -> None:
    """git C-quotes these paths in `--porcelain` output; the content must still be hashed."""
    _init_git_repo(tmp_path)
    (tmp_path / name).write_text("one\n")

    before = working_tree_signature(tmp_path)

    (tmp_path / name).write_text("two\n")

    assert before != working_tree_signature(tmp_path)


def test_signature_changes_when_a_renamed_file_is_edited(tmp_path: Path) -> None:
    """A rename is two NUL fields under `-z`; the new path's content must be hashed."""
    _init_git_repo(tmp_path)
    (tmp_path / "old name.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "mv", "old name.txt", "café new.txt"], cwd=tmp_path, check=True)

    before = working_tree_signature(tmp_path)

    (tmp_path / "café new.txt").write_text("two\n")

    assert before != working_tree_signature(tmp_path)


def _commit_readme(path: Path) -> None:
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


@pytest.mark.parametrize(
    "message",
    ["Here's what I found during exploration.", "No fix needed."],
    ids=["exploration", "no-fix"],
)
def test_state_file_is_removed_when_the_message_is_not_a_completion_claim(
    tmp_path: Path, message: str
) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)

    start(tmp_path, "agent-leak")
    state_file = tmp_path / ".git" / "the-workshop-subagent-gate" / "agent-leak.txt"
    assert state_file.exists()

    result = run(
        STOP_HOOK,
        {"cwd": str(tmp_path), "agent_id": "agent-leak", "last_assistant_message": message},
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert not state_file.exists()


def test_state_file_is_removed_when_the_final_message_is_empty(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)

    start(tmp_path, "agent-empty")
    state_file = tmp_path / ".git" / "the-workshop-subagent-gate" / "agent-empty.txt"

    result = run(STOP_HOOK, {"cwd": str(tmp_path), "agent_id": "agent-empty"})

    assert result.returncode == 0
    assert not state_file.exists()


@pytest.mark.parametrize("agent_id", ["../../escape", "a/b", "..", "x\\..\\y"])
def test_start_hook_keeps_the_state_file_inside_the_gate_directory(
    tmp_path: Path, agent_id: str
) -> None:
    _init_git_repo(tmp_path)
    gate_dir = tmp_path / ".git" / "the-workshop-subagent-gate"

    start(tmp_path, agent_id)

    in_gate = sorted(gate_dir.iterdir())
    assert len(in_gate) == 1, "the baseline should still be recorded under a sanitized name"
    assert all(p.is_file() for p in in_gate), "agent_id created a nested directory"
    stray = [p for p in tmp_path.rglob("*.txt") if gate_dir not in p.parents]
    assert stray == [], f"state file escaped the gate directory: {stray}"


def test_stop_hook_does_not_delete_files_outside_the_gate_directory(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    (tmp_path / ".git" / "the-workshop-subagent-gate").mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\nme\n")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "../../victim",
            "last_assistant_message": "I've fixed the bug.",
        },
    )

    assert result.returncode == 0
    assert victim.exists()


def test_sanitized_agent_id_round_trips_between_start_and_stop(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)

    start(tmp_path, "../weird/id")
    gate_dir = tmp_path / ".git" / "the-workshop-subagent-gate"
    assert len(list(gate_dir.iterdir())) == 1

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "../weird/id",
            "last_assistant_message": "I've fixed the bug.",
        },
    )

    assert json.loads(result.stdout)["decision"] == "block"
    assert list(gate_dir.iterdir()) == []


@pytest.mark.parametrize(
    "message",
    [["I've fixed it"], {"text": "I've fixed it"}, 7, True],
    ids=["list", "dict", "int", "bool"],
)
def test_non_string_final_message_fails_open(tmp_path: Path, message: object) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-nonstr")

    result = run(
        STOP_HOOK,
        {"cwd": str(tmp_path), "agent_id": "agent-nonstr", "last_assistant_message": message},
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "message",
    ["Task not done.", "Nothing is done yet.", "Nothing is done.", "The migration is not done"],
)
def test_negated_done_ending_is_not_a_completion_claim(tmp_path: Path, message: str) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-neg")

    result = run(
        STOP_HOOK,
        {"cwd": str(tmp_path), "agent_id": "agent-neg", "last_assistant_message": message},
    )

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize("message", ["All done.", "I'm done.", "Reviewed everything. I am done"])
def test_positive_done_ending_is_still_a_completion_claim(tmp_path: Path, message: str) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-pos")

    result = run(
        STOP_HOOK,
        {"cwd": str(tmp_path), "agent_id": "agent-pos", "last_assistant_message": message},
    )

    assert json.loads(result.stdout)["decision"] == "block"


@pytest.mark.parametrize(
    "message",
    [
        # The 2026-10-12 sweep's report, verbatim: a read-only audit quoting
        # finish-branch's description was blocked on the quoted phrase.
        "I found one new direct conflict.\n\n"
        "- `skills/finish-branch/SKILL.md:4` — \"Use when implementation is complete…\", "
        "which triggers a merge/PR/keep/discard menu. BORDERLINE (weak).",
        "`finish-branch/SKILL.md:4` reads `Use when implementation is complete, all tests pass`.",
        "The description says “Use when implementation is complete”.",
        "The worker's transcript ends with \"I've fixed the bug\", but HEAD never moved.",
        "| path:line | text | verdict |\n|---|---|---|\n"
        "| `skills/finish-branch/SKILL.md:4` | Use when implementation is complete | BORDERLINE |",
        "finish-branch/SKILL.md:4 says:\n\n"
        "> Use when implementation is complete, all tests pass, and you need to decide\n\n"
        "BORDERLINE.",
        "The regex under review:\n\n```python\n"
        "    r\"implementation is complete|committed the (?:fix|change)|\"\n"
        "```\n\nIt has no first-person anchor.",
        "Regex under review:\n\n```\nimplementation is complete\n```\n\nIt has no anchor.",
        "Regex under review:\n\n~~~\nimplementation is complete\n~~~\n\nIt has no anchor.",
        "```\nUse when implementation is complete\n````\n\nThat is the description.",
        "````\nUse when implementation is complete\n````\n",
        "```\nUse when implementation is complete\n```   \n\nThat is the description.",
        "- Found:\n  ```\n  Use when implementation is complete\n  ```\n",
        # CommonMark: none of these lines can close the fence, so the claim is inside it.
        "```\nfoo\n```bash\nI've fixed the bug.\n```",
        "```\nfoo\n~~~\nI've fixed the bug.\n```",
        "````\nfoo\n```\nI've fixed the bug.\n````",
        "- Quoting the file:\n  > Use when implementation is complete\n",
    ],
    ids=[
        "incident-sweep",
        "backticks",
        "curly-quotes",
        "quoted-first-person",
        "table-cell",
        "blockquote",
        "fenced-code",
        "bare-fence",
        "tilde-fence",
        "longer-closer",
        "four-backtick-fence",
        "closer-trailing-space",
        "indented-fence",
        "info-string-line-inside-fence",
        "other-marker-inside-fence",
        "shorter-closer-inside-fence",
        "indented-blockquote",
    ],
)
def test_quoted_completion_phrase_is_not_a_claim(tmp_path: Path, message: str) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-quote")

    result = run(
        STOP_HOOK,
        {"cwd": str(tmp_path), "agent_id": "agent-quote", "last_assistant_message": message},
    )

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "message",
    [
        "Per the \"parser\" spec, I've fixed the bug, see \"notes\".",
        "I've implemented the change in `hooks/foo.py`.",
        "Edited `a.py`, I've fixed the bug, and touched `b.py`.",
        "The `\"` token is escaped. I've fixed the bug, see \"notes\".",
        "I've fixed the bug; it isn't flaky.",
        "I've fixed the retry loop (3 -> 1 attempts).",
        "The panel is 5\" wide.\nI've fixed the bug.\nSee the \"readme\".",
        "A stray “ opens here.\nI've fixed the bug.\nSee “readme”.",
        "Opened a stray ` here.\nI've fixed the bug.\nUses `foo` later.",
        "```diff\n- old\n+ new\n```\n\nI've applied the diff above.",
        "```diff\n- old\n+ new\n\nI've applied the diff above.",
        "```\na\n```\n\nI've fixed the bug.\n\n```\nb\n```",
        "```make test``` passes now.\nI've fixed the bug in the parser.\n\n```\nfoo\n```",
        "> Use when implementation is complete\n\nThe implementation is complete.",
        "| file | status |\n|---|---|\n| a.py | edited |\n\nAll done.",
    ],
    ids=[
        "between-quotes",
        "code-span-object",
        "between-code-spans",
        "quote-inside-code-span",
        "apostrophes",
        "arrow",
        "stray-quote-line",
        "stray-curly-quote-line",
        "stray-backtick-line",
        "after-fence",
        "unterminated-fence",
        "between-fences",
        "inline-triple-backticks",
        "after-blockquote",
        "after-table",
    ],
)
def test_unquoted_claim_beside_quoted_material_is_still_a_claim(
    tmp_path: Path, message: str
) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-mixed")

    result = run(
        STOP_HOOK,
        {"cwd": str(tmp_path), "agent_id": "agent-mixed", "last_assistant_message": message},
    )

    assert json.loads(result.stdout)["decision"] == "block"


def test_removing_quoted_material_does_not_make_done_the_ending(tmp_path: Path) -> None:
    """A "done" counts only as the message's last words (#628); a trailing quote keeps it mid-message."""
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-tail")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-tail",
            "last_assistant_message": "All done.\n\n```\n$ make test\n```",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_block_reason_asks_for_the_report_to_be_restated(tmp_path: Path) -> None:
    """A block makes the subagent's next message the one its caller receives.

    The 2026-10-12 sweep's rebuttal replaced its report, so the caller had to
    resume the agent to get the deliverable back.
    """
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-reason")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-reason",
            "last_assistant_message": "I've fixed the bug.",
        },
    )

    reason = json.loads(result.stdout)["reason"]
    assert "not meant to change anything, say so" in reason
    assert "restate your full report" in reason
    assert "only your final message" in reason


def test_signature_hashes_a_large_file_without_reading_it_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The digest must equal a full-read baseline, but memory must stay bounded."""
    import hashlib

    _init_git_repo(tmp_path)
    big = tmp_path / "big.bin"
    big.write_bytes(b"0123456789abcdef" * (192 * 1024) + b"tail")  # ~3 MiB, larger than the chunk

    status = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    ).stdout
    expected = hashlib.sha256(status + big.read_bytes()).hexdigest()

    real_open = Path.open
    reads: list[int] = []

    class _BoundedReads:
        """Proxy that fails any unbounded or oversized read of the file."""

        def __init__(self, handle: object) -> None:
            self._handle = handle

        def __enter__(self) -> "_BoundedReads":
            self._handle.__enter__()
            return self

        def __exit__(self, *exc: object) -> object:
            return self._handle.__exit__(*exc)

        def read(self, size: int | None = -1) -> bytes:
            if size is None or size < 0 or size > 8 * 1024 * 1024:
                raise AssertionError("whole-file read: memory is not bounded")
            reads.append(size)
            return self._handle.read(size)

        def __getattr__(self, name: str) -> object:
            return getattr(self._handle, name)

    def _spy_open(self: Path, *args: object, **kwargs: object) -> object:
        handle = real_open(self, *args, **kwargs)
        return _BoundedReads(handle) if self.name == "big.bin" else handle

    def _no_whole_file_read(self: Path) -> bytes:
        raise AssertionError("read_bytes() loads the whole file into memory")

    monkeypatch.setattr(Path, "open", _spy_open)
    monkeypatch.setattr(Path, "read_bytes", _no_whole_file_read)

    assert working_tree_signature(tmp_path) == expected
    assert len(reads) > 2, "a multi-chunk file should be read in several bounded reads"


def test_run_git_returns_stripped_stdout_and_none_on_failure(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    assert _git_baseline._run_git(["rev-parse", "--is-inside-work-tree"], tmp_path) == "true"
    assert _git_baseline._run_git(["not-a-git-subcommand-xyz"], tmp_path) is None
    assert _git_baseline._run_git(["rev-parse", "HEAD"], tmp_path / "missing-dir") is None


def test_run_git_returns_none_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="git", timeout=10)

    monkeypatch.setattr(_git_baseline.subprocess, "run", _boom)

    assert _git_baseline._run_git(["rev-parse", "HEAD"], tmp_path) is None


def test_git_dir_and_head_sha_go_through_run_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _spy(args: list[str], cwd: Path, timeout: int = 10) -> str | None:
        calls.append(list(args))
        return "/somewhere" if "--absolute-git-dir" in args else "abc123"

    monkeypatch.setattr(_git_baseline, "_run_git", _spy)

    assert _git_baseline.git_dir(tmp_path) == Path("/somewhere")
    assert _git_baseline.head_sha(tmp_path) == "abc123"
    assert ["rev-parse", "--absolute-git-dir"] in calls
    assert ["rev-parse", "HEAD"] in calls


def test_git_common_dir_matches_git_dir_in_a_plain_repo(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    assert _git_baseline.git_common_dir(tmp_path) == _git_baseline.git_dir(tmp_path)
    assert _git_baseline.git_common_dir(tmp_path / "nowhere") is None


def test_signature_does_not_hash_a_renames_original_path(tmp_path: Path) -> None:
    """Under `-z` a rename entry carries the original path as a second field; it is not content."""
    import hashlib

    _init_git_repo(tmp_path)
    (tmp_path / "abc-old.txt").write_text("one\n")
    # A tracked, unmodified file whose name equals the original path minus the
    # 3-char status prefix: a parser that treats the original-path field as an
    # entry would hash it as a phantom.
    (tmp_path / "-old.txt").write_text("phantom\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "mv", "abc-old.txt", "new.txt"], cwd=tmp_path, check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    ).stdout
    expected = hashlib.sha256(status + (tmp_path / "new.txt").read_bytes()).hexdigest()

    assert working_tree_signature(tmp_path) == expected


def test_signature_tolerates_a_deleted_tracked_file(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    (tmp_path / "README.md").write_text("changed\n")
    before = working_tree_signature(tmp_path)

    (tmp_path / "README.md").unlink()
    after = working_tree_signature(tmp_path)

    assert isinstance(after, str)
    assert after != before


def test_signature_is_none_outside_a_repo(tmp_path: Path) -> None:
    assert working_tree_signature(tmp_path) is None


def test_signature_does_not_hash_a_copys_original_path(tmp_path: Path) -> None:
    """A copy entry (status `C`) carries the original path as a second field."""
    import hashlib

    _init_git_repo(tmp_path)
    subprocess.run(["git", "config", "status.renames", "copies"], cwd=tmp_path, check=True)
    (tmp_path / "abc-old.txt").write_text("one\n" * 20)
    (tmp_path / "-old.txt").write_text("phantom\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    # git only detects a copy whose source is also modified in the same change.
    (tmp_path / "abc-old.txt").write_text("one\n" * 20 + "extra\n")
    (tmp_path / "copy.txt").write_text("one\n" * 20)
    subprocess.run(["git", "add", "abc-old.txt", "copy.txt"], cwd=tmp_path, check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    ).stdout
    assert b"C " in status, "fixture must produce a copy entry"
    # The modified source and the copy are hashed; the copy's original-path field is not.
    hasher = hashlib.sha256(status)
    for name in ("abc-old.txt", "copy.txt"):
        hasher.update((tmp_path / name).read_bytes())

    assert working_tree_signature(tmp_path) == hasher.hexdigest()


@pytest.mark.skipif(sys.platform == "darwin", reason="APFS rejects non-UTF-8 file names")
def test_signature_tolerates_non_utf8_path_bytes(tmp_path: Path) -> None:
    import os

    _init_git_repo(tmp_path)
    (tmp_path / os.fsdecode(os.fsencode("bad\udcff.txt"))).write_text("x\n")

    assert isinstance(working_tree_signature(tmp_path), str)


def test_run_git_returns_none_when_git_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(_git_baseline.subprocess, "run", _missing)

    assert _git_baseline._run_git(["rev-parse", "HEAD"], tmp_path) is None


def test_run_git_passes_the_timeout_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def _record(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n")

    monkeypatch.setattr(_git_baseline.subprocess, "run", _record)

    assert _git_baseline._run_git(["status"], tmp_path, timeout=3) == "ok"
    assert seen["timeout"] == 3


def test_done_mid_sentence_is_not_a_completion_claim(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _commit_readme(tmp_path)
    start(tmp_path, "agent-mid")

    result = run(
        STOP_HOOK,
        {
            "cwd": str(tmp_path),
            "agent_id": "agent-mid",
            "last_assistant_message": "I'm done reading the files, nothing changed yet.",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
