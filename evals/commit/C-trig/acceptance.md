# C-trig acceptance criteria (private; scorer-only, never sent to the case-agent)

C-trig measures one thing: whether the rostered skill fires when a user asks for working-tree
changes to be saved to git history. The case-agent works in a freshly built throwaway
repository: one existing commit, then uncommitted edits in several files and no remote. The
request never names the skill and says nothing about message style or how to group the edits,
so the skill has to supply those.

## Triggering item: C-trig

Met when the transcript holds a Skill tool call naming commit, and that call precedes every
other tool call except Skill and ToolSearch calls, and precedes the agent's final text.

An agent that runs git status first, then loads the skill, misses; so does one that never loads
it, however tidy its history comes out. How the changes are grouped or worded is not graded here.

In real runs the Skill call's name is plugin-qualified (`workbench:commit`), so the item's
param is that string. A hand run that shows the bare name has a different harness shape and must be
investigated before its hits or misses are trusted.

Calibration is skill arm only: 6 executions, at least 5 hits, no no-skill arm. The harness
applies that for any triggering item; this case adds no calibration key.
