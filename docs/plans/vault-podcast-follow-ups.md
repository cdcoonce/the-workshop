# vault-podcast — deferred follow-ups

Deferred by explicit decision during the 2026-08-16 grill + CEO review that
shaped the v1 skill (see the skill's `references/command.md` for the shipped
contract). Each entry carries enough context to start cold.

## 1. `briefing` style — S, P2

**What:** A third script recipe: a short (~3 min) spoken digest of the vault's
handoff/standup surface — "your week, spoken."
**Why:** The natural daily-use style, and the payload for any future scheduled
run. Deferred because the recipe is unproven and v1 should prove listening
habits first.
**Start:** Add a `briefing` section beside `deep-dive`/`lesson` in
`references/command.md`; the renderer needs nothing new. Sources: the handoff
digest and `personal/Index.md` actives.

## 2. Scheduled / unattended episodes — M, P3

**What:** A cron/afk-driven render (e.g. Monday-morning briefing) with no
interactive session.
**Why:** Turns the skill from on-demand into ambient. Deferred because headless
execution is its own surface — auth, PATH, network-in-cron, and the script
writer currently _is_ the session LLM, so unattended needs a scripted prompt
path. Depends on: item 1 (briefing is the natural payload).
**Start:** Follow the vault's afk headless-environment lessons; the renderer is
already fully non-interactive.

## 3. Phone transport — S, P3

**What:** Copy finished episodes to an iCloud Drive folder
(`~/Library/Mobile Documents/com~apple~CloudDocs/vault-podcast/`) so they appear
in the Files app for commute listening.
**Why:** v1 audio is Mac-local by decision (workshop convention); a listening
habit on the phone would justify the one-line copy step in the render procedure.
**Start:** One `cp` in command.md step 5, or a `--publish` flag on render.py.

## 4. `say` offline fallback — S, P3

**What:** Optional `--engine say` using macOS built-in voices when edge-tts is
unreachable.
**Why:** v1 fails fast offline (script survives; re-run is one command), and
`say` quality was never judged. Only worth it if offline rendering becomes a
real need.
**Start:** Second implementation of the `synthesize_turn` seam in render.py.

## 5. Automated grounding checker — M, P3

**What:** A check that every script claim maps to a Key-claims citation in the
show note (or flags uncited spans).
**Why:** v1 relies on the human citation discipline inherited from `/teach`
("cite everything; never parametric"). At personal scale that suffices; automate
only if episodes start drifting from sources.
**Start:** Compare script.txt sentences against the show note's `## Key claims`
rows; an LLM-judge pass over (script, sources) is the likely shape.
