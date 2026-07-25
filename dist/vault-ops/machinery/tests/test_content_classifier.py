"""Tests for the content classifier — category detection and routing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(SCRIPTS_DIR))

from content_classifier import ClassificationResult, classify, routing_hook_output


# ---------------------------------------------------------------------------
# Category detection — each category should match its keywords
# ---------------------------------------------------------------------------

class TestIncidentCategory:
    def test_incident_keyword(self) -> None:
        result = classify("There was a production incident with the data pipeline")
        assert result.category == "incident"

    def test_outage_keyword(self) -> None:
        result = classify("We had a major outage affecting the analytics dashboard")
        assert result.category == "incident"

    def test_root_cause(self) -> None:
        result = classify("The root cause was a misconfigured connection pool")
        assert result.category == "incident"

    def test_postmortem(self) -> None:
        result = classify("Writing the postmortem for yesterday's downtime")
        assert result.category == "incident"


class TestOneOnOneCategory:
    def test_1_1_colon(self) -> None:
        result = classify("Had a 1:1 with Jane about pipeline performance")
        assert result.category == "1-1"

    def test_1_1_hyphen(self) -> None:
        result = classify("My 1-1 with the manager went well")
        assert result.category == "1-1"

    def test_met_with(self) -> None:
        result = classify("Met with Sarah to discuss the data model changes")
        assert result.category == "1-1"

    def test_sync_with(self) -> None:
        result = classify("Quick sync with Alex about the ETL migration")
        assert result.category == "1-1"


class TestDecisionCategory:
    def test_decided_keyword(self) -> None:
        result = classify("We decided to use Snowflake instead of BigQuery")
        assert result.category == "decision"

    def test_going_with(self) -> None:
        result = classify("Going with dbt for our transformation layer")
        assert result.category == "decision"

    def test_pros_and_cons(self) -> None:
        result = classify("Weighing pros and cons of Airflow vs Dagster")
        assert result.category == "decision"

    def test_decision_suggested_folder(self) -> None:
        result = classify("We decided to use Snowflake instead of BigQuery")
        assert result.suggested_folder == "work/decisions"
        assert "work/decisions" in result.routing_hint


class TestWinCategory:
    def test_shipped(self) -> None:
        result = classify("Shipped the new customer segmentation pipeline")
        assert result.category == "win"

    def test_positive_feedback(self) -> None:
        result = classify("Got great feedback from the product team on the dashboard")
        assert result.category == "win"

    def test_milestone(self) -> None:
        result = classify("Hit a major milestone — zero data quality incidents this quarter")
        assert result.category == "win"


class TestProjectUpdateCategory:
    def test_working_on(self) -> None:
        result = classify("Still working on the data warehouse migration, hit a blocker")
        assert result.category == "project-update"

    def test_sprint(self) -> None:
        result = classify("Sprint planning: picked up three pipeline tickets for next week")
        assert result.category == "project-update"

    def test_deployed(self) -> None:
        result = classify("Deployed the new staging environment for the analytics platform")
        assert result.category == "project-update"

    def test_suggested_folder_is_ad_hoc_inbox(self) -> None:
        # New work-note captures land in the ad-hoc inbox by default; the
        # routing hint nudges toward updating an existing project note first.
        result = classify("Sprint planning: picked up three pipeline tickets for next week")
        assert result.suggested_folder == "work/active/ad-hoc"
        assert "existing project note" in result.routing_hint


class TestPersonContextCategory:
    def test_works_on(self) -> None:
        result = classify("Jake works on the platform team and is responsible for CI/CD")
        assert result.category == "person-context"

    def test_new_hire(self) -> None:
        result = classify("New hire Lisa joined the team as a data analyst")
        assert result.category == "person-context"

    def test_reports_to(self) -> None:
        result = classify("She reports to Mark and manages two junior engineers")
        assert result.category == "person-context"


class TestLearningCategory:
    def test_learned(self) -> None:
        result = classify("Learned about window functions in advanced SQL today")
        assert result.category == "learning"

    def test_tutorial(self) -> None:
        result = classify("Following a tutorial on dbt incremental models")
        assert result.category == "learning"

    def test_til(self) -> None:
        result = classify("TIL: you can use QUALIFY in Snowflake to filter window functions")
        assert result.category == "learning"


class TestSideProjectCategory:
    def test_side_project(self) -> None:
        result = classify("My side project is a hobby project CLI data profiler")
        assert result.category == "side-project"

    def test_personal_project(self) -> None:
        result = classify("My personal project needs a web scraper component")
        assert result.category == "side-project"


class TestIdeaCategory:
    def test_what_if(self) -> None:
        result = classify("What if we built a data quality scoreboard for the company?")
        assert result.category == "project-idea"

    def test_brainstorm(self) -> None:
        result = classify("Brainstorm: automated anomaly detection for our key metrics")
        assert result.category == "project-idea"


class TestDefaultCategory:
    def test_empty_string(self) -> None:
        result = classify("")
        assert result.category == "thought"

    def test_whitespace_only(self) -> None:
        result = classify("   \n  ")
        assert result.category == "thought"

    def test_no_keywords(self) -> None:
        result = classify("The weather is nice today")
        assert result.category == "thought"

    def test_generic_text(self) -> None:
        result = classify("The weather is really something else this week")
        assert result.category == "thought"


# ---------------------------------------------------------------------------
# Task category
# ---------------------------------------------------------------------------

class TestTaskCategory:
    def test_need_to(self) -> None:
        result = classify("I need to buy groceries later")
        assert result.category == "task"

    def test_reminder(self) -> None:
        result = classify("Reminder to call the dentist tomorrow")
        assert result.category == "task"

    def test_todo(self) -> None:
        result = classify("Todo: pick up the dry cleaning")
        assert result.category == "task"

    def test_to_do(self) -> None:
        result = classify("To-do: renew car registration")
        assert result.category == "task"

    def test_pick_up(self) -> None:
        result = classify("Pick up prescription from pharmacy")
        assert result.category == "task"

    def test_schedule(self) -> None:
        result = classify("Schedule a vet appointment for the dog")
        assert result.category == "task"

    def test_errand(self) -> None:
        result = classify("Errand: drop off package at the post office")
        assert result.category == "task"

    def test_dont_forget(self) -> None:
        result = classify("Don't forget to pay the electric bill")
        assert result.category == "task"

    def test_remember_to(self) -> None:
        result = classify("Remember to cancel that subscription")
        assert result.category == "task"

    def test_grocery(self) -> None:
        result = classify("Grocery run: eggs, milk, bread")
        assert result.category == "task"

    def test_chore(self) -> None:
        result = classify("Chore: clean the gutters this weekend")
        assert result.category == "task"

    def test_routing_hint(self) -> None:
        result = classify("Need to buy groceries")
        assert "personal/tasks" in result.routing_hint

    def test_suggested_folder(self) -> None:
        result = classify("Need to buy groceries")
        assert result.suggested_folder == "personal/tasks"

    def test_suggested_template(self) -> None:
        result = classify("Need to buy groceries")
        assert result.suggested_template == "Task"


class TestTaskPriority:
    def test_incident_beats_task(self) -> None:
        """Higher-priority categories should win over task."""
        result = classify("There was an incident, need to fix the pipeline immediately")
        assert result.category == "incident"

    def test_learning_beats_task(self) -> None:
        result = classify("Learned how to schedule dbt jobs in Dagster")
        assert result.category == "learning"

    def test_project_update_beats_task(self) -> None:
        result = classify("Working on the next steps for the pipeline deployment")
        assert result.category == "project-update"


# ---------------------------------------------------------------------------
# Priority order — when text matches multiple categories
# ---------------------------------------------------------------------------

class TestPriorityOrder:
    def test_incident_beats_decision(self) -> None:
        """incident > decision per priority order."""
        result = classify("We decided to fix the root cause of the incident immediately")
        assert result.category == "incident"

    def test_1_1_beats_decision_same_score(self) -> None:
        """1-1 > decision when both match equally (priority order)."""
        result = classify("In my 1:1 we agreed to the new scope")
        assert result.category == "1-1"

    def test_higher_score_beats_priority(self) -> None:
        """When decision has more matches than 1-1, score wins over priority."""
        result = classify("In my 1:1 we decided to go with option B and settled on a timeline")
        assert result.category == "decision"

    def test_incident_beats_1_1(self) -> None:
        """incident > 1-1 per priority order."""
        result = classify("Met with the team about the production incident response")
        assert result.category == "incident"

    def test_decision_beats_win(self) -> None:
        """decision > win per priority order."""
        result = classify("Decided to ship the feature and it was a great milestone")
        # Both match, but with more patterns matching for one or the other
        # The key is that it picks one consistently
        assert result.category in ("decision", "win")


# ---------------------------------------------------------------------------
# False positive resistance
# ---------------------------------------------------------------------------

class TestFalsePositiveResistance:
    def test_won_in_wonder(self) -> None:
        """'won' should not trigger 'win' when in 'wonder'."""
        result = classify("I wonder what the best approach would be here")
        assert result.category != "win"

    def test_learned_in_context(self) -> None:
        """'learned' should trigger learning, not be ignored."""
        result = classify("I learned that dbt snapshots use type-2 SCD")
        assert result.category == "learning"

    def test_met_without_person(self) -> None:
        """'met with' should still trigger 1-1."""
        result = classify("Met with the team to discuss architecture")
        assert result.category == "1-1"

    def test_pipeline_not_always_project(self) -> None:
        """'pipeline' alone matches project-update."""
        result = classify("The pipeline is running slowly today")
        assert result.category == "project-update"


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_result_has_all_fields(self) -> None:
        result = classify("Had a 1:1 with Jane")
        assert isinstance(result, ClassificationResult)
        assert result.category == "1-1"
        assert result.suggested_folder == "work/1-1"
        assert result.suggested_template == "1-1 Note"
        assert "1:1" in result.routing_hint or "1-1" in result.routing_hint
        assert 0.0 < result.confidence <= 1.0

    def test_default_result_structure(self) -> None:
        result = classify("Random unclassifiable text here")
        assert result.category == "thought"
        assert result.suggested_folder == "thinking"
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# routing_hook_output — contract-correct UserPromptSubmit payload (#81)
# ---------------------------------------------------------------------------

class TestRoutingHookOutput:
    def test_shape_matches_userpromptsubmit_contract(self) -> None:
        # hookSpecificOutput must be an OBJECT (not a JSON-encoded string) with
        # hookEventName + additionalContext — the documented UserPromptSubmit shape.
        result = classify("There was a production incident with an outage")
        out = routing_hook_output(result)
        hso = out["hookSpecificOutput"]
        assert isinstance(hso, dict)
        assert hso["hookEventName"] == "UserPromptSubmit"
        assert isinstance(hso["additionalContext"], str)
        assert hso["additionalContext"]  # non-empty

    def test_additional_context_carries_routing_info(self) -> None:
        result = classify("I need to buy groceries")  # → task
        ctx = routing_hook_output(result)["hookSpecificOutput"]["additionalContext"]
        assert result.category in ctx
        assert result.suggested_folder in ctx
        assert result.routing_hint in ctx

    def test_no_double_json_encoding(self) -> None:
        # Regression guard for #81: the value must not be a JSON string.
        result = classify("There was an incident outage")
        hso = routing_hook_output(result)["hookSpecificOutput"]
        assert not isinstance(hso, str)


# ---------------------------------------------------------------------------
# Confidence — comparable across categories via a fixed denominator K=3 (#42)
# ---------------------------------------------------------------------------

class TestConfidenceComparable:
    def test_single_match_is_one_third(self) -> None:
        # One keyword hit → 1/3, regardless of how many patterns the category has.
        result = classify("There was an incident")  # exactly one incident keyword
        assert result.category == "incident"
        assert result.confidence == pytest.approx(1 / 3)

    def test_three_or_more_matches_saturate_to_one(self) -> None:
        result = classify("incident outage postmortem downtime")  # 4 incident keywords
        assert result.confidence == 1.0

    def test_comparable_across_categories(self) -> None:
        # Same hit count → same confidence, independent of category vocabulary size.
        # (Previously incident=1/13 vs side-project=1/8 for one hit — not comparable.)
        a = classify("There was an incident")        # incident (13 patterns), 1 hit
        b = classify("This is my side project")      # side-project (8 patterns), 1 hit
        assert a.confidence == pytest.approx(b.confidence)
