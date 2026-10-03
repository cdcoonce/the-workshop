# T-trig acceptance criteria (private; scorer-only, never sent to the case-agent)

T-trig measures one thing: whether the rostered skill fires when a user asks for a feature to
be built test-first. The case-agent works in a small text-helpers library with a green suite
and one new function to add. The request says how the user wants the work done but spells out
none of the method, so the skill has to supply it.

## Triggering item: T-trig

Met when the transcript holds a Skill tool call naming tdd, and that call precedes every other
tool call except Skill and ToolSearch calls, and precedes the agent's final text.

An agent that writes tests first on its own but never loads the skill misses. So does an agent
that loads it after reading the repository, after editing a file, or only in its closing reply.
Whether the function ends up correct is not graded here.

Calibration is skill arm only: 6 executions, at least 5 hits, no no-skill arm. The harness
applies that for any triggering item; this case adds no calibration key.
