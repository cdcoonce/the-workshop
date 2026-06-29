# Codebase Analysis Methodology Reference

This is the detailed reference for **Step 1 (Codebase Analysis)** of the project-context workflow. The main SKILL.md contains a brief summary of each phase and links here for the full methodology.

Follow these three phases sequentially. Tag every extracted fact with a confidence level. The output of all three phases feeds into Step 2 (Clarifying Questions) and Step 3 (project.md Generation).

---

## Confidence Tracking

Tag every fact recorded during analysis:

| Tag               | Meaning                                                  | Downstream effect                           |
| ----------------- | -------------------------------------------------------- | ------------------------------------------- |
| `[confirmed]`     | Read directly from source code, config, or documentation | Use in project.md without qualification     |
| `[inferred-high]` | Strong evidence from naming, structure, or patterns      | Use in project.md, flag for user review     |
| `[inferred-low]`  | Guess based on partial or ambiguous evidence             | Becomes a **clarifying question** in Step 2 |
| `[unknown]`       | Cannot determine from codebase analysis alone            | Becomes a **clarifying question** in Step 2 |

Example:

```
- Project name: "am-external-reporting-tools" [confirmed — pyproject.toml]
- Primary purpose: Generates AM investor reports [inferred-high — module names + docstrings]
- Deployment target: Azure App Service [inferred-low — saw azure dependency but no infra config]
- Target audience: [unknown]
```

---

## Phase 1: Project Metadata Scan

**Goal:** Establish what the project is, what it depends on, and how it is configured.

### Tool Actions

**1. Glob for project and build files — run all in parallel:**

```
**/pyproject.toml          **/setup.py             **/setup.cfg
**/package.json            **/requirements*.txt    **/uv.lock
**/Cargo.toml              **/go.mod               **/pom.xml
**/Makefile                **/justfile             **/Taskfile.yml
**/Dockerfile              **/docker-compose.yml
**/.env.example            **/.env.template        **/.env.sample
```

**2. Glob for CI/CD and toolchain configs — run in parallel:**

```
**/.gitlab-ci.yml
**/.github/workflows/*.yml
**/.github/workflows/*.yaml
```

```
**/ruff.toml               **/.eslintrc*           **/.prettierrc*
**/.pre-commit-config.yaml **/mypy.ini
**/tsconfig.json           **/biome.json
```

```
**/LICENSE*                 **/CLAUDE.md            **/CONTRIBUTING.md
```

**3. Read each found file. Extract and record:**

- Project name and version
- Language and version constraint (e.g., `requires-python = ">=3.11"`)
- Package manager — detect from lock files: `uv.lock` (uv), `poetry.lock` (poetry), `package-lock.json` (npm), `yarn.lock` (yarn), `pnpm-lock.yaml` (pnpm), `Cargo.lock` (cargo), `go.sum` (go)
- All dependencies — categorize as **core**, **dev/test**, **optional**. For each major dependency, note its purpose in one phrase
- Available scripts/commands — from `[project.scripts]`, Makefile targets, `package.json` scripts, etc.
- Environment variables — from `.env.example` or equivalent, classify as **required** or **optional**
- CI stages and what each does
- Test markers and custom pytest/jest/cargo configuration
- Linting/formatting tools and their config

### Phase 1 Record Template

```markdown
## Phase 1 — Project Metadata

| Field           | Value | Confidence |
| --------------- | ----- | ---------- |
| Project name    |       |            |
| Version         |       |            |
| Language        |       |            |
| Package manager |       |            |
| License         |       |            |

### Dependencies
| Dependency | Category | Purpose |
|---|---|---|
| | core / dev / optional | |

### Scripts & Commands
| Command | What it does |
|---|---|
| | |

### Environment Variables
| Variable | Required/Optional | Purpose |
|---|---|---|
| | | |

### CI/CD Pipeline
| Stage | What it does |
|---|---|
| | |

### Test Configuration
| Marker/Flag | Purpose |
|---|---|
| | |
```

---

## Phase 2: Architecture Scan

**Goal:** Understand how the codebase is organized and how modules relate.

### Tool Actions

**1. Glob for all source files to get the complete file tree.**

Use language-appropriate patterns:

```
# Python
**/src/**/*.py    **/lib/**/*.py    **/app/**/*.py    **/*.py

# JavaScript/TypeScript
**/src/**/*.{ts,tsx,js,jsx}    **/lib/**/*.{ts,tsx,js,jsx}

# Rust
**/src/**/*.rs

# Go
**/*.go
```

Exclude virtual environments, build artifacts, and `node_modules/`.

Record the directory structure with brief annotations.

**2. Identify entry point(s).**

Grep for entry point patterns appropriate to the language/framework:

| Language/Framework | Grep pattern                                                  |
| ------------------ | ------------------------------------------------------------- |
| Python             | `if __name__`                                                 |
| Python (Streamlit) | Look for file passed to `streamlit run` (often `app.py`)      |
| Python (CLI)       | `[project.scripts]` in pyproject.toml, `@click.command`       |
| Node.js            | `"main"` in package.json, `"bin"` field                       |
| Rust               | `fn main()` in `src/main.rs`                                  |
| Go                 | `func main()` in `main.go`                                    |

Read each entry point file. Record what it imports and orchestrates.

**3. Build the import graph.**

Grep for import patterns across all source files:

| Language   | Grep pattern                                        |
| ---------- | --------------------------------------------------- |
| Python     | `^from\s+\S+\s+import\|^import\s+\S+`              |
| TypeScript | `^import\s+.*from`                                  |
| Rust       | `^use\s+crate::`                                    |
| Go         | `"[module-path]/`                                   |

For each source file, record **internal** imports only (other project modules). Classify modules:

- **Leaf** — imported by others, imports nothing internal (e.g., `exceptions.py`, `constants.ts`)
- **Core** — imported by 3+ other modules (e.g., `models.py`, `utils.ts`)
- **Orchestrator** — imports many modules, imported by few (e.g., `app.py`, `main.ts`)

**4. Identify the architecture pattern.**

| Pattern              | Indicators                                                                        |
| -------------------- | --------------------------------------------------------------------------------- |
| Data pipeline / ETL  | `*_transformer`, `*_loader`, `*_writer`, `*_client`; sequential DataFrame flow    |
| Web application      | Route handlers, middleware, templates, static assets                               |
| CLI tool             | `click`/`typer`/`argparse`/`clap` usage; command/subcommand pattern               |
| Library / SDK        | Public API re-exports in `__init__.py` or `index.ts`; no entry point              |
| Report generator     | Template files, mapping configs, data → template population workflow              |
| Dashboard            | `st.`/React/Vue calls; layout components; data visualization                      |
| Microservices        | Multiple independent services; shared proto/schema definitions; message queues     |
| Monolith             | Single large application; MVC or layered architecture; ORM models                 |

**5. Read config files referenced by source code.**

Grep for config-loading patterns:

```
yaml\.safe_load|json\.load|toml\.load|configparser
load_dotenv|os\.environ|os\.getenv
```

Read any discovered config files — they often contain critical domain knowledge.

### Phase 2 Record Template

```markdown
## Phase 2 — Architecture

### Directory Structure
```

project-root/
├── src/      # [purpose]
├── config/   # [purpose]
└── tests/    # [purpose]

```

### Entry Points
| File | Type | What it orchestrates |
|---|---|---|
| | | |

### Module Classification
| Module | Role | Key imports/exports |
|---|---|---|
| | core / leaf / orchestrator | |

### Architecture Pattern
- **Pattern:** [name] [confidence]
- **Evidence:** [indicators matched]

### Runtime Configuration
| Config file | What it controls |
|---|---|
| | |
```

---

## Phase 3: Data Sources & Infrastructure

**Goal:** Map external dependencies, test structure, and error patterns.

### Tool Actions

**1. Identify external data sources and output targets.**

Grep for connection/client patterns:

```
# Databases
connect|connection_string|DATABASE_URL|SnowflakeClient|pg_connect

# APIs
requests\.(get|post|put)|httpx\.|fetch\(|axios\.|GraphAPI

# File I/O
open\(|read_csv|read_parquet|read_excel|openpyxl|pd\.read_
```

For each external system found, record: name, what data flows in/out, which module handles it.

**2. Map test structure.**

Glob for test files and fixtures:

```
**/test_*.py       **/*_test.py      **/*.test.{ts,tsx,js}
**/tests/**/*      **/__tests__/**/* **/spec/**/*
**/conftest.py     **/fixtures/**/*  **/testdata/**/*
```

Read `conftest.py` or equivalent setup files. Grep for custom markers:

```
pytest\.mark\.
```

Build a test-to-module mapping: which tests cover which source modules.

**3. Identify error handling patterns.**

Grep for custom exception/error classes:

```
class\s+\w+(Error|Exception)\(
```

If a dedicated `exceptions.py` or `errors.ts` exists, read it fully.

### Phase 3 Record Template

```markdown
## Phase 3 — Data Sources & Infrastructure

### External Systems
| System | Direction | Data | Handled by |
|---|---|---|---|
| | input / output / both | | |

### Test Structure
| Test file | Module under test | Markers |
|---|---|---|
| | | |

### Custom markers: [list]
### Fixture files: [list]

### Exception Hierarchy
| Exception | Trigger |
|---|---|
| | |
```

---

## Stop Criteria

### Stop analyzing when ALL of these are true:

- Architecture pattern identified with `[confirmed]` or `[inferred-high]`
- Every module with 100+ lines has been read — purpose known
- All external data sources identified
- Test markers and commands documented
- Entry point(s) identified and read

### Do NOT stop if any of these are true:

- Only config files have been read, not source code
- Cannot explain what the core module (highest in-degree) does
- Found a config file referenced in source code but have not read it
- Entry point identified but not yet read

---

## Scaling Guidance

| Codebase Size       | Strategy                                                                                      |
| ------------------- | --------------------------------------------------------------------------------------------- |
| **Small** (1-7 files)   | Execute all three phases sequentially. Read every source file.                           |
| **Medium** (8-20 files) | Phases 1-2 sequentially. Dispatch 2-3 parallel agents for Phase 3 module analysis.       |
| **Large** (20+ files)   | Phases 1-2 sequentially. Dispatch 4-6 parallel agents for Phase 3 grouped by directory.  |

When dispatching parallel agents, always include the import graph from Phase 2 in each agent's prompt.
