# Security Review Report Template

Use this format when writing security review reports to `docs/security-reviews/YYYY-MM-DD-<component>.md`.

```markdown
## Security Review: [File/Component Name]

### Summary
- **Findings**: X (Y Critical, Z High, ...)
- **Risk Level**: Critical/High/Medium/Low
- **Confidence**: High/Mixed

### Findings

#### [VULN-001] [Vulnerability Type] (Severity)
- **Location**: `file.py:123`
- **Confidence**: High
- **Issue**: [What the vulnerability is]
- **Impact**: [What an attacker could do]
- **Evidence**:
  ```python
  [Vulnerable code snippet]
  ```
- **Fix**: [How to remediate]

### Needs Verification

#### [VERIFY-001] [Potential Issue]
- **Location**: `file.py:456`
- **Question**: [What needs to be verified]
```

## Rules

- Number findings sequentially: VULN-001, VULN-002, etc.
- Number verification items separately: VERIFY-001, VERIFY-002, etc.
- Include code evidence for every finding
- HIGH confidence findings go in **Findings** section
- MEDIUM confidence findings go in **Needs Verification** section
- LOW confidence findings are not reported
- If no vulnerabilities found, state: "No high-confidence vulnerabilities identified."
