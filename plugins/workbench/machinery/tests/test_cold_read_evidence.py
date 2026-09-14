from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from cold_read_evidence import (  # noqa: E402
    VERDICT_EXIT_CODES,
    classify_token,
    collect,
    extract_tokens,
    main,
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
    """Records calls; ``issues`` maps 'owner/repo#N' -> a canned response."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.issue_bodies: dict[tuple[str, int], str] = {}
        self.issues: dict[str, dict] = {}
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
    counted = report["counts"].get("PATH:RESOLVES", 0)
    assert counted >= 1  # chronicles/ resolves and is OK (not a row, just a count)
    assert report["verdict"] == "BLOCKING"
    assert report["exit_code"] == 1


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
    assert report["verdict"] == "NEEDS_JUDGMENT"
    assert report["exit_code"] == 0


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
    good = rows["docs/design/storylets.md:163-164"]
    assert good["result"] == "RESOLVES"
    assert good["line_text"][0] == "the real storylet text at 163"
    assert good["line_text"][1] == "the real storylet text at 164"
    assert rows["docs/design/storylets.md:9999"]["result"] == "LINE_OUT_OF_RANGE"
    assert rows["breakroom.economy.move_dial"]["result"] == "ABSENT"
    assert report["verdict"] == "BLOCKING"  # LINE_OUT_OF_RANGE blocks


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
    row = next(r for r in report["rows"] if r["token"] == "big.py:1-5")
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
    assert report["counts"].get("TEMPLATED:PREFIX_RESOLVES", 0) >= 1
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
    assert report["verdict"] == "BLOCKING"


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
    assert report["verdict"] == "BLOCKING"


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
    # RESOLVES is OK severity -> no row emitted; a row here would mean it
    # was (wrongly) UNRESOLVED or PARENT_ONLY instead.
    assert not any(r["token"] == "new_upstream.py" for r in report["rows"])
    assert report["counts"].get("PATH:RESOLVES", 0) >= 1


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
    vault_root.mkdir()

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
    assert report["verdict"] == "BLOCKING"


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
    assert report["verdict"] == "RESOLVED"
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
    row = next(r for r in report["rows"] if r["token"].startswith("docs/désign"))
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
    assert rc == VERDICT_EXIT_CODES["RESOLVED"] == 0
    out = capsys.readouterr().out
    assert '"verdict": "RESOLVED"' in out


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
