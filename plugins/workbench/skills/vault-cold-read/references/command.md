# /cold-read — Adversarial Spec Gate Before the Executor

Attack a dispatched issue's **specification** before an executor spends a run on it. The cold read reads the issue the way the executor will: cold, with no memory of the conversation that shaped it. It finds the places where a competent builder would have to guess — and a guess made unattended is a wasted run.

This is the pre-build twin of `adversarial-review`. That skill attacks finished work; this one attacks the words that describe unfinished work. It is cheap here and expensive later: an ambiguous spec does not fail fast, it fails plausibly.

Ships as the gate between [/dispatch](../../vault-dispatch/references/command.md) step 5 (file) and step 7 (promote).

## When to run

- Immediately after `/dispatch` files an issue, before the promotion decision.
- Before any manual `--promote` of a `proposed` issue, whoever filed it — Scout proposals especially, since they were never shaped by a human.
- On a `decompose:ready` parent's children, individually, after decomposition. The parent's clarity says nothing about the children's. Run the source-fidelity pass on each child with the parent's body as its source: the decomposer asks a child only for what to build and its acceptance criteria, so a parent's anti-scope, Budget and gate drop out silently. A per-child pass checks only that what a child claims is at least as strong as the parent, so a parent decision the child does not claim is out of its slice and gets no row there.
- Once per decomposed parent, over the whole child set, after the children's own reads and before any child is promoted: the [coverage pass](#the-coverage-pass-decomposed-parents). Whether the siblings together carry every parent criterion is its question, and no per-child read can answer it.
- When an executor run quarantines on `question` or `scope` — cold-read the issue before re-filing, and record which detector should have caught it.

NOT for: issues already promoted or in flight (that ship has sailed — fix forward), or work Charles is building live.

## The cold constraint

**The reader must not have seen the shaping conversation.** This is the whole mechanism; everything else is a checklist.

- **Default:** dispatch a subagent whose entire prompt is the issue body, the repo name, and this procedure. Do not summarize the conversation into it. Do not "helpfully" add the context that makes it make sense — that context is exactly what the executor will not have.
- **If a subagent is unavailable:** say so out loud, then re-derive strictly from `gh issue view <N> --repo <repo>` output and treat every claim in your own memory as unavailable. This is weaker and must be labeled weaker in the digest. Never silently downgrade.
- The reader may read the target repo **only** to resolve evidence the issue cites — does this file exist, does this issue number resolve, and (detector 8) does the cited code actually behave as the body claims — and to run the [probe builds](#probe-builds) below, which settle such questions by measuring them. It may not go code-archaeologing to reconstruct intent the issue failed to state. Reading a function to check a stated fact is verification; reading the codebase to work out what the issue _meant_ is the finding.

## Probe builds

A reader settles an empirical question by running it, not by reading about it. This is the default method. (Precedent: in the ragmark cold reads of 2026-09-26/27, where every reader had these rights, about half of the 47 findings were measured, and every case in which a later round caught what an earlier round had passed turned on execution.) A probe build reads the archive in order to run it, never to work out what the issue meant; the cold constraint's code-archaeology clause still holds.

- **Runnable gate.** A repo has a runnable gate when its `.afk/config.toml` has a `test_command`.
- **Fork point.** Build on the executor's fork point. The fork point is the first of these that applies:
  - the issue's Target: afk/epic-N branch, when the body carries one;
  - otherwise `integration_target` from the repo's `.afk/config.toml`;
  - otherwise `main`, afk's `DEFAULT_INTEGRATION_TARGET`.

  Fetch the local checkout, `git archive` the fork point's `origin/` branch into a fresh scratch directory from `mktemp -d`, outside every checkout, and record the SHA you archived. Never use a fixed path: parallel readers collided on a shared `scratchpad/probe`, and one of them ran `rm -rf` on it.

- **Baseline.** An archive has no `.git`. In the scratch directory, run `git init` and commit the archived tree as the baseline. Then run the gate once, unchanged, and record every test that is red at baseline. Only new failures are graded. A gate step that needs a remote ref, such as `verify-versions`, is skipped and named in the record.
- **Build from the body alone.** The faithful build implements the slice in the scratch tree from the issue body and nothing else. Every choice the build had to invent is a detector-7 finding.
- **Which build each detector runs.** Detectors whose tests name a build run that build:
  - detector 3 runs the named mutation against the faithful build;
  - detector 8 probes the claimed behaviour;
  - detector 9 runs the faithful build against each bar;
  - detector 11 runs the violating build.
- **Mutation tooling.** Mutations go through `detector-teeth-check`'s `teeth_check.py`, never a hand-rolled mutate-and-revert. It refuses a red baseline, so its test command names the tests under mutation, not a gate that was already red.
- **The code is an instrument, not a proposal.** It never enters the body or a real checkout, and replacement text states behaviour, not implementation.
- **Tagging.** Every finding is tagged MEASURED — the command and its observed outcome, in 3 lines or fewer — or REASONED. The per-detector record lists the experiments run and skipped, with the reason for each skip.
- **Degraded verdict.** On a repo with a runnable gate, a BUILD is degraded when any detector-3, 9 or 11 criterion was only REASONED. It is labelled degraded, exactly as a non-subagent read is, and a degraded BUILD does not auto-promote ([Gate contract](#gate-contract-with-dispatch)).
- **Executor contract.**
  - The afk executor can write only its branch and `.afk/notes.md`. It cannot write the PR body, the commit message, labels, or other issues: `afk-driver --execute` regenerates the PR body on every round-trip, and the executor commits with a fixed message.
  - Every checkbox must be gradable from the diff, the issue body and the gate report, because that is all the reviewer sees, and the reviewer fails any criterion it cannot confirm. `.afk/notes.md` reaches the issue as agent notes, but review never sees it.
  - A criterion that needs a missing channel, or evidence only `.afk/notes.md` would carry, is a detector-9 finding.
  - The default fix: the checkbox keeps what the diff shows. The recording moves into prose after the checkbox, followed by the sentence "Reviewer: the note is not visible to you; do not fail the slice for it."
- **Dependencies.**
  - A `Depends on #N` that has landed on the fork point is checked against the shipped code in the archive, never against its body.
  - One that has not landed is checked against its body, and the verdict is marked provisional. While its issue is open, the stamp records it as open, and the stamp check sends the slice back for a re-read once it closes (step 7, [Gate contract](#gate-contract-with-dispatch)).

## The source-fidelity pass

The cold reader cannot compare a body against the decisions it claims to encode, because it may not read them. When the body was composed from decisions recorded elsewhere, a second reader does. That reader is deliberately not cold. The two passes answer different questions: the cold read asks whether a stranger can build from these words, and this pass asks whether these words are what was decided. Their findings barely overlap. A decision that never reached the body leaves nothing for a cold reader to find, and a builder graded only on the acceptance criteria ships without it. (Precedent: [42% of stated ## Budget sections are silently discarded, and unparsed slices drop out of the overrun denominator](https://github.com/cdcoonce/afk-agent-system/issues/1116). Its unpark comment decided that a range budget parses to its upper bound. The criterion asked only for a non-`None` count, which the wrong value also satisfies, so the issue closed with the decision unshipped.)

- **When it runs.** It runs whenever the body encodes decisions recorded outside it: the resolution comments on a `/blueprint` map's decision tickets, a grill log, a PRD, or, for a decomposed child, the parent's body. Test: does the body cite such a record, or was it composed from one by `/blueprint`, `/write-a-prd`, `/prd-to-issues` or a decomposer? The conductor running the gate knows the issue's provenance even though its readers must not, so it answers this before dispatch. Yes means the pass runs. An issue shaped in conversation with no written upstream record skips the pass, and the digest then says `fidelity: n/a — no decision sources`. Never leave the fidelity line out.
- **Who reads.** A second fresh subagent, dispatched in the same message as the cold reader. Neither reader sees the other's prompt or output, and only the conductor merges them. The pass is never run by whoever composed the body. The composer reads their own intent back into the words, which is the blindness the cold constraint defeats, arriving from the other side.
- **Sources come from the record, not the body.** The body cites the decisions it kept, and a decision it dropped is exactly one it will not cite. For a map, fetch every decision ticket the map lists at dispatch time, by command and not from memory, and pass all of their URLs. (Precedent: [Standing eval suite for adversarial-review, tdd, and commit](https://github.com/cdcoonce/the-workshop/issues/988) cited 10 of its map's 14 decision tickets.)
- **The unit is the decision, not the ticket.** Extract each decision from the latest settlement on each ticket. If a ticket was reopened, its re-settlement replaces the original. If a later ticket overrides a decision, classify it `superseded` and cite the overriding comment; it is never `contradicted`.
- **Classify each decision against the acceptance criteria, not the prose,** because the built artifact is graded against the criteria alone. Name the violating build, meaning the smallest build that breaks the decision, then find the checkbox that goes red on it:
  - `enforced`: a checkbox goes red. Quote it.
  - `prose-only`: the body states the decision, but every checkbox stays green.
  - `weakened`: a checkbox exists, but it also passes a value the decision forbids. `is not None` is the classic form.
  - `contradicted`: the body prescribes something else.
  - `missing`: the body never mentions the decision.
  - `routed`: the decision belongs to another named issue, or binds only a human step that the body names. If no such step is named, the decision is `missing`.
  - `superseded`: a later settlement replaced it, as defined above.
- **Severity.** `prose-only`, `weakened`, `contradicted` and `missing` all block. Each takes as its default the value-level criterion that would go red. `routed` passes only when the named destination exists. Never grade whether a decision is important enough to enforce. The first ad hoc run of this pass, on the eval-suite epic above, filed "`retired.md` is append-only" as non-blocking. It was the rule the map's guard-activation settlement rested on.
- **Record.** Write one row per decision: the source comment's URL, the decision in one line, its class, and either the enforcing checkbox or the default. Lead with the counts: sources read, sources unreadable, decisions extracted, and decisions per class. "All encoded" without the table is not a result. An unreadable source blocks like a `missing` row until it is re-fetched or Charles waives it by name, because its decisions are unaccounted for.
- **The cold constraint is untouched.** Fidelity findings never reach the cold reader, before or after it runs. A rewrite that folds them in still gets no re-run from its author (step 8).
- **Merging.** When the two passes report the same gap, for instance detector 11 flagging an unenforced rule and the fidelity pass classifying the same decision `prose-only`, the conductor files a single finding that cites both, with one default. Agreement between the two is corroboration, not two findings.

## The coverage pass (decomposed parents)

Every other read in this gate sees one child. None can tell whether the children together carry every parent criterion, or whether two of them prescribe different versions of one thing. The coverage pass reads the set: the parent and every child together, once per parent. It is therefore not cold, by design, like the fidelity pass. (Precedent: [Standing eval suite for adversarial-review, tdd, and commit](https://github.com/cdcoonce/the-workshop/issues/988) decomposed into 13 children. All 13 carried its anti-scope block verbatim, because the block's own heading demanded it. None carried its Budget, and none named its gate command, because the decomposer asks a child only for what to build and its acceptance criteria. The first carriage probe, a search for `make test`, read the gate as present in all 13: the anti-scope block itself says `make test`. The first run of this pass also found "a stale record cannot satisfy the direct-tier guard" in no child. The nearest child checkbox, a fingerprint-mismatch guard, checks fixtures against run files, not calibration records against current inputs.)

- **When it runs.** After afk labels the parent `decomposed`, once every child's own cold read has settled, and before any child is promoted. A parent afk labels `decompose:incomplete` is not ready, because its child set is known to be short. When every child lacks the parent's anti-scope block or gate command, the conductor pastes it into each child before the per-child cold reads, and gives each child the `BU` default below, so thirteen readers do not file one finding thirteen times; this pass then checks the paste like any other carriage. If a child is already promoted, run the pass anyway. A gap in that child's criteria becomes a new child or a fix-forward, never an edit to the in-flight body.
- **The child set comes from the record, not from memory.** Enumerate it by command three ways: the parent's native sub-issues (`gh api repos/<owner>/<repo>/issues/<N>/sub_issues`), the `## Decomposed into` checklist the decomposer appends to the parent, and a body search for `Part of #<N>` (`gh issue list --repo <repo> --state all --search '"Part of #<N>" in:body'`). Any disagreement between them blocks until it is explained, because a child that one source omits is a child the pass never reads. A child closed as not planned carries nothing, so its criteria count as `dropped` unless a sibling carries them.
- **The parent's obligations come by command, not by reading.** Count every checkbox in the parent's acceptance criteria and exclude the `## Decomposed into` checklist, which is the decomposer's output, not a criterion (#988 counts 62 raw and 49 real). Number the criteria P1 to Pn in document order and give the reader n. Three more obligations bind the whole set: `AS`, the parent's anti-scope block; `BU`, its Budget; and `GA`, its gate command. An obligation the parent does not state is recorded `n/a — parent states none`. The pass never invents one; the parent's own cold read owns that gap.
- **Who reads.** A fresh subagent that did not decompose the parent and did not write any child. Its prompt is the parent body, every child body fetched by command, the count n, the conductor's carriage results for `AS`, `BU` and `GA`, and this section. It gets no detector list. Its findings never reach any child's cold reader, before or after it runs.
- **Criterion rows.** For each criterion, name the violating build, as the fidelity pass does, and find the child checkbox that goes red on it. List every child that claims the criterion, not only the strongest.
  - `covered`: at least one child checkbox goes red, and no child claims a conflicting version. A criterion split across children is covered only when every violating build turns some child's checkbox red. The row quotes each part.
  - `weakened`: the strongest child claim also passes a value the parent forbids.
  - `prose-only`: a child states the criterion, but no child checkbox goes red.
  - `dropped`: no child mentions it.
  - `conflicted`: two children prescribe versions no single build satisfies, such as different values for one threshold, different paths or schemas for one file, or opposite orders. The default is the parent's version. A child criterion that requires an edit the parent's anti-scope forbids is `conflicted` too. When that edit is the child's reason to exist, the fix is an exception named in the parent's block, never an altered copy in the child.
  - `routed`: the parent itself assigns the criterion to a named issue outside the child set, or to a named human step. It passes only when that destination exists and states the criterion. (#988 routes its first calibration run to [Standing eval suite: first calibration run and manual audit (hand-run)](https://github.com/cdcoonce/the-workshop/issues/989).)

  Conflicts are not limited to parent criteria. Two children that write and read one key, path or schema under different names conflict even when the parent never mentions it. Record each such pair as an `X` row, whose default names the version you would ship and why.

- **Whole-set rows bind every child,** because an executor reads only its own child, never the parent. `AS`, `BU` and `GA` each get one cell per child: `carried`, `altered` or `absent`. The conductor decides the cells by command and passes the results, and the reader confirms or disputes them. A narrowed `AS` cell is the exception: the reader decides it.
  - `AS`: by default, the lines under the parent's anti-scope heading appear in the child as byte-identical contiguous lines. A child may add lines of its own outside the block. Any edit inside the block is `altered` and blocks, even one that reads tighter, because a tightening belongs in the child's own lines. When the parent's anti-scope itself lets each child carry a narrowed copy, the reader judges the cell one parent prohibition at a time instead. Each prohibition is `kept`; `narrowed`, meaning the child still forbids everything the prohibition forbids within the child's footprint; `weaker`; or `dropped`. A `weaker` or `dropped` prohibition blocks. Narrowing must be authorized in the parent's text. A decomposer's or conductor's brief does not count, because the executor never sees it.
  - `GA`: the child names the parent's gate command, or a command that runs it and more, outside the pasted `AS` block. Match the whole command, never a word from it, and never text the child carries only because the anti-scope block contains it.
  - `BU`: the child has a `## Budget` section in the parent's form, at the parent's tier or cheaper, and the children's declared slices sum to no more than the parent's. A child with no Budget defaults to `1 slice` at the parent's tier. More children than the parent has slices is a size finding for Charles, not a rewrite, because the Budget is his.
- **Severity.** Blocking: every `weakened`, `prose-only`, `dropped` and `conflicted` row, every `altered` or `absent` cell, every `weaker` or `dropped` prohibition, and a `routed` row whose destination is missing. One blocking row withholds every child, not only the children it names. A promoted child's body is frozen, so a criterion dropped from the set would then have no home but a new child, which the Budget may not cover. A conflicted pair promoted one at a time ships whichever version lands first. Never grade whether a criterion matters enough to carry.
- **Record.** Post a comment on the parent titled `## Coverage — CLEAN` or `## Coverage — BLOCKED`. Lead with the counts: children per enumeration source, the criterion count n, rows per class, and carried cells per whole-set row out of the child count. Then write one row per child that claims each criterion, and one per `X` conflict:

  | Parent criterion             | Class   | Child | Checkbox                  | Default |
  | ---------------------------- | ------- | ----- | ------------------------- | ------- |
  | P7 `<criterion in one line>` | covered | #994  | `<quoted child checkbox>` | —       |

  Then write the `AS`, `BU` and `GA` grid, one column per child. A record with fewer than n criterion rows did not run, and "all covered" without the table is not a result.

- **Stamp.** End the record with the parent's body hash and each child's, keyed by issue number. Each is the 12-hex body= field of the stamp line that `python3 "<engine>/cold_read_stamp.py" stamp --repo <repo> --issue <N> --repo-dir <checkout> --target <fork point>` prints when run without `--apply`. Any later edit to any of those bodies makes the record stale: a child's cold-read rewrite, a hand fix, or a child added or closed. Before promoting any child, re-enumerate the set and re-hash every body. Any difference from the stamp means re-running the pass.
- **Rewrite and labels.** A BLOCKED finding that editing the children can fix comes with the exact replacement text per child, as in step 8. Applying the text clears it. The conductor then edits the comment to CLEAN and re-stamps it with the new hashes, and it does not re-run the pass on its own edit. A second pass, if wanted, is a fresh subagent. It does re-run detector 10's command on every child the rewrite touched, because a criterion moved into a child can name a protected path that the child's cold read never saw. A finding only Charles can settle, such as a Budget overrun or a conflict the parent never decided, stays BLOCKED. While the record is BLOCKED, label the parent and every child `coverage:blocked`, and remove the label on CLEAN. Skip silently if the repo lacks the label; the comment carries the verdict either way.
- **Merging.** A per-child fidelity row and a coverage row that report the same gap are a single finding that cites both.

## Detectors

Run all eleven. Each has a test that returns yes or no — record which ones you ran and what you found, per detector. "Looks fine" is not a result.

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

   Text-only resolution cannot rule out a subtree-relative path, a cross-repo citation, or a bare branch name, so no verdict here is a flat pass/fail. The output separates what it trusts from what it doesn't:

   - **`rows` (severity CHECK) are hints, not findings.** Verify each with one unpiped command before writing it up — the row names the token, its class, and why the resolver couldn't trust it, but it can be wrong in either direction (a subtree-relative path, a branch name, a citation into a different repo can all read CHECK on a good body).
   - **The OK list is exact — everything else is CHECK:**
     - a path/directory that resolves exactly, or a bare **file** basename resolving by an unambiguous suffix match (a directory match, or any `/`-bearing token matched only by suffix, is `EXISTS_ELSEWHERE` — a CHECK naming the path(s) found);
     - a symbol found in a non-doc/non-test code file, including inside a comment or string literal (whether it does what the body claims is detector 8's concern);
     - a commit reachable from the resolved ref itself (reachable only from another branch is `COMMIT_ON_OTHER_BRANCH`, a CHECK naming that branch);
     - an issue/PR ref with a real state (open, closed, merged);
     - a wikilink that resolves;
     - a `REF`/`REPO` token (branch, tag, `owner/repo`) confirmed against git or GitHub.

     Everything else — including a glob/templated pattern whose literal prefix resolves — is CHECK: only the prefix was checked, never its members.

   - **`evidence_lines` still need the line-text-vs-claim read.** A resolved `path:line` citation is OK severity but appears here with up to 8 lines of the actual text; a longer range is marked `truncated: true` and needs reading by hand. It blocks only when the line no longer supports the claim.
   - **`assumed_repo_refs` need no further check.** A bare `#N` is resolved against `--repo` by default; the script already promotes it into `rows` with a CHECK once the body names another repo — by `owner/repo#N`, a GitHub URL, a backticked `owner/name`, an `alias#N` shorthand, or the bare name of any sibling repo, anywhere in the prose. Whatever is left in `assumed_repo_refs` had none of those signals.
   - **`INCOMPLETE`:** classes under `not_run` (no gh auth, a non-404 gh failure, missing graphmark with wikilinks present, a bad `--vault-root`, a failed sibling-repo lookup) and reasons under `input_errors` (bad `--repo-dir`, an origin mismatch, a bad `--ref`, a fetch failure, an empty body, zero extractable tokens) resolve by hand, the old one-command-each way.
   - **What the script cannot see is still the reader's job:** prose too far from any "lines N-M" citation to pair with it (`PROSE_LINE_CITATION`, always CHECK), or a claim about what a line of code _does_ (detector 8's concern) — the script resolves existence, never behavior.

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

11. **Unenforced rule.** Detectors 2, 3 and 9 start at each criterion and look outward. This one starts at each rule the body states and looks for the criterion that enforces it. A rule is any statement that constrains the build:
    - a must, never, only or always;
    - a constraint carried by a modifier, such as private criteria, an append-only file, synthetic secrets or a write-once run file;
    - a checkbox clause that the checkbox's own check never exercises. A checkbox whose test covers its first sentence leaves its second unenforced.

    The same holds for a decision in the issue's own comments (step 2 fetches them), such as an unpark answer, that never reached the body. The executor is graded on the body's criteria, and comments reach it, if at all, as untrusted context. Skip anti-scope lines, which are detector 4's, and steps only a human performs, which bind no build. File a weak test criterion under detector 3 and every other unexercised clause here, never under both. Record enforced rules as a count with one example, and write up only the unenforced ones.
    → Test: for each rule, name the violating build, meaning the smallest change that breaks the rule, and the checkbox that goes red on it. If every checkbox stays green, the rule is unenforced, and the default is the value-level criterion that would go red. A criterion that the violating value also passes does not enforce the rule. Two statements that prescribe different things for the same case are a finding too, including a criterion that a faithful build of another section cannot meet. For those, default to whichever side the criteria already enforce.
    Precedent: the first body of [Standing eval suite for adversarial-review, tdd, and commit](https://github.com/cdcoonce/the-workshop/issues/988) stated three rules that no criterion enforced:
    - "`retired.md` is append-only", as a second clause on a checkbox whose check covered only the missing-entry case;
    - the private acceptance criteria;
    - the single-prompt gap record.

    The ten-detector cold read passed all three, and only the non-cold fidelity pass found them, yet every one was visible in the body. This detector, replayed cold on that body, recovered two of the three and four more of the same class. Replayed on the rewritten body that had cleared the gate, it found two criteria that contradict the fixture spec. One demands a line window for matchers where D4 and D5 have none. The other demands a no-skill arm that triggering items do not have.

## Every finding carries a default

A finding that ends in a question blocks. A finding that ends in a proposed default is one word from resolved. Write each as:

> **[detector] <what is ambiguous>.** Default: I'll <specific choice> because <reason>. Say otherwise to change it.

Charles reads a list of defaults and answers only the ones he disagrees with. Silence is assent — so the default must be one you are genuinely willing to ship, not a placeholder.

## Procedure

1. **Before dispatching the subagent:** expand `<engine>` — the same placeholder `vault-audit` and `vault-wrap-up` use — and the local checkout path into real absolute paths in detector 5's procedure text; the subagent cannot resolve `<engine>` itself. Add `--vault-root <absolute vault path>` when the body has `[[wikilinks]]`, and include `--with pyyaml` alongside `--with 'graphmark>=0.7,<0.8'` in the command line. Expand the path to `detector-teeth-check`'s `teeth_check.py` the same way, for the probe builds. State plainly, in the dispatch, that this expansion was done; a subagent handed the literal placeholder cannot run the script. If the source-fidelity pass applies, fetch its source URLs by command now and dispatch its subagent in the same message as the cold reader. Its prompt is the issue body, the source URLs, and the source-fidelity section of this procedure; it gets no detector list, and the cold reader gets no source URLs.
2. **Fetch the issue cold.** `gh issue view <N> --repo <repo> --comments` — a prior cold read's findings live in the comments. Note existing labels.
3. **Run all eleven detectors** against the body. Record per-detector: ran / found N / found none, with the specific noun or criterion you checked and the experiments run and skipped ([Probe builds](#probe-builds)). A detector you skipped is reported as skipped, not as clean.
4. **Resolve every path the body names** — evidence and destination alike (detector 5) — with the single `cold_read_evidence.py` invocation described there. Verify each `CHECK` row with one unpiped command before writing it up as a finding; `evidence_lines` show up to 8 lines per citation (`truncated: true` beyond that) and still need the line-text-vs-claim read; anything left in `assumed_repo_refs` had no cross-repo signal and needs no further check. Only a class listed under its `not_run`, or a reason under `input_errors`, falls back to resolving that evidence by hand.
5. **Assign a verdict:**
   - **BUILD** — zero blocking findings from either reader. Non-blocking defaults may still be listed; they do not gate. Label: `cold-read:pass`.
   - **REWRITE** — findings exist and are fixable by editing the issue body. This is the common case. Produce the exact replacement text for each affected section, not a description of it, and measure its new tests where you can: step 8 spares a fresh read only for replacement text you both produced and measured. Label: `cold-read:rewrite`.
   - **NOT-DISPATCH-READY** — the idea is not executor-implementable as scoped: a size lie, ambiguity only Charles can resolve, or a slice at step 8's read cap. Recommend `decompose:ready`, `daytime-only`, or back to `/grill`. Label: `cold-read:blocked`.
6. **Write the findings back to the issue** as a comment titled `## Cold read — <verdict>`. The ticket is the memory store; a cold read that lives only in this chat did not happen. Include the per-detector record, with every finding tagged MEASURED or REASONED, so a later reader can tell a clean pass from a lazy one, and, when the source-fidelity pass ran, its per-decision table under `### Source fidelity`.
7. **Apply the label and stamp.** Apply the verdict's label from step 5. Skip silently if the repo lacks the label — the comment carries the verdict either way. On BUILD, stamp the body with cold_read_stamp.py stamp (stdlib only): `python3 "<engine>/cold_read_stamp.py" stamp --repo <repo> --issue <N> --repo-dir <checkout> --target <fork point> --apply`, where `<fork point>` is the branch [Probe builds](#probe-builds) names. The digest quotes the stamp line it prints. If it exits nonzero, the body carries no stamp: say so in the digest and withhold the promote command.
8. **On REWRITE — the rewrite loop.**
   - Edit the issue body with the replacement text, then say plainly that the body changed. Applying replacement text sets cold-read:rewrite, never pass. The pass label needs a fresh reader's BUILD on that exact body, labelled and stamped in that read's own step 7.
   - Replacement text may tighten implementation narrative; it never shortens acceptance criteria, the test criterion, or interface contracts to save length — those sections are the executor's whole signal, and length pressure guts test content first.
   - Do not re-run the cold read on your own edit — you are no longer cold to it. The next read is a fresh subagent, dispatched from step 1 on the edited body.
   - The sole exemption: an applied change that is byte-identical to replacement text the previous reader both produced and measured (its new test red under the targeted mutant and green on the faithful build), and that answers every blocking finding of that read, sets `cold-read:pass`, runs step 7's `stamp --apply`, and quotes the previous reader's MEASURED lines in its comment. Any conductor addition voids the exemption, however small or editorial.
   - The read cap: count fresh reads since the last body Charles approved. If a slice's third fresh read still finds a blocking defect, the verdict is NOT-DISPATCH-READY and the slice goes to Charles, carrying that read's replacement text as a proposal.
9. **Digest:** verdict, findings count by detector with how many were MEASURED, the fidelity line (decisions per class, or `n/a` and why), whether the read was truly cold or degraded (a non-subagent read, or a BUILD whose detector-3, 9 or 11 criteria were only reasoned; [Probe builds](#probe-builds)), whether it is provisional, the label applied, the stamp line (step 7), and the promote command preceded by its `cold_read_stamp.py check` command — or the reason promotion is withheld. For a decomposed child, print the promote command only when the parent's latest coverage record is CLEAN and its stamp still matches; otherwise the reason is `withheld: coverage`.

## Gate contract with /dispatch

- **No `proposed` issue is auto-promoted without a BUILD verdict from a cold reader that did not shape it** — and, when its body encodes decisions recorded elsewhere, a source-fidelity record with no blocking row. This is an additional clause on `/dispatch`'s low-risk test, not a replacement for it: every existing clause still has to hold.
- **No child of a decomposed parent is promoted, automatically or by hand, until the parent carries a `## Coverage — CLEAN` record whose stamp matches the current body of the parent and of every child.** One blocking row withholds every child. afk's `--promote` checks no cold-read or coverage label, so this clause holds only when whoever promotes reads it; the `coverage:blocked` label is its visible form on each child.
- A REWRITE clears the gate only through a fresh reader's BUILD on the edited body, or through step 8's sole exemption, which counts as the previous reader's BUILD on the body it measured. A NOT-DISPATCH-READY does not, ever, without Charles.
- **Every manual promote checks the stamp first.** Before a manual `--promote`, whoever runs it — `/dispatch` or Charles — runs cold_read_stamp.py check: `python3 "<engine>/cold_read_stamp.py" check --repo <repo> --issue <N>`. Its exit code decides, and stderr names the cause of an exit 2:
  - exit 0: promote;
  - exit 1: re-read — the body changed since the stamp, or a dependency the stamp recorded open has closed and is re-read against its shipped code;
  - exit 2 on a missing or bad stamp: re-read, and stamp only on that read's BUILD (step 7), unless it is a legacy pass that qualifies below;
  - exit 2 on a failed fetch or a failed dependency lookup: retry the check.
- **Legacy passes.** A `cold-read:pass` with no stamp may be stamped with step 7's command without a re-read only when its last `## Cold read` BUILD comment is newer than its last body edit, checked with GraphQL `issue.userContentEdits`. Otherwise it is re-read. Stamping first would certify an unread body: on 2026-09-27 all 7 queued ragmark passes were in that state, and fresh reads found blocking defects in 4 of them.
- **A degraded BUILD blocks auto-promote.** It does not satisfy `/dispatch`'s low-risk test ([vault-dispatch](../../vault-dispatch/references/command.md#low-risk-auto-promotion-test)), whichever way it is degraded: a non-subagent read, or a reasoned-only BUILD under [Probe builds](#probe-builds).
- Auto-promotion in afk enforces the same stamp through `cold_read_current` (afk-agent-system#1534) once a repo turns on `require_cold_read_stamp`.
- Cold read never promotes. It clears or withholds; the promote command is `/dispatch`'s to run or Charles's to paste.
- **A verdict is stamped to the fork-point SHA the reader checked.** The stamp line's `target=` field records it, and `check` never compares it, so this re-run is by hand. If the fork branch moves past that SHA before dispatch — an integration lands, a prerequisite is pushed — the body's present-tense claims (rosters, "X does not exist yet", dependency status) may have rotted: re-run detectors 5 and 8 against the new SHA before promoting. (Precedent: kaggriculture#29 — its "two registered zoo members" claim went stale when the integration it waited behind registered four more; kaggriculture#41 — a "do not promote until #30/#31 merge" gate survived their landing and contradicted the updated status paragraph above it.)

## Anti-rubber-stamp

The failure mode of this skill is a confident BUILD on a vague issue — it is faster, it is agreeable, and nothing catches it until the run is gone.

- A BUILD verdict must name at least one referent it resolved and one anti-scope boundary it found stated. If you cannot, the issue is not clean; you did not look.
- A BUILD verdict must quote the detector-10 command it ran and its exit code. "No protected paths" asserted without the command is the exact miss this detector exists to close — seven of eleven readers wrote a confident anti-scope about a neighbouring file while editing a protected one. An unrun check is reported as skipped, never as clean.
- A first-ever cold read that finds nothing is suspicious, not impressive. Say so.
- A BUILD verdict on a body composed from recorded decisions must carry the source-fidelity counts. A fidelity pass that reports no decisions, or reads fewer sources than the record lists without naming the unreadable ones, did not run.
- A `Coverage — CLEAN` record must carry n criterion rows, n being the conductor's command count, and name all three enumeration sources with their counts. A record that reads every row `covered` without quoting a child checkbox in each did not run.
- Do not soften a finding because the issue is Charles's own. `/dispatch` shaped it in a conversation you are pretending not to have had; that is the point.
- No code the reader writes goes in the body, and no checkout is edited. Probe builds are instruments, not proposals: a probe's code measures what the words produce, lives only in its scratch directory, and never becomes replacement text.

## Constraints

- **The spec, not the code.** Every finding must be a defect in the _words_ — including a sentence that is false about the code (detector 8). Reporting a false premise is a spec finding; fixing the code is not.
- **One issue per run.** Cold-reading a batch means skimming. The coverage pass is the one exception, because its question is about the set and it is not a cold read. Its one-row-per-criterion count is what keeps it from skimming.
- **Never edit acceptance criteria to match what you think the executor will do.** Criteria describe what Charles wants; if they are wrong, that is a finding, not an edit.
- **Report degradation honestly.** A cold read run inside the shaping session's own context is worth less, and so is a BUILD whose probe-able criteria were only reasoned ([Probe builds](#probe-builds)). Label it and let Charles decide whether to re-run it clean.
