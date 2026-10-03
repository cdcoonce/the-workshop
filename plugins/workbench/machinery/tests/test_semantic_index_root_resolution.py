"""semantic_index previously derived ``VAULT_ROOT`` from its own file position
(``SCRIPTS_DIR.parents[1]``) — correct when the module was vendored at
``<vault>/.claude/scripts/``, wrong ever since the flat reorg moved it into the
plugin's ``machinery/engine/``: the root resolved into the plugin cache, the
index looked absent, and every caller degraded silently to empty results
(the-workshop issue #677). The module now resolves the vault through
``vault_utils.find_vault_root_from_env()`` at ``main()`` and threads the root
through every function that touches disk.

The discriminating arrangement (from the issue's test note): the module's
on-disk location is this repo — NOT inside the vault — while the vault is a
``tmp_path`` fixture carrying the ``brain/`` + ``perf/`` + ``CLAUDE.md``
signature. A test that compares the root against a path built from
``__file__`` passes in both the broken and fixed code; a test that requires
the seeded index *inside the fixture vault* to be visible does not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import semantic_index as si  # noqa: E402
from test_ragmark_shims import StubEmbedder  # noqa: E402


@pytest.fixture(autouse=True)
def stub_embedder(monkeypatch):
    import ragmark.embed

    monkeypatch.setattr(ragmark.embed, "FastembedEmbedder", StubEmbedder)


def _make_vault(tmp_path: Path) -> Path:
    """A directory carrying the vault signature ``find_vault_root`` checks."""
    (tmp_path / "CLAUDE.md").write_text("# vault")
    (tmp_path / "brain").mkdir()
    (tmp_path / "perf").mkdir()
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vault" / "vault.json").write_text('{"vault": "test"}\n')
    return tmp_path


def _seed_index(vault: Path, note_rel: str = "brain/a.md") -> None:
    """Build a real fixture ragmark index, then change one note without refresh."""
    for rel in (note_rel, "brain/b.md"):
        path = vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Fixture note\n")
    si.build_index(vault)
    (vault / note_rel).write_text("# Changed fixture note\n")


class TestMainResolution:
    def test_no_vault_anywhere_errors_loudly(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as excinfo:
            si.main(["status"])

        assert excinfo.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "vault root" in out["error"]

    def test_claude_project_dir_without_signature_is_not_a_vault(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        (tmp_path / "CLAUDE.md").write_text("# not a vault")  # signature incomplete
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as excinfo:
            si.main(["status"])

        assert excinfo.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "vault root" in out["error"]

    def test_status_reads_the_index_inside_the_env_resolved_vault(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        """THE regression test for #677.

        The index lives in the fixture vault; the module lives in this repo.
        Positional ``__file__`` resolution looks in the plugin tree, finds
        nothing, and reports an empty, not-ready index — silently.
        """
        vault = _make_vault(tmp_path)
        _seed_index(vault)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vault))

        rc = si.main(["status"])

        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ready"] is False
        assert out["state"] == "stale"
        assert out["chunks"] == 2
        assert out["notes"] == 2
        # One of the two live notes changed after the fixture build.
        assert out["stale_notes"] == 1
        # Loudness: status names the root it resolved, so a wrong root is
        # visible in the output instead of masquerading as an empty vault.
        assert Path(out["vault_root"]).samefile(vault)

    def test_status_without_index_reports_not_ready_against_vault_root(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        vault = _make_vault(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(vault))

        rc = si.main(["status"])

        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ready"] is False
        assert Path(out["vault_root"]).samefile(vault)


class TestIndexIO:
    def test_build_index_writes_under_the_given_vault(self, tmp_path) -> None:
        vault = _make_vault(tmp_path)
        (vault / "brain/a.md").write_text("# Fixture\n")

        report = si.build_index(vault)

        assert report["indexed"] == 1
        assert (vault / ".ragmark" / "ragmark.db").exists()
        assert (vault / ".ragmark" / "vectors.npy").exists()
        assert not (vault / ".claude" / "data" / "semantic").exists()

    def test_status_names_the_requested_root_not_another_cached_root(
        self, tmp_path
    ) -> None:
        first = tmp_path / "first"
        first.mkdir()
        second = tmp_path / "second"
        second.mkdir()
        _make_vault(first)
        _make_vault(second)
        _seed_index(first)

        report = si.status(second)

        assert report["state"] == "missing"
        assert report["ready"] is False
        assert report["vault_root"] == str(second.resolve())
        assert not (second / ".ragmark").exists()
