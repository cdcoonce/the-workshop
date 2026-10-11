"""Direct tests for _glab: pagination and remote-URL parsing."""

from __future__ import annotations

import pytest

import _glab


def _stub_pages(monkeypatch, pages: dict[int, object]) -> list[str]:
    """Replace glab_json with a per-page lookup; return the paths requested."""
    seen: list[str] = []

    def fake(path: str) -> object | None:
        seen.append(path)
        page = int(path.rsplit("page=", 1)[1])
        return pages.get(page)

    monkeypatch.setattr(_glab, "glab_json", fake)
    return seen


def test_glab_list_assembles_multiple_pages(monkeypatch):
    full = [{"i": i} for i in range(_glab.PAGE_SIZE)]
    tail = [{"i": "tail"}]
    seen = _stub_pages(monkeypatch, {1: full, 2: tail})
    result = _glab.glab_list("projects/p/jobs")
    assert result == full + tail
    assert len(seen) == 2
    assert seen[1].endswith("page=2")


def test_glab_list_uses_ampersand_when_path_has_query(monkeypatch):
    seen = _stub_pages(monkeypatch, {1: []})
    _glab.glab_list("projects/p/pipelines?sha=abc")
    assert seen[0].startswith("projects/p/pipelines?sha=abc&per_page=")


def test_glab_list_page_cap_exhaustion_is_none(monkeypatch):
    full = [{"i": i} for i in range(_glab.PAGE_SIZE)]
    seen = _stub_pages(monkeypatch, {p: full for p in range(1, _glab.MAX_PAGES + 5)})
    assert _glab.glab_list("projects/p/jobs") is None
    assert len(seen) == _glab.MAX_PAGES


def test_glab_list_mid_pagination_failure_is_none(monkeypatch):
    full = [{"i": i} for i in range(_glab.PAGE_SIZE)]
    _stub_pages(monkeypatch, {1: full})  # page 2 -> None
    assert _glab.glab_list("projects/p/jobs") is None


def test_glab_list_non_list_page_is_none(monkeypatch):
    _stub_pages(monkeypatch, {1: {"message": "nope"}})
    assert _glab.glab_list("projects/p/jobs") is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@gitlab.com:group/project.git", "group/project"),
        ("git@gitlab.com:group/sub/project", "group/sub/project"),
        ("ssh://git@gitlab.com/group/project.git", "group/project"),
        ("ssh://git@gitlab.com/group/project", "group/project"),
        ("https://gitlab.com/group/project.git", "group/project"),
        ("https://gitlab.com/group/sub/project", "group/sub/project"),
        ("https://gitlab.com/group/project/", "group/project"),
        ("git@host:group/p:q.git", "group/p:q"),
    ],
)
def test_parse_project_path(url: str, expected: str) -> None:
    assert _glab.parse_project_path(url) == expected


@pytest.mark.parametrize("url", ["not-a-url", "https://gitlab.com/", "git@gitlab.com:"])
def test_parse_project_path_unparseable_is_none(url: str) -> None:
    assert _glab.parse_project_path(url) is None
