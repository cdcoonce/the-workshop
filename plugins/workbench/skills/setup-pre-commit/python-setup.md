# Python Pre-Commit Setup

## Available Checks

Present these options to the user via AskUserQuestion. Let them select which checks to enable:

- **ruff lint** — linting with autofix (`ruff check --fix`)
- **ruff format** — code formatting (`ruff format`)
- **mypy** — static type checking
- **pytest** — test suite

## Steps

### 1. Install pre-commit

```bash
uv add --dev pre-commit
```

### 2. Create `.pre-commit-config.yaml`

Generate the config based on the user's selected checks. Include only the hooks they chose.

Hooks are ordered fastest-first:

#### ruff (lint + format)

Use the official astral-sh repo hooks (maintained, versioned, no local dependency needed):

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.4 # Check latest version
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

Include `ruff` hook if user selected "ruff lint". Include `ruff-format` hook if user selected "ruff format".

#### mypy

Run as a `local` hook — needs access to project dependencies via the virtual environment:

```yaml
- repo: local
  hooks:
    - id: mypy
      name: mypy
      entry: uv run mypy src/
      language: system
      types: [python]
      pass_filenames: false
      args: [--ignore-missing-imports]
```

**Adapt**: Detect the source directory from `pyproject.toml` (look for `[tool.setuptools.packages.find]`, `[tool.hatch]`, or `packages` config). Fall back to `src/` if not found.

#### pytest

Run as a `local` hook — needs access to project dependencies:

```yaml
- repo: local
  hooks:
    - id: pytest
      name: pytest
      entry: uv run pytest
      language: system
      types: [python]
      pass_filenames: false
```

### 3. Install hooks

```bash
uv run pre-commit install
```

### 4. Verify

```bash
uv run pre-commit run --all-files
```

### 5. Commit

Stage and commit with message: `Add pre-commit hooks (pre-commit framework)`

## Both-Languages Mode

When the user selected "both" in the detection step, also add JS tools as `local` hooks in the same `.pre-commit-config.yaml`. This avoids the `.git/hooks/pre-commit` ownership conflict between the `pre-commit` framework and Husky.

### Install JS dependencies first

```bash
npm install --save-dev prettier
```

If ESLint config exists in the project, also:

```bash
npm install --save-dev eslint
```

### Add JS hooks to config

Append after the Python hooks:

#### Prettier

```yaml
- repo: local
  hooks:
    - id: prettier
      name: prettier
      entry: npx prettier --ignore-unknown --write
      language: system
      types_or: [javascript, jsx, ts, tsx, css, json, markdown, yaml]
```

#### ESLint (only if config exists)

```yaml
- repo: local
  hooks:
    - id: eslint
      name: eslint
      entry: npx eslint --fix
      language: system
      types_or: [javascript, jsx, ts, tsx]
```

### Combined hook order (fastest-first)

1. ruff check (Python lint)
2. ruff format (Python format)
3. prettier (JS format)
4. eslint (JS lint)
5. mypy (Python type check)
6. pytest (Python tests)
