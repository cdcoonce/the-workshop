"""Tests for vault_utils shared helpers."""

import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import vault_scope
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
# read_batch_model — scaffold-owned vault_scope.BATCH_MODEL (#431)
# ---------------------------------------------------------------------------
class TestReadBatchModel:
    def test_reads_scaffold_value(self):
        assert read_batch_model() == vault_scope.BATCH_MODEL

    def test_reads_custom_model(self, monkeypatch):
        monkeypatch.setattr(vault_scope, "BATCH_MODEL", "claude-opus-5")
        assert read_batch_model() == "claude-opus-5"

    def test_absent_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.delattr(vault_scope, "BATCH_MODEL")
        assert read_batch_model() == DEFAULT_BATCH_MODEL

    def test_non_string_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(vault_scope, "BATCH_MODEL", 5)
        assert read_batch_model() == DEFAULT_BATCH_MODEL

    def test_empty_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(vault_scope, "BATCH_MODEL", "")
        assert read_batch_model() == DEFAULT_BATCH_MODEL

    def test_explicit_default_is_the_last_resort(self, monkeypatch):
        # #464 layering: scaffold value → shipped default → caller's default.
        # The shipped surface (vault_scope_defaults) interposes before the
        # param, so the param only applies when the name is unknown to both.
        import vault_scope_defaults

        monkeypatch.delattr(vault_scope, "BATCH_MODEL")
        assert read_batch_model(default="claude-sonnet-5") == DEFAULT_BATCH_MODEL

        monkeypatch.delattr(vault_scope_defaults, "BATCH_MODEL")
        assert read_batch_model(default="claude-sonnet-5") == "claude-sonnet-5"
