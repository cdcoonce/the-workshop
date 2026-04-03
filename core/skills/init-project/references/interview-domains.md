# Interview Domains Reference

Four domains drive the `/init-project` interview. Each domain has two question modes: **confirm** (normal mode, codebase exists) and **open-ended** (empty repo, interview-heavy mode).

All questions use `AskUserQuestion`. Present recommended defaults where applicable.

---

## Domain 1: Stack

Covers language, framework, package management, testing, and CI/CD.

### Questions

| Topic | Confirm Mode | Open-Ended Mode |
|---|---|---|
| Language & version | "I detected **{language} {version}**. Is this correct?" (Yes / No, it's {X}) | "What primary language will this project use?" |
| Framework | "I detected **{framework}**. Is this correct?" (Yes / No, it's {X}) | "What framework will this project use? (or 'none')" |
| Package manager | "I detected **{manager}** (found `{lockfile}`). Is this correct?" (Yes / No, it's {X}) | "What package manager will you use? (e.g., uv, pip, npm, yarn, pnpm, cargo)" |
| Test runner & command | "I found test command `{cmd}` in `{source}`. Is this correct?" (Yes / Correct the command) | "What test runner and test command will this project use?" |
| CI/CD system | "I detected **{ci_system}** (found `{config_file}`). Is this correct?" (Yes / No, it's {X}) | "What CI/CD system will this project use? (GitHub Actions, GitLab CI, none, etc.)" |

### Detection Sources

- **Language**: File extensions (`*.py`, `*.ts`, `*.js`, `*.go`, `*.rs`, `*.java`, `*.rb`), config files (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`)
- **Framework**: Import patterns, config files (`manage.py` = Django, `next.config.*` = Next.js, `astro.config.*` = Astro)
- **Package manager**: Lock files (`uv.lock`, `poetry.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`)
- **Test runner**: Config sections in `pyproject.toml` (`[tool.pytest]`), `package.json` (`scripts.test`), CI config test stages
- **CI/CD**: `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/`

### AskUserQuestion Format

For confirm mode, use single-select with two options:
```
(A) Yes, that's correct
(B) No — let me correct it
```
If user selects (B), follow up with a free-text AskUserQuestion for the correction.

For open-ended mode, use free-text AskUserQuestion. Do not offer multiple choice unless there is a small fixed set (e.g., package managers).

---

## Domain 2: Style

Covers naming conventions, formatting tools, type discipline, and documentation style.

### Questions

| Topic | Confirm Mode | Open-Ended Mode |
|---|---|---|
| Naming convention | "I see **{convention}** used throughout the codebase (e.g., `{example_name}`). Is this the standard?" (Yes / No) | "What naming convention should this project use?" with options: (A) snake_case (Python standard), (B) camelCase (JS/TS standard), (C) PascalCase, (D) Mixed — describe |
| Formatter / linter | "I detected **{tools}** (found `{config_file}`). Are these the project formatters/linters?" (Yes / No, it's {X}) | "What formatter and linter will this project use? (e.g., ruff, black, prettier, eslint, none)" |
| Type hints | "I see type hints **{present/absent}** in the codebase. Should Claude always use type hints?" (Yes / No) | "Should Claude use type hints on all function signatures?" (Yes / No) |
| Docstring style | "I detected **{style}** docstrings (e.g., in `{file}`). Is this the standard?" (Yes / No, it's {X}) | "What docstring style should this project use?" with options: (A) Numpy-style, (B) Google-style, (C) None / minimal |

### Detection Sources

- **Naming**: Grep for function/variable definitions, check snake_case vs camelCase prevalence
- **Formatter**: Config files (`.ruff.toml`, `ruff` section in `pyproject.toml`, `.prettierrc`, `.eslintrc`)
- **Type hints**: Sample function signatures from source files
- **Docstrings**: Sample docstrings, check for `Parameters`/`Args`/`Returns` patterns

---

## Domain 3: Methodology

Covers development workflow, branching, review, and commit practices. These are mostly asked (rarely auto-detectable).

### Questions

| Topic | Confirm Mode | Open-Ended Mode |
|---|---|---|
| TDD preference | "Does this project follow TDD (test-driven development)?" with options: (A) Yes, red-green-refactor, (B) Tests after implementation, (C) No formal test practice | Same as confirm mode — this is always asked |
| Branching strategy | "I see branches matching **{pattern}** (e.g., `feat/`, `fix/`). Is this the branching convention?" (Yes / No) | "What branching strategy will this project use?" with options: (A) Feature branches (feat/, fix/, etc.), (B) Trunk-based development, (C) Other — describe |
| PR/MR review | "How should Claude handle code review?" with options: (A) Always request review before merge, (B) Self-merge for small changes, (C) No formal review process | Same as confirm mode — this is always asked |
| Commit convention | "I see commit messages matching **{pattern}**. Is this the commit convention?" (Yes / No, it's {X}) | "What commit message convention should this project use?" with options: (A) Conventional Commits (feat:, fix:, etc.) (Recommended), (B) Free-form, (C) Other — describe |

### Detection Sources

- **Branching**: `git branch -a` output, branch naming patterns
- **Commits**: `git log --oneline -20`, check for conventional commit prefixes

---

## Domain 4: Guardrails

Covers file and directory protection. Uses stack-specific presets from `references/hook-presets.md`.

### Workflow

1. Read `references/hook-presets.md` to load the available presets for the detected stack.
2. Assemble a multiSelect list combining:
   - **General presets** (always included)
   - **Stack-specific presets** (based on detected or stated language from Domain 1)
3. Present via `AskUserQuestion` with `multiSelect`:

```
Which files and directories should Claude be prevented from editing?
Select all that apply (recommended defaults are pre-checked):

[ ] .env — Environment variables with secrets
[ ] uv.lock — Lock file (auto-generated, do not edit manually)
[ ] migrations/ — Database migrations (manual review required)
[ ] .git/ — Git internals (always protected)
[ ] *.key / *.pem — Cryptographic keys
[ ] .claude/settings.json — Claude config (prevent accidental overwrites)
...additional stack-specific options
```

4. For any selection, record the file patterns. These patterns will be passed to `/setup-hooks` in Phase 5 to create PreToolUse protection hooks.

### Confirm Mode vs. Open-Ended Mode

Both modes use the same multiSelect approach. The only difference:

- **Confirm mode**: Pre-check recommended defaults based on what exists in the repo (e.g., if `uv.lock` exists, pre-check it).
- **Open-ended mode**: Pre-check all "General" presets plus reasonable defaults for the stated stack.
