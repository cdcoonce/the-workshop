---
name: setup-hooks
description: >
  Set up Claude Code hooks for the current project. Use when user wants to add
  custom hooks, create PreToolUse or PostToolUse handlers, automate tool-triggered
  actions, or mentions "hooks", "hook setup", or /setup-hooks.
---

# Setup Claude Code Hooks

Scaffold a Claude Code hook through a guided interview. Collects event type, tool matcher, and desired behavior, then hands off to script generation.

Read [hook-protocol.md](references/hook-protocol.md) before proceeding. It defines the stdin JSON schema, exit code semantics, matcher syntax, and annotated examples you will need to generate correct hooks.

## Prerequisites

Before proceeding, verify:

1. **`.claude/` directory exists** — check for a `.claude/` directory in the project root. If not found, inform the user and stop.
2. **Python available** — run `python3 --version` (or `python --version` on Windows) to confirm Python is installed. Hooks are Python scripts.

If prerequisites fail, inform the user what is missing and how to fix it.

## Step 1: Event Type

Use `AskUserQuestion` to ask which hook event type the user needs. Provide these options:

- **PreToolUse (Recommended)** — Runs BEFORE a tool executes. Can BLOCK the operation by exiting non-zero. Use for: file protection, input validation, policy enforcement, preventing edits to specific files or patterns.
- **PostToolUse** — Runs AFTER a tool executes. Cannot block. Use for: auto-formatting, linting, logging, notifications, running fixers on modified files.

If the user is unsure, recommend PreToolUse — it covers the most common use case (protecting files from unwanted changes).

Record the selection for use in later phases.

## Step 2: Matcher Pattern

Use `AskUserQuestion` to ask which tools should trigger this hook. Offer these preset options:

- **Edit|Write (Recommended)** — Triggers on file modification tools. Most common choice for both protection and formatting hooks.
- **Bash** — Triggers on shell command execution. Use for command validation or post-command cleanup.
- **Read** — Triggers on file reading. Use for access logging or sensitive file detection.
- **Other** — Custom matcher pattern. Ask the user to type a pipe-separated tool list (e.g., `Edit|Write|Read`).

If the user selects "Other", follow up with a free-text `AskUserQuestion` asking them to provide their custom matcher pattern.

Record the matcher pattern for use in later phases.

## Step 3: Behavior Description

Use `AskUserQuestion` to ask the user to describe what the hook should do. This is a free-text question — do not offer multiple choice options.

Prompt: "Describe the behavior you want this hook to perform. Be specific about what conditions should trigger action and what the action should be. For example: 'Block edits to any file in the migrations/ directory' or 'Run black formatter on Python files after they are edited'."

Record the behavior description for use in later phases.

## Summary

After collecting all three answers, present a summary to the user:

- **Event type**: PreToolUse or PostToolUse
- **Matcher**: the selected tool pattern
- **Behavior**: the user's description

Confirm the user is satisfied before proceeding to the next phase.

<!-- Phase 2: Script generation and config wiring -->
