# Review a pull request

Two files in your working directory describe a pull request: `spec.md` holds its title and description, and `diff.patch` holds its diff. Review the change against that description. Read only those two files.

Reply with a single JSON object and nothing else, in exactly this shape:

{"findings": [{"file": "<path as it appears in the diff>", "line": <integer line number in the new file>, "description": "<what is wrong and how it fails>"}]}

If you find nothing wrong, reply with an empty findings list.
