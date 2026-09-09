# Worker Contract

Send the complete contract in the first worker message. Amend it explicitly when
scope changes; prior silence never grants authority.

```text
Task name: <human-readable unique name>

Objective
- <one independently verifiable outcome>

Repository and workspace Ownership
- Origin project: <existing Vault project/task identity; user-visible worker owner>
- Target repository: <absolute path or saved-project identity; separate from origin project>
- Workspace/worktree: <exact isolated path or creation policy; must be a
  durable, non-purgeable location — never /tmp or /private/tmp, which periodic
  OS cleanup deletes. The controller records the actual provisioned path and
  confirms it with git before relying on it.>
- Integration target: <remote and branch resolved from repository policy>
- Owned files/responsibility: <exclusive footprint>
- Dependencies: <worker names or milestones that gate this task>

Allowed mutations
- <files, branches, commits, issue/PR actions, or external systems explicitly allowed>

Explicit Prohibitions
- Do not mutate outside the owned footprint.
- Do not create a projectless worker or attach the worker to the target repository's
  project when the origin is Vault; project association and repository ownership are
  separate.
- Workers never merge or promote; this authority is non-delegable, even when an
  approval message, green PR, auto-merge option, or merge-capable tool exists.
- Do not deploy, touch live data, destroy/discard work, disclose externally, or
  create replacement workers unless each operation is explicitly authorized.
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
- Success: <observable result, target reachability, required validation, durable-status location, and no remaining follow-up>
- Stop: <boundary, failed gate, owner decision, or capability gap>

COMPLETE report
- Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- Changes: <paths and concise behavior>
- Verification: <commands and exact results>
- Commits/durable outputs: <identifiers and locations>
- Integration: <target, current reachability, remaining action>
- Review artifact: <PR URL or why none exists>
- Merge-ready handoff: <exact head SHA, base/integration target, checks, and unresolved blockers>
- Durable status: <record path/commit or still required>
- Follow-up: <none or exact remaining assignment>
- Risks/questions: <none or explicit items>
```

Workers never merge. The originating controller independently revalidates the exact
head and checks, obtains required owner authorization, and performs the merge or
promotion from its trusted context. COMPLETE, approval, and green checks are
evidence for that decision, never worker-side merge permission.

The controller answers a question itself when repository instructions, the worker
contract, or an already-recorded owner decision yields one valid answer. It sends
the answer as a durable worker message and records the policy source. It escalates
when multiple valid choices remain or the question seeks new authority, money,
external disclosure, destructive action, live-data access, merge, or deployment.
