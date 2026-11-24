# Documentation Freshness

A document is stale when it describes behavior the diff just changed. Staleness is a finding here; fixing it is `repo-docs`' job, so report and hand off, and edit docs only through the fix workflow when the user approves.

## README and docs

1. List what the diff renames, removes or changes: functions, classes, CLI flags, environment variables, config keys, table, column and model names, file paths, commands.
2. Run `git grep -n "<identifier>"` over `README*.md`, `docs/`, docstrings, `.env.example`, config templates and CI files. Each hit that no longer matches the code is a finding with file and line. Documentation that now misleads is Major.
3. README setup, run, test and lint commands still work as written: flags and paths exist, and Python tooling uses `uv`, not pip. Required environment variables are listed by name only, never value. The limitations section is still true.
4. New user-facing behavior, a new setup step or a new dependency with no documentation change is Major. A new package or service with no README is Major.

These findings land on files the diff did not touch. That is the one exception to "findings only on changed hunks": the cause is in the diff.

## Docstrings (numpy style)

- Public modules, classes, functions and methods have docstrings. Private helpers need one only when the intent is not obvious.
- Layout: a one-line imperative summary ending with a period, a blank line, an optional extended description, then sections in numpydoc order: Parameters, Returns (or Yields), Raises, See Also, Notes, Examples. Each section title is underlined with dashes of the same length.
- Parameters are written `name : type` (add `, optional` where a default exists), in signature order, and agree with the annotations.
- Staleness is the main defect: the docstring promises a return value, exception or parameter the code no longer has. Compare every docstring in a changed function with its body. Ruff's `D` rules check layout only and pydoclint catches parameter and section mismatches, but neither knows whether the described behavior is still true, so read them.
- pydoclint and mypy point at the `def` line, so a finding with `on_changed_line: false` can still belong to a function the diff changed. Check before dropping it.

```python
def load_rows(frame, table, *, chunk_size=10_000):
    """Load a DataFrame into a Snowflake table.

    Parameters
    ----------
    frame : pandas.DataFrame
        Rows to load.
    table : str
        Fully qualified target table name.
    chunk_size : int, optional
        Rows per upload chunk. Default is 10000.

    Returns
    -------
    int
        Number of rows loaded.

    Raises
    ------
    ValueError
        If ``frame`` is empty.
    """
```

## Diagrams

Syntax and rendering checks are in [mermaid-checks.md](mermaid-checks.md). Freshness is judged here: every node and edge corresponds to something that exists after the change, and the diff's structural changes (new service, table, pipeline step, renamed module) appear in the diagram. A stale architecture or data-flow diagram is Major.

## Style the linters miss

- The repo's own Ruff and SQLFluff configuration decides the rules. Report tool findings, not personal preferences.
- Do not comment on what the formatter fixes automatically. One Minor finding for a failing format check covers the whole change.
- Also check: naming (snake_case functions and variables, PascalCase classes; worked example in [python-checks.md#naming](python-checks.md#naming)), commented-out code, unexplained magic numbers.
