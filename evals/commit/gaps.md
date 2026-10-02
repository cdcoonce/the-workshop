# Gaps

Guarded behaviors that cannot be exercised as a single-prompt case, one line of reason each.
- never amend an existing commit (the "new commits only" rule): this fixture gives the case-agent no commit of its own to amend and no reason to, so a single prompt cannot tempt it
- never skip hooks with --no-verify: the fixture installs no git hook, so there is no hook failure for the agent to be tempted to bypass
- no generated artifacts in a commit: the fixture's only untracked non-secret files are ignored by its gitignore, so nothing generated is on offer to stage
- imperative mood and a summary that gives the why: judging either needs a human reader, so the subject gate scores only the mechanical format
- warning the user when a secret is staged: scoring it needs the agent's final reply read as prose, and this case takes no findings envelope
- body and trailer layout of a multi-line message: the gates read only the subject and the attribution lines, not how a longer body is formatted
