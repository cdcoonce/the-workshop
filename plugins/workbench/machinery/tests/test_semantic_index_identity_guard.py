"""Identity-change guard on ``semantic_index.py reindex --force`` (#1152).

Each docstring names the defect the test guards. Fixture notes and a stub model
only; the embedder identity is swapped by patching ``ragmark.embed``.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pytest

from ragmark.embed import Embedder
from ragmark.model import ModelIdentity
from ragmark.store import IndexStore

import semantic_index

RECORDED = ("fixture", 2, "1")
ERROR = (
    "Rebuilding re-records the index identity from fixture (dim 2, v1) to "
    "fixture (dim 2, v2); every reader that resolves fixture (dim 2, v1) will "
    "refuse the index afterwards."
)
REMEDIATION = (
    "List the processes that use this index first, then pass "
    "--accept-identity-change, or run the readers under the recorded identity "
    "instead."
)


def make_embedder(name: str, dim: int, version: str) -> type[Embedder]:
    class _Embedder(Embedder):
        def identity(self) -> ModelIdentity:
            return ModelIdentity(name, dim, version)

        def count_tokens(self, text: str) -> int:
            return max(1, len(text.split()))

        def embed(self, texts) -> np.ndarray:
            return np.array([[1.0, 0.5] for _ in texts], dtype=np.float32)

    return _Embedder


def use_identity(monkeypatch, name: str, dim: int, version: str) -> None:
    import ragmark.embed

    monkeypatch.setattr(ragmark.embed, "FastembedEmbedder", make_embedder(name, dim, version))


@pytest.fixture
def vault(tmp_path, monkeypatch, capsys):
    """A fixture vault with one note, HOME redirected outside it, index built."""
    root = tmp_path / "vault"
    (root / ".vault").mkdir(parents=True)
    (root / ".vault" / "vault.json").write_text("{}")
    (root / "reference").mkdir()
    (root / "reference" / "a.md").write_text("# Alpha\n\nUnique alpha phrase.\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    use_identity(monkeypatch, *RECORDED)
    assert semantic_index.main(["reindex"]) == 0
    capsys.readouterr()
    return root


def snapshot(*roots: Path) -> dict[str, bytes]:
    """Name-to-bytes snapshot of every file under *roots*."""
    return {
        str(path): path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def index_files(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in (root / ".ragmark").iterdir()}


def recorded_identity(root: Path):
    store = IndexStore(root / ".ragmark")
    with closing(store.connect()) as conn:
        return store.read_identity(conn)


def run(argv: list[str], capsys) -> tuple[int | None, dict]:
    """Run ``main``; return (SystemExit code or None, parsed JSON stdout)."""
    code = None
    try:
        semantic_index.main(argv)
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(capsys.readouterr().out)


def test_refuses_identity_change_with_pinned_text_and_changes_nothing(
    vault, monkeypatch, capsys
) -> None:
    """Defect: --force silently re-records the identity and strands readers."""
    use_identity(monkeypatch, "fixture", 2, "2")
    before = snapshot(vault, vault.parent / "home")

    code, out = run(["reindex", "--force"], capsys)

    assert code == 1
    assert out["error"] == ERROR
    assert out["remediation"] == REMEDIATION
    assert set(out) == {"error", "remediation"}
    assert snapshot(vault, vault.parent / "home") == before


@pytest.mark.parametrize(
    "requested", [("other", 2, "1"), ("fixture", 3, "1")], ids=["name", "dim"]
)
def test_refuses_name_only_and_dim_only_change(
    vault, monkeypatch, capsys, requested
) -> None:
    """Defect: comparing only the version component lets a model swap through."""
    use_identity(monkeypatch, *requested)
    before = index_files(vault)

    code, _ = run(["reindex", "--force"], capsys)

    assert code == 1
    assert index_files(vault) == before


def test_accept_flag_rebuilds_and_records_new_identity(
    vault, monkeypatch, capsys
) -> None:
    """Defect: --accept-identity-change is parsed but ignored."""
    use_identity(monkeypatch, "fixture", 2, "2")

    assert semantic_index.main(["reindex", "--force", "--accept-identity-change"]) == 0

    assert recorded_identity(vault).version == "2"
    assert sorted(index_files(vault)) == ["ragmark.db", "vectors.npy"]
    home = vault.parent / "home"
    assert list(home.rglob("*")) == []


def test_equal_identities_rebuild_without_flag(vault, capsys) -> None:
    """Defect: the comparison uses identity (is not) rather than equality."""
    assert semantic_index.main(["reindex", "--force"]) == 0


def test_no_index_rebuilds_without_flag(tmp_path, monkeypatch) -> None:
    """Defect: a missing index is treated as an identity change."""
    root = tmp_path / "v"
    (root / ".vault").mkdir(parents=True)
    (root / ".vault" / "vault.json").write_text("{}")
    (root / "reference").mkdir()
    (root / "reference" / "a.md").write_text("# A\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    use_identity(monkeypatch, *RECORDED)

    assert semantic_index.main(["reindex", "--force"]) == 0


def test_identity_rows_deleted_rebuilds_without_flag(
    vault, monkeypatch, capsys
) -> None:
    """Defect: a database with no recorded identity is refused (raise on exists)."""
    with closing(sqlite3.connect(vault / ".ragmark" / "ragmark.db")) as conn:
        conn.execute(
            "DELETE FROM meta WHERE key IN "
            "('model_name', 'model_dim', 'model_version')"
        )
        conn.commit()
    use_identity(monkeypatch, "fixture", 2, "2")

    assert semantic_index.main(["reindex", "--force"]) == 0
    assert recorded_identity(vault).version == "2"


def test_unreadable_database_still_rebuilds_without_flag(
    vault, monkeypatch, capsys
) -> None:
    """Defect: --force stops being the remedy for a corrupt index."""
    (vault / ".ragmark" / "ragmark.db").write_bytes(b"this is not sqlite" * 50)
    use_identity(monkeypatch, "fixture", 2, "2")

    assert semantic_index.main(["reindex", "--force"]) == 0
    assert recorded_identity(vault).version == "2"


def test_flag_without_force_has_no_effect(vault, monkeypatch, capsys) -> None:
    """Defect: the flag alone implies --force, or the guard runs without it."""
    use_identity(monkeypatch, "fixture", 2, "2")
    before = index_files(vault)

    for argv in (["reindex"], ["reindex", "--accept-identity-change"]):
        code, out = run(argv, capsys)
        assert code == 1
        assert "Rebuilding re-records the index identity" not in out["error"]
        assert "--accept-identity-change" not in out["remediation"]
        assert index_files(vault) == before


def test_refused_and_accepted_calls_write_only_the_two_index_files(
    vault, monkeypatch, capsys
) -> None:
    """Defect: a lease, lock or registry file appears beside the index."""
    home = vault.parent / "home"
    use_identity(monkeypatch, "fixture", 2, "2")
    notes = {
        str(p): p.read_bytes()
        for p in list(vault.rglob("*")) + list(home.rglob("*"))
        if p.is_file() and ".ragmark" not in p.parts
    }

    run(["reindex", "--force"], capsys)
    assert sorted(index_files(vault)) == ["ragmark.db", "vectors.npy"]
    semantic_index.main(["reindex", "--force", "--accept-identity-change"])
    capsys.readouterr()

    assert sorted(index_files(vault)) == ["ragmark.db", "vectors.npy"]
    after = {
        str(p): p.read_bytes()
        for p in list(vault.rglob("*")) + list(home.rglob("*"))
        if p.is_file() and ".ragmark" not in p.parts
    }
    assert after == notes


def test_guard_lives_in_build_index_not_only_the_cli(vault, monkeypatch) -> None:
    """Defect: the guard sits in cmd_reindex, so other callers bypass it."""
    use_identity(monkeypatch, "fixture", 2, "2")
    before = index_files(vault)

    with pytest.raises(semantic_index.IdentityChangeRefused):
        semantic_index.build_index(vault, force=True)
    assert index_files(vault) == before
    assert issubclass(semantic_index.IdentityChangeRefused, Exception)

    semantic_index.build_index(vault, force=True, accept_identity_change=True)
    assert recorded_identity(vault).version == "2"


def test_command_doc_carries_the_flag() -> None:
    """Defect: the doc drops the refusal sentence or names plain --reindex as the
    recovery for a model mismatch."""
    doc = (
        Path(__file__).resolve().parents[2]
        / "skills/vault-find/references/command.md"
    ).read_text()
    section = doc.split("### `/find --reindex`", 1)[1].split("\n#", 1)[0]
    assert "refused unless `--accept-identity-change` is passed" in section

    bullet = next(
        line for line in doc.splitlines() if line.startswith("- **Missing index:**")
    )
    clause = bullet.split("**Corrupt or model-mismatched index:**", 1)[1]
    assert clause.count("`--reindex`") == 1  # the corrupt-index recovery only
    assert "model mismatch" in clause
    mismatch = clause.split("model mismatch", 1)[1]
    assert "`--accept-identity-change`" in mismatch
    assert "`--reindex`" not in mismatch
