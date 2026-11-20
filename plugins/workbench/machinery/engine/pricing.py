#!/usr/bin/env python3
"""pricing — the only place the engine turns token counts into dollars.

``price_call`` takes one call record (the ``transcript_reader.Call``, read
duck-typed) and returns a ``PricedCall``: dollars for fresh input, output,
cache read, 5-minute cache write and 1-hour cache write, separately, plus their
total. Each component is that call's token count times that model's own price
for that component, divided by 1,000,000. Nothing is derived from a multiplier
on input at pricing time.

The default table (``pricing_defaults.DEFAULT_MODEL_PRICES``) holds absolute USD
prices per million tokens, keyed by model, from Anthropic's published pricing
page https://platform.claude.com/docs/en/about-claude/pricing and, for the
fast-mode multiplier, https://platform.claude.com/docs/en/build-with-claude/fast-mode,
checked 2026-11-14. A machine overrides it per key with ``MODEL_PRICES`` in its
``budget_burn_config.py`` (``merge_table``).

Model ids resolve to the longest table key that is a prefix of the (lower-cased,
``anthropic.``-stripped) id and whose remainder is empty, a ``-YYYYMMDD`` date
(optionally followed by a bracketed suffix such as ``[1m]``), ``@`` plus digits,
or a bracketed suffix alone. Anything else is unpriced: ``claude-opus-5-6`` is
not ``claude-opus-5``.

Unpriced calls contribute no dollars. ``Pricer`` prices calls against one table
and keeps the list of what it could not price, so every caller reports the same
thing. A call whose token counts are all zero costs nothing and is never
unpriced.

Spec amendment P4a: prompt length is input plus cache read plus the larger of the
total cache-write count and the 5-minute plus 1-hour split, write tokens the
split does not name are priced at the 5-minute rate, and a token count that is
not a non-negative int makes the call unpriced (a missing count is 0).

Stdlib only; imports nothing else from the engine but its defaults.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pricing_defaults import DEFAULT_MODEL_PRICES

# Config names that used to drive dollars and now do nothing.
DEPRECATED_CONFIG_NAMES: tuple[str, ...] = ("RATES",)

_COMPONENTS = ("input", "output", "write_5m", "write_1h", "cache_read")
_SUFFIX = re.compile(r"(?:-\d{8}(?:\[[^\]]*\])?|@\d+|\[[^\]]*\])?")
_PER = 1_000_000


class PriceTableError(ValueError):
    """A price table (or one row of it) is not in the documented shape."""


@dataclass(frozen=True)
class PricedCall:
    """The priced result for one call. Dollars are 0.0 when not priced."""

    input_usd: float
    output_usd: float
    cache_read_usd: float
    write_5m_usd: float
    write_1h_usd: float
    total_usd: float
    priced: bool
    table_key: str | None
    reason: str | None = None
    # USD per million tokens actually applied (after the long-prompt row and the
    # fast multiplier), keyed like a table row; None when not priced.
    rates: dict | None = None


# ---------------------------------------------------------------------------
# table
# ---------------------------------------------------------------------------
def _number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _check_rates(key: str, where: str, rates: object) -> None:
    if not isinstance(rates, dict):
        raise PriceTableError(f"{key}: {where} must be a dict, got {type(rates).__name__}")
    for name in _COMPONENTS:
        if name not in rates:
            raise PriceTableError(f"{key}: {where} is missing {name!r}")
        value = rates[name]
        if not _number(value) or value < 0:
            raise PriceTableError(
                f"{key}: {where} {name!r} must be a non-negative number, got {value!r}"
            )


def _check_row(key: object, row: object) -> None:
    if not isinstance(key, str) or not key:
        raise PriceTableError(f"price table key must be a non-empty string, got {key!r}")
    _check_rates(key, "row", row)
    fast = row.get("fast_multiplier")
    if fast is not None and (not _number(fast) or fast <= 0):
        raise PriceTableError(f"{key}: 'fast_multiplier' must be a positive number, got {fast!r}")
    has_threshold = row.get("long_prompt_threshold") is not None
    has_long = row.get("long_prompt") is not None
    if has_threshold != has_long:
        raise PriceTableError(
            f"{key}: 'long_prompt_threshold' and 'long_prompt' go together"
        )
    if has_threshold:
        threshold = row["long_prompt_threshold"]
        if not _number(threshold) or threshold < 0:
            raise PriceTableError(
                f"{key}: 'long_prompt_threshold' must be a non-negative number, got {threshold!r}"
            )
        _check_rates(key, "long_prompt", row["long_prompt"])


def merge_table(overrides: object = None) -> dict[str, dict]:
    """The default table with ``overrides`` merged per key over it.

    An overridden key replaces its whole row, other rows remain, a new key adds
    a row. Raises ``PriceTableError`` for an override that is not a dict of
    well-formed rows. The defaults are never mutated.
    """
    table = {k: dict(v) for k, v in DEFAULT_MODEL_PRICES.items()}
    if overrides is None:
        return table
    if not isinstance(overrides, dict):
        raise PriceTableError(
            f"MODEL_PRICES must be a dict of model key to price row, got {type(overrides).__name__}"
        )
    for key, row in overrides.items():
        _check_row(key, row)
        table[key] = dict(row)
    return table


def deprecated_config_names(config: object) -> list[str]:
    """Deprecated names a config module still defines (they no longer act)."""
    if config is None:
        return []
    return [n for n in DEPRECATED_CONFIG_NAMES if getattr(config, n, None) is not None]


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------
def _resolve(model: object, table: dict[str, dict]) -> str | None:
    if not isinstance(model, str) or not model:
        return None
    ident = model.lower()
    if "anthropic." in ident:
        ident = ident.split("anthropic.", 1)[1]
    for key in sorted(table, key=len, reverse=True):
        if ident.startswith(key) and _SUFFIX.fullmatch(ident[len(key) :]):
            return key
    return None


def _tokens(call: object, name: str) -> int:
    value = getattr(call, name, 0)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


_COUNT_ATTRS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_5m_tokens",
    "cache_write_1h_tokens",
    "cache_write_tokens",
)


def _invalid_counts(call: object) -> list[str]:
    """Names of count attributes present on the call that are not non-negative ints."""
    bad = []
    for name in _COUNT_ATTRS:
        if not hasattr(call, name):
            continue
        value = getattr(call, name)
        if not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
            bad.append(name)
    return bad


def _total_write(call: object, counts: dict[str, int]) -> int:
    """Total cache-write tokens: the call's own total, else the split's sum."""
    split = counts["write_5m"] + counts["write_1h"]
    return max(_tokens(call, "cache_write_tokens"), split)


def _counts(call: object) -> dict[str, int]:
    return {
        "input": _tokens(call, "input_tokens"),
        "output": _tokens(call, "output_tokens"),
        "cache_read": _tokens(call, "cache_read_tokens"),
        "write_5m": _tokens(call, "cache_write_5m_tokens"),
        "write_1h": _tokens(call, "cache_write_1h_tokens"),
    }


def _unpriced(key: str | None, reason: str) -> PricedCall:
    return PricedCall(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, key, reason)


def price_call(call: object, table: dict[str, dict] | None = None) -> PricedCall:
    """Price one call. ``table`` defaults to the shipped table."""
    if table is None:
        table = DEFAULT_MODEL_PRICES
    counts = _counts(call)
    model = getattr(call, "model", None)
    key = _resolve(model, table)
    invalid = _invalid_counts(call)
    if invalid:
        return _unpriced(key, f"invalid token count in {', '.join(invalid)}")
    if not any(counts.values()):
        return PricedCall(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, True, key)
    if key is None:
        if not isinstance(model, str) or not model:
            return _unpriced(None, "no model recorded")
        return _unpriced(None, f"model {model!r} is not in the price table")
    row = table[key]
    rates = row
    threshold = row.get("long_prompt_threshold")
    if threshold is not None:
        prompt = counts["input"] + counts["cache_read"] + _total_write(call, counts)
        if prompt > threshold:
            rates = row["long_prompt"]
    factor = 1
    if getattr(call, "speed", None) == "fast":
        factor = row.get("fast_multiplier")
        if factor is None:
            return _unpriced(key, f"fast mode has no price for {key}")
    shortfall = _total_write(call, counts) - counts["write_5m"] - counts["write_1h"]
    counts = {**counts, "write_5m": counts["write_5m"] + shortfall}
    applied = {name: rates[name] * factor for name in _COMPONENTS}
    usd = {name: counts[name] * rates[name] / _PER * factor for name in _COMPONENTS}
    total = sum(usd.values())
    return PricedCall(
        input_usd=usd["input"],
        output_usd=usd["output"],
        cache_read_usd=usd["cache_read"],
        write_5m_usd=usd["write_5m"],
        write_1h_usd=usd["write_1h"],
        total_usd=total,
        priced=True,
        table_key=key,
        rates=applied,
    )


class Pricer:
    """Prices calls against one table and tallies the ones it could not price."""

    def __init__(self, table: dict[str, dict] | None = None) -> None:
        self.table = table if table is not None else DEFAULT_MODEL_PRICES
        self._unpriced: dict[tuple, dict] = {}

    def price(self, call: object) -> PricedCall:
        result = price_call(call, self.table)
        if not result.priced:
            model = getattr(call, "model", None)
            if not isinstance(model, str):
                model = None
            row = self._unpriced.setdefault(
                (model, result.reason),
                {
                    "model": model,
                    "reason": result.reason,
                    "calls": 0,
                    "tokens": {name: 0 for name in _COMPONENTS},
                },
            )
            row["calls"] += 1
            counts = _counts(call)
            counts["write_5m"] += _total_write(call, counts) - counts["write_5m"] - counts["write_1h"]
            for name, n in counts.items():
                row["tokens"][name] += n
        return result

    def unpriced(self) -> list[dict]:
        """Unpriced calls grouped by model and reason, sorted for stable output."""
        rows = sorted(
            self._unpriced.values(), key=lambda r: (r["model"] or "", r["reason"] or "")
        )
        return [{**r, "tokens": dict(r["tokens"])} for r in rows]
