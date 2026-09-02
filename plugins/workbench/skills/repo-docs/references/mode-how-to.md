# How-to guide

A how-to guide gives directions that take an already-competent reader through a problem or towards a result. It is goal-oriented: it serves the reader's work, not their study. It assumes the reader knows what they want to achieve and can follow instructions correctly.

How-to guides are about goals and problems, never about tools. Tools appear only as the means to the reader's end. The reader has their hands on the machinery and a job to finish.

## House shapes that are how-to

| Shape                            | Typical goal                                                    |
| -------------------------------- | --------------------------------------------------------------- |
| Runbook                          | Run the pipeline for one day, one partition, or one environment |
| Operations guide                 | Deploy, monitor, recover, roll back                             |
| Troubleshooting guide            | Diagnose a named symptom and clear it                           |
| Migration or cutover procedure   | Move from the old schema, host, or deployment to the new one    |
| "How to add a new source" recipe | Extend the system along a supported axis                        |

Until now these shapes were filed under `docs/reference/`. They belong under `docs/how-to/`; see [layout.md](layout.md) for the move and [workflow.md](workflow.md) for the migrate loop.

## Naming

Titles say exactly what the guide shows, and start with "How to".

| Title                                               | Verdict  | Reason                                      |
| --------------------------------------------------- | -------- | ------------------------------------------- |
| How to integrate application performance monitoring | Good     | Promises a procedure and nothing else       |
| Integrating application performance monitoring      | Bad      | Could be about whether to do it, not how    |
| Application performance monitoring                  | Very bad | Could be how, whether, or merely what it is |

The file slug mirrors the title without a `how-to-` prefix, since the directory already says it: `docs/how-to/integrate-apm.md`.

## Principles

- Address real-world complexity: a guide useful only for one exact narrow case is rarely worth writing. Leave room for the reader to adapt it.
- Omit the unnecessary: practical usability beats completeness. Start and end in a reasonable place and let the reader join it to their own work.
- Describe a logical sequence: ordering carries meaning. Put first whatever sets up the environment, or the thinking, for what follows.
- Allow forks and multiple entry points: real problems are not linear. "If this, then that" is expected, and some steps call for judgement, not just action.
- Seek flow: ground the sequence in the reader's own activity. Do not make them switch contexts or hold thoughts open longer than necessary.
- Write from the user's perspective, not the machinery's. "To shut off the flow of water, turn the tap clockwise" looks like guidance and is not; nor is "select the options and press Deploy". A competent reader already knows where the switch is.
- Link to reference for the full option list instead of listing it. Action and only action: no digression, explanation, or teaching.

## Language

| Phrase                                                 | Use                                                  |
| ------------------------------------------------------ | ---------------------------------------------------- |
| "This guide shows you how to …"                        | State the goal: the problem or task the guide solves |
| "If you want x, do y. To achieve w, do z."             | Conditional imperatives for forks                    |
| "Refer to the x reference for a full list of options." | Keep the guide clean; reference owns completeness    |

A recipe is the model: it names what it produces, assumes basic competence, and a professional follows it to get the dish right, not to learn cooking.

## Template

```markdown
# How to <verb phrase>

This guide shows you how to <goal>.

## Before you start

- You have <assumed state>.
- <Tool> is installed and authenticated; see the [<tool> reference](../reference/<tool>.md).

## Steps

1. <Imperative step>.
   Verify: <what the reader should see>.
2. <Imperative step>. If <condition>, then <alternative>.
3. <Imperative step>.
   Verify: <what the reader should see>.

## If it fails

| Symptom        | Cause            | Fix          |
| -------------- | ---------------- | ------------ |
| <what you see> | <why it happens> | <what to do> |

## Related

- [<Reference doc>](../reference/<name>.md) for the full option list
- [<Explanation doc>](../explanation/<name>.md) for why it works this way

<!-- repo-docs: mode=how-to baseline=<commit-sha> covers=<comma,separated,paths> -->
```

## Compass check

Ask the two questions from [compass.md](compass.md): does the content inform action rather than cognition, and does it serve the application of skill rather than its acquisition? Both yes means how-to.

Leaks to catch:

- Teaching or motivating the reader: belongs in a tutorial, see [mode-tutorial.md](mode-tutorial.md).
- Explaining why the steps are what they are: belongs in explanation, see [mode-explanation.md](mode-explanation.md).
- Listing every option or flag: belongs in reference, see [mode-reference.md](mode-reference.md).

The single most common conflation in software documentation is tutorial versus how-to. The test: is the reader at study, acquiring a skill, or at work, applying one?

Condensed from [Diátaxis](https://diataxis.fr) by Daniele Procida, CC BY-SA 4.0.
