# Architecture Doc Templates

## Package Overview (`overview.md`)

Every package directory gets an `overview.md`. This is the directory's index page in the wiki sidebar.

### Template

```markdown
# {Package Name} Architecture

## Purpose
{One paragraph: what this package does, why it exists.}

## Primary Entrypoint
- `{package}/{file}.py` -> `{ClassName}` or `{function_name}()`

{Brief description of what the entrypoint orchestrates.}

## Package Components
- {Component group}: `{package}/{file_or_dir}`
  - {Sub-component if nested}
- {Another group}: `{package}/{file_or_dir}`

## External Dependencies
- {Internal package}: {what it provides to this package}
- {External lib/service}: {purpose}

## Data Contracts
- Input: {what goes in, from where, type/shape}
- Output: {what comes out, format/type}

## Structural Notes
{Non-obvious design decisions, constraints, gotchas. Omit section if none.}
```

### Include

- **Purpose**: Why the package exists and what problem it solves
- **Entrypoint**: The facade class or function external consumers call
- **Components**: Internal modules grouped by responsibility
- **Dependencies**: Internal (other packages) and external (libraries, APIs, databases)
- **Data contracts**: What goes in and out — types, shapes, formats
- **Structural notes**: Only non-obvious things (e.g., "local simulation intentionally unsupported")

### Exclude

- Implementation details (algorithms, line-by-line logic)
- Configuration values (those belong in config files)
- Usage examples (those belong in workflow docs)
- Historical context or changelogs

## Component Docs

For significant sub-modules within a package. Lighter than an overview.

### Template

```markdown
# {Component Name}

## Role
{One sentence: what this component does within the package.}

## Key Classes/Functions
- `{ClassName}` / `{function_name}()`: {what it does}

## Inputs
{What this component receives and from where.}

## Outputs
{What this component produces.}

## Integration
{How this connects to other components in the package.}
```

### When to create component docs

Create when a sub-module has:
- Its own distinct responsibility
- Non-trivial internal structure (multiple classes or files)
- External consumers or data contracts worth documenting

Skip for:
- Simple utility files
- Internal helpers used by one parent module
- Files under ~50 lines with obvious purpose

## System Overview (`system-overview.md`)

One doc at `{wiki_dir}/architecture/system-overview.md` describing how packages connect.

### Template

```markdown
# {Project} System Overview

## Purpose
{What the project does as a whole.}

### {package_name}
{2-5 sentences: purpose, entrypoint, key capabilities.}

### {package_name}
...

## Runtime Surfaces
{How the project is executed: CLI, web apps, orchestration, scheduled jobs.}

## External Integrations
{Databases, APIs, cloud services — with connection method.}

## Design Notes
{Cross-cutting concerns: configuration approach, logging, deployment modes.}
```

## Directory Structure

```
{wiki_dir}/architecture/
├── system-overview.md         # Cross-package view
├── repo-structure.md          # Annotated directory tree
├── package-a/
│   ├── overview.md            # Package index (directory link in sidebar)
│   ├── component-a.md         # Significant sub-module
│   └── sub-module/
│       ├── overview.md        # Sub-module index
│       └── specific-thing.md
└── package-b/
    ├── overview.md
    └── another-component.md
```
