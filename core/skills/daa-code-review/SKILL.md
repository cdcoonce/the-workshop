---
name: daa-code-review
description: AI-powered code quality analysis for Python, Markdown, and Mermaid diagrams. Use when the user asks for a "code review" or "quality check"; when Python files need checking for PEP8 violations, unused code, missing type hints, docstring problems, complexity issues, or potential runtime errors; when Markdown documentation needs validation for broken links, heading structure, or formatting; when Mermaid diagram syntax needs validation; or when the user pastes code snippets for analysis.
---

# DAA Code Review Skill

Analyze Python code, Markdown documentation, and Mermaid diagrams for quality issues. Combines external linters (ruff) with Claude's analysis to provide comprehensive code review with suggested fixes.

Go beyond running linters: also check for SOLID/DRY/YAGNI conformance, obvious security issues spotted in passing, and descriptive variable naming. See [python-checks.md#naming](references/python-checks.md#naming) for a worked example.

**Role boundary:** this skill is the _quality_ review. For a dedicated vulnerability audit (injection, auth, crypto, OWASP categories), defer to the `security-review` skill — flag anything suspicious you notice here, then recommend running `/security-review` rather than deepening the security analysis inline.

## Quick Start

```python
from python_analyzer import analyze_python, analyze_python_file
from markdown_analyzer import analyze_markdown, analyze_markdown_file
from report_generator import generate_console_report, generate_markdown_report
from models import ReviewReport

result = analyze_python_file(Path("src/module.py"))  # or analyze_python(code_string)
result = analyze_markdown_file(Path("README.md"))  # or analyze_markdown(content)
report = ReviewReport(results=[result], title="Code Review")
generate_console_report(report)  # Console output
markdown = generate_markdown_report(report)  # Markdown string
```

For Mermaid diagrams, combine Claude's understanding with a web search for current syntax — see [mermaid-checks.md](references/mermaid-checks.md).

## Workflow

1. **Receive code** - From file path or pasted snippet
2. **Detect file type** - Python (.py), Markdown (.md), or Mermaid (.mmd, code blocks)
3. **Run analysis** - External linters first, then Claude's analysis
4. **Generate report** - Both console and markdown formats; see [fix-workflow.md](references/fix-workflow.md) for output format details
5. **Save report** - Write markdown report to `docs/code_reviews/{YYYY-MM-DD}_{file_name}.md` (create directory if needed)
6. **Review fixes** - Present suggested fixes to user
7. **Apply fixes** - With user approval; see [fix-workflow.md](references/fix-workflow.md) for approval modes and examples
8. **Check README** - Before pushing, verify README.md reflects current changes (new features, modified APIs, updated dependencies, changed configuration)

## Analysis Capabilities

| Language/Format | Categories                                                                              | Details                                             |
| --------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Python (ruff)   | PEP8, unused code, type hints, docstrings, complexity, runtime errors, imports          | [python-checks.md](references/python-checks.md)     |
| Markdown        | Heading structure, broken links, alt text, formatting, code blocks, encoding corruption | [markdown-checks.md](references/markdown-checks.md) |
| Mermaid         | Diagram type declaration, node/edge syntax, structural correctness                      | [mermaid-checks.md](references/mermaid-checks.md)   |

## Reference Documentation

- [python-checks.md](references/python-checks.md) - Python rule details and naming example
- [markdown-checks.md](references/markdown-checks.md) - Markdown rule details
- [mermaid-checks.md](references/mermaid-checks.md) - Mermaid validation guide
- [fix-workflow.md](references/fix-workflow.md) - Output formats, fix approval workflow, and usage pattern examples
- [authoring-conventions.md](references/authoring-conventions.md) - Conventions for modifying the analyzer scripts (script inventory, URI detection, frontmatter parsing)

## Requirements

Python 3.10+, ruff, and web access for Mermaid documentation lookup.
