"""Shipped default model price table.

Managed tier: upgrade owns this file. ``pricing`` merges a vault's own
``MODEL_PRICES`` (in the scaffold-owned ``budget_burn_config.py``) over it, key
by key, so a vault that re-prices one model keeps the rest. It sits beside
``budget_burn_defaults.py`` the same way: managed defaults here, per-machine
override in the config.

USD per million tokens, from Anthropic's published pricing page
https://platform.claude.com/docs/en/about-claude/pricing and, for the fast-mode
multiplier, https://platform.claude.com/docs/en/build-with-claude/fast-mode,
checked 2026-11-14.

Row shape (every price is USD per million tokens)::

    {"input": ..., "output": ..., "write_5m": ..., "write_1h": ...,
     "cache_read": ...,
     "fast_multiplier": 2,                  # optional; absent = no fast mode
     "long_prompt_threshold": 100_000,      # optional, with long_prompt
     "long_prompt": {"input": ..., ...}}    # optional alternate five prices

A call whose prompt (input + cache read + all cache-write tokens) is strictly
over ``long_prompt_threshold`` uses the ``long_prompt`` prices for every
component.
"""

from __future__ import annotations


def _row(
    price_in: float,
    price_out: float,
    write_5m: float,
    write_1h: float,
    cache_read: float,
    fast: float | None = None,
) -> dict:
    row: dict = {
        "input": price_in,
        "output": price_out,
        "write_5m": write_5m,
        "write_1h": write_1h,
        "cache_read": cache_read,
    }
    if fast is not None:
        row["fast_multiplier"] = fast
    return row


DEFAULT_MODEL_PRICES: dict[str, dict] = {
    "claude-fable-5-2": _row(8, 40, 10, 16, 0.2, fast=2),
    "claude-mythos-5-2": _row(8, 40, 10, 16, 0.2, fast=2),
    "claude-fable-5-1": _row(10, 50, 12.5, 20, 0.25),
    "claude-mythos-5-1": _row(10, 50, 12.5, 20, 0.25),
    "claude-fable-5": _row(10, 50, 12.5, 20, 1),
    "claude-mythos-5": _row(10, 50, 12.5, 20, 1),
    "claude-opus-5-5": _row(4, 20, 5, 8, 0.2, fast=2),
    "claude-opus-5": _row(5, 25, 6.25, 10, 0.5, fast=2),
    "claude-opus-4-8": _row(5, 25, 6.25, 10, 0.5, fast=2),
    "claude-opus-4-7": _row(5, 25, 6.25, 10, 0.5),
    "claude-opus-4-6": _row(5, 25, 6.25, 10, 0.5),
    "claude-opus-4-5": _row(5, 25, 6.25, 10, 0.5),
    "claude-opus-4-1": _row(15, 75, 18.75, 30, 1.5),
    "claude-opus-4": _row(15, 75, 18.75, 30, 1.5),
    "claude-sonnet-5-5": _row(2, 10, 2.5, 4, 0.1),
    "claude-sonnet-5": _row(2, 10, 2.5, 4, 0.2),
    "claude-sonnet-4-6": _row(3, 15, 3.75, 6, 0.3),
    "claude-sonnet-4-5": _row(3, 15, 3.75, 6, 0.3),
    "claude-sonnet-4": _row(3, 15, 3.75, 6, 0.3),
    "claude-haiku-4-5": _row(1, 5, 1.25, 2, 0.1),
    # Haiku 5.5 bills a prompt over 100,000 tokens at the higher row.
    "claude-haiku-5-5": {
        **_row(0.10, 0.50, 0.125, 0.20, 0.01),
        "long_prompt_threshold": 100_000,
        "long_prompt": {
            "input": 0.50,
            "output": 2.50,
            "write_5m": 0.625,
            "write_1h": 1.0,
            "cache_read": 0.05,
        },
    },
}
