# vault-ops

Charles Coonce's vault (The Vault) lifecycle, graph, capture, search, sync, and writing workflows

## Conventions

- Frontmatter on every note
- Wikilinks over bare references
- Rebase-before-push git sync, refreshed handoff

## Skills

| Skill | Summary |
| --- | --- |
| `/vault-audit` | Run Charles's vault (The Vault) /vault-audit structural audit across frontmatter, wikilinks, indexes, stale notes, duplicates, and templates. |
| `/vault-budget` | Run Charles's vault (The Vault) /budget spend and subscription-value meter from local Claude transcripts. |
| `/vault-clickup-task-sync` | Run Charles's vault (The Vault) /clickup-task-sync workflow to sync vault action items into ClickUp without duplicating tasks. |
| `/vault-connect` | Run Charles's vault (The Vault) /connect autonomous graph connection pass with preview-gated wikilink edits. |
| `/vault-context-then-delegate` | Run Charles's vault (The Vault) /context-then-delegate workflow to resolve real-world ambiguity (email/SharePoint/Slack) before writing a coding-agent prompt. |
| `/vault-dispatch` | Run Charles's vault (The Vault) /dispatch workflow to turn a shaped idea into an afk-managed issue linked back into the vault. |
| `/vault-dump` | Run Charles's vault (The Vault) /dump capture workflow for routing freeform input into durable vault notes, tasks, indexes, and wikilinks. |
| `/vault-essay` | Draft long-form prose (essays and posts) in Charles's voice using The Vault's /essay writing rules. |
| `/vault-find` | Run Charles's vault (The Vault) /find semantic vault search workflow, including reindex and status modes. |
| `/vault-fix-issue` | Run Charles's vault (The Vault) /fix-issue workflow to resolve a filed issue under TDD + mutation-teeth-check + review-before-commit discipline. |
| `/vault-garden` | Run Charles's vault (The Vault) /garden graph-gardener apply workflow for queued link, profile, memory, index, and orphan repairs. |
| `/vault-grill` | Run Charles's vault (The Vault) /grill active knowledge-extraction interview and route the result into the vault graph. |
| `/vault-handoff` | Run Charles's vault (The Vault) /handoff workflow to refresh the machine-scoped rolling handoff digest. |
| `/vault-link` | Run Charles's vault (The Vault) /link helper to find notes and suggest or insert correct Obsidian wikilinks. |
| `/vault-mr-review-packet` | Run Charles's vault (The Vault) /mr-review-packet workflow to generate a self-guided reviewer packet for a large merge request. |
| `/vault-recall` | Run Charles's vault (The Vault) /recall post-build consolidation workflow for afk merge outcomes, stubs, brag candidates, and handoff refresh. |
| `/vault-standup` | Run Charles's vault (The Vault) /standup context-loading workflow, including lean, deep, and comprehensive modes. |
| `/vault-sync` | Run Charles's vault (The Vault) /sync git synchronization workflow with rebase-before-push and conflict-safe handling. |
| `/vault-teach` | Run Charles's vault (The Vault) /teach stateful learning workspace workflow for a topic. |
| `/vault-wrap-up` | Run Charles's vault (The Vault) /wrap-up session audit, handoff refresh, and git sync workflow. |
| `/vault-write` | Draft Outlook or Teams messages in Charles's voice using The Vault's /write communication rules. |

## CLAUDE.md Template

Copy the following into your project's `CLAUDE.md` to reference this plugin:

```
# Project Name

## Plugins

This project uses the vault-ops plugin for Claude Code configuration.

## Methodology

See plugin documentation for TDD, root cause tracing, and subagent development processes.
```
