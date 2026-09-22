# Arm B — terse contract (same lens scopes, compressed language)

Prompt assembly: identical to arm A: `<shared preamble>\n\n<lens body>\n\n<output format>\n\nSPEC file: <absolute path to fixture/spec.md>\nDIFF file: <absolute path to fixture/diff.patch>`

## Shared preamble (every lens)

Review PR #896 against SPEC and DIFF, read from the two files named at the
end of this prompt. No other tools, no other files — those materials only. Defects only, each with file:line and a concrete failure.
An empty findings list is a valid answer. No style, naming, or preference.

## Lens: domain

Lens: git history and squash semantics only. Hand-check each ancestry test,
prefix boundary, and squash-base pick against a concrete pushed/unpushed
session.

## Lens: test_veracity

Lens: would each new test fail on the pre-change tree? Flag tests that pass
anyway, and assertions that cannot fail or assert the implementation to
itself.

## Lens: spec_conformance

Lens: SPEC vs DIFF, both directions — requirements SPEC states that DIFF
misses, and changes in DIFF that SPEC never asked for.

## Output format (identical in both arms)

Output ONLY a JSON object, no prose before or after, in this exact shape:
{"findings": [{"file": "<path as it appears in DIFF>", "line": <integer line number in the new file>, "description": "<the defect and its concrete failure scenario>"}]}
