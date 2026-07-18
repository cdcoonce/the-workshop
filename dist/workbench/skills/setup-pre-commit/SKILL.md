---
name: setup-pre-commit
description: Set up pre-commit hooks for the current repo. Use when user wants to add pre-commit hooks, configure commit-time linting, formatting, type checking, or testing. Triggers on "pre-commit", "git hooks", "linting hooks", or /setup-pre-commit.
---

# Setup Pre-Commit Hooks

## Prerequisites

Before proceeding, verify:

1. **Git repo exists** — check for `.git/` directory. If not found, inform the user and stop.
2. **Package manager available** — after detection (below), verify the relevant tool is installed:
   - Python: run `uv --version` to confirm `uv` is available
   - JS/TS: run `npx --version` to confirm `npx` is available

If prerequisites fail, inform the user what's missing and how to install it.

## Step 1: Detect Project Type

Check the project root for:

| Signal                                      | Result                                           |
| ------------------------------------------- | ------------------------------------------------ |
| `pyproject.toml` present, no `package.json` | **Python** → read `python-setup.md`              |
| `package.json` present, no `pyproject.toml` | **JS/TS** → read `js-setup.md`                   |
| Both present                                | **Ask user** (see below)                         |
| Neither present                             | Inform user: no supported project detected, stop |

### Both detected

Use AskUserQuestion to offer three options:

- **A) Python only** — follow `python-setup.md`
- **B) JS/TS only** — follow `js-setup.md`
- **C) Both** — follow `python-setup.md` including the "Both-Languages Mode" section

## Step 2: Ask User Which Checks to Enable

Delegate to the language-specific setup file. Each file presents available checks via AskUserQuestion.

**If the user selects no checks**: inform them that no hooks will be installed and exit gracefully.

## Step 3: Install Framework

Follow the language-specific setup file.

## Step 4: Generate Config

Follow the language-specific setup file to create config file(s) based on user selections.

## Step 5: Install Hooks

Follow the language-specific setup file to activate hooks in git.

## Step 6: Verify

Run hooks against the full codebase to confirm they work.

## Step 7: Handle Verification Failures

- If lint/format violations are found, auto-fix where possible (`ruff --fix`, `ruff format`, `prettier --write`) and re-run.
- If type or test failures occur, inform the user and proceed with committing the hook config files only.

## Step 8: Commit

Stage and commit all created/modified config files.
