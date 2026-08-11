# /connect — Autonomous Connection Pass

Strengthen the brain's graph in one launch. `/connect` takes the Brain Map's **weak connections**
(semantically-similar-but-unlinked note pairs), **autonomously drafts** a reasoned `## Related` link
for each, shows you the whole batch **once**, and on your OK writes + commits them. The autonomous
counterpart to `/garden`'s interactive weak-connections lane — same signal, less ceremony.
Design: `thinking/2026-06-27-connect-autonomous-connection-pass-design.md`.

**Human-launched only.** You typing `/connect` *is* the sanctioned run (Constitution §2: "inside a
human-launched run, autonomous vault writes are allowed; git history is the undo"). It never fires on a
timer; it only ever **appends `## Related` links** — never edits prose.

## Usage

```
/connect            # draft + batch-apply the top weak connections
/connect 5          # cap at N pairs (default 12)
/connect --bridges  # "thicken" mode — target structurally-siloed notes (reachable only via a bridge)
```

> **Why a generous N:** score and degree do **not** separate real connections from vocabulary-twins
> (verified 2026-06-27 — kept and rejected pairs overlapped on both). The semantic **drafter** is the
> only reliable discriminator, and it filters cheaply in one call — so feed it a healthy pool and let it
> reject, rather than pre-filtering by a signal that can't discriminate.

## Process

1. **Candidates.** Run `uv run .claude/scripts/graph_cli.py --gaps --top <N>` (default N=12) — or, in
   **`--bridges` ("thicken") mode**, `--gaps --near-bridges --top <N>` to prioritize connections for
   **structurally-siloed** notes (those reachable only via a single bridge — the under-integrated
   periphery). Same loop either way; bridges only *target* where to look, never force a link. These are
   band-filtered (0.6–0.92), novelty-ranked (non-hub, cross-folder first), and suppress-aware already.
   If it returns `[]` (or the semantic index is absent), report "🌿 no weak connections pending" and
   stop — nothing to do.

2. **Draft (delegate — conductor stays lean).** Dispatch **one cheap subagent** (Sonnet/Haiku) with the
   full candidate list. For each pair it reads both notes and returns structured JSON:
   `{a, b, score, sig, target, related_line, has_related}` where —
   - `target` = the better-fit home note (the more specific/active one usually links to the more
     foundational; pick whichever reads naturally),
   - `related_line` = `- [[<other>]] — <one-line reason drawn from BOTH notes>` (the reason must be real,
     grounded in the notes — no fabrication),
   - `has_related` = whether `target` already has a `## Related` section.
   The conductor works from these drafts; it does **not** bulk-read the notes itself.

3. **Batch preview (the gate — nothing is written before this).** Present **all** drafted edits at once
   — for each: `target` → `related_line` (+ score). Offer them via `AskUserQuestion` (multiSelect) so
   Charles picks which to apply; selected = apply, unpicked = dismiss. **Constraints that matter:**
   `AskUserQuestion` allows ≤4 options per question and **requires ≥1 selection to submit** — so if
   there are >3 pairs, split across multiple questions, and **every group MUST include an explicit
   "None of these" option** (≤3 real pairs + "None" per group) so Charles can decline a whole group
   without being forced to pick. Equivalently, if he prefers, accept a free-text list of pair numbers.

4. **Apply** (only the selected). For each: `Edit` the `target` note to append `related_line` under its
   `## Related` section (create `## Related` at the end of the note if `has_related` is false). Validate:
   frontmatter still valid, the new `[[wikilink]]` resolves (run a `graph_cli`/gardener dry-run on the
   touched notes to confirm **no broken links introduced**), append-only (never alter existing prose).

5. **Resolve + report.**
   - **Deselected** pairs → run `uv run .claude/scripts/graph_cli.py --dismiss "<a>" "<b>"` per pair.
     This records a **content-aware** dismissal (fingerprints both notes) in `.claude/data/connect-dismissed.json`
     — it auto-expires and the pair re-surfaces if *either note later changes*, so a "no" is only as
     permanent as the notes that justified it. Never blocks a manual link; only suppresses the suggestion.
   - **Commit** the batch (`vault: /connect — N weak-connection links`), letting the normal vault sync
     carry it. Git history is the audit/undo (§2).
   - **Report** every link added: `target`, target-of-link, reason, score. The report + git diff are the
     after-the-fact review surface.

## Constraints

- **Human-launched, append-only, bounded.** Only appends `## Related` links to existing notes; never
  edits prose, never deletes, never auto-merges to any code repo. Capped at N.
- **No fabrication** — every reason is grounded in both notes' actual content (anti-goal §6). A pair
  whose notes don't actually justify a connection should be dropped by the drafter, not invented.
- **One gate, not none** — the batch preview (step 3) is mandatory; nothing is written before Charles
  confirms. Autonomy is in the *drafting*, not the *landing*.
- **Reuse, don't rebuild** — candidates come from `graph_cli --gaps`; dismissals are **content-aware**
  (`graph_cli --dismiss`, fingerprinted in `connect-dismissed.json`) so they expire when notes evolve.
  No new analysis engine.
- **Conductor-aware** — the per-pair note reads happen in the subagent, never the live session.
- **Graph contract** — every applied edit keeps frontmatter valid and adds a real, resolving
  `[[wikilink]]`; no broken links, no orphans.
