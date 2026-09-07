# Post-Sync Session Follow-Up

Run this workflow only after the wrap-up audit, touched-sections-only handoff
refresh, and sync have all succeeded. A failed or uncertain sync blocks both
offers. Resolve it in the current session; begin this workflow only after a
confirmed successful retry.

## Ground the Context

Use the current conversation and its tool results as the source of truth for
what happened this session. Include relevant work committed earlier in the
session. Git status, diffs, commits, the session notebook, and the rolling
handoff are supporting evidence; do not treat unrelated pre-existing edits as
session work or stale handoff text as current merely because it exists.

Keep prompts in the current conversation and native tool call. Never write a
prompt file or a draft skill.

## Consent Rules

The workflow-improvement session and continuation session are independent
offers. Ask them separately and apply each answer only to its own offer. An
acceptance of one never authorizes the other; a decline of one never suppresses
the other.

Ask before generating the complete prompt or starting a session. Once the user
accepts, that answer authorizes prompt generation and one launch attempt; do not
add a preview-approval step.

Use the runtime's proper interactive question mechanism. With an asynchronous
form, keep the question active and wait for actual input: do not end the turn,
emit a final response, apply a timeout/default, preselect an answer, or treat a
partial form response as answers to untouched questions. No answer is never
approval. If only plain-text questions are available, ask one concise question
at a time and wait.

## Offer 1: Workflow Improvement

If Step 7 retained a meaningful opportunity, state the strongest one as a
concrete friction or reusable success, name one meaningful example, cite its
evidence pointers, and ask whether to open one focused improvement session. Do
not offer a menu of candidates.

After acceptance, generate an observation-and-context-only prompt containing:

- the observed friction or reusable success and its concrete example;
- stable evidence pointers such as paths, commits, issues, or command output;
- the relevant session and repository context; and
- a request to investigate the opportunity.

Leave diagnosis, scope, and design to the receiving agent. Do not prescribe a
fix, supply an implementation-ready plan, or assume the outcome is a new skill.
Launch or display the prompt using **Launch Protocol** below. After the accepted
offer is launched or its result is reported, continue to Offer 2 even when the
improvement launch remains uncertain; preserve that attempt and suppress unsafe
retries without letting its unresolved status gate continuation. A decline also
continues to Offer 2. If the question remains unanswered, keep it active and do
nothing dependent on it.

If no meaningful opportunity exists, skip Offer 1 and continue to Offer 2.

## Offer 2: Continue Current Work

Offer a separate new session to continue the current work. If the session had
one workstream, name it in the offer. If it had several, first ask whether the
user wants a continuation session; after acceptance, ask which single
workstream to continue. Generate no continuation prompt until those answers are
received.

The accepted prompt includes only the selected workstream and is self-contained:

- the task or current checkpoint and what was completed this session;
- the next unresolved obligation, blocker, or decision;
- stable evidence and repository references needed to resume; and
- constraints or accepted decisions that still govern the work.

Do not rely only on the mutable rolling handoff. Select the project or
repository that owns the workstream, which may differ from the vault where the
thinking session began. Ask a focused follow-up after acceptance if ownership is
ambiguous.

## Launch Protocol

After acceptance, use a native tool that creates an independent, user-owned
session or task when the host provides one. Follow its schema and preserve the
user's saved host, project, model, and reasoning defaults. Resolve the owner
project from the prompt's work, not from the current directory alone. Do not
substitute a subagent, fork, background process, or assumed portable CLI.

In Codex, resolve the saved owner project with `list_projects`, then call
`create_thread` once. Use the project environment required by that tool and
omit `model` and `thinking` unless the user explicitly asked to override them.
Only report a task ID returned by the tool.

If the host has no native independent-session tool, explain that after
acceptance and show the complete manual-launch prompt in the current
conversation. Do not continue the work in the current session as a substitute.

## Launch Results and Duplicate Prevention

Track each accepted offer, generated prompt, and launch attempt in the current
conversation so a retry reuses the same scope. Report definitive success,
definitive failure, and uncertainty exactly as returned. Never invent an ID.

An uncertain result without a stable task or operation ID may already have
created the session. Do not repeat the creation call automatically, even when
the user says to try again. First use any native read-only status, operation, or
task-list mechanism to reconcile the original attempt. Retry only if the host
can prove no session was created or offers an idempotent retry. Otherwise explain
the duplicate risk and provide the complete manual prompt or ask the user to
identify the created task. A definitive failed attempt may be retried when the
user requests it.
