"""Shipped default project aliases and monthly budget.

Managed tier: upgrade owns this file. It is the fallback only — the values a
vault actually bills against live in the owner's ``budget_burn_config.py``
(optional; an owner copies this file out and drops the ``_defaults`` suffix).
budget_burn prefers that config and
falls back here for any name it does not define, so a vault vendored before the
config existed still reports its burn.

Prices are not here: the per-model default table is ``pricing_defaults.py``.
A vault overrides it by defining ``MODEL_PRICES`` in its own
``budget_burn_config.py`` (a dict of table key to price row, merged per key over
the defaults; row shape in ``pricing_defaults``). The old tier-keyed ``RATES``
no longer affects any dollar figure and is reported if still defined.
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

MONTHLY_BUDGET = 350.0
