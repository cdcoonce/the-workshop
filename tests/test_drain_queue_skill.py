"""Contract for `drain-queue`'s cold-read step (#1039).

drain-queue runs its own cold reader, so it inherits the two holes #1037
closed in `vault-cold-read`: applied replacement text must not clear the gate
without a fresh read, and the reader must be allowed the probe builds that
settle empirical questions by running them. The rest of the rewrite loop, and
the probe-build method itself, stay owned by `vault-cold-read`; these pins
check that drain-queue defers to it and names only its own exceptions.
String pins cannot see paraphrase, so the value checks below pin what the
REWRITE bullet must never say, and review covers the rest.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "plugins" / "workbench" / "skills" / "drain-queue"
SKILL = SKILL_DIR / "SKILL.md"
COLD_READER = SKILL_DIR / "references" / "cold-reader.md"


def _flat(text: str) -> str:
    """Collapse whitespace so phrase pins survive formatter re-wrapping."""
    return " ".join(text.split())


def _skill_files() -> list[Path]:
    files = sorted(p for p in SKILL_DIR.rglob("*") if p.is_file())
    assert files, f"no files under {SKILL_DIR}"
    return files


def _rewrite_bullet() -> str:
    """Step 1's REWRITE bullet: from `**REWRITE**` to `**NOT-DISPATCH-READY**`."""
    flat = _flat(SKILL.read_text())
    start = flat.index("**REWRITE**")
    end = flat.index("**NOT-DISPATCH-READY**", start)
    return flat[start:end]


def _template() -> str:
    """The fenced text template under `## Template`, flattened."""
    text = COLD_READER.read_text()
    start = text.index("```text", text.index("## Template"))
    end = text.index("\n```", start + len("```text"))
    return _flat(text[start:end])


def _reading_the_result() -> str:
    text = COLD_READER.read_text()
    start = text.index("## Reading the result")
    end = text.find("\n## ", start + 1)
    return _flat(text[start : end if end != -1 else len(text)])


def test_old_rewrite_and_probe_bans_are_gone() -> None:
    """Rewrite text must not clear the gate unread, and nothing may forbid
    the probe builds that produced about half of ragmark's findings."""
    for path in _skill_files():
        flat = _flat(path.read_text())
        lowered = flat.lower()
        for phrase in (
            "then re-state BUILD",
            "Do not fix code and do not propose implementations",
            "Read-only on code",
            "Do NOT edit files",
        ):
            assert phrase not in flat, f"{path.name} still says {phrase!r}"
            assert phrase.lower() not in lowered, f"{path.name} still says {phrase!r}"


def test_rewrite_bullet_needs_a_fresh_build_on_the_exact_body() -> None:
    bullet = _rewrite_bullet()
    assert "leaves the issue at cold-read:rewrite" in bullet
    assert "a fresh reader's BUILD on that exact body" in bullet


def test_rewrite_bullet_has_no_second_path_to_build_or_pass() -> None:
    """The fresh reader's BUILD is the only BUILD the bullet may name: a
    bullet that also says "then treat the verdict as BUILD" goes red here."""
    bullet = _rewrite_bullet()
    assert bullet.count("BUILD") == 1, bullet
    assert "cold-read:pass" not in bullet


def test_rewrite_bullet_defers_the_loop_to_vault_cold_read_step_8() -> None:
    bullet = _rewrite_bullet()
    assert "vault-cold-read" in bullet
    assert "step 8" in bullet
    assert "lacks the label" in bullet and "verdict comment" in bullet


def test_template_admits_probe_builds_by_reference() -> None:
    template = _template()
    for phrase in (
        "vault-cold-read/references/command.md",
        "Probe builds",
        "instruments, not proposals",
    ):
        assert phrase in template, f"cold-reader template lacks {phrase!r}"


def test_template_names_drain_queue_exceptions_to_probe_builds() -> None:
    """Probe builds' afk fork-point rule, executor contract and detectors
    9 and 11 are false for drain-queue; each exception must be stated."""
    template = _template()
    for phrase in (
        "integration branch pinned in step zero",
        "executor-contract bullet does not apply",
        "detector-3 mutation",
        "detector-8 probe",
    ):
        assert phrase in template, f"cold-reader template lacks {phrase!r}"


def test_template_keeps_the_code_archaeology_ban() -> None:
    template = _template()
    assert "code archaeology" in template
    assert "IS a finding" in template


def test_reading_the_result_dispatches_a_fresh_reader_before_step_2() -> None:
    section = _reading_the_result()
    assert "fresh reader" in section
    assert "before step 2" in section
