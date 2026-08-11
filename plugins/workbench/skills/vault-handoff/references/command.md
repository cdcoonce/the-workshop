# /handoff — Refresh the Rolling Orchestrator Handoff

Rewrite the machine-scoped handoff digest (`.brain/handoff-<context>.md`) so the next session — or the same session post-compaction — resumes cleanly. The handoff is the **single deterministic resume point**: `session-start.py` injects it at every session start, so the next session always reads it without anyone having to remember to.

## When to run

- **Session end** — invoked by `/wrap-up`.
- **Before context compaction** — the PreCompact hook reminds you; refresh so post-compaction context resumes cleanly.
- **Switching machines mid-thread** — so the other machine picks up accurately.
- Any time current state has drifted materially from what the handoff says.

## Procedure

1. **Pick the file.** Read `.vault-context` (`work` | `personal`; default `personal`). Target `.brain/handoff-<context>.md`. If this session did substantial work in the _other_ context too, update both.
2. **Consolidate the notebook first.** Read the live session notebook (`.brain/notebook-<context>.md`) if it exists — it's the hippocampus, the auto-distilled short-term state for this session. Use it as the **primary raw input** for the handoff: promote its durable threads, decisions, and open loops into the curated handoff below. This is the one-directional flow — notebook → handoff, never the reverse — so the two never drift. The notebook is disposable working memory; the handoff is its consolidated, synced trace. (The notebook is gitignored and machine-local; don't try to commit it.)
3. **Overwrite in place — don't append.** The handoff is a _digest that guides_, not a log that grows. Replace stale content; keep it scannable (aim under ~50 lines). Transcripts live in `thinking/session-logs/`; durable knowledge lives in `brain/`. The handoff holds only what the next session needs to **resume**.
4. **Write absolute dates.** Convert "today / tomorrow / last night" to `YYYY-MM-DD` — the reader is a future session with no clock context. Update the `_Updated YYYY-MM-DD_` line.
5. **Cover these sections** (adapt to context; skip any that are empty):
   - **Resume from here / Next steps** — lead with the single most important thing to do next. On a work machine, lead with Charles's _stated_ plan if there is one, then clearly-separated inferred background.
   - **Where we are** — 1–2 sentences of orientation.
   - **What's running** — background processes, in-flight drains/PRs, anything mid-flight (or "nothing").
   - **Open threads** — active work, one line each, with `[[wikilinks]]` and issue/PR refs.
   - **Mode** — the working posture (orchestration / building / review) and any standing working-style preferences.
6. **Link, don't dump.** Point into the vault (`[[notes]]`, `brain/Gotchas.md`, repo issue/PR numbers) instead of restating detail.
7. **Commit it.** The handoff rides git to the other machine. `/wrap-up` performs the push; a standalone `/handoff` should commit + push itself (via `/sync`).

## Constraints

- **Digest, not history.** If it grows past a screen, you're logging — cut it back.
- **`.brain/` is machine infrastructure**, hidden from Obsidian, synced via git. Never move the handoff into the Obsidian-visible tree.
- **Keep it true.** The handoff is the resume contract; a stale handoff is worse than none because it sends the next session down the wrong path.
