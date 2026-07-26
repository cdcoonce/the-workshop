"""Shipped defaults for pulse — the weekly work-quantification ledger.

Instance-tunable values (scaffold-owned ``pulse_config.py`` overrides these,
same contract as ``budget_burn_config.py``): the attention gap threshold, the
recompute window, the project→domain map, and the commit-classification
patterns. They change with new repos and new habits, not with engine releases.
"""

from __future__ import annotations

# Silence longer than this (minutes) closes an attention block. The absolute
# hours move with this dial; week-over-week trends barely do. Keep it stable —
# changing it mid-series makes old and new rows incomparable.
GAP_MINUTES = 15

# How many trailing ISO weeks a default run recomputes. Rows older than the
# window are FROZEN: their sources (Claude transcripts especially) get pruned,
# so recomputing them would silently shrink history.
RECOMPUTE_WEEKS = 10

# How far back --backfill looks. Backfill is FILL-ONLY: it adds rows for
# weeks the ledger doesn't have yet and never rewrites an existing row, so a
# larger window is safe but weeks with no surviving evidence stay absent.
BACKFILL_WEEKS = 60

# Matched against a SCOPE — "repo/dir/subdir", not just a repo name — so a
# directory inside a repo can carry its own domain. First match wins, which
# is why the school rules come first: coursework lives inside the vault, and
# a repo-level match would book those hours to "vault", inflating the number
# whose decline the ledger exists to detect.
# Domains: vault (second-brain ops), build (personal engineering),
# home (household software), school (the master's program), other.
DOMAIN_RULES: tuple[tuple[str, str], ...] = (
    # School first — these win wherever they appear in a path.
    ("school", "school"),
    ("coursework", "school"),
    ("asu", "school"),
    ("cse5", "school"),  # CSE 511 Data Processing at Scale, CSE 575, ...
    ("hse5", "school"),  # HSE 542 Foundations of Human Systems Engineering
    ("dse5", "school"),
    ("the-vault", "vault"),
    ("my-brain", "vault"),
    ("second-brain", "vault"),
    ("afk", "build"),
    ("the-workshop", "build"),
    ("claude-workflow", "build"),
    ("graphmark", "build"),
    ("orbit-wars", "build"),
    ("homebase", "build"),
    ("PortfolioWebsite", "build"),
    ("oura-pipeline", "build"),
    ("statehood-timeline", "build"),
    ("Weather_Adjusted", "build"),
    ("household", "home"),
    ("housing-commute", "home"),
    ("school", "school"),
    ("masters", "school"),
)

# Vault git author email → machine. First substring match wins; everything
# else is the personal machine (GitHub noreply, web-UI commits).
AUTHOR_MACHINE_RULES: tuple[tuple[str, str], ...] = (
    ("clearwayenergy.com", "work"),
)

# The Stop-hook sync commit — counted as a session-activity proxy, never as
# deliberate work.
AUTOSYNC_PREFIX = "vault: auto-sync session changes"

# Commit subjects excluded from the deliberate-commit count (mechanical
# traffic). Wrap-up harvests are NOT here on purpose: they are human-directed
# session output.
AUTOMATION_SUBJECT_PATTERNS: tuple[str, ...] = (
    r"^Merge ",
    r"^AFK:",
    r"^chore\(afk-cockpit\): refresh",
    r"^chore\(dashboard\): refresh",
    r"^chore\(release\):",
)
