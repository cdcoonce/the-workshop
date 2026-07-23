# Operational Details

Runtime specifics the workflow depends on. Read this before running the skill.

## Running the bundled scripts

The scripts live in **this skill's own `scripts/` directory**, which is *not*
the runtime working directory. Resolve the skill directory first (the folder
containing this skill's `SKILL.md`) and invoke the scripts by absolute path, or
`cd` into that `scripts/` directory before running them. Do not assume a bare
`scripts/…` path resolves — it won't from the user's project cwd.

```bash
SKILL_DIR="<absolute path to this skill>"          # the dir holding SKILL.md
uv run "$SKILL_DIR/scripts/fetch_transcript.py" "<url-or-id>" -o /tmp/transcript-notes-raw.txt
python3 "$SKILL_DIR/scripts/clean_transcript.py" /tmp/transcript-notes-raw.txt -o /tmp/transcript-notes-clean.txt
```

## Timestamps — read the anchors in the cleaned file

The cleaner keeps **sparse anchor lines** in its output — `[t=HH:MM:SS]` on their
own line, one at the start of the first sentence opening each ~120 s window (tune
with `--anchor-interval`). These are the timestamp source; you do **not** need to
re-read the raw file:

- **`[!gap]` markers (Step 3):** use the nearest **preceding** `[t=…]` anchor as
  the "~mm:ss" for the referenced visual — approximate is expected.
- **Segmentation (Step 2):** the cleaner's word-count sizes the job; the anchors
  give wall-clock positions. Put ~20–30 min splits and the map note's ranges at
  the anchors nearest each topic boundary.
- **Plain pasted prose carries no anchors** (it has no timing). Then omit `[!gap]`
  timestamps (the rule is "when inferable") and segment by topic and word count.

Anchors are emitted for YouTube (fetched), VTT, SRT, and timestamped inputs. If
you need finer precision than the anchor spacing gives, the raw file is still on
disk (fetched file or the uploaded VTT/SRT) and can be consulted, but the anchors
cover the normal case.

## Duplicate check and idempotent resume (Step 0 ↔ Step 2)

A source is identified by its `video_id` (YouTube) — pasted/non-YouTube inputs
carry no id, so they are **not** dedup-checked (re-pasting produces a new note;
state this if it matters). For YouTube inputs, reconcile the two rules with one
state check before fetching:

1. **`INDEX.md` absent** → first run ever; treat as no prior ingests (you will
   create `INDEX.md` in Step 5).
2. **id not in `INDEX.md` and no part files on disk** → fresh ingest.
3. **id in `INDEX.md` and all expected part files present** → already ingested;
   report where they live and stop unless the user forces a re-ingest.
4. **Part files present but incomplete** (a crashed segmented run) → **resume**:
   continue from the first missing part; do not re-emit completed parts.

Write the `INDEX.md` line in Step 5 **after all parts for the source succeed**, so
a partial run is detected as case 4 (by its part files), not falsely skipped as
case 3.

## Notes directory creation and `~` expansion

Create the destination before writing: `mkdir -p ~/.workshop/transcript-notes/`
(or the configured dir). When writing via a non-shell tool (a file API rather
than a shell), **expand `~` to `$HOME` yourself** — a literal `~/.workshop/…`
path is not expanded by most file APIs and will misfile the note.

## Caption language

The fetcher prefers English but falls back to any available track. If the
resolved track (`caption_track` in the printed output) is **not English**, say so
in chat and record the language in frontmatter; proceed to build the note in that
language rather than failing. Do not silently present a foreign-language note as
if it were English.
