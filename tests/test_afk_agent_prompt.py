"""Guards the afk agent_prompt for a scope-discipline guardrail (#258).

The AFK executor quarantined 60 slices as `other` — diffs broad enough that
the classifier could not map them to gate/review/build-crash/setup-crash/
no-op. The recurring cause is the agent broadening a diff into unrelated
files while chasing an unclear root cause. This pins a guardrail sentence in
.afk/config.toml's agent_prompt instructing the agent to stop and record its
analysis in .afk/question.md instead, so the rule can't be silently dropped.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_agent_prompt_tells_agent_to_stop_on_unclear_root_cause() -> None:
    config = (REPO_ROOT / ".afk" / "config.toml").read_text()
    assert "record your analysis in .afk/question.md" in config, (
        ".afk/config.toml agent_prompt must instruct the agent to stop and "
        "record its analysis in .afk/question.md when a root cause is "
        "unclear, instead of broadening the diff into unrelated files — "
        "unexplained multi-file diffs are what the classifier lands in the "
        "`other` bucket"
    )
