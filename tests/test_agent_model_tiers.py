"""Guards that every AGENT.md carries the #285 role-to-tier rubric as a
declarative `model:` frontmatter key (#851).

Before this change, only 3 of 19 AGENT.md files (brag-spotter, cross-linker,
people-profiler) declared `model:`. The other 16 — all of workbench's
builders/reviewers plus all 6 workshop-maintainer agents — omitted the key,
so any dispatch that didn't pass a model explicitly silently inherited the
orchestrator's own model, typically the most expensive tier, for routine
work.

These guards fail loudly if any agent's `model:` key is ever dropped, or if
its value drifts from the tier the #285 rubric assigns it, so the gap can't
silently reopen. Model values are literal model names (`sonnet` / `opus`),
matching the 3 precedent agents — see
plugins/workbench/docs/agent-matching.md#model-selection for the underlying
`cheapest`/`mid`/`frontier` tier rubric that these literal values encode.
"""

from pathlib import Path

from scripts.smoke_test import _parse_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every AGENT.md under the two plugins this issue covers, mapped to the
# literal `model:` value the #285 rubric assigns it. Builders and routine
# reviewers land on `sonnet` (mid tier); judgment-heavy review (security,
# skill-analyst, strategy) lands on `opus` (frontier tier). No agent on the
# current roster is pure retrieval, so none defaults to `haiku`.
EXPECTED_MODELS = {
    # plugins/workbench/agents/ (13)
    "plugins/workbench/agents/analysis-builder/AGENT.md": "sonnet",
    "plugins/workbench/agents/api-builder/AGENT.md": "sonnet",
    "plugins/workbench/agents/backend-builder/AGENT.md": "sonnet",
    "plugins/workbench/agents/brag-spotter/AGENT.md": "sonnet",
    "plugins/workbench/agents/code-reviewer/AGENT.md": "sonnet",
    "plugins/workbench/agents/cross-linker/AGENT.md": "sonnet",
    "plugins/workbench/agents/data-quality-reviewer/AGENT.md": "sonnet",
    "plugins/workbench/agents/frontend-builder/AGENT.md": "sonnet",
    "plugins/workbench/agents/people-profiler/AGENT.md": "sonnet",
    "plugins/workbench/agents/pipeline-builder/AGENT.md": "sonnet",
    "plugins/workbench/agents/security-reviewer/AGENT.md": "opus",
    "plugins/workbench/agents/tdd-implementer/AGENT.md": "sonnet",
    "plugins/workbench/agents/ux-reviewer/AGENT.md": "sonnet",
    # plugins/workshop-maintainer/agents/ (6)
    "plugins/workshop-maintainer/agents/qa-tester/AGENT.md": "sonnet",
    "plugins/workshop-maintainer/agents/skill-analyst/AGENT.md": "opus",
    "plugins/workshop-maintainer/agents/skill-builder/AGENT.md": "sonnet",
    "plugins/workshop-maintainer/agents/skill-reviewer/AGENT.md": "sonnet",
    "plugins/workshop-maintainer/agents/skill-writer/AGENT.md": "sonnet",
    "plugins/workshop-maintainer/agents/strategy/AGENT.md": "opus",
}


def test_expected_models_covers_exactly_the_19_agent_files() -> None:
    """Guards the fixture itself against drift: exactly 19 AGENT.md files
    exist under the two plugins this issue covers (13 workbench + 6
    workshop-maintainer), and EXPECTED_MODELS names exactly those files —
    no more, no fewer. A new agent added later without updating this test
    fails here instead of silently skipping coverage.
    """
    on_disk = {
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "plugins/workbench/agents").glob("*/AGENT.md")
    } | {
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "plugins/workshop-maintainer/agents").glob(
            "*/AGENT.md"
        )
    }
    assert len(on_disk) == 19, (
        f"expected exactly 19 AGENT.md files across workbench + "
        f"workshop-maintainer, found {len(on_disk)}: {sorted(on_disk)}"
    )
    assert on_disk == set(EXPECTED_MODELS), (
        "EXPECTED_MODELS must name exactly the AGENT.md files on disk; "
        f"missing from fixture: {sorted(on_disk - set(EXPECTED_MODELS))}; "
        f"stale in fixture: {sorted(set(EXPECTED_MODELS) - on_disk)}"
    )


class TestEveryAgentDeclaresAModelKey:
    """All 19 AGENT.md files must carry an explicit `model:` key (AC1)."""

    def test_every_agent_file_carries_a_model_key(self) -> None:
        missing = []
        for relative_path in sorted(EXPECTED_MODELS):
            text = (REPO_ROOT / relative_path).read_text()
            frontmatter = _parse_frontmatter(text)
            if not frontmatter or "model" not in frontmatter:
                missing.append(relative_path)
        assert not missing, (
            "these AGENT.md files are missing an explicit `model:` "
            f"frontmatter key: {missing}"
        )


class TestModelTierMatchesTheRubric:
    """Each agent's `model:` value must match the tier the #285 rubric
    assigns it (AC2) — this also catches an invalid model value (e.g.
    `gpt5`), since any value other than the rubric-assigned tier fails
    the equality check.
    """

    def test_every_agent_model_matches_the_rubric_assignment(self) -> None:
        mismatches = []
        for relative_path, expected_model in sorted(EXPECTED_MODELS.items()):
            text = (REPO_ROOT / relative_path).read_text()
            frontmatter = _parse_frontmatter(text)
            actual_model = (frontmatter or {}).get("model")
            if actual_model != expected_model:
                mismatches.append(
                    f"{relative_path}: expected model={expected_model!r}, "
                    f"got {actual_model!r}"
                )
        assert not mismatches, (
            "these AGENT.md files declare a `model:` value that does not "
            "match the #285 role-to-tier rubric assignment:\n"
            + "\n".join(mismatches)
        )

    def test_model_values_are_literal_names_not_tier_vocabulary(self) -> None:
        # The `cheapest`/`mid`/`frontier` tier vocabulary is scoped to the
        # five dispatch-template call sites (#285), not to AGENT.md
        # frontmatter, which uses literal model names — matching the 3
        # existing precedent agents.
        tier_words = {"cheapest", "mid", "frontier"}
        offenders = []
        for relative_path in sorted(EXPECTED_MODELS):
            text = (REPO_ROOT / relative_path).read_text()
            frontmatter = _parse_frontmatter(text)
            actual_model = (frontmatter or {}).get("model")
            if actual_model in tier_words:
                offenders.append(relative_path)
        assert not offenders, (
            "these AGENT.md files use tier vocabulary "
            f"(cheapest/mid/frontier) instead of a literal model name: "
            f"{offenders}"
        )
