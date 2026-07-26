"""Shipped default project aliases, price table, and monthly budget.

Managed tier: upgrade owns this file. It is the fallback only — the values a
vault actually bills against live in the scaffold-rendered
``budget_burn_config.py`` (``scaffold/budget_burn_config.py.tmpl``), which init
writes once and upgrade never touches. budget_burn prefers that config and
falls back here for any name it does not define, so a vault vendored before the
config existed still reports its burn.
"""

from __future__ import annotations

# Renamed project dirs re-key their ~/.claude/projects/ transcript folder,
# splitting one real project across two keys. Map legacy keys to current so
# by_project attribution stays whole (totals are already rename-safe via the
# global requestId dedup in budget_burn.scan).
PROJECT_ALIASES: dict[str, str] = {
    "-Users-cdcoonce-Developer-GitHub-my-brain": (
        "-Users-cdcoonce-Developer-GitHub-the-vault"
    ),
    "-Users-cdcoonce-Developer-GitHub-claude-workflow": (
        "-Users-cdcoonce-Developer-GitHub-the-workshop"
    ),
}

# Per-1M-token USD rates (input, output). Cache read = 0.1x input; cache write
# (5-min TTL) = 1.25x input. Source: claude-api pricing 2026-06-16.
RATES: dict[str, tuple[float, float]] = {
    "fable": (10.0, 50.0),
    "opus": (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}

MONTHLY_BUDGET = 350.0
