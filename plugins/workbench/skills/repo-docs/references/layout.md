# Layout

Where each mode lives, what the landing pages are, and the order a repository's
docs grow in. The tree below is the destination, never a scaffold: a directory
exists only once its first real file does.

```
README.md                    landing page, mode=landing, near 150 lines
docs/
  README.md                  hub landing page (once two or more mode directories exist)
  tutorials/                 tutorial, one lesson per file
  how-to/                    how-to, one goal per file ("How to <verb> …")
  reference/                 reference, mirrors the machinery
  explanation/               explanation, "About <topic>"
  plans/  archive/  …        process directories, untouched and exempt
```

Directory names are always these four. House names such as `runbooks/` or
`decisions/` are aliases for classifying existing content
([compass.md](compass.md)), not names for new directories.

## The root README

The front door, `mode=landing`, near 150 lines. Exempt from the one-mode rule because it introduces every mode; past the bar the checker reports `readme-length`, and the fix is an extraction into a mode directory. Structure, writing rules, `covers`, and the hand-written or legacy-footer rule: [readme-structure.md](readme-structure.md).

## Landing pages under docs/

A landing page reads like an overview: it introduces what is inside, it does not
merely list it. Two rules from the removed "Diátaxis in complex hierarchies" page
(withdrawn from the live site; archived copy: <https://web.archive.org/web/20260802004758/https://diataxis.fr/complex-hierarchies/>):

- A landing page introduces its contents with a sentence or two per group, then links.
- Lists longer than about seven items are hard to read; break them into groups with
  a short introduction each.

`docs/README.md` is the hub. It exists once the repo has two or more mode directories, and creating it is part of the change that creates the second mode directory: a landing page, not a second doc.
One short paragraph per mode that exists, linking into it, plus one line naming the
process directories and what they are for.

```markdown
# Documentation

How this repository works and how to operate it, for engineers onboarding to it.

## Reference

What the system is made of, where each piece lives, and how data moves:
[architecture](reference/architecture.md), [module map](reference/module-map.md),
[data flow](reference/data-flow.md), [conventions](reference/conventions.md).

## How-to guides

Operating procedures for people already familiar with the system:
[run and deploy](how-to/run-and-deploy.md), [recover a failed partition](how-to/recover-a-failed-partition.md).

## Explanation

Why it is built this way: [about the partition scheme](explanation/partition-scheme.md).

Plans and review records live in `plans/` and `archive/`; they are process
artifacts, not documentation.

<!-- repo-docs: mode=landing baseline=<sha> covers=docs -->
```

A mode directory gets its own `README.md` once it holds more than about five files.
It is a landing page and declares `mode=landing`.
Same shape as the hub: grouped, introduced, linked.

## Process directories

`docs/plans/` (prd-to-plan), `docs/archive/`, `docs/dev-cycle/`, code, security, and
MR review directories are not documentation in the Diátaxis sense. The skill never
classifies, moves, or stamps them, and the checker skips them. Add repo-specific ones
with `--exempt`.

Decision records (`docs/decisions/`, `DECISIONS.md`, ADRs) are documentation, in
explanation mode by alias. They stay where they are, get linked from
`docs/explanation/` and the hub, and are never moved or rewritten by this skill.

## Order of growth

1. **README + reference pass.** A repo with nothing gets the landing page and
   `docs/reference/` in one grounded pass, because both are derived from source, not
   from judgment about what readers need next. No other directory is created.
2. **One doc per invocation**, and first whenever a need is named before the reference pass exists. Each how-to, tutorial, or explanation
   answers a need someone named: a runbook that does not exist, a why-question asked
   twice, steps found inside a reference table. The directory appears with the file.
3. **Landing pages** appear when the count demands them: the hub at two mode
   directories, a per-mode README past about five files.

## Migration target for the old reference set

Repos stamped by `repo-reference-docs` have `docs/reference/` holding a mix. The
destination for each house file, applied one move per pass
([workflow.md](workflow.md#migration)):

| Existing file                                                                                      | Mode        | Destination                                                                      |
| -------------------------------------------------------------------------------------------------- | ----------- | -------------------------------------------------------------------------------- |
| `architecture.md`, `module-map.md`, `data-flow.md`, `conventions.md`, `schema.md`, `data-model.md` | reference   | stay in `docs/reference/`; rationale paragraphs extracted to `docs/explanation/` |
| `operations.md`, `deployment-runbook.md`, `*-runbook.md`                                           | how-to      | `docs/how-to/<slug>.md`; a single-goal runbook is retitled "How to …", a multi-goal runbook keeps its name on the move and is split later, one extraction per pass             |
| `data-quality.md`                                                                                  | reference   | stays; describes the checks that exist, not why                                  |
| `column-assumptions-methodology.md`, `DECISIONS.md`-style rationale                                | explanation | `docs/explanation/<topic>.md`; decision records themselves stay put              |
| `README.md` (reference index)                                                                      | landing     | becomes `docs/reference/README.md` or folds into the hub                         |

Landing-page rules condensed from [Diátaxis](https://diataxis.fr) by Daniele Procida, CC BY-SA 4.0.
