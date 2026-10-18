from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import cold_read_ledger as ledger_mod  # noqa: E402
from cold_read_ledger import main, parse_ledger_lines, summarize  # noqa: E402

BODY = "0123456789ab"


def line(**fields) -> str:
    """Render one ledger comment line from key=value fields, in given order."""
    pairs = " ".join(f"{k}={v}" for k, v in fields.items())
    return f"<!-- cold-read-ledger: {pairs} -->"


def read_line(**over) -> str:
    fields = {"v": 1, "read": 1, "verdict": "REWRITE", "body": BODY, "blocking": 3}
    fields.update(over)
    return line(**{k: v for k, v in fields.items() if v is not None})


def verdict_comment(created: str, verdict: str, ledger: str | None) -> dict:
    body = f"## Cold read — {verdict}\n\nfindings here\n"
    if ledger is not None:
        body += ledger + "\n"
    return {"body": body, "createdAt": created}


# ---- parse_ledger_lines --------------------------------------------------- #

def test_valid_read_line_is_parsed():
    text = "## Cold read — REWRITE\n\n" + read_line(
        advisory=2, rule_born=1, mutants=15, survivors=9, tokens=1234, seconds=56
    )
    (rec,) = parse_ledger_lines(text)
    assert "error" not in rec
    assert rec["v"] == 1
    assert rec["read"] == 1
    assert rec["verdict"] == "REWRITE"
    assert rec["body"] == BODY
    assert rec["blocking"] == 3
    assert rec["advisory"] == 2
    assert rec["rule_born"] == 1
    assert rec["mutants"] == 15
    assert rec["survivors"] == 9
    assert rec["tokens"] == 1234
    assert rec["seconds"] == 56


@pytest.mark.parametrize("missing", ["v", "read", "verdict", "body", "blocking"])
def test_each_required_key_missing_is_an_error_record(missing):
    (rec,) = parse_ledger_lines(read_line(**{missing: None}))
    assert "error" in rec
    assert missing in rec["error"]


def test_non_int_blocking_is_an_error_record():
    (rec,) = parse_ledger_lines(read_line(blocking="three"))
    assert "blocking" in rec["error"]


def test_non_int_read_is_an_error_record():
    (rec,) = parse_ledger_lines(read_line(read="x"))
    assert "read" in rec["error"]


def test_unsupported_version_is_an_error_record():
    (rec,) = parse_ledger_lines(read_line(v=2))
    assert "v" in rec["error"]


def test_bad_verdict_is_an_error_record():
    (rec,) = parse_ledger_lines(read_line(verdict="MAYBE"))
    assert "verdict" in rec["error"]


@pytest.mark.parametrize("verdict", ["BUILD", "REWRITE", "NOT-DISPATCH-READY", "BUILD-exempt"])
def test_every_documented_verdict_is_accepted(verdict):
    (rec,) = parse_ledger_lines(read_line(verdict=verdict))
    assert "error" not in rec


@pytest.mark.parametrize("body", ["0123456789a", "0123456789abc", "0123456789AB", "gggggggggggg"])
def test_bad_body_hash_is_an_error_record(body):
    (rec,) = parse_ledger_lines(read_line(body=body))
    assert "body" in rec["error"]


def test_rule_born_na_is_none():
    (rec,) = parse_ledger_lines(read_line(rule_born="na"))
    assert "error" not in rec
    assert rec["rule_born"] is None


def test_non_int_optional_value_is_an_error_record():
    (rec,) = parse_ledger_lines(read_line(tokens="lots"))
    assert "tokens" in rec["error"]


def test_omitted_optional_keys_read_as_none():
    (rec,) = parse_ledger_lines(read_line())
    assert rec["tokens"] is None
    assert rec["seconds"] is None
    assert rec["mutants"] is None


def test_unknown_extra_key_is_kept():
    (rec,) = parse_ledger_lines(read_line(flavor="spicy"))
    assert "error" not in rec
    assert rec["flavor"] == "spicy"


def test_error_is_a_reserved_key_name():
    (rec,) = parse_ledger_lines(read_line(error=1))
    assert "reserved" in rec["error"]


def test_token_without_equals_is_an_error_record():
    (rec,) = parse_ledger_lines(
        "<!-- cold-read-ledger: v=1 read=1 stray verdict=BUILD body=" + BODY + " blocking=0 -->"
    )
    assert "error" in rec


def test_duplicate_key_is_an_error_record():
    (rec,) = parse_ledger_lines(read_line().replace(" -->", " blocking=9 -->"))
    assert "blocking" in rec["error"]


def test_two_ledger_lines_in_one_comment_are_both_reported():
    text = "head\n" + read_line(read=1) + "\nmiddle\n" + read_line(read=2) + "\n"
    recs = parse_ledger_lines(text)
    assert [r["read"] for r in recs] == [1, 2]


def test_a_malformed_line_does_not_hide_a_valid_one():
    text = read_line(blocking="x") + "\n" + read_line(read=2)
    recs = parse_ledger_lines(text)
    assert "error" in recs[0]
    assert recs[1]["read"] == 2


def test_no_ledger_line_gives_empty_list():
    assert parse_ledger_lines("## Cold read — BUILD\n\njust prose\n") == []


def test_ledger_line_inside_a_code_fence_is_ignored():
    text = "format:\n```\n" + read_line() + "\n```\n"
    assert parse_ledger_lines(text) == []


def test_ledger_text_mid_line_is_not_a_ledger_line():
    assert parse_ledger_lines("see " + read_line()) == []


def test_crlf_line_endings_are_tolerated():
    (rec,) = parse_ledger_lines("title\r\n" + read_line() + "\r\n")
    assert "error" not in rec


def test_landed_record_is_parsed():
    text = line(
        v=1, event="landed", pr=1593, source_lines=40, test_lines=120,
        teeth_gaps=3, teeth_gaps_raised=2,
    )
    (rec,) = parse_ledger_lines(text)
    assert "error" not in rec
    assert rec["event"] == "landed"
    assert (rec["pr"], rec["source_lines"], rec["test_lines"]) == (1593, 40, 120)
    assert (rec["teeth_gaps"], rec["teeth_gaps_raised"]) == (3, 2)


@pytest.mark.parametrize(
    "missing", ["pr", "source_lines", "test_lines", "teeth_gaps", "teeth_gaps_raised"]
)
def test_landed_record_requires_every_field(missing):
    fields = dict(v=1, event="landed", pr=1, source_lines=1, test_lines=1,
                  teeth_gaps=0, teeth_gaps_raised=0)
    del fields[missing]
    (rec,) = parse_ledger_lines(line(**fields))
    assert missing in rec["error"]


def test_unknown_event_is_an_error_record():
    (rec,) = parse_ledger_lines(line(v=1, event="exploded"))
    assert "event" in rec["error"]


# ---- summarize ------------------------------------------------------------ #

def test_non_verdict_comments_are_ignored():
    comments = [
        {"body": "just chatting\n" + read_line(), "createdAt": "2026-10-01T00:00:00Z"},
        {"body": "## Coverage — CLEAN\n" + read_line(), "createdAt": "2026-10-01T01:00:00Z"},
    ]
    s = summarize(comments)
    assert s["reads"] == 0
    assert s["unledgered"] == 0
    assert s["verdicts"] == []


def test_comment_without_a_ledger_line_is_counted_unledgered():
    comments = [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", None),
        verdict_comment("2026-10-01T01:00:00Z", "BUILD", read_line(read=2, verdict="BUILD", blocking=0)),
    ]
    s = summarize(comments)
    assert s["reads"] == 2
    assert s["unledgered"] == 1
    assert s["verdicts"] == [None, "BUILD"]
    assert s["blocking"] == [None, 0]


def test_comment_with_only_a_malformed_line_is_unledgered_and_error_listed():
    comments = [verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(blocking="x"))]
    s = summarize(comments)
    assert s["unledgered"] == 1
    assert len(s["errors"]) == 1
    assert "blocking" in s["errors"][0]["error"]


def test_comment_with_two_valid_lines_uses_the_first_and_is_flagged():
    comments = [
        verdict_comment(
            "2026-10-01T00:00:00Z", "REWRITE",
            read_line(blocking=5) + "\n" + read_line(blocking=7),
        )
    ]
    s = summarize(comments)
    assert s["reads"] == 1
    assert s["unledgered"] == 0
    assert s["blocking"] == [5]
    assert s["multi_ledger"] == 1


def test_reads_are_ordered_by_created_at_not_input_order():
    later = verdict_comment("2026-10-02T00:00:00Z", "BUILD", read_line(read=2, verdict="BUILD", blocking=0))
    earlier = verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(read=1, blocking=4))
    s = summarize([later, earlier])
    assert s["verdicts"] == ["REWRITE", "BUILD"]
    assert s["blocking"] == [4, 0]


def test_tokens_and_seconds_are_summed_with_na_counted():
    comments = [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(read=1, tokens=1000, seconds=60)),
        verdict_comment("2026-10-02T00:00:00Z", "REWRITE", read_line(read=2, tokens="na", seconds=30)),
        verdict_comment("2026-10-03T00:00:00Z", "BUILD", read_line(read=3, verdict="BUILD", tokens=500, seconds="na")),
    ]
    s = summarize(comments)
    assert s["tokens"] == [1000, None, 500]
    assert s["tokens_total"] == 1500
    assert s["tokens_na"] == 1
    assert s["seconds_total"] == 90
    assert s["seconds_na"] == 1


def test_totals_are_none_when_every_value_is_na():
    comments = [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(tokens="na", seconds="na")),
    ]
    s = summarize(comments)
    assert s["tokens_total"] is None
    assert s["tokens_na"] == 1
    assert s["seconds_total"] is None


def test_an_unledgered_read_counts_as_na_for_tokens():
    comments = [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", None),
        verdict_comment("2026-10-02T00:00:00Z", "BUILD", read_line(read=2, verdict="BUILD", tokens=700)),
    ]
    s = summarize(comments)
    assert s["tokens_total"] == 700
    assert s["tokens_na"] == 1


def test_landed_record_is_reported_and_latest_wins():
    first = {
        "body": "merged\n" + line(v=1, event="landed", pr=10, source_lines=1, test_lines=2,
                                  teeth_gaps=0, teeth_gaps_raised=0),
        "createdAt": "2026-10-03T00:00:00Z",
    }
    second = {
        "body": "re-landed\n" + line(v=1, event="landed", pr=11, source_lines=5, test_lines=6,
                                     teeth_gaps=2, teeth_gaps_raised=1),
        "createdAt": "2026-10-04T00:00:00Z",
    }
    s = summarize([second, first])
    assert s["landed"]["pr"] == 11
    assert s["landed"]["teeth_gaps_raised"] == 1
    assert summarize([first])["landed"]["pr"] == 10


def test_landed_is_none_when_absent():
    assert summarize([])["landed"] is None


def test_empty_comment_list_summarizes_to_zero_reads():
    s = summarize([])
    assert s["reads"] == 0
    assert s["tokens_total"] is None
    assert s["tokens_na"] == 0


def test_six_read_issue_regression_fixture():
    """Shaped like the real census row: five REWRITE reads, then BUILD."""
    blocking = [6, 4, 1, 2, 2, 0]
    rule_born = ["na", 1, 0, 1, 0, 0]
    mutants = [15, 19, 23, 23, 28, 28]
    survivors = [9, 4, 1, 2, 2, 5]
    comments = []
    for i in range(6):
        verdict = "BUILD" if i == 5 else "REWRITE"
        comments.append(verdict_comment(
            f"2026-10-0{i + 1}T12:00:00Z", verdict,
            read_line(
                read=i + 1, verdict=verdict, blocking=blocking[i],
                rule_born=rule_born[i], mutants=mutants[i], survivors=survivors[i],
                tokens="na", seconds="na",
            ),
        ))
    comments.reverse()  # input order must not matter
    s = summarize(comments)
    assert s["reads"] == 6
    assert s["unledgered"] == 0
    assert s["verdicts"] == ["REWRITE"] * 5 + ["BUILD"]
    assert s["blocking"] == blocking
    assert s["rule_born"] == [None, 1, 0, 1, 0, 0]
    assert s["mutants"] == mutants
    assert s["survivors"] == survivors
    assert s["tokens_total"] is None
    assert s["tokens_na"] == 6
    assert s["landed"] is None


# ---- CLI ------------------------------------------------------------------ #

def _write_comments(tmp_path: Path, comments: list[dict]) -> Path:
    path = tmp_path / "comments.json"
    path.write_text(json.dumps({"comments": comments}), encoding="utf-8")
    return path


def _two_reads() -> list[dict]:
    return [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(read=1, blocking=3, tokens=1000, seconds=60)),
        verdict_comment("2026-10-02T00:00:00Z", "BUILD", read_line(read=2, verdict="BUILD", blocking=0, tokens="na")),
    ]


def test_cli_human_output_with_comments_json(tmp_path, capsys):
    path = _write_comments(tmp_path, _two_reads())
    rc = main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "#7" in out
    assert "REWRITE>BUILD" in out
    assert "3,0" in out
    assert "issues=1" in out
    assert "reads=2" in out
    assert "unledgered=0" in out
    assert "tokens=1000" in out
    assert "na=1" in out


def test_cli_json_output_is_one_parseable_document(tmp_path, capsys):
    path = _write_comments(tmp_path, _two_reads())
    rc = main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert doc["repo"] == "o/r"
    (issue,) = doc["issues"]
    assert issue["issue"] == 7
    assert issue["verdicts"] == ["REWRITE", "BUILD"]
    assert doc["totals"]["reads"] == 2
    assert doc["totals"]["tokens_total"] == 1000


def test_cli_accepts_a_bare_comment_list(tmp_path, capsys):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(_two_reads()), encoding="utf-8")
    rc = main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["totals"]["reads"] == 2


def test_cli_unreadable_json_exits_2(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    rc = main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)])
    assert rc == 2
    assert "cold_read_ledger" in capsys.readouterr().err


def test_cli_missing_file_exits_2(tmp_path, capsys):
    rc = main(["--repo", "o/r", "--issue", "7", "--comments-json", str(tmp_path / "nope.json")])
    assert rc == 2


def test_cli_wrong_json_shape_exits_2(tmp_path):
    path = tmp_path / "shape.json"
    path.write_text(json.dumps({"comments": "nope"}), encoding="utf-8")
    assert main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)]) == 2


def test_cli_usage_error_exits_2(capsys):
    assert main(["--repo", "o/r"]) == 2  # no --issue


def test_cli_comments_json_with_two_issues_exits_2(tmp_path):
    path = _write_comments(tmp_path, _two_reads())
    rc = main(["--repo", "o/r", "--issue", "1", "--issue", "2", "--comments-json", str(path)])
    assert rc == 2


def test_cli_uses_the_fetch_seam_when_comments_json_is_absent(monkeypatch, capsys):
    calls: list[tuple[str, int]] = []

    def fake_fetch(repo: str, issue: int) -> list[dict]:
        calls.append((repo, issue))
        return _two_reads()

    monkeypatch.setattr(ledger_mod, "_fetch_comments", fake_fetch)
    rc = main(["--repo", "o/r", "--issue", "7", "--issue", "9", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert calls == [("o/r", 7), ("o/r", 9)]
    assert [i["issue"] for i in doc["issues"]] == [7, 9]
    assert doc["totals"]["issues"] == 2
    assert doc["totals"]["reads"] == 4


def test_cli_fetch_failure_exits_2(monkeypatch, capsys):
    def boom(repo: str, issue: int) -> list[dict]:
        raise ledger_mod.FetchError("gh failed")

    monkeypatch.setattr(ledger_mod, "_fetch_comments", boom)
    assert main(["--repo", "o/r", "--issue", "7"]) == 2
    assert "gh failed" in capsys.readouterr().err


# ---- the real fetch seam, with subprocess faked --------------------------- #

def test_fetch_comments_shells_out_to_gh_issue_view(monkeypatch):
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"comments": [{"body": "x", "createdAt": "t"}]}), stderr=""
        )

    monkeypatch.setattr(ledger_mod.subprocess, "run", fake_run)
    got = ledger_mod._fetch_comments("o/r", 7)
    assert got == [{"body": "x", "createdAt": "t"}]
    assert seen["cmd"] == ["gh", "issue", "view", "7", "--repo", "o/r", "--json", "comments"]


def test_fetch_comments_nonzero_exit_raises_fetch_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such issue")

    monkeypatch.setattr(ledger_mod.subprocess, "run", fake_run)
    with pytest.raises(ledger_mod.FetchError, match="no such issue"):
        ledger_mod._fetch_comments("o/r", 7)


def test_fetch_comments_missing_gh_raises_fetch_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(ledger_mod.subprocess, "run", fake_run)
    with pytest.raises(ledger_mod.FetchError):
        ledger_mod._fetch_comments("o/r", 7)


# ---- teeth-pass additions ------------------------------------------------- #

@pytest.mark.parametrize("key", ["read", "blocking", "advisory"])
@pytest.mark.parametrize(
    "bad", ["-1", "", "1.5", "+5", "1_0", "5x", "x5", "١٢", "²", "na"]
)
def test_strict_int_fields_reject_anything_but_ascii_digits_and_na(key, bad):
    (rec,) = parse_ledger_lines(read_line(**{key: bad}))
    assert f"{key} must be an integer" in rec["error"]


@pytest.mark.parametrize("key", ["rule_born", "mutants", "survivors", "tokens", "seconds"])
def test_na_or_int_fields_accept_na_and_reject_other_non_digits(key):
    (ok,) = parse_ledger_lines(read_line(**{key: "na"}))
    assert "error" not in ok
    assert ok[key] is None
    (zero,) = parse_ledger_lines(read_line(**{key: 0}))
    assert zero[key] == 0
    for bad in ["-1", "", "1.5", "+5", "1_0", "5x", "NA", "١٢"]:
        (rec,) = parse_ledger_lines(read_line(**{key: bad}))
        assert f"{key} must be an integer or na" in rec["error"], bad


@pytest.mark.parametrize(
    "verdict", ["build", "Build", "BUILD-EXEMPT", "build-exempt", "SKIP", "", "BUILD,REWRITE"]
)
def test_verdict_is_a_case_sensitive_closed_set(verdict):
    (rec,) = parse_ledger_lines(read_line(verdict=verdict))
    assert "verdict" in rec["error"]


def test_the_verdict_allow_list_is_exactly_the_documented_four():
    # The four verdicts of a read, plus VOID (the-workshop#1180): a read that
    # did not happen as the gate defines it.
    assert ledger_mod.VERDICTS == frozenset(
        {"BUILD", "REWRITE", "NOT-DISPATCH-READY", "BUILD-exempt", "VOID"}
    )


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
def test_ledger_after_a_closed_fence_is_parsed_and_the_quoted_one_is_not(fence):
    text = (
        f"format:\n{fence}\n" + read_line(read=9) + f"\n{fence}\n\n"
        + read_line(read=2) + "\n"
    )
    recs = parse_ledger_lines(text)
    assert [r["read"] for r in recs] == [2]


def test_a_tilde_fenced_ledger_line_is_ignored():
    assert parse_ledger_lines("~~~\n" + read_line() + "\n~~~\n") == []


def test_text_after_the_closing_marker_is_not_a_ledger_line():
    assert parse_ledger_lines(read_line() + " trailing words") == []


def test_a_token_with_an_empty_key_is_an_error_record():
    (rec,) = parse_ledger_lines(read_line().replace(" -->", " =5 -->"))
    assert "error" in rec
    assert "key=value" in rec["error"]


@pytest.mark.parametrize(
    "field", ["pr", "source_lines", "test_lines", "teeth_gaps", "teeth_gaps_raised"]
)
@pytest.mark.parametrize("bad", ["x", "", "-1", "1.5", "na"])
def test_landed_record_integers_are_validated(field, bad):
    fields = dict(v=1, event="landed", pr=1, source_lines=1, test_lines=1,
                  teeth_gaps=0, teeth_gaps_raised=0)
    fields[field] = bad
    (rec,) = parse_ledger_lines(line(**fields))
    assert f"{field} must be an integer" in rec["error"]


def test_unknown_event_with_every_landed_field_is_still_an_error_record():
    (rec,) = parse_ledger_lines(line(
        v=1, event="exploded", pr=1, source_lines=1, test_lines=1,
        teeth_gaps=0, teeth_gaps_raised=0,
    ))
    assert "event" in rec["error"]


def test_a_verdict_title_quoted_later_in_a_comment_is_not_a_verdict_comment():
    comments = [
        {"body": "as in my earlier ## Cold read — BUILD comment\n" + read_line(),
         "createdAt": "2026-10-01T00:00:00Z"},
        {"body": "intro line\n## Cold read — BUILD\n" + read_line(),
         "createdAt": "2026-10-02T00:00:00Z"},
    ]
    s = summarize(comments)
    assert s["reads"] == 0
    assert s["verdicts"] == []


def test_a_malformed_plus_a_valid_line_is_not_multi_ledger():
    comments = [verdict_comment(
        "2026-10-01T00:00:00Z", "REWRITE", read_line(blocking="x") + "\n" + read_line(blocking=4)
    )]
    s = summarize(comments)
    assert s["multi_ledger"] == 0
    assert s["unledgered"] == 0
    assert s["blocking"] == [4]
    assert len(s["errors"]) == 1


def test_errors_come_only_from_verdict_comments_and_carry_the_one_based_read_index():
    comments = [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(blocking=3)),
        {"body": "chat\n" + read_line(blocking="x"), "createdAt": "2026-10-01T12:00:00Z"},
        verdict_comment("2026-10-02T00:00:00Z", "BUILD", read_line(read=2, blocking="y")),
    ]
    s = summarize(comments)
    assert [e["read_index"] for e in s["errors"]] == [2]
    assert "blocking" in s["errors"][0]["error"]
    assert s["unledgered"] == 1


def test_a_landed_line_in_a_verdict_comment_is_not_a_read_ledger():
    landed = line(v=1, event="landed", pr=5, source_lines=1, test_lines=2,
                  teeth_gaps=0, teeth_gaps_raised=0)
    s = summarize([verdict_comment("2026-10-01T00:00:00Z", "BUILD", landed)])
    assert s["reads"] == 1
    assert s["unledgered"] == 1
    assert s["verdicts"] == [None]
    assert s["blocking"] == [None]
    assert s["landed"]["pr"] == 5


def test_every_per_read_list_is_parallel_and_carries_its_own_field():
    comments = [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(
            read=1, body="aaaaaaaaaaaa", blocking=3, advisory=2, rule_born=1,
            mutants=10, survivors=4, tokens=100, seconds=7)),
        verdict_comment("2026-10-02T00:00:00Z", "BUILD", None),
        verdict_comment("2026-10-03T00:00:00Z", "BUILD", read_line(
            read=3, verdict="BUILD", body="bbbbbbbbbbbb", blocking=0, advisory=5,
            rule_born="na", mutants="na", survivors="na", tokens="na", seconds=9)),
    ]
    s = summarize(comments)
    assert s["verdicts"] == ["REWRITE", None, "BUILD"]
    assert s["bodies"] == ["aaaaaaaaaaaa", None, "bbbbbbbbbbbb"]
    assert s["blocking"] == [3, None, 0]
    assert s["advisory"] == [2, None, 5]
    assert s["rule_born"] == [1, None, None]
    assert s["mutants"] == [10, None, None]
    assert s["survivors"] == [4, None, None]
    assert s["tokens"] == [100, None, None]
    assert s["seconds"] == [7, None, 9]
    assert (s["seconds_total"], s["seconds_na"]) == (16, 1)


def test_cli_rejects_non_object_comment_elements_with_exit_2(tmp_path, capsys):
    for payload in ([1, 2], {"comments": ["x"]}, {"comments": [{"body": 5}]}):
        path = tmp_path / "shape.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        rc = main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)])
        assert rc == 2
        assert "every comment must be an object" in capsys.readouterr().err


def test_fetch_comments_unreadable_or_misshapen_gh_output_raises_fetch_error(monkeypatch):
    for stdout in ("not json", json.dumps({"comments": "x"})):
        monkeypatch.setattr(
            ledger_mod.subprocess, "run",
            lambda cmd, _out=stdout, **kw: subprocess.CompletedProcess(cmd, 0, stdout=_out, stderr=""),
        )
        with pytest.raises(ledger_mod.FetchError, match="unreadable output"):
            ledger_mod._fetch_comments("o/r", 7)


def _table_rows(capsys) -> list[list[str]]:
    lines = capsys.readouterr().out.splitlines()
    return [ln.split() for ln in lines[1:-1]]  # drop header and footer


def test_cli_table_row_marks_unledgered_cells_and_shows_landed_pr(tmp_path, capsys):
    comments = [
        verdict_comment("2026-10-01T00:00:00Z", "REWRITE", None),
        verdict_comment("2026-10-02T00:00:00Z", "BUILD", read_line(read=2, verdict="BUILD", blocking=0)),
        {"body": "merged\n" + line(v=1, event="landed", pr=10, source_lines=1, test_lines=2,
                                    teeth_gaps=0, teeth_gaps_raised=0),
         "createdAt": "2026-10-03T00:00:00Z"},
    ]
    path = _write_comments(tmp_path, comments)
    assert main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)]) == 0
    assert _table_rows(capsys) == [["#7", "2", "1", "->BUILD", "-,0", "-", "PR#10"]]


def test_cli_table_row_shows_the_token_total_and_an_empty_issue_as_dashes(tmp_path, capsys):
    path = _write_comments(tmp_path, _two_reads())
    assert main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)]) == 0
    assert _table_rows(capsys) == [["#7", "2", "0", "REWRITE>BUILD", "3,0", "1000", "-"]]
    path = _write_comments(tmp_path, [])
    assert main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)]) == 0
    assert _table_rows(capsys) == [["#7", "0", "0", "-", "-", "-", "-"]]


def test_cli_footer_says_none_when_no_token_count_is_known(tmp_path, capsys):
    comments = [verdict_comment("2026-10-01T00:00:00Z", "REWRITE", read_line(tokens="na"))]
    path = _write_comments(tmp_path, comments)
    assert main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)]) == 0
    footer = capsys.readouterr().out.splitlines()[-1]
    assert footer == "Totals: issues=1 reads=1 unledgered=0 tokens=none (na=1)"


def test_cli_totals_sum_across_issues(monkeypatch, capsys):
    per_issue = {
        7: [verdict_comment("2026-10-01T00:00:00Z", "REWRITE", None),
            verdict_comment("2026-10-02T00:00:00Z", "BUILD",
                            read_line(read=2, verdict="BUILD", tokens=1000))],
        9: [verdict_comment("2026-10-01T00:00:00Z", "REWRITE", None),
            verdict_comment("2026-10-02T00:00:00Z", "BUILD",
                            read_line(read=2, verdict="BUILD", tokens=500)),
            verdict_comment("2026-10-03T00:00:00Z", "BUILD",
                            read_line(read=3, verdict="BUILD", tokens="na"))],
    }
    monkeypatch.setattr(ledger_mod, "_fetch_comments", lambda repo, issue: per_issue[issue])
    assert main(["--repo", "o/r", "--issue", "7", "--issue", "9"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "Totals: issues=2 reads=5 unledgered=2 tokens=1500 (na=3)"
    assert main(["--repo", "o/r", "--issue", "7", "--issue", "9", "--json"]) == 0
    totals = json.loads(capsys.readouterr().out)["totals"]
    assert totals == {"issues": 2, "reads": 5, "unledgered": 2, "tokens_total": 1500, "tokens_na": 3}


# ---- fence tracking: marker character, length and info string -------------- #

@pytest.mark.parametrize("outer, inner, info", [
    ("````", "```", "md"),
    ("```", "~~~", ""),
    ("~~~~", "~~~", ""),
    ("```", "```python", ""),
])
def test_a_quoted_ledger_inside_a_nested_fence_does_not_leak(outer, inner, info):
    # The inner marker is shorter, a different character, or carries an info
    # string, so it does not close the outer fence (CommonMark).
    quoted = read_line(read=0, verdict="BUILD", blocking=0)
    text = (f"{outer}{info}\n{inner}\n{quoted}\n{inner}\n{outer}\n\n"
            + read_line(read=4, verdict="REWRITE", blocking=3) + "\n")
    recs = parse_ledger_lines(text)
    assert [(r["read"], r["verdict"]) for r in recs] == [(4, "REWRITE")]


def test_a_longer_closing_marker_still_closes_the_fence():
    text = "```\n" + read_line(read=9) + "\n`````\n" + read_line(read=2) + "\n"
    assert [r["read"] for r in parse_ledger_lines(text)] == [2]


# ---- verdict=VOID and the degraded key (the-workshop#1180) ----------------- #
# Precedent: on 2026-10-10 this script reported reads=3 unledgered=0 for both
# cold-read issues and summed 389,948 tokens of reads that could not count
# toward auto-promote, because every comment titled `## Cold read` was a read
# and nothing recorded that a read had not happened as the gate defines it.
# Each test below names the defect it guards.

T1, T2, T3, T4 = (f"2026-10-0{n}T00:00:00Z" for n in (1, 2, 3, 4))

# `issue` plus the 18 keys summarize returned before the change.
OLD_ISSUE_KEYS = frozenset({
    "issue", "reads", "unledgered", "verdicts", "bodies", "blocking", "rule_born",
    "advisory", "mutants", "survivors", "tokens", "seconds", "tokens_total",
    "tokens_na", "seconds_total", "seconds_na", "multi_ledger", "errors", "landed",
})
NEW_ISSUE_KEYS = frozenset({
    "voided", "void_causes", "tokens_void", "degraded", "clean", "tokens_clean",
    "tokens_degraded",
})
PER_READ_LISTS = (
    "verdicts", "bodies", "blocking", "rule_born", "advisory", "mutants",
    "survivors", "tokens", "seconds", "degraded",
)
TOTALS_KEYS = {"issues", "reads", "unledgered", "tokens_total", "tokens_na"}


def void_line(**over) -> str:
    """A valid VOID ledger line unless a field is overridden (None drops a key)."""
    fields = {"verdict": "VOID", "blocking": 0, "void_cause": "no-probe-build"}
    fields.update(over)
    return read_line(**fields)


def _run_json(tmp_path: Path, capsys, comments: list[dict]) -> dict:
    path = _write_comments(tmp_path, comments)
    rc = main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path), "--json"])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def _run_text(tmp_path: Path, capsys, comments: list[dict]) -> list[str]:
    path = _write_comments(tmp_path, comments)
    assert main(["--repo", "o/r", "--issue", "7", "--comments-json", str(path)]) == 0
    return capsys.readouterr().out.splitlines()


def _void_mixed_fixture() -> list[dict]:
    """A REWRITE read, a VOID read and the BUILD that replaces it, every field
    different so a VOID value leaking into a list or a sum cannot hide."""
    return [
        verdict_comment(T1, "REWRITE", read_line(
            read=1, body="aaaaaaaaaaaa", blocking=3, advisory=2, rule_born=1,
            mutants=10, survivors=4, tokens=1000, seconds=60)),
        verdict_comment(T2, "VOID", void_line(
            read=2, body="bbbbbbbbbbbb", advisory=5, rule_born=3, mutants=7,
            survivors=6, tokens=700, seconds=40)),
        verdict_comment(T3, "BUILD", read_line(
            read=2, verdict="BUILD", body="cccccccccccc", blocking=0, advisory=1,
            rule_born="na", mutants="na", survivors="na", tokens=500, seconds=30)),
    ]


def _four_read_fixture() -> list[dict]:
    """One clean read, one denied read, one unaudited read and one VOID read;
    the tokens are powers of two so no sum can be mistaken for another."""
    return [
        verdict_comment(T1, "REWRITE", read_line(
            read=1, blocking=2, degraded="none", tokens=1000, seconds=60)),
        verdict_comment(T2, "REWRITE", read_line(
            read=2, blocking=1, degraded="denied", tokens=2000, seconds=70)),
        verdict_comment(T3, "REWRITE", read_line(
            read=3, blocking=1, tokens=4000, seconds=80)),
        verdict_comment(T4, "VOID", void_line(read=4, tokens=8000, seconds=90)),
    ]


# -- the grammar ------------------------------------------------------------ #

@pytest.mark.parametrize("cause", ["no-probe-build", "comments-read"])
def test_a_void_line_with_a_known_cause_and_blocking_zero_is_a_valid_record(cause):
    """Guards a VOID line being refused: a void read would then count as a read
    and show as unledgered, the defect this slice removes."""
    (rec,) = parse_ledger_lines(void_line(void_cause=cause))
    assert "error" not in rec
    assert rec["verdict"] == "VOID"
    assert rec["void_cause"] == cause
    assert rec["blocking"] == 0


@pytest.mark.parametrize(
    "over, word",
    [
        ({"void_cause": None}, "void_cause"),
        ({"void_cause": "other"}, "void_cause"),
        ({"void_cause": "NO-PROBE-BUILD"}, "void_cause"),
        ({"blocking": 3}, "blocking"),
        ({"blocking": 1}, "blocking"),
    ],
    ids=["no-cause", "unknown-cause", "cause-case", "blocking-3", "blocking-1"],
)
def test_a_void_line_needs_a_known_cause_and_blocking_zero(over, word):
    """Guards a VOID line accepted without a cause, with a cause outside its
    set, or with blocking findings: such a line is an error record, so the
    comment still counts as a read and shows as unledgered."""
    (rec,) = parse_ledger_lines(void_line(**over))
    assert word in rec["error"]
    s = summarize([verdict_comment(T1, "VOID", void_line(**over))])
    assert (s["reads"], s["unledgered"], s["voided"]) == (1, 1, 0)
    assert s["verdicts"] == [None]
    assert s["void_causes"] == []


def test_a_lowercase_void_verdict_is_an_error_record():
    """Guards the verdict set losing its case sensitivity for the new member."""
    (rec,) = parse_ledger_lines(read_line(verdict="void", void_cause="no-probe-build", blocking=0))
    assert "verdict" in rec["error"]


@pytest.mark.parametrize(
    "verdict", ["BUILD", "REWRITE", "NOT-DISPATCH-READY", "BUILD-exempt"]
)
@pytest.mark.parametrize("cause", ["no-probe-build", "comments-read", "other", "NO-PROBE-BUILD"])
def test_a_void_cause_on_a_non_void_line_is_accepted_and_kept_as_written(verdict, cause):
    """Guards the cause check leaking past a VOID line: only a VOID line has a
    closed set of causes, any other verdict keeps the value as written."""
    (rec,) = parse_ledger_lines(read_line(verdict=verdict, void_cause=cause))
    assert "error" not in rec
    assert rec["void_cause"] == cause
    s = summarize([verdict_comment(T1, verdict, read_line(verdict=verdict, void_cause=cause))])
    assert (s["reads"], s["unledgered"], s["voided"]) == (1, 0, 0)


@pytest.mark.parametrize(
    "value",
    [
        "denied", "gh-used", "agent-type", "preflight-none", "preflight-failed",
        "denied,gh-used", "none",
        "denied,gh-used,agent-type,preflight-none,preflight-failed",
    ],
)
def test_degraded_in_its_vocabulary_is_kept_verbatim(value):
    """Guards the value being normalised, reordered or dropped: the digest and
    the extra lines print it exactly as the writer wrote it."""
    (rec,) = parse_ledger_lines(read_line(degraded=value))
    assert "error" not in rec
    assert rec["degraded"] == value


@pytest.mark.parametrize(
    "value",
    ["bogus", "denied,", ",denied", "none,denied", "denied,none", "DENIED", "gh_used",
     "denied,bogus"],
)
def test_degraded_outside_its_vocabulary_is_an_error_record(value):
    """Guards an unknown token, a stray comma or `none` combined with another
    token being accepted: the comment must count as a read and show as
    unledgered, never as an audited read."""
    (rec,) = parse_ledger_lines(read_line(degraded=value))
    assert "degraded" in rec["error"]
    s = summarize([verdict_comment(T1, "REWRITE", read_line(degraded=value))])
    assert (s["reads"], s["unledgered"], s["clean"]) == (1, 1, 0)
    assert s["degraded"] == [None]
    assert s["tokens_clean"] is None and s["tokens_degraded"] is None


@pytest.mark.parametrize("value", ["denied", "none", "bogus", "none,denied", "denied,", ""])
def test_degraded_on_a_void_line_is_kept_and_ignored_whatever_its_value(value):
    """Guards the degraded check running on a VOID line (a void read with a
    mangled degraded value would become a counted, unledgered read) and the
    parser dropping the key from the VOID record it returns."""
    (rec,) = parse_ledger_lines(void_line(degraded=value))
    assert "error" not in rec
    assert rec["degraded"] == value
    s = summarize([verdict_comment(T1, "VOID", void_line(degraded=value))])
    assert (s["reads"], s["unledgered"], s["voided"]) == (0, 0, 1)
    assert s["degraded"] == []


# -- summarize: what a VOID read is and is not ------------------------------ #

def test_a_void_read_is_excluded_from_reads_and_from_every_per_read_list():
    """Guards a VOID read counting as a read, which feeds the cap count and
    lets an unaudited read stand in for a clean one."""
    s = summarize(_void_mixed_fixture())
    assert s["reads"] == 2
    assert s["unledgered"] == 0
    assert s["verdicts"] == ["REWRITE", "BUILD"]
    assert s["bodies"] == ["aaaaaaaaaaaa", "cccccccccccc"]
    assert s["blocking"] == [3, 0]
    assert s["rule_born"] == [1, None]
    assert s["advisory"] == [2, 1]
    assert s["mutants"] == [10, None]
    assert s["survivors"] == [4, None]
    assert s["tokens"] == [1000, 500]
    assert s["seconds"] == [60, 30]
    assert s["voided"] == 1
    assert s["void_causes"] == ["no-probe-build"]


@pytest.mark.parametrize("key", PER_READ_LISTS)
def test_every_per_read_list_keeps_length_reads_when_a_void_read_is_present(key):
    """Guards a VOID read left in the parallel lists: every list is indexed by
    read, so one extra entry shifts each later read against its neighbours."""
    comments = [
        *_void_mixed_fixture(),
        verdict_comment(T4, "REWRITE", None),
    ]
    s = summarize(comments)
    assert s["reads"] == 3
    assert len(s[key]) == s["reads"]
    s_only_void = summarize([verdict_comment(T1, "VOID", void_line())])
    assert s_only_void["reads"] == 0
    assert s_only_void[key] == []


def test_a_void_reads_tokens_and_seconds_stay_in_tokens_total_and_seconds_total():
    """Guards the cost of a void read vanishing from tokens_total and
    seconds_total: the cost was real, and the footer must agree with the
    table, so the footer sums the issues' tokens_total, void tokens included."""
    s = summarize(_void_mixed_fixture())
    assert s["tokens_total"] == 1000 + 700 + 500
    assert s["tokens_void"] == 700
    assert s["seconds_total"] == 60 + 40 + 30
    assert s["tokens_na"] == 0 and s["seconds_na"] == 0


def test_the_four_read_fixture_separates_clean_degraded_unaudited_and_void(tmp_path, capsys):
    """Guards `clean`, `tokens_clean` and `tokens_degraded` counting a read
    with no `degraded` key (unaudited) as clean, or counting every non-void
    read as clean."""
    s = summarize(_four_read_fixture())
    assert s["reads"] == 3
    assert s["degraded"] == ["none", "denied", None]
    assert s["clean"] == 1
    assert s["tokens_clean"] == 1000
    assert s["tokens_degraded"] == 2000
    assert s["tokens"] == [1000, 2000, 4000]
    assert s["tokens_total"] == 1000 + 2000 + 4000 + 8000
    assert s["seconds_total"] == 60 + 70 + 80 + 90
    assert (s["voided"], s["tokens_void"]) == (1, 8000)
    doc = _run_json(tmp_path, capsys, _four_read_fixture())
    (issue,) = doc["issues"]
    for key in ("clean", "tokens_clean", "tokens_degraded", "tokens_total", "seconds_total"):
        assert issue[key] == s[key], key


def test_each_sum_is_null_when_no_read_of_its_kind_has_a_known_token_count():
    """Guards `tokens_void`, `tokens_clean` and `tokens_degraded` reporting 0
    for 'none is known': 0 reads as a measured cost of nothing."""
    def one(comment_verdict, line_text):
        return summarize([verdict_comment(T1, comment_verdict, line_text)])

    denied = one("REWRITE", read_line(tokens=300, degraded="denied"))
    assert (denied["clean"], denied["tokens_clean"], denied["tokens_degraded"]) == (0, None, 300)
    unaudited = one("REWRITE", read_line(tokens=300))
    assert (unaudited["clean"], unaudited["tokens_clean"], unaudited["tokens_degraded"]) == (0, None, None)
    clean = one("REWRITE", read_line(tokens=300, degraded="none"))
    assert (clean["clean"], clean["tokens_clean"], clean["tokens_degraded"]) == (1, 300, None)
    unknown_clean = one("REWRITE", read_line(tokens="na", degraded="none"))
    assert (unknown_clean["clean"], unknown_clean["tokens_clean"]) == (1, None)
    unknown_denied = one("REWRITE", read_line(tokens="na", degraded="denied"))
    assert unknown_denied["tokens_degraded"] is None
    empty = summarize([])
    assert (empty["voided"], empty["void_causes"], empty["tokens_void"]) == (0, [], None)
    assert (empty["degraded"], empty["clean"]) == ([], 0)
    assert (empty["tokens_clean"], empty["tokens_degraded"]) == (None, None)


def test_tokens_void_is_null_without_a_void_read_or_a_known_void_count():
    """Guards `tokens_void` reporting 0 for an issue with no void read, or
    with void reads whose token counts are all unknown."""
    assert summarize([verdict_comment(T1, "REWRITE", read_line(tokens=5))])["tokens_void"] is None
    na_void = summarize([verdict_comment(T1, "VOID", void_line(tokens="na"))])
    assert (na_void["voided"], na_void["tokens_void"]) == (1, None)
    two = summarize([
        verdict_comment(T1, "VOID", void_line(tokens=30)),
        verdict_comment(T2, "VOID", void_line(tokens="na", void_cause="comments-read")),
    ])
    assert (two["voided"], two["tokens_void"]) == (2, 30)
    assert two["void_causes"] == ["no-probe-build", "comments-read"]


def test_an_absent_degraded_key_is_null_and_a_present_one_is_listed_at_its_index():
    """Guards the degraded list drifting from the reads: absent is null, the
    value is the string as written, and a void read (in the middle) is not
    listed at all."""
    s = summarize([
        verdict_comment(T1, "REWRITE", read_line(read=1)),
        verdict_comment(T2, "VOID", void_line(read=2, degraded="denied")),
        verdict_comment(T3, "REWRITE", read_line(read=2, degraded="denied,gh-used")),
        verdict_comment(T4, "BUILD", read_line(read=3, verdict="BUILD", degraded="none")),
    ])
    assert s["degraded"] == [None, "denied,gh-used", "none"]
    assert s["reads"] == 3


# -- the --json document ---------------------------------------------------- #

def test_the_per_issue_json_object_gains_exactly_the_seven_keys(tmp_path, capsys):
    """Guards an eighth key (or a missing one) in the per-issue object: the
    contract names exactly voided, void_causes, tokens_void, degraded, clean,
    tokens_clean and tokens_degraded."""
    doc = _run_json(tmp_path, capsys, _void_mixed_fixture())
    (issue,) = doc["issues"]
    assert set(issue) == OLD_ISSUE_KEYS | NEW_ISSUE_KEYS
    assert len(issue) == 19 + 7
    assert set(summarize([])) == (OLD_ISSUE_KEYS - {"issue"}) | NEW_ISSUE_KEYS
    assert (issue["voided"], issue["void_causes"], issue["tokens_void"]) == (1, ["no-probe-build"], 700)
    assert isinstance(issue["voided"], int) and isinstance(issue["clean"], int)
    assert isinstance(issue["void_causes"], list) and isinstance(issue["degraded"], list)


def test_json_with_no_void_and_no_degraded_read_differs_only_by_the_added_keys(tmp_path, capsys):
    """Guards the old per-issue values and the totals object changing when no
    read is void or degraded: the existing fields keep their values."""
    comments = [*_two_reads(), verdict_comment(T3, "REWRITE", None)]
    doc = _run_json(tmp_path, capsys, comments)
    (issue,) = doc["issues"]
    added = {k: issue.pop(k) for k in NEW_ISSUE_KEYS}
    assert issue == {
        "issue": 7, "reads": 3, "unledgered": 1,
        "verdicts": ["REWRITE", "BUILD", None], "bodies": [BODY, BODY, None],
        "blocking": [3, 0, None], "rule_born": [None, None, None],
        "advisory": [None, None, None], "mutants": [None, None, None],
        "survivors": [None, None, None], "tokens": [1000, None, None],
        "seconds": [60, None, None], "tokens_total": 1000, "tokens_na": 2,
        "seconds_total": 60, "seconds_na": 2, "multi_ledger": 0, "errors": [],
        "landed": None,
    }
    assert added == {
        "voided": 0, "void_causes": [], "tokens_void": None,
        "degraded": [None, None, None], "clean": 0, "tokens_clean": None,
        "tokens_degraded": None,
    }
    assert doc["totals"] == {
        "issues": 1, "reads": 3, "unledgered": 1, "tokens_total": 1000, "tokens_na": 2,
    }


# -- the text output -------------------------------------------------------- #

def _legacy_issues() -> dict[int, list[dict]]:
    landed = {
        "body": "merged\n" + line(v=1, event="landed", pr=10, source_lines=1, test_lines=2,
                                  teeth_gaps=0, teeth_gaps_raised=0),
        "createdAt": T4,
    }
    return {
        7: [*_two_reads(), landed],
        9: [
            verdict_comment(T1, "REWRITE", None),
            verdict_comment(T2, "BUILD", read_line(read=2, verdict="BUILD", tokens=1000, flavor="spicy")),
            verdict_comment(T3, "BUILD", read_line(read=3, verdict="BUILD", tokens="na")),
            verdict_comment(T4, "REWRITE", read_line(blocking="x")),
        ],
        11: [],
    }


# Recorded from the script as it stood before #1180, on the fixture above.
LEGACY_TEXT = [
    "issue  reads  unledgered  verdicts         blocking  tokens  landed",
    "#7     2      0           REWRITE>BUILD    3,0       1000    PR#10",
    "#9     4      2           ->BUILD>BUILD>-  -,3,3,-   1000    -",
    "#11    0      0           -                -         -       -",
    "Totals: issues=3 reads=6 unledgered=2 tokens=2000 (na=4)",
]


def test_text_output_is_byte_identical_when_no_read_is_void_or_degraded(monkeypatch, capsys):
    """Guards any extra line, column or changed cell appearing when no read is
    void and none carries a degraded value: unaudited reads (no key) must not
    print a degraded line, and the table and footer keep their old bytes."""
    issues = _legacy_issues()
    monkeypatch.setattr(ledger_mod, "_fetch_comments", lambda repo, issue: issues[issue])
    assert main(["--repo", "o/r", "--issue", "7", "--issue", "9", "--issue", "11"]) == 0
    assert capsys.readouterr().out == "\n".join(LEGACY_TEXT) + "\n"


def _audited_reads(degraded: str | None) -> list[dict]:
    return [
        verdict_comment(T1, "REWRITE", read_line(read=1, blocking=3, tokens=1000, seconds=60,
                                                 degraded=degraded)),
        verdict_comment(T2, "REWRITE", read_line(read=2, blocking=1, tokens="na",
                                                 degraded=degraded)),
        verdict_comment(T3, "BUILD", read_line(read=3, verdict="BUILD", blocking=0, tokens=500,
                                               degraded=degraded)),
    ]


def test_reads_marked_degraded_none_print_what_the_same_reads_without_the_key_print(
    tmp_path, capsys
):
    """Guards an extra line for `degraded=none`: a clean audited read is not a
    degraded read, so its output is the unaudited output, byte for byte."""
    without = _run_text(tmp_path, capsys, _audited_reads(None))
    clean = _run_text(tmp_path, capsys, _audited_reads("none"))
    assert clean == without
    assert len(clean) == 3
    doc_without = _run_json(tmp_path, capsys, _audited_reads(None))["issues"][0]
    doc_clean = _run_json(tmp_path, capsys, _audited_reads("none"))["issues"][0]
    assert doc_clean["clean"] == 3 and doc_without["clean"] == 0
    assert doc_clean["degraded"] == ["none"] * 3
    assert doc_clean["tokens_clean"] == 1500 and doc_without["tokens_clean"] is None
    for key in doc_clean:
        if key not in ("degraded", "clean", "tokens_clean"):
            assert doc_clean[key] == doc_without[key], key


def _extra_fixture(order: str) -> list[dict]:
    """A degraded read (read=7) and a void read (read=9, itself carrying
    `degraded=denied`), in comment order `order`: "DV" or "VD"."""
    degraded_at, void_at = (T1, T2) if order == "DV" else (T2, T1)
    return [
        verdict_comment(degraded_at, "REWRITE", read_line(
            read=7, blocking=3, tokens=100, seconds=10, degraded="denied,gh-used")),
        verdict_comment(void_at, "VOID", void_line(
            read=9, void_cause="comments-read", tokens=300, seconds=30, degraded="denied")),
    ]


EXTRA_DEGRADED = "  #7 read 7 degraded denied,gh-used"
EXTRA_VOID = "  #7 read 9 VOID comments-read"


@pytest.mark.parametrize(
    "order, expected",
    [("DV", [EXTRA_DEGRADED, EXTRA_VOID]), ("VD", [EXTRA_VOID, EXTRA_DEGRADED])],
)
def test_the_extra_lines_follow_the_totals_line_in_comment_order(
    tmp_path, capsys, order, expected
):
    """Guards the extra lines being grouped by kind (every VOID line first, or
    every degraded line first) instead of one sequence in comment order, the
    `<k>` being the position of the read instead of its `read=`, a void read
    that carries `degraded=denied` also printing a degraded line, and the
    footer leaving the void tokens out."""
    lines = _run_text(tmp_path, capsys, _extra_fixture(order))
    assert lines[1].split() == ["#7", "1", "0", "REWRITE", "3", "400", "-"]
    assert lines[2] == "Totals: issues=1 reads=1 unledgered=0 tokens=400 (na=0)"
    assert lines[3:] == expected
    assert len(lines) == 5


def test_the_extra_lines_follow_created_at_not_input_position(tmp_path, capsys):
    """Guards the extra lines being walked in the order the comments were
    given: like the reads, they are ordered by `createdAt`."""
    comments = list(reversed(_extra_fixture("DV")))
    assert [c["createdAt"] for c in comments] == [T2, T1]
    lines = _run_text(tmp_path, capsys, comments)
    assert lines[3:] == [EXTRA_DEGRADED, EXTRA_VOID]


def test_three_extra_lines_keep_one_sequence_in_comment_order(tmp_path, capsys):
    """Guards kind-grouping with more than one line of a kind: degraded, void,
    degraded must print in exactly that order."""
    comments = [
        verdict_comment(T1, "REWRITE", read_line(read=3, degraded="gh-used")),
        verdict_comment(T2, "VOID", void_line(read=4)),
        verdict_comment(T3, "REWRITE", read_line(read=4, degraded="agent-type,preflight-none")),
    ]
    lines = _run_text(tmp_path, capsys, comments)
    assert lines[3:] == [
        "  #7 read 3 degraded gh-used",
        "  #7 read 4 VOID no-probe-build",
        "  #7 read 4 degraded agent-type,preflight-none",
    ]


def test_the_totals_object_keeps_its_five_keys_and_sums_the_issues_values(monkeypatch, capsys):
    """Guards a key added to, removed from or renamed in `totals`, and the
    footer's `tokens` being summed over the parallel lists (which leave a void
    read out) instead of over the issues' `tokens_total`."""
    per_issue = {
        7: _extra_fixture("DV"),
        9: [verdict_comment(T1, "BUILD", read_line(read=1, verdict="BUILD", tokens=1000)),
            verdict_comment(T2, "BUILD", read_line(read=2, verdict="BUILD", tokens="na"))],
    }
    monkeypatch.setattr(ledger_mod, "_fetch_comments", lambda repo, issue: per_issue[issue])
    assert main(["--repo", "o/r", "--issue", "7", "--issue", "9"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[3] == "Totals: issues=2 reads=3 unledgered=0 tokens=1400 (na=1)"
    assert out[4:] == [EXTRA_DEGRADED, EXTRA_VOID]
    assert main(["--repo", "o/r", "--issue", "7", "--issue", "9", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["totals"] == {
        "issues": 2, "reads": 3, "unledgered": 0, "tokens_total": 1400, "tokens_na": 1,
    }
    assert set(doc["totals"]) == TOTALS_KEYS
    assert doc["totals"]["tokens_total"] == sum(i["tokens_total"] for i in doc["issues"])


def test_the_text_output_carries_no_clean_or_voided_count(tmp_path, capsys):
    """Guards the `clean` and `voided` counts leaking into the text output:
    they are `--json` only, the text carries the extra lines and nothing else."""
    lines = _run_text(tmp_path, capsys, _four_read_fixture())
    assert lines[3:] == ["  #7 read 2 degraded denied", "  #7 read 4 VOID no-probe-build"]
    assert "clean" not in "\n".join(lines) and "voided" not in "\n".join(lines)
