"""Guards that every subagent dispatch template names a required Model slot (#285).

No dispatch template in this repo named a model, so every subagent silently
inherited the orchestrator's model — typically the most capable and most
expensive tier — exactly where the heaviest loops are dispatch-intensive
(improve-skill, design-an-interface, dev-cycle). These guards fail loudly if a
`model` slot is ever dropped from a dispatch template, or if the tier rubric
disappears from `agent-matching.md`, so the gap can't silently reopen.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DISPATCH_SITES = [
    "core/docs/subagent-development.md",
    "core/docs/parallel-agents.md",
    "core/skills/dev-cycle/references/phase-transitions.md",
    "presets/workshop-maintainer/skills/improve-skill/references/phase-3-baseline.md",
    "core/skills/design-an-interface/SKILL.md",
]


def test_every_dispatch_site_requires_a_model_slot() -> None:
    for relative_path in DISPATCH_SITES:
        text = (REPO_ROOT / relative_path).read_text()
        assert "model" in text.lower(), (
            f"{relative_path} must name a required `model` slot at its "
            "dispatch site — an omitted model silently inherits the "
            "orchestrator's model"
        )
        assert "required" in text.lower(), (
            f"{relative_path} must mark the model slot as required, not optional"
        )


def test_agent_matching_documents_model_selection() -> None:
    text = (REPO_ROOT / "core/docs/agent-matching.md").read_text()
    assert "## Model Selection" in text, (
        "agent-matching.md must have a Model Selection section documenting "
        "the role-to-tier rubric"
    )
    for tier in ("cheapest", "mid", "frontier"):
        assert tier in text, (
            f"agent-matching.md Model Selection section must use the "
            f"'{tier}' tier name in its normative vocabulary"
        )
    assert "reviewer" in text.lower() and "mid" in text, (
        "agent-matching.md must document the reviewer floor at mid tier"
    )
    assert "turn" in text.lower(), (
        "agent-matching.md must document the turn-count-beats-token-price rule"
    )
