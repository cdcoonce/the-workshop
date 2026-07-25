"""Tests for scripts.dist_digest — the verify-generated staleness snapshot."""

from __future__ import annotations

from pathlib import Path

from scripts.dist_digest import GENERATED_ROOTS, tree_digest

ROOTS = (Path("dist"), Path("marketplace.json"))


class TestGeneratedRoots:
    def test_machinery_generated_sources_are_covered(self) -> None:
        """verify-generated must catch stale source-side machinery output:
        rendered/ and vendor-map.json are committed-generated (like dist/),
        rebuilt by build_preset, so they belong in the drift digest."""
        assert Path("presets/vault-ops/machinery/rendered") in GENERATED_ROOTS
        assert (
            Path("presets/vault-ops/machinery/vendor-map.json")
            in GENERATED_ROOTS
        )


def _seed(root: Path) -> None:
    (root / "dist" / "a").mkdir(parents=True)
    (root / "dist" / "a" / "one.md").write_text("one")
    (root / "marketplace.json").write_text("{}")


class TestTreeDigest:
    def test_stable_across_runs(self, tmp_path: Path) -> None:
        _seed(tmp_path)
        assert tree_digest(tmp_path, ROOTS) == tree_digest(tmp_path, ROOTS)

    def test_content_change_changes_digest(self, tmp_path: Path) -> None:
        _seed(tmp_path)
        before = tree_digest(tmp_path, ROOTS)
        (tmp_path / "dist" / "a" / "one.md").write_text("two")
        assert tree_digest(tmp_path, ROOTS) != before

    def test_new_file_changes_digest(self, tmp_path: Path) -> None:
        _seed(tmp_path)
        before = tree_digest(tmp_path, ROOTS)
        (tmp_path / "dist" / "a" / "two.md").write_text("two")
        assert tree_digest(tmp_path, ROOTS) != before

    def test_rename_changes_digest(self, tmp_path: Path) -> None:
        _seed(tmp_path)
        before = tree_digest(tmp_path, ROOTS)
        (tmp_path / "dist" / "a" / "one.md").rename(tmp_path / "dist" / "a" / "uno.md")
        assert tree_digest(tmp_path, ROOTS) != before

    def test_missing_roots_digest_like_empty(self, tmp_path: Path) -> None:
        no_roots = tmp_path / "empty"
        no_roots.mkdir()
        empty_dist = tmp_path / "emptydist"
        (empty_dist / "dist").mkdir(parents=True)
        assert tree_digest(no_roots, ROOTS) == tree_digest(empty_dist, ROOTS)
