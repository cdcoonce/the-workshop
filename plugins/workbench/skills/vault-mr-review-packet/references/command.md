# /mr-review-packet — Reviewer Walkthrough in the MR Description

Turn an intimidating, large MR into a navigable map a reviewer can walk on their own. The walkthrough is the connective tissue between the diff and the reviewer's understanding — not a summary of the code, a _guide_ to reading it. It lives in the MR description itself.

**Standalone packet files are retired (2026-08-24).** A committed `docs/review/*-review-packet.md` is a point-in-time document describing a moving branch — every merge into the source branch silently invalidates it, and reviews came back rejected over documentation misalignment. The MR description is the artifact reviewers actually read and judge against, and it lives next to the diff it describes. When the user asks for a "review packet", build this: the same walkthrough, delivered as the description.

## When to run

- A large MR (many files, many commits) needs review and the raw diff is too much to parse cold.
- The user wants a reviewer-facing walkthrough (e.g. for Biodun, Sowan).
- The source branch moved under an already-open promotion MR and the description no longer matches the tip.
- **Async review** — the reviewer reads on their own, unattended. (A live-meeting walkthrough is a different artifact: talking points, not a description.)

## Process

1. **Scope it with the user first.** Run `/grill-me` (or equivalent) to settle: who's the audience, and what's the spine (by feature/family vs pipeline stage vs review-priority). Don't assume — the spine decision drives the whole structure.

2. **Fetch the existing description before writing.** `glab api "projects/<enc>/merge_requests/<iid>"` — save it to a scratch file. The rewrite replaces the walkthrough, not the MR's history: preserve whatever still earns its place (test-plan checklist, supersedes/incident notes, links to prior MRs). Surgical edits beat clobbering a good description.

3. **Build context from the real code — and report what you find.** Read the source at the branch tip, not old summaries. Verify every feature-area claim against current code before repeating it. A walkthrough that surfaces a real bug during its own construction is doing its job — flag it to the user immediately rather than silently working around it.

4. **Draft the walkthrough** (adapt the anatomy to the MR — skip sections that don't apply):
   - **How to read this MR** — defang the file count: the diff's shape, what's tests/tooling/noise to skip, what's the real review surface, the honest "why so big."
   - **The big picture** — one diagram of the whole change; a table of the major pieces with status.
   - **Per-piece sections** — one per feature/family/module: a Mermaid flow map (source → transforms → output), the handful of files that actually matter (linked), sample output where it helps.
   - **Cross-cutting layers** — data quality / safety, hardening, etc. Often the highest-stakes section (the "why is it safe" argument) — give it real depth, not a one-liner. Count things accurately, don't round.
   - **Testing** — how we know it's correct; name any bugs the review process already caught.
   - **Go-live posture** — what's live vs dormant on merge, and what coordination is owned outside the MR.

5. **Link discipline.** An MR description does not resolve repo-relative paths the way a committed doc does — use full blob URLs pinned to the source branch, or MR-diff anchors where landing on the diff specifically matters. **Attach gitignored outputs** (sample CSVs, workbooks) as MR uploads referenced from the description or a comment — never commit them.

6. **Deliver through the API, then verify.**
   - Write the description to a Markdown file with real newlines.
   - Update with a JSON body and explicit Content-Type — wrap the file as `{"description": ...}` and send `glab api "projects/<enc>/merge_requests/<iid>" -X PUT -H "Content-Type: application/json" --input <payload.json>`. (glab's `-F` does not read `@file` values, and glab form fields have silently dropped parameters before — the JSON body is the reliable path.)
   - Read the description back and diff it against the file, then check the rendered MR on GitLab itself: links resolve, Mermaid renders.
   - Write the vault's thin pointer note (wikilinks + decision log + thinking) — the walkthrough lives in the description; understanding lives in the vault graph.
   - On GitHub, the same flow is `gh pr edit <n> --body-file <file>`.

7. **Keep it current.** While the MR stays open, every merge into its source branch is a description-refresh trigger: re-verify the feature areas the merge touched and update the description in the same motion. A stale walkthrough is the same defect the retired packets had.

## Gotchas

- **Verify "dormant"/feature-flag claims against both gates in the code, not the one you remember.** A walkthrough that reports a feature as dormant based on one flag when a second flag actually gates it will mislead the reviewer into approving something live.
- **GitLab clips Mermaid box text.** With the default `htmlLabels: true`, GitLab measures label width with a different font than it renders, so longer labels overflow and get cut off inside the box. Fix: prepend `%%{init: {"flowchart": {"htmlLabels": false}}}%%` (forces SVG-text measurement) and keep labels short — push detail into the prose beside the diagram, not the nodes. **`mermaid-cli` renders correctly and does _not_ reproduce this**, so a diagram that looks clean locally can still clip on GitLab — verify the rendered description on GitLab itself before handing off.

## Related

- `/grill-me` — the scoping front-end (step 1)
- `/gitlab-mr-create` — the same description-file + API read-back discipline at MR creation time
- [[Key Decisions]] — description-canonical convention (packets retired 2026-08-24; the walkthrough is the MR description, the vault keeps a pointer note)
- [[Gotchas]] — dormancy/two-gate trap
