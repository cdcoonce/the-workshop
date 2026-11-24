# Python Quality Checks Reference

This document details the Python code quality checks performed by the daa-code-review skill. The coding standard is `dignified-python`; judge changed hunks against it. Run the deterministic pass with the `branch_checks.py` command in SKILL.md's "Standards pass" section, using an absolute `<skill_dir>` path. A check whose status is `not_run` or `error` is a gap: say so, never report a pass.

## Category Overview

| Category       | Examples                                  | Severity  |
| -------------- | ----------------------------------------- | --------- |
| PEP8           | Line length, indentation, whitespace      | Minor/Nit |
| Unused Code    | Unused imports, variables, arguments      | Minor     |
| Type Hints     | Missing annotations on functions          | Nit       |
| Docstrings     | Missing/malformed numpy-style docstrings  | Nit       |
| Complexity     | Functions with high cyclomatic complexity | Nit       |
| Runtime Errors | Undefined names, syntax errors            | Blocker   |
| Imports        | Unsorted imports, banned imports          | Nit       |
| Security (S)   | Bandit routine calls (S1xx)               | Minor     |

## Naming

Beyond linter categories above, flag non-descriptive variable names. Don't do this:

```python
pkb = p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
```

Instead do this:

```python
private_key_bytes = p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
```

## Ruff Configuration

The repo's own ruff config wins (`ruff.toml`, `.ruff.toml`, or `[tool.ruff]` in `pyproject.toml`). With no config, ruff's defaults plus `B` (bugbear) and `S` (bandit) run. Ruff's bandit (`S`) findings are Minor, except S105 to S107 (hardcoded credential), which are Major with the value redacted and are triaged by reading ([engineering-design.md](engineering-design.md#bandit-triage)). `assert` (S101) in test files is a Nit. A test file is one whose basename matches `test_*.py`, `*_test.py` or `conftest.py`, or one under a `tests/` directory (`is_test_file` in `scripts/python_analyzer.py`).

## External Tools

The skill uses **ruff** as the primary linter. Ruff is a fast Python linter that implements rules from multiple tools including pycodestyle, pyflakes, isort, pydocstyle, and more.

## Check Categories

### PEP8 Style (Category: `pep8`)

Style violations from pycodestyle rules.

| Rule      | Description        | Severity |
| --------- | ------------------ | -------- |
| E1xx      | Indentation errors | Minor    |
| E2xx      | Whitespace errors  | Minor    |
| E3xx      | Blank line errors  | Minor    |
| E4xx      | Import errors      | Minor    |
| E5xx      | Line length (E501) | Minor    |
| E7xx      | Statement errors   | Minor    |
| W1xx-W6xx | Warnings           | Nit      |

### Unused Code (Category: `unused_code`)

Dead code detection from Pyflakes.

| Rule          | Description                 | Severity |
| ------------- | --------------------------- | -------- |
| F401          | Unused import               | Minor    |
| F841          | Unused variable             | Minor    |
| F811          | Redefinition of unused name | Minor    |
| ARG001-ARG005 | Unused arguments            | Minor    |
| ERA001        | Commented-out code          | Minor    |

### Type Hints (Category: `type_hint`)

Missing or incorrect type annotations.

| Rule   | Description                                         | Severity |
| ------ | --------------------------------------------------- | -------- |
| ANN001 | Missing type annotation for function argument       | Nit      |
| ANN002 | Missing type annotation for \*args                  | Nit      |
| ANN003 | Missing type annotation for \*\*kwargs              | Nit      |
| ANN201 | Missing return type annotation for public function  | Nit      |
| ANN202 | Missing return type annotation for private function | Nit      |
| ANN204 | Missing return type annotation for **init**         | Nit      |

### Docstrings (Category: `docstring`)

Documentation quality from pydocstyle.

| Rule      | Description                          | Severity |
| --------- | ------------------------------------ | -------- |
| D100      | Missing docstring in public module   | Nit      |
| D101      | Missing docstring in public class    | Nit      |
| D102      | Missing docstring in public method   | Nit      |
| D103      | Missing docstring in public function | Nit      |
| D200-D215 | Docstring formatting rules           | Nit      |
| D400-D419 | Docstring content rules              | Nit      |

### Complexity (Category: `complexity`)

Cyclomatic complexity checks from mccabe.

| Rule    | Description                              | Severity |
| ------- | ---------------------------------------- | -------- |
| C901    | Function is too complex (>10 by default) | Nit      |
| PERF1xx | Performance anti-patterns                | Nit      |

### Runtime Errors (Category: `runtime_error`)

Potential bugs and runtime issues.

| Rule | Description                                 | Severity |
| ---- | ------------------------------------------- | -------- |
| F821 | Undefined name                              | Blocker  |
| F823 | Local variable referenced before assignment | Blocker  |
| E999 | Syntax error                                | Blocker  |
| B006 | Mutable default argument                    | Minor    |
| B007 | Loop control variable not used              | Minor    |
| B008 | Function call in default argument           | Minor    |
| F822 | Undefined name in `__all__`                 | Blocker  |
| B018 | Useless expression                          | Blocker  |

### Imports (Category: `import`)

Import organization and style.

| Rule   | Description                 | Severity |
| ------ | --------------------------- | -------- |
| I001   | Import block unsorted       | Nit      |
| I002   | Missing required import     | Nit      |
| TID251 | Banned import               | Minor    |
| ICN001 | Unconventional import alias | Nit      |

## Severity Mapping

Source of truth: `RUFF_SEVERITY_MAP` and `ERROR_RULES` in `scripts/python_analyzer.py`.

| Prefix | Severity |
| ------ | -------- |
| E      | Minor    |
| W      | Nit      |
| F      | Minor    |
| C90    | Nit      |
| I      | Nit      |
| N      | Nit      |
| D      | Nit      |
| ANN    | Nit      |
| B      | Minor    |
| S      | Minor    |

- **Blocker:** only F821, F822, F823, E999 and B018: the code does not run as written.
- **Major:** S105, S106 and S107, pending triage.
- **Minor:** the prefixes above, unknown rules, and every other bandit `S` finding.
- **Nit:** the prefixes above, and S101 in test files.

## Other Python checks in `branch_checks.py`

| Check              | What it reports                                                                     | Severity                                             |
| ------------------ | ----------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `ruff-format`      | A format difference on changed lines; one finding for the whole change              | Minor                                                |
| `docstring-layout` | Ruff `D` rules, numpy convention, non-test files                                    | Minor                                                |
| `pydoclint`        | Missing or extra parameters, returns and raises (type-hint style codes are dropped) | Minor                                                |
| `bandit`           | Security patterns, secret values redacted                                           | [bandit triage](engineering-design.md#bandit-triage) |
| `pytest`, `mypy`   | Failing test ids and type errors; only with `--run-project-tools`                   | Blocker unless it already fails on the target branch |

A format difference that touches only unchanged lines is a pass with reason "pre-existing". What the docstring tools cannot judge is in [docs-freshness.md](docs-freshness.md).

## Auto-Fixable Issues

Many issues can be automatically fixed by ruff. The skill identifies these and provides fix suggestions when available. Common auto-fixable issues include:

- Unused imports (F401)
- Import sorting (I001)
- Trailing whitespace (W291, W293)
- Missing trailing newline (W292)
- Blank line issues (E302, E303)
- Quote style (Q000-Q003)
