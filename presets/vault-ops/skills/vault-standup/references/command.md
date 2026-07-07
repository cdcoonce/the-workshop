# /standup — Context Loading & Structured Summary

Load vault context, sync from M365 (work machine only), and present a structured summary tailored to machine context and time of day.

**Arguments:** $ARGUMENTS

## Mode (read first — conductor discipline)

`/standup` is the single biggest context load in a session, so it is **lean by default** and only does the full sweep on request. See the Operating Model in root `CLAUDE.md`.

- **Default (lean) — DO THIS unless `--deep` is passed.** Load only: the rolling handoff (`.brain/handoff-<context>.md`), `git log` since the window below, and open tasks (`work/Tasks.md` / current `personal/tasks/` week). **Skip** Quick-Reference, the indexes, North Star, and M365 email. Present a short orientation built around the handoff (the handoff already _is_ the digest). On a work machine, still pull today's calendar (cheap), but skip the email scan. This keeps the conductor's context small — that's the point. Also run `uv run python .claude/scripts/graph_gardener.py --queue-summary` (cheap) and surface its line — it's the escalating `/garden` reminder (goes ⚠️ loud when the queue is large or stale).
- **`--deep`** — run the full **Phase 1** below (handoff + Quick-Reference + indexes + North Star + M365 calendar + recent flagged email). Per conductor discipline, **delegate the heavy loading to a Sonnet/Haiku worker** that returns a ≤20-line digest, rather than reading it all into this (Opus) context.
- **`--comprehensive`** — implies `--deep`, and additionally scans the last 7 days of email for missed action items (work machine only).

Default → present from the lean set and stop. `--deep` / `--comprehensive` → continue into Phase 1.

---

## Phase 1: Data Loading (`--deep` / `--comprehensive` only)

Load all data first. The presentation template (Phase 2) decides what to emphasize. **Prefer delegating the bulk loads to a worker** (see Mode above) so this only enters the conductor's context as a digest.

### 1. Detect Machine Context

Read `.vault-context` to determine machine (work vs personal).

- If `work`: proceed with full M365 sync
- If `personal` or missing: skip M365, vault-only standup

### 2. Detect Time of Day

Read the local system time (not UTC) and classify:

- **Morning:** before 11:00
- **Afternoon:** 11:00–18:00
- **Evening:** after 18:00

### 2.5. Weekly Work Task Rollover (work machine only)

Before loading tasks, check whether a new ISO week has started. On a work machine:

```python
from work_task_manager import rollover_work_tasks
result = rollover_work_tasks(vault_root)
```

The function is idempotent — if the `week:` field in `work/Tasks.md` already matches today's ISO week, it returns `{"rolled_over": False, ...}` and the standup continues normally.

If `rolled_over: True`, the function has already:

- Archived the prior week to `work/tasks/{YYYY-WNN}-tasks.md` (verbatim)
- Rewritten `work/Tasks.md` carrying forward only `[ ]` items from Active, Waiting On, and Someday (preserving `### [[Project]]` subsection headers unless empty)
- Emptied the Done section and updated the `week:` frontmatter

**After a successful rollover, before continuing the standup:**

1. Announce: `🔁 Rolled over to {new_week}. Archived last week to [work/tasks/{archived_week}-tasks.md](work/tasks/{archived_week}-tasks.md).`
2. If `done_items` is non-empty, surface it for Brag Doc triage:

   ```
   ## Last week's Done items — Brag Doc scan
   [list each done_item on its own line]

   Which of these deserve entries in perf/Brag Doc.md? [user picks; skip if none]
   ```

3. After user picks entries (or says "none"), append them to `perf/Brag Doc.md` under the current quarter.
4. Then proceed with the rest of the standup against the freshly-leaned `work/Tasks.md`.

On a personal machine, skip this step — personal/tasks already uses weekly files and `task_manager.rollover_tasks()`.

### 2.6. Stale Prep Sweep

A meeting-prep note carries the meeting date in `date:`, so once it has passed the prep is objectively done. This deterministic, no-LLM sweep flips such notes to `completed` so the Active surfaces (`work/Index.md`, the Obsidian Bases) stay honest without a manual pass:

```python
from note_lifecycle import sweep_stale_prep
prep = sweep_stale_prep(vault_root)
```

Idempotent (re-running the same day is a no-op) and reversible (only the `status` line changes). It touches a note only when it is tagged `meeting-prep`, has `status: active`, and its `date` is strictly before today — so evergreen notes and future/same-day prep are left alone. Runs on both machines (prep lives in `work/`; the scan is cheap).

If `prep["count"] > 0`, announce: `🧹 Swept {count} stale prep note(s) → completed.` and list `prep["flipped"]`.

### 2.7. Load the Rolling Handoff

Read `.brain/handoff-<context>.md` (the context from step 1: `work` | `personal`). This is the **resume anchor** — the prior session's own digest of where things stand and what to do next. `session-start.py` already injected it into context at session start; re-read it here so the standup is built _around_ it, not in parallel to it. Treat its "resume from here / next steps" as the spine of today's summary; everything else (git log, tasks, calendar) is corroborating detail. If git activity or M365 data contradicts the handoff, the live data wins — flag the drift so the handoff gets corrected at `/wrap-up`.

### 3. Load Quick Reference

Read `brain/Quick-Reference.md` if it exists. Use its People/Terms/Projects tables to decode workplace shorthand throughout the standup.

### 4. Recent Work

- **Morning:** `git log --since="24 hours ago"` — shows yesterday's work
- **Afternoon/Evening:** `git log --since="midnight"` — shows today's work specifically

### 5. Active Projects

Scan `work/Index.md` for active projects and their current status.

### 6. M365 Sync (work machine only)

**Calendar:** Use `mcp__claude_ai_Microsoft_365__outlook_calendar_search` to get today's events:

- List each meeting with time, attendees, and subject
- For 1:1 meetings: check `work/1-1/` for recent notes with that person and surface context
- For meetings with agendas or pre-read attachments: extract prep items

**Email — Quick mode (default):** Use `mcp__claude_ai_Microsoft_365__outlook_email_search` to search for recent emails (last 24 hours) that contain action items.

**Email — Comprehensive mode (`--comprehensive`):** Search the last 7 days of email.

For each email, extract action items conservatively:

- Look for explicit asks: "can you", "please", "action required", "by [date]", "need you to"
- Look for meeting prep: "pre-read", "agenda", "please review before"
- Ignore: FYIs, newsletters, thread replies with no asks

For each extracted item, check `work/Tasks.md` for duplicates using title similarity. Skip duplicates.

**Present extracted items for confirmation:**

```
## Extracted Action Items (from M365)
- [ ] **[item title]** (from: [sender] email [date])
- [ ] **[item title]** (from: [meeting name] [date])

Add these to work/Tasks.md? [confirm each or all]
```

After confirmation, add to `work/Tasks.md` using the work_task_manager pattern (Active section, with inline provenance).

If MCP fails for either calendar or email: print "⚠️ M365 sync failed: [reason]. Showing vault-only data." and continue.

### 7. Open Work Tasks

Search for unchecked `- [ ]` items in `work/Tasks.md` (Active and Waiting On sections).
Also search across active work notes for open items.

### 8. Personal Tasks

Scan `personal/tasks/` for the current week's task file and any past week files with incomplete tasks.

- Show open tasks from the current week sorted by due date.
- If past week files have incomplete tasks, offer rollover.
- Use `task_manager.get_open_tasks()` and `task_manager.rollover_tasks()`.

### 9. North Star Goals

Read `brain/North Star.md` and compare active work against stated goals.

### 10. Personal Context (personal machine only)

- Scan `personal/Index.md` for active learning, side projects, and ideas.
- Scan `thinking/` for drafts modified in the last 48 hours (excluding `session-logs/`). These feed the "What's Been on Your Mind" section.

---

## Phase 2: Present the Summary

Based on the machine context and time of day detected in Phase 1, jump to the matching template below. **Skip any section that would be empty** — never show an empty header.

**Always surface the gardener nudge** if `--queue-summary` returned a non-empty line — show it near the top (as a `## Vault Maintenance` line) so the `/garden` call-to-action isn't missed, especially when it's ⚠️ loud.

---

### Work — Morning (before 11:00)

Tone: Forward-looking, planning energy. "Here's what's ahead."

```
## Yesterday
- [completed items from git log]

## Today's Calendar
- 09:00 — Sprint Planning (Alice, Bob, Carol)
- 10:30 — 1:1 with [[Biodun]] — last discussed [context from work/1-1/]

## Extracted Action Items (from M365)
- [ ] **[item]** (from: [sender] [date])
→ Added to work/Tasks.md ✓

## Today's Priorities
- [suggested focus based on calendar, deadlines, and North Star alignment]

## Open Work Tasks
- [ ] [tasks from work/Tasks.md]

## Personal Tasks
- [ ] [open tasks from personal/tasks/]

## North Star Check
- [which goals current work serves]
- [any goals going unserved]
```

---

### Work — Afternoon (11:00–18:00)

Tone: Continuation, momentum check. "Here's where things stand."

```
## Today So Far
- [commits/changes since midnight from git log]

## Remaining Calendar
- [only meetings still ahead today]

## Focus for the Rest of the Day
- [highest priority open items, weighted toward deadlines]

## Open Work Tasks
- [ ] [tasks, sorted by urgency]

## Waiting On
- [items in Waiting On section of work/Tasks.md]
```

---

### Work — Evening (after 18:00)

Tone: Wrap-up, quick orientation. "Where did things land today?"

```
## Today's Progress
- [commits/changes from today]

## Loose Ends
- [open tasks that were due today or are urgent]
- [any unresolved action items from today's meetings]

## Tomorrow Preview
- [tomorrow's calendar if available, otherwise top priorities]

## North Star Check
- [brief alignment note]
```

---

### Personal — Morning (before 11:00)

Tone: Gentle warm-up, goal-setting. "What do you want to move forward today?"

```
## What's Been on Your Mind
- [recent thinking/ drafts from last 48h, summarized]
- [any incomplete ideas from personal/ideas/]

## North Star Progress
- [personal goals from North Star with recent momentum indicators]
- [side projects: last touched date, current status]
- [learning: where you left off]

## Personal Tasks
- [ ] [open tasks from current week, sorted by date]
- [rollover items if any]

## Suggested Focus
- [1-2 items based on momentum + what's been idle too long]
```

---

### Personal — Afternoon (11:00–18:00)

Tone: Check-in, continuation. "Here's where things stand — pick something up?"

```
## What's Been on Your Mind
- [recent thinking/ drafts, briefer than morning]

## Today So Far
- [any commits/changes from today]

## Open Threads
- [side projects with recent activity, where you left off]
- [learning notes in progress]

## Personal Tasks
- [ ] [remaining open tasks for the week]

## Quick Win?
- [suggest one small task or idea that could be finished quickly]
```

---

### Personal — Evening (after 18:00)

Tone: Focused session setup. "You've got time — here's what's worth picking up."

```
## What's Been on Your Mind
- [recent thinking/ drafts]

## Session Setup
- [side projects ranked by recency + momentum — "you last touched X 3 days ago"]
- [learning with progress markers — "you're on chapter 4 of..."]

## Personal Tasks
- [ ] [open tasks, but de-emphasized — not the lead]

## North Star Check
- [goals with no recent activity — gentle nudge, not guilt]

## Evening Focus
- [1 recommended deep-work item based on what has momentum and what's been idle]
```

---

## Constraints

- Keep summaries concise — quick orientation, not deep dive
- If vault is new/empty, say so and suggest `/dump` or `/start`
- Link to relevant notes using wikilinks
- If `brain/Quick-Reference.md` exists, use it to decode any acronyms or names encountered
- M365 failures are warnings, not blockers — continue with vault-only data
- Graceful degradation: if `thinking/` has no recent drafts, skip "What's Been on Your Mind"
- **Personal templates should never feel like a guilt trip.** Frame idle projects as opportunities, not failures. "You haven't touched X in a while — want to pick it back up?" not "X is overdue."
- **Local time, not UTC.** Time detection must use the system's local clock.
