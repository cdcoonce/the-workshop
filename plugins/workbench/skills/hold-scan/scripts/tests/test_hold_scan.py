"""Tests for hold_scan.py, graded against the criteria of the-workshop#1017."""

from __future__ import annotations

import ast
import re
import json
import shutil
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES, comment, gh, load, scan, write_note

import hold_scan

BR = "cdcoonce/breakroom"
HA = "acme/household-app"
RM = "cdcoonce/ragmark"


def vault_hits(out):
    return [h for h in out["hits"] if h["source"] == "vault"]


def thread_hits(out):
    return [h for h in out["hits"] if h["source"] == "thread"]


# ---- thread -----------------------------------------------------------------


@pytest.mark.parametrize("n,fixture", [(112, "breakroom_112_comments.json"), (142, "breakroom_142_comments.json")])
def test_thread_positive(stub, no_vault, n, fixture):
    comments = load(fixture)
    stub.pr(BR, n)
    stub.thread(BR, n, comments)
    code, out = scan(*gh(BR, n))
    assert code == 1 and out["verdict"] == "HOLD-FOUND"
    (hit,) = thread_hits(out)
    assert "Holding this unmerged" in hit["quote"]
    assert hit["url_or_path"] == comments[1]["html_url"]
    assert hit["timestamp"] == comments[1]["created_at"]


def test_thread_quote_is_the_matching_line(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("intro line\ndo not merge this\ntail")])
    _, out = scan(*gh(BR, 1))
    assert out["hits"][0]["quote"] == "do not merge this"


@pytest.mark.parametrize(
    "body", ["holding this", "Holding it", "DO NOT MERGE", "don't merge", "not merging yet", "left unmerged"]
)
def test_each_pattern_hits(stub, no_vault, body):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment(body)])
    code, out = scan(*gh(BR, 1))
    assert code == 1 and len(thread_hits(out)) == 1


def test_advisory_negatives(stub, no_vault):
    bodies = [c["body"] for c in load("breakroom_112_comments.json")[:1] + load("breakroom_142_comments.json")[:1]]
    bodies.append(
        "### Reviewer advisory (non-blocking)\n\nNo regression. CI was blocked earlier; "
        "the fixture is frozen and the seed held constant."
    )
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment(b) for b in bodies])
    code, out = scan(*gh(BR, 1))
    assert code == 0 and out["verdict"] == "NO-HOLD-FOUND" and out["hits"] == []


def test_reviews_and_inline_are_read(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(
        BR, 1, reviews=[{"body": "do not merge", "submitted_at": "2026-08-01T00:00:00Z", "html_url": "https://x/r"}]
    )
    _, out = scan(*gh(BR, 1))
    assert out["hits"][0]["url_or_path"] == "https://x/r"
    assert out["hits"][0]["timestamp"] == "2026-08-01T00:00:00Z"


@pytest.mark.parametrize("which", ["comments", "reviews", "inline"])
def test_pagination_page_two(stub, no_vault, which):
    stub.pr(BR, 1)
    filler = [comment("fine", url=f"https://x/{i}") for i in range(100)]
    hold = comment("do not merge", url="https://x/hold")
    review_filler = [{"body": "fine", "submitted_at": "2026-08-01T00:00:00Z", "html_url": "https://x"}] * 100
    review_hold = {"body": "do not merge", "submitted_at": "2026-08-01T00:00:00Z", "html_url": "https://x/hold"}
    if which == "comments":
        stub.thread(BR, 1, filler + [hold])
    elif which == "reviews":
        stub.thread(BR, 1, reviews=review_filler + [review_hold])
    else:
        stub.thread(BR, 1, inline=filler + [hold])
    code, out = scan(*gh(BR, 1))
    assert code == 1
    assert out["hits"][0]["url_or_path"] == "https://x/hold"


def test_exactly_100_items_fetches_next_page(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("fine")] * 100)
    scan(*gh(BR, 1))
    paged = [c[2] for c in stub.calls if "issues/1/comments" in c[2]]
    assert any("page=2" in p for p in paged)


# ---- acknowledgement --------------------------------------------------------


def test_acknowledgement_reported_never_a_hit(stub, no_vault):
    hold = comment("do not merge", ts="2026-09-01T10:00:00Z", url="https://x/hold")
    ack = comment(
        "hold-scan: acknowledged owner says merge; the do not merge note was about the old head",
        ts="2026-09-01T10:01:00Z",
        url="https://x/ack",
    )
    stub.pr(BR, 1)
    stub.thread(BR, 1, [hold, ack])
    code, out = scan(*gh(BR, 1))
    assert code == 1 and out["verdict"] == "HOLD-FOUND"
    assert [h["url_or_path"] for h in out["hits"]] == ["https://x/hold"]
    assert out["acknowledgement"] == {"url_or_path": "https://x/ack", "timestamp": "2026-09-01T10:01:00Z"}


def test_newest_acknowledgement_wins_and_none_is_null(stub, no_vault):
    a1 = comment("hold-scan: acknowledged one", ts="2026-09-01T10:00:00Z", url="https://x/a1")
    a2 = comment("hold-scan: acknowledged two", ts="2026-09-02T10:00:00Z", url="https://x/a2")
    stub.pr(BR, 1)
    stub.thread(BR, 1, [a2, a1])
    _, out = scan(*gh(BR, 1))
    assert out["acknowledgement"]["url_or_path"] == "https://x/a2"
    stub.thread(BR, 1, [comment("fine")])
    _, out = scan(*gh(BR, 1))
    assert out["acknowledgement"] is None


def test_acknowledgement_must_start_the_first_line(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("see below\nhold-scan: acknowledged x"), comment("re: hold-scan: acknowledged")])
    _, out = scan(*gh(BR, 1))
    assert out["acknowledgement"] is None


def test_review_cannot_be_an_acknowledgement(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(
        BR, 1, reviews=[{"body": "hold-scan: acknowledged x", "submitted_at": "2026-09-01T00:00:00Z", "html_url": "u"}]
    )
    _, out = scan(*gh(BR, 1))
    assert out["acknowledgement"] is None


# ---- labels -----------------------------------------------------------------


def test_label_afk_hold_is_a_hit(stub, no_vault):
    stub.pr(BR, 5, closing=[7])
    stub.thread(BR, 5)
    stub.issue(BR, 7, labels=["afk:hold"])
    code, out = scan(*gh(BR, 5))
    assert code == 1
    (hit,) = out["hits"]
    assert hit["source"] == "label" and hit["timestamp"] is None
    assert hit["url_or_path"] == f"https://github.com/{BR}/issues/7"
    assert "afk:hold" in hit["quote"]


def test_requires_human_is_not_a_hit(stub, no_vault):
    stub.pr(BR, 5, closing=[7])
    stub.thread(BR, 5)
    stub.issue(BR, 7, labels=["requires:human"])
    code, out = scan(*gh(BR, 5))
    assert code == 0 and out["hits"] == []


@pytest.mark.parametrize(
    "line", ["Depends on #8", "- Depends on #8", "* **Depends on** #8", "**Depends on:** #3, #8", "depends on #8"]
)
def test_depends_on_target_label_is_a_hit(stub, no_vault, line):
    stub.pr(BR, 5, closing=[7])
    stub.thread(BR, 5)
    stub.issue(BR, 7, body=f"text\n{line}\nmore")
    stub.issue(BR, 3)
    stub.issue(BR, 8, labels=["afk:hold"])
    code, out = scan(*gh(BR, 5))
    assert code == 1
    assert out["hits"][0]["url_or_path"].endswith("/issues/8")


def test_depends_on_is_one_level_and_line_start_only(stub, no_vault):
    stub.pr(BR, 5, closing=[7])
    stub.thread(BR, 5)
    stub.issue(BR, 7, body="This work depends on #8 sometimes\nDepends on #9")
    stub.issue(BR, 9, body="Depends on #10")
    stub.issue(BR, 10, labels=["afk:hold"])
    code, _ = scan(*gh(BR, 5))
    assert code == 0
    assert not any("issue" in c and "10" in c[3:4] for c in stub.calls)


def test_closing_issue_comments_are_never_read(stub, no_vault):
    stub.pr(BR, 5, closing=[7])
    stub.thread(BR, 5)
    stub.issue(BR, 7)
    scan(*gh(BR, 5))
    for c in stub.calls:
        assert "issues/7/comments" not in " ".join(c)
        assert "--comments" not in c


# ---- stale ------------------------------------------------------------------


def _scanned_names(out):
    return [e["name"] for e in out["scanned"]]


def test_stale_pr_15_days(stub, no_vault):
    stub.pr(BR, 1, created="2026-10-07T11:00:00Z")
    stub.thread(BR, 1)
    code, out = scan(*gh(BR, 1))
    assert code == 0 and out["verdict"] == "NO-HOLD-FOUND"
    assert "stale-no-thread" in _scanned_names(out)


def test_not_stale_at_13_days_or_with_a_comment_or_closed(stub, no_vault):
    stub.pr(BR, 1, created="2026-10-09T11:00:00Z")
    stub.thread(BR, 1)
    assert "stale-no-thread" not in _scanned_names(scan(*gh(BR, 1))[1])
    stub.pr(BR, 1, created="2026-10-07T11:00:00Z")
    stub.thread(BR, 1, [comment("hi")])
    assert "stale-no-thread" not in _scanned_names(scan(*gh(BR, 1))[1])
    stub.pr(BR, 1, created="2026-10-07T11:00:00Z", state="MERGED")
    stub.thread(BR, 1)
    assert "stale-no-thread" not in _scanned_names(scan(*gh(BR, 1))[1])


# ---- vault ------------------------------------------------------------------


def _vault_pr(stub, repo, n, closing=(), issues=None):
    stub.pr(repo, n, closing=closing)
    stub.thread(repo, n)
    for m in closing:
        body = (issues or {}).get(m, "")
        stub.issue(repo, m, body=body)
        for dep in re.findall(r"#(\d+)", body):
            stub.issue(repo, int(dep))


@pytest.mark.parametrize("n,closing", [(112, [42]), (142, [89])])
def test_vault_positive_breakroom(stub, vault, n, closing):
    _vault_pr(stub, BR, n, closing)
    code, out = scan(*gh(BR, n))
    assert code == 1
    assert vault_hits(out)
    assert all(h["timestamp"] is None for h in vault_hits(out))


def test_vault_positive_household_via_closing_issue(stub, vault):
    _vault_pr(stub, HA, 251, [236], {236: "Depends on #234, #235"})
    code, out = scan(*gh(HA, 251))
    assert code == 1 and vault_hits(out)


def test_vault_quote_is_a_paragraph_cut_to_300(stub, vault, tmp_path):
    long = "x" * 400
    write_note(vault, "personal/projects/household-app.md",
               f'---\nrepo: "https://github.com/{HA}"\n---\n## Current Status\n\n#251 is held {long}\n')
    _vault_pr(stub, HA, 251)
    _, out = scan(*gh(HA, 251))
    hit = [h for h in vault_hits(out) if h["url_or_path"].endswith("household-app.md")][0]
    assert len(hit["quote"]) == 300 and hit["quote"].startswith("#251 is held")


def test_vault_negatives_ragmark(stub, vault):
    _vault_pr(stub, RM, 129, [114, 120, 121, 123])
    _, out = scan(*gh(RM, 129))
    assert vault_hits(out) == []
    _vault_pr(stub, RM, 117)
    code, out = scan(*gh(RM, 117))
    assert code == 0 and out["verdict"] == "NO-HOLD-FOUND"


def test_vault_117_needs_the_hold_word(stub, vault):
    """Positive control: the #117 paragraph turns into a hit once it holds a hold word."""
    _vault_pr(stub, RM, 117)
    note = vault / "personal/projects/vault-local-rag.md"
    note.write_text(note.read_text().replace("not on review", "not on review; we are holding"))
    code, out = scan(*gh(RM, 117))
    assert code == 1 and vault_hits(out)


def test_scope_decoys(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "decoy"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "personal/notes/random.md", "---\ndescription: nothing\n---\n## Current Status\n\n#236 is held\n")
    write_note(root, "personal/projects/household-app.md",
               f'---\nrepo: "https://github.com/{HA}"\n---\n## Current Status\n\nall quiet\n\n## Status / next\n\n#236 is held\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, HA, 251, [236])
    code, out = scan(*gh(HA, 251))
    assert vault_hits(out) == [] and code == 0


def test_boundaries(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "bound"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "personal/projects/household-app.md",
               f'---\nrepo: "https://github.com/{HA}"\n---\n## Current Status\n\nthe household chain #236 is on ice\n\nhcc#42 is frozen\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    for n in (23, 42):
        _vault_pr(stub, HA, n)
        code, out = scan(*gh(HA, n))
        assert vault_hits(out) == [] and code == 0, n


def test_hold_inside_household_is_not_a_hold_word(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "hh"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "personal/projects/household-app.md",
               f'---\nrepo: "https://github.com/{HA}"\n---\n## Current Status\n\nthe household chain #236 is on ice\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, HA, 251, [236])
    code, out = scan(*gh(HA, 251))
    assert vault_hits(out) == [] and code == 0


@pytest.mark.parametrize("text", ["#236 is held", "see foo-#23 held", "see x/#23 held", "mything#23 held"])
def test_number_boundaries_with_a_hold_word(stub, vault, tmp_path, monkeypatch, text):
    """PR #23 must not match #236, nor a dash/slash/foreign-word prefixed #23."""
    root = tmp_path / "nb"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "personal/projects/household-app.md",
               f'---\nrepo: "https://github.com/{HA}"\n---\n## Current Status\n\n{text}\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, HA, 23)
    code, out = scan(*gh(HA, 23))
    assert vault_hits(out) == [] and code == 0


def test_alias(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "alias"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "brain/Holds.md", "# Holds\n\n### 2026-09-05 chain\n\nhapp#236 waits on the exit test\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, HA, 251, [236])
    code, out = scan(*gh(HA, 251))  # `vault` fixture put the alias config in HOME
    assert code == 1 and vault_hits(out)
    (Path(__import__("os").environ["HOME"]) / ".workshop/hold-scan/hold-scan.toml").write_text("[aliases]\n")
    code, out = scan(*gh(HA, 251))
    assert vault_hits(out) == [] and code == 0


def test_dependency_numbers(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "dep"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "personal/projects/household-app.md",
               f'---\nrepo: "https://github.com/{HA}"\n---\n## Current Status\n\n#235 is held\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, HA, 251, [236], {236: "Depends on #234, #235"})
    code, out = scan(*gh(HA, 251))
    assert code == 1 and vault_hits(out)


def test_frontmatter_description_owns_a_note(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "desc"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "a.md", f'---\ndescription: "see {BR} for it"\n---\n## Current Status\n\nPR #9 is frozen\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    code, _ = scan(*gh(BR, 9))
    assert code == 1


def test_a_list_is_one_paragraph(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "list"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "a.md", f'---\nrepo: "https://github.com/{BR}"\n---\n## Current Status\n\n- item #9\n- other is held\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    code, _ = scan(*gh(BR, 9))
    assert code == 1


def test_holds_entry_ends_at_next_heading(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "kd"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "brain/Holds.md",
               "# Holds\n\n### one breakroom\n\nnothing here\n\n### two other\n\n#9 is held\n\n## Later\n\n#9 breakroom\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    code, out = scan(*gh(BR, 9))
    assert code == 0 and vault_hits(out) == []


# ---- brain/Holds.md ---------------------------------------------------------


def _holds_vault(tmp_path, monkeypatch, holds_text=None, kd_text=None):
    root = tmp_path / "hv"
    write_note(root, ".vault/vault.json", "{}")
    if holds_text is not None:
        write_note(root, "brain/Holds.md", holds_text)
    if kd_text is not None:
        write_note(root, "brain/Key Decisions.md", kd_text)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


def test_holds_entry_without_a_hold_word_is_a_hit(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch, "# Holds\n\n### 2026-10-11 breakroom#9 \u2014 waits on review\n\nmerge after the audit lands\n")
    _vault_pr(stub, BR, 9)
    code, out = scan(*gh(BR, 9))
    assert code == 1 and len(vault_hits(out)) == 1
    assert vault_hits(out)[0]["url_or_path"].endswith("brain/Holds.md")


def test_holds_hit_quote_is_the_entry_heading_line(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch, "# Holds\n\n### 2026-10-11 breakroom \u2014 reason\n\nfirst para\n\nPR #9 is the one\n")
    _vault_pr(stub, BR, 9)
    _, out = scan(*gh(BR, 9))
    assert [h["quote"] for h in vault_hits(out)] == ["### 2026-10-11 breakroom \u2014 reason"]


def test_key_decisions_entry_with_hold_word_and_number_is_not_a_hit(stub, vault, tmp_path, monkeypatch):
    """B1 regression guard: Key Decisions is no longer read."""
    _holds_vault(tmp_path, monkeypatch, "# Holds\n\nnone open\n",
                 "# KD\n\n### 2026-09-05 breakroom\n\nbreakroom#9 is frozen and held\n")
    _vault_pr(stub, BR, 9)
    code, out = scan(*gh(BR, 9))
    assert vault_hits(out) == [] and code == 0


def test_key_decisions_alone_is_never_read(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch, None, "# KD\n\n### 2026-09-05 breakroom\n\n#9 is held\n")
    _vault_pr(stub, BR, 9)
    assert vault_hits(scan(*gh(BR, 9))[1]) == []


def test_missing_holds_file_is_skipped_not_silent(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch)
    _vault_pr(stub, BR, 9)
    code, out = scan(*gh(BR, 9))
    assert code == 0
    entry = [e for e in out["scanned"] if e["name"] == "vault:holds"][0]
    assert entry["status"] == "skipped" and "Holds.md" in entry["detail"]
    assert not any("key-decisions" in e["name"] for e in out["scanned"])


def test_holds_preamble_is_never_an_entry(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch,
                 "---\ndate: 2026-10-24\ntags:\n  - holds\n---\n# Holds\n\nOpen holds on breakroom#9 live below.\n\n"
                 "### 2026-10-11 other-repo#3 \u2014 unrelated\n\nnothing\n")
    _vault_pr(stub, BR, 9)
    code, out = scan(*gh(BR, 9))
    assert vault_hits(out) == [] and code == 0


def test_holds_entry_stops_at_a_level_two_heading(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch,
                 "# Holds\n\n### 2026-10-11 breakroom \u2014 reason\n\nnothing\n\n## Notes\n\nbreakroom #9 here\n")
    _vault_pr(stub, BR, 9)
    assert vault_hits(scan(*gh(BR, 9))[1]) == []


def test_holds_entry_naming_the_repo_with_another_number_is_not_a_hit(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch, "# Holds\n\n### 2026-10-11 breakroom#90 \u2014 reason\n\n#90\n")
    _vault_pr(stub, BR, 9)
    assert vault_hits(scan(*gh(BR, 9))[1]) == []


def test_holds_entry_not_naming_the_repo_is_out_of_scope(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch, "# Holds\n\n### 2026-10-11 ragmark \u2014 reason\n\n#9\n")
    _vault_pr(stub, BR, 9)
    assert vault_hits(scan(*gh(BR, 9))[1]) == []


def test_holds_alias_scopes_an_entry(stub, vault, tmp_path, monkeypatch):
    _holds_vault(tmp_path, monkeypatch, "# Holds\n\n### 2026-10-11 happ#236 \u2014 reason\n\nbody\n")
    _vault_pr(stub, HA, 251, [236])
    assert scan(*gh(HA, 251))[0] == 1


# ---- vault resolution -------------------------------------------------------


def test_no_vault_is_skipped(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1)
    code, out = scan(*gh(BR, 1))
    assert code == 0
    entry = [e for e in out["scanned"] if e["name"] == "vault"][0]
    assert entry["status"] == "skipped"


def test_walk_up_from_a_subdirectory(stub, no_vault, tmp_path, monkeypatch):
    root = tmp_path / "v"
    shutil.copytree(FIXTURES / "vault", root)
    (root / "deep/er").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root / "deep/er"))
    _vault_pr(stub, BR, 112, [42])
    code, out = scan(*gh(BR, 112))
    assert code == 1 and vault_hits(out)


def test_walk_up_falls_back_to_pwd(stub, no_vault, tmp_path, monkeypatch):
    root = tmp_path / "v"
    shutil.copytree(FIXTURES / "vault", root)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    monkeypatch.setenv("PWD", str(root))
    _vault_pr(stub, BR, 112, [42])
    assert scan(*gh(BR, 112))[0] == 1


def test_config_vault_root(stub, no_vault, tmp_path):
    root = tmp_path / "v"
    shutil.copytree(FIXTURES / "vault", root)
    cfg = no_vault / ".workshop/hold-scan"
    cfg.mkdir(parents=True)
    (cfg / "hold-scan.toml").write_text(f'vault_root = "{root}"\n')
    _vault_pr(stub, BR, 112, [42])
    code, out = scan(*gh(BR, 112))
    assert code == 1 and vault_hits(out)


def test_config_vault_root_without_marker_is_scan_error(stub, no_vault, tmp_path):
    bad = tmp_path / "notavault"
    bad.mkdir()
    cfg = no_vault / ".workshop/hold-scan"
    cfg.mkdir(parents=True)
    (cfg / "hold-scan.toml").write_text(f'vault_root = "{bad}"\n')
    stub.pr(BR, 1)
    stub.thread(BR, 1)
    code, out = scan(*gh(BR, 1))
    assert code == 2 and out["verdict"] == "SCAN-ERROR"
    assert str(bad) in json.dumps(out["scanned"])


def test_malformed_toml_is_scan_error(stub, no_vault):
    cfg = no_vault / ".workshop/hold-scan"
    cfg.mkdir(parents=True)
    (cfg / "hold-scan.toml").write_text("vault_root = = =\n")
    stub.pr(BR, 1)
    stub.thread(BR, 1)
    code, out = scan(*gh(BR, 1))
    assert code == 2 and out["verdict"] == "SCAN-ERROR"


# ---- failures ---------------------------------------------------------------


def test_failed_call_without_hit_is_scan_error(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1)
    stub.failing = ["pulls/1/reviews"]
    code, out = scan(*gh(BR, 1))
    assert code == 2 and out["verdict"] == "SCAN-ERROR"
    failed = [e for e in out["scanned"] if e["status"] == "failed"]
    assert failed and "pulls/1/reviews" in json.dumps(failed)


def test_failed_call_with_hit_is_hold_found(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("do not merge")])
    stub.failing = ["pulls/1/reviews"]
    code, out = scan(*gh(BR, 1))
    assert code == 1 and out["verdict"] == "HOLD-FOUND"
    assert any(e["status"] == "failed" for e in out["scanned"])


def test_pr_view_failure_is_scan_error(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1)
    stub.failing = ["pr view"]
    assert scan(*gh(BR, 1))[0] == 2


def test_unparseable_json_is_scan_error(stub, no_vault, monkeypatch):
    stub.pr(BR, 1)
    stub.thread(BR, 1)
    real = stub.__call__

    def junk(argv):
        if argv[:2] == ["gh", "api"]:
            return 0, "not json", ""
        return real(argv)

    monkeypatch.setattr(hold_scan, "_run", junk)
    assert scan(*gh(BR, 1))[0] == 2


# ---- gitlab -----------------------------------------------------------------

GL = "group/project"
GLQ = "projects/group%2Fproject"


def gl_stub(stub, notes=(), closes=(), created="2026-10-20T00:00:00Z", state="opened"):
    stub.api[f"{GLQ}/merge_requests/42"] = {"web_url": "https://gitlab.example/group/project/-/merge_requests/42",
                                            "created_at": created, "state": state}
    stub.api[f"{GLQ}/merge_requests/42/notes"] = list(notes)
    stub.api[f"{GLQ}/merge_requests/42/closes_issues"] = list(closes)


def note(body, nid=1, ts="2026-10-21T00:00:00Z", system=False):
    return {"id": nid, "body": body, "created_at": ts, "system": system}


def test_gitlab_note_hit(stub, no_vault):
    gl_stub(stub, notes=[note("do not merge", 9)])
    code, out = scan("--gitlab", GL, "--mr", "42")
    assert code == 1
    (hit,) = out["hits"]
    assert hit["source"] == "thread" and hit["url_or_path"].endswith("#note_9")
    assert hit["timestamp"] == "2026-10-21T00:00:00Z"


def test_gitlab_clean_and_system_notes(stub, no_vault):
    gl_stub(stub, notes=[note("looks good"), note("do not merge", 2, system=True)])
    code, out = scan("--gitlab", GL, "--mr", "42")
    assert code == 0 and out["verdict"] == "NO-HOLD-FOUND"


def test_gitlab_label_hit(stub, no_vault):
    gl_stub(stub, closes=[{"iid": 7, "labels": ["afk:hold"], "description": "", "web_url": "https://gitlab.example/i/7"}])
    code, out = scan("--gitlab", GL, "--mr", "42")
    assert code == 1 and out["hits"][0]["source"] == "label"


def test_gitlab_acknowledgement(stub, no_vault):
    gl_stub(stub, notes=[note("hold-scan: acknowledged ok", 3, "2026-10-21T01:00:00Z")])
    _, out = scan("--gitlab", GL, "--mr", "42")
    assert out["acknowledgement"]["timestamp"] == "2026-10-21T01:00:00Z"


def test_gitlab_keys_match_github(stub, no_vault):
    gl_stub(stub, notes=[note("do not merge", 9)])
    _, g = scan("--gitlab", GL, "--mr", "42")
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("do not merge")])
    _, h = scan(*gh(BR, 1))
    assert set(g) == set(h) and set(g["hits"][0]) == set(h["hits"][0])


def test_gitlab_vault_uses_last_path_segment(stub, vault):
    gl_stub(stub, closes=[])
    stub.api[f"{GLQ}/merge_requests/42/notes"] = []
    write_note(vault, "brain/Holds.md", "### e project\n\n#42 waits\n")
    code, out = scan("--gitlab", GL, "--mr", "42")
    assert code == 1 and vault_hits(out)


# ---- contract ---------------------------------------------------------------


def test_json_contract(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("do not merge")])
    _, out = scan(*gh(BR, 1))
    assert set(out) == {"verdict", "hits", "acknowledgement", "scanned"}
    assert set(out["hits"][0]) == {"source", "url_or_path", "quote", "timestamp"}


def test_human_summary_without_json(stub, no_vault, capsys):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("do not merge")])
    code = hold_scan.main(["--repo", BR, "--pr", "1"])
    text = capsys.readouterr().out
    assert code == 1 and "HOLD-FOUND" in text and "do not merge" in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


def test_imports_only_the_standard_library():
    tree = ast.parse(Path(hold_scan.__file__).read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            mods.add(node.module.split(".")[0])
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)


def test_no_write_calls_are_made(stub, no_vault):
    stub.pr(BR, 1, closing=[7])
    stub.thread(BR, 1)
    stub.issue(BR, 7)
    scan(*gh(BR, 1))
    for c in stub.calls:
        assert "-X" not in c and "--method" not in c and "-f" not in c and "--input" not in c


# ---- review round: fail closed, scope teeth, hold preservation ---------------


def test_real_run_missing_executable_is_scan_error(monkeypatch, no_vault):
    """The real `_run` (no stub): a missing `gh` must read SCAN-ERROR, never NO-HOLD-FOUND."""
    monkeypatch.setenv("PATH", str(no_vault))
    code, out = scan(*gh(BR, 1))
    assert code == 2 and out["verdict"] == "SCAN-ERROR"
    assert any(e["status"] == "failed" for e in out["scanned"])


def test_real_run_timeout_is_scan_error(monkeypatch, no_vault):
    def boom(*a, **k):
        raise hold_scan.subprocess.TimeoutExpired(a[0], 1)

    monkeypatch.setattr(hold_scan.subprocess, "run", boom)
    code, out = scan(*gh(BR, 1))
    assert code == 2 and out["verdict"] == "SCAN-ERROR"


def test_real_run_returns_nonzero_on_failure():
    rc, out, err = hold_scan._run(["/nonexistent/definitely-not-here"])
    assert rc != 0 and out == ""


@pytest.mark.parametrize("payload", [{"a": 1}, "str", None])
def test_non_list_page_payload_is_scan_error(stub, no_vault, payload):
    stub.pr(BR, 1)
    stub.thread(BR, 1)
    stub.api[f"repos/{BR}/pulls/1/reviews"] = payload if payload is not None else {}
    code, out = scan(*gh(BR, 1))
    assert code == 2 and out["verdict"] == "SCAN-ERROR"


def _owned(root, repo, status_text, rel="a.md"):
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, rel, f'---\nrepo: "https://github.com/{repo}"\n---\n## Current Status\n\n{status_text}\n')


def test_walk_up_beats_config_vault_root(stub, no_vault, tmp_path, monkeypatch):
    walked, configured = tmp_path / "walked", tmp_path / "configured"
    _owned(walked, BR, "#9 is frozen")
    _owned(configured, BR, "nothing")
    cfg = no_vault / ".workshop/hold-scan"
    cfg.mkdir(parents=True)
    (cfg / "hold-scan.toml").write_text(f'vault_root = "{configured}"\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(walked))
    _vault_pr(stub, BR, 9)
    code, out = scan(*gh(BR, 9))
    assert code == 1 and str(walked) in vault_hits(out)[0]["url_or_path"]


def test_scope_heading_is_end_anchored(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "anch"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "a.md", f'---\nrepo: "https://github.com/{BR}"\n---\n## Current Status Archive\n\n#9 is frozen\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    assert scan(*gh(BR, 9))[0] == 0


def test_ownership_only_from_frontmatter(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "own"
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "a.md", f'---\ntitle: x\n---\nrepo: "https://github.com/{BR}"\n## Current Status\n\n#9 is frozen\n')
    write_note(root, "b.md", f'intro\nrepo: "https://github.com/{BR}"\n## Current Status\n\n#9 is frozen\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    assert scan(*gh(BR, 9))[0] == 0


@pytest.mark.parametrize("hidden", [".obsidian", ".trash"])
def test_hidden_dirs_not_scanned(stub, vault, tmp_path, monkeypatch, hidden):
    root = tmp_path / "hid"
    write_note(root, ".vault/vault.json", "{}")
    _owned(root, BR, "#9 is frozen", rel=f"{hidden}/a.md")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    assert scan(*gh(BR, 9))[0] == 0


def test_vault_hit_order_is_sorted(stub, vault, tmp_path, monkeypatch):
    root = tmp_path / "ord"
    for rel in ("z.md", "m.md", "a.md"):
        _owned(root, BR, "#9 is frozen", rel=rel)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    paths = [Path(h["url_or_path"]).name for h in vault_hits(scan(*gh(BR, 9))[1])]
    assert paths == ["a.md", "m.md", "z.md"]


def _kd(root, entry):
    write_note(root, ".vault/vault.json", "{}")
    write_note(root, "brain/Holds.md", f"# Holds\n\n### 2026-01-01 {entry}\n\n#9 waits\n")


@pytest.mark.parametrize("entry,expect", [("breakroomer notes", 0), ("my-breakroom-x", 1), ("BREAKROOM notes", 1),
                                          ("Breakroom notes", 1), ("unbreakroom", 0)])
def test_holds_name_is_whole_word_and_case_insensitive(stub, vault, tmp_path, monkeypatch, entry, expect):
    root = tmp_path / "kdw"
    _kd(root, entry)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    _vault_pr(stub, BR, 9)
    assert scan(*gh(BR, 9))[0] == expect


def test_label_match_is_exact_github(stub, no_vault):
    stub.pr(BR, 5, closing=[7])
    stub.thread(BR, 5)
    stub.issue(BR, 7, labels=["afk:hold-released", "xafk:hold", "AFK:HOLD"])
    assert scan(*gh(BR, 5))[0] == 0


def test_label_match_is_exact_gitlab(stub, no_vault):
    gl_stub(stub, closes=[{"iid": 7, "labels": ["afk:hold-released"], "description": "", "web_url": "u"}])
    assert scan("--gitlab", GL, "--mr", "42")[0] == 0


def test_gitlab_depends_on_is_followed(stub, no_vault):
    gl_stub(stub, closes=[{"iid": 7, "labels": [], "description": "Depends on #8", "web_url": "u7"}])
    stub.api[f"{GLQ}/issues/8"] = {"iid": 8, "labels": ["afk:hold"], "web_url": "https://gitlab.example/i/8"}
    code, out = scan("--gitlab", GL, "--mr", "42")
    assert code == 1 and out["hits"][0]["url_or_path"] == "https://gitlab.example/i/8"


def test_ack_matching_is_strict_and_outside_the_contract_otherwise(stub, no_vault):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment("  hold-scan: acknowledged x"), comment("Hold-Scan: Acknowledged x"),
                        comment("- hold-scan: acknowledged x")])
    _, out = scan(*gh(BR, 1))
    assert out["acknowledgement"] is None


def test_edited_comment_stamped_with_the_later_time(stub, no_vault):
    c = comment("do not merge", ts="2026-09-01T09:00:00Z")
    c["updated_at"] = "2026-09-01T11:00:00Z"
    stub.pr(BR, 1)
    stub.thread(BR, 1, [c])
    _, out = scan(*gh(BR, 1))
    assert out["hits"][0]["timestamp"] == "2026-09-01T11:00:00Z"


def test_updated_before_created_does_not_move_the_stamp(stub, no_vault):
    c = comment("do not merge", ts="2026-09-01T09:00:00Z")
    c["updated_at"] = "2026-09-01T08:00:00Z"
    stub.pr(BR, 1)
    stub.thread(BR, 1, [c])
    assert scan(*gh(BR, 1))[1]["hits"][0]["timestamp"] == "2026-09-01T09:00:00Z"


@pytest.mark.parametrize("created, updated, expect", [
    # As strings "." sorts before "Z", so the half-second edit would read as earlier.
    ("2026-10-01T10:00:00Z", "2026-10-01T10:00:00.500Z", "updated"),
    # 05:30-05:00 is 10:30Z, later than 10:00Z, though "05" sorts before "10".
    ("2026-10-01T10:00:00Z", "2026-10-01T05:30:00-05:00", "updated"),
    # The reverse: as strings the update would read as later.
    ("2026-10-01T10:00:00.500Z", "2026-10-01T10:00:00Z", "created"),
])
def test_later_compares_parsed_times_not_strings(stub, no_vault, created, updated, expect):
    c = comment("do not merge", ts=created)
    c["updated_at"] = updated
    stub.pr(BR, 1)
    stub.thread(BR, 1, [c])
    assert scan(*gh(BR, 1))[1]["hits"][0]["timestamp"] == {"created": created, "updated": updated}[expect]


def test_edited_inline_and_gitlab_notes_use_updated_at(stub, no_vault):
    inline = comment("do not merge", ts="2026-09-01T09:00:00Z")
    inline["updated_at"] = "2026-09-02T09:00:00Z"
    stub.pr(BR, 1)
    stub.thread(BR, 1, inline=[inline])
    assert scan(*gh(BR, 1))[1]["hits"][0]["timestamp"] == "2026-09-02T09:00:00Z"
    n = note("do not merge", 9, "2026-09-01T09:00:00Z")
    n["updated_at"] = "2026-09-03T09:00:00Z"
    gl_stub(stub, notes=[n])
    assert scan("--gitlab", GL, "--mr", "42")[1]["hits"][0]["timestamp"] == "2026-09-03T09:00:00Z"


def test_edited_ack_keeps_its_creation_time(stub, no_vault):
    a = comment("hold-scan: acknowledged ok", ts="2026-09-01T10:00:00Z", url="https://x/a")
    a["updated_at"] = "2026-09-09T10:00:00Z"
    stub.pr(BR, 1)
    stub.thread(BR, 1, [a])
    assert scan(*gh(BR, 1))[1]["acknowledgement"]["timestamp"] == "2026-09-01T10:00:00Z"


@pytest.mark.parametrize("body", ["don’t merge", "Don’t merge this"])
def test_curly_apostrophe_dont_merge(stub, no_vault, body):
    stub.pr(BR, 1)
    stub.thread(BR, 1, [comment(body)])
    assert scan(*gh(BR, 1))[0] == 1


def test_gitlab_depends_on_target_label_match_is_exact(stub, no_vault):
    gl_stub(stub, closes=[{"iid": 7, "labels": [], "description": "Depends on #8", "web_url": "u7"}])
    stub.api[f"{GLQ}/issues/8"] = {"iid": 8, "labels": ["afk:hold-released"], "web_url": "https://gitlab.example/i/8"}
    code, out = scan("--gitlab", GL, "--mr", "42")
    assert code == 0 and out["hits"] == []
