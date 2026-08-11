---
name: dignified-python
description: Production Python coding standards with automatic version detection (3.10-3.13). Use when writing,
  reviewing, or refactoring Python to ensure adherence to modern type syntax, LBYL exception
  handling, pathlib operations, ABC-based interfaces, and production-tested patterns. Not
  Dagster-specific - applies to any Python project.
---

# Dignified Python Coding Standards Skill

Production-quality Python coding standards for writing clean, maintainable, modern Python code
(versions 3.10-3.13). General Python standards, not Dagster-specific — use `/dagster-expert` for
Dagster patterns.

## When to Use This Skill

Auto-invoke when users ask about:

- "make this pythonic" / "is this good python" / "code review" / "improve this code"
- "type hints" / "type annotations" / "typing"
- "LBYL vs EAFP" / "exception handling"
- "pathlib vs os.path" / "path operations"
- "CLI patterns" / "click usage"
- Any Python code quality or standards question

## Core Knowledge (ALWAYS Loaded)

[dignified-python-core.md](dignified-python-core.md)

## Version Detection

**Identify the project's minimum Python version** by checking (in order):

1. `pyproject.toml` - Look for `requires-python` field (e.g., `requires-python = ">=3.12"`)
2. `setup.py` or `setup.cfg` - Look for `python_requires`
3. `.python-version` file - Contains version like `3.12` or `3.12.0`
4. Default to Python 3.12 if no version specifier found

**Once identified, load the appropriate version-specific file:** `versions/python-3.10.md`,
`versions/python-3.11.md`, `versions/python-3.12.md`, or `versions/python-3.13.md`.

## Reference Routing

Core knowledge covers 80%+ of Python code patterns. Load additional references only when the
task matches a trigger below. See `references/checklists.md` for the full reference file map
(core, version-specific, and advanced-topic files).

| Trigger                                                                                                             | Load                               |
| ------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| "click" or "CLI" mentioned                                                                                          | `cli-patterns.md`                  |
| "subprocess" mentioned                                                                                              | `subprocess.md`                    |
| Writing try/except, wrapping third-party APIs, seeing `from e`/`from None`, unsure if LBYL exists                   | `references/exception-handling.md` |
| Creating ABC/Protocol classes, `@abstractmethod`, gateway interfaces, choosing ABC vs Protocol                      | `references/interfaces.md`         |
| Using `typing.cast()`, `Literal` aliases, narrowing types in conditionals                                           | `references/typing-advanced.md`    |
| Creating modules, module-level code, `@cache` at module scope, `Path()`/computation at module level, inline imports | `references/module-design.md`      |
| Adding default parameters, functions with 5+ params, `ThreadPoolExecutor.submit()`, signature review                | `references/api-design.md`         |
| Final review before commit, unsure if all rules followed                                                            | `references/checklists.md`         |

## How to Use This Skill

1. **Core knowledge** is loaded automatically (LBYL, pathlib, basic imports, anti-patterns)
2. **Version detection** happens once - identify the minimum Python version and load the
   appropriate version file
3. **Reference documents** are loaded on-demand based on the triggers above
4. **Each file is self-contained** with complete guidance for its domain
