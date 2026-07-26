"""Tests for pulse — the weekly work-quantification ledger engine.

Every expectation is a hand-computed oracle, not an invariant: fixtures are
small enough to sum by hand, and each collector is exercised against records
mirroring the REAL on-disk formats sampled 2026-07-26 (Claude transcript
records, Codex rollout records, afk telemetry.jsonl, Brag Doc bullets,
weekly task snapshots, vault git log lines).

Design constraints under test:
- week bucketing is LOCAL-timezone ISO weeks (UTC records near midnight must
  land in the local week, not the UTC week);
- attention is gap-clustered and union-merged so parallel sessions cannot
  exceed wall clock;
- headless traffic (sdk-* entrypoints, sidechains, codex_exec) never counts
  as attention;
- token/spend sums dedup by requestId exactly like budget_burn;
- the ledger upsert recomputes only the requested window, preserves manual
  columns (energy/satisfaction), leaves frozen rows untouched, and is
  idempotent;
- config sourcing follows the budget_burn scaffold contract (defaults
  fallback, typed override, clear error on an unusable value).
"""

from __future__ import annotations

import csv
import importlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import pulse
import pulse_defaults
from pulse import (
    _classify_vault_commits,
    _cluster,
    _domain,
    _last_week_keys,
    _normalize_project,
    _union_hours,
    _week_key,
    collect_afk,
    collect_claude,
    collect_codex,
    collect_tasks,
    collect_wins,
    upsert_ledger,
)

TZ = ZoneInfo("America/Denver")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# _week_key — UTC ISO timestamps → LOCAL ISO week
# ---------------------------------------------------------------------------
class TestWeekKey:
    def test_plain_midweek(self) -> None:
        assert _week_key("2026-07-22T18:00:00.000Z", TZ) == "2026-W30"

    def test_utc_monday_is_local_sunday(self) -> None:
        # 2026-07-20 03:00 UTC = 2026-07-19 21:00 in Denver (Sunday) → W29.
        assert _week_key("2026-07-20T03:00:00.000Z", TZ) == "2026-W29"

    def test_date_only_is_read_as_local(self) -> None:
        # A bare date has no zone. Reading it as UTC midnight would shift it
        # to the previous local day and the previous ISO week; 2026-07-20 is
        # a Monday and must stay in W30 (matches collect_wins' reading).
        assert _week_key("2026-07-20", TZ) == "2026-W30"

    def test_naive_timestamp_is_read_as_local(self) -> None:
        assert _week_key("2026-07-20T01:30:00", TZ) == "2026-W30"

    def test_offset_timestamp(self) -> None:
        assert _week_key("2026-07-20T10:00:00+00:00", TZ) == "2026-W30"

    def test_garbage_returns_none(self) -> None:
        assert _week_key("not-a-timestamp", TZ) is None
        assert _week_key("", TZ) is None
        assert _week_key(None, TZ) is None

    def test_week_number_zero_padded(self) -> None:
        # 2026-01-07 is in ISO W02 — the key must be zero-padded for sorting.
        assert _week_key("2026-01-07T12:00:00Z", TZ) == "2026-W02"


class TestLastWeekKeys:
    def test_trailing_weeks_inclusive_of_current(self) -> None:
        # Local "today" 2026-07-26 (Sunday) is in W30.
        keys = _last_week_keys(datetime(2026, 7, 26, tzinfo=TZ).date(), 3)
        assert keys == ["2026-W28", "2026-W29", "2026-W30"]

    def test_year_boundary(self) -> None:
        # 2026-01-07 is W02; two weeks back crosses into 2025's W01 of 2026?
        # 2026 ISO W01 begins Mon 2025-12-29.
        keys = _last_week_keys(datetime(2026, 1, 7, tzinfo=TZ).date(), 3)
        assert keys == ["2025-W52", "2026-W01", "2026-W02"]


# ---------------------------------------------------------------------------
# _cluster / _union_hours — gap clustering and interval union
# ---------------------------------------------------------------------------
class TestCluster:
    def test_gap_splits_clusters(self) -> None:
        times = [
            _dt("2026-07-22T10:00:00+00:00"),
            _dt("2026-07-22T10:05:00+00:00"),
            _dt("2026-07-22T10:20:00+00:00"),  # 15 min gap == threshold: joins
            _dt("2026-07-22T11:00:00+00:00"),  # 40 min gap: splits
        ]
        clusters = _cluster(times, gap_minutes=15)
        assert clusters == [
            (_dt("2026-07-22T10:00:00+00:00"), _dt("2026-07-22T10:20:00+00:00")),
            (_dt("2026-07-22T11:00:00+00:00"), _dt("2026-07-22T11:00:00+00:00")),
        ]

    def test_unsorted_input_is_sorted(self) -> None:
        times = [
            _dt("2026-07-22T10:10:00+00:00"),
            _dt("2026-07-22T10:00:00+00:00"),
        ]
        assert _cluster(times, gap_minutes=15) == [
            (_dt("2026-07-22T10:00:00+00:00"), _dt("2026-07-22T10:10:00+00:00"))
        ]

    def test_empty(self) -> None:
        assert _cluster([], gap_minutes=15) == []


class TestUnionHours:
    def test_overlapping_intervals_merge(self) -> None:
        # [10:00-11:00] ∪ [10:30-11:30] = 1.5h — parallel sessions can't
        # exceed wall clock.
        intervals = [
            (_dt("2026-07-22T10:00:00+00:00"), _dt("2026-07-22T11:00:00+00:00")),
            (_dt("2026-07-22T10:30:00+00:00"), _dt("2026-07-22T11:30:00+00:00")),
        ]
        assert _union_hours(intervals) == pytest.approx(1.5)

    def test_disjoint_intervals_sum(self) -> None:
        intervals = [
            (_dt("2026-07-22T10:00:00+00:00"), _dt("2026-07-22T10:20:00+00:00")),
            (_dt("2026-07-22T11:00:00+00:00"), _dt("2026-07-22T11:10:00+00:00")),
        ]
        assert _union_hours(intervals) == pytest.approx(0.5)

    def test_empty(self) -> None:
        assert _union_hours([]) == 0.0


# ---------------------------------------------------------------------------
# _normalize_project / _domain — cwd → project → domain
# ---------------------------------------------------------------------------
class TestNormalizeProject:
    def test_plain_repo(self) -> None:
        assert (
            _normalize_project("/Users/x/Developer/GitHub/graphmark") == "graphmark"
        )

    def test_afk_worktree_collapses_to_repo(self) -> None:
        assert (
            _normalize_project(
                "/Users/x/Developer/GitHub/orbit-wars/.afk/worktrees/issue-98"
            )
            == "orbit-wars"
        )

    def test_claude_worktree_collapses_to_repo(self) -> None:
        assert (
            _normalize_project(
                "/Users/x/Developer/GitHub/the-vault/.claude/worktrees/adoring-r"
            )
            == "the-vault"
        )

    def test_temp_dir_buckets(self) -> None:
        assert (
            _normalize_project("/private/var/folders/c3/xyz/T") == "_desktop-temp"
        )
        assert _normalize_project("/private/tmp/claude-501/x/scratchpad/spike") == (
            "_desktop-temp"
        )

    def test_empty(self) -> None:
        assert _normalize_project("") == "_unknown"
        assert _normalize_project(None) == "_unknown"


class TestSchoolScope:
    """Coursework happens IN the vault via Claude, so repo-level attribution
    books it to `vault` — school time would inflate vault work and mask the
    decline it is causing. Domain must be decided by path, not repo."""

    PATTERN = pulse._repo_pattern(Path("/Users/x/Developer/GitHub"))
    RULES = pulse_defaults.DOMAIN_RULES

    def test_coursework_in_the_vault_is_school_not_vault(self) -> None:
        scope = pulse._touched_scope(
            '{"file_path": "/Users/x/Developer/GitHub/the-vault/school/'
            'cse511/week-1-notes.md"}',
            self.PATTERN,
        )
        assert scope == "the-vault/school/cse511"
        assert _domain(scope, self.RULES) == "school"

    def test_ordinary_vault_work_is_still_vault(self) -> None:
        scope = pulse._touched_scope(
            '{"file_path": "/Users/x/Developer/GitHub/the-vault/work/Tasks.md"}',
            self.PATTERN,
        )
        assert scope == "the-vault/work"
        assert _domain(scope, self.RULES) == "vault"

    def test_course_codes_and_asu_anywhere_are_school(self) -> None:
        for path, expected in (
            ("/Users/x/Developer/GitHub/the-vault/personal/school/a.md", "school"),
            ("/Users/x/Developer/GitHub/the-vault/personal/asu/notes.md", "school"),
            ("/Users/x/Developer/GitHub/cse511-project/src/main.py", "school"),
            ("/Users/x/Developer/GitHub/the-vault/personal/hse542/x.md", "school"),
            ("/Users/x/Developer/GitHub/the-vault/coursework/a.md", "school"),
        ):
            scope = pulse._touched_scope(f'{{"file_path": "{path}"}}', self.PATTERN)
            assert _domain(scope, self.RULES) == "school", path

    def test_repo_root_file_keeps_the_repo_scope(self) -> None:
        scope = pulse._touched_scope(
            '{"file_path": "/Users/x/Developer/GitHub/graphmark/README.md"}',
            self.PATTERN,
        )
        assert scope == "graphmark"
        assert _domain(scope, self.RULES) == "build"

    def test_bucket_key_stays_the_repo(self) -> None:
        # Clustering buckets by repo so a session hopping directories inside
        # one repo does not fragment into many tiny blocks.
        assert pulse._scope_repo("the-vault/school/cse511") == "the-vault"
        assert pulse._scope_repo("graphmark") == "graphmark"


class TestTouchedScope:
    """Attribution follows what a session TOUCHES, not the dir it was
    launched from: nearly every session is launched from the vault and works
    cross-repo, so cwd alone books all of it to 'vault'."""

    PATTERN = pulse._repo_pattern(Path("/Users/x/Developer/GitHub"))

    def test_dominant_scope_in_line(self) -> None:
        line = (
            'edit /Users/x/Developer/GitHub/the-workshop/core/a.py and '
            '/Users/x/Developer/GitHub/the-workshop/core/b.py vs '
            '/Users/x/Developer/GitHub/the-vault/c.md'
        )
        assert pulse._touched_scope(line, self.PATTERN) == "the-workshop/core"

    def test_worktree_sibling_dir_maps_to_repo(self) -> None:
        line = "/Users/x/Developer/GitHub/afk-agent-system-worktrees/aa6/x.py"
        assert (
            pulse._touched_scope(line, self.PATTERN) == "afk-agent-system/aa6"
        )

    def test_tie_is_no_signal(self) -> None:
        line = (
            "/Users/x/Developer/GitHub/alpha/src/a "
            "/Users/x/Developer/GitHub/beta/src/b"
        )
        assert pulse._touched_scope(line, self.PATTERN) is None

    def test_depth_is_capped_at_two_directories(self) -> None:
        line = "/Users/x/Developer/GitHub/the-vault/a/b/c/d/e.md"
        assert pulse._touched_scope(line, self.PATTERN) == "the-vault/a/b"

    def test_no_mention(self) -> None:
        assert pulse._touched_scope("nothing here", self.PATTERN) is None


class TestDomain:
    RULES = (
        ("the-vault", "vault"),
        ("graphmark", "build"),
        ("household", "home"),
    )

    def test_first_matching_rule_wins(self) -> None:
        assert _domain("the-vault", self.RULES) == "vault"
        assert _domain("graphmark", self.RULES) == "build"
        assert _domain("household-bms", self.RULES) == "home"

    def test_unmatched_is_other(self) -> None:
        assert _domain("mystery-repo", self.RULES) == "other"

    def test_defaults_cover_known_repos(self) -> None:
        rules = pulse_defaults.DOMAIN_RULES
        assert _domain("the-vault", rules) == "vault"
        assert _domain("afk-agent-system", rules) == "build"
        assert _domain("the-workshop", rules) == "build"
        assert _domain("household-command-center", rules) == "home"
        assert _domain("_desktop-temp", rules) == "other"


# ---------------------------------------------------------------------------
# collect_claude — transcripts → interactive events + deduped tokens/spend
# ---------------------------------------------------------------------------
def _claude_fixture(root: Path) -> None:
    proj = root / "-Users-x-Developer-GitHub-graphmark"
    proj.mkdir(parents=True)
    # Interactive session: 2 user records + 2 assistant records carrying the
    # SAME requestId (streaming duplicate) + one sidechain record.
    interactive = [
        {
            "type": "user",
            "timestamp": "2026-07-22T18:00:00.000Z",
            "sessionId": "s1",
            "cwd": "/Users/x/Developer/GitHub/graphmark",
            "entrypoint": "claude-desktop",
            "isSidechain": False,
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-22T18:10:00.000Z",
            "sessionId": "s1",
            "cwd": "/Users/x/Developer/GitHub/graphmark",
            "entrypoint": "claude-desktop",
            "isSidechain": False,
            "requestId": "req_1",
            "message": {
                "model": "claude-opus-5",
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-22T18:10:05.000Z",
            "sessionId": "s1",
            "cwd": "/Users/x/Developer/GitHub/graphmark",
            "entrypoint": "claude-desktop",
            "isSidechain": False,
            "requestId": "req_1",  # duplicate — must count once
            "message": {
                "model": "claude-opus-5",
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-22T18:20:00.000Z",
            "sessionId": "s1",
            "cwd": "/Users/x/Developer/GitHub/graphmark",
            "entrypoint": "claude-desktop",
            "isSidechain": True,  # subagent thread: not attention
            "requestId": "req_2",
            "message": {
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 2000, "output_tokens": 100},
            },
        },
    ]
    (proj / "s1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in interactive) + "\n"
    )
    # Headless SDK session in the same project: tokens count, attention no.
    headless = [
        {
            "type": "assistant",
            "timestamp": "2026-07-22T19:00:00.000Z",
            "sessionId": "s2",
            "cwd": "/Users/x/Developer/GitHub/graphmark",
            "entrypoint": "sdk-cli",
            "isSidechain": False,
            "requestId": "req_3",
            "message": {
                "model": "claude-sonnet-5",
                "usage": {"input_tokens": 4000, "output_tokens": 1000},
            },
        }
    ]
    (proj / "s2.jsonl").write_text("\n".join(json.dumps(r) for r in headless) + "\n")


class TestCollectClaude:
    def test_events_tokens_sessions(self, tmp_path: Path) -> None:
        _claude_fixture(tmp_path)
        got = collect_claude(tmp_path, TZ)
        # Attention events: only the 3 non-sidechain interactive records.
        assert [(e[0].isoformat(), e[1]) for e in got["events"]] == [
            ("2026-07-22T18:00:00+00:00", "graphmark"),
            ("2026-07-22T18:10:00+00:00", "graphmark"),
            ("2026-07-22T18:10:05+00:00", "graphmark"),
        ]
        # Sessions: s1 only (s2 is sdk-cli).
        assert got["sessions_by_week"] == {"2026-W30": 1}
        # Tokens: req_1 once (1500) + req_2 (2100) + req_3 (5000) = 8600.
        assert got["tokens_by_week"] == {"2026-W30": 8600}
        # Spend: opus 1000*5/1M + 500*25/1M = 0.0175; haiku 2000*1 + 100*5 → 0.0025;
        # sonnet 4000*3 + 1000*15 → 0.027. Total 0.047.
        assert got["spend_by_week"]["2026-W30"] == pytest.approx(0.047)

    def test_empty_root(self, tmp_path: Path) -> None:
        got = collect_claude(tmp_path, TZ)
        assert got["events"] == []
        assert got["sessions_by_week"] == {}

    def test_pre_entrypoint_records_of_sdk_session_are_not_attention(
        self, tmp_path: Path
    ) -> None:
        """The real transcript shape: two timestamped queue-operation records
        before the entrypoint appears. Deciding interactivity per-record leaks
        the opening of every headless run into attention."""
        proj = tmp_path / "-Users-x-Developer-GitHub-graphmark"
        proj.mkdir(parents=True)
        records = [
            {
                "type": "queue-operation",
                "timestamp": "2026-07-22T02:00:00.000Z",
                "sessionId": "h1",
                "cwd": None,
            },
            {
                "type": "queue-operation",
                "timestamp": "2026-07-22T02:30:00.000Z",
                "sessionId": "h1",
                "cwd": None,
            },
            {
                "type": "assistant",
                "timestamp": "2026-07-22T02:31:00.000Z",
                "sessionId": "h1",
                "cwd": "/Users/x/Developer/GitHub/graphmark",
                "entrypoint": "sdk-cli",
                "isSidechain": False,
                "requestId": "req_h",
                "message": {
                    "model": "claude-sonnet-5",
                    "usage": {"input_tokens": 100, "output_tokens": 10},
                },
            },
        ]
        (proj / "h1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )
        got = collect_claude(tmp_path, TZ)
        assert got["events"] == []
        assert got["sessions_by_week"] == {}
        # Headless work still costs money, so tokens must survive: 110.
        assert got["tokens_by_week"] == {"2026-W30": 110}

    def test_session_without_entrypoint_is_untrusted(self, tmp_path: Path) -> None:
        proj = tmp_path / "-Users-x-Developer-GitHub-graphmark"
        proj.mkdir(parents=True)
        records = [
            {
                "type": "user",
                "timestamp": "2026-07-22T18:00:00.000Z",
                "sessionId": "u1",
                "cwd": "/Users/x/Developer/GitHub/graphmark",
                "isSidechain": False,
            },
            {
                "type": "user",
                "timestamp": "2026-07-22T18:05:00.000Z",
                "sessionId": "u1",
                "cwd": "/Users/x/Developer/GitHub/graphmark",
                "isSidechain": False,
            },
        ]
        (proj / "u1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )
        got = collect_claude(tmp_path, TZ)
        # Neither hours nor a session count — the two must never disagree.
        assert got["events"] == []
        assert got["sessions_by_week"] == {}

    def test_duplicate_transcript_across_project_dirs_counts_once(
        self, tmp_path: Path
    ) -> None:
        """The dir-rename reconciliation left 141 byte-identical transcripts
        in two project dirs; a path-keyed session count double-counts them."""
        records = [
            {
                "type": "user",
                "timestamp": "2026-07-22T18:00:00.000Z",
                "sessionId": "d1",
                "cwd": "/Users/x/Developer/GitHub/the-vault",
                "entrypoint": "claude-desktop",
                "isSidechain": False,
            },
            {
                "type": "assistant",
                "timestamp": "2026-07-22T18:05:00.000Z",
                "sessionId": "d1",
                "cwd": "/Users/x/Developer/GitHub/the-vault",
                "entrypoint": "claude-desktop",
                "isSidechain": False,
                "requestId": "req_d",
                "message": {
                    "model": "claude-opus-5",
                    "usage": {"input_tokens": 1000, "output_tokens": 0},
                },
            },
        ]
        body = "\n".join(json.dumps(r) for r in records) + "\n"
        for dirname in ("-Users-x-my-brain", "-Users-x-the-vault"):
            d = tmp_path / dirname
            d.mkdir(parents=True)
            (d / "d1.jsonl").write_text(body)
        got = collect_claude(tmp_path, TZ)
        assert got["sessions_by_week"] == {"2026-W30": 1}
        # requestId dedup already protects tokens: 1000, not 2000.
        assert got["tokens_by_week"] == {"2026-W30": 1000}

    def test_school_hours_do_not_inflate_vault_hours(self, tmp_path: Path) -> None:
        """End-to-end: an hour of coursework in the vault must land in
        attn_school_h, not attn_vault_h."""
        proj = tmp_path / "-Users-x-Developer-GitHub-the-vault"
        proj.mkdir(parents=True)
        base = {
            "sessionId": "sc",
            "cwd": "/Users/x/Developer/GitHub/the-vault",
            "entrypoint": "claude-desktop",
            "isSidechain": False,
        }

        def edit(ts: str, path: str) -> dict:
            return {
                **base,
                "type": "assistant",
                "timestamp": ts,
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": path},
                        }
                    ]
                },
            }

        school = "/Users/x/Developer/GitHub/the-vault/school/cse511/hw1.md"
        vault = "/Users/x/Developer/GitHub/the-vault/work/Tasks.md"
        # Steps stay under GAP_MINUTES so each run is one continuous block.
        records = [
            edit("2026-09-07T18:00:00.000Z", school),
            edit("2026-09-07T18:10:00.000Z", school),
            edit("2026-09-07T18:20:00.000Z", school),
            edit("2026-09-07T18:30:00.000Z", school),
            edit("2026-09-07T20:00:00.000Z", vault),
            edit("2026-09-07T20:10:00.000Z", vault),
            edit("2026-09-07T20:20:00.000Z", vault),
            edit("2026-09-07T20:30:00.000Z", vault),
        ]
        (proj / "sc.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )
        rows = pulse.scan(
            projects_root=tmp_path,
            codex_root=tmp_path / "none",
            repos_root=Path("/Users/x/Developer/GitHub"),
            vault_root=tmp_path / "vault",
            week_keys=["2026-W37"],
            tz=TZ,
        )
        r = rows["2026-W37"]
        assert r["attn_school_h"] == "0.50"
        assert r["attn_vault_h"] == "0.50"
        assert r["attn_total_h"] == "1.00"

    def test_attribution_follows_touched_repo(self, tmp_path: Path) -> None:
        """A vault-launched session working on graphmark is graphmark work."""
        proj = tmp_path / "-Users-x-Developer-GitHub-the-vault"
        proj.mkdir(parents=True)
        base = {
            "sessionId": "t1",
            "cwd": "/Users/x/Developer/GitHub/the-vault",
            "entrypoint": "claude-desktop",
            "isSidechain": False,
        }
        records = [
            # Before any repo is touched: falls back to the launch dir.
            {**base, "type": "user", "timestamp": "2026-07-22T18:00:00.000Z"},
            {
                **base,
                "type": "assistant",
                "timestamp": "2026-07-22T18:05:00.000Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {
                                "file_path": (
                                    "/Users/x/Developer/GitHub/graphmark/a.py"
                                )
                            },
                        }
                    ]
                },
            },
            # Sticky: no mention here, but the session is still on graphmark.
            {**base, "type": "user", "timestamp": "2026-07-22T18:10:00.000Z"},
        ]
        (proj / "t1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )
        got = collect_claude(
            tmp_path, TZ, repos_root=Path("/Users/x/Developer/GitHub")
        )
        assert [e[1] for e in got["events"]] == [
            "the-vault",
            "graphmark",
            "graphmark",
        ]

    def test_request_id_dedup_spans_files(self, tmp_path: Path) -> None:
        """A resumed session rewrites earlier records into a new transcript;
        `seen` is scoped across files so the API call counts once."""
        proj = tmp_path / "-Users-x-Developer-GitHub-graphmark"
        proj.mkdir(parents=True)
        rec = {
            "type": "assistant",
            "timestamp": "2026-07-22T18:00:00.000Z",
            "cwd": "/Users/x/Developer/GitHub/graphmark",
            "entrypoint": "claude-desktop",
            "isSidechain": False,
            "requestId": "req_shared",
            "message": {
                "model": "claude-opus-5",
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        }
        (proj / "a.jsonl").write_text(json.dumps({**rec, "sessionId": "a"}) + "\n")
        (proj / "b.jsonl").write_text(json.dumps({**rec, "sessionId": "b"}) + "\n")
        got = collect_claude(tmp_path, TZ)
        assert got["tokens_by_week"] == {"2026-W30": 1500}
        assert got["spend_by_week"]["2026-W30"] == pytest.approx(0.0175)


# ---------------------------------------------------------------------------
# collect_codex — rollouts → interactive events + last-total tokens
# ---------------------------------------------------------------------------
def _codex_rollout(
    path: Path, *, cwd: str, originator: str, source: str, base: str
) -> None:
    records = [
        {
            "timestamp": f"{base}T18:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "session_id": "x",
                "cwd": cwd,
                "originator": originator,
                "source": source,
            },
        },
        {
            "timestamp": f"{base}T18:05:00.000Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {"total_tokens": 1000},
                    "last_token_usage": {"total_tokens": 1000},
                },
            },
        },
        {
            "timestamp": f"{base}T18:30:00.000Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {"total_tokens": 2500},
                    "last_token_usage": {"total_tokens": 1500},
                },
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


class TestCollectCodex:
    def test_desktop_counts_exec_does_not(self, tmp_path: Path) -> None:
        _codex_rollout(
            tmp_path / "2026/07/22/rollout-a.jsonl",
            cwd="/Users/x/Developer/GitHub/graphmark",
            originator="Codex Desktop",
            source="vscode",
            base="2026-07-22",
        )
        _codex_rollout(
            tmp_path / "2026/07/22/rollout-b.jsonl",
            cwd="/Users/x/Developer/GitHub/orbit-wars/.afk/worktrees/issue-9",
            originator="codex_exec",
            source="exec",
            base="2026-07-22",
        )
        got = collect_codex(tmp_path, TZ)
        # Only the desktop session emits attention events (all 3 records).
        assert [(e[0].isoformat(), e[1]) for e in got["events"]] == [
            ("2026-07-22T18:00:00+00:00", "graphmark"),
            ("2026-07-22T18:05:00+00:00", "graphmark"),
            ("2026-07-22T18:30:00+00:00", "graphmark"),
        ]
        assert got["sessions_by_week"] == {"2026-W30": 1}
        # Tokens: LAST cumulative total (2500), not the sum of totals (3500) —
        # interactive sessions only.
        assert got["tokens_by_week"] == {"2026-W30": 2500}

    def test_temp_cwd_buckets_stable(self, tmp_path: Path) -> None:
        _codex_rollout(
            tmp_path / "2026/07/22/rollout-c.jsonl",
            cwd="/private/var/folders/c3/xvb9/T",
            originator="Codex Desktop",
            source="vscode",
            base="2026-07-22",
        )
        got = collect_codex(tmp_path, TZ)
        assert {e[1] for e in got["events"]} == {"_desktop-temp"}

    def test_subagent_source_dict_is_automation(self, tmp_path: Path) -> None:
        """Real rollouts carry source as a dict for subagent runs; a string
        compare against 'exec' lets that automation through."""
        path = tmp_path / "2026/07/22/rollout-sub.jsonl"
        path.parent.mkdir(parents=True)
        records = [
            {
                "timestamp": "2026-07-22T18:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "session_id": "g",
                    "cwd": "/Users/x/Developer/GitHub/graphmark",
                    "originator": "Codex Desktop",
                    "source": {"subagent": {"other": "guardian"}},
                },
            },
            {
                "timestamp": "2026-07-22T18:10:00.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 900}},
                },
            },
        ]
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        got = collect_codex(tmp_path, TZ)
        assert got["events"] == []
        assert got["sessions_by_week"] == {}
        assert got["tokens_by_week"] == {}

    def test_week_spanning_session_books_token_deltas_per_week(
        self, tmp_path: Path
    ) -> None:
        """A Sunday→Monday session must not bill Sunday's tokens to Monday:
        attention splits across both weeks, so tokens have to as well."""
        path = tmp_path / "2026/07/20/rollout-span.jsonl"
        path.parent.mkdir(parents=True)
        records = [
            # Sun 2026-07-19 22:00 local (W29) = 2026-07-20 04:00Z
            {
                "timestamp": "2026-07-20T04:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "session_id": "s",
                    "cwd": "/Users/x/Developer/GitHub/graphmark",
                    "originator": "Codex Desktop",
                    "source": "vscode",
                },
            },
            {
                "timestamp": "2026-07-20T04:30:00.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 4_500_000}},
                },
            },
            # Mon 2026-07-20 00:30 local (W30) = 2026-07-20 06:30Z
            {
                "timestamp": "2026-07-20T06:30:00.000Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 5_000_000}},
                },
            },
        ]
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        got = collect_codex(tmp_path, TZ)
        assert got["tokens_by_week"] == {
            "2026-W29": 4_500_000,
            "2026-W30": 500_000,
        }
        # The session itself counts in both weeks it touched.
        assert got["sessions_by_week"] == {"2026-W29": 1, "2026-W30": 1}

    def test_empty_root(self, tmp_path: Path) -> None:
        got = collect_codex(tmp_path, TZ)
        assert got["events"] == []


# ---------------------------------------------------------------------------
# collect_afk — telemetry.jsonl glob → weekly output metrics
# ---------------------------------------------------------------------------
def _afk_fixture(root: Path) -> None:
    repo = root / "some-repo" / "docs" / "dev-cycle"
    repo.mkdir(parents=True)
    records = [
        # 4 slice outcomes in W30: merged@1, merged@2, published@1, quarantined.
        {"ts": "2026-07-22T02:00:00Z", "issue": 1, "status": "merged",
         "attempts": 1, "cost": 1.50},
        {"ts": "2026-07-22T02:10:00Z", "issue": 2, "status": "merged",
         "attempts": 2, "cost": 3.25},
        {"ts": "2026-07-22T02:20:00Z", "issue": 3, "status": "published",
         "attempts": 1, "cost": 0.75},
        {"ts": "2026-07-22T02:30:00Z", "issue": 4, "status": "quarantined",
         "attempts": 3, "cost": 2.00},
        # Non-slice records: cost-bearing orchestrator + resume count toward
        # cost; attestations and deduped auto_promote decisions never count.
        {"ts": "2026-07-22T02:40:00Z", "record_type": "orchestrator_cost",
         "op": "scout", "cost": 0.50},
        {"ts": "2026-07-22T02:41:00Z", "record_type": "conductor_resume",
         "resume_mode": "fresh", "cost": 0.25},
        {"ts": "2026-07-22T02:42:00Z", "record_type": "plan_attestation",
         "issue": 1},
        {"ts": "2026-07-22T02:43:00Z", "record_type": "generation_attestation",
         "issue": 1, "cost": 1.50},  # duplicates slice cost — must NOT sum
        {"ts": "2026-07-22T02:44:00Z", "record_type": "auto_promote_decision",
         "promoted": []},
    ]
    (repo / "telemetry.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )


class TestCollectAfk:
    def test_weekly_metrics(self, tmp_path: Path) -> None:
        _afk_fixture(tmp_path)
        got = collect_afk(tmp_path, TZ)
        wk = got["2026-W30"]
        assert wk["merged"] == 2
        assert wk["outcomes"] == 4
        # first-attempt: merged+published with attempts==1 → 2 of 3.
        assert wk["first_attempt_pct"] == pytest.approx(66.7, abs=0.1)
        assert wk["quarantine_pct"] == pytest.approx(25.0)
        # cost: 1.50+3.25+0.75+2.00 slices + 0.50 orchestrator + 0.25 resume
        # = 8.25; generation_attestation's 1.50 must NOT be double-counted.
        assert wk["cost_usd"] == pytest.approx(8.25)

    def test_missing_root(self, tmp_path: Path) -> None:
        assert collect_afk(tmp_path / "nope", TZ) == {}


# ---------------------------------------------------------------------------
# _classify_vault_commits — git log lines → per-machine weekly counts
# ---------------------------------------------------------------------------
class TestClassifyVaultCommits:
    ENTRIES = [
        ("charles.coonce@clearwayenergy.com", "2026-07-22T09:00:00-06:00",
         "vault: auto-sync session changes"),
        ("charles.coonce@clearwayenergy.com", "2026-07-22T10:00:00-06:00",
         "vault: auto-sync session changes"),
        ("152736273+cdcoonce@users.noreply.github.com",
         "2026-07-22T11:00:00-06:00", "vault: auto-sync session changes"),
        ("152736273+cdcoonce@users.noreply.github.com",
         "2026-07-22T12:00:00-06:00", "wrap-up: harvest the session"),
        ("152736273+cdcoonce@users.noreply.github.com",
         "2026-07-22T13:00:00-06:00", "Add Meals-at-Home idea (#118)"),
        ("152736273+cdcoonce@users.noreply.github.com",
         "2026-07-22T14:00:00-06:00", "Merge pull request #99 from x/y"),
    ]

    def test_counts(self) -> None:
        got = _classify_vault_commits(self.ENTRIES, TZ)
        wk = got["2026-W30"]
        assert wk["autosync_work"] == 2
        assert wk["autosync_personal"] == 1
        # Deliberate: wrap-up + hand commit; the merge is excluded.
        assert wk["deliberate_work"] == 0
        assert wk["deliberate_personal"] == 2

    def test_empty(self) -> None:
        assert _classify_vault_commits([], TZ) == {}


# ---------------------------------------------------------------------------
# collect_wins / collect_tasks — markdown parsers
# ---------------------------------------------------------------------------
class TestCollectWins:
    def test_dated_bullets_counted_by_week(self, tmp_path: Path) -> None:
        brag = tmp_path / "Brag Doc.md"
        brag.write_text(
            "# Brag\n"
            "## Q3 2026\n"
            "- **2026-07-22 — Did a thing.** Detail.\n"
            "- **2026-07-21 — Did another.** Detail.\n"
            "- **2026-07-13 — Older win.** Detail.\n"
            "Some prose mentioning **2026-07-22** that is not a bullet.\n"
        )
        got = collect_wins(brag, TZ)
        assert got == {"2026-W30": 2, "2026-W29": 1}

    def test_missing_file(self, tmp_path: Path) -> None:
        assert collect_wins(tmp_path / "nope.md", TZ) == {}


class TestCollectTasks:
    def test_snapshot_levels(self, tmp_path: Path) -> None:
        arch = tmp_path / "work" / "archive" / "2026" / "tasks"
        arch.mkdir(parents=True)
        (arch / "2026-W29-tasks.md").write_text(
            "- [x] done one\n- [ ] open\n  - [x] nested done\n"
        )
        (arch / "2026-W30-tasks.md").write_text("- [x] done\n")
        got = collect_tasks(tmp_path)
        assert got == {"2026-W29": 2, "2026-W30": 1}

    def test_current_tasks_frontmatter_week(self, tmp_path: Path) -> None:
        arch = tmp_path / "work" / "archive" / "2026" / "tasks"
        arch.mkdir(parents=True)
        (tmp_path / "work" / "Tasks.md").write_text(
            '---\nweek: "2026-07-20"\n---\n- [x] a\n- [x] b\n'
        )
        got = collect_tasks(tmp_path)
        # 2026-07-20 is the Monday of W30.
        assert got == {"2026-W30": 2}

    def test_flat_archive_layout(self, tmp_path: Path) -> None:
        """The real vault has snapshots BOTH at archive/<year>/tasks/ and
        directly at archive/tasks/; a single-layout glob silently drops one."""
        nested = tmp_path / "work" / "archive" / "2026" / "tasks"
        nested.mkdir(parents=True)
        (nested / "2026-W27-tasks.md").write_text("- [x] a\n")
        flat = tmp_path / "work" / "archive" / "tasks"
        flat.mkdir(parents=True)
        (flat / "2026-W28-tasks.md").write_text("- [x] a\n- [x] b\n")
        assert collect_tasks(tmp_path) == {"2026-W27": 1, "2026-W28": 2}

    def test_missing_dirs(self, tmp_path: Path) -> None:
        assert collect_tasks(tmp_path) == {}


# ---------------------------------------------------------------------------
# upsert_ledger — frozen rows, manual columns, idempotency
# ---------------------------------------------------------------------------
class TestUpsertLedger:
    def _row(self, week: str, **over: object) -> dict[str, str]:
        row = {c: "" for c in pulse.LEDGER_COLUMNS}
        row.update({"week": week, "machine": "personal"})
        row.update({k: str(v) for k, v in over.items()})
        return row

    def test_upsert_preserves_manual_and_frozen(self, tmp_path: Path) -> None:
        ledger = tmp_path / "pulse-personal.csv"
        with ledger.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=pulse.LEDGER_COLUMNS)
            w.writeheader()
            # Frozen row (outside window) with manual energy — untouchable.
            w.writerow(self._row("2026-W20", attn_total_h="9.99", energy="4"))
            # In-window row with stale derived value + manual satisfaction.
            w.writerow(
                self._row("2026-W30", attn_total_h="1.00", satisfaction="3")
            )
        new_rows = {
            "2026-W30": {"attn_total_h": "2.50", "wins": "2"},
            "2026-W31": {"attn_total_h": "0.00"},
        }
        upsert_ledger(ledger, new_rows, machine="personal")
        got = {r["week"]: r for r in csv.DictReader(ledger.open())}
        assert got["2026-W20"]["attn_total_h"] == "9.99"  # frozen
        assert got["2026-W20"]["energy"] == "4"
        assert got["2026-W30"]["attn_total_h"] == "2.50"  # recomputed
        assert got["2026-W30"]["wins"] == "2"
        assert got["2026-W30"]["satisfaction"] == "3"  # manual preserved
        assert got["2026-W31"]["attn_total_h"] == "0.00"  # appended
        assert list(got) == ["2026-W20", "2026-W30", "2026-W31"]  # sorted

    def test_idempotent(self, tmp_path: Path) -> None:
        ledger = tmp_path / "pulse-personal.csv"
        rows = {"2026-W30": {"attn_total_h": "2.50"}}
        upsert_ledger(ledger, rows, machine="personal")
        first = ledger.read_text()
        upsert_ledger(ledger, rows, machine="personal")
        assert ledger.read_text() == first

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        ledger = tmp_path / "perf" / "metrics" / "pulse-personal.csv"
        upsert_ledger(ledger, {"2026-W30": {"wins": "1"}}, machine="personal")
        got = list(csv.DictReader(ledger.open()))
        assert got[0]["week"] == "2026-W30"
        assert got[0]["machine"] == "personal"

    def test_unknown_columns_survive_on_frozen_rows(self, tmp_path: Path) -> None:
        """A newer engine's column must survive an older engine's run —
        frozen weeks can never be recomputed, so a drop is unrecoverable."""
        ledger = tmp_path / "pulse-personal.csv"
        fields = pulse.LEDGER_COLUMNS + ["attn_meetings_h"]
        with ledger.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            frozen = self._row("2026-W20")
            frozen["attn_meetings_h"] = "3.50"
            w.writerow(frozen)
        upsert_ledger(ledger, {"2026-W30": {"wins": "1"}}, machine="personal")
        rows = {r["week"]: r for r in csv.DictReader(ledger.open())}
        assert rows["2026-W20"]["attn_meetings_h"] == "3.50"
        assert "attn_meetings_h" in rows["2026-W30"]

    def test_duplicate_week_raises(self, tmp_path: Path) -> None:
        """Last-wins would silently discard the first row's manual values."""
        ledger = tmp_path / "pulse-personal.csv"
        with ledger.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=pulse.LEDGER_COLUMNS)
            w.writeheader()
            w.writerow(self._row("2026-W28", energy="4"))
            w.writerow(self._row("2026-W28"))
        with pytest.raises(ValueError, match="2026-W28"):
            upsert_ledger(ledger, {"2026-W30": {"wins": "1"}}, machine="personal")


class TestHasEvidence:
    def test_all_zero_row_is_not_evidence(self) -> None:
        row = {c: "" for c in pulse.LEDGER_COLUMNS}
        row.update(
            {
                "week": "2025-W30",
                "machine": "personal",
                "computed_at": "2026-07-26T00:00:00Z",
                "attn_total_h": "0.00",
                "claude_sessions": "0",
                "afk_merged": "0",
                "tokens_m": "0.00",
            }
        )
        assert pulse.has_evidence(row) is False

    def test_any_nonzero_is_evidence(self) -> None:
        row = {c: "" for c in pulse.LEDGER_COLUMNS}
        row.update({"week": "2026-W30", "attn_total_h": "0.00", "wins": "1"})
        assert pulse.has_evidence(row) is True

    def test_manual_rating_alone_is_evidence(self) -> None:
        row = {c: "" for c in pulse.LEDGER_COLUMNS}
        row.update({"week": "2026-W30", "attn_total_h": "0.00", "energy": "4"})
        assert pulse.has_evidence(row) is True


class TestExistingWeeks:
    def test_reads_week_keys(self, tmp_path: Path) -> None:
        ledger = tmp_path / "pulse-personal.csv"
        upsert_ledger(
            ledger,
            {"2026-W29": {"wins": "1"}, "2026-W30": {"wins": "2"}},
            machine="personal",
        )
        assert pulse.existing_weeks(ledger) == {"2026-W29", "2026-W30"}

    def test_missing_file(self, tmp_path: Path) -> None:
        assert pulse.existing_weeks(tmp_path / "nope.csv") == set()


# ---------------------------------------------------------------------------
# Config sourcing — scaffold contract mirrored from budget_burn
# ---------------------------------------------------------------------------
class TestConfigSourcing:
    def test_defaults_when_no_config(self) -> None:
        assert pulse.GAP_MINUTES == pulse_defaults.GAP_MINUTES
        assert pulse.DOMAIN_RULES == pulse_defaults.DOMAIN_RULES

    def test_config_override_and_bad_type(self) -> None:
        fake = SimpleNamespace(GAP_MINUTES=30)
        sys.modules["pulse_config"] = fake  # type: ignore[assignment]
        try:
            importlib.reload(pulse)
            assert pulse.GAP_MINUTES == 30
            sys.modules["pulse_config"] = SimpleNamespace(  # type: ignore
                GAP_MINUTES="fast"
            )
            # Reload redefines PulseConfigError before raising it, so the
            # pre-reload class object would never match — catch the stable
            # builtin parent instead.
            with pytest.raises(RuntimeError, match="GAP_MINUTES"):
                importlib.reload(pulse)
        finally:
            del sys.modules["pulse_config"]
            importlib.reload(pulse)


# ---------------------------------------------------------------------------
# scan — end-to-end over fixture roots (no vault git; fail-open)
# ---------------------------------------------------------------------------
class TestScan:
    def test_rows_over_fixture_roots(self, tmp_path: Path) -> None:
        claude_root = tmp_path / "claude"
        claude_root.mkdir()
        _claude_fixture(claude_root)
        codex_root = tmp_path / "codex"
        _codex_rollout(
            codex_root / "2026/07/22/rollout-a.jsonl",
            cwd="/Users/x/Developer/GitHub/graphmark",
            originator="Codex Desktop",
            source="vscode",
            base="2026-07-22",
        )
        repos_root = tmp_path / "repos"
        _afk_fixture(repos_root)
        vault_root = tmp_path / "vault"
        (vault_root / "perf").mkdir(parents=True)
        (vault_root / "perf" / "Brag Doc.md").write_text(
            "- **2026-07-22 — Win.** x\n"
        )
        rows = pulse.scan(
            projects_root=claude_root,
            codex_root=codex_root,
            repos_root=repos_root,
            vault_root=vault_root,
            week_keys=["2026-W29", "2026-W30"],
            tz=TZ,
        )
        w30 = rows["2026-W30"]
        # Claude interactive events 18:00→18:10:05 cluster = 10m05s;
        # codex desktop 18:00→18:05 and 18:30 clusters = 5m + 0.
        # Union across tools (same wall clock): [18:00-18:10:05] ∪ [18:00-18:05]
        # ∪ [18:30-18:30] = 10m05s → 0.17h.
        assert w30["attn_total_h"] == "0.17"
        assert w30["attn_build_h"] == "0.17"  # graphmark → build
        assert w30["claude_sessions"] == "1"
        assert w30["codex_sessions"] == "1"
        # tokens: claude 8600 + codex 2500 = 11100 → 0.01 M
        assert w30["tokens_m"] == "0.01"
        assert w30["afk_merged"] == "2"
        assert w30["wins"] == "1"
        # W29 precedes every collector's earliest record, so its columns stay
        # BLANK — a pruned-source week is not a measured-zero week.
        w29 = rows["2026-W29"]
        assert "attn_total_h" not in w29
        assert "afk_merged" not in w29
        assert w29["wins"] == "0"  # Brag Doc is never pruned: a real zero

    def test_a_quiet_week_inside_coverage_is_a_real_zero(
        self, tmp_path: Path
    ) -> None:
        """The distinction the ledger lives on: a week with no sessions but
        live sources is a measured zero (the school signal), while a week
        whose transcripts were pruned is blank."""
        claude_root = tmp_path / "claude"
        claude_root.mkdir()
        _claude_fixture(claude_root)  # events in 2026-W30
        rows = pulse.scan(
            projects_root=claude_root,
            codex_root=tmp_path / "codex",
            repos_root=tmp_path / "repos",
            vault_root=tmp_path / "vault",
            week_keys=["2026-W20", "2026-W29", "2026-W30", "2026-W31"],
            tz=TZ,
        )
        # After the newest record the collector demonstrably ran, so an empty
        # week is a measured zero — this is the shape the school signal takes.
        assert rows["2026-W31"]["attn_total_h"] == "0.00"
        # Below the earliest record, pruned and quiet are indistinguishable:
        # claim nothing rather than invent a zero.
        assert "attn_total_h" not in rows["2026-W20"]
        assert "attn_total_h" not in rows["2026-W29"]

    def test_scan_survives_missing_everything(self, tmp_path: Path) -> None:
        rows = pulse.scan(
            projects_root=tmp_path / "a",
            codex_root=tmp_path / "b",
            repos_root=tmp_path / "c",
            vault_root=tmp_path / "d",
            week_keys=["2026-W30"],
            tz=TZ,
        )
        # No sources at all: the row exists but claims nothing.
        assert "attn_total_h" not in rows["2026-W30"]
        assert rows["2026-W30"]["wins"] == "0"


class TestCoveredWeeks:
    WINDOW = [f"2026-W{n:02d}" for n in range(20, 31)]

    def test_pruned_history_is_not_covered(self) -> None:
        # Nothing is claimed below the earliest record: whether W28 was quiet
        # or simply pruned is unknowable, so it gets no zero.
        got = pulse._covered_weeks({"2026-W29", "2026-W30"}, self.WINDOW)
        assert got == {"2026-W29", "2026-W30"}

    def test_short_gap_stays_covered(self) -> None:
        got = pulse._covered_weeks({"2026-W26", "2026-W28", "2026-W30"}, self.WINDOW)
        assert {"2026-W27", "2026-W29"} <= got

    def test_lone_ancient_record_does_not_cover_the_gap(self) -> None:
        got = pulse._covered_weeks({"2026-W20", "2026-W30"}, self.WINDOW)
        assert "2026-W20" not in got
        assert "2026-W21" not in got

    def test_weeks_after_newest_record_are_covered(self) -> None:
        got = pulse._covered_weeks({"2026-W25"}, self.WINDOW)
        assert {"2026-W29", "2026-W30"} <= got

    def test_no_records(self) -> None:
        assert pulse._covered_weeks(set(), self.WINDOW) == set()


# ---------------------------------------------------------------------------
# CLI smoke — the engine runs headless as a script
# ---------------------------------------------------------------------------
class TestCli:
    def _run(self, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "pulse.py"),
                "--vault-root", str(tmp_path),
                "--projects-root", str(tmp_path / "none"),
                "--codex-root", str(tmp_path / "none2"),
                "--repos-root", str(tmp_path / "none3"),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_backfill_never_rewrites_an_existing_row(self, tmp_path: Path) -> None:
        """The failure this guards: transcripts get pruned, so recomputing an
        old week yields zeros — a backfill that overwrites destroys the very
        baseline the ledger exists to hold."""
        (tmp_path / ".vault-context").write_text("personal\n")
        ledger = tmp_path / "perf" / "metrics" / "pulse-personal.csv"
        ledger.parent.mkdir(parents=True)
        old_week = pulse._last_week_keys(
            datetime.now(TZ).date(), pulse.RECOMPUTE_WEEKS + 5
        )[0]
        with ledger.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=pulse.LEDGER_COLUMNS)
            w.writeheader()
            row = {c: "" for c in pulse.LEDGER_COLUMNS}
            row.update(
                {
                    "week": old_week,
                    "machine": "personal",
                    "attn_total_h": "21.50",
                    "claude_sessions": "14",
                }
            )
            w.writerow(row)
        out = self._run(tmp_path, "--backfill", "--no-vault-git")
        assert out.returncode == 0, out.stderr
        rows = {r["week"]: r for r in csv.DictReader(ledger.open())}
        assert rows[old_week]["attn_total_h"] == "21.50"
        assert rows[old_week]["claude_sessions"] == "14"
        assert "backfill skipped" in out.stderr

    def test_git_collector_failure_preserves_prior_columns(
        self, tmp_path: Path
    ) -> None:
        """A failed git read must not read as 'a quiet week' — zeros there
        would look exactly like the output crash the ledger is watching for."""
        (tmp_path / ".vault-context").write_text("personal\n")
        ledger = tmp_path / "perf" / "metrics" / "pulse-personal.csv"
        ledger.parent.mkdir(parents=True)
        week = pulse._last_week_keys(datetime.now(TZ).date(), 1)[0]
        with ledger.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=pulse.LEDGER_COLUMNS)
            w.writeheader()
            row = {c: "" for c in pulse.LEDGER_COLUMNS}
            row.update(
                {
                    "week": week,
                    "machine": "personal",
                    "vault_sessions_personal": "7",
                    "deliberate_commits_personal": "5",
                }
            )
            w.writerow(row)
        # tmp_path is not a git repo, so the collector fails.
        out = self._run(tmp_path, "--weeks", "1")
        assert out.returncode == 0, out.stderr
        rows = {r["week"]: r for r in csv.DictReader(ledger.open())}
        assert rows[week]["vault_sessions_personal"] == "7"
        assert rows[week]["deliberate_commits_personal"] == "5"
        assert "git collector failed" in out.stderr

    def test_backfill_writes_no_row_for_evidence_free_weeks(
        self, tmp_path: Path
    ) -> None:
        """Weeks predating every source must be ABSENT, not zero: 50-odd zero
        rows would drag a rolling median and invent a collapse."""
        (tmp_path / ".vault-context").write_text("personal\n")
        out = self._run(tmp_path, "--backfill", "--no-vault-git")
        assert out.returncode == 0, out.stderr
        ledger = tmp_path / "perf" / "metrics" / "pulse-personal.csv"
        rows = list(csv.DictReader(ledger.open()))
        assert rows == []
        assert "no surviving evidence" in out.stderr

    def test_weeks_zero_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / ".vault-context").write_text("personal\n")
        out = self._run(tmp_path, "--weeks", "0", "--no-vault-git")
        assert out.returncode == 2
        assert "must be >= 1" in out.stderr

    def test_json_mode_runs(self, tmp_path: Path) -> None:
        (tmp_path / ".vault-context").write_text("personal\n")
        out = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "pulse.py"),
                "--json",
                "--weeks", "2",
                "--vault-root", str(tmp_path),
                "--projects-root", str(tmp_path / "none"),
                "--codex-root", str(tmp_path / "none2"),
                "--repos-root", str(tmp_path / "none3"),
                "--no-vault-git",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        payload = json.loads(out.stdout)
        assert payload["machine"] == "personal"
        assert len(payload["rows"]) == 2
        ledger = tmp_path / "perf" / "metrics" / "pulse-personal.csv"
        assert ledger.exists()
