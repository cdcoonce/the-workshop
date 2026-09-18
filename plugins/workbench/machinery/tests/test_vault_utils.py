"""Tests for vault_utils shared helpers."""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import vault_scope_defaults
import vault_utils
from vault_utils import (
    DEFAULT_BATCH_MODEL,
    find_vault_root,
    find_vault_root_from_env,
    iso_week_string,
    read_batch_model,
    read_vault_context,
)


def _make_vault(root: Path) -> Path:
    """Build a fake vault matching find_vault_root's signature.

    Signature: CLAUDE.md file + brain/ dir + perf/ dir.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("# vault")
    (root / "brain").mkdir()
    (root / "perf").mkdir()
    (root / ".vault").mkdir(parents=True, exist_ok=True)
    (root / ".vault" / "vault.json").write_text('{"vault": "test"}\n')
    return root


# ---------------------------------------------------------------------------
# find_vault_root
# ---------------------------------------------------------------------------
class TestFindVaultRoot:
    def test_found_from_nested_subdir(self, tmp_path):
        vault = _make_vault(tmp_path / "vault")
        nested = vault / "work" / "active" / "deep"
        nested.mkdir(parents=True)
        assert find_vault_root(nested) == vault

    def test_found_when_start_is_root(self, tmp_path):
        vault = _make_vault(tmp_path / "vault")
        assert find_vault_root(vault) == vault

    def test_returns_none_when_no_signature(self, tmp_path):
        # A tree with no CLAUDE.md/brain/perf signature anywhere up.
        nested = tmp_path / "not_a_vault" / "sub"
        nested.mkdir(parents=True)
        assert find_vault_root(nested) is None

    def test_claude_md_alone_is_not_a_vault(self, tmp_path):
        # CLAUDE.md without brain/ + perf/ must NOT match (the whole point
        # of the signature check — many project repos carry CLAUDE.md).
        repo = tmp_path / "some_repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text("# project")
        assert find_vault_root(repo) is None

    def test_explicit_start_path_overrides_cwd(self, tmp_path, monkeypatch):
        # cwd points at a non-vault dir; explicit start points at the vault.
        vault = _make_vault(tmp_path / "vault")
        non_vault = tmp_path / "elsewhere"
        non_vault.mkdir()
        monkeypatch.chdir(non_vault)
        # Explicit start finds the vault even though cwd would not.
        assert find_vault_root(vault) == vault

    def test_default_start_uses_cwd(self, tmp_path, monkeypatch):
        vault = _make_vault(tmp_path / "vault")
        nested = vault / "personal" / "projects"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        # No argument => walks up from cwd.
        assert find_vault_root() == vault

    def test_default_start_returns_none_outside_vault(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.chdir(outside)
        assert find_vault_root() is None


# ---------------------------------------------------------------------------
# find_vault_root_from_env
# ---------------------------------------------------------------------------
class TestFindVaultRootFromEnv:
    def test_uses_claude_project_dir_when_set(self, tmp_path, monkeypatch):
        # CLAUDE_PROJECT_DIR points at the vault; cwd is elsewhere. The env var
        # must win — this is the anchor that keeps hooks vault-only.
        vault = _make_vault(tmp_path / "vault")
        non_vault = tmp_path / "elsewhere"
        non_vault.mkdir()
        monkeypatch.chdir(non_vault)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vault))
        assert find_vault_root_from_env() == vault

    def test_falls_back_to_cwd_when_unset(self, tmp_path, monkeypatch):
        # No CLAUDE_PROJECT_DIR => walk up from cwd-based discovery.
        vault = _make_vault(tmp_path / "vault")
        nested = vault / "work" / "active"
        nested.mkdir(parents=True)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(nested)
        assert find_vault_root_from_env() == vault


# ---------------------------------------------------------------------------
# iso_week_string
# ---------------------------------------------------------------------------
class TestIsoWeekString:
    def test_zero_padding(self):
        # Week numbers below 10 are zero-padded to two digits.
        assert iso_week_string(date(2026, 1, 5)) == "2026-W02"

    def test_year_boundary_rolls_into_next_iso_year(self):
        # 2025-12-29 falls in ISO week 1 of ISO year 2026.
        assert iso_week_string(date(2025, 12, 29)) == "2026-W01"

    def test_week_53(self):
        assert iso_week_string(date(2020, 12, 31)) == "2020-W53"

    def test_mid_year(self):
        assert iso_week_string(date(2026, 4, 4)) == "2026-W14"


# ---------------------------------------------------------------------------
# read_vault_context — the canonical .vault-context reader (#50)
# ---------------------------------------------------------------------------
class TestReadVaultContext:
    def test_reads_personal(self, tmp_path):
        (tmp_path / ".vault-context").write_text("personal\n")
        assert read_vault_context(tmp_path) == "personal"

    def test_reads_work_case_insensitive(self, tmp_path):
        (tmp_path / ".vault-context").write_text("WORK")
        assert read_vault_context(tmp_path) == "work"

    def test_missing_file_returns_default_unknown(self, tmp_path):
        # The reconciled missing-file default (#50): "unknown", not "personal".
        assert read_vault_context(tmp_path) == "unknown"

    def test_garbage_value_returns_default(self, tmp_path):
        (tmp_path / ".vault-context").write_text("banana")
        assert read_vault_context(tmp_path) == "unknown"

    def test_explicit_default_override(self, tmp_path):
        assert read_vault_context(tmp_path, default="personal") == "personal"


# ---------------------------------------------------------------------------
# read_vault_context — linked-worktree fallback
#
# `.vault-context` is gitignored and untracked, so it exists ONLY in the main
# checkout. Claude Code desktop sessions run inside `<vault>/.claude/worktrees/
# <name>/`, where it is absent — and the reader used to answer "unknown" there.
# Nothing failed loudly: session-start looked up `handoff-unknown.md`, found
# nothing, and injected no handoff while logging that it had; the distiller and
# gardener WROTE orphan `notebook-unknown-*.md` / `gardener-unknown.md` files
# into the worktree that nothing ever reads back; and `/wrap-up` fails closed
# on "unknown", so it could never reach CLEAN from a worktree.
#
# Real `git worktree add` fixtures, never a mocked git: the whole bug lives in
# the on-disk layout git produces (`.git` as a FILE holding `gitdir:`, whose
# target holds a `commondir` pointing back at the main `.git`), so a mock that
# invented that layout would prove only that the mock matches the code.
# ---------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _main_checkout(root: Path) -> Path:
    """A real git repo with one commit, so `git worktree add` can branch off it."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("vault\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    return root


def _linked_worktree(main: Path, path: Path, branch: str = "wt") -> Path:
    _git(main, "worktree", "add", "-q", "-b", branch, str(path))
    return path


class TestReadVaultContextWorktreeFallback:
    def test_worktree_inherits_main_checkout_context(self, tmp_path):
        """The bug: the marker is untracked, so only the main checkout has it."""
        main = _main_checkout(tmp_path / "vault")
        (main / ".vault-context").write_text("personal\n")
        wt = _linked_worktree(main, tmp_path / "wt")

        assert not (wt / ".vault-context").exists()
        assert read_vault_context(wt) == "personal"

    def test_worktree_inherits_work_too(self, tmp_path):
        """Not hardcoded to one value — the main checkout's value is read."""
        main = _main_checkout(tmp_path / "vault")
        (main / ".vault-context").write_text("work\n")
        wt = _linked_worktree(main, tmp_path / "wt")

        assert read_vault_context(wt) == "work"

    def test_worktrees_own_marker_wins(self, tmp_path):
        """An explicitly placed per-worktree marker overrides the inherited one."""
        main = _main_checkout(tmp_path / "vault")
        (main / ".vault-context").write_text("personal\n")
        wt = _linked_worktree(main, tmp_path / "wt")
        (wt / ".vault-context").write_text("work\n")

        assert read_vault_context(wt) == "work"

    def test_worktrees_invalid_marker_does_not_fall_through(self, tmp_path):
        """Present-but-invalid is still PRESENT: it answers `default`, and does
        NOT silently inherit the main checkout's value. Otherwise a typo in a
        worktree marker would resolve to a different context than it names."""
        main = _main_checkout(tmp_path / "vault")
        (main / ".vault-context").write_text("personal\n")
        wt = _linked_worktree(main, tmp_path / "wt")
        (wt / ".vault-context").write_text("banana\n")

        assert read_vault_context(wt) == "unknown"

    def test_neither_present_returns_default(self, tmp_path):
        """`default` semantics are unchanged when the marker exists nowhere."""
        main = _main_checkout(tmp_path / "vault")
        wt = _linked_worktree(main, tmp_path / "wt")

        assert read_vault_context(wt) == "unknown"
        assert read_vault_context(wt, default="personal") == "personal"

    def test_non_git_directory_returns_default_without_raising(self, tmp_path):
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        assert read_vault_context(plain) == "unknown"

    def test_main_checkout_is_unaffected(self, tmp_path):
        """A normal checkout (`.git` is a DIRECTORY) takes no fallback path."""
        main = _main_checkout(tmp_path / "vault")
        assert (main / ".git").is_dir()
        assert read_vault_context(main) == "unknown"

    def test_submodule_does_not_resolve_to_superproject(self, tmp_path):
        """A submodule's `.git` is ALSO a file — but its gitdir has no
        `commondir`, so it is not a linked worktree and must not inherit the
        superproject's context."""
        sup = _main_checkout(tmp_path / "super")
        (sup / ".vault-context").write_text("personal\n")
        sub_src = _main_checkout(tmp_path / "sub-src")
        _git(
            sup,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(sub_src),
            "sub",
        )

        sub = sup / "sub"
        assert (sub / ".git").is_file()
        assert read_vault_context(sub) == "unknown"

    def test_worktree_of_bare_repo_returns_default(self, tmp_path):
        """A bare repo's common dir is the repo itself (`repo.git`), not a
        `.git` inside a work tree — so its parent is an unrelated directory.
        Taking it would read a `.vault-context` belonging to whatever else
        happens to sit beside the bare repo."""
        src = _main_checkout(tmp_path / "src")
        bare = tmp_path / "bare.git"
        _git(tmp_path, "clone", "-q", "--bare", str(src), str(bare))
        wt = tmp_path / "wt"
        _git(bare, "worktree", "add", "-q", "-b", "wt", str(wt))
        # The directory holding the bare repo, which the missing guard would reach.
        (tmp_path / ".vault-context").write_text("work\n")

        assert (wt / ".git").is_file()
        assert read_vault_context(wt) == "unknown"

    def test_reader_never_writes_the_marker(self, tmp_path):
        main = _main_checkout(tmp_path / "vault")
        (main / ".vault-context").write_text("personal\n")
        wt = _linked_worktree(main, tmp_path / "wt")

        read_vault_context(wt)

        assert not (wt / ".vault-context").exists()


# ---------------------------------------------------------------------------
# read_batch_model — owner-owned vault_scope.BATCH_MODEL (#431)
#
# The owner's value arrives through a real config file in a real vault, not
# through a module injected under the name `vault_scope` (#691) — see this
# suite's conftest for why the injected form proved nothing.
# ---------------------------------------------------------------------------
class TestReadBatchModel:
    def test_reads_shipped_value_when_no_owner_config(self, no_owner_scope):
        assert read_batch_model() == vault_scope_defaults.BATCH_MODEL

    def test_reads_custom_model(self, owner_scope):
        owner_scope(BATCH_MODEL="claude-opus-5")
        assert read_batch_model() == "claude-opus-5"

    def test_absent_value_falls_back_to_default(self, owner_scope):
        # A config that defines something, but not this name.
        owner_scope(TASKS_DIR="custom/tasks")
        assert read_batch_model() == DEFAULT_BATCH_MODEL

    def test_non_string_value_falls_back_to_default(self, owner_scope):
        owner_scope(BATCH_MODEL=5)
        assert read_batch_model() == DEFAULT_BATCH_MODEL

    def test_empty_value_falls_back_to_default(self, owner_scope):
        owner_scope(BATCH_MODEL="")
        assert read_batch_model() == DEFAULT_BATCH_MODEL

    def test_explicit_default_is_the_last_resort(self, owner_scope, monkeypatch):
        # #464 layering: owner value → shipped default → caller's default.
        # The shipped surface (vault_scope_defaults) interposes before the
        # param, so the param only applies when the name is unknown to both.
        owner_scope(TASKS_DIR="custom/tasks")
        assert read_batch_model(default="claude-sonnet-5") == DEFAULT_BATCH_MODEL

        monkeypatch.delattr(vault_scope_defaults, "BATCH_MODEL")
        assert read_batch_model(default="claude-sonnet-5") == "claude-sonnet-5"
