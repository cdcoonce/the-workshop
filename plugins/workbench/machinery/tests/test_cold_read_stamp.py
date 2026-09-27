from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from cold_read_stamp import (  # noqa: E402
    body_hash,
    cmd_check,
    cmd_stamp,
    main,
)

VECTOR_PATH = Path(__file__).resolve().parent / "fixtures" / "cold_read_stamp_vector.json"
VECTOR = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))

REPO = "acme/proj"


# --------------------------------------------------------------------------- #
# fake gh / git seams
# --------------------------------------------------------------------------- #

class FakeGh:
    """Records calls; ``issues`` maps ``'owner/repo#N'`` -> ``{"body", "state"}``.

    Raises ``AssertionError`` on any call shape this fixture does not model,
    the way ``test_cold_read_evidence.py``'s ``FakeGh`` does. Three sets tune
    a specific failure mode for a specific key without changing every test's
    setup: ``patch_should_fail`` (PATCH returns non-zero), ``drop_stamp_on_patch``
    (GitHub silently drops the appended stamp line, rest unchanged), and
    ``mangle_on_patch`` (GitHub's stored body differs from what was posted).
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.issues: dict[str, dict] = {}
        self.patch_should_fail: set[str] = set()
        self.drop_stamp_on_patch: set[str] = set()
        self.mangle_on_patch: set[str] = set()

    def set_issue(self, repo: str, number: int, body: str | None, state: str = "open") -> None:
        self.issues[f"{repo}#{number}"] = {"body": body, "state": state}

    def __call__(self, args: list[str], timeout: int = 30):
        self.calls.append(list(args))
        if args[0] != "api":
            raise AssertionError(f"unexpected fake gh call (not 'api'): {args}")
        if len(args) >= 4 and args[1] == "-X" and args[2] == "PATCH":
            path = args[3]
            key = path.removeprefix("repos/").replace("/issues/", "#")
            if key in self.patch_should_fail:
                return (1, "", "gh: HTTP 422: Unprocessable Entity")
            file_arg = args[5]
            assert args[4] == "-F" and file_arg.startswith("body=@"), f"unexpected PATCH args: {args}"
            file_path = file_arg[len("body=@"):]
            with open(file_path, encoding="utf-8", newline="") as handle:
                content = handle.read()
            if key in self.drop_stamp_on_patch:
                import re as _re

                content = _re.sub(r"<!-- cold-read-stamp: [^\n]* -->\n?", "", content)
            if key in self.mangle_on_patch:
                # Alter body content itself (not the stamp line or its
                # terminator), so the mismatch survives stamp-line stripping.
                content = "MANGLED " + content
            self.issues.setdefault(key, {"state": "open"})["body"] = content
            return (0, "{}", "")
        if len(args) == 2:
            path = args[1]
            key = path.removeprefix("repos/").replace("/issues/", "#")
            data = self.issues.get(key)
            if data is None:
                return (1, "", "gh: HTTP 404: Not Found")
            return (0, json.dumps(data), "")
        raise AssertionError(f"unexpected fake gh call shape: {args}")


@pytest.fixture
def fake_gh(monkeypatch):
    import cold_read_stamp as crs

    fake = FakeGh()
    monkeypatch.setattr(crs, "_run_gh", fake)
    yield fake
    for call in fake.calls:
        assert call[0] == "api", f"non-api gh call recorded: {call}"
        assert "--jq" not in call, f"gh call used --jq: {call}"
        assert "-q" not in call, f"gh call used -q: {call}"


class FakeGit:
    """Records calls; ``shas`` maps ``'origin/<ref>'`` -> the sha it resolves to."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.shas: dict[str, str] = {}

    def __call__(self, args: list[str], timeout: int = 30):
        self.calls.append(list(args))
        if len(args) >= 5 and args[0] == "-C" and args[2:4] == ["rev-parse", "--verify"]:
            ref = args[4]
            sha = self.shas.get(ref)
            if sha is None:
                return (1, "", f"fatal: ambiguous argument '{ref}': unknown revision")
            return (0, sha + "\n", "")
        raise AssertionError(f"unexpected fake git call: {args}")


@pytest.fixture
def fake_git(monkeypatch):
    import cold_read_stamp as crs

    fake = FakeGit()
    monkeypatch.setattr(crs, "_run_git", fake)
    return fake


def _stamp(body_h12: str, target: str, sha12: str, deps: str) -> str:
    return f"<!-- cold-read-stamp: v1 body={body_h12} target={target}@{sha12} deps={deps} -->"


# --------------------------------------------------------------------------- #
# body_hash — the shared vector, and the properties item 2/6/8/9/12 of the
# issue body describe
# --------------------------------------------------------------------------- #

def test_body_hash_matches_vector_and_survives_appended_stamp() -> None:
    body = VECTOR["body"]
    assert body_hash(body) == VECTOR["hash"]

    extra = "<!-- cold-read-stamp: v1 body=aaaaaaaaaaaa target=dev@aaaaaaaaaaaa deps=- -->"
    assert body_hash(body + extra + "\n") == VECTOR["hash"]
    assert body_hash(body + extra) == VECTOR["hash"]


def test_body_hash_sensitive_to_crlf_and_trailing_newline() -> None:
    body = VECTOR["body"]
    crlf_to_lf = body.replace("## Vector\r\n", "## Vector\n", 1)
    assert body_hash(crlf_to_lf) != body_hash(body)

    extra_trailing_newline = body + "\n"
    assert body_hash(extra_trailing_newline) != body_hash(body)


def test_body_hash_distinguishes_prefix_stamp_like_line() -> None:
    stamp = "<!-- cold-read-stamp: v1 body=aaaaaaaaaaaa target=dev@aaaaaaaaaaaa deps=- -->"
    assert body_hash("a\n" + stamp + " x\n") != body_hash("a\n")


# --------------------------------------------------------------------------- #
# stamp — dependency parsing and formatting
# --------------------------------------------------------------------------- #

def test_stamp_dedupes_depends_on_and_orders_by_declaration(capsys, fake_gh, fake_git) -> None:
    body = "Depends on #6 and #5 and #6\n\nrest of the body\n"
    fake_gh.set_issue(REPO, 42, body)
    fake_gh.set_issue(REPO, 6, None, state="open")
    fake_gh.set_issue(REPO, 5, None, state="closed")
    fake_git.shas["origin/dev"] = "1" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=False)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "deps=#6:open,#5:closed" in out


def test_stamp_dedupes_across_multiple_depends_on_lines(capsys, fake_gh, fake_git) -> None:
    body = "Depends on #5\n\nsome text in between\n\nDepends on #6\n"
    fake_gh.set_issue(REPO, 42, body)
    fake_gh.set_issue(REPO, 5, None, state="open")
    fake_gh.set_issue(REPO, 6, None, state="open")
    fake_git.shas["origin/dev"] = "2" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=False)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "deps=#5:open,#6:open" in out


def test_stamp_no_deps_prints_dash(capsys, fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "no dependencies here\n")
    fake_git.shas["origin/dev"] = "3" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=False)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "deps=-" in out


def test_stamp_mixed_deps_open_and_closed(capsys, fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "Depends on #5 and #6\n")
    fake_gh.set_issue(REPO, 5, None, state="open")
    fake_gh.set_issue(REPO, 6, None, state="closed")
    fake_git.shas["origin/dev"] = "4" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=False)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "deps=#5:open,#6:closed" in out


def test_stamp_exits_2_on_failed_rev_parse(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "no deps\n")
    # fake_git.shas left empty: rev-parse fails.
    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=False)
    assert rc == 2


def test_stamp_exits_2_on_failed_dependency_lookup(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "Depends on #9\n")
    # #9 is never registered -> lookup 404s.
    fake_git.shas["origin/dev"] = "5" * 40
    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=False)
    assert rc == 2


# --------------------------------------------------------------------------- #
# stamp --apply — the write-and-verify round trip
# --------------------------------------------------------------------------- #

def test_apply_on_plain_body_writes_and_check_passes(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "abc")
    fake_git.shas["origin/dev"] = "6" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=True)
    assert rc == 0

    written = fake_gh.issues[f"{REPO}#42"]["body"]
    assert written.startswith("abc\n<!-- cold-read-stamp: v1 ")
    assert written.endswith(" -->\n")
    # exactly one stamp line, immediately after "abc\n", nothing else.
    assert written.count("<!-- cold-read-stamp:") == 1

    assert cmd_check(REPO, 42) == 0


def test_apply_on_null_body_writes_and_check_passes(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, None)
    fake_git.shas["origin/dev"] = "7" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=True)
    assert rc == 0

    written = fake_gh.issues[f"{REPO}#42"]["body"]
    assert written.startswith("\n<!-- cold-read-stamp: v1 ")
    assert written.endswith(" -->\n")

    assert cmd_check(REPO, 42) == 0


def test_apply_replaces_existing_stamp_not_appends(fake_gh, fake_git) -> None:
    old_stamp = _stamp("111111111111", "dev", "111111111111", "-")
    fake_gh.set_issue(REPO, 42, f"content\n{old_stamp}\n")
    fake_git.shas["origin/dev"] = "8" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=True)
    assert rc == 0

    written = fake_gh.issues[f"{REPO}#42"]["body"]
    assert written.count("<!-- cold-read-stamp:") == 1
    assert old_stamp not in written


def test_apply_exits_2_when_patch_returns_non_zero_body_hash_mismatch(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "content\n")
    fake_gh.mangle_on_patch.add(f"{REPO}#42")
    fake_git.shas["origin/dev"] = "9" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=True)
    assert rc == 2


def test_apply_exits_2_when_patch_fails(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "content\n")
    fake_gh.patch_should_fail.add(f"{REPO}#42")
    fake_git.shas["origin/dev"] = "a" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=True)
    assert rc == 2


def test_apply_exits_2_when_refetched_body_has_no_stamp_line(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "content\n")
    fake_gh.drop_stamp_on_patch.add(f"{REPO}#42")
    fake_git.shas["origin/dev"] = "b" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=True)
    assert rc == 2


# --------------------------------------------------------------------------- #
# check — fresh stamp, drift, dependency closure, and malformed input
# --------------------------------------------------------------------------- #

def test_check_exits_2_on_prefix_stamp_like_line_zero_real_stamps(fake_gh) -> None:
    stamp = "<!-- cold-read-stamp: v1 body=aaaaaaaaaaaa target=dev@aaaaaaaaaaaa deps=- -->"
    fake_gh.set_issue(REPO, 42, "a\n" + stamp + " x\n")
    rc = cmd_check(REPO, 42)
    assert rc == 2


def test_check_ignores_stray_stamp_like_line_when_counting(fake_gh, fake_git) -> None:
    stray = "<!-- cold-read-stamp: v1 body=aaaaaaaaaaaa target=dev@aaaaaaaaaaaa deps=- --> x"
    fake_gh.set_issue(REPO, 42, f"line1\n{stray}\nline2\n")
    fake_git.shas["origin/dev"] = "c" * 40

    rc = cmd_stamp(REPO, 42, Path("/repo"), "dev", apply=True)
    assert rc == 0

    written = fake_gh.issues[f"{REPO}#42"]["body"]
    assert stray in written
    assert written.count("<!-- cold-read-stamp:") == 2  # the stray one plus the real one

    assert cmd_check(REPO, 42) == 0


def test_check_passes_when_stamp_line_ends_in_crlf(fake_gh) -> None:
    rest = "hello\nworld\n"
    h12 = body_hash(rest)[:12]
    stamp = _stamp(h12, "dev", "0" * 12, "-")
    body = "hello\n" + stamp + "\r\n" + "world\n"
    fake_gh.set_issue(REPO, 42, body)

    assert cmd_check(REPO, 42) == 0


def test_check_skips_dependency_lookup_for_deps_recorded_closed(fake_gh) -> None:
    rest = "x\n"
    h12 = body_hash(rest)[:12]
    stamp = _stamp(h12, "dev", "0" * 12, "#5:open,#6:closed")
    fake_gh.set_issue(REPO, 42, rest + stamp + "\n")
    fake_gh.set_issue(REPO, 5, None, state="open")
    # #6 deliberately not registered: any call for it would 404.

    rc = cmd_check(REPO, 42)
    assert rc == 0
    assert not any(f"repos/{REPO}/issues/6" in call for call in fake_gh.calls)


def test_check_dependency_closed_since_stamp_names_issue(capsys, fake_gh) -> None:
    rest = "x\n"
    h12 = body_hash(rest)[:12]
    stamp = _stamp(h12, "dev", "0" * 12, "#5:open")
    fake_gh.set_issue(REPO, 42, rest + stamp + "\n")
    fake_gh.set_issue(REPO, 5, None, state="closed")

    rc = cmd_check(REPO, 42)
    assert rc == 1
    out = capsys.readouterr().out
    assert "dependency #5 closed since stamp; re-read against shipped code" in out


def test_check_body_changed_since_stamp_single_char_edit(capsys, fake_gh) -> None:
    rest = "x\n"
    h12 = body_hash(rest)[:12]
    stamp = _stamp(h12, "dev", "0" * 12, "-")
    fake_gh.set_issue(REPO, 42, "y\n" + stamp + "\n")  # "x" -> "y": body changed

    rc = cmd_check(REPO, 42)
    assert rc == 1
    out = capsys.readouterr().out
    assert out.strip() == "body changed since stamp"


def test_check_exits_1_with_body_changed_and_dependency_closed_reasons(capsys, fake_gh) -> None:
    rest = "x\n"
    h12 = body_hash(rest)[:12]
    stamp = _stamp(h12, "dev", "0" * 12, "#5:open")
    fake_gh.set_issue(REPO, 42, "y\n" + stamp + "\n")  # body changed
    fake_gh.set_issue(REPO, 5, None, state="closed")

    rc = cmd_check(REPO, 42)
    assert rc == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == [
        "body changed since stamp",
        "dependency #5 closed since stamp; re-read against shipped code",
    ]


def test_check_exits_2_when_body_changed_and_open_dependency_lookup_fails(fake_gh) -> None:
    rest = "x\n"
    h12 = body_hash(rest)[:12]
    stamp = _stamp(h12, "dev", "0" * 12, "#5:open")
    fake_gh.set_issue(REPO, 42, "y\n" + stamp + "\n")  # body changed
    # #5 not registered -> lookup fails.

    rc = cmd_check(REPO, 42)
    assert rc == 2


def test_check_exits_2_naming_issue_when_dependency_lookup_fails(fake_gh) -> None:
    rest = "x\n"
    h12 = body_hash(rest)[:12]
    stamp = _stamp(h12, "dev", "0" * 12, "#9:open")
    fake_gh.set_issue(REPO, 42, rest + stamp + "\n")
    # #9 not registered -> lookup fails.

    import io
    import contextlib

    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        rc = cmd_check(REPO, 42)
    assert rc == 2
    assert "#9" in captured.getvalue()


def test_check_makes_no_git_call(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "no stamp at all\n")
    cmd_check(REPO, 42)
    assert fake_git.calls == []


def test_check_exits_2_on_no_stamp(fake_gh) -> None:
    fake_gh.set_issue(REPO, 42, "no stamp here\n")
    assert cmd_check(REPO, 42) == 2


def test_check_exits_2_on_two_stamp_lines(fake_gh) -> None:
    stamp = _stamp("0" * 12, "dev", "0" * 12, "-")
    fake_gh.set_issue(REPO, 42, f"a\n{stamp}\nb\n{stamp}\n")
    assert cmd_check(REPO, 42) == 2


def test_check_exits_2_on_v2_stamp(fake_gh) -> None:
    fake_gh.set_issue(REPO, 42, "<!-- cold-read-stamp: v2 body=aaaaaaaaaaaa -->\n")
    assert cmd_check(REPO, 42) == 2


def test_check_exits_2_on_failed_fetch(fake_gh) -> None:
    # 42 never registered -> fetch 404s.
    assert cmd_check(REPO, 42) == 2


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #

def test_main_cli_stamp_apply_then_check(fake_gh, fake_git) -> None:
    fake_gh.set_issue(REPO, 42, "cli body\n")
    fake_git.shas["origin/dev"] = "d" * 40

    rc = main(["stamp", "--repo", REPO, "--issue", "42", "--repo-dir", "/repo", "--target", "dev", "--apply"])
    assert rc == 0

    rc = main(["check", "--repo", REPO, "--issue", "42"])
    assert rc == 0
