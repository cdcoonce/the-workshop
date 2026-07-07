# /grill — Active Knowledge Extraction

Interrogate Charles about a topic until it is **holistic**, then route the captured knowledge to a
durable vault note. This is the **inverse of [[teach]]**: `/teach` pushes knowledge into Charles's
head; `/grill` pulls knowledge out of it into the vault. And it is the active counterpart to
[[dump]]: `/dump` passively routes what Charles already typed; `/grill` interrogates first, then
routes. Design spec: `thinking/2026-06-22-grill-skill-design.md`.

**Explicit-invoke by design.** Triggered only by `/grill`, never model-auto-triggered — grilling is
an opt-in mode you choose deliberately, not something that fires on any mention of a topic. See
[[Patterns]] → "Skill & Agent Design".

## Usage

```
/grill <topic>     # start or resume a knowledge-extraction interview on <topic>
```

`<topic>` is a person, project, decision, concept, or idea — anything whose knowledge lives in
Charles's head but not yet (fully) in the vault.

## The capture verbs

| Skill    | Direction         | Interrogates? |
| -------- | ----------------- | ------------- |
| `/teach` | vault → your head | —             |
| `/dump`  | your head → vault | no (passive)  |
| `/grill` | your head → vault | yes (active)  |

## Process

1. **RESOLVE** — Classify the entity type using `/dump`'s classifier (person / project / decision /
   concept-learning / idea). Check whether a note already exists for this topic (search by name,
   slug, and likely folder). State the type you chose and why if it's ambiguous.

2. **RESUME** — If a note exists, **delegate the read to a worker**: a subagent reads the note and
   its backlinks and returns a distilled summary of what the vault already knows (conductor stays
   lean — see [[2026-06-16-conductor-workers-operating-model]]). Open the grill with that summary
   and the thin spots: _"Here's what the vault already knows: … The thin spots are X and Y — start
   there, or somewhere else?"_ If the topic is new, ask **one** framing question first: what is this
   note *for* (how will you want to use it later)? — then begin. Never grill blind.

3. **GRILL** — Work the **typed starter-domains** for the entity type (below) as a coverage
   checklist. Adapt within the skeleton — these are seeds, not a script. Use **hybrid** questioning:
   - **`AskUserQuestion`** for branch points, disambiguation, and decisions — multiple-choice,
     **recommendation first** (your best guess as option one, `(Recommended)` appended), **batched**
     up to 4 related questions per call within a single domain. Never mix domains in one call.
   - **Open-ended prompts** (plain text, one at a time) for genuine brain-dumps where options can't
     be enumerated — _"walk me through the history of…"_, _"what do you know about X that isn't
     written down?"_.
   - **Explore before asking.** If a question is answerable from the existing note, other vault
     notes, or git history, answer it yourself (via a worker if it needs a sweep) instead of asking.
     Only ask what genuinely needs Charles's head.
   - **No assumption survives.** If something is implied but unstated, surface it and confirm.

4. **GATE — evergreen vs. transient** (the ingest-discipline rule). As answers come in, filter:
   - **Evergreen** ("will this matter in a year?" — remit, rationale, decisions, durable context) →
     **capture** into the note.
   - **Transient** (Slack threads, emails, live tickets, current status, changing customer data) →
     **do not transcribe**. Record a **pointer** to where it lives instead — _"current status:
     ClickUp OTA-7"_ — so the brain knows where to *reach*, not what to stale-cache. When unsure,
     ask Charles which bucket a piece of data is in.

5. **STOP — coverage + diminishing returns.** Maintain a live coverage map (✅ covered · ◐ thin ·
   ○ untouched) across the starter-domains. Surface it on request and at the end. End the session
   when every domain is covered **or** answers go thin ("not sure", "skip"). Charles can call it
   done at any point — respect it immediately.

6. **ROUTE — persist via `/dump`'s rules.** Synthesize the captured knowledge into the vault note:
   - **New topic** → create in the routed folder with the correct template, full frontmatter
     (`date`, `description` ~150 chars, `tags`), wikilinks to people/projects/competencies/related
     notes, and the relevant index update — exactly `/dump`'s contract.
   - **Existing topic** → **merge** the new knowledge in (integrate or append; **never blind-
     overwrite**). Preserve what was there; mark anything Charles corrected as superseded.

7. **REPORT** — Close with: the coverage map, the note path, the wikilinks added, and any
   **transient pointers** recorded (so Charles sees what was deliberately *not* ingested and why).

## Typed starter-domains (seeds, not scripts)

| Type                 | Starter domains                                                                                      | Routes to                                     |
| -------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| **Person**           | remit · history with Charles · how they work · what they care about · relationships/influence · current plate | `org/people/<Full Name>.md`                   |
| **Project**          | goal / definition-of-done · status & momentum · key decisions + *why* · risks / open questions · stakeholders / deps · origin | `work/active/` or `personal/projects/`        |
| **Decision**         | the choice & context · options considered · rationale / tradeoffs · what it forecloses · revisit conditions | `brain/Key Decisions.md` or a decision record |
| **Concept / learning** | it in your words · why it matters to you · how it connects · where you're fuzzy · sources           | `personal/learning/`                          |
| **Idea**             | core insight · what sparked it · what it could become · what would kill it · adjacent ideas           | `personal/ideas/`                             |
| **Unmatched**        | one question to name the type, then improvise                                                         | route by best fit                             |

## Constraints

- **Stateful through the graph, not a workspace.** Resume by reading the existing note + backlinks;
  never restart from blank, never spin up a parallel coverage-tracking workspace.
- **Self-contained.** No dependency on `claude-workflow/grill-me` — the vault must run identically on
  a fresh machine ([[Constitution]]). Borrow its habits, don't import it.
- **Conductor-aware.** The interview is judgment work — keep it on the conductor. Delegate any
  "what does the vault already know" sweep to a worker that returns a digest.
- **One topic per grill.** Two unrelated topics = two sessions.
- **Evergreen only.** The note is for knowledge that stays true; transient data gets a pointer, not a
  transcription.
- **Vault contract.** Validate frontmatter and wikilinks before saving; update the relevant index;
  no orphan notes.
