# /garden — Apply the Graph Gardener Queue

Review and apply the Graph Gardener's proposals. The gardener (`graph_gardener.py`, Stop-triggered)
_produces_ `.brain/gardener-<context>.md`; `/garden` is the **apply side** — you review each
proposal, apply the ones you approve (reusing `/find` for orphans), and dismiss the rest so they
don't come back. Closes the produce → review → apply loop. Design: `thinking/2026-06-23-garden-apply-skill-design.md`.

**Explicit-invoke only.** A deliberate review pass you choose to run, not auto-fired.

## Usage

```
/garden        # review and apply the pending gardener proposals
```

## Process

1. **Acquire the apply-lock.** Run
   `uv run python .claude/scripts/graph_gardener.py --acquire-lock`. This writes `.brain/.garden-lock`
   so the gardener's detached Stop-hook workers **bail instead of regenerating the queue** while you
   apply — without it, a worker can overwrite `.brain/gardener-<context>.md` mid-pass (the
   producer/consumer race; see `thinking/2026-06-27-gardener-apply-lock-race-fix-design.md`). The lock
   self-heals after 30 min if a pass is abandoned. **You MUST release it before exiting** (step 6).

2. **Load the queue.** Read `.brain/gardener-<context>.md` (`<context>` from `.vault-context`,
   default `personal`). If it's absent or has no proposals, **release the lock** (step 6), report
   "🌱 nothing pending" plus the last gardener-run time, and stop. Briefly note the
   `## Applied (auto-repairs)` section if present — those already happened (broken links the gardener
   auto-fixed); they're for transparency, nothing to do.

3. **Walk the `## Proposed` subsections, easiest → hardest:** broken links → unprofiled people →
   auto-memory drift → missing links → index drift → stranded branches → orphans. For each non-empty
   subsection, present the items and use **`AskUserQuestion` (multiSelect)** to let Charles choose
   **Apply / Dismiss / Skip** per item (batch within the category). Then act:

   - **Broken links (unresolved).** The line carries candidate targets ("did you mean `Y`, `Z`?").
     Show them; Charles picks the right one (or "create the note" / "remove the link"). Apply →
     `Edit` the note, replacing `[[X]]` with `[[chosen]]`.
   - **Unprofiled people.** A `[[Name]]` indexed in `org/People & Context.md` with no
     `org/people/<Name>.md` profile — a **distinct disposition, NOT** the generic "create or remove"
     broken-link flow above. No-op if the `### Unprofiled people` subsection is absent. Per person, offer:
     - **Profile** → dispatch the **`people-profiler`** agent (`.claude/agents/people-profiler.md`, cheap
       tier) to _draft_ `org/people/<Name>.md` from real vault evidence (org schema: `role`/`team`,
       wikilinks back to the index + mentions). **Review the draft before the write** (every-edit-confirmed);
       **no fabrication** — leave `role`/`team` blank if the vault doesn't state them.
     - **Dismiss** → append the verbatim `unprofiled|<name>` gsig token (read off the line) to
       `.claude/data/gardener-dismissed.json`.
     - **Skip** → leave in the queue.
   - **Auto-memory drift.** A durable fact wikilinked but living only in machine-local auto-memory
     (`~/.claude/.../memory/<slug>.md`) — it must move **into** the vault (auto-memory → vault, never the
     reverse; the Memory & Self-Sufficiency rule). No-op if `### Auto-memory drift` is absent. Per item:
     - **Promote** → read the auto-memory file, draft a vault note in the right folder (by content) with
       enforced frontmatter + ≥1 `[[wikilink]]` + the appropriate index entry; **review before writing**.
       Optionally trim the auto-memory entry to a pointer into the new note (one-way dependency).
     - **Unlink** → strip the brackets where the concept isn't worth its own node.
     - **Dismiss** → append the verbatim `memdrift|<slug>` gsig token (read off the line) to
       `.claude/data/gardener-dismissed.json`.
     - **Skip** → leave in the queue.
   - **Missing links.** Show the exact prose and the suggested `[[Target]]`. On confirm → `Edit` the
     note, wrapping that exact prose in `[[Target]]` (preserve surrounding text exactly).
   - **Index drift.** Show the note and the target index. On confirm → append the appropriate entry to
     that index file (follow the index's existing line format).
   - **Stranded branches.** A git branch holding net-new notes not on `main`. No-op if `### Stranded
branches` is absent. Per branch, show the net-new file(s) and offer:
     - **Port** → `git checkout <branch> -- <files>`, then verify each file is truly absent from / not
       stale on `main`, add the relevant index entries, and stage (conductor judgment; review before
       committing).
     - **Delete branch** → explicit confirm, then `git push origin --delete <branch>` + prune (the
       dead/merged case).
     - **Dismiss** → append the verbatim `branch|<name>` gsig token (read off the line) to
       `.claude/data/gardener-dismissed.json` (a branch kept on purpose).
     - **Skip** → leave in the queue.
   - **Orphans.** The note links to nothing. Run its text/description through the semantic engine —
     `uv run --script .claude/scripts/semantic_index.py search "<note topic>"` — present the top link
     targets, Charles picks one or more, then `Edit` the note to add the `[[link]](s)` in a natural spot.

3b. **Weak connections (live semantic pass).** A _pull_ lane — generated now, not from the producer
queue. Run `uv run .claude/scripts/graph_cli.py --gaps --top 10` (graphmark's
similar-but-unlinked pairs, in the 0.6–0.92 band, transient task-logs + dismissed pairs already
filtered). **No-op** if it returns `[]` or the semantic index is absent. For each pair `{a, b, score, sig}`,
show both notes' context (snippets / `graph_cli.py --neighborhood`) and offer:

- **Link** → pick the better-fit note, draft `- [[B]] — <one-line reason>` under its `## Related`
  section (create the section if absent), drawing the reason from both notes. Show the exact edit;
  apply on confirm. One direction suffices (Obsidian backlinks). Validate frontmatter + wikilinks.
- **Dismiss** → run `uv run .claude/scripts/graph_cli.py --dismiss "<a>" "<b>"` (same store /connect
  uses — graphmark's content-hash store in `.claude/data/connect-dismissed.json`, which is what
  `--gaps` actually filters against; a sig appended to `gardener-dismissed.json` would never
  suppress anything here).
- **Skip** → leave it (resurfaces next pass).

4. **Show every edit before writing.** Never apply without an explicit pick/confirm. Validate
   frontmatter + wikilinks on every write (the contract still holds).

5. **Resolve the queue** after the pass (safe now — the lock keeps workers out):
   - **Applied** → remove from the queue file.
   - **Dismissed** → remove from the queue file **and** append its signature to the suppress-list so
     the gardener won't re-propose it. Each proposal line carries an invisible `<!-- gsig: ... -->`
     token — extract that token verbatim and append it to `.claude/data/gardener-dismissed.json` under
     the `"dismissed"` list (create the file as `{"dismissed": []}` if absent). Do NOT recompute the
     signature — read it off the line.
   - **Skipped** → leave in the queue for next time.
   - Rewrite `.brain/gardener-<context>.md` with only the skipped items, preserving its frontmatter and
     the `## Applied` section. If nothing remains, you may delete the file.

6. **Release the apply-lock.** Run
   `uv run python .claude/scripts/graph_gardener.py --release-lock`. This is the **last action of every
   exit path** — the normal end, the "nothing pending" early-exit (step 2), and any error/abort.
   Leaving it set blocks queue regeneration until the 30-min TTL clears. Releasing also **stamps
   "last gardened"** (`last_applied_ts`), which drives the escalating session-start / `/standup` nudge —
   so running `/garden` resets the reminder.

7. **Report** what was applied, dismissed, and skipped, with the note paths and links touched.

## Constraints

- **Always release the lock** — acquire it first (step 1), release it on **every** exit path (step 6),
  including "nothing pending" and any error. A held lock blocks the gardener until the 30-min TTL.
- **Every edit confirmed** — `/garden` proposes; Charles disposes. Nothing auto-applies.
- **Reuse, don't rebuild** — link targets for orphans come from `/find`'s `semantic_index.py`; the
  proposals come from the gardener queue. No new analysis engine.
- **Conductor-aware** — the `semantic_index.py` calls are cheap subprocesses returning JSON; don't
  bulk-read the vault.
- **Fail-soft on the queue** — a missing, empty, or malformed queue is reported and exits cleanly,
  never a crash.
- **Signature fidelity** — dismissals MUST use the `gsig` token read verbatim from the queue line, so
  the gardener's suppress check matches exactly. Mis-formatting a signature silently breaks
  convergence (the dismissed item returns).
- **Graph contract** — every applied edit keeps frontmatter valid and adds real `[[wikilinks]]`; no
  orphan notes, no broken links introduced.
