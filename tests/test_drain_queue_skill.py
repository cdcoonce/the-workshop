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
    lowered = bullet.lower()
    # "pass needs a fresh reader's BUILD" is the only pass the bullet may name;
    # "then set the pass label" or "then proceed to step 2" goes red here.
    assert lowered.count("pass") == 1, bullet
    for phrase in ("proceed", "step 2"):
        assert phrase not in lowered, f"REWRITE bullet says {phrase!r}"


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


def test_template_read_allowlist_admits_probe_builds() -> None:
    """The ONLY-to allowlist is the old ban's shape: dropping probe builds
    from it re-forbids them however the rest of the template reads."""
    template = _template()
    start = template.index("ONLY to")
    sentence = template[start : template.index(".", start)]
    assert "probe builds" in sentence, sentence


def test_template_sets_the_rewrite_label_the_skill_relies_on() -> None:
    """SKILL.md step 1 says applied text leaves the issue at cold-read:rewrite;
    the reader is the one who sets it."""
    template = _template()
    assert "cold-read:rewrite on REWRITE" in template


def test_template_keeps_the_code_archaeology_ban() -> None:
    template = _template()
    assert "code archaeology" in template
    assert "IS a finding" in template


def test_reading_the_result_dispatches_a_fresh_reader_before_step_2() -> None:
    section = _reading_the_result()
    assert "fresh reader" in section
    assert "before step 2" in section


def _step_text(start_marker: str, end_marker: str) -> str:
    flat = _flat(SKILL.read_text())
    start = flat.index(start_marker)
    return flat[start : flat.index(end_marker, start)]


def test_step_1_routes_hand_built_issues_to_the_cold_read_tier() -> None:
    """A hand-built issue's test-strength-only findings arrive as a must-kill
    list, not as a REWRITE, from read 2 on."""
    step = _step_text("**1. Gate the spec cold.**", "**2. Dispatch one worker")
    for phrase in (
        "the issue body opens with ``Build path: hand-built under the `drain-queue` skill``",
        "Hand-built slices tier applies",
        "from read 2 on",
        "a test does not grade a stated rule, measured or not,",
        "must-kill list for the worker and the independent teeth pass, not as a REWRITE",
    ):
        assert phrase in step, f"step 1 lacks {phrase!r}"
    assert "header says" not in step


def test_step_3_requires_an_independent_teeth_pass_for_hand_built_slices() -> None:
    step = _step_text("**3. Review the diff yourself.**", "**4. Land and tear down.**")
    for phrase in (
        "**Independent teeth pass (hand-built tier).**",
        "every slice gated under that tier, whether or not a finding was downgraded",
        "a worker other than the builder",
        "`detector-teeth-check`",
        "the gate's must-kill list",
        "The pass worker only reports",
        "The conductor or another worker closes the gaps and re-runs the surviving mutants",
        "does not land while a must-kill mutant is neither killed nor explained",
        "`explained` means the conductor accepts the explanation",
        "ledger and the gaps closed",
        "afk#1520 (PR #1593) and afk#1548 (PR #1594)",
    ):
        assert phrase in step, f"step 3 lacks {phrase!r}"
    # After the specialist pre-reads, which say "before you start the manual review".
    assert step.index("Independent teeth pass") > step.index(
        "**Specialist pre-reads.**"
    )
    assert step.index("Independent teeth pass") > step.index("Worked dispatch (a diff")


def test_teeth_evidence_iron_rule_still_stands_beside_the_independent_pass() -> None:
    flat = _flat(SKILL.read_text())
    assert "Every pull request carries teeth evidence" in flat


def test_queue_ledger_rows_carry_the_tier_and_the_independent_pass() -> None:
    flat = _flat(SKILL.read_text())
    assert (
        "issue, pull request, cold-read verdict, tier, teeth evidence, "
        "the independent teeth pass result, and outcome"
    ) in flat


def test_reading_the_result_regrades_hand_built_findings() -> None:
    section = _reading_the_result()
    assert (
        "On a hand-built slice from read 2 on, the conductor re-grades the reader's "
        "findings under `vault-cold-read`'s Hand-built slices tier, then edits the "
        "verdict comment and ledger line, corrects the label, and stamps if the "
        "result is BUILD."
    ) in section
