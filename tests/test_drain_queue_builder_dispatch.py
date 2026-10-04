"""Hard lines in the drain-queue worker dispatch prompt (issue #1110).

Builder subagents never see auto-memory, so every trap a past build hit must
be a line in the prompt the worker is handed: a gate piped through ``tail``
loses its exit code, parallel gates flake a Docker test, a red test and its
fix squashed into one commit cannot prove failing-first, and a field read from
a file another tool writes crashed two read-APIs that every builder gate passed.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCH_MD = (
    REPO_ROOT
    / "plugins"
    / "workbench"
    / "skills"
    / "drain-queue"
    / "references"
    / "builder-dispatch.md"
)


def _text() -> str:
    return " ".join(DISPATCH_MD.read_text(encoding="utf-8").lower().split())


def test_gate_is_never_piped_through_tail_or_head() -> None:
    """A pipe replaces the gate's exit code with the pager's."""
    text = _text()
    assert "echo rc=$?" in text, "gate must be run with its rc captured to a log"
    assert "pipefail" in text
    assert "never pipe" in text and "tail" in text


def test_parallel_docker_flake_rule() -> None:
    """A lone Docker failure in a parallel run is rerun once; the solo gate rules."""
    text = _text()
    assert "rerun a lone docker failure once" in text
    assert "run alone by the conductor" in text and "authority" in text


def test_red_test_and_fix_are_separate_commits() -> None:
    """Failing-first is only provable from history."""
    text = _text()
    assert "red test and the fix as separate commits" in text
    assert "failing-first" in text


def test_foreign_file_fields_are_untrusted() -> None:
    """Every field of a tool-written file is untrusted input."""
    text = _text()
    assert "another tool writes" in text and "untrusted" in text
    assert "isinstance" in text
    assert 'errors="replace"' in text
    assert "non-finite" in text


def test_golden_fixture_is_derived_by_someone_else() -> None:
    """A builder-generated golden mirrors the implementation."""
    text = _text()
    assert "golden fixture" in text
    assert "other than its builder" in text
    assert "derivation" in text and "recorded" in text
    assert "mirror" in text and "detector-teeth-check" in text
