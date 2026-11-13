# Python Quality Checks Reference

This document details the Python code quality checks performed by the daa-code-review skill. The coding standard is `dignified-python`; judge changed hunks against it. Run the deterministic pass with the command in SKILL.md ("Analyzer CLI"): an absolute `<skill_dir>` path under `uv run --with ruff` (exit 3 means ruff is missing; say so, never report clean).

## Category Overview

| Category       | Examples                                  | Severity     |
| -------------- | ----------------------------------------- | ------------ |
| PEP8           | Line length, indentation, whitespace      | WARNING/INFO |
| Unused Code    | Unused imports, variables, arguments      | WARNING      |
| Type Hints     | Missing annotations on functions          | INFO         |
| Docstrings     | Missing/malformed numpy-style docstrings  | INFO         |
| Complexity     | Functions with high cyclomatic complexity | INFO         |
| Runtime Errors | Undefined names, syntax errors            | ERROR        |
| Imports        | Unsorted imports, banned imports          | INFO         |
| Security (S)   | Bandit routine calls (S1xx)               | WARNING      |

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

The repo's own ruff config wins (`ruff.toml`, `.ruff.toml`, or `[tool.ruff]` in `pyproject.toml`). With no config, ruff's defaults plus `B` (bugbear) and `S` (bandit) run. Bandit (`S`) findings are WARNING (should-fix): they are hints for the quality pass, and real vulnerability calls belong to `security-review`. `assert` (S101) in test files is INFO (nit). A test file is one whose basename matches `test_*.py`, `*_test.py` or `conftest.py`, or one under a `tests/` directory (`is_test_file` in `scripts/python_analyzer.py`).

## External Tools

The skill uses **ruff** as the primary linter. Ruff is a fast Python linter that implements rules from multiple tools including pycodestyle, pyflakes, isort, pydocstyle, and more.

## Check Categories

### PEP8 Style (Category: `pep8`)

Style violations from pycodestyle rules.

| Rule      | Description        | Severity |
| --------- | ------------------ | -------- |
| E1xx      | Indentation errors | WARNING  |
| E2xx      | Whitespace errors  | WARNING  |
| E3xx      | Blank line errors  | WARNING  |
| E4xx      | Import errors      | WARNING  |
| E5xx      | Line length (E501) | WARNING  |
| E7xx      | Statement errors   | WARNING  |
| W1xx-W6xx | Warnings           | INFO     |

### Unused Code (Category: `unused_code`)

Dead code detection from Pyflakes.

| Rule          | Description                 | Severity |
| ------------- | --------------------------- | -------- |
| F401          | Unused import               | WARNING  |
| F841          | Unused variable             | WARNING  |
| F811          | Redefinition of unused name | WARNING  |
| ARG001-ARG005 | Unused arguments            | WARNING  |
| ERA001        | Commented-out code          | WARNING  |

### Type Hints (Category: `type_hint`)

Missing or incorrect type annotations.

| Rule   | Description                                         | Severity |
| ------ | --------------------------------------------------- | -------- |
| ANN001 | Missing type annotation for function argument       | INFO     |
| ANN002 | Missing type annotation for \*args                  | INFO     |
| ANN003 | Missing type annotation for \*\*kwargs              | INFO     |
| ANN201 | Missing return type annotation for public function  | INFO     |
| ANN202 | Missing return type annotation for private function | INFO     |
| ANN204 | Missing return type annotation for **init**         | INFO     |

### Docstrings (Category: `docstring`)

Documentation quality from pydocstyle.

| Rule      | Description                          | Severity |
| --------- | ------------------------------------ | -------- |
| D100      | Missing docstring in public module   | INFO     |
| D101      | Missing docstring in public class    | INFO     |
| D102      | Missing docstring in public method   | INFO     |
| D103      | Missing docstring in public function | INFO     |
| D200-D215 | Docstring formatting rules           | INFO     |
| D400-D419 | Docstring content rules              | INFO     |

### Complexity (Category: `complexity`)

Cyclomatic complexity checks from mccabe.

| Rule    | Description                              | Severity |
| ------- | ---------------------------------------- | -------- |
| C901    | Function is too complex (>10 by default) | INFO     |
| PERF1xx | Performance anti-patterns                | INFO     |

### Runtime Errors (Category: `runtime_error`)

Potential bugs and runtime issues.

| Rule | Description                                 | Severity |
| ---- | ------------------------------------------- | -------- |
| F821 | Undefined name                              | ERROR    |
| F823 | Local variable referenced before assignment | ERROR    |
| E999 | Syntax error                                | ERROR    |
| B006 | Mutable default argument                    | WARNING  |
| B007 | Loop control variable not used              | WARNING  |
| B008 | Function call in default argument           | WARNING  |
| F822 | Undefined name in `__all__`                 | ERROR    |
| B018 | Useless expression                          | ERROR    |

### Imports (Category: `import`)

Import organization and style.

| Rule   | Description                 | Severity |
| ------ | --------------------------- | -------- |
| I001   | Import block unsorted       | INFO     |
| I002   | Missing required import     | INFO     |
| TID251 | Banned import               | WARNING  |
| ICN001 | Unconventional import alias | INFO     |

## Severity Mapping

Source of truth: `RUFF_SEVERITY_MAP` and `ERROR_RULES` in `scripts/python_analyzer.py`.

| Prefix | Severity |
| ------ | -------- |
| E      | WARNING  |
| W      | INFO     |
| F      | WARNING  |
| C90    | INFO     |
| I      | INFO     |
| N      | INFO     |
| D      | INFO     |
| ANN    | INFO     |
| B      | WARNING  |
| S      | WARNING  |

- **ERROR** (blocking): only F821, F822, F823, E999 and B018.
- **WARNING** (should-fix): the prefixes above, unknown rules, and every bandit `S` finding (S1xx included). Security vulnerabilities are not ERROR here; real ones belong to `security-review`.
- **INFO** (nit): the prefixes above, and S101 in test files.

## Auto-Fixable Issues

Many issues can be automatically fixed by ruff. The skill identifies these and provides fix suggestions when available. Common auto-fixable issues include:

- Unused imports (F401)
- Import sorting (I001)
- Trailing whitespace (W291, W293)
- Missing trailing newline (W292)
- Blank line issues (E302, E303)
- Quote style (Q000-Q003)
