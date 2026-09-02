# Reference

Reference is the technical description of the machinery and how to operate it. It is information-oriented and led by the product it describes, not by the needs of the reader. Diátaxis puts it plainly: "One hardly reads reference material; one consults it."

Reference is austere, neutral, and factual. It is structured like the machinery itself, so a reader can move through the docs and the code at the same time. Its only job is to describe, as succinctly as possible and in an orderly way.

For telling the four modes apart, see [compass.md](compass.md). For where reference files live, see [layout.md](layout.md); for the write and migrate loop, see [workflow.md](workflow.md).

## Principles

- Describe and only describe. No instruction and no rationale: a task belongs in a how-to ([mode-how-to.md](mode-how-to.md)), a reason belongs in an explanation ([mode-explanation.md](mode-explanation.md)). Reference links out to both.
- Adopt standard patterns. Every reference page in a repo has the same shape, so a reader finds the same kind of fact in the same place every time. Reference is not the place for stylistic range.
- Respect the structure of the machinery. Docs mirror code structure: a method sits under its class, a model under its schema, a module under its package.
- Provide examples that illustrate without teaching. A usage example shows a command in context; it does not walk the reader through a lesson or defend a design.
- Auto-generated reference is a floor, not the whole documentation. Generated API docs stay faithful to the code, but they do not replace the hand-written set below.

## Language

| Phrase                                                                                           | Function                                                           |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| "The `settings` module inherits the framework defaults. It is defined in `src/app/settings.py`." | State facts about the machinery and its behaviour.                 |
| "Sub-commands are: `build`, `check`, `sync`."                                                    | List commands, options, operations, flags, limits, error messages. |
| "You must use a. You must not apply b unless c. Never d."                                        | Warn where appropriate.                                            |

Rule of thumb from Diátaxis: "If it's boring and unmemorable it's probably reference." Tables of information and lists of things (classes, methods, attributes, columns, flags) belong here.

## The reference set

The standard docs under `docs/reference/` for a code repository. Each one describes; none explains why.

| File                                   | Describes                                                                                                                                                                     | Covers, typical paths                         |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `architecture.md`                      | What the system is made of: components, how they connect, entry points, external dependencies. One Mermaid component diagram. No rationale; that goes to `docs/explanation/`. | `src/`, `pyproject.toml`, entry-point modules |
| `module-map.md`                        | Per top-level package or directory: responsibility, key files, public surface. The "where does X live" table.                                                                 | Every top-level package directory             |
| `data-flow.md`                         | Input, transformation, output per major operation. A sequence diagram for the one or two flows that matter. Where state lives. Invariants stated as facts.                    | Pipeline, handler, and storage modules        |
| `conventions.md`                       | Naming, recurring patterns with one canonical example path each, glossary of domain terms.                                                                                    | The modules cited as canonical examples       |
| `schema.md` (optional, database repos) | Entities, keys, join paths, view dependencies. Generated from DDL per [generated-erd.md](generated-erd.md); the footer sits outside the generated markers.                    | DDL files, migrations, view definitions       |

Accepted house aliases within `docs/reference/`: `data-model.md` is schema by another name; `data-quality.md` describes the checks that exist, not why they exist.

Diagram type, size, and validation before commit are covered in [mermaid-guidelines.md](mermaid-guidelines.md).

## Per-doc layouts

Starting shapes, not rigid forms. Adapt headings to the repo, drop sections that do not apply, never pad. Every hint is descriptive; where a reason wants to be written, link out instead. The `prettier-ignore` comment keeps each skeleton compact under the repo formatter.

### architecture.md

<!-- prettier-ignore -->
```markdown
# Architecture
## What this system is
One paragraph: purpose and scope. For why, see docs/explanation/<topic>.md.
## Components
Each top-level part and its responsibility; Mermaid `flowchart` of their dependencies, then prose on the edges.
## Entry points
Where execution starts: CLI, server, jobs, `__main__`.
## External dependencies
Services, APIs, datastores the system calls.
<!-- repo-docs: mode=reference baseline=<commit-sha> covers=<comma,separated,paths> -->
```

### module-map.md

<!-- prettier-ignore -->
```markdown
# Module map
## Packages
Table: directory, responsibility, key files, public surface; one row per top-level package. Boundaries stated as facts ("`api/` does not import `storage/`"). For why a package exists, see docs/explanation/<topic>.md.
## Where does X live
Table: concern, directory, file.
<!-- repo-docs: mode=reference baseline=<commit-sha> covers=<comma,separated,paths> -->
```

### data-flow.md

<!-- prettier-ignore -->
```markdown
# Data flow
## Primary flows
Per major operation: input, transformation, output, and the component that owns each step.
## Sequences
Mermaid `sequenceDiagram` for the one or two flows that matter, then prose.
## State
Where state lives: persisted, cached, derived.
## Invariants
Constraints that hold across the flow, stated as facts. For why they hold, see docs/explanation/<topic>.md.
<!-- repo-docs: mode=reference baseline=<commit-sha> covers=<comma,separated,paths> -->
```

### conventions.md

<!-- prettier-ignore -->
```markdown
# Conventions
## Naming
File, symbol, branch, and commit conventions in use, one example each.
## Patterns
Table: pattern, canonical example path. Error handling, config, testing, logging. For why a pattern was adopted, see docs/explanation/<topic>.md.
## Glossary
Table: term, definition. Domain terms and acronyms.
<!-- repo-docs: mode=reference baseline=<commit-sha> covers=<comma,separated,paths> -->
```

### schema.md

<!-- prettier-ignore -->
```markdown
# Schema
## What this schema is
One paragraph; links to the DDL and any data dictionary. Grain splits, derived versus authored tables, append-only tables, stated as facts. For why the model has this shape, see docs/explanation/<topic>.md.
## Entities
Mermaid `erDiagram` plus a table: entity, grain, primary key, natural key.
## Join paths and view dependencies
Key pairs that join and the grain each yields; Mermaid `flowchart` DAG plus a table: view, reads from, purpose.
## Provenance
One sentence: diagrams derive from the repo's DDL, not the live database; neither runs in CI. Link the how-to for verifying against the live engine.
<!-- repo-docs: mode=reference baseline=<commit-sha> covers=<comma,separated,paths> -->
```

## Compass check

The two questions from [compass.md](compass.md), answered for this mode:

- Action or cognition? Reference informs cognition: it states what is, not what to do. Steps belong in a how-to.
- Acquisition or application? Reference serves application: it is consulted during work, not studied away from it. Theory to think about belongs in explanation.

The leak to watch for is explanation sprinkled into reference. It starts with an illustrative example that grows expansive and begins to say why, or what if, or how it came to be. The reference is interrupted by the digression, and the explanation never gets room to do its own work.

Rule: when a reference paragraph contains "because", "historically", "we chose", or weighs alternatives, that paragraph is an extraction candidate for `docs/explanation/`. Extract one per pass and leave a link behind; see [workflow.md](workflow.md).

Condensed from [Diátaxis](https://diataxis.fr) by Daniele Procida, CC BY-SA 4.0.
