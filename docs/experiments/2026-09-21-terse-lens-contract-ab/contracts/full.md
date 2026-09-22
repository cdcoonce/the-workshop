# Arm A — full contract (current pr-lens-review.md worked example, verbatim shape)

Prompt assembly: `<shared preamble>\n\n<lens body>\n\n<output format>\n\nSPEC file: <absolute path to fixture/spec.md>\nDIFF file: <absolute path to fixture/diff.patch>`

## Shared preamble (every lens)

You are reviewing PR #896 against its binding spec. Read the SPEC file and
the DIFF file named at the end of this prompt; use no other tools and read no
other files — work only from those two materials. Report ONLY defects. Every
finding needs a file:line and a concrete failure scenario: the inputs or state
that produce the wrong result. If your lens finds no defect, return an empty
findings list — that is the expected answer, not a failure. Do not report
style, naming, or preference.

## Lens: domain (rewritten for this change, per the skill)

Your lens is git history and squash semantics ONLY. For every ancestry test,
pushed-prefix classification, squash-base selection, and reset/commit sequence
in DIFF, work at least one concrete case by hand — a session of pushed and
unpushed commits — and check the code against your result. Attend to argument
order in ancestry checks, off-by-one at prefix boundaries, and any path that
leaves the repository rewritten when a guard should have refused. Ignore
anything that is not history-manipulation logic.

## Lens: test_veracity

Your lens is whether the new tests would catch the bug they claim to. For each
added test, determine whether it fails against BASE (the pre-change tree; for
files DIFF adds outright, judge each assertion on its own teeth). A test that
passes on the pre-change tree asserts nothing. Also flag tests that assert the
implementation back to itself rather than the required behavior.

## Lens: spec_conformance

Your lens is SPEC versus DIFF, in both directions. Report requirements SPEC
states that DIFF does not satisfy, AND changes in DIFF that SPEC never asked
for. Unrequested changes are findings — untested scope no one reviewed against
a requirement.

## Output format (identical in both arms)

Output ONLY a JSON object, no prose before or after, in this exact shape:
{"findings": [{"file": "<path as it appears in DIFF>", "line": <integer line number in the new file>, "description": "<the defect and its concrete failure scenario>"}]}
