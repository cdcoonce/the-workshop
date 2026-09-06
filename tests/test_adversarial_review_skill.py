"""Ownership and discipline contract for the `adversarial-review` skill.

The capability is attacking finished work: enumerating what the work claims and
trying to disprove each claim, rather than reading it and pronouncing it sound.
That is universal to any repo, so `workbench` is the canonical owner.

Membership is the part worth pinning, and the mechanism changed with the flat
reorg: a plugin ships exactly what is in its own `skills/` directory, so
ownership is the directory it sits in and nothing else declares it. What used to
erode through a second manifest list now erodes through a second directory, so
the check below is a directory sweep rather than a manifest read.

The rest of these tests pin the machinery that makes the skill adversarial rather
than merely another reviewer. A review skill degrades in one direction only: it
reads the work, finds it plausible, and reports a clean bill of health. Each
assertion below guards one of the load-bearing parts that failure routes around.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "adversarial-review"
SKILL_DIR = REPO_ROOT / "plugins" / "workbench" / "skills" / SLUG

SIBLING_REVIEWERS = (
    "plan-ceo-review",
    "security-review",
    "daa-code-review",
    "detector-teeth-check",
)


def _skill_text() -> str:
    return (SKILL_DIR / "SKILL.md").read_text()


def _description() -> str:
    """The frontmatter description — the only thing the router matches on."""
    text = _skill_text()
    assert text.startswith("---"), f"{SLUG}: no frontmatter"
    frontmatter = text.split("---", 2)[1]
    body: list[str] = []
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            body.append(line.split(":", 1)[1].strip())
        elif body and line.startswith((" ", "\t")):
            body.append(line.strip())
        elif body:
            break
    assert body, f"{SLUG}: frontmatter has no description"
    return " ".join(part for part in body if part not in {">", "|"})


def test_skill_is_owned_by_workbench() -> None:
    """Universal capability, so it belongs to the plugin everyone installs."""
    assert (SKILL_DIR / "SKILL.md").is_file()


def test_no_other_plugin_also_ships_it() -> None:
    """One skill, one plugin — a second copy splits the trigger and the edits.

    Under the composition build this was a manifest question: a preset could
    name the skill in `core.skills` and get its own copy. Flat plugins have no
    such list, so the only way to duplicate it now is to put a second directory
    on disk — which is what this sweeps for.
    """
    owners = sorted(
        path.parents[2].name
        for path in REPO_ROOT.glob(f"plugins/*/skills/{SLUG}/SKILL.md")
    )
    assert owners == ["workbench"], (
        f"{SLUG} is shipped by {owners}; it belongs to workbench alone"
    )


def test_skill_md_stays_under_the_line_budget() -> None:
    """Progressive disclosure: the invocation-loaded file stays readable.

    The budget was 100 and the file sat at 99, so the PR-scoped section had no
    room. It was raised rather than paid for by deleting guidance, because the
    guard protects an intent — SKILL.md routes, it does not accumulate — and the
    added section routes: eleven lines that hand the reader to
    `references/pr-lens-review.md`. Raising it to buy room for a section that
    inlined the pattern instead would defeat the guard while still passing it.
    """
    line_count = len(_skill_text().splitlines())
    assert line_count < 115, f"SKILL.md is {line_count} lines"


def test_description_is_trigger_only() -> None:
    """The description is a retrieval index, not a spec. An agent that reads a
    workflow-bearing description executes the lossy summary instead of the body."""
    description = _description()
    assert len(description) < 1024
    assert "use when" in description.lower()
    assert "→" not in description, "description narrates a step chain"
    assert "phase" not in description.lower(), "description leaks phase structure"


def test_every_referenced_file_exists() -> None:
    """A dangling reference link silently drops the part of the skill it points at."""
    text = _skill_text()
    for reference in (SKILL_DIR / "references").glob("*.md"):
        assert reference.name in text, (
            f"{reference.name} exists but SKILL.md never links to it"
        )
    for line in text.splitlines():
        if "references/" not in line:
            continue
        fragment = line.split("references/", 1)[1]
        name = fragment.split(")")[0].split("]")[0].split(" ")[0].split("#")[0]
        assert (SKILL_DIR / "references" / name).is_file(), f"missing references/{name}"


def test_references_are_one_level_deep() -> None:
    """Never nest a references directory inside another."""
    assert not list((SKILL_DIR / "references").glob("*/*"))


def test_carries_the_iron_law_without_a_nuance_clause() -> None:
    """An Iron Law with an exception clause is not a law — every future
    rationalization routes through the clause instead of confronting the law."""
    text = _skill_text()
    law = "NO CLAIM PASSES WITHOUT A DISPROOF ATTEMPT THAT COULD HAVE FAILED IT."
    assert law in text, "the Iron Law is missing or reworded"
    line = next(line for line in text.splitlines() if law in line)
    for hedge in ("unless", "except", "when practical", "if time"):
        assert hedge not in line.lower(), f"Iron Law carries a nuance clause: {hedge!r}"


def test_requires_an_unverified_coverage_section() -> None:
    """The clean-bill-of-health failure. An empty findings list means nothing
    unless the review also states what it could not reach, so the omission has to
    be visible as a blank template slot rather than a silent gap."""
    text = _skill_text().lower()
    assert "could not verify" in text
    assert "required" in text, "the report slots are not marked required"


def test_separates_reproduced_findings_from_argued_ones() -> None:
    """Reasoning promoted to evidence is where AI reviewers generate confident
    noise. A finding without a concrete trigger is capped, not asserted."""
    text = _skill_text().lower()
    assert "plausible" in text
    assert "confirmed" in text
    assert "refuted" in text


def test_sets_an_escalation_threshold_as_a_number() -> None:
    """Vague thresholds ('if it's taking too long') do not trigger; a number does."""
    text = _skill_text().lower()
    assert "3 " in text or "three " in text, "no numeric escalation threshold"


def test_is_read_only() -> None:
    """A reviewer that starts fixing stops reviewing, and its findings become
    unauditable because the evidence moved underneath them."""
    text = _skill_text().lower()
    assert "read-only" in text or "never fix" in text or "does not fix" in text


def test_names_its_boundary_against_every_sibling_reviewer() -> None:
    """Four review-shaped skills already exist. Without an explicit boundary the
    router fires two of them at the same request."""
    text = _skill_text()
    for sibling in SIBLING_REVIEWERS:
        assert sibling in text, f"SKILL.md never distinguishes itself from {sibling}"


def test_does_not_claim_a_sibling_reviewers_quoted_trigger() -> None:
    """`smoke_test` lints this globally; pinning it here keeps the failure legible."""
    description = _description().lower()
    for stolen in ('"code review"', '"security review"', '"plan review"'):
        assert stolen not in description


def test_ships_pressure_scenarios_with_a_recorded_red_baseline() -> None:
    """A discipline skill written from guesses about what needs preventing encodes
    the author's assumptions. Only scenarios with an observed no-skill failure
    earn a place in the suite."""
    tests_md = (SKILL_DIR / "tests.md").read_text().lower()
    assert "no-skill" in tests_md or "no skill" in tests_md
    assert tests_md.count("observed no-skill red") >= 2, (
        "fewer than 2 scenarios have an observed no-skill failure recorded"
    )
    assert "discarded" in tests_md, (
        "scenarios the no-skill baseline already passed must be recorded as "
        "discarded, or someone re-derives them"
    )


# --- PR-scoped multi-lens pattern -------------------------------------------
#
# Nine slices drained by hand produced the same review shape six times, written
# from scratch each time: 3-4 narrow lenses over one PR against its binding
# spec, then three refuters per finding defaulting to refuted. It caught real
# defects on five of seven PRs, including a failed re-write that truncated a
# valid data file to zero bytes. Two failure modes are what the reference has to
# carry, because both produce a confident clean report: a run contaminated by a
# mid-review commit into the same worktree, where a correct finding and its
# unanimous refutation described different trees; and a zero-findings result
# that is indistinguishable from a lens that died on dispatch.

PR_LENS_REFERENCE = SKILL_DIR / "references" / "pr-lens-review.md"


def _pr_lens_text() -> str:
    return PR_LENS_REFERENCE.read_text()


def test_general_method_stays_primary() -> None:
    """The PR pattern is an added instantiation, not a replacement.

    The skill's value is that it attacks any finished work — a claim, a result,
    a plan. A concrete PR recipe is the kind of addition that quietly becomes
    the whole skill, so the general spine is pinned here explicitly.
    """
    text = _skill_text()
    for heading in (
        "## 1. Build the claim ledger",
        "## 2. Attack each claim",
        "## 3. Grade on evidence, not conviction",
        "## 4. Report — every slot REQUIRED",
    ):
        assert heading in text, f"general method lost its section: {heading}"
    assert text.index("## 1. Build the claim ledger") < text.index(
        "## When the work is one pull request"
    ), "the PR section must follow the general method, not precede it"


def test_skill_routes_to_the_pr_lens_reference() -> None:
    """A reader on a PR gets handed the pattern instead of reinventing it."""
    assert PR_LENS_REFERENCE.is_file(), f"{PR_LENS_REFERENCE} is missing"
    assert "references/pr-lens-review.md" in _skill_text()


def test_lens_pass_contract_is_pinned() -> None:
    """Narrow lenses, evidence-backed defects, and a real empty-list option.

    A lens told to report defects with no stated empty-list option invents one
    to look useful, which is the noise the refutation pass then has to absorb.
    """
    text = _pr_lens_text().lower()
    assert "binding spec" in text, "findings are scored against the issue body"
    assert "file:line" in text, "every finding needs a location"
    assert "failure scenario" in text, "every finding needs a concrete trigger"
    assert "empty" in text, "an empty findings list must be named as expected"
    for lens in ("domain correctness", "test veracity", "spec conformance", "credential"):
        assert lens in text, f"lens set must name {lens}"


def test_refutation_bias_and_threshold_are_pinned() -> None:
    """Three refuters, default refuted, >=2 upheld — inverted for secrets."""
    text = _pr_lens_text().lower()
    assert "three independent refuters" in text, "one refuter is not a vote"
    assert "refuted=true" in text, "refuters default to refuted when uncertain"
    assert "two or more upheld" in text, "the confirmation threshold must be explicit"
    assert "invert the bias" in text, (
        "credential and live-network findings must invert the default bias"
    )


def test_structured_output_uses_the_workflow_schema_option() -> None:
    """Parsing prose is where a hedged sentence becomes a dropped defect."""
    assert "schema" in _pr_lens_text().lower()


def test_tree_must_be_frozen_before_dispatch() -> None:
    """A finding and its refutation have to describe the same tree."""
    text = _pr_lens_text().lower()
    assert "freeze the head before dispatch" in text
    assert "frozen head" in text, (
        "a mid-run edit means re-running against a frozen head, not reasoning "
        "about which agent saw which state"
    )


def test_zero_findings_requires_reading_the_journal() -> None:
    """A dead lens and a clean lens hand the conductor the same result."""
    text = _pr_lens_text()
    assert "journal.jsonl" in text, "a clean result is checked against the journal"
    assert "one result record per lens" in text.lower(), (
        "the journal check must name what it confirms"
    )
    assert "Could not verify" in text, (
        "a missing lens record belongs in the report's coverage slot"
    )


def test_cost_is_stated_before_dispatch() -> None:
    """A reader spending 4-9 agents cannot make that call blind."""
    text = _pr_lens_text().lower()
    assert "4-9 agents" in text, "name the real scale of a per-PR run"


def test_workflow_script_backtick_gotcha_is_recorded() -> None:
    """Raw backticks in a JS template literal break the script parse."""
    text = _pr_lens_text().lower()
    assert "template literal" in text, "name where the backticks break"
    assert "join" in text, "give the fix: join an array of plain strings"


def test_sibling_boundaries_are_cross_referenced_not_duplicated() -> None:
    """drain-queue owns the queue loop; detector-teeth-check owns mutation."""
    text = _pr_lens_text()
    assert "drain-queue" in text, "the queue loop belongs to drain-queue"
    assert "detector-teeth-check" in text, (
        "mutation mechanics belong to detector-teeth-check"
    )
    assert "does not replace" in text or "does not substitute" in text, (
        "the reference must defer to its siblings, not absorb them"
    )
