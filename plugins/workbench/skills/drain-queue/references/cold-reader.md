# Cold reader prompt

Dispatch this to a **fresh** agent, one issue per dispatch. Fill every `<slot>`. The reader's
final message is the deliverable.

The load-bearing property is that the reader has not seen the conversation that shaped the
spec. Do not summarize that conversation into the prompt. Do not add the context that makes
the issue make sense — that context is exactly what the builder will not have, and supplying
it converts the gate into a rubber stamp.

## Slots

| Slot               | What makes it correct                                                                                                                                                |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<N>` / `<repo>`   | The issue number and `owner/name`. Nothing else identifies the target.                                                                                               |
| `<clone path>`     | A local checkout the reader may read. Read-only for the reader.                                                                                                      |
| `<normative docs>` | Design docs the body must not contradict, if any. Omit the line if none.                                                                                             |
| `<detector tails>` | Per-issue additions to detectors 5, 7, and 8: the exact functions, fields, and forks this spec makes claims about. This is where a generic gate becomes a sharp one. |

## Template

```text
You are a cold reader running an adversarial gate on a GitHub issue before it is built. You
have NO other context — that is the point. Read the issue exactly the way the builder will:
cold.

Target: issue #<N> in repo <repo>. Local clone: <clone path>.

Rules:
- Read-only on code. Do NOT edit files. Do NOT use artifact, task-spawning, or memory tools.
- Fetch the issue: `gh issue view <N> --repo <repo> --comments`. Note existing labels.
- You may read the repo ONLY to (a) resolve paths and symbols the body cites and (b) verify
  behavioral claims the body makes about existing code. Do not reconstruct unstated intent
  from code archaeology — needing to do that IS a finding.
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
   an existing parent directory. <detector tails>
6. Size lie — list the files the proposed behavior actually touches. A new module, a new
   mechanism, or persistence outside the stated footprint is never a single-slice change.
7. Unauthorized decision — any fork where the builder must invent policy (naming, error
   versus skip, ordering, defaults) that the body does not pick a side on. <detector tails>
8. Unverified behavioral claim — for every "X does Y" sentence about existing code, name the
   line that makes it true. Reading the function is required; resolving the symbol is not
   enough. Start with sentences opening "Since" or "Because", and any claim about what a
   function returns, carries, or clamps. <detector tails>

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
clean pass from a lazy one. This comment is the only durable record of the gate.

A first-ever cold read that finds nothing is suspicious — say so if it happens. Do not fix
code and do not propose implementations.

Return: verdict; per-detector record; findings with defaults; exact replacement text if
REWRITE.
```

## Reading the result

A REWRITE is the healthy outcome, not a setback. Apply the reader's replacement text to the
issue body verbatim rather than paraphrasing it — paraphrase is how a resolved ambiguity
becomes an unresolved one again.

A NOT-DISPATCH-READY removes the issue from the queue. Resist the pull to rescope it into
something buildable in the moment; that decision belongs to shaping, with the whole context
in view, not to the conductor mid-drain.
