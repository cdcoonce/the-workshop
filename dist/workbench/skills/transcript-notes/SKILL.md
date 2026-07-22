---
name: transcript-notes
description: 'Turn a YouTube lecture/talk or a raw transcript (VTT, SRT, or plain text) into a readable Obsidian-markdown study note — imposed structure, reconstructed LaTeX with plain-word glosses, flagged missing visuals, and per-section reading prompts. Trigger when the user gives a YouTube URL/video id to ingest, or uploads/pastes a transcript and wants it made readable ("ingest this talk", "clean up this transcript", "turn this lecture into notes"). Handles lectures, talks, webinars, interviews, and panels. Do NOT trigger to summarize (this skill never summarizes), to quiz/drill, or to typeset non-transcript prose.'
---

# Transcript Notes

Turn a transcript into one readable Obsidian-markdown study note per segment. A
transcript loses the visual channel and mangles spoken math; this skill repairs
what it can (structure, equations) and honestly flags what it can't (missing
visuals). **It never summarizes** — a summary of a transcript is a worse
transcript; the output preserves the full argument, restructured for a reader.

## Inputs

1. A **YouTube URL or bare video id** → fetch captions first (Step 0).
2. An **uploaded or pasted transcript** (`.vtt`, `.srt`, `.txt`, `.md`, raw
   text) → skip Step 0, start at Step 1.
3. **Bare invocation** with nothing → ask once, in one line, for a URL or
   transcript. Never proceed empty or fabricate a transcript.

## Output location

Write to the configured destination if set (a `TRANSCRIPT_NOTES_DIR` env var or
an explicit path the user gives); otherwise default to
`~/.workshop/transcript-notes/` (create if missing) — study notes are
machine-local output, not a repo artifact. Maintain an `INDEX.md` there, one line
per source. Frontmatter, index, and map-note formats:
[references/frontmatter-schema.md](references/frontmatter-schema.md).

## Workflow

### Step 0 — Fetch (YouTube inputs only)

Before fetching, check `INDEX.md` and existing frontmatter for the video id. If
already ingested, report where the notes live and stop unless the user forces a
re-ingest. Then run the fetcher with `uv` (its dependency resolves from inline
PEP 723 metadata — no install):

```bash
uv run scripts/fetch_transcript.py "<url-or-id>" -o /tmp/transcript-notes-raw.txt
```

It prefers manual English captions, then generated English, then any track, and
prints `video_id=… track=… (manual|generated)` — record both for frontmatter. On
no captions, a private/unavailable video, or a network error it exits non-zero
with the real error: **report it and stop**; never summarize from memory.

### Step 1 — Clean deterministically

Save pasted text to a file first, then run the cleaner and read its output (not
the raw file):

```bash
python3 scripts/clean_transcript.py <input_file> -o /tmp/transcript-notes-clean.txt
```

It auto-detects the format, strips cue metadata and timestamps, collapses YouTube's rolling-overlap
duplication, joins fragments into sentences, and prints word count and estimated minutes.

### Step 2 — Size the job

Using the cleaner's estimate (~150 wpm): under ~45 min (~7,000 words) → one note.
Longer → split at topic boundaries into ~20–30 min segments, emit **every**
segment as its own note in a single run (never wait for "next"), plus a **map
note** linking all parts. **Idempotent resume:** if part files for this source
already exist, continue from the first missing part.

### Step 3 — Reconstruct (model pass)

Read the cleaned text and, in one pass: **classify** each block with a callout
(flex the labels to the content — lecture vs interview vs demo); **rebuild** every
spoken equation as `$$…$$` LaTeX with a one-line italic gloss, marking any
uncertain reconstruction rather than inventing math; **flag** each visual
reference ("as you can see here") with a `[!gap]` callout naming the likely
visual and timestamp. Add a `[!ask]` reading prompt at each section start. Words
stay the speaker's argument, lightly repaired for grammar and ASR errors ("grade
in descent" → "gradient descent") — never paraphrased or summarized. Full
component rules: [references/callout-vocabulary.md](references/callout-vocabulary.md).

### Step 4 — Write the note

One markdown file per segment with full YAML frontmatter, `##` sections with type kickers, the Step 3
callouts, and `$$` math with glosses. Name files `<slug>--<video_id>.md` (or `-partN` when segmented;
drop `--<video_id>` for non-YouTube inputs). `<slug>` is a 3–6 word lowercase ASCII topic slug.

### Step 5 — Index and report

Append one line to `INDEX.md` per source. In chat: the saved path(s), one line on
coverage, and (if segmented) that all parts and the map note were written. **Do
not summarize the content in chat.**

## Quality floor

Notes render in Obsidian; every `$$` equation has a gloss; every visual reference
became a `[!gap]` or was genuinely non-visual; no section summarizes dropped
content; one `#` title with `##` sections; ASR terms repaired consistently;
frontmatter complete; `INDEX.md` updated; duplicates skipped unless forced.
Scope ends at "readable note" — no quizzing, drilling, interactive visuals, or
routing into a downstream learning system; that boundary is deliberate.
