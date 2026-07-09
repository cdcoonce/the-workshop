# /mr-review-packet — Self-Guided Reviewer Packet for a Large MR

Turn an intimidating, large MR into a navigable map a reviewer can walk on their own. The packet is the connective tissue between the diff and the reviewer's understanding — not a summary of the code, a *guide* to reading it.

## When to run

- A large MR (many files, many commits) needs review and the raw diff is too much to parse cold.
- The user wants a reviewer-facing walkthrough (e.g. for Biodun, Sowan).
- **Async review** — the reviewer reads on their own, unattended. (A live-meeting walkthrough is a different artifact: talking points, not a packet.)

## Process

1. **Scope it with the user first.** Run `/grill-me` (or equivalent) to settle: who's the audience, what's the spine (by feature/family vs pipeline stage vs review-priority), what format, where it lives. Don't assume — the spine decision drives the whole document structure.

2. **Decide where it lives.** The packet is canonical **in the project repo**: `docs/review/<mr>-review-packet.md`, committed on the MR branch so it ships inside the MR's own file tree. The vault keeps only a thin **pointer note** (wikilinks + decision log + thinking) — execution-layer artifact goes to the repo, understanding goes to the vault graph.

3. **Build context before writing — and report what you find.** Read the real code, not the MR description. Verify claims against the source; don't take the MR's own summary at face value. A review packet that surfaces a real bug during its own construction is doing its job — flag it to the user immediately rather than silently working around it.

4. **Draft the packet** (adapt the anatomy to the MR — skip sections that don't apply):
   - **How to read this MR** — defang the file count: what's tests/tooling/noise to skip, what's the real review surface, the honest "why so big."
   - **The big picture** — one diagram of the whole change; a table of the major pieces with status.
   - **Per-piece sections** — one per feature/family/module: a Mermaid flow map (source → transforms → output), the handful of files that actually matter (linked), and any sample output.
   - **Cross-cutting layers** — data quality / safety, hardening, etc. This is often the highest-stakes section (the "why is it safe" argument) — give it real depth, not a one-liner. Count things accurately, don't round.
   - **Testing** — how we know it's correct; name any bugs the review process already caught.
   - **Go-live posture** — what's live vs dormant on merge, and what coordination is owned outside the MR.
   - **Artifacts index** — sample outputs, validation reports, generator scripts.

5. **Link discipline.** Repo-relative paths for committed files (clean, rebase-proof). GitLab/GitHub MR-diff anchors only where landing on the diff specifically matters. **Attach gitignored outputs** (sample CSVs, workbooks) to the MR as uploads rather than committing them.

6. **Deliver.**
   - Commit the packet to the repo (canonical) + write the vault pointer note.
   - Optionally update the MR description for accuracy — surgical edits, don't clobber a good existing one.
   - Optionally post an MR comment attaching output samples.
   - **Verify links resolve and CI is green before handing off.** A broken link in a reviewer-facing document defeats the purpose.

## Gotchas

- **Verify "dormant"/feature-flag claims against both gates in the code, not the one you remember.** A packet that reports a feature as dormant based on one flag when a second flag actually gates it will mislead the reviewer into approving something live.
- **Mermaid renders in GitLab/GitHub markdown** but not in plain pandoc docx without extra tooling — pick the format to match where the packet will actually be read.
- **On an SSH-blocked network, push via HTTPS through the platform's credential helper** (e.g. `glab`) rather than fighting SSH.

## Related

- `/grill-me` — the scoping front-end (step 1)
- [[Key Decisions]] — packet-location convention (repo canonical, vault pointer)
- [[Gotchas]] — dormancy/two-gate trap, SSH-blocked push workaround
