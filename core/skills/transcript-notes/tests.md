# Transcript Notes Tests

Behavioral scenarios for the `transcript-notes` skill. Each scenario states an
input and the expected behavior; a QA pass scores the SKILL.md against them.
Transcript excerpts here are original, written for testing — no third-party
caption text.

## Scenario 1: Never summarizes

Given a 6-minute cleaned transcript, the user says "make this readable."

Expected: the note reconstructs the full argument restructured for reading —
headings, callouts, equations — and preserves every substantive point. It does
NOT produce a shorter summary, an abstract, or a bullet digest that drops
content. A note materially shorter than the transcript's argument is a failure.

## Scenario 2: Spoken math becomes glossed LaTeX

The transcript contains: "so the loss is the negative log likelihood, sum over i
of log p of y i given x i."

Expected: rendered as `$$…$$` display math in standard notation
(e.g. $\mathcal{L} = -\sum_i \log p(y_i \mid x_i)$) with a one-line italic gloss
beneath explaining what it does. The spoken phrase is not left as prose.

## Scenario 3: Honesty on mangled math

The transcript contains an equation the ASR garbled into noise
("the thing over the other square root d something").

Expected: the note renders a best-guess equation AND explicitly marks it as
uncertain / to-verify. It does NOT present a fabricated equation as if certain,
and does NOT silently drop the equation.

## Scenario 4: Missing visuals are flagged, not invented

The transcript says "as you can see in this plot, the curve flattens out around
here."

Expected: a `[!gap]` callout stating the likely visual type and role (a curve
that plateaus — probably a loss/accuracy curve) with an approximate timestamp if
inferable. It does NOT fabricate specific axis values, numbers, or a detailed
description of a chart it cannot see.

## Scenario 5: Fetch failure fails fast

The user gives a YouTube URL whose video has captions disabled; the fetcher exits
non-zero reporting that.

Expected: the skill reports the actual error and stops. It does NOT fabricate a
transcript, and does NOT fall back to summarizing the video from general
knowledge.

## Scenario 6: Duplicate is skipped unless forced

The user gives a YouTube URL whose video id already appears in `INDEX.md`.

Expected: the skill reports where the existing notes live and stops, unless the
user explicitly asks to force a re-ingest. It does not silently overwrite.

## Scenario 7: Taxonomy flexes for non-lecture content

The input is an interview transcript (two speakers, Q and A), not a lecture.

Expected: block callouts adapt to the content (e.g. question / answer / point)
rather than forcing SETUP / DERIVATION labels, while still using the same callout
machinery and reading prompts.

## Scenario 8: Output goes to the convention location

The user ingests a transcript with no destination configured.

Expected: the note is written under `~/.workshop/transcript-notes/` with full
YAML frontmatter, and `INDEX.md` there gains one line. If `TRANSCRIPT_NOTES_DIR`
or an explicit path is configured, that destination is used instead.

## Scenario 9: Long transcript segments in one run

A 90-minute lecture is ingested.

Expected: the skill splits at topic boundaries into ~20–30 min segments, writes
every part as its own note in the same run (no waiting for "next"), and writes a
map note linking all parts with wikilinks.

## Scenario 10: Bare invocation asks once

The user triggers the skill with no URL and no transcript.

Expected: a single one-line request for a URL or transcript. It does not proceed
on empty input and does not invent content.

## Scenario 11: Scripts run from the right directory

The user ingests a transcript while their shell is in an unrelated project
directory, not the skill's directory.

Expected: the skill resolves the skill directory and invokes the bundled scripts
by an absolute/skill-anchored path (e.g. `$SKILL_DIR/scripts/...`), not a bare
`scripts/...` that would be "file not found" from the project cwd.

## Scenario 12: Gap and segment timestamps survive cleaning

The cleaner strips all timestamps, yet a `[!gap]` needs "~mm:ss" and a 90-min
lecture needs wall-clock segment boundaries.

Expected: the skill keeps the raw timestamped file and reads timestamps from it
for gaps, segment boundaries, and the map note — it does not try to read them
from the cleaned prose (which has none) or fabricate them. For plain pasted prose
with no timestamps, it omits gap timestamps rather than inventing them.

## Scenario 13: Crashed segmented run resumes, not skipped

A 3-part ingest wrote part 1 then crashed; the user re-runs the same URL.

Expected: the skill detects the partial run (part files present, INDEX line not
yet written) and resumes from part 2 — it does NOT see the id and skip as an
"already ingested" duplicate, and does NOT restart from part 1. This requires the
INDEX line to be written only after all parts succeed.

## Scenario 14: First-ever run with no INDEX.md

The notes directory does not exist yet; the user ingests their first source.

Expected: the skill treats an absent `INDEX.md` as no prior ingests (no error),
creates the directory (`mkdir -p`, `~` expanded to `$HOME` for non-shell writes),
and creates `INDEX.md` at the end.

## Scenario 15: Non-English-only captions

The YouTube video has only French captions.

Expected: the fetcher falls back to the French track; the skill notes the
language in chat and in `caption_track` frontmatter and proceeds to build a
French note — it does not silently present it as English and does not fail.

---

Scenarios 1–10 include some that a competent no-skill agent would also pass
(e.g. 5, 10, and the baseline-competence parts of 2–4); they guard against
regression rather than proving the skill's machinery. Scenarios 11–15 target the
skill-specific operational behavior (script paths, timestamp sourcing,
resume/index state, first-run, language handling) where a no-skill baseline fails.
