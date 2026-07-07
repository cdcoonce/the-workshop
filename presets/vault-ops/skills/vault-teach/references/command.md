# /teach — Stateful Teaching Workspace

Teach Charles a skill or concept **over multiple sessions**, using the vault as the persistent learning state. Adapted from Matt Pocock's `teach` skill ([github.com/mattpocock/skills](https://github.com/mattpocock/skills)), made vault-native. This is a **stateful** request — see [[Patterns]] → "Skill & Agent Design".

**Explicit-invoke by design.** Triggered only by `/teach`, never model-auto-triggered — a teaching workspace is an opt-in mode you choose deliberately, not something that should fire on any "how does X work?" question. (Matt sets `disable-model-invocation: true` for the same reason.)

## Usage

```
/teach <topic>        # start or resume learning a topic
```

## The Workspace

Each topic gets a folder: `personal/learning/<topic-slug>/`. It **is** the learning state — committed to the graph, not scratch. On invocation, if the folder exists, **resume**: read the state, open with _"welcome back — last time you nailed X; the open edge was Y. Pick up there, or zoom out?"_ Otherwise, interview for the mission first.

Files (all markdown notes carry vault frontmatter — `date`, `description`, `tags: [learning, teach]` — and link into the graph):

- **`MISSION.md`** — the *why*. The concrete real-world goal driving this. Grounds every teaching decision. If vague, **interview before writing** — a bad mission is worse than none. Tie to [[North Star]] where it maps to a stated goal. Keep it to a screen.
- **`GLOSSARY.md`** — the canonical, opinionated language for the topic. Add a term only once Charles can *use* it correctly (compression = evidence of understanding). Tight one-line definitions; pick the best word, list aliases to avoid.
- **`learning-records/NNNN-slug.md`** — ADR-style, decision-grade insights (sequential numbering). Write one when: genuine understanding is demonstrated (sets a new floor), prior knowledge is disclosed, a misconception is corrected, or the mission shifts. Not a journal — coverage ≠ learning. Mark superseded records rather than deleting.
- **`RESOURCES.md`** — curated, high-trust sources, split **Knowledge** (books, primary sources, expert articles) and **Wisdom** (communities to test skills in the real world). Annotate every entry with "use for…". Never teach from parametric guessing — ground in these. Note a `## Gaps` section for missing areas.
- **`lessons/NNNN-slug.md`** — the primary unit of teaching. One self-contained lesson per file, teaching **ONE thing** tied to the mission, completable fast for a tangible win. Littered with citations to `RESOURCES.md`. Markdown vault notes (graph-linked); offer to render a lesson to a styled printable HTML on request.
- **`NOTES.md`** — scratchpad for Charles's teaching preferences and working notes.

## Philosophy — Knowledge, Skills, Wisdom

Deep learning needs three things: **Knowledge** (from high-trust resources), **Skills** (acquired through interactive lessons you devise), and **Wisdom** (from real-world practice / community). Before `RESOURCES.md` is populated, prioritize finding trusted sources. Some topics lean knowledge-heavy (theory), others skill-heavy (anything practiced) — calibrate.

## Zone of Proximal Development (the core technique)

Every lesson should challenge **"just enough"** — past what Charles can do alone, reachable with guidance. Too easy → boredom; too hard → overwhelm. This is the payoff of statefulness: target the zone using the persisted model of current mastery.

- **Retrieval practice is the sensor.** End each chunk with a scenario question ("what would you do if…?", "why does X fail here?"). A wrong answer → scaffold back; an effortless one → push further. Use the signal to **choose the next thing to teach**, not just confirm the last.
- **Scaffold, then fade** — heavy support at the edge, removed as mastery grows.
- **Sequence by readiness + dependency**, not a fixed curriculum.
- Record demonstrated mastery in `learning-records/` so the floor — and the zone — advance each session.

## Mission grounding

Every lesson traces back to `MISSION.md`. If the mission is unclear, that's the first job — interview Charles on why he wants this. Ungrounded knowledge feels abstract and you lose the basis for judging what to teach next. Revise the mission when reality shifts.

## Acquiring Wisdom

When a question needs wisdom (judgment from real practice), attempt an answer but ultimately point Charles to a **community** (forum, subreddit, local group, class) where he can test skills for real. Find high-reputation ones; respect it if he opts out.

## Index & graph

- New topic → add a line under Learning in [[personal/Index.md|Index]].
- Link the workspace to [[North Star]] (mission), relevant projects, and related learning notes. No orphan notes.

## Constraints

- **Stateful first** — always read the workspace state on resume; never restart from blank.
- **Compact state** — `MISSION.md` and `learning-records` are a compass, not a journal. Read them, don't re-derive.
- **One mission per workspace** — two unrelated topics = two workspaces.
- **Cite everything; never trust parametric knowledge** for claims.
- **Evidence before glossary/records** — promote a term or write a record only once understanding is demonstrated.
