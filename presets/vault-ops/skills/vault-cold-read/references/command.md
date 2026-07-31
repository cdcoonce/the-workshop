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
- The reader may read the target repo **only** to resolve evidence the issue cites — does this file exist, does this issue number resolve. It may not go code-archaeologing to reconstruct intent the issue failed to state. If understanding requires reading the code, that IS the finding.

## Detectors

Run all seven. Each has a test that returns yes or no — record which ones you ran and what you found, per detector. "Looks fine" is not a result.

1. **Unbound referent.** Every "it", "this", "the existing X", "the current behavior" resolves to a named file, function, flag, or issue number _inside the body_.
   → Test: can you point at the noun? If resolving it needs the conversation, it is unbound.

2. **Unverifiable acceptance criterion.** Each checkbox is answerable yes/no from the repo and the issue alone.
   → Test: could two people who disagree be forced to the same verdict? "Handles errors gracefully" fails. "Raises `ValueError` when `zone` is None" passes.

3. **Toothless test criterion.** `/dispatch` requires a test criterion; this checks it has teeth.
   → Test: if the feature were absent — or the bug reintroduced — would the named test go red? A criterion satisfied by asserting the code's own output on its own fixture is a tautology. Name the mutation that should break it.

4. **Missing anti-scope.** The body states what the executor must NOT touch.
   → Test: name one adjacent file or behavior an over-eager executor would plausibly "improve." If the body does not forbid it, that is the finding.

5. **Unresolvable evidence.** Every cited artifact resolves: file paths exist, issue/PR numbers open, vault notes are real.
   → Test: check them, one unpiped command each. A citation that does not resolve is either stale or invented; both are blocking.

6. **Size lie.** The `afk-sized` claim survives the footprint the body actually implies.
   → Test: list the files the proposed behavior touches. A new module, a new mechanism, or changes persisting outside the issue's footprint is never `afk-sized` (precedent: afk#324, quarantined on scope after 4 attempts). If the implied slice count exceeds the Budget line, the Budget is the bug.

7. **Unauthorized decision.** A place where the executor must choose between two defensible approaches and the issue does not say which.
   → Test: read the Proposed behavior and ask "where would I, building this, have to invent policy?" Naming schemes, error-vs-skip, ordering, defaults. Every such fork is a finding unless the body picks a side.

## Every finding carries a default

A finding that ends in a question blocks. A finding that ends in a proposed default is one word from resolved. Write each as:

> **[detector] <what is ambiguous>.** Default: I'll <specific choice> because <reason>. Say otherwise to change it.

Charles reads a list of defaults and answers only the ones he disagrees with. Silence is assent — so the default must be one you are genuinely willing to ship, not a placeholder.

## Procedure

1. **Fetch the issue cold.** `gh issue view <N> --repo <repo> --comments` — a prior cold read's findings live in the comments. Note existing labels.
2. **Run all seven detectors** against the body. Record per-detector: ran / found N / found none, with the specific noun or criterion you checked. A detector you skipped is reported as skipped, not as clean.
3. **Resolve cited evidence** — one unpiped command per citation. Do not batch into a pipeline whose failure you cannot attribute to a specific citation.
4. **Assign a verdict:**
   - **BUILD** — zero blocking findings. Non-blocking defaults may still be listed; they do not gate.
   - **REWRITE** — findings exist and are fixable by editing the issue body. This is the common case. Produce the exact replacement text for each affected section, not a description of it.
   - **NOT-DISPATCH-READY** — the idea is not executor-implementable as scoped: a size lie, or ambiguity only Charles can resolve. Recommend `decompose:ready`, `daytime-only`, or back to `/grill`.
5. **Write the findings back to the issue** as a comment titled `## Cold read — <verdict>`. The ticket is the memory store; a cold read that lives only in this chat did not happen. Include the per-detector record so a later reader can tell a clean pass from a lazy one.
6. **Apply the label:** `cold-read:pass` on BUILD, `cold-read:rewrite` on REWRITE, `cold-read:blocked` on NOT-DISPATCH-READY. Skip silently if the repo lacks the label — the comment carries the verdict either way.
7. **On REWRITE:** edit the issue body with the replacement text, then say plainly that the body changed and re-state the verdict as BUILD. Do not re-run the cold read on your own edit — you are no longer cold to it. A second pass, if wanted, is a fresh subagent.
8. **Digest:** verdict, findings count by detector, whether the reader was truly cold or degraded, the label applied, and the promote command — or the reason promotion is withheld.

## Gate contract with /dispatch

- **No `proposed` issue is auto-promoted without a BUILD verdict from a cold reader that did not shape it.** This is an additional clause on `/dispatch`'s low-risk test, not a replacement for it: every existing clause still has to hold.
- A REWRITE resolved by editing the body clears the gate. A NOT-DISPATCH-READY does not, ever, without Charles.
- Cold read never promotes. It clears or withholds; the promote command is `/dispatch`'s to run or Charles's to paste.

## Anti-rubber-stamp

The failure mode of this skill is a confident BUILD on a vague issue — it is faster, it is agreeable, and nothing catches it until the run is gone.

- A BUILD verdict must name at least one referent it resolved and one anti-scope boundary it found stated. If you cannot, the issue is not clean; you did not look.
- A first-ever cold read that finds nothing is suspicious, not impressive. Say so.
- Do not soften a finding because the issue is Charles's own. `/dispatch` shaped it in a conversation you are pretending not to have had; that is the point.
- Do not fix the code. Do not propose an implementation. If you catch yourself writing the diff, you have stopped reading the spec.

## Constraints

- **The spec, not the code.** Every finding must be a defect in the _words_.
- **One issue per run.** Cold-reading a batch means skimming.
- **Never edit acceptance criteria to match what you think the executor will do.** Criteria describe what Charles wants; if they are wrong, that is a finding, not an edit.
- **Report degradation honestly.** A cold read run inside the shaping session's own context is worth less. Label it and let Charles decide whether to re-run it clean.
