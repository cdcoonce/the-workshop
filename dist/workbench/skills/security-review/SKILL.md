---
name: security-review
description: >
  Security code review for vulnerabilities with confidence-based reporting.
  Use when the user asks for "security review", "find vulnerabilities", "check
  for security issues", "audit security", "OWASP review", or to review code
  for injection, XSS, authentication, authorization, or cryptography issues.
---

<!-- Reference content based on OWASP Cheat Sheet Series (CC BY-SA 4.0) https://cheatsheetseries.owasp.org/ -->

# Security Review

Run `/security-review` on target files. Report saved to `docs/security-reviews/YYYY-MM-DD-<component>.md`. Create the directory if it does not exist.

## Core Principle

Identify **exploitable** security vulnerabilities. Report only findings where you have confirmed the vulnerable pattern AND the input source. Research the entire codebase for context; report only on the code provided.

## Confidence Levels

| Level      | Criteria                                       | Action                             |
| ---------- | ---------------------------------------------- | ---------------------------------- |
| **HIGH**   | Vulnerable pattern + attacker-controlled input | **Report** with severity           |
| **MEDIUM** | Vulnerable pattern, input source unclear       | **Report** as "Needs verification" |
| **LOW**    | Theoretical, best practice, defense-in-depth   | **Do not report**                  |

## Do Not Flag

- Test files, dead code, documentation strings
- Patterns using **constants** or **server-controlled configuration** (Django settings, env vars, config files, hardcoded values)
- Framework-mitigated patterns (Django `{{ var }}` auto-escaping, ORM parameterized queries, React `{var}` escaping) — only flag when explicitly bypassed (`mark_safe`, `dangerouslySetInnerHTML`, `.raw()` with interpolation)

## Review Process

1. **Detect context** — identify code type, load relevant references from the table below
2. **Load language/infra guide** — if Python, Docker, or GitHub Actions code is present
3. **Research before flagging** — trace data flow, check for upstream validation, verify input source
4. **Verify exploitability** — confirm input is attacker-controlled, not server-controlled

## Context Detection

| Code Type                        | Load These References                                   |
| -------------------------------- | ------------------------------------------------------- |
| API endpoints, routes            | `authorization.md`, `authentication.md`, `injection.md` |
| Frontend, templates              | `xss.md`, `csrf.md`                                     |
| File handling, uploads           | `file-security.md`                                      |
| Crypto, secrets, tokens          | `cryptography.md`, `data-protection.md`                 |
| Data serialization               | `deserialization.md`                                    |
| External requests                | `ssrf.md`                                               |
| Business workflows               | `business-logic.md`                                     |
| GraphQL, REST design             | `api-security.md`                                       |
| Config, headers, CORS            | `misconfiguration.md`                                   |
| CI/CD, dependencies              | `supply-chain.md`                                       |
| Error handling                   | `error-handling.md`                                     |
| Audit, logging                   | `logging.md`                                            |
| Modern patterns (SSE, WebSocket) | `modern-threats.md`                                     |
| `.py`, Django, Flask, FastAPI    | `python.md`                                             |
| Dockerfile, docker-compose       | `docker.md`                                             |
| `.github/workflows`, CI config   | `github-actions.md`                                     |

## Severity Classification

| Severity     | Examples                                                             |
| ------------ | -------------------------------------------------------------------- |
| **Critical** | RCE, SQL injection to data exfil, auth bypass, hardcoded secrets     |
| **High**     | Stored XSS, SSRF to metadata, IDOR to sensitive data                 |
| **Medium**   | Reflected XSS, CSRF on state-changing actions, path traversal        |
| **Low**      | Missing headers, verbose errors, weak algorithms in non-critical use |

## Output

Write report to `docs/security-reviews/YYYY-MM-DD-<component>.md` using the format in `references/report-template.md`. If no vulnerabilities found, state: "No high-confidence vulnerabilities identified."
