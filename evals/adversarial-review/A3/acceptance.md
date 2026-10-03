# A3 acceptance criteria (private; scorer-only, never sent to the case-agent)

A3 measures one thing: whether the rostered skill fires on a plain pre-merge-check request.
The case-agent works in a freshly built settlement repository with a fix branch checked out.
The request never names the skill and carries none of its method, so the only route to the
skill is the agent recognising that a merge check calls for it.

## Triggering item: A3

Met when the transcript holds a Skill tool call naming adversarial-review, and that call
precedes every other tool call except Skill and ToolSearch calls, and precedes the agent's
final text.

An agent that reviews the branch well but never loads the skill misses. So does an agent that
loads it after reading files, after running the tests, or only after writing its answer.

Calibration is skill arm only: 6 executions, at least 5 hits, no no-skill arm. The harness
applies that for any triggering item; this case adds no calibration key.
