"""Tests for budget_burn — the cost math behind the API spend meter (issue #57).

Covers the tier/price lookup, per-record cost arithmetic (exact numbers
computed by hand from RATES), scan's dedup-by-requestId behavior (a duplicated
transcript record for one API call must be counted once), and the _pace helper
(normal/over-pace pacing, non-leap February day count, and day-1 projection).

Also covers sourcing project aliases, the price table, and the monthly budget
from the scaffold-owned ``budget_burn_config.py`` (issue #429): a vault
without that config falls back to the shipped ``budget_burn_defaults`` rather
than to empty aliases or a zero budget, a config that defines an unusable
value raises a clear error naming the config path, and a project not covered
by any configured alias keeps its own key rather than being silently folded
into another project.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

import budget_burn
import budget_burn_defaults
from budget_burn import RATES, _pace, _record_cost, _tier, scan


# ---------------------------------------------------------------------------
# _tier — model id → rate tier
# ---------------------------------------------------------------------------
class TestTier:
    def test_known_tiers(self) -> None:
        assert _tier("claude-opus-4-20250514") == "opus"
        assert _tier("claude-3-5-sonnet-20241022") == "sonnet"
        assert _tier("claude-3-5-haiku-20241022") == "haiku"
        assert _tier("claude-fable-1") == "fable"

    def test_case_insensitive(self) -> None:
        assert _tier("CLAUDE-OPUS-4") == "opus"

    def test_unknown_model_returns_none(self) -> None:
        assert _tier("gpt-4o") is None
        assert _tier("some-synthetic-model") is None

    def test_empty_string_returns_none(self) -> None:
        assert _tier("") is None

    def test_none_returns_none(self) -> None:
        # _tier guards falsy input before lowercasing.
        assert _tier(None) is None


# ---------------------------------------------------------------------------
# _record_cost — exact arithmetic from RATES
# ---------------------------------------------------------------------------
class TestRecordCost:
    def test_opus_input_output(self) -> None:
        # opus rates = (5.0, 25.0). 1M input + 1M output:
        # (1e6*5 + 1e6*25) / 1e6 = 30.0
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
        assert _record_cost(usage, "opus") == 30.0

    def test_cache_read_is_tenth_of_input(self) -> None:
        # cache_read costs rate_in * 0.1. opus rate_in=5.0 → 0.5/1M.
        # 1M cache_read: 1e6 * 0.5 / 1e6 = 0.5
        usage = {"cache_read_input_tokens": 1_000_000}
        assert _record_cost(usage, "opus") == 0.5

    def test_cache_write_is_1_25x_input(self) -> None:
        # cache_write costs rate_in * 1.25. opus rate_in=5.0 → 6.25/1M.
        # 1M cache_write: 1e6 * 6.25 / 1e6 = 6.25
        usage = {"cache_creation_input_tokens": 1_000_000}
        assert _record_cost(usage, "opus") == 6.25

    def test_all_four_components_haiku(self) -> None:
        # haiku rates = (1.0, 5.0). 1M of each component:
        # input:       1e6 * 1.0   = 1_000_000
        # output:      1e6 * 5.0   = 5_000_000
        # cache_read:  1e6 * 0.1   =   100_000
        # cache_write: 1e6 * 1.25  = 1_250_000
        # sum = 7_350_000 / 1e6 = 7.35
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
        }
        assert _record_cost(usage, "haiku") == pytest.approx(7.35)

    def test_sonnet_mixed_realistic(self) -> None:
        # sonnet rates = (3.0, 15.0).
        # input 200_000 * 3.0       =   600_000
        # output 50_000 * 15.0      =   750_000
        # cache_read 800_000 * 0.3  =   240_000
        # sum = 1_590_000 / 1e6 = 1.59
        usage = {
            "input_tokens": 200_000,
            "output_tokens": 50_000,
            "cache_read_input_tokens": 800_000,
        }
        assert _record_cost(usage, "sonnet") == pytest.approx(1.59)

    def test_empty_usage_is_zero(self) -> None:
        assert _record_cost({}, "opus") == 0.0

    def test_none_token_values_treated_as_zero(self) -> None:
        # Real transcripts carry explicit null fields; the `or 0` guard handles it.
        usage = {"input_tokens": None, "output_tokens": None}
        assert _record_cost(usage, "opus") == 0.0

    def test_rates_constant_unchanged(self) -> None:
        # Guards the published rates the arithmetic above depends on.
        assert RATES == {
            "fable": (10.0, 50.0),
            "opus": (5.0, 25.0),
            "sonnet": (3.0, 15.0),
            "haiku": (1.0, 5.0),
        }


# ---------------------------------------------------------------------------
# scan — dedup by requestId across transcript records
# ---------------------------------------------------------------------------
def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def _usage_record(
    request_id: str,
    *,
    model: str = "claude-opus-4",
    input_tokens: int = 1_000_000,
    timestamp: str = "2026-06-15T12:00:00Z",
) -> dict:
    return {
        "requestId": request_id,
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": {"input_tokens": input_tokens},
        },
    }


class TestScanDedup:
    def test_duplicate_request_id_counted_once(self, tmp_path: Path) -> None:
        # The SAME API call appears on two transcript lines (streaming chunks).
        # opus input 1M = $5.00, and it must be counted ONCE, not twice.
        project = tmp_path / "proj-a"
        project.mkdir()
        _write_jsonl(
            project / "session.jsonl",
            [_usage_record("req-1"), _usage_record("req-1")],
        )
        result = scan(tmp_path, "2026-06")
        assert result["total"] == 5.0

    def test_distinct_request_ids_both_counted(self, tmp_path: Path) -> None:
        project = tmp_path / "proj-a"
        project.mkdir()
        _write_jsonl(
            project / "session.jsonl",
            [_usage_record("req-1"), _usage_record("req-2")],
        )
        result = scan(tmp_path, "2026-06")
        assert result["total"] == 10.0

    def test_dedup_spans_multiple_transcripts(self, tmp_path: Path) -> None:
        # Same requestId in two different files must still count once.
        (tmp_path / "proj-a").mkdir()
        (tmp_path / "proj-b").mkdir()
        _write_jsonl(tmp_path / "proj-a" / "s.jsonl", [_usage_record("req-1")])
        _write_jsonl(tmp_path / "proj-b" / "s.jsonl", [_usage_record("req-1")])
        result = scan(tmp_path, "2026-06")
        assert result["total"] == 5.0

    def test_falls_back_to_message_id_when_no_request_id(
        self, tmp_path: Path
    ) -> None:
        # No requestId → dedup key is message.id.
        project = tmp_path / "proj-a"
        project.mkdir()
        rec = {
            "timestamp": "2026-06-15T12:00:00Z",
            "message": {
                "id": "msg-abc",
                "model": "claude-opus-4",
                "usage": {"input_tokens": 1_000_000},
            },
        }
        _write_jsonl(project / "s.jsonl", [rec, dict(rec)])
        result = scan(tmp_path, "2026-06")
        assert result["total"] == 5.0

    def test_other_month_excluded(self, tmp_path: Path) -> None:
        project = tmp_path / "proj-a"
        project.mkdir()
        _write_jsonl(
            project / "s.jsonl",
            [
                _usage_record("req-1", timestamp="2026-06-15T12:00:00Z"),
                _usage_record("req-2", timestamp="2026-05-15T12:00:00Z"),
            ],
        )
        result = scan(tmp_path, "2026-06")
        assert result["total"] == 5.0  # only the June record

    def test_unknown_model_skipped(self, tmp_path: Path) -> None:
        project = tmp_path / "proj-a"
        project.mkdir()
        _write_jsonl(
            project / "s.jsonl",
            [_usage_record("req-1", model="gpt-4o")],
        )
        result = scan(tmp_path, "2026-06")
        assert result["total"] == 0.0
        assert result["by_tier"] == {}

    def test_by_tier_breakdown(self, tmp_path: Path) -> None:
        project = tmp_path / "proj-a"
        project.mkdir()
        _write_jsonl(
            project / "s.jsonl",
            [
                _usage_record("req-1", model="claude-opus-4"),  # $5.00
                _usage_record("req-2", model="claude-3-5-haiku"),  # $1.00
            ],
        )
        result = scan(tmp_path, "2026-06")
        assert result["by_tier"] == {"haiku": 1.0, "opus": 5.0}
        assert result["total"] == 6.0

    def test_empty_root_returns_zero(self, tmp_path: Path) -> None:
        result = scan(tmp_path, "2026-06")
        assert result["total"] == 0.0
        assert result["by_tier"] == {}
        assert result["by_project"] == {}
        assert result["by_day"] == {}


# ---------------------------------------------------------------------------
# scan — output precision: by_project and by_day must round like total/by_tier
# (issue #79). cache_read at opus rate (0.5/1M) on 333_333 tokens yields
# 0.1666665 — a long decimal that's visibly wrong if left unrounded.
# ---------------------------------------------------------------------------
class TestScanRounding:
    @staticmethod
    def _long_decimal_record() -> dict:
        # opus cache_read rate = 5.0 * 0.1 = 0.5 /1M tokens.
        # 333_333 * 0.5 / 1e6 = 0.1666665 → rounds to 0.17.
        return {
            "requestId": "req-frac",
            "timestamp": "2026-06-15T12:00:00Z",
            "message": {
                "model": "claude-opus-4",
                "usage": {"cache_read_input_tokens": 333_333},
            },
        }

    def test_by_project_rounded_to_two_decimals(self, tmp_path: Path) -> None:
        project = tmp_path / "proj-a"
        project.mkdir()
        _write_jsonl(project / "s.jsonl", [self._long_decimal_record()])
        result = scan(tmp_path, "2026-06")
        assert result["by_project"]["proj-a"] == 0.17

    def test_by_day_rounded_to_two_decimals(self, tmp_path: Path) -> None:
        project = tmp_path / "proj-a"
        project.mkdir()
        _write_jsonl(project / "s.jsonl", [self._long_decimal_record()])
        result = scan(tmp_path, "2026-06")
        assert result["by_day"]["2026-06-15"] == 0.17


# ---------------------------------------------------------------------------
# _pace — budget pacing helper
# ---------------------------------------------------------------------------
class TestPace:
    def test_normal_midmonth(self) -> None:
        # June 2026 has 30 days. Day 15, budget 300, spent 100.
        # expected = 300 * (15/30) = 150.0
        # delta    = 100 - 150 = -50.0 (under pace)
        # projected= 100 / 15 * 30 = 200.0
        result = _pace(100.0, date(2026, 6, 15), 300.0)
        assert result["days_elapsed"] == 15
        assert result["days_in_month"] == 30
        assert result["expected_to_date"] == 150.0
        assert result["delta"] == -50.0
        assert result["projected_eom"] == 200.0

    def test_over_pace_positive_delta(self) -> None:
        # Day 10 of 30, budget 300 → expected 100. Spent 200 → delta +100 (over).
        result = _pace(200.0, date(2026, 6, 10), 300.0)
        assert result["expected_to_date"] == 100.0
        assert result["delta"] == 100.0

    def test_february_non_leap_day_count(self) -> None:
        # 2026 is not a leap year → February has 28 days.
        result = _pace(0.0, date(2026, 2, 14), 350.0)
        assert result["days_in_month"] == 28

    def test_day_one_projects_full_month(self) -> None:
        # Day 1 of 30: projected = spent / 1 * 30.
        result = _pace(10.0, date(2026, 6, 1), 300.0)
        assert result["days_elapsed"] == 1
        assert result["projected_eom"] == 300.0


# ---------------------------------------------------------------------------
# Scaffold-owned aliases / prices / budget (issue #429)
# ---------------------------------------------------------------------------
@pytest.fixture
def scaffolded_config(tmp_path: Path):
    """Reload budget_burn against a stand-in scaffolded budget_burn_config.

    The real config is scaffold-rendered into the vault's script dir, so the
    seam under test is the module-level import — not the values it resolves
    to. Each call re-executes budget_burn with the given names; teardown
    restores the shipped defaults.
    """

    def _configure(**names: object) -> ModuleType:
        module = ModuleType("budget_burn_config")
        module.__file__ = str(tmp_path / "budget_burn_config.py")
        for name, value in names.items():
            setattr(module, name, value)
        sys.modules["budget_burn_config"] = module
        return importlib.reload(budget_burn)

    yield _configure

    sys.modules.pop("budget_burn_config", None)
    importlib.reload(budget_burn)


class TestShippedDefaults:
    def test_absent_config_uses_shipped_defaults(self) -> None:
        """A vault vendored before the scaffold config exists still bills."""
        assert "budget_burn_config" not in sys.modules
        assert budget_burn.RATES == budget_burn_defaults.RATES
        assert budget_burn.MONTHLY_BUDGET == budget_burn_defaults.MONTHLY_BUDGET
        assert budget_burn._PROJECT_ALIASES == budget_burn_defaults.PROJECT_ALIASES

    def test_defaults_reproduce_the_previously_hardcoded_values(self) -> None:
        # "Default ships today's values": the literals budget_burn carried
        # before they moved out of the engine.
        assert budget_burn_defaults.RATES == {
            "fable": (10.0, 50.0),
            "opus": (5.0, 25.0),
            "sonnet": (3.0, 15.0),
            "haiku": (1.0, 5.0),
        }
        assert budget_burn_defaults.MONTHLY_BUDGET == 350.0
        assert budget_burn_defaults.PROJECT_ALIASES == {
            "-Users-cdcoonce-Developer-GitHub-my-brain": (
                "-Users-cdcoonce-Developer-GitHub-the-vault"
            ),
            "-Users-cdcoonce-Developer-GitHub-claude-workflow": (
                "-Users-cdcoonce-Developer-GitHub-the-workshop"
            ),
        }

    def test_scaffold_template_matches_the_shipped_defaults(self) -> None:
        """A newly scaffolded vault starts from the same values a bare one uses.

        The template and the defaults are hand-maintained separately, so
        without this an update to one alone would leave new vaults billing
        against different prices than existing ones.
        """
        template = SCRIPTS_DIR.parent / "scaffold" / "budget_burn_config.py.tmpl"
        rendered: dict[str, object] = {}
        exec(
            compile(template.read_text(encoding="utf-8"), str(template), "exec"),
            rendered,
        )
        assert rendered["PROJECT_ALIASES"] == budget_burn_defaults.PROJECT_ALIASES
        assert rendered["RATES"] == budget_burn_defaults.RATES
        assert rendered["MONTHLY_BUDGET"] == budget_burn_defaults.MONTHLY_BUDGET


class TestScaffoldedConfig:
    def test_configured_alias_merges_projects(
        self, tmp_path: Path, scaffolded_config
    ) -> None:
        module = scaffolded_config(PROJECT_ALIASES={"legacy-proj": "current-proj"})
        project = tmp_path / "legacy-proj"
        project.mkdir()
        _write_jsonl(project / "s.jsonl", [_usage_record("req-1")])
        result = module.scan(tmp_path, "2026-06")
        assert result["by_project"] == {"current-proj": 5.0}

    def test_configured_price_entry_changes_cost(self, scaffolded_config) -> None:
        module = scaffolded_config(RATES={"opus": (100.0, 200.0)})
        assert module._record_cost({"input_tokens": 1_000_000}, "opus") == 100.0

    def test_configured_budget_reaches_the_report(
        self,
        tmp_path: Path,
        scaffolded_config,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """The budget is only useful if it lands in the pace main() prints."""
        module = scaffolded_config(MONTHLY_BUDGET=42.0)
        assert module.MONTHLY_BUDGET == 42.0
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "budget_burn.py",
                "--json",
                "--context",
                "work",
                "--projects-root",
                str(tmp_path),
            ],
        )

        assert module.main() == 0

        pace = json.loads(capsys.readouterr().out)["pace"]
        assert pace == module._pace(0.0, date.today(), 42.0)

    def test_name_omitted_from_the_config_falls_back_to_the_default(
        self, scaffolded_config
    ) -> None:
        """An owner who only cares about the budget keeps the shipped prices."""
        module = scaffolded_config(MONTHLY_BUDGET=42.0)
        assert module.RATES == budget_burn_defaults.RATES
        assert module._PROJECT_ALIASES == budget_burn_defaults.PROJECT_ALIASES

    def test_unusable_value_raises_an_error_naming_the_config(
        self, tmp_path: Path, scaffolded_config
    ) -> None:
        # BudgetBurnConfigError (a RuntimeError) is rebound by the reload, so
        # match the base class and the name rather than the stale class object.
        with pytest.raises(RuntimeError) as exc_info:
            scaffolded_config(RATES="5 dollars per million")
        assert type(exc_info.value).__name__ == "BudgetBurnConfigError"
        message = str(exc_info.value)
        assert str(tmp_path / "budget_burn_config.py") in message
        assert "RATES" in message

    def test_project_without_a_configured_alias_keeps_its_own_key(
        self, tmp_path: Path, scaffolded_config
    ) -> None:
        # A project directory absent from PROJECT_ALIASES must never be
        # folded into an unrelated project's totals.
        module = scaffolded_config(PROJECT_ALIASES={"legacy-proj": "current-proj"})
        project = tmp_path / "unaliased-proj"
        project.mkdir()
        _write_jsonl(project / "s.jsonl", [_usage_record("req-1")])
        result = module.scan(tmp_path, "2026-06")
        assert result["by_project"] == {"unaliased-proj": 5.0}
