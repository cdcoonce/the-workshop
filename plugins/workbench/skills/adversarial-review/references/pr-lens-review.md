# Multi-Lens PR Review

The method scales down to one claim and up to one pull request. This is the
pull-request instantiation: a fixed shape, hand-written six times over one queue
of nine slices, which found real defects on five of seven PRs — including a
failed re-write that truncated a previously valid data file to zero bytes, and a
credential reachable where the spec said it was not.

It is not the default. One reviewer reading a small diff is cheaper and usually
enough. Reach for this when the PR will merge without a second human, or when
being wrong is expensive.

**Cost: roughly 4-9 agents per PR** — 3-4 lenses, then 3 refuters per surviving
finding. A clean PR costs 4; three findings costs 13. State that number before
dispatching, not after.

## Scope

| Input               | What it is                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------------- |
| The diff            | One PR. Not a branch of many, not a range — one merge unit                                     |
| The binding spec    | The issue body the PR claims to implement. Findings are scored against this, not against taste |
| The pre-change tree | The base commit, readable                                                                      |

Without the spec, lenses drift into style review. Without the pre-change tree,
regression is invisible — a lens can see what the new code does, never what it
stopped doing.

## The lens pass

Three to four reviewers in parallel, each given **one narrow lens and nothing
else**. Narrowness is the mechanism: a reviewer told to "review this PR" returns a
survey, and a survey buries the one real defect under nine notes about naming. A
reviewer told to check only whether the arithmetic is right returns a defect or
nothing.

The contract every lens gets:

- Report **only defects**, each with a `file:line` and a concrete failure
  scenario — the inputs or state that produce the wrong result.
- Return an **empty list** when there are none. Say explicitly that this is the
  expected answer, or the lens manufactures a finding to look useful.
- No style, naming, or preference. Other tools own those.

| Lens                       | Asks                                                                                                                |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Domain correctness         | Is the math or semantics the change is actually about right? Balances, dates, rounding, ordering, state transitions |
| Test veracity              | Do the new tests fail against the base? Or do they assert the implementation back to itself?                        |
| Spec conformance and scope | Does it do what the issue asked, all of it, and nothing it did not ask for?                                         |
| Credential safety          | Add whenever secrets, tokens, or live network calls appear in the diff                                              |

Domain correctness is written fresh each time — it carries what this particular
change is about. The other three are close to reusable as written.

## The refutation pass

Every surviving finding goes to **three independent refuters**, each told to try
to refute it and to default to `refuted=true` when uncertain. A finding is
confirmed only at **two or more upheld**.

The bias is the point. Lenses over-produce: an agent given a narrow mandate and an
expectation of output will find something. The refutation pass is where that gets
paid for, and a finding no one can defend under three hostile reads was not a
finding.

**Invert the bias for credential-exposure and live-network findings** — uphold
unless the exposure can be positively demonstrated impossible. The asymmetry
matches the cost: a false positive costs one wasted look, a false negative costs
the credential.

Refuters get the finding and the code, never each other's verdicts. Three refuters
reading one shared thread is one refuter with extra steps.

## Structured output

Use the Workflow tool's `schema` option for both passes — findings from the
lenses, verdicts from the refuters. Parsing prose is where a hedged sentence
becomes a dropped defect, and where a lens that returned nothing becomes
indistinguishable from a lens that said nothing. A schema makes those two
different values instead of the same blank.

## Rule 1 — freeze the tree before dispatching

The skill is read-only because editing the work moves its evidence out from under
the findings. With parallel agents that failure also becomes invisible.

One run was contaminated exactly this way: the conductor committed a fix into the
same worktree while the review was in flight. A lens correctly flagged a
divergence from the spec, and three refuters then unanimously refuted it — only
because the trees had converged by their turn. The finding and its refutation
described two different moments, and nothing in either output said so.

Freeze the head before dispatch and leave the tree alone until every agent
returns. If you must edit mid-run, **re-run against a frozen head** rather than
reasoning about which agent saw which state. That reasoning is unauditable, and it
fails in the direction that says the work was fine.

## Rule 2 — zero findings means nothing until you read the journal

A lens that died on dispatch and a lens that read the whole diff and found nothing
hand the conductor the same result.

Before reporting a clean PR, open `journal.jsonl` in the workflow transcript
directory and confirm **one result record per lens**. Four lenses, four records.
Three records is not a clean review; it is a three-lens review with an unreported
hole — and that hole belongs in **Could not verify**, not in the verdict.

## Worked example — the lens prompts

`SPEC` is the issue body, `DIFF` the PR diff, `BASE` the pre-change tree.

Shared preamble, given to every lens:

> You are reviewing PR #N against its binding spec. Report ONLY defects. Every
> finding needs a file:line and a concrete failure scenario: the inputs or state
> that produce the wrong result. If your lens finds no defect, return an empty
> findings list — that is the expected answer, not a failure. Do not report
> style, naming, or preference.

Domain correctness — rewritten per change; this one came from a ledger:

> Your lens is arithmetic and accounting semantics ONLY. For every balance,
> total, split, and date-bucketing operation in DIFF, work at least one concrete
> case by hand and check the code against your result. Attend to sign
> conventions, off-by-one on period boundaries, and rounding that accumulates.
> Ignore anything that is not a number being computed.

Test veracity:

> Your lens is whether the new tests would catch the bug they claim to. For each
> added test, determine whether it fails against BASE. A test that passes on the
> pre-change tree asserts nothing. Also flag tests that assert the implementation
> back to itself rather than the required behavior.

Spec conformance and scope:

> Your lens is SPEC versus DIFF, in both directions. Report requirements SPEC
> states that DIFF does not satisfy, AND changes in DIFF that SPEC never asked
> for. Unrequested changes are findings — untested scope no one reviewed against
> a requirement.

Credential safety:

> Your lens is credential and secret exposure ONLY. Trace every credential,
> token, and connection string in DIFF: where it is read, where it is written,
> and whether it can reach a log, an error message, a test fixture, or a
> committed file. Report any path you cannot rule out. Uncertainty is a finding
> here, not a pass.

Refuter:

> Here is a finding from a code review. Your job is to REFUTE it. Read the code
> and decide whether the described failure can actually occur. Default to
> refuted=true — if you cannot demonstrate the failure is real, it is refuted.
> [For credential findings: default to refuted=false — uphold unless you can
> positively demonstrate the exposure is impossible.]

## Workflow script gotcha

**Raw backticks inside a JS template literal break the script parse.** Prompts
about code want backticks, and a workflow script is JavaScript, so a prompt built
as a template literal fails to parse the moment one appears. Build prompt strings
by joining an array of plain strings instead:

```js
const preamble = [
  "You are reviewing PR #N against its binding spec.",
  "Report ONLY defects. Every finding needs a file:line reference",
  "and a concrete failure scenario."
].join(" ");
```

## Boundaries

- `drain-queue` owns the queue loop — which PRs, in what order, and what happens
  to a confirmed finding. Its step 3 has the conductor review the diff alone;
  this is that step when one reviewer is not enough. It does not replace the
  cold-read gate that runs before the build.
- `detector-teeth-check` owns mutation mechanics. The test-veracity lens asks the
  teeth question at review scale and does not substitute for a mutation pass.
- `using-workflow` pins the stages a Workflow-dispatched _build_ runs. This is the
  review shape, dispatched the same way — neither one implies the other.
