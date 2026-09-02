# Explanation

Explanation is a discursive treatment of a subject that permits reflection. It is understanding-oriented: it deepens and broadens what the reader grasps about a topic and joins things together. Readers consult it away from the work, and it answers the question "Can you tell me about …?"

Explanation is less urgent than the other three modes but no less important. Diátaxis is blunt about it: "It's not a luxury." A repo whose docs never say why leaves every reader's knowledge of it loose and fragile.

## Where explanation lives in a house repo

Explanation lives at `docs/explanation/<topic>.md`: rationale, design discussion, background, and trade-offs. See [layout.md](layout.md) for the directory rules and [workflow.md](workflow.md) for how a file gets there.

Decision records are explanation by alias and stay exactly where they are. The skill classifies them, links to them from explanation and reference docs, and never moves or rewrites them.

| Alias | Where it stays |
| --- | --- |
| ADRs | `docs/decisions/ADR-*.md` |
| Decision log | `DECISIONS.md` |



Plans under `docs/plans/` are process files owned by `prd-to-plan`; the skill links to a plan's decisions section and never classifies it. Brainstorm write-ups are classified like any other doc.

Explanation is the usual destination of an extraction. The paragraph in a reference doc that says why, and the digression in a tutorial, both move here; see [mode-reference.md](mode-reference.md) and [mode-tutorial.md](mode-tutorial.md) for what each of those modes keeps.

## Naming

Apply the "About" test: every title should read naturally with an implicit "About" in front of it. "About user authentication" and "About the partition scheme" pass; "Configuring authentication" and "Partition reference" fail.

The slug drops the word: `docs/explanation/user-authentication.md`, `docs/explanation/partition-scheme.md`. A real or imagined why-question is the best prompt for the piece and the best guard against its open-endedness; without one, draw a reasonable boundary and stop there.

## Principles

- Make connections: to other parts of the system, to the bigger picture, even to things outside the topic when that helps.
- Provide context: design decisions, history, technical constraints, and their implications, with specific examples.
- Talk about the subject: alternatives, possibilities, and the reasons behind choices. Explanation is around a topic, not inside it.
- Admit opinion and perspective: explanation may weigh and judge, and it "can and must consider alternatives". Write it as discussion.
- Keep it closely bounded: explanation absorbs instruction and description if let. Both already have a home elsewhere; send them there.

## Language

| Phrase | Move |
| --- | --- |
| "The reason for x is because historically, y …" | Explain |
| "W is better than z, because …" | Offer a judgement |
| "An x in system y is analogous to a w in system z. However …" | Provide context |
| "Some users prefer w (because z). This can be a good approach, but …" | Weigh alternatives |
| "An x interacts with a y as follows: …" | Unfold the internals |

Rule of thumb: explanation is readable in the bath. It is consulted away from the work, not while doing it.

## Template

```markdown
# <Noun phrase that passes the About test>

**This answers:** <the why-question, one line>

## Background

<What the reader needs to hold in mind before the rest makes sense.>

## How it works today

<Two or three sentences, then link to the reference doc. Do not restate it.>

## Why it is this way

<Decisions, constraints, alternatives considered. Link decision records rather than paraphrasing them.>

## Trade-offs and open questions

<What was given up, and what remains unsettled.>

## Related

- Reference: [<name>](../reference/<file>.md)
- How-to: [<name>](../how-to/<file>.md)
- Decision: [<ADR>](../decisions/<file>.md)

<!-- repo-docs: mode=explanation baseline=<commit-sha> covers=<comma,separated,paths> -->
```

## Compass check

Two questions from [compass.md](compass.md) place a doc here: does it serve the reader's cognition rather than their action, and does it serve acquisition (study) rather than application (work)? Explanation answers yes to both. Watch for three leaks:

- Instructions creeping in: numbered steps or "run this" belong to a how-to; see [mode-how-to.md](mode-how-to.md).
- Tables of facts: lists of options, fields, or commands belong to reference; see [mode-reference.md](mode-reference.md).
- A lesson: a guided exercise with a guaranteed outcome is a tutorial, and a tutorial file is written only on explicit request; see [mode-tutorial.md](mode-tutorial.md).

The reference-vs-explanation test: would someone turn to this while working, executing a task (reference), or once they have stepped away and want to think about it (explanation)? Intuition is right most of the time and wrong exactly where reference starts to expand. Run the test on any reference doc whose illustrative example has grown into a why.

Condensed from [Diátaxis](https://diataxis.fr) by Daniele Procida, CC BY-SA 4.0.
