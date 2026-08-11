# Frontmatter and Index Schema

## Note frontmatter

Every note opens with YAML frontmatter so Obsidian (and Dataview) can query the
collection and so `INDEX.md` lines can be generated from it.

```yaml
---
title: "Attention Is All You Need — walkthrough"
source: "https://www.youtube.com/watch?v=ROEad3SDI9Q"   # omit for non-YouTube inputs
video_id: "ROEad3SDI9Q"                                  # omit for non-YouTube inputs
ingested: 2026-07-22                                     # date the note was created
duration_estimate_min: 52                                # from the cleaner
part: 1                                                  # omit when single-segment
part_of: 3                                               # omit when single-segment
caption_track: "en (manual)"                             # from the fetcher; omit for supplied transcripts
content_kind: lecture                                    # lecture | talk | webinar | interview | panel | demo
tags: [transcript-notes, attention, transformers]
---
```

Rules:

- `ingested` is an absolute date, never "today".
- Include `source`, `video_id`, and `caption_track` only for YouTube inputs.
- `part` / `part_of` appear only on multi-segment notes; the map note itself
  carries `part: 0` or omits both and sets `content_kind` unchanged.
- `tags` always includes `transcript-notes` plus 1–4 topic tags derived from the
  content. Keep them lowercase and hyphenated.

## Map note (segmented inputs)

When a source is split into parts, write one extra map note named
`<slug>--<video_id>-map.md` (or `<slug>-map.md`). Its body lists every segment
with a rough timestamp range, a one-line topic, and a wikilink:

```markdown
# Attention Is All You Need — segment map

- **00:00–24:30** — Motivation and attention definition → [[attention-walkthrough--ROEad3SDI9Q-part1]]
- **24:30–41:00** — Multi-head attention and scaling → [[attention-walkthrough--ROEad3SDI9Q-part2]]
- **41:00–52:00** — Positional encoding and results → [[attention-walkthrough--ROEad3SDI9Q-part3]]
```

## INDEX.md

One line is appended per ingested source (not per part) in the notes directory:

```markdown
- 2026-07-22 — **Attention Is All You Need — walkthrough** (3 parts) — https://www.youtube.com/watch?v=ROEad3SDI9Q
```

The video id in these lines and in each note's frontmatter is what the duplicate
check in Step 0 reads before fetching.
