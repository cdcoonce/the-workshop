# /cold-read — Adversarial Spec Gate Before the Executor

Attack a dispatched issue's **specification** before an executor spends a run on it. The cold read reads the issue the way the executor will: cold, with no memory of the conversation that shaped it. It finds the places where a competent builder would have to guess — and a guess made unattended is a wasted run.

This is the pre-build twin of `adversarial-review`. That skill attacks finished work; this one attacks the words that describe unfinished work. It is cheap here and expensive later: an ambiguous spec does not fail fast, it fails plausibly.

Ships as the gate between [/dispatch](../../vault-dispatch/references/command.md) step 5 (file) and step 7 (promote).

## When to run

- Immediately after `/dispatch` files an issue, before the promotion decision.
- Before any manual `--promote` of a `proposed` issue, whoever filed it — Scout proposals especially, since they were never shaped by a human.
- On a `decompose:ready` parent's children, individually, after decomposition. The parent's clarity says nothing about the children's.
- When an executor run quarantines on `question` or `scope` — cold-read the issue before re-filing, and record which detector should have caught it.

NOT for: issues already promoted or in flight (that ship has sailed — fix forward), or work Charles is building live.

## The cold constraint

**The reader must not have seen the shaping conversation.** This is the whole mechanism; everything else is a checklist.

- **Default:** dispatch a subagent whose entire prompt is the issue body, the repo name, and this procedure. Do not summarize the conversation into it. Do not "helpfully" add the context that makes it make sense — that context is exactly what the executor will not have.
- **If a subagent is unavailable:** say so out loud, then re-derive strictly from `gh issue view <N> --repo <repo>` output and treat every claim in your own memory as unavailable. This is weaker and must be labeled weaker in the digest. Never silently downgrade.
- The reader may read the target repo **only** to resolve evidence the issue cites — does this file exist, does this issue number resolve, and (detector 8) does the cited code actually behave as the body claims. It may not go code-archaeologing to reconstruct intent the issue failed to state. Reading a function to check a stated fact is verification; reading the codebase to work out what the issue _meant_ is the finding.

## Detectors

Run all ten. Each has a test that returns yes or no — record which ones you ran and what you found, per detector. "Looks fine" is not a result.

1. **Unbound referent.** Every "it", "this", "the existing X", "the current behavior" resolves to a named file, function, flag, or issue number _inside the body_.
   → Test: can you point at the noun? If resolving it needs the conversation, it is unbound.

2. **Unverifiable acceptance criterion.** Each checkbox is answerable yes/no from the repo and the issue alone.
   → Test: could two people who disagree be forced to the same verdict? "Handles errors gracefully" fails. "Raises `ValueError` when `zone` is None" passes.

3. **Toothless test criterion.** `/dispatch` requires a test criterion; this checks it has teeth.
   → Test: if the feature were absent — or the bug reintroduced — would the named test go red? A criterion satisfied by asserting the code's own output on its own fixture is a tautology. Name the mutation that should break it.

4. **Missing anti-scope.** The body states what the executor must NOT touch.
   → Test: name one adjacent file or behavior an over-eager executor would plausibly "improve." If the body does not forbid it, that is the finding.

5. **Unresolvable evidence.** Every path the body names resolves, in either role it plays: as **evidence** (cited as proof of existing state — a file, an issue/PR number, a vault note) or as a **destination** (named as where the slice will create something new — a test file, a module, a fixture).
   → Test: run `uv run --with 'graphmark>=0.7,<0.8' --with pyyaml python "<engine>/cold_read_evidence.py" --repo <repo> --repo-dir <local checkout> --issue <N> --json` (add `--vault-root <absolute vault path>` when the body has `[[wikilinks]]`). It resolves every path, issue/PR number, commit SHA and `[[wikilink]]` the script can extract from the body against the target repo's default branch — never every citation, and never a SHA the body pins: the script reads no such pin from the body text. If the body pins a SHA (`at commit abc1234`, a specific tag), pass `--ref <that sha>` yourself; the resolved-ref line in the output tells you which ref it actually checked.

   A corpus review scored an earlier all-or-nothing BLOCKING verdict at roughly 2% precision across 41 real cold reads — text-only resolution cannot rule out a subtree-relative path, a cross-repo citation, or a branch name typed bare, so no verdict from this script is trustworthy as a flat pass/fail. The output instead separates what it trusts from what it doesn't:

   - **`rows` (severity CHECK) are hints, not findings.** Verify each with one unpiped command before writing it up as a detector-5 finding — the row names the token, its class, and why the resolver couldn't trust it outright, but a text resolver can be wrong in either direction (a subtree-relative path, a branch name, a citation into a different repo can all read CHECK on a perfectly good body). A row's `result` (`UNRESOLVED`, `PARENT_ONLY`, `ABSENT`, `AMBIGUOUS_SUFFIX`, `REFERENCED_ONLY`, `NOT_FOUND`, `COMMIT_MISSING`, `COMMIT_EXISTS_UNREACHABLE`, `PROSE_LINE_CITATION`, `UNKNOWN_REPO_ALIAS`, `OUTSIDE_REPO`, `DIRECTORY_NOT_FILE`, `BINARY_FILE`, `ERROR`, ...) says what to check for, not what to conclude.
   - **Everything not in `rows` (severity OK) needs no re-check** — a path or directory that resolves exactly or by an unambiguous segment-boundary suffix match, an issue/PR ref with a real state, a commit reachable from the ref (or from a named remote-tracking ref), a wikilink that resolves, a branch/tag or `owner/repo` the script confirmed against git/GitHub.
   - **`evidence_lines` still need the line-text-vs-claim comparison.** A resolved `path:line` citation is OK severity (the file and range are real) but still appears here with the actual text at that line — read it against the claim; it blocks only when the line no longer supports what the body says it does.
   - **`assumed_repo_refs` must be confirmed to target this repo** whenever the body concerns more than one repo. A bare `#N` is resolved against `--repo` by default and listed here with that assumption spelled out — neither OK nor a CHECK finding on its own, but if the body also names another `owner/repo` or a known sibling repo, the script already promotes that bare ref into `rows` with the hint "body mentions other repos; confirm target"; read that promotion, don't second-guess a bare `#N` the script left alone.
   - **`INCOMPLETE`:** the classes listed under `not_run` (no gh auth, a non-404 gh failure, missing graphmark with wikilinks present, a `--vault-root` that isn't a real vault) and the reasons under `input_errors` (bad `--repo-dir`, an origin mismatch, a bad `--ref`, a fetch failure, an empty body, zero extractable tokens) are resolved by hand, the old one-unpiped-command-each way, for those classes only.
   - **What the script cannot see is still the reader's job:** a reference named only in prose with no backticks and no "lines N-M" citation near it, or a claim about what a line of code _does_ (detector 8's concern, not this one's) — the script resolves existence, never behavior.

6. **Size lie.** The `afk-sized` claim survives the footprint the body actually implies.
   → Test: list the files the proposed behavior touches. A new module, a new mechanism, or changes persisting outside the issue's footprint is never `afk-sized` (precedent: afk#324, quarantined on scope after 4 attempts). If the implied slice count exceeds the Budget line, the Budget is the bug.

7. **Unauthorized decision.** A place where the executor must choose between two defensible approaches and the issue does not say which.
   → Test: read the Proposed behavior and ask "where would I, building this, have to invent policy?" Naming schemes, error-vs-skip, ordering, defaults. Every such fork is a finding unless the body picks a side.

8. **Unverified behavioral claim.** Detectors 1–7 interrogate the words against themselves; this one asks whether they are true. Every sentence of the form "X does Y" about existing code is a factual claim the executor will build on.
   → Test: for each one, name the line that makes it true. If the claim is about what a function _returns_ or _carries_, read the function — **resolving the symbol is not resolving the behavior**. Detector 5 answers "does `rebuild` exist at that line?"; this one answers "does it do what this paragraph says?" A premise no line supports is blocking, whatever else the issue gets right. Cheapest place to start: the sentence beginning "Since …" or "Because …" — that is where a spec states the fact its whole argument rests on, and it is the sentence least likely to have been checked (precedent: afk#919, whose false premise about `rebuild()`'s `attempts` count passed a seven-detector cold read, built at one attempt, went green on every gate, and had to be reverted).

9. **Unreachable bar.** Every numeric or threshold acceptance criterion names the mechanism by which a _faithful_ implementation attains it, using only what the spec itself authorizes.
   → Test: derive the bar from the spec's own tables and mechanics — simulate or count when cheap. A bar attainable only through behavior the spec forbids or never specifies is blocking: a gate-green run will still exist, but only by distortion, and the reviewer becomes the last line of defense. Detector 3 asks "would the test go red if the feature broke?"; this one asks "can the test go green without cheating?" (Precedent: kaggriculture#23 — "≥18 water ops/day" against a PLANT table supporting ~15; two gate-green attempts both faked it by double-watering, and the reviewer, not the gate, caught them. kaggriculture#29 — a crash-detection teeth-check demanded a raise surface through a never-raise safety shell, and its "fits 8 minutes" budget claim measured 12.5–17.5 min; two attempts burned.)

10. **Unchecked deny surface.** The paths the slice would _edit_ are tested against `PROTECTED_DENY_SURFACE` — the safety machinery an autonomous slice may never modify — by running the check, not by reading for it.
    → Test: run `uv run afk-driver --project <path-to-afk-agent-system> --repo <repo> --deny-surface-check <N>` (exit 0 clean, 1 matched, `--json` for the path list). It works for any enrolled repo, not just afk — the target-relative entries (`.afk/config.toml`, `.claude/settings.json`, `.claude/scripts/guard_worktree.py`) apply fleet-wide. If afk-driver is unavailable, say so and grep the body against the tuple in `src/afk_driver/deny_surface_scan.py` instead. Then classify each matched path with detector 5's evidence/destination split: a protected path cited as **evidence** of where a bug lives is not a target and is not a finding; one named as a **destination** is blocking — the slice must be hand-built, labelled `deny-surface` + `requires:human`. The check over-fires on citations by design (afk#1231, `cold-read:pass`, flagged only for citing `executor.py:504-508` as evidence while its own anti-scope forbids touching it), so it is a prompt to look, never an auto-verdict. Run it anyway: measured 2026-08-09 over afk's 22 auto-promotable issues, LLM cold reads caught deny-surface at **3 of 11**, and the misses share one signature — the reader checked whether a _neighbouring_ file was protected, wrote a careful anti-scope forbidding edits to it, and never checked the file being edited (afk#1170; afk#1171; afk#1208, whose reader had `deny_surface_scan.py` open and quoted line 106 without reading the tuple twelve lines above). This is a set-membership test against a literal tuple. Do not decide it by prose.

## Every finding carries a default

A finding that ends in a question blocks. A finding that ends in a proposed default is one word from resolved. Write each as:

> **[detector] <what is ambiguous>.** Default: I'll <specific choice> because <reason>. Say otherwise to change it.

Charles reads a list of defaults and answers only the ones he disagrees with. Silence is assent — so the default must be one you are genuinely willing to ship, not a placeholder.

## Procedure

1. **Before dispatching the subagent:** expand `<engine>` — the same placeholder `vault-audit` and `vault-wrap-up` use — and the local checkout path into real absolute paths in detector 5's procedure text; the subagent cannot resolve `<engine>` itself. Add `--vault-root <absolute vault path>` when the body has `[[wikilinks]]`, and include `--with pyyaml` alongside `--with 'graphmark>=0.7,<0.8'` in the command line. State plainly, in the dispatch, that this expansion was done; a subagent handed the literal placeholder cannot run the script.
2. **Fetch the issue cold.** `gh issue view <N> --repo <repo> --comments` — a prior cold read's findings live in the comments. Note existing labels.
3. **Run all ten detectors** against the body. Record per-detector: ran / found N / found none, with the specific noun or criterion you checked. A detector you skipped is reported as skipped, not as clean.
4. **Resolve every path the body names** — evidence and destination alike (detector 5) — with the single `cold_read_evidence.py` invocation described there. Verify each `CHECK` row with one unpiped command before writing it up as a finding; `evidence_lines` still need the line-text-vs-claim read; `assumed_repo_refs` need confirming only when the body names more than one repo. Only a class listed under its `not_run`, or a reason under `input_errors`, falls back to resolving that evidence by hand.
5. **Assign a verdict:**
   - **BUILD** — zero blocking findings. Non-blocking defaults may still be listed; they do not gate.
   - **REWRITE** — findings exist and are fixable by editing the issue body. This is the common case. Produce the exact replacement text for each affected section, not a description of it.
   - **NOT-DISPATCH-READY** — the idea is not executor-implementable as scoped: a size lie, or ambiguity only Charles can resolve. Recommend `decompose:ready`, `daytime-only`, or back to `/grill`.
6. **Write the findings back to the issue** as a comment titled `## Cold read — <verdict>`. The ticket is the memory store; a cold read that lives only in this chat did not happen. Include the per-detector record so a later reader can tell a clean pass from a lazy one.
7. **Apply the label:** `cold-read:pass` on BUILD, `cold-read:rewrite` on REWRITE, `cold-read:blocked` on NOT-DISPATCH-READY. Skip silently if the repo lacks the label — the comment carries the verdict either way.
8. **On REWRITE:** edit the issue body with the replacement text, then say plainly that the body changed and re-state the verdict as BUILD. Do not re-run the cold read on your own edit — you are no longer cold to it. A second pass, if wanted, is a fresh subagent.
9. **Digest:** verdict, findings count by detector, whether the reader was truly cold or degraded, the label applied, and the promote command — or the reason promotion is withheld.

## Gate contract with /dispatch

- **No `proposed` issue is auto-promoted without a BUILD verdict from a cold reader that did not shape it.** This is an additional clause on `/dispatch`'s low-risk test, not a replacement for it: every existing clause still has to hold.
- A REWRITE resolved by editing the body clears the gate. A NOT-DISPATCH-READY does not, ever, without Charles.
- Cold read never promotes. It clears or withholds; the promote command is `/dispatch`'s to run or Charles's to paste.
- **A verdict is stamped to the fork-point SHA the reader checked.** If the fork branch moves past that SHA before dispatch — an integration lands, a prerequisite is pushed — the body's present-tense claims (rosters, "X does not exist yet", dependency status) may have rotted: re-run detectors 5 and 8 against the new SHA before promoting. (Precedent: kaggriculture#29 — its "two registered zoo members" claim went stale when the integration it waited behind registered four more; kaggriculture#41 — a "do not promote until #30/#31 merge" gate survived their landing and contradicted the updated status paragraph above it.)

## Anti-rubber-stamp

The failure mode of this skill is a confident BUILD on a vague issue — it is faster, it is agreeable, and nothing catches it until the run is gone.

- A BUILD verdict must name at least one referent it resolved and one anti-scope boundary it found stated. If you cannot, the issue is not clean; you did not look.
- A BUILD verdict must quote the detector-10 command it ran and its exit code. "No protected paths" asserted without the command is the exact miss this detector exists to close — seven of eleven readers wrote a confident anti-scope about a neighbouring file while editing a protected one. An unrun check is reported as skipped, never as clean.
- A first-ever cold read that finds nothing is suspicious, not impressive. Say so.
- Do not soften a finding because the issue is Charles's own. `/dispatch` shaped it in a conversation you are pretending not to have had; that is the point.
- Do not fix the code. Do not propose an implementation. If you catch yourself writing the diff, you have stopped reading the spec.

## Constraints

- **The spec, not the code.** Every finding must be a defect in the _words_ — including a sentence that is false about the code (detector 8). Reporting a false premise is a spec finding; fixing the code is not.
- **One issue per run.** Cold-reading a batch means skimming.
- **Never edit acceptance criteria to match what you think the executor will do.** Criteria describe what Charles wants; if they are wrong, that is a finding, not an edit.
- **Report degradation honestly.** A cold read run inside the shaping session's own context is worth less. Label it and let Charles decide whether to re-run it clean.
