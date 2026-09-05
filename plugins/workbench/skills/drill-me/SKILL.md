---
name: drill-me
description: >
  Closed-book multiple-choice drilling that tells a recall gap apart from a
  comprehension gap. Use when Charles invokes /drill-me, or asks to be drilled,
  quizzed, or tested on material — "quiz me", "drill me", "test me on this",
  "exam-style practice" — especially before an assessment.
---

# Drill Me

Assess by asking, not by explaining. The output is a diagnosis: what is known,
what is merely recognized, and what is wrong in a way that predicts a specific
failure. Teaching happens only on a miss.

**Explicit-invoke by design.** Answer an ordinary question directly. This is an
opt-in assessment mode, not a reflex for every "how does X work?".

## The one rule that cannot be dropped

**Generate each question's correct-answer position with a random number
generator before writing the options, and follow the generated list.** Never
place the correct option by judgment.

Authoring by feel parks the answer in slot one. The observed failure was
position 1 on eight consecutive questions — which made every result
uninterpretable and cost a re-run to recover the signal. The pull comes from the
habit of listing a recommended option first; assessment inverts that. Eyeballing
a distribution is exactly what fails, so compute it:

```bash
python3 -c "import random; print([random.randint(1,4) for _ in range(12)])"
```

Honour the list, including runs that look insufficiently random. If the drill
outlives the list, generate another.

## Required reading

1. Read [protocol.md](references/protocol.md) — sourcing items, building
   distractors, cadence, and how to adapt mid-drill.
2. Read [diagnosis.md](references/diagnosis.md) — reading the signal, what to do
   on a miss, and banking the result.

## Core loop

- **Source every item from the material**, never from parametric memory. If the
  material is not at hand, say so and drill only what can be grounded.
- **One question per turn** unless the user asks for a batch. A batch is faster;
  one at a time adapts.
- **Every option carries a written-through rationale.** An option set where only
  the correct answer is argued convincingly is guessable without the stem.
- **Distractors encode real misconceptions** — the flipped relationship, the
  skipped condition, the plausible-but-wrong number. Filler options waste a slot
  and inflate the score.
- **Grade immediately**, one line, before the next question.
- **On a miss: scaffold, then retest with fresh surface content** — never
  verbatim. Re-asking the same item measures memory of the option text.
- **Adapt.** Stop drilling a block that comes back clean; escalate difficulty on
  effortless answers; drop difficulty after two misses in one area.

## Constraints

- **Closed book.** Say so at the start. The user reaching for notes is their
  call, but the drill assumes they did not.
- **Never reveal the answer key** in advance, and never hint by option length,
  specificity, or hedging language.
- **Report the tally honestly**, including items the user got right by
  elimination if they say so. An inflated score defeats the purpose.
- **A drill is not a lesson.** Teach only enough to convert the miss, then
  return to asking.
