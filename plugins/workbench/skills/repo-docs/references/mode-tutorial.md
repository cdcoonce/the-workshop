# Tutorial

A tutorial is a lesson: it takes a learner by the hand through an exercise that is meaningful, successful, logical, and usefully complete. It serves the reader's study, not their work; what matters is what the learner acquires, not what they produce. In documentation the instructor is absent, so the text carries the whole responsibility for the learner's safety and success.

## When repo-docs writes one

Write a tutorial file only when the user explicitly asks for one (they say "tutorial" or ask for a committed lesson under `docs/`) and the compass agrees the content serves study rather than work. A "tutorial" that is really a procedure, such as "a tutorial on deploying to prod", is written as a how-to. Conversational requests ("teach me this repo", "walk me through it", "explain this to me") hand off instead: `walkthrough` for an ephemeral session, or, where installed, `repo-crash-course` for a persistent tutor. Neither produces a file.

Two reasons for the high bar. Tutorials are the most revision-expensive mode: the end-to-end story must keep making sense, so a product change cascades through every step instead of landing in one place. A new tutorial is a maintenance commitment, not a routine addition.

## Principles

- Show the learner where they'll be going: state the goal at the outset so they see themselves building toward it.
- Deliver visible results early and often: every step produces a comprehensible result, however small.
- Maintain a narrative of the expected: say what will happen, show actual output, flag the likely signs of going wrong.
- Point out what to notice: close the loop by naming what changed, in passing, as the lesson moves along.
- Target the feeling of doing: tie purpose and action together so the learner finds the rhythm of the craft.
- Encourage and permit repetition: make steps repeatable wherever possible; learners repeat a success to confirm it works.
- Ruthlessly minimise explanation: one clause of why, then a link. Explanation distracts from doing.
- Focus on the concrete: this problem, this action, this result. General patterns emerge from particulars on their own.
- Ignore options and alternatives: guide only what is required to reach the conclusion.
- Aspire to perfect reliability: the learner must see the promised result every time, or confidence collapses.

## Language

| Phrase                                                     | Why                                                                                                                                |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| We ...                                                     | First-person plural affirms the tutor-learner relationship: the learner is not alone.                                              |
| In this tutorial, we will ...                              | Describes what the learner will accomplish.                                                                                        |
| First, do x. Now, do y.                                    | Leaves no room for ambiguity or doubt.                                                                                             |
| We must always do x before y because ... (see explanation) | Minimal explanation in the most basic language, linked out for depth.                                                              |
| The output should look something like ...                  | Gives the learner clear expectations.                                                                                              |
| Notice that ... Remember that ... Let's check ...          | Clues that confirm the learner is on the right track.                                                                              |
| You have built ...                                         | Describes, and mildly admires, what the learner accomplished.                                                                      |
| Avoid: In this tutorial you will learn ...                 | Diátaxis calls this "presumptuous and a very poor pattern": only the learner can learn, so promise the activity, not the learning. |

## Not a how-to

| Tutorial                                              | How-to                                          |
| ----------------------------------------------------- | ----------------------------------------------- |
| Helps the learner acquire competence                  | Helps the competent user perform a task         |
| Contrived, safe setting; the unexpected is eliminated | Real world; the unexpected must be prepared for |
| Single path, no choices or alternatives               | Forks and branches: if this, then that          |
| Responsibility lies with the teacher                  | Responsibility lies with the user               |
| Concrete and particular                               | General, because each case differs              |

The difference is the need served, study versus work, not basic versus advanced: a tutorial can cover something advanced and a how-to can cover something basic. See [mode-how-to.md](mode-how-to.md).

## Template

```markdown
# Build a <thing> with <repo>

In this tutorial, we will <accomplish X>. Along the way we will encounter <tool> and <concept>.

## What you need

- <prerequisite, with version>

## 1. <First action>

<Do x.> The output should look something like:

    <exact expected output>

Notice that <what changed>.

## 2. <Next action>

Now that <x is done>, <do y>. The output should look something like:

    <expected output>

If the output doesn't show <sign>, you have probably forgotten to <step>.

## What you built

You have built <thing>. It <does what>.

Where to go next: [How to <task>](../how-to/<slug>.md) for a real-world task, [About <design choice>](../explanation/<slug>.md) for the reasoning.

<!-- repo-docs: mode=tutorial baseline=<commit-sha> covers=<comma,separated,paths> -->
```

Title with "Build a ..." or "Create your first ...". Every numbered step ends with an expected-result line. Placement under `docs/tutorials/` is in [layout.md](layout.md); the write and migrate loop is in [workflow.md](workflow.md).

## Compass check

Ask of every paragraph: does it inform action, and does it serve the acquisition of skill? Yes to both means it belongs here; any other answer points to a sibling mode via [compass.md](compass.md). Leaks to watch for:

- Explanation creeping in: a "why" longer than one clause moves to [mode-explanation.md](mode-explanation.md) territory, with a link left behind.
- Options and alternatives: "or you could ..." is a fork, and forks belong in [mode-how-to.md](mode-how-to.md).
- Flag-by-flag coverage: a tutorial that lists every option has become a [mode-reference.md](mode-reference.md) page wearing a lesson's clothes.

Condensed from [Diátaxis](https://diataxis.fr) by Daniele Procida, CC BY-SA 4.0.
