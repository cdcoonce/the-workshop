# Engineering Design and Security

## Tie-breaker: YAGNI wins over SOLID

SOLID and YAGNI pull in opposite directions, and enforcing both without a rule produces contradictory findings. Flag a SOLID violation only when it costs something today: it makes the changed code hard to test, forces the same edit in several places, or has already needed a second implementation. "This could be more extensible" is not a finding. Speculative abstraction that adds code a reader must understand for no current benefit is Major.

## When to flag

| Principle             | Flag when                                                                                                                                                                        | Do not flag when                                                                                                                |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Single responsibility | One function or class mixes I/O (Snowflake calls, file reads), business rules and formatting, so none can be tested alone                                                        | A short function does one job in several steps                                                                                  |
| Open/closed           | A conditional keyed on type or name is extended again and every extension edits the same chain                                                                                   | A two-branch `if` that has never grown                                                                                          |
| Liskov substitution   | A subclass narrows inputs, changes return types, or raises `NotImplementedError` for inherited methods                                                                           | Subclasses that only add behavior                                                                                               |
| Interface segregation | Callers must depend on or mock a large interface to use one method                                                                                                               | Small, cohesive interfaces                                                                                                      |
| Dependency inversion  | Business logic builds its own Snowflake connection, HTTP client or clock, so tests need the real thing; pass it in as a parameter or resource                                    | Thin scripts with one entry point and no tests to enable                                                                        |
| DRY                   | The same business rule, SQL logic, schema or constant lives in two or more places and a change must be made twice                                                                | Two blocks that look alike but change for different reasons; extract at three real occurrences or two that must change together |
| YAGNI                 | Unused parameters or flags, config no caller sets, base classes or registries with one implementation, dead code paths, a new dependency for something the standard library does | Code required by the change's stated scope                                                                                      |

A file full of single-use helpers is harder to read than the straightforward code it replaces. Prefer inline code unless a helper is reused or clearly improves readability.

## Security checklist

Check each item against the diff, not the whole repository. This is the diff-scoped pass every review runs, including `--quality-only`; a deep audit (auth flows, crypto, OWASP) is still `security-review`.

- **Secrets:** none in code, tests, notebooks, Dockerfiles, CI files or logs; configuration comes from the environment or a secret manager. A plausible real credential is a Blocker whatever severity the tool gave it. Reporting rule: [review-process.md](review-process.md).
- **Injection:** SQL built with f-strings, `%`, `.format` or concatenation from any non-constant value (use bind parameters; for dynamic Snowflake object names use `IDENTIFIER()`); `subprocess` with `shell=True` and variable input; `eval`, `exec`, `pickle.load` or `yaml.load` on untrusted input; unescaped HTML (`unsafe_allow_html` in Streamlit).
- **Authentication and authorization:** checks enforced server-side, not only hidden in the UI; new endpoints and pages authenticated by default.
- **Data exposure:** PII or secrets in logs, error messages, URLs or error-monitoring payloads (Sentry: `send_default_pii=False`, scrub before capture); responses return only fields the caller may see.
- **Transport:** TLS verification is never disabled (`verify=False`, unverified SSL contexts).
- **Dependencies:** new or changed packages are pinned, the lockfile change is committed, the source is the official index, the package is maintained and its license is acceptable. When versions change, ask for a vulnerability audit.
- **CI/CD:** changes to `.gitlab-ci.yml` that print variables, add `allow_failure: true` to security jobs, hardcode secrets or weaken branch rules.
- **Errors:** users never see stack traces or internal details; no `except: pass` that hides failures.
- **Least privilege:** credentials and roles are scoped to what the code uses.

### bandit triage

- HIGH severity with MEDIUM or HIGH confidence is a Blocker; MEDIUM severity is Major; LOW is Minor. `branch_checks.py` already applies this mapping.
- B105, B106, B107 (and ruff S105 to S107) arrive as Major with the value redacted. Read the line: a plausible real credential is a Blocker; a placeholder or test fixture is dropped or Minor.
- An import-only finding such as B404 is not worth reporting unless a risky call (B602, B603, B605) accompanies it.
- B608 (SQL built from strings) is heuristic: confirm a non-constant value reaches the query before reporting.

## Stack conventions

- **Dagster:** Snowflake and other connections come from resources, not constructed inside asset bodies; secrets from environment variables; assets are safe to re-run. Deeper asset, sensor and schedule questions go to `dagster-expert`.
- **Streamlit:** no SQL inside layout code; data loaders cached deliberately (`st.cache_data`); session state is not a dumping ground.
- **Hex:** no business logic in display cells; parameterized queries only.
- **Sentry:** initialized once at startup with PII off.
- **Python tooling:** `uv` for packages (not pip), Ruff for lint and format, type hints on public functions.
