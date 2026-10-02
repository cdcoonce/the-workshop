# Review a pull request against its spec

A pull request is about to merge and nobody else will read it first. Two files in your working directory describe it:

- `spec.md` holds the pull request's title and description, which is the binding specification for the change.
- `diff.patch` holds the full diff of the change.

Review the change against that specification. Read those two files and nothing else in the directory: everything you need is in them. Do not run code or use the network.

Report real defects only. That covers code that does the wrong thing, tests that would not catch the failure they are named for, requirements the specification states that the change does not meet, and changes the specification never asked for. For each defect give the file, the line number in the new version of that file, and a worked example of the failure: which input or starting state makes the code misbehave, and what it does instead. A problem you cannot tie to a file and a line is not reportable. Leave out style, naming and personal preference. If you find no defect, an empty list is the right answer.

Reply with a single JSON object and nothing else, in exactly this shape:

{"findings": [{"file": "<path as it appears in the diff>", "line": <integer line number>, "description": "<the defect and its failure scenario>"}]}
