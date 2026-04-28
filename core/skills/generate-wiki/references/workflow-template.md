# Workflow Doc Templates

## Workflow Index (`readme.md` or `{package}-workflow.md`)

Each package's workflows directory gets an index listing all workflows.

### Template

```markdown
# {Package} Workflows

## Workflow Index
- {Workflow Name}
  - Trigger: `{how to invoke — class method, CLI command, Dagster job}`
  - Doc: `{filename}.md`
- {Another Workflow}
  - Trigger: `{invocation}`
  - Doc: `{filename}.md`

---

## Shared Pipeline Steps

{If multiple workflows share common stages (e.g., input assembly, feature engineering),
document them once here rather than repeating in each workflow doc.}
```

## Individual Workflow Doc

### Template

```markdown
# {Workflow Name}

## Trigger
- {Schedule, CLI command, API call, UI button}
- Manual: `{exact code or command to run it}`

## Steps

### Step 1 — {Name}
{What happens. Be specific about data transformations, API calls, file I/O.}
- {Sub-step or detail}
- {Sub-step or detail}

### Step 2 — {Name}
{What happens.}

...

## Inputs
{What data/config this workflow needs to start.}

## Outputs
{What this workflow produces: files, artifacts, database records, reports.}

## Failure Modes
- **{Failure type}**: {what happens, how it's handled or recovered}
- **{Another failure}**: {handling}
```

### Include

- **Trigger**: Exactly how to start (command, schedule, UI). Include both automated and manual invocations.
- **Steps**: Sequential runtime description. Specific about data flow, transformations, side effects.
- **Inputs/Outputs**: What goes in and what comes out.
- **Failure modes**: Known error conditions and recovery behavior.

### Exclude

- Code-level implementation details (that's architecture)
- Configuration reference (link to config docs instead)
- Performance data or benchmarks

### Shared steps pattern

When multiple workflows share common stages, document the shared pipeline **once** in the workflow index file and reference it from individual docs. Don't duplicate content across workflow files.

## Directory Structure

```
{wiki_dir}/workflows/
├── package-a/
│   ├── readme.md              # Workflow index
│   ├── daily-job.md           # Individual workflow
│   └── backfill.md
└── package-b/
    ├── readme.md
    ├── training.md
    └── inference.md
```
