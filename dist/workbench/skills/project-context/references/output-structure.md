# project.md Output Structure

The generated `project.md` must follow this structure. Scale depth to match the project — small projects may skip sections, complex projects may add subsections.

````markdown
# {Project Name} — Project Context

{One-sentence description: what it is, what it does, key technology.}

## Tech Stack

- **{Language/Runtime}** — {version constraint if known}
- **{Framework}** — {what it's used for}
- **{Key Library}** — {purpose}
- ...bulleted list, bold the tool name, annotate purpose

## Project Layout

```text
{annotated directory tree — one short phrase per entry}
```
````

## Data Flow

```text
{ASCII diagram showing source → transform → output pipeline}
```

## Data Sources

- `{SOURCE_NAME}` — {what it provides}
- ...for databases, APIs, local files, etc.

## Test Markers

- `{test command}` — {what it runs}
- `{marker name}` — {what it gates}

## Key Architecture Patterns

- **{Pattern name}** (`{file}`): {one-sentence explanation}
- ...only non-obvious patterns worth calling out

```

```
