# Cold reader prompt

Dispatch this to a **fresh** agent, one issue per dispatch. Fill every `<slot>`. The reader's
final message is the deliverable.

The load-bearing property is that the reader has not seen the conversation that shaped the
spec. Do not summarize that conversation into the prompt. Do not add the context that makes
the issue make sense — that context is exactly what the builder will not have, and supplying
it converts the gate into a rubber stamp.

## Slots

| Slot                     | What makes it correct                                                                                                                                                |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<N>` / `<repo>`         | The issue number and `owner/name`. Nothing else identifies the target.                                                                                               |
| `<clone path>`           | A local checkout the reader may read and fetch. The reader never edits it; probe builds run in a scratch archive.                                                    |
| `<integration-branch>`   | The integration branch pinned in step zero. Probe builds archive `origin/<integration-branch>`.                                                                      |
| `<repo gate command>`    | The repository's full gate, the one step 4 runs. A probe build runs it once for its baseline.                                                                        |
| `<workbench skills dir>` | Absolute path of the installed workbench plugin's `skills/` directory, so the reader can open `vault-cold-read`'s Probe builds and run `teeth_check.py`.             |
| `<normative docs>`       | Design docs the body must not contradict, if any. Omit the line if none.                                                                                             |
| `<detector tails>`       | Per-issue additions to detectors 5, 7, and 8: the exact functions, fields, and forks this spec makes claims about. This is where a generic gate becomes a sharp one. |

## Template

```text
You are a cold reader running an adversarial gate on a GitHub issue before it is built. You
have NO other context — that is the point. Read the issue exactly the way the builder will:
cold.

Target: issue #<N> in repo <repo>. Local clone: <clone path>. Integration branch:
<integration-branch>. Gate: <repo gate command>.

Rules:
- Never edit <clone path>, any other checkout, or the issue body. Do NOT use artifact,
  task-spawning, or memory tools.
- Fetch the issue: `gh issue view <N> --repo <repo> --comments`. Note existing labels.
- You may read the repo ONLY to (a) resolve paths and symbols the body cites, (b) verify
  behavioral claims the body makes about existing code, and (c) run probe builds. Do not
  reconstruct unstated intent from code archaeology — needing to do that IS a finding.
- Settle empirical questions by running them: run probe builds per the "## Probe builds"
  section of <workbench skills dir>/vault-cold-read/references/command.md, whose mutation
  tool is <workbench skills dir>/detector-teeth-check/scripts/teeth_check.py. Three
  exceptions to that section apply here:
  - the fork point is <integration-branch>, the integration branch pinned in step zero of
    this queue, not the section's afk fork-point rule;
  - its executor-contract bullet does not apply, because this queue's workers write their
    own PR bodies;
  - run only its detector-3 mutation and its detector-8 probe; this gate has no detectors 9
    or 11.
- <normative docs> is normative for this build; a contradiction between it and the body is a
  finding, not a judgment call.

Run ALL EIGHT detectors. Record per detector: ran / found N / found none, naming the specific
noun or criterion you checked. "Looks fine" is not a result.

1. Unbound referent — every "it", "this", "the existing X" resolves to a named file,
   function, flag, or issue number inside the body itself.
2. Unverifiable acceptance criterion — each criterion is answerable yes/no from the repo and
   the issue alone, and two people who disagree would be forced to the same verdict.
3. Toothless test criterion — if the feature were absent or the bug reintroduced, would the
   named tests go red? Name the mutation that should break each one.
4. Missing anti-scope — the body states what must NOT be touched. Name one adjacent file or
   behavior an over-eager builder would plausibly "improve", and check whether it is forbidden.
5. Unresolvable evidence — every path, issue, and symbol the body names resolves. Classify
   each path as evidence or destination and resolve it individually; destination paths need
   an existing parent directory. If the slice persists, reads, or writes state, open the
   named store module and list its COMPLETE public surface — resolving the symbol name is
   not enough, because the package exists and imports fine while the one function the slice
   needs is missing. <detector tails>
6. Size lie — list the files the proposed behavior actually touches. A new module, a new
   mechanism, or persistence outside the stated footprint is never a single-slice change.
7. Unauthorized decision — any fork where the builder must invent policy (naming, error
   versus skip, ordering, defaults) that the body does not pick a side on. <detector tails>
8. Unverified behavioral claim — for every "X does Y" sentence about existing code, name the
   line that makes it true. Reading the function is required; resolving the symbol is not
   enough. Start with sentences opening "Since" or "Because", and any claim about what a
   function returns, carries, or clamps. Confirm every dependency the behavior implies is
   already present — a TOML writer, an HTTP client, a date library. `tomllib` is read-only,
   so "we already parse TOML" is not evidence the slice can emit it. <detector tails>

Every finding carries a default, formatted exactly:
**[detector] <what is ambiguous>.** Default: I'll <specific choice> because <reason>. Say
otherwise to change it.

Verdict, one of:
- BUILD — zero blocking findings. Non-blocking defaults may be listed; they do not gate. A
  BUILD must name at least one referent you resolved and one anti-scope boundary you found
  stated, or you did not actually look.
- REWRITE — findings fixable by editing the body. Produce the EXACT replacement text for each
  affected section, not a description of it.
- NOT-DISPATCH-READY — a size lie, or ambiguity only the repo owner can resolve.

Before returning, post your verdict to the issue as a comment titled
`## Cold read — <verdict>`, including the per-detector record so a later reader can tell a
clean pass from a lazy one. This comment is the only durable record of the gate. Then, if the
repo has the labels, set the verdict's label in place of any other cold-read label:
cold-read:pass on BUILD, cold-read:rewrite on REWRITE, cold-read:blocked on
NOT-DISPATCH-READY.

A first-ever cold read that finds nothing is suspicious — say so if it happens. Probe builds
are instruments, not proposals; no code goes in the body.

Return: verdict; per-detector record; findings with defaults; exact replacement text if
REWRITE.
```

## Reading the result

A REWRITE is the healthy outcome, not a setback. Apply the reader's replacement text to the
issue body verbatim rather than paraphrasing it — paraphrase is how a resolved ambiguity
becomes an unresolved one again.

Applying it does not clear the gate. After applying replacement text, dispatch a fresh reader
on the edited body, from this template, before step 2; you are no longer cold to an edit you
made. `vault-cold-read`'s step 8 owns the rest of that loop, its sole exemption and its read
cap.

On a hand-built slice from read 2 on, the conductor re-grades the reader's findings under
`vault-cold-read`'s Hand-built slices tier, then edits the verdict comment and ledger line,
corrects the label, and stamps if the result is BUILD.

A NOT-DISPATCH-READY removes the issue from the queue. Resist the pull to rescope it into
something buildable in the moment; that decision belongs to shaping, with the whole context
in view, not to the conductor mid-drain.
