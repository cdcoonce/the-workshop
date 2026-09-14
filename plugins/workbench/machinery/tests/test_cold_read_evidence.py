from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from cold_read_evidence import (  # noqa: E402
    VERDICT_EXIT_CODES,
    classify_token,
    collect,
    extract_tokens,
    main,
    normalize_backtick_token,
    parse_path_line_token,
)


def _graphmark_at_least_0_7() -> bool:
    try:
        ver = importlib.metadata.version("graphmark")
    except importlib.metadata.PackageNotFoundError:
        return False
    parts = ver.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return False
    return (major, minor) >= (0, 7)


NEEDS_GRAPHMARK_07 = pytest.mark.skipif(
    not _graphmark_at_least_0_7(),
    reason="requires graphmark>=0.7 (see make test-cold-read-evidence-wikilink-parity)",
)


# --------------------------------------------------------------------------- #
# git fixture helpers
# --------------------------------------------------------------------------- #

def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _git_init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_bytes(root: Path, rel: str, data: bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _commit_all(repo: Path, message: str) -> None:
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-q", "-m", message], repo)


def make_repo_pair(tmp_path: Path, owner: str = "testowner", name: str = "breakroom") -> tuple[Path, Path, str]:
    """Build an ``upstream`` (acts as origin) and a ``checkout`` (repo-dir) pair.

    ``upstream`` lives under ``tmp_path/remotes/<owner>/<name>`` so its path's
    trailing two segments are exactly ``owner/name`` — what ``--repo`` must
    match against the checkout's ``origin`` remote URL. Returns
    ``(upstream, checkout, "owner/name")``.
    """
    upstream = tmp_path / "remotes" / owner / name
    _git_init(upstream)
    # Allows a later push into upstream's currently-checked-out branch
    # (push_to_upstream) without touching its working tree.
    _run(["git", "config", "receive.denyCurrentBranch", "updateInstead"], upstream)
    _write(upstream, "README.md", "# repo\n")
    _commit_all(upstream, "init")

    checkout = tmp_path / "checkout"
    _run(["git", "clone", "-q", str(upstream), str(checkout)], tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], checkout)
    _run(["git", "config", "user.name", "Test"], checkout)
    return upstream, checkout, f"{owner}/{name}"


def push_to_upstream(upstream: Path, checkout: Path, rel: str, text: str, message: str) -> str:
    """Write+commit+push a file via a throwaway clone of upstream, so ``checkout``'s
    local HEAD does not silently advance (proves the working tree / local HEAD is
    never what resolution reads — only the fetched ``--ref``)."""
    work = upstream.parent / f"_push_work_{rel.replace('/', '_')}"
    _run(["git", "clone", "-q", str(upstream), str(work)], upstream.parent)
    _run(["git", "config", "user.email", "test@example.com"], work)
    _run(["git", "config", "user.name", "Test"], work)
    _write(work, rel, text)
    _commit_all(work, message)
    _run(["git", "push", "-q", "origin", "HEAD:main"], work)
    sha = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    return sha


# --------------------------------------------------------------------------- #
# fake gh seam
# --------------------------------------------------------------------------- #

class FakeGh:
    """Records calls; ``issues`` maps 'owner/repo#N' (or 'owner/repo' for a
    bare repos/<owner>/<repo> lookup) -> a canned response. ``custom`` maps
    the exact ``api`` path string to a raw (rc, stdout, stderr) tuple,
    overriding the default success/404 behavior -- for a non-404 failure
    (rate limit, auth, 5xx) that must never read as NOT_FOUND."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.issue_bodies: dict[tuple[str, int], str] = {}
        self.issues: dict[str, dict] = {}
        self.custom: dict[str, tuple[int, str, str]] = {}
        self.unavailable = False

    def __call__(self, args: list[str], timeout: int = 30):
        self.calls.append(args)
        if self.unavailable:
            return None
        if args[:2] == ["issue", "view"]:
            number = int(args[2])
            repo = args[args.index("--repo") + 1]
            body = self.issue_bodies.get((repo, number))
            if body is None:
                return (1, "", "gh: issue not found")
            import json as _json

            return (0, _json.dumps({"body": body}), "")
        if args[0] == "api":
            path = args[1]
            if path in self.custom:
                return self.custom[path]
            key = path.removeprefix("repos/").replace("/issues/", "#")
            data = self.issues.get(key)
            if data is None:
                return (1, "", "gh: HTTP 404: Not Found")
            import json as _json

            return (0, _json.dumps(data), "")
        raise AssertionError(f"unexpected fake gh call: {args}")


@pytest.fixture
def fake_gh(monkeypatch):
    import cold_read_evidence as cre

    fake = FakeGh()
    monkeypatch.setattr(cre, "_run_gh", fake)
    return fake


# =========================================================================== #
# classify_token — unit tests over the corpus rule table
# =========================================================================== #

@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("afk-driver --fleet-health", "SKIP_COMMAND"),
        ("git ls-remote origin", "SKIP_COMMAND"),
        ("--deny-surface-check", "SKIP_FLAG"),
        ("~/.afk-oauth-token", "LOCAL"),
        ("/Users/charles/x", "LOCAL"),
        ("<project>/.afk/last-cycle.json", "TEMPLATED"),
        ("tests/fixtures/scope_corpus/<case>/", "TEMPLATED"),
        ("data/thresholds/*.toml", "GLOB"),
        ("src/afk_driver/cli.py:3349", "PATH_LINE"),
        ("norms.py:171", "PATH_LINE"),
        ("docs/design/storylets.md:163-164", "PATH_LINE"),
        ("chronicle/", "PATH"),
        ("chronicles/", "PATH"),
        ("src/breakroom/chronicle.py", "PATH"),
        (".afk/config.toml", "PATH"),
        ("0a5a91e2d1", "SHA"),
        ("_expense_fraud", "SYMBOL"),
        ("_expense_claim_overstated", "SYMBOL"),
        ("breakroom.economy.move_dial", "SYMBOL"),
        ("coverage_gate.scan_diff_for_untested_modules", "SYMBOL"),
        ("deadbeef", "SYMBOL"),  # no digit -> not a SHA, but is symbol-shaped
        ("added", "SYMBOL"),
        ("!!!", "SKIP_OTHER"),
    ],
)
def test_classify_token(token: str, expected: str) -> None:
    assert classify_token(token) == expected


def test_classify_order_flag_beats_local_shape() -> None:
    # starts with '-', not '/', so SKIP_FLAG must win even though it also
    # contains no whitespace.
    assert classify_token("-x") == "SKIP_FLAG"


# =========================================================================== #
# extract_tokens — extraction guards
# =========================================================================== #

def test_fenced_code_block_ignored() -> None:
    body = "before\n```\n`inside.py` #999 [[Nope]]\n```\nafter `real.py`"
    tokens = extract_tokens(body)
    texts = [t["text"] for t in tokens]
    assert "inside.py" not in texts
    assert "999" not in texts
    assert "real.py" in texts


def test_hash_inside_word_or_url_fragment_ignored() -> None:
    body = "see docs/design/storylets.md#123 and word#123here, but standalone #456 counts."
    tokens = extract_tokens(body)
    issue_tokens = [t for t in tokens if t["cls"] == "ISSUE_REF"]
    numbers = [t["number"] for t in issue_tokens]
    assert 123 not in numbers
    assert 456 in numbers


def test_duplicate_tokens_collapse() -> None:
    body = "See `norms.py:171` and again `norms.py:171` later."
    tokens = extract_tokens(body)
    matching = [t for t in tokens if t["text"] == "norms.py:171"]
    assert len(matching) == 1


def test_backtick_spans_extracted_inside_tables_and_lists() -> None:
    body = (
        "| col |\n"
        "| --- |\n"
        "| `table.py` |\n"
        "\n"
        "- `list_item.py`\n"
    )
    tokens = extract_tokens(body)
    texts = [t["text"] for t in tokens]
    assert "table.py" in texts
    assert "list_item.py" in texts


def test_zero_tokens_extracted_from_plain_prose() -> None:
    assert extract_tokens("Just some plain words with no evidence at all.") == []


def test_wikilink_extraction_strips_alias_and_heading() -> None:
    body = "See [[Some Note|alias text]] and [[Other Note#Heading]]."
    tokens = extract_tokens(body)
    wiki = [t["text"] for t in tokens if t["cls"] == "WIKILINK"]
    assert "Some Note" in wiki
    assert "Other Note" in wiki


def test_bare_sha_extraction_requires_digit_and_letter() -> None:
    body = "commit deadbeef fixed it, but added more later. Real one: 0a5a91e2d1abc."
    tokens = extract_tokens(body)
    sha_texts = [t["text"] for t in tokens if t["cls"] == "SHA"]
    assert "deadbeef" not in sha_texts
    assert "added" not in sha_texts
    assert any(s.startswith("0a5a91e2d1") for s in sha_texts)


def test_issue_url_form_extracted() -> None:
    body = "https://github.com/acme/widgets/issues/42 and https://github.com/acme/widgets/pull/7"
    tokens = extract_tokens(body)
    refs = [(t["repo"], t["number"]) for t in tokens if t["cls"] == "ISSUE_REF"]
    assert ("acme/widgets", 42) in refs
    assert ("acme/widgets", 7) in refs


def test_owner_repo_hash_form_extracted() -> None:
    body = "See acme/widgets#42 for details."
    tokens = extract_tokens(body)
    refs = [(t["repo"], t["number"]) for t in tokens if t["cls"] == "ISSUE_REF"]
    assert ("acme/widgets", 42) in refs


# =========================================================================== #
# resolution buckets — breakroom#17 (paths)
# =========================================================================== #

def test_breakroom17_path_buckets(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "chronicles/log.md", "x\n")
    _write(upstream, "src/breakroom/norms.py", "x = 1\n")
    _commit_all(upstream, "add chronicles and norms")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "Evidence: `chronicle/` is wrong; `chronicles/` is right; `src/breakroom/chronicle.py` is a destination."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body17.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    rows = {r["token"]: r["result"] for r in report["rows"]}
    assert rows["chronicle/"] == "UNRESOLVED"
    assert rows["src/breakroom/chronicle.py"] == "PARENT_ONLY"
    # chronicles/ exists directly at root (direct ls-tree hit) -> RESOLVES.
    # Either way it's OK severity, no row.
    counted = report["counts"].get("PATH:RESOLVES", 0) + report["counts"].get("PATH:RESOLVES_BY_SUFFIX", 0)
    assert counted >= 1
    assert report["verdict"] == "CHECK_REQUIRED"
    assert report["exit_code"] == 1


# =========================================================================== #
# REFERENCED_ONLY — a directory git never records but code establishes
# (breakroom#17 precision-check finding: chronicles/ is created at runtime
# by `(world / "chronicles").mkdir(...)`, never committed, so plain
# git-tree PATH resolution false-blocks the exact path a human cold read
# confirmed as correct)
# =========================================================================== #

def test_referenced_only_bucket(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(
        upstream, "src/breakroom/init.py",
        'from pathlib import Path\n\n'
        'def make_world(root: Path) -> None:\n'
        '    (root / "chronicles").mkdir(parents=True, exist_ok=True)\n',
    )
    _write(
        upstream, "src/breakroom/tick.py",
        'def write_chronicle(world, day):\n'
        '    return world / "chronicles" / f"day-{day:04d}.md"\n',
    )
    # chronicles.py deliberately NOT written: it must stay a missing file,
    # untouched by the REFERENCED_ONLY directory check.
    _commit_all(upstream, "runtime-created chronicles/, never committed")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = (
        "Digests write to `chronicles/`. The stale name `chronicle/` is wrong. "
        "The helper is `write_chronicle` (not a path). "
        "A destination `chronicles.py` doesn't exist yet."
    )
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body_refonly.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    rows = {r["token"]: r for r in report["rows"]}

    # chronicles/ -> REFERENCED_ONLY, with the init.py evidence line.
    assert rows["chronicles/"]["result"] == "REFERENCED_ONLY"
    assert rows["chronicles/"]["severity"] == "CHECK"
    assert "init.py" in rows["chronicles/"]["detail"]
    assert "chronicles" in rows["chronicles/"]["detail"]

    # chronicle/ (singular) has no quoted-literal occurrence anywhere ->
    # still a flat UNRESOLVED, still BLOCKING. The recall case must survive.
    assert rows["chronicle/"]["result"] == "UNRESOLVED"
    assert rows["chronicle/"]["severity"] == "CHECK"

    # `write_chronicle` is a SYMBOL token (identifier-shaped, no '/'), not a
    # PATH token -- it is exercised as its own class, not as a directory
    # substring match. Confirm it resolves as SYMBOL:FOUND (grep -w finds
    # the def), never contaminating the PATH REFERENCED_ONLY check.
    assert "write_chronicle" not in rows  # FOUND is OK severity -> no row
    assert report["counts"].get("SYMBOL:FOUND", 0) >= 1

    # chronicles.py is a file token (has an extension) -> unaffected by
    # REFERENCED_ONLY; PARENT_ONLY since its parent (repo root) is not a
    # named directory, matching the pre-existing rule for a root-level file.
    assert rows["chronicles.py"]["result"] in ("PARENT_ONLY", "UNRESOLVED")

    assert report["verdict"] == "CHECK_REQUIRED"  # chronicle/ alone still blocks


def test_referenced_only_requires_quoted_literal_not_bare_substring(tmp_path: Path, fake_gh) -> None:
    """A directory name that only occurs as a substring of a longer
    identifier (never quoted on its own) must NOT get REFERENCED_ONLY --
    that would demote an unrelated / wrong directory just because some
    function happens to share a word with it."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(
        upstream, "src/breakroom/tick.py",
        'def write_chronicle(world, day):\n'
        '    return world / "chronicles" / f"day-{day:04d}.md"\n',
    )
    _commit_all(upstream, "only an identifier, no quoted 'chronicle' literal")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "Digests write to `chronicle/` today."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body_substr.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "chronicle/")
    assert row["result"] == "UNRESOLVED"
    assert row["severity"] == "CHECK"


# =========================================================================== #
# Bare-basename resolution — a PATH/PATH_LINE token with no directory
# component resolves across the whole tree at <ref>, not just the repo root
# (breakroom#17 current-body precision-check finding round 2: `tick.py:42-50`
# cites the file by its bare basename, the dominant real-spec citation
# style — secret_scan.py:57-64, norms.py:171, executor.py:386-392 — and the
# old root-only check false-blocked it even though the human's round-5 cold
# read re-verified it as real).
# =========================================================================== #

def _make_basename_fixture(tmp_path: Path):
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "basenametest")
    _write(upstream, "src/pkg/tick.py", "line one\nsecond line\nthird line\nfourth line\n")
    _write(upstream, "docs/a/notes.md", "a\n")
    _write(upstream, "docs/b/notes.md", "b\n")
    _write(upstream, "src/pkg/chronicles/log.md", "x\n")
    _write(upstream, "data/x.toml", "y = 1\n")
    _commit_all(upstream, "basename fixture")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    return upstream, checkout, repo


def test_bare_basename_path_line_resolves_uniquely(tmp_path: Path, fake_gh) -> None:
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "See `tick.py:2-3` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename1.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    # A resolved PATH_LINE is OK severity now (trusted) -> it lands in
    # evidence_lines for the reader to skim, not in rows as a CHECK finding.
    row = next(r for r in report["evidence_lines"] if r["token"] == "tick.py:2-3")
    assert row["result"] == "RESOLVES_BY_SUFFIX"
    assert row["line_text"] == ["second line", "third line"]
    assert not any(r["token"] == "tick.py:2-3" for r in report["rows"])


def test_bare_basename_path_line_out_of_range(tmp_path: Path, fake_gh) -> None:
    """The basename-matched path still runs the LINE_OUT_OF_RANGE check --
    the same code path as a direct match, not a separate unchecked one."""
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "See `tick.py:9999` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename_oor.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "tick.py:9999")
    assert row["result"] == "LINE_OUT_OF_RANGE"
    assert row["severity"] == "CHECK"


def test_bare_basename_path_ambiguous(tmp_path: Path, fake_gh) -> None:
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "See `notes.md` for context."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename2.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "notes.md")
    assert row["result"] == "AMBIGUOUS_SUFFIX"
    assert row["severity"] == "CHECK"
    assert "docs/a/notes.md" in row["detail"]
    assert "docs/b/notes.md" in row["detail"]
    assert "2" in row["detail"]  # candidate count


def test_bare_basename_zero_matches_falls_through_to_unresolved(tmp_path: Path, fake_gh) -> None:
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "See `nope.py` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename3.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "nope.py")
    assert row["result"] == "UNRESOLVED"
    assert row["severity"] == "CHECK"


def test_bare_basename_directory_resolves(tmp_path: Path, fake_gh) -> None:
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "Digests write to `chronicles/` today."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename4.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    # RESOLVES_BY_SUFFIX is OK severity for PATH -> no row, just a count.
    assert not any(r["token"] == "chronicles/" for r in report["rows"])
    assert report["counts"].get("PATH:RESOLVES_BY_SUFFIX", 0) >= 1


def test_bare_basename_directory_shaped_does_not_match_a_file(tmp_path: Path, fake_gh) -> None:
    """`tick/` (directory-shaped: trailing slash) must not match the FILE
    `src/pkg/tick.py` -- files and directories are separate basename tables,
    never cross-matched."""
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "See `tick/` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename5.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "tick/")
    assert row["result"] == "UNRESOLVED"


def test_brace_placeholder_no_directory_prefix(tmp_path: Path, fake_gh) -> None:
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "Digests are named `day-{day:04d}.md`, one per tick."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename6.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert not any(r["token"] == "day-{day:04d}.md" for r in report["rows"])
    assert report["counts"].get("TEMPLATED:TEMPLATED_NO_PREFIX", 0) >= 1


def test_brace_placeholder_with_directory_prefix(tmp_path: Path, fake_gh) -> None:
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "Config lives at `data/{name}.toml`."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename7.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["counts"].get("TEMPLATED:PREFIX_RESOLVES", 0) >= 1


def test_brace_placeholder_with_unresolved_directory_prefix(tmp_path: Path, fake_gh) -> None:
    _, checkout, repo = _make_basename_fixture(tmp_path)
    body = "Config lives at `nosuchdir/{name}.toml`."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_basename8.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "nosuchdir/{name}.toml")
    assert row["result"] == "PREFIX_UNRESOLVED"
    assert row["severity"] == "CHECK"


def test_brace_token_with_quotes_is_not_templated() -> None:
    """A code snippet with a brace and a quote (f"{x}", {"check": POLICY})
    must not be misread as a templated filename convention."""
    assert classify_token('f"{x}"') != "TEMPLATED"
    assert classify_token('{"check": POLICY}') == "SKIP_COMMAND"  # whitespace wins first


# =========================================================================== #
# resolution buckets — breakroom#59 (symbols)
# =========================================================================== #

def test_breakroom59_symbol_buckets(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "src/breakroom/norms.py", "def _expense_claim_overstated():\n    pass\n")
    _commit_all(upstream, "add norms")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "`_expense_fraud` is not real; `_expense_claim_overstated` is."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body59.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    rows = {r["token"]: r["result"] for r in report["rows"]}
    assert rows["_expense_fraud"] == "ABSENT"
    assert report["counts"].get("SYMBOL:FOUND", 0) >= 1
    assert report["verdict"] == "CHECK_REQUIRED"
    assert report["exit_code"] == 1  # CHECK_REQUIRED always exits 1 now


# =========================================================================== #
# resolution buckets — breakroom#40 (path_line + line drift + absent dotted symbol)
# =========================================================================== #

def test_breakroom40_path_line_and_out_of_range(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    lines = [f"line {i}" for i in range(1, 200)]
    lines[162] = "the real storylet text at 163"  # 0-indexed -> line 163
    lines[163] = "the real storylet text at 164"  # line 164
    _write(upstream, "docs/design/storylets.md", "\n".join(lines) + "\n")
    _commit_all(upstream, "add storylets")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = (
        "See `docs/design/storylets.md:163-164` for the mechanic, "
        "and `docs/design/storylets.md:9999` which is beyond the file, "
        "and `breakroom.economy.move_dial` which does not exist."
    )
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body40.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    rows = {r["token"]: r for r in report["rows"]}
    evidence = {r["token"]: r for r in report["evidence_lines"]}
    # A resolved PATH_LINE is OK/evidence now, not a CHECK row.
    good = evidence["docs/design/storylets.md:163-164"]
    assert good["result"] == "RESOLVES"
    assert good["line_text"][0] == "the real storylet text at 163"
    assert good["line_text"][1] == "the real storylet text at 164"
    assert "docs/design/storylets.md:163-164" not in rows
    assert rows["docs/design/storylets.md:9999"]["result"] == "LINE_OUT_OF_RANGE"
    assert rows["breakroom.economy.move_dial"]["result"] == "ABSENT"
    assert report["verdict"] == "CHECK_REQUIRED"  # LINE_OUT_OF_RANGE still needs a CHECK


def test_path_line_caps_at_three_lines_and_160_chars(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    long_line = "x" * 300
    text = "\n".join([long_line] * 10) + "\n"
    _write(upstream, "big.py", text)
    _commit_all(upstream, "add big.py")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "See `big.py:1-5` please."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodybig.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["evidence_lines"] if r["token"] == "big.py:1-5")
    assert len(row["line_text"]) == 3
    assert all(len(line) <= 160 for line in row["line_text"])


# =========================================================================== #
# afk#1380 — templated / skip_command classification
# =========================================================================== #

def test_afk1380_templated_and_skip_command(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "afk-agent-system")
    _commit_all(upstream, "noop") if False else None  # README already committed by make_repo_pair
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "Run `afk-driver --fleet-health` then check `<project>/.afk/last-cycle.json`."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body1380.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["counts"].get("SKIP_COMMAND:(none)", 0) >= 1
    # <project>/.afk/last-cycle.json has nothing before its placeholder
    # (<project> IS the placeholder) -> TEMPLATED_NO_PREFIX, not
    # PREFIX_RESOLVES (there is no literal directory prefix to have checked).
    assert report["counts"].get("TEMPLATED:TEMPLATED_NO_PREFIX", 0) >= 1
    # Neither is a blocking/judgment row.
    tokens_in_rows = {r["token"] for r in report["rows"]}
    assert "afk-driver --fleet-health" not in tokens_in_rows
    assert "<project>/.afk/last-cycle.json" not in tokens_in_rows


def test_local_and_glob_prefix(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "afk-agent-system")
    _write(upstream, "data/thresholds/x.toml", "a = 1\n")
    _commit_all(upstream, "add thresholds")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "Token `~/.afk-oauth-token` is local; `data/thresholds/*.toml` should resolve."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyglob.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["counts"].get("LOCAL:(none)", 0) >= 1
    assert report["counts"].get("GLOB:PREFIX_RESOLVES", 0) >= 1


def test_glob_prefix_unresolved(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "afk-agent-system")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "`data/thresholds/*.toml` should NOT resolve here."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyglob2.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "data/thresholds/*.toml")
    assert row["result"] == "PREFIX_UNRESOLVED"
    assert report["verdict"] == "CHECK_REQUIRED"


# =========================================================================== #
# SHA resolution
# =========================================================================== #

def test_sha_exists_and_missing(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    real_sha = _run(["git", "-C", str(upstream), "rev-parse", "HEAD"], tmp_path).stdout.strip()
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = f"Commit `{real_sha}` fixed it. Commit `deadbeefcafe01` did not."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodysha.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    rows = {r["token"]: r["result"] for r in report["rows"]}
    assert rows[real_sha] if real_sha in rows else True  # exists -> not a row (OK), tolerate absence
    assert report["counts"].get("SHA:COMMIT_EXISTS", 0) >= 1
    missing_row = next(r for r in report["rows"] if r["token"] == "deadbeefcafe01")
    assert missing_row["result"] == "COMMIT_MISSING"


# =========================================================================== #
# issue/PR refs via fake gh
# =========================================================================== #

def test_issue_ref_states(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    fake_gh.issues[f"{repo}#1"] = {"state": "open"}
    fake_gh.issues[f"{repo}#2"] = {"state": "closed"}
    fake_gh.issues[f"{repo}#3"] = {"state": "closed", "pull_request": {"merged_at": "2026-01-01T00:00:00Z"}}
    # #4 intentionally absent -> NOT_FOUND
    fake_gh.issues["otherowner/other#9"] = {"state": "open"}

    body = "#1 open, #2 closed, #3 merged, #4 missing, otherowner/other#9 elsewhere."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyissues.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    rows = {r["token"]: r["result"] for r in report["rows"]}
    assert rows["#4"] == "NOT_FOUND"
    assert report["counts"].get("ISSUE_REF:OPEN", 0) >= 2  # #1 and otherowner/other#9
    assert report["counts"].get("ISSUE_REF:CLOSED", 0) >= 1
    assert report["counts"].get("ISSUE_REF:MERGED", 0) >= 1
    assert report["verdict"] == "CHECK_REQUIRED"


def test_owner_repo_hash_queries_that_repo_not_default(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    fake_gh.issues["otherowner/other#5"] = {"state": "open"}

    body = "otherowner/other#5 is the reference."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyother.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    calls = [c for c in fake_gh.calls if c[0] == "api"]
    assert any("otherowner/other/issues/5" in c[1] for c in calls)
    assert not any(f"{repo}/issues/5" in c[1] for c in calls)


# =========================================================================== #
# Ref policy — working tree is never read
# =========================================================================== #

def test_working_tree_only_path_is_unresolved_at_ref(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    # Untracked, working-tree-only file.
    _write(checkout, "only_local.py", "x = 1\n")

    body = "See `only_local.py` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodylocal.md", body),
        ref=None, no_fetch=True, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "only_local.py")
    assert row["result"] == "UNRESOLVED"


def test_committed_on_local_branch_not_at_ref_is_unresolved(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    _write(checkout, "local_only.py", "x = 1\n")
    _commit_all(checkout, "local only, never pushed")

    body = "See `local_only.py` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodylocal2.md", body),
        ref="origin/main", no_fetch=True, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "local_only.py")
    assert row["result"] == "UNRESOLVED"


def test_path_added_upstream_after_local_head_resolves_once_fetched(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    push_to_upstream(upstream, checkout, "new_upstream.py", "x = 1\n", "add new_upstream.py")
    # checkout's local HEAD has NOT advanced.

    body = "See `new_upstream.py` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyupstream.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    # RESOLVES(_BY_SUFFIX) is OK severity -> no row emitted; a row here
    # would mean it was (wrongly) UNRESOLVED or PARENT_ONLY instead.
    assert not any(r["token"] == "new_upstream.py" for r in report["rows"])
    resolved_count = (
        report["counts"].get("PATH:RESOLVES", 0) + report["counts"].get("PATH:RESOLVES_BY_SUFFIX", 0)
    )
    assert resolved_count >= 1


def test_default_branch_read_from_remote_not_local_head(tmp_path: Path, fake_gh) -> None:
    """ragmark-shaped: default branch is 'dev', not 'main'; must not be hardcoded."""
    upstream = tmp_path / "remotes" / "testowner" / "ragmark"
    _git_init(upstream)
    _run(["git", "-C", str(upstream), "checkout", "-q", "-b", "dev"], tmp_path)
    _write(upstream, "README.md", "# ragmark\n")
    _commit_all(upstream, "init on dev")
    _run(["git", "-C", str(upstream), "symbolic-ref", "HEAD", "refs/heads/dev"], tmp_path)
    _write(upstream, "evidence.py", "x = 1\n")
    _commit_all(upstream, "add evidence.py")

    checkout = tmp_path / "checkout_ragmark"
    _run(["git", "clone", "-q", str(upstream), str(checkout)], tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], checkout)
    _run(["git", "config", "user.name", "Test"], checkout)

    body = "See `evidence.py` for the fix."
    report = collect(
        repo="testowner/ragmark", repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyragmark.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["resolved_ref"] == "origin/dev"


# =========================================================================== #
# INCOMPLETE conditions
# =========================================================================== #

def test_empty_body_is_incomplete_never_resolved(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path)
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "empty.md", "   \n"),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2
    assert "empty body" in " ".join(report["input_errors"])


def test_zero_extractable_tokens_is_incomplete(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path)
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "prose.md", "Just prose, nothing to check."),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2


def test_repo_dir_not_a_git_repo_is_incomplete(tmp_path: Path, fake_gh) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    report = collect(
        repo="testowner/breakroom", repo_dir=not_a_repo, issue=None,
        body_file=_write(tmp_path, "body.md", "`x.py` evidence."),
        ref=None, no_fetch=True, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2


def test_repo_dir_origin_mismatch_is_incomplete(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    report = collect(
        repo="someone/else", repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body.md", "`x.py` evidence."),
        ref=None, no_fetch=True, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2


def test_ref_does_not_resolve_after_fetch_is_incomplete(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "body.md", "`x.py` evidence."),
        ref="origin/does-not-exist-branch", no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2


def test_gh_failure_with_issue_refs_present_is_incomplete(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    fake_gh.unavailable = True

    body = "See #42 for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodygh.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2
    assert any(nr["class"] == "issue_ref" for nr in report["not_run"])


def test_graphmark_unavailable_with_wikilink_present_is_incomplete(tmp_path: Path, monkeypatch, fake_gh) -> None:
    import builtins

    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    vault_root = tmp_path / "vault"
    _write(vault_root, ".vault/vault.json", "{}")

    real_import = builtins.__import__

    def blocked_import(name, *a, **kw):
        if name == "graph_cli" or name.startswith("graphmark"):
            raise ImportError("graphmark blocked for test")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    body = "See [[Some Note]] for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodywiki.md", body),
        ref=None, no_fetch=False, vault_root=vault_root, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2
    assert any(nr["class"] == "wikilink" for nr in report["not_run"])


# =========================================================================== #
# wikilinks against a tmp fixture vault
# =========================================================================== #

def test_wikilink_resolves_and_unresolved(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    vault_root = tmp_path / "vault"
    _write(vault_root, ".vault/vault.json", "{}")
    _write(vault_root, "work/active/Some Note.md", "---\ndate: 2026-01-01\n---\n\n# Some Note\n\nbody\n")
    _write(vault_root, "ci/vault_health.py", "")

    body = "See [[Some Note]] which exists and [[Totally Missing Note]] which does not."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodywiki2.md", body),
        ref=None, no_fetch=False, vault_root=vault_root, limit=20,
    )
    rows = {r["token"]: r["result"] for r in report["rows"]}
    assert rows["Totally Missing Note"] == "NOTE_UNRESOLVED"
    assert report["counts"].get("WIKILINK:NOTE_RESOLVES", 0) >= 1
    assert report["verdict"] == "CHECK_REQUIRED"


# =========================================================================== #
# --issue via fake gh
# =========================================================================== #

def test_issue_body_fetched_via_gh(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "evidence.py", "x = 1\n")
    _commit_all(upstream, "add evidence")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    fake_gh.issue_bodies[(repo, 100)] = "See `evidence.py` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=100, body_file=None,
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "ALL_RESOLVED"
    assert report["exit_code"] == 0


def test_issue_body_missing_is_incomplete(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    report = collect(
        repo=repo, repo_dir=checkout, issue=999, body_file=None,
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2


# =========================================================================== #
# non-ASCII / spaces round trip
# =========================================================================== #

def test_path_with_unicode_name_round_trips(tmp_path: Path, fake_gh) -> None:
    """Filenames with non-ASCII names must round-trip through PATH_LINE resolution.

    A space in the token itself is a separate (and, per the corpus
    classify_token rule table, deliberately unresolvable — SKIP_COMMAND
    wins on any whitespace) case; see test_classify_token. This test
    isolates the non-ASCII half of the carry-over lesson.
    """
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "docs/désign/café-plan.md", "line one\nla ligne deux\n")
    _commit_all(upstream, "add unicode path")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "See `docs/désign/café-plan.md:2` for the plan."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyunicode.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["evidence_lines"] if r["token"].startswith("docs/désign"))
    assert row["result"] == "RESOLVES"
    assert row["line_text"][0] == "la ligne deux"


def test_path_with_space_in_token_is_skip_command_not_path(tmp_path: Path, fake_gh) -> None:
    """A literal space inside a backticked token always wins as SKIP_COMMAND
    (classify_token's whitespace rule is first and unconditional), even when
    the token also looks path-shaped. This is a corpus rule, not a gap: paths
    the resolver must check never contain spaces in the 12-issue corpus."""
    assert classify_token("docs/has space/plan.md") == "SKIP_COMMAND"


# =========================================================================== #
# --limit / rendering / verdict priority
# =========================================================================== #

def test_verdict_precedence_incomplete_beats_blocking(tmp_path: Path, fake_gh) -> None:
    """not_run (INCOMPLETE) must win even when a BLOCKING row also exists."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    fake_gh.unavailable = True

    body = "`totally_missing_file.py` is blocking, and #1 needs gh which is down."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodyprec.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2


def test_main_returns_matching_exit_code(tmp_path: Path, fake_gh, capsys) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "evidence.py", "x = 1\n")
    _commit_all(upstream, "add evidence")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body_file = _write(tmp_path, "bodymain.md", "See `evidence.py`.")

    rc = main([
        "--repo", repo, "--repo-dir", str(checkout),
        "--body-file", str(body_file), "--json",
    ])
    assert rc == VERDICT_EXIT_CODES["ALL_RESOLVED"] == 0
    out = capsys.readouterr().out
    assert '"verdict": "ALL_RESOLVED"' in out


def test_main_crash_exits_2_not_1(tmp_path: Path, monkeypatch, fake_gh) -> None:
    import cold_read_evidence as cre

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(cre, "collect", boom)
    rc = main(["--repo", "a/b", "--repo-dir", str(tmp_path), "--body-file", str(tmp_path / "nope.md")])
    assert rc == 2


# =========================================================================== #
# afk-agent-system#1380 classification-only smoke shape (unit, no network)
# =========================================================================== #

def test_afk1380_shape_classification_only() -> None:
    assert classify_token("afk-driver --fleet-health") == "SKIP_COMMAND"
    assert classify_token(".afk/last-cycle.json") == "PATH"


# =========================================================================== #
# graphmark 0.7 parity fixtures
# =========================================================================== #

@NEEDS_GRAPHMARK_07
def test_graphmark_07_wikilink_resolution_matches_06(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    vault_root = tmp_path / "vault07"
    _write(vault_root, ".vault/vault.json", "{}")
    _write(vault_root, "work/active/Some Note.md", "---\ndate: 2026-01-01\n---\n\n# Some Note\n\nbody\n")
    _write(vault_root, "ci/vault_health.py", "")

    body = "See [[Some Note]] which exists."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "bodywiki07.md", body),
        ref=None, no_fetch=False, vault_root=vault_root, limit=20,
    )
    assert report["counts"].get("WIKILINK:NOTE_RESOLVES", 0) >= 1
    import importlib.metadata as im

    print("graphmark version under test:", im.version("graphmark"))


# =========================================================================== #
# Round 4 — severity model (A): OK (trusted, no re-check) / CHECK (verify
# before it counts as a finding). Corpus review scored the old BLOCKING
# model at ~2% precision (166 rows, ~3-4 real) across 41 real issues.
# =========================================================================== #

def test_severity_table_is_only_ok_or_check() -> None:
    import cold_read_evidence as cre

    for (cls, result), severity in cre._SEVERITY.items():
        assert severity in ("OK", "CHECK"), f"{cls}:{result} -> {severity}"


@pytest.mark.parametrize(
    ("cls", "result", "expected"),
    [
        ("PATH", "RESOLVES", "OK"),
        ("PATH", "RESOLVES_BY_SUFFIX", "OK"),
        ("PATH", "PARENT_ONLY", "CHECK"),
        ("PATH", "UNRESOLVED", "CHECK"),
        ("PATH", "REFERENCED_ONLY", "CHECK"),
        ("PATH", "AMBIGUOUS_SUFFIX", "CHECK"),
        ("PATH_LINE", "RESOLVES", "OK"),
        ("PATH_LINE", "RESOLVES_BY_SUFFIX", "OK"),
        ("PATH_LINE", "LINE_OUT_OF_RANGE", "CHECK"),
        ("PATH_LINE", "DIRECTORY_NOT_FILE", "CHECK"),
        ("PATH_LINE", "BINARY_FILE", "CHECK"),
        ("SYMBOL", "FOUND", "OK"),
        ("SYMBOL", "FOUND_IN_DOCS_OR_TESTS", "CHECK"),
        ("SYMBOL", "ABSENT", "CHECK"),
        ("SHA", "COMMIT_EXISTS", "OK"),
        ("SHA", "COMMIT_EXISTS_UNREACHABLE", "CHECK"),
        ("SHA", "COMMIT_MISSING", "CHECK"),
        ("ISSUE_REF", "OPEN", "OK"),
        ("ISSUE_REF", "CLOSED", "OK"),
        ("ISSUE_REF", "MERGED", "OK"),
        ("ISSUE_REF", "NOT_FOUND", "CHECK"),
        ("WIKILINK", "NOTE_RESOLVES", "OK"),
        ("WIKILINK", "NOTE_UNRESOLVED", "CHECK"),
        ("WIKILINK", "NOTE_AMBIGUOUS", "CHECK"),
        ("WIKILINK", "OUTSIDE_GRAPH_SCOPE", "CHECK"),
        ("REF", "REF_RESOLVES", "OK"),
        ("REF", "REF_UNRESOLVED", "CHECK"),
        ("REPO", "REPO_RESOLVES", "OK"),
        ("REPO", "REPO_UNRESOLVED", "CHECK"),
        ("TEMPLATED", "TEMPLATED_NO_PREFIX", "OK"),
        ("TEMPLATED", "PREFIX_UNRESOLVED", "CHECK"),
    ],
)
def test_severity_table_key_buckets(cls: str, result: str, expected: str) -> None:
    import cold_read_evidence as cre

    assert cre._SEVERITY[(cls, result)] == expected


def test_verdict_all_resolved_exit_0(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "evidence.py", "x = 1\n")
    _commit_all(upstream, "add evidence")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See `evidence.py` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_allresolved.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "ALL_RESOLVED"
    assert report["exit_code"] == 0


def test_verdict_check_required_exit_1(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "`_absent_symbol` is cited."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_checkreq.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "CHECK_REQUIRED"
    assert report["exit_code"] == 1


# =========================================================================== #
# Round 4 — bug fixes (B)
# =========================================================================== #

def test_gh_failure_on_second_ref_is_incomplete_not_resolved(tmp_path: Path, fake_gh) -> None:
    """Bug B1: collect() previously only checked the FIRST issue-ref gh
    call for failure; a later None result silently fell through
    ('already recorded as not_run above', except nothing was recorded).
    Repro: #1 open, #2 a non-404 gh failure, #3 a 404 -- must be
    INCOMPLETE with not_run, never a clean RESOLVED."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    fake_gh.issues[f"{repo}#1"] = {"state": "open"}
    fake_gh.custom[f"repos/{repo}/issues/2"] = (1, "", "gh: HTTP 403: API rate limit exceeded")
    # #3 intentionally absent from fake_gh.issues -> would 404 if reached

    body = "#1 is fine, #2 rate-limits, #3 is unresolved."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_ghfail2.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2
    assert report["not_run"], "must record the rate-limit failure"
    assert any(nr["class"] == "issue_ref" for nr in report["not_run"])


def test_non_404_gh_error_never_becomes_not_found(tmp_path: Path, fake_gh) -> None:
    """R14b / B1: a non-404 gh failure (rate limit, auth, 5xx) cannot
    distinguish private from nonexistent -- it must never be read as the
    authoritative NOT_FOUND result."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    fake_gh.custom[f"repos/{repo}/issues/5"] = (1, "", "HTTP 500: Internal Server Error")

    body = "#5 is cited."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_gh500.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert not any(r.get("result") == "NOT_FOUND" for r in report["rows"])
    assert any(nr["class"] == "issue_ref" for nr in report["not_run"])


def test_binary_cited_file_gives_check_not_crash(tmp_path: Path, fake_gh) -> None:
    """Bug B2: a cited binary (or non-UTF-8) file must not raise
    UnicodeDecodeError inside subprocess text-mode decoding -- it becomes a
    BINARY_FILE CHECK row."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write_bytes(upstream, "data/blob.bin", b"\xff\xfe\x00\x01\x02binary\x00tail")
    _commit_all(upstream, "add binary blob")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "See `data/blob.bin:1` for the format."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_binary.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "data/blob.bin:1")
    assert row["result"] == "BINARY_FILE"
    assert report["verdict"] == "CHECK_REQUIRED"


def test_per_token_exception_becomes_error_row_not_crash(tmp_path: Path, fake_gh, monkeypatch) -> None:
    """Bug B2 (general form): ANY per-token exception degrades to a single
    CHECK/ERROR row, never a whole-run crash -- other tokens still resolve."""
    import cold_read_evidence as cre

    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "ok.py", "x = 1\n")
    _commit_all(upstream, "add ok.py")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    def boom(*a, **kw):
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(cre, "_resolve_symbol", boom)

    body = "`some_symbol` and `ok.py` are both cited."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_crash.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    err_row = next(r for r in report["rows"] if r["class"] == "SYMBOL" and r["result"] == "ERROR")
    assert "resolver exploded" in err_row["detail"]
    assert not any(r["token"] == "ok.py" for r in report["rows"])  # unaffected


def test_limit_never_elides_check_rows(tmp_path: Path, fake_gh) -> None:
    """Bug B3 (afk#1378: 26 of 36 past row 20): --limit must never hide a
    CHECK row, however many there are."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = " ".join(f"`_absent_sym_{i}`" for i in range(30))
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_manycheck.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=5,
    )
    assert len(report["rows"]) == 30
    assert report["elided"] == 0


def test_limit_elides_evidence_lines_not_rows(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    for i in range(10):
        _write(upstream, f"f{i}.py", "a\nb\nc\n")
    _commit_all(upstream, "add many files")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = " ".join(f"`f{i}.py:1`" for i in range(10))
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_manyevidence.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=3,
    )
    assert len(report["evidence_lines"]) == 3
    assert report["evidence_elided"] == 7


def test_run_git_sets_literal_pathspecs_env(tmp_path: Path, monkeypatch, fake_gh) -> None:
    """Pathspec-magic fix: every git call must run with
    GIT_LITERAL_PATHSPECS=1 so a cited path beginning with ':' is read
    literally, never as pathspec magic."""
    import cold_read_evidence as cre

    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    captured: dict[str, Any] = {}
    real_run = cre.subprocess.run

    def spy(*a, **kw):
        captured["env"] = kw.get("env")
        return real_run(*a, **kw)

    monkeypatch.setattr(cre.subprocess, "run", spy)
    cre._run_git(checkout, ["rev-parse", "HEAD"])
    assert captured["env"] is not None
    assert captured["env"].get("GIT_LITERAL_PATHSPECS") == "1"


# =========================================================================== #
# Round 4 — extraction/resolution fixes (C)
# =========================================================================== #

def test_html_comment_masked() -> None:
    body = "before <!-- `secret.py` hidden --> after `real.py`"
    texts = [t["text"] for t in extract_tokens(body)]
    assert "secret.py" not in texts
    assert "real.py" in texts


def test_details_content_is_not_masked() -> None:
    body = "<details>\n\n`visible.py` is inside details, which renders.\n\n</details>"
    texts = [t["text"] for t in extract_tokens(body)]
    assert "visible.py" in texts


def test_indented_code_block_masked() -> None:
    body = "Some prose.\n\n    `hidden.py` indented code block\n\nMore prose with `visible.py`."
    texts = [t["text"] for t in extract_tokens(body)]
    assert "hidden.py" not in texts
    assert "visible.py" in texts


def test_four_backtick_fence_with_nested_shorter_fence_masked() -> None:
    body = "````\n```\n`nested.py` still fenced\n```\n`hidden.py`\n````\nAfter fence `real.py`."
    texts = [t["text"] for t in extract_tokens(body)]
    assert "nested.py" not in texts
    assert "hidden.py" not in texts
    assert "real.py" in texts


def test_tilde_fence_masked() -> None:
    body = "~~~\n`hidden.py`\n~~~\n`real.py` after."
    texts = [t["text"] for t in extract_tokens(body)]
    assert "hidden.py" not in texts
    assert "real.py" in texts


def test_stray_backtick_does_not_shift_a_later_well_formed_span() -> None:
    """CommonMark backtick-run pairing: a run with no same-length partner
    on ITS line is not a delimiter and must not swallow (or shift the
    position of) a later, properly paired span on a different line."""
    body = "A stray backtick ` appears here with no partner on this line.\nSee `ghost3b.py` for the real citation."
    texts = [t["text"] for t in extract_tokens(body)]
    assert "ghost3b.py" in texts


def test_trailing_punctuation_stripped_before_classification() -> None:
    assert normalize_backtick_token("norms.py:171,") == "norms.py:171"
    assert normalize_backtick_token("secret_scan.py:57-64.") == "secret_scan.py:57-64"
    texts = [t["text"] for t in extract_tokens("See `norms.py:171,` for it.")]
    assert "norms.py:171" in texts


def test_hash_l_line_anchor_normalizes_to_path_line() -> None:
    tokens = extract_tokens("See `mod.py#L1-L2` for it.")
    t = next(t for t in tokens if t["cls"] == "PATH_LINE")
    assert t["text"] == "mod.py#L1-L2"
    assert parse_path_line_token(t["text"]) == ("mod.py", 1, 2)


def test_path_line_column_ignored() -> None:
    tokens = extract_tokens("See `src/pkg/mod.py:1:5` for it.")
    t = next(t for t in tokens if t["cls"] == "PATH_LINE")
    assert parse_path_line_token(t["text"]) == ("src/pkg/mod.py", 1, None)


def test_pytest_node_id_extracts_path_only() -> None:
    tokens = extract_tokens("See `tests/x.py::test_y` for it.")
    matching = [(t["text"], t["cls"]) for t in tokens if t["text"] == "tests/x.py"]
    assert ("tests/x.py", "PATH") in matching


def test_dotdot_normalization_within_repo() -> None:
    tokens = extract_tokens("See `src/../README.md` for it.")
    texts = [t["text"] for t in tokens]
    assert "README.md" in texts


def test_dotdot_escaping_repo_root_is_outside_repo(tmp_path: Path, fake_gh) -> None:
    tokens = extract_tokens("See `../../etc/passwd` for it.")
    assert any(t["cls"] == "OUTSIDE_REPO_TOKEN" for t in tokens)

    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_outside.md", "See `../../etc/passwd` for it."),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "../../etc/passwd")
    assert row["result"] == "OUTSIDE_REPO"
    assert row["severity"] == "CHECK"


def test_issue_zero_is_never_extracted() -> None:
    tokens = extract_tokens("See #0 for context.")
    assert not any(t["cls"] == "ISSUE_REF" for t in tokens)


def test_bare_extension_is_skipped_not_a_path() -> None:
    tokens = extract_tokens("Rename the `.py` file to `.sql`.")
    assert all(t["cls"] == "SKIP_BARE_EXTENSION" for t in tokens)


def test_alias_hash_n_shorthand_is_unknown_repo_alias(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See bms#235 for the related ticket."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_alias.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "bms#235")
    assert row["class"] == "UNKNOWN_REPO_ALIAS"
    assert row["severity"] == "CHECK"


def test_python_keyword_and_builtin_skipped() -> None:
    assert classify_token("return") == "SKIP_KEYWORD"
    assert classify_token("len") == "SKIP_KEYWORD"
    assert classify_token("None") == "SKIP_KEYWORD"


def test_dotted_symbol_through_builtin_looking_segment_still_resolves() -> None:
    # "os.path" is not itself a keyword/builtin (only bare names are
    # skipped) -- it must remain a normal, resolvable SYMBOL.
    assert classify_token("os.path") == "SYMBOL"


def test_subtree_relative_path_resolves_by_suffix(tmp_path: Path, fake_gh) -> None:
    """C: path-suffix resolution generalizes the round-3 basename rule --
    `engine/sync_manager.py` matches a file several directories deeper,
    not just a bare basename."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "tools/vault-ops/machinery/engine/sync_manager.py", "x = 1\n")
    _commit_all(upstream, "add nested engine file")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "See `engine/sync_manager.py` for the fix."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_suffix.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert not any(r["token"] == "engine/sync_manager.py" for r in report["rows"])
    assert report["counts"].get("PATH:RESOLVES_BY_SUFFIX", 0) >= 1


def test_suffix_does_not_match_a_different_file_with_same_ending() -> None:
    """A suffix match must align with whole path segments: `_manager.py`
    must NOT match `.../sync_manager.py` (that's a substring, not a
    segment-boundary suffix)."""
    import cold_read_evidence as cre

    assert cre._suffix_matches(["a/sync_manager.py"], "_manager.py") == []
    assert cre._suffix_matches(["a/sync_manager.py"], "sync_manager.py") == ["a/sync_manager.py"]


def test_prose_line_citation_for_symbol(tmp_path: Path, fake_gh) -> None:
    """afk#1208 shape: a symbol cited with a prose line range, not a
    backticked path:line -- the resolver cannot verify the range actually
    contains the symbol from text alone, so it is a CHECK hint, not a
    resolved PATH_LINE."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "src/scope.py", "def scan_diff_for_scope():\n    pass\n")
    _commit_all(upstream, "add scope.py")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "`scan_diff_for_scope` (lines 316-346) does the check."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_prose.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["class"] == "PROSE_LINE_CITATION")
    assert "scan_diff_for_scope" in row["detail"]


def test_prose_line_citation_for_path_becomes_path_line() -> None:
    body = "See `norms.py` at lines 5-6 for the check."
    tokens = extract_tokens(body)
    assert any(t["cls"] == "PATH_LINE" and t["text"] == "norms.py:5-6" for t in tokens)


def test_origin_branch_ref_resolves(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See `origin/main` for the branch."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_ref.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert not any(r["token"] == "origin/main" for r in report["rows"])
    assert report["counts"].get("REF:REF_RESOLVES", 0) >= 1


def test_unknown_branch_ref_is_check(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See `origin/no-such-branch` for it."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_noref.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "origin/no-such-branch")
    assert row["class"] == "REF"
    assert row["result"] == "REF_UNRESOLVED"


def test_repo_shape_token_resolves_via_gh(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    fake_gh.issues["otherowner/otherrepo"] = {"exists": True}
    body = "See `otherowner/otherrepo` for the sibling project."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_repo.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert not any(r["token"] == "otherowner/otherrepo" for r in report["rows"])
    assert report["counts"].get("REPO:REPO_RESOLVES", 0) >= 1


def test_repo_shape_token_unresolved_via_gh(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See `nosuch/repo123` which doesn't exist."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_norepo.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "nosuch/repo123")
    assert row["class"] == "REPO"
    assert row["result"] == "REPO_UNRESOLVED"


def test_vault_root_that_is_not_a_vault_gives_not_run(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    not_a_vault = tmp_path / "not_a_vault"
    not_a_vault.mkdir()
    body = "See [[Some Note]] please."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_notvault.md", body),
        ref=None, no_fetch=False, vault_root=not_a_vault, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert any(nr["class"] == "wikilink" for nr in report["not_run"])
    assert not any(r.get("result") == "NOTE_UNRESOLVED" for r in report["rows"])


def test_sha_exists_but_unreachable_from_ref_or_remotes_is_check(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    _run(["git", "-C", str(checkout), "checkout", "-q", "-b", "scratch"], tmp_path)
    _write(checkout, "local_only.py", "x = 1\n")
    _run(["git", "-C", str(checkout), "add", "-A"], tmp_path)
    _run(["git", "-C", str(checkout), "commit", "-q", "-m", "local-only, never pushed"], tmp_path)
    sha = _run(["git", "-C", str(checkout), "rev-parse", "HEAD"], tmp_path).stdout.strip()

    body = f"Commit `{sha}` fixed it."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_unreach.md", body),
        ref=None, no_fetch=True, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == sha)
    assert row["result"] == "COMMIT_EXISTS_UNREACHABLE"


def test_path_line_on_a_directory_gives_directory_not_file(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "docs/design/notes.md", "x\n")
    _commit_all(upstream, "add docs/design dir")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "See `docs/design:5` for it."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_dirline.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "docs/design:5")
    assert row["result"] == "DIRECTORY_NOT_FILE"


def test_path_line_start_less_than_one(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "norms.py", "a\nb\nc\n")
    _commit_all(upstream, "add norms")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See `norms.py:0` for it."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_startzero.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "norms.py:0")
    assert row["result"] == "LINE_OUT_OF_RANGE"


def test_path_line_start_greater_than_end(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "norms.py", "a\nb\nc\n")
    _commit_all(upstream, "add norms")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See `norms.py:3-1` for it."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_reversed.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "norms.py:3-1")
    assert row["result"] == "LINE_OUT_OF_RANGE"


def test_sha_not_run_when_check_fails(tmp_path: Path, fake_gh, monkeypatch) -> None:
    import cold_read_evidence as cre

    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    monkeypatch.setattr(cre, "_resolve_sha", lambda *a, **kw: (None, None))

    body = "Commit `0a5a91e2d1` fixed it."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_shanotrun.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert any(nr["class"] == "sha" for nr in report["not_run"])


def test_fetch_failure_gives_input_error_and_incomplete(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    bogus_origin = tmp_path / "does-not-exist-anywhere" / "testowner" / "breakroom"
    _run(["git", "-C", str(checkout), "remote", "set-url", "origin", str(bogus_origin)], tmp_path)

    body = "`x.py` is cited."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_fetchfail.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert report["exit_code"] == 2
    assert any("fetch" in e.lower() for e in report["input_errors"])


# =========================================================================== #
# Round 4 — reviewer survivors (D)
# =========================================================================== #

def test_r9_dotted_symbol_resolves_via_module_path_fallback(tmp_path: Path, fake_gh) -> None:
    """R9: the dotted module-path fallback itself -- a file exists at the
    module path even though the last dotted segment never appears as a
    standalone grepped word anywhere."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "pkg/target.py", "def other_fn():\n    pass\n")
    _commit_all(upstream, "add pkg/target.py, no standalone 'target' word")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "`pkg.target` is the module."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_r9.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert not any(r["token"] == "pkg.target" for r in report["rows"])
    assert report["counts"].get("SYMBOL:FOUND", 0) >= 1


def test_r10_word_boundary_excludes_substring_match(tmp_path: Path, fake_gh) -> None:
    """R10: `-w` word-boundary grep. `foo` must not match `foobar`."""
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _write(upstream, "src/x.py", "def foobar():\n    pass\n")
    _commit_all(upstream, "add foobar only, no standalone foo")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)

    body = "`foo` is cited."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_r10.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    row = next(r for r in report["rows"] if r["token"] == "foo")
    assert row["result"] == "ABSENT"


def test_r12_collect_restores_process_state_after_wikilink_resolution(tmp_path: Path, fake_gh) -> None:
    """R12a/b/c: CLAUDE_PROJECT_DIR and the pinned sys.modules identities
    must be exactly as found once collect() returns, mirroring
    wrap_up_audit's test_collect_restores_process_state_* pattern."""
    prior_env = os.environ.get("CLAUDE_PROJECT_DIR")
    prior_modules = {
        name: sys.modules.get(name)
        for name in ("vault_scope", "vault_scope_resolved", "vault_scope_defaults",
                      "frontmatter_engine", "vault_audit", "graph_cli")
    }

    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    vault_root = tmp_path / "vault"
    _write(vault_root, ".vault/vault.json", "{}")
    _write(vault_root, "work/active/Some Note.md", "---\ndate: 2026-01-01\n---\n\n# Some Note\n\nbody\n")

    body = "See [[Some Note]] for it."
    collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_r12.md", body),
        ref=None, no_fetch=False, vault_root=vault_root, limit=20,
    )

    assert os.environ.get("CLAUDE_PROJECT_DIR") == prior_env
    for name, mod in prior_modules.items():
        assert sys.modules.get(name) is mod


def test_x1_wikilinks_without_vault_root_is_not_run(tmp_path: Path, fake_gh) -> None:
    upstream, checkout, repo = make_repo_pair(tmp_path, "testowner", "breakroom")
    _run(["git", "-C", str(checkout), "fetch", "origin"], tmp_path)
    body = "See [[Some Note]] please."
    report = collect(
        repo=repo, repo_dir=checkout, issue=None,
        body_file=_write(tmp_path, "b_x1.md", body),
        ref=None, no_fetch=False, vault_root=None, limit=20,
    )
    assert report["verdict"] == "INCOMPLETE"
    assert any(nr["class"] == "wikilink" for nr in report["not_run"])
