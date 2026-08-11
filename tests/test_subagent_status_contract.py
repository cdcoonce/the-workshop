"""Doc-consistency tests for the subagent status vocabulary (issue #282).

Mirrors the docstring-vs-wiring cross-validation style in test_build_docs.py:
static assertions over doc text, not runtime behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBAGENT_DOC = REPO_ROOT / "plugins" / "workbench" / "docs" / "subagent-development.md"
PARALLEL_AGENTS_DOC = REPO_ROOT / "plugins" / "workbench" / "docs" / "parallel-agents.md"
PHASE_TRANSITIONS_DOC = (
    REPO_ROOT / "plugins" / "workbench" / "skills" / "dev-cycle" / "references" / "phase-transitions.md"
)
TDD_IMPLEMENTER_AGENT = REPO_ROOT / "plugins" / "workbench" / "agents" / "tdd-implementer" / "AGENT.md"

STATUS_TOKENS = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT")

# Worker dispatch prompt templates in subagent-development.md that must carry
# the REQUIRED "STATUS:" final line. Identified by a marker string unique to
# each template block.
DISPATCH_TEMPLATE_MARKERS = (
    "Task tool (general-purpose):",
    "Fix issues from code review:",
)


def _fenced_code_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:[^\n]*)\n(.*?)```", text, flags=re.DOTALL)


class TestStatusVocabulary:
    def test_all_four_status_tokens_present(self) -> None:
        text = SUBAGENT_DOC.read_text(encoding="utf-8")
        for token in STATUS_TOKENS:
            assert token in text, f"missing status token: {token}"

    def test_dispatch_templates_carry_required_status_line(self) -> None:
        text = SUBAGENT_DOC.read_text(encoding="utf-8")
        blocks = _fenced_code_blocks(text)
        for marker in DISPATCH_TEMPLATE_MARKERS:
            matching = [b for b in blocks if marker in b]
            assert matching, f"no dispatch template found for marker: {marker}"
            for block in matching:
                assert "STATUS:" in block, (
                    f"dispatch template for {marker!r} is missing the "
                    "REQUIRED 'STATUS:' final line"
                )

    def test_controller_playbook_and_escalation_ladder_present(self) -> None:
        text = SUBAGENT_DOC.read_text(encoding="utf-8")
        assert "Controller Playbook" in text
        assert "Escalation Ladder" in text
        assert "escalate to the human" in text.lower()

    def test_bad_work_is_worse_than_no_work_sanctioned(self) -> None:
        text = SUBAGENT_DOC.read_text(encoding="utf-8")
        assert "Bad work is worse than no work" in text
        assert "not be penalized for reporting" in text

    def test_reply_length_cap_documented(self) -> None:
        text = SUBAGENT_DOC.read_text(encoding="utf-8")
        assert "15 line" in text


class TestCrossReferences:
    def test_parallel_agents_points_at_status_contract(self) -> None:
        text = PARALLEL_AGENTS_DOC.read_text(encoding="utf-8")
        assert "subagent-development.md" in text
        for token in STATUS_TOKENS:
            assert token in text

    def test_phase_transitions_derives_pass_fail_from_status_line(self) -> None:
        text = PHASE_TRANSITIONS_DOC.read_text(encoding="utf-8")
        assert "STATUS" in text
        assert "subagent-development.md" in text

    def test_tdd_implementer_reporting_aligned_to_enum(self) -> None:
        text = TDD_IMPLEMENTER_AGENT.read_text(encoding="utf-8")
        for token in STATUS_TOKENS:
            assert token in text, (
                f"missing status token in tdd-implementer AGENT.md: {token}"
            )
