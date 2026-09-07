# Worker Contract

Send the complete contract in the first worker message. Amend it explicitly when
scope changes; prior silence never grants authority.

```text
Task name: <human-readable unique name>

Objective
- <one independently verifiable outcome>

Repository and workspace Ownership
- Repository: <absolute path or saved-project identity>
- Workspace/worktree: <exact path or creation policy>
- Integration target: <remote and branch resolved from repository policy>
- Owned files/responsibility: <exclusive footprint>
- Dependencies: <worker names or milestones that gate this task>

Allowed mutations
- <files, branches, commits, issue/PR actions, or external systems explicitly allowed>

Explicit Prohibitions
- Do not mutate outside the owned footprint.
- Do not merge, deploy, touch live data, destroy/discard work, disclose externally,
  or create replacement workers unless each operation is explicitly authorized.
- Do not revert or overwrite concurrent user/worker changes; adapt around them.

Verification gates
- <targeted tests and full repository gates>
- <durable-output and git reachability checks>

Reporting protocol
- Send MILESTONE when durable progress changes.
- Send QUESTION with the exact decision and evidence; continue safe independent work.
- Send BLOCKED after safe alternatives are exhausted.
- Send COMPLETE only with the report below.

Integration obligations and sync
- <commit/push/PR/handoff obligations explicitly authorized>
- Rebase-before-push only when repository policy requires/allows it.
- Worktree completion is not integration; name the intended target and evidence.

Terminal conditions
- Success: <observable result and target reachability>
- Stop: <boundary, failed gate, owner decision, or capability gap>

COMPLETE report
- Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- Changes: <paths and concise behavior>
- Verification: <commands and exact results>
- Commits/durable outputs: <identifiers and locations>
- Integration: <target, current reachability, remaining action>
- Risks/questions: <none or explicit items>
```

The controller answers a question itself when repository instructions, the worker
contract, or an already-recorded owner decision yields one valid answer. It sends
the answer as a durable worker message and records the policy source. It escalates
when multiple valid choices remain or the question seeks new authority, money,
external disclosure, destructive action, live-data access, merge, or deployment.
