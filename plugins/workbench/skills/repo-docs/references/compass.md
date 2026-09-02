# The compass

Diátaxis rests on two axes of craft. Documentation informs either action (practical steps, doing) or cognition (theoretical knowledge, thinking), and it serves either the acquisition of skill (study) or its application (work). Two axes yield exactly four quarters, "and there could not be three, or five"; the compass is the two questions that place a piece of writing in one of them.

## Two questions

| If the content... | ...and serves the user's... | ...then it must belong to... |
| ----------------- | --------------------------- | ---------------------------- |
| informs action | acquisition of skill (study) | a tutorial |
| informs action | application of skill (work) | a how-to guide |
| informs cognition | application of skill (work) | reference |
| informs cognition | acquisition of skill (study) | explanation |

Ask the two questions, action or cognition, study or work (Diátaxis says acquisition or application of skill), in whichever form fits the moment. Use the terms loosely at first; the axis matters more than the exact names.

| Form                                                     | Fits when                         |
| -------------------------------------------------------- | --------------------------------- |
| Is this written for x or y?                              | planning a new doc                |
| Is the writing in front of the reader engaged in x or y? | auditing an existing doc          |
| Does the user need x or y?                               | starting from a user's situation  |
| Is the intent to x or y?                                 | checking the author's own purpose |

Apply the questions close up, at the level of a sentence or a word, and from a distance, to the whole document. A doc can pass at one scale and fail at the other. Intuition often supplies an immediate answer that is also wrong, so run the compass before trusting a first impression.

## The map

|                      | Tutorial                         | How-to                            | Reference                                | Explanation                           |
| -------------------- | -------------------------------- | --------------------------------- | ---------------------------------------- | ------------------------------------- |
| answers the question | "Can you teach me to...?"        | "How do I...?"                    | "What is...?"                            | "Why...?"                             |
| oriented to          | learning                         | goals                             | information                              | understanding                         |
| purpose              | to provide a learning experience | to help achieve a particular goal | to describe the machinery                | to illuminate a topic                 |
| form                 | a lesson                         | a series of steps                 | dry description                          | discursive explanation                |
| analogy              | teaching a child how to cook     | a recipe in a cookery book        | information on the back of a food packet | an article on culinary social history |

Each mode has its own reference file: [mode-tutorial.md](mode-tutorial.md), [mode-how-to.md](mode-how-to.md), [mode-reference.md](mode-reference.md), [mode-explanation.md](mode-explanation.md). Directory placement is in [layout.md](layout.md).

## Where docs blur

Every mode shares one axis with two neighbours, and the shared quality is exactly what lets them bleed into each other. Crossing these boundaries is behind most documentation problems.

| Neighbours                | Shared quality                       | How the blur happens                                                                                      |
| ------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| tutorial and how-to       | both guide action as ordered steps   | the single most common conflation: a lesson sprouts branches and caveats, or a task guide starts teaching |
| how-to and reference      | both serve application (work)        | a how-to swells into an option catalogue, or a reference page grows step sequences                        |
| reference and explanation | both contain propositional knowledge | illustrative examples expand into why, what-if, and history; the explanation never gets room to develop   |
| explanation and tutorial  | both serve acquisition (study)       | an anxious tutorial author overloads the lesson with background the learner cannot use yet                |

Rules of thumb when the compass alone does not settle it:

- Boring and unmemorable: reference. Lists of things and tables of information belong in reference.
- Readable in the bath, or the answer to "tell me more about this topic" over a drink: explanation.
- The axis is study versus work, never basic versus advanced. A how-to can cover a trivial procedure; a tutorial can teach something advanced.
- The reference-or-explanation test: would someone reach for it mid-task, or after stepping away from the work to think?
- A tutorial follows a single line with no alternatives; a how-to forks and branches ("if this, then that").

## Alias table

Existing repos name docs by house convention, not by mode. These aliases give the default reading of a name; the content still decides, and a "getting started" that is a guided lesson rather than a task path is a tutorial.

| Existing name or directory                                                      | Mode                                     |
| ------------------------------------------------------------------------------- | ---------------------------------------- |
| runbook, operations                                                             | how-to                                   |
| troubleshooting, playbook                                                       | how-to                                   |
| getting-started (steps toward a task)                                           | how-to                                   |
| lesson, walkthrough as a committed file, first-project, "learn X by building Y" | tutorial                                 |
| module-map, schema, data-model                                                  | reference                                |
| API, CLI, configuration, environment variables                                  | reference                                |
| glossary, conventions                                                           | reference                                |
| DECISIONS.md, docs/decisions/, ADR-*                                            | explanation (kept in place, never moved) |
| brainstorms, background, discussion                                             | explanation                              |
| topics, concepts, design notes, "why we..."                                     | explanation                              |

Aliases classify existing content only. New files always use the four canonical directory names; see [layout.md](layout.md). A conversational "teach me this repo" is not a tutorial file: it hands off to `walkthrough` or, where installed, `repo-crash-course`. A tutorial file is written only when explicitly asked for and the content serves study; "a tutorial on deploying to prod" is a how-to.

## Exempt files

The compass never classifies these. README.md gets mode=landing and its own rules; the rest belong to another owner or to no mode at all.

- README.md and any other landing page (mode=landing): a front door that points into the four modes, exempt from the one-mode rule.
- CONTRIBUTING.md, CHANGELOG.md, LICENSE.
- `.claude/docs/project.md`: owned by `project-context`. CLAUDE.md: exempt, not this skill's to classify or write.
- `docs/plans/`: owned by `prd-to-plan`.
- `docs/archive/`, `docs/dev-cycle/`, and any review or security-review directory.

## Verdict format

Classifying an existing doc produces exactly four lines:

```text
Mode: <tutorial | how-to | reference | explanation | landing | mixed (dominant: <mode>)>
Evidence: <one sentence quoting or pointing at the passage that decides it>
Leak: <content that belongs to another mode, with that mode named, or "none">
Next action: <exactly one add, move, remove, or change, small enough for one pass>
```

- Mode is one of the four, or landing, or mixed with the dominant mode named. Mixed is a verdict, not a shrug; the next action must move the doc toward one mode.
- Evidence points at a passage in the body, never at a title, a filename, or a directory.
- Leak names the mode the stray content belongs to, so the next action can be a move rather than a delete.
- One action per pass, applied only after approval, then the doc is re-read and the compass runs again. The loop is in [workflow.md](workflow.md).

Condensed from [Diátaxis](https://diataxis.fr) by Daniele Procida, CC BY-SA 4.0.
