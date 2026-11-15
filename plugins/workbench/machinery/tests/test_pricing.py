"""Tests for pricing, the only place the engine turns token counts into dollars.

The expected prices below are typed in from the spec's table, independently of
``pricing_defaults.py``, so a wrong default shows up as a failing row here.
Each row is priced with a round token count per component and compared to the
spec price times that count over 1,000,000.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import pricing

M = 1_000_000
TOL = 1e-12

# key, input, output, write 5m, write 1h, cache read, fast multiplier
SPEC_ROWS = [
    ("claude-fable-5-2", 8, 40, 10, 16, 0.20, 2),
    ("claude-mythos-5-2", 8, 40, 10, 16, 0.20, 2),
    ("claude-fable-5-1", 10, 50, 12.50, 20, 0.25, None),
    ("claude-mythos-5-1", 10, 50, 12.50, 20, 0.25, None),
    ("claude-fable-5", 10, 50, 12.50, 20, 1, None),
    ("claude-mythos-5", 10, 50, 12.50, 20, 1, None),
    ("claude-opus-5-5", 4, 20, 5, 8, 0.20, 2),
    ("claude-opus-5", 5, 25, 6.25, 10, 0.50, 2),
    ("claude-opus-4-8", 5, 25, 6.25, 10, 0.50, 2),
    ("claude-opus-4-7", 5, 25, 6.25, 10, 0.50, None),
    ("claude-opus-4-6", 5, 25, 6.25, 10, 0.50, None),
    ("claude-opus-4-5", 5, 25, 6.25, 10, 0.50, None),
    ("claude-opus-4-1", 15, 75, 18.75, 30, 1.50, None),
    ("claude-opus-4", 15, 75, 18.75, 30, 1.50, None),
    ("claude-sonnet-5-5", 2, 10, 2.50, 4, 0.10, None),
    ("claude-sonnet-5", 2, 10, 2.50, 4, 0.20, None),
    ("claude-sonnet-4-6", 3, 15, 3.75, 6, 0.30, None),
    ("claude-sonnet-4-5", 3, 15, 3.75, 6, 0.30, None),
    ("claude-sonnet-4", 3, 15, 3.75, 6, 0.30, None),
    ("claude-haiku-5-5", 0.10, 0.50, 0.125, 0.20, 0.01, None),
    ("claude-haiku-4-5", 1, 5, 1.25, 2, 0.10, None),
]
SPEC_KEYS = [r[0] for r in SPEC_ROWS]


def mk(model="claude-opus-4-8", i=0, o=0, cr=0, w5=0, w1=0, speed=None, tot=None):
    return SimpleNamespace(
        model=model,
        input_tokens=i,
        output_tokens=o,
        cache_read_tokens=cr,
        cache_write_5m_tokens=w5,
        cache_write_1h_tokens=w1,
        cache_write_tokens=w5 + w1 if tot is None else tot,
        speed=speed,
    )


def close(a: float, b: float) -> bool:
    return abs(a - b) <= TOL


# ---------------------------------------------------------------------------
# P1, P2: the table, one component at a time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("row", SPEC_ROWS, ids=SPEC_KEYS)
def test_default_row_prices_each_component_exactly(row) -> None:
    # 20,000 tokens of each component keeps the prompt (80,000) under the
    # haiku 5.5 long-prompt threshold, so the standard row is the one priced.
    key, p_in, p_out, p_w5, p_w1, p_cr, _fast = row
    n = 20_000
    r = pricing.price_call(mk(key, i=n, o=n, cr=n, w5=n, w1=n))
    assert r.priced is True
    assert r.table_key == key
    assert r.reason is None
    assert close(r.input_usd, n * p_in / M)
    assert close(r.output_usd, n * p_out / M)
    assert close(r.cache_read_usd, n * p_cr / M)
    assert close(r.write_5m_usd, n * p_w5 / M)
    assert close(r.write_1h_usd, n * p_w1 / M)
    assert close(r.total_usd, n * (p_in + p_out + p_cr + p_w5 + p_w1) / M)


@pytest.mark.parametrize("row", SPEC_ROWS, ids=SPEC_KEYS)
def test_default_row_fast_multiplier(row) -> None:
    key, p_in, *_rest, fast = row
    r = pricing.price_call(mk(key, i=20_000, speed="fast"))
    if fast is None:
        assert r.priced is False
    else:
        assert close(r.input_usd, 20_000 * p_in * fast / M)


def test_default_table_has_exactly_the_spec_keys() -> None:
    assert sorted(pricing.DEFAULT_MODEL_PRICES) == sorted(SPEC_KEYS)


def test_components_scale_linearly_with_tokens() -> None:
    r = pricing.price_call(mk("claude-sonnet-4-5", i=250_000, o=100_000, cr=500_000, w5=200_000, w1=40_000))
    assert close(r.input_usd, 0.75)
    assert close(r.output_usd, 1.5)
    assert close(r.cache_read_usd, 0.15)
    assert close(r.write_5m_usd, 0.75)
    assert close(r.write_1h_usd, 0.24)


def test_one_hour_write_is_not_a_multiple_of_input() -> None:
    # 1h price is its own column: opus 5-5 input 4, 1h write 8, not 2x or 1.6x.
    r = pricing.price_call(mk("claude-opus-5-5", w1=M))
    assert r.write_1h_usd == 8.0
    assert r.write_5m_usd == 0.0


# ---------------------------------------------------------------------------
# P3: model resolution
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "model, key",
    [
        ("claude-opus-4-5-20251101", "claude-opus-4-5"),
        ("claude-opus-4-20250514", "claude-opus-4"),
        ("claude-opus-4-1-20250805", "claude-opus-4-1"),
        ("CLAUDE-OPUS-4-5", "claude-opus-4-5"),
        ("claude-opus-4-5@20251101", "claude-opus-4-5"),
        ("claude-opus-4-5@1", "claude-opus-4-5"),
        ("claude-opus-4-8[1m]", "claude-opus-4-8"),
        ("claude-sonnet-4-5-20250929[1m]", "claude-sonnet-4-5"),
        ("anthropic.claude-opus-4-5-20251101", "claude-opus-4-5"),
        ("us.anthropic.claude-sonnet-4-5", "claude-sonnet-4-5"),
        ("claude-opus-5", "claude-opus-5"),
        ("claude-opus-5-5", "claude-opus-5-5"),
        ("claude-haiku-4-5-20251001", "claude-haiku-4-5"),
    ],
)
def test_model_resolves_to_longest_key_with_allowed_suffix(model, key) -> None:
    assert pricing.price_call(mk(model, i=1)).table_key == key


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-5-6",  # must not fall back to claude-opus-5
        "claude-opus-4-9",
        "claude-opus-4-5-2025",  # not 8 digits
        "claude-opus-4-5-202511011",  # 9 digits
        "claude-opus-4-5-latest",
        "claude-opus-4-5x",
        "claude-opus-4-5@abc",
        "claude-opus-4-5[1m",
        "claude-opus-4-5[1m]x",
        "claude-opus-4-5@20251101[1m]",
        "claude-opus",
        "claude-3-5-sonnet-20241022",
        "gpt-4o",
        "<synthetic>",
        "",
        None,
        123,
        ["claude-opus-4-5"],
    ],
)
def test_model_with_other_remainder_is_unpriced(model) -> None:
    r = pricing.price_call(mk(model, i=M))
    assert r.priced is False
    assert r.table_key is None
    assert r.total_usd == 0.0
    assert r.input_usd == 0.0
    assert isinstance(r.reason, str) and r.reason


def test_unpriced_reasons_differ_for_missing_and_unknown_models() -> None:
    assert pricing.price_call(mk(None, i=1)).reason != pricing.price_call(mk("gpt-4o", i=1)).reason


# ---------------------------------------------------------------------------
# P4: long-prompt rows
# ---------------------------------------------------------------------------
HAIKU = "claude-haiku-5-5"


def test_haiku_5_5_exactly_100000_prompt_uses_standard_row() -> None:
    r = pricing.price_call(mk(HAIKU, i=40_000, cr=50_000, w5=5_000, w1=5_000))
    assert close(r.input_usd, 40_000 * 0.10 / M)
    assert close(r.cache_read_usd, 50_000 * 0.01 / M)
    assert close(r.write_5m_usd, 5_000 * 0.125 / M)
    assert close(r.write_1h_usd, 5_000 * 0.20 / M)


def test_haiku_5_5_over_100000_prompt_uses_long_row_for_every_component() -> None:
    r = pricing.price_call(mk(HAIKU, i=40_000, o=1_000, cr=50_000, w5=5_000, w1=5_001))
    assert close(r.input_usd, 40_000 * 0.50 / M)
    assert close(r.output_usd, 1_000 * 2.50 / M)
    assert close(r.cache_read_usd, 50_000 * 0.05 / M)
    assert close(r.write_5m_usd, 5_000 * 0.625 / M)
    assert close(r.write_1h_usd, 5_001 * 1.0 / M)


def test_long_prompt_counts_all_three_input_kinds_and_not_output() -> None:
    # 99,999 prompt tokens plus a huge output stays standard.
    standard = pricing.price_call(mk(HAIKU, i=99_999, o=500_000))
    assert close(standard.input_usd, 99_999 * 0.10 / M)
    assert close(standard.output_usd, 500_000 * 0.50 / M)
    # cache reads alone can push a call over.
    over = pricing.price_call(mk(HAIKU, cr=100_001))
    assert close(over.cache_read_usd, 100_001 * 0.05 / M)
    # cache writes alone can too.
    over_w = pricing.price_call(mk(HAIKU, w1=100_001))
    assert close(over_w.write_1h_usd, 100_001 * 1.0 / M)


def test_long_prompt_is_modelled_in_the_row_not_by_model_name() -> None:
    table = pricing.merge_table(
        {
            "my-model": {
                "input": 1,
                "output": 2,
                "write_5m": 3,
                "write_1h": 4,
                "cache_read": 5,
                "long_prompt_threshold": 10,
                "long_prompt": {"input": 10, "output": 20, "write_5m": 30, "write_1h": 40, "cache_read": 50},
            }
        }
    )
    short = pricing.price_call(mk("my-model", i=10), table)
    long_ = pricing.price_call(mk("my-model", i=11), table)
    assert close(short.input_usd, 10 * 1 / M)
    assert close(long_.input_usd, 11 * 10 / M)


# ---------------------------------------------------------------------------
# P5: fast mode
# ---------------------------------------------------------------------------
def test_fast_multiplies_every_component_by_the_row_multiplier() -> None:
    r = pricing.price_call(mk("claude-opus-5-5", i=M, o=M, cr=M, w5=M, w1=M, speed="fast"))
    assert close(r.input_usd, 8)
    assert close(r.output_usd, 40)
    assert close(r.cache_read_usd, 0.4)
    assert close(r.write_5m_usd, 10)
    assert close(r.write_1h_usd, 16)
    assert close(r.total_usd, 2 * (4 + 20 + 0.2 + 5 + 8))


def test_fast_on_a_row_without_a_multiplier_is_unpriced_with_a_reason() -> None:
    r = pricing.price_call(mk("claude-opus-4-5", i=M, speed="fast"))
    assert r.priced is False
    assert r.total_usd == 0.0
    assert "fast" in r.reason
    assert r.table_key == "claude-opus-4-5"


@pytest.mark.parametrize("speed", [None, "standard", "slow", "FAST", "", 1, True])
def test_any_other_speed_is_standard(speed) -> None:
    r = pricing.price_call(mk("claude-opus-5-5", i=M, speed=speed))
    assert r.priced is True
    assert close(r.input_usd, 4)


def test_speed_absent_from_the_record_is_standard() -> None:
    c = mk("claude-opus-5-5", i=M)
    del c.speed
    assert close(pricing.price_call(c).input_usd, 4)


def test_fast_applies_to_the_long_prompt_row_too() -> None:
    table = pricing.merge_table(
        {
            "m": {
                "input": 1, "output": 1, "write_5m": 1, "write_1h": 1, "cache_read": 1,
                "fast_multiplier": 3,
                "long_prompt_threshold": 5,
                "long_prompt": {"input": 7, "output": 7, "write_5m": 7, "write_1h": 7, "cache_read": 7},
            }
        }
    )
    assert close(pricing.price_call(mk("m", i=10, speed="fast"), table).input_usd, 10 * 7 * 3 / M)


# ---------------------------------------------------------------------------
# P6: unpriced accounting
# ---------------------------------------------------------------------------
def test_all_zero_call_costs_nothing_and_is_never_unpriced() -> None:
    for model in ("<synthetic>", None, "", "gpt-4o", "claude-opus-4-5"):
        r = pricing.price_call(mk(model))
        assert r.total_usd == 0.0
        assert r.priced is True
    pricer = pricing.Pricer()
    pricer.price(mk("<synthetic>"))
    assert pricer.unpriced() == []


def test_zero_tokens_with_fast_on_unsupported_row_is_not_unpriced() -> None:
    pricer = pricing.Pricer()
    pricer.price(mk("claude-opus-4-5", speed="fast"))
    assert pricer.unpriced() == []


def test_pricer_lists_unpriced_models_with_counts_and_tokens() -> None:
    pricer = pricing.Pricer()
    pricer.price(mk("mystery-9", i=10, o=20, cr=30, w5=40, w1=50))
    pricer.price(mk("mystery-9", i=1, o=2, cr=3, w5=4, w1=5))
    pricer.price(mk("claude-opus-5-6", i=7))
    pricer.price(mk("claude-opus-4-5", i=9, speed="fast"))
    pricer.price(mk("claude-opus-4-8", i=M))  # priced: not listed
    rows = pricer.unpriced()
    by = {(r["model"], r["reason"]): r for r in rows}
    assert len(rows) == 3
    mystery = next(r for r in rows if r["model"] == "mystery-9")
    assert mystery["calls"] == 2
    assert mystery["tokens"] == {
        "input": 11,
        "output": 22,
        "cache_read": 33,
        "write_5m": 44,
        "write_1h": 55,
    }
    assert {r["model"] for r in rows} == {"mystery-9", "claude-opus-5-6", "claude-opus-4-5"}
    fast = next(r for r in rows if r["model"] == "claude-opus-4-5")
    assert "fast" in fast["reason"] and fast["calls"] == 1
    assert len(by) == 3
    for r in rows:
        assert set(r) == {"model", "reason", "calls", "tokens"}


def test_pricer_returns_the_priced_result_and_json_serialisable_rows() -> None:
    import json

    pricer = pricing.Pricer()
    r = pricer.price(mk("claude-opus-4-8", i=M))
    assert r.input_usd == 5.0
    pricer.price(mk(None, i=1))
    json.dumps(pricer.unpriced())


def test_pricer_uses_the_table_it_was_given() -> None:
    table = pricing.merge_table({"mystery-9": _row(input=3)})
    pricer = pricing.Pricer(table)
    assert pricer.price(mk("mystery-9", i=M)).input_usd == 3.0
    assert pricer.unpriced() == []


# ---------------------------------------------------------------------------
# P7: override merge and validation
# ---------------------------------------------------------------------------
def _row(**kw):
    row = {"input": 1, "output": 2, "write_5m": 3, "write_1h": 4, "cache_read": 5}
    row.update(kw)
    return row


def test_merge_with_nothing_is_the_default_table() -> None:
    assert pricing.merge_table(None) == pricing.DEFAULT_MODEL_PRICES
    assert pricing.merge_table({}) == pricing.DEFAULT_MODEL_PRICES


def test_override_replaces_one_key_keeps_others_and_adds_new() -> None:
    table = pricing.merge_table({"claude-opus-4-8": _row(), "brand-new": _row(input=9)})
    assert pricing.price_call(mk("claude-opus-4-8", i=M), table).input_usd == 1.0
    # replaced row has no fast multiplier: it is replaced, not merged field-wise
    assert pricing.price_call(mk("claude-opus-4-8", i=1, speed="fast"), table).priced is False
    assert pricing.price_call(mk("claude-sonnet-4-5", i=M), table).input_usd == 3.0
    assert pricing.price_call(mk("brand-new-20260101", i=M), table).input_usd == 9.0
    assert sorted(table) == sorted([*SPEC_KEYS, "brand-new"])


def test_merge_does_not_mutate_the_defaults() -> None:
    before = {k: dict(v) for k, v in pricing.DEFAULT_MODEL_PRICES.items()}
    pricing.merge_table({"claude-opus-4-8": _row()})
    assert pricing.DEFAULT_MODEL_PRICES == before


@pytest.mark.parametrize(
    "bad",
    [
        "not a dict",
        {"k": "not a row"},
        {"k": {"input": 1}},  # missing components
        {"k": _row(input="1")},
        {"k": _row(input=-1)},
        {"k": _row(output=True)},
        {"k": _row(cache_read=float("nan"))},
        {"k": _row(fast_multiplier=0)},
        {"k": _row(fast_multiplier="2")},
        {"k": _row(long_prompt_threshold=10)},  # threshold without rates
        {"k": _row(long_prompt={"input": 1, "output": 1, "write_5m": 1, "write_1h": 1, "cache_read": 1})},
        {"k": _row(long_prompt_threshold=-1, long_prompt={"input": 1, "output": 1, "write_5m": 1, "write_1h": 1, "cache_read": 1})},
        {"k": _row(long_prompt_threshold=10, long_prompt={"input": 1})},
        {1: _row()},
    ],
)
def test_malformed_override_raises_price_table_error(bad) -> None:
    with pytest.raises(pricing.PriceTableError):
        pricing.merge_table(bad)


def test_price_table_error_names_the_offending_key() -> None:
    with pytest.raises(pricing.PriceTableError, match="my-key"):
        pricing.merge_table({"my-key": {"input": 1}})


# ---------------------------------------------------------------------------
# P8: deprecated config names
# ---------------------------------------------------------------------------
def test_deprecated_config_names_reports_rates_only_when_defined() -> None:
    assert pricing.deprecated_config_names(None) == []
    assert pricing.deprecated_config_names(SimpleNamespace()) == []
    assert pricing.deprecated_config_names(SimpleNamespace(MODEL_PRICES={})) == []
    assert pricing.deprecated_config_names(SimpleNamespace(RATES={"opus": (1.0, 2.0)})) == ["RATES"]


def test_engine_has_no_tier_price_table() -> None:
    import budget_burn
    import budget_burn_defaults

    assert not hasattr(budget_burn, "RATES")
    assert not hasattr(budget_burn_defaults, "RATES")
    assert not hasattr(pricing, "RATES")


def test_pricing_is_pure_and_imports_nothing_from_the_instruments() -> None:
    text = (ENGINE_DIR / "pricing.py").read_text(encoding="utf-8")
    for name in ("budget_burn", "context_spend", "transcript_reader"):
        assert f"import {name}" not in text
        assert f"from {name}" not in text


# ---------------------------------------------------------------------------
# source cited
# ---------------------------------------------------------------------------
def test_module_docstring_cites_the_price_sources_and_date() -> None:
    doc = pricing.__doc__ or ""
    assert "https://platform.claude.com/docs/en/about-claude/pricing" in doc
    assert "https://platform.claude.com/docs/en/build-with-claude/fast-mode" in doc
    assert "2026-11-14" in doc


# ---------------------------------------------------------------------------
# review fixes: conserved writes, prompt length from the larger figure, invalid counts
# ---------------------------------------------------------------------------
def test_prompt_length_uses_total_cache_write_when_split_under_sums() -> None:
    # 200,000 written tokens with a split that names only 2 of them: the prompt
    # is over 100,000, so the long row applies to every component.
    r = pricing.price_call(mk(HAIKU, i=1, w5=1, w1=1, tot=200_000))
    assert close(r.input_usd, 1 * 0.50 / M)
    assert close(r.write_5m_usd, (1 + 199_998) * 0.625 / M)
    assert close(r.write_1h_usd, 1 * 1.0 / M)


def test_unsplit_write_shortfall_is_priced_at_five_minute_rate() -> None:
    r = pricing.price_call(mk("claude-opus-4-8", w5=10, w1=20, tot=1_000_030))
    assert close(r.write_5m_usd, (10 + 1_000_000) * 6.25 / M)
    assert close(r.write_1h_usd, 20 * 10 / M)
    assert close(r.total_usd, r.write_5m_usd + r.write_1h_usd)


@pytest.mark.parametrize(
    "bad", [True, 1.5, "100", -5, float("nan"), None], ids=repr
)
@pytest.mark.parametrize(
    "field",
    ["input_tokens", "cache_write_5m_tokens", "cache_write_tokens"],
)
def test_invalid_token_count_makes_call_unpriced_and_listed(bad, field) -> None:
    call = mk("claude-opus-4-8", o=1_000_000)
    setattr(call, field, bad)
    r = pricing.price_call(call)
    assert r.priced is False
    assert r.total_usd == 0.0
    assert "invalid token count" in r.reason
    assert field in r.reason
    pricer = pricing.Pricer()
    pricer.price(call)
    (row,) = pricer.unpriced()
    assert row["calls"] == 1
    assert "invalid token count" in row["reason"]


def test_valid_all_zero_call_still_not_listed() -> None:
    pricer = pricing.Pricer()
    r = pricer.price(mk("<synthetic>"))
    assert r.priced is True and r.total_usd == 0.0
    # a missing attribute is a zero, not an invalid count
    r2 = pricer.price(SimpleNamespace(model="claude-opus-4-8"))
    assert r2.priced is True and r2.total_usd == 0.0
    assert pricer.unpriced() == []
