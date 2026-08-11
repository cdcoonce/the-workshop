# /context-then-delegate — Resolve Context Before Writing a Delegated Prompt

Before writing a coding-agent prompt (e.g. for Cortex Code) for a task with real-world ambiguity, gather and resolve context from email/SharePoint/Slack first — cross-reference sources, confirm disputed facts against actual replies, and flag unresolved data issues explicitly — then write a self-contained scoped prompt with confirmed facts baked in and an explicit definition of done.

## When to run

- The task needs domain knowledge that lives outside the codebase: broker naming conventions, a person's answer to a disambiguation question, which file is the actual source of truth.
- Before delegating to a coding agent whose prompt would otherwise contain a TODO or a guess instead of a confirmed fact.

## Process

1. **Identify what's actually unresolved.** Before touching the coding agent, figure out which facts the task needs that aren't already settled — naming ambiguities, "is X the same as Y" questions, which file is the real source of truth. Write these down as the search targets.

2. **Search broadly and in parallel, then narrow.** Fire email search + SharePoint search + Slack search across plausible keywords concurrently — this is read-only research with no ordering dependency, so there's no reason to run it sequentially. Once a specific thread is found, follow it sequentially (a reply chain has to be read in order). When multiple candidate files/threads turn up, check dates/authors to figure out which is authoritative vs. superseded (e.g. an original ask vs. a further-developed version of the same workbook).

3. **Prefer resolved answers over the original question.** If the person who raised the ambiguity already got a reply, use the reply's answer, not just the original question — pull the full thread, not just the first match.

4. **Cross-reference conflicting sources rather than picking one.** When two files describe the same thing at different levels of completeness (e.g. a blank template vs. a partially-filled version), use both — one for structure, one for content — and say so explicitly in the prompt.

5. **Flag data problems found along the way — don't silently pass them through.** If cross-referencing surfaces something that looks wrong (a copy-paste error, an inconsistent mapping), call it out in the prompt as something to fix, not just data to ingest as-is.

6. **Respect binary/tracked-file boundaries.** Don't copy source reference files (spreadsheets, PDFs) into a git repo just to hand them to a coding agent — stage them somewhere scratch/session-local and point the prompt there; only derived, purpose-built artifacts (a CSV seed, code) belong in the repo.

7. **Write the prompt with facts resolved, not TODOs.** Use this scaffold — two independent uses converged on it organically:
   - **Task** — what the coding agent should build/produce.
   - **Background** — the real-world context needed to understand why.
   - **Source files** — where scratch/session-local reference material lives.
   - **Confirmed facts** — each stated as "X confirmed by Y's reply on Z," not "check with someone about X."
   - **Known issues** — data problems surfaced during research, flagged for the agent to handle, not silently ingest.
   - **Requirements** — what the output must do.
   - **Constraints** — what it must not do / boundaries.
   - **Definition of done** — explicit, checkable.

## Constraints

- Never hand off an unresolved ambiguity as a TODO in the prompt — resolve it first or flag it to the user as a blocker.
- Never copy source reference files into a tracked repo just to stage them for delegation.
- Cross-reference conflicting sources; don't silently pick one and discard the other's information.

## Related

- [[mr-review-packet]] — another "build context before writing" pattern, for reviewer-facing docs rather than coding-agent prompts.
