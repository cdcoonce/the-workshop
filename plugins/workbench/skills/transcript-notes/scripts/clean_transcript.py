"""Deterministically clean a raw transcript into readable prose.

This is Step 1 of the ``transcript-notes`` skill: a stdlib-only pass that runs
before any model reconstruction. It auto-detects the transcript format
(WebVTT, SRT, ``[HH:MM:SS]`` timestamped-plain, or plain prose), strips cue
metadata, removes the rolling-overlap duplication that YouTube auto-captions
produce, joins caption fragments into sentences, and reports the word count and
an estimated lecture length.

Rather than discarding every timestamp, the cleaner keeps **sparse anchor
lines** of the form ``[t=HH:MM:SS]`` in the output — one at the start of the
first sentence that opens each new anchor interval (default 120 s). Downstream
reconstruction reads these to place ``[!gap]`` markers, segment boundaries, and
map-note time ranges without re-parsing the raw transcript. Plain prose has no
timestamps, so it gets no anchors.

The cleaner never paraphrases or drops content beyond duplicated caption
overlap and structural metadata — the reconstruction pass downstream owns all
interpretation. Run as a CLI::

    python clean_transcript.py <input_file> -o <output_file> [--anchor-interval SECONDS]

Detected format, word count, and estimated minutes are printed to stdout.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

WORDS_PER_MINUTE = 150
ANCHOR_INTERVAL_DEFAULT_S = 120

_VTT_TIMING = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}")
_SRT_TIMING = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
_TIMING_START = re.compile(r"^(\d{1,2}:\d{2}:\d{2}[.,]\d{3})\s*-->")
_LEADING_TIMESTAMP = re.compile(r"^\[?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{3})?\]?\s*")
_LEADING_TIMESTAMP_CAPTURE = re.compile(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{3})?)\]?")
_INLINE_TAGS = re.compile(r"</?[cbiuv][^>]*>|<\d{2}:\d{2}:\d{2}[.,]\d{3}>")
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?$")
_ANCHOR_LINE = re.compile(r"^\[t=\d{2}:\d{2}:\d{2}\]$")


def is_anchor_line(line: str) -> bool:
    """Return whether a line is a ``[t=HH:MM:SS]`` timestamp anchor."""
    return bool(_ANCHOR_LINE.match(line.strip()))


def _parse_timestamp(raw_ts: str) -> float | None:
    """Parse ``HH:MM:SS.mmm`` / ``MM:SS`` / bracketed forms into seconds."""
    ts = raw_ts.strip().strip("[]").replace(",", ".")
    parts = ts.split(":")
    seconds = 0.0
    for part in parts:
        try:
            seconds = seconds * 60 + float(part)
        except ValueError:
            return None
    return seconds


def _format_hms(seconds: float) -> str:
    """Format a second count as ``HH:MM:SS``."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class TranscriptFormat(str, Enum):
    """The transcript shapes the cleaner recognizes."""

    VTT = "vtt"
    SRT = "srt"
    TIMESTAMPED = "timestamped"
    PLAIN = "plain"


@dataclass(frozen=True)
class CleanResult:
    """The cleaned transcript and its size metadata.

    Parameters
    ----------
    text
        Cleaned prose, one sentence per line.
    word_count
        Number of whitespace-delimited words in ``text``.
    estimated_minutes
        Approximate spoken length at :data:`WORDS_PER_MINUTE`.
    source_format
        The format the raw input was detected as.
    """

    text: str
    word_count: int
    estimated_minutes: int
    source_format: TranscriptFormat


def detect_format(raw: str) -> TranscriptFormat:
    """Classify a raw transcript by its structural markers.

    Parameters
    ----------
    raw
        The unprocessed transcript text.

    Returns
    -------
    TranscriptFormat
        The detected format. Plain prose is the fallback when no caption
        markers are present.
    """
    lines = raw.splitlines()
    if lines and lines[0].lstrip().upper().startswith("WEBVTT"):
        return TranscriptFormat.VTT
    if any(_SRT_TIMING.match(line.strip()) for line in lines):
        return TranscriptFormat.SRT
    if any(_VTT_TIMING.match(line.strip()) for line in lines):
        return TranscriptFormat.VTT
    if any(_LEADING_TIMESTAMP.match(line) and line.strip() for line in lines):
        return TranscriptFormat.TIMESTAMPED
    return TranscriptFormat.PLAIN


def _is_metadata_line(line: str, fmt: TranscriptFormat) -> bool:
    """Return whether a line is cue metadata rather than spoken text."""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.upper().startswith("WEBVTT"):
        return True
    if stripped.startswith("NOTE") or stripped.startswith("Kind:") or stripped.startswith("Language:"):
        return True
    if "-->" in stripped and (_VTT_TIMING.match(stripped) or _SRT_TIMING.match(stripped)):
        return True
    if fmt is TranscriptFormat.SRT and stripped.isdigit():
        return True
    return False


def _extract_timed_lines(raw: str, fmt: TranscriptFormat) -> list[tuple[float | None, str]]:
    """Strip metadata, returning ``(start_seconds, text)`` per spoken-text line.

    ``start_seconds`` is the cue's start time (``None`` when the format carries
    no timing, i.e. plain prose).
    """
    out: list[tuple[float | None, str]] = []
    current_time: float | None = None
    for line in raw.splitlines():
        if fmt is TranscriptFormat.TIMESTAMPED:
            match = _LEADING_TIMESTAMP_CAPTURE.match(line)
            cue_time = _parse_timestamp(match.group(1)) if match else None
            text = _LEADING_TIMESTAMP.sub("", _INLINE_TAGS.sub("", line)).strip()
            if text:
                out.append((cue_time, text))
            continue
        if fmt is TranscriptFormat.PLAIN:
            text = line.strip()
            if text:
                out.append((None, text))
            continue
        # VTT / SRT: a timing line sets the cue start for the text lines that follow.
        timing = _TIMING_START.match(line.strip())
        if timing:
            current_time = _parse_timestamp(timing.group(1))
            continue
        if _is_metadata_line(line, fmt):
            continue
        text = _INLINE_TAGS.sub("", line).strip()
        if text:
            out.append((current_time, text))
    return out


def _dedupe_rolling_timed(
    timed_lines: list[tuple[float | None, str]],
) -> tuple[list[str], list[float | None]]:
    """Collapse rolling-overlap duplication, keeping a time per surviving token.

    Consecutive caption cues repeat a sliding window of words. This rebuilds a
    single token stream, appending only the non-overlapping tail of each cue
    (an exact-duplicate cue contributes nothing). Each appended token carries
    its originating cue's start time.

    Parameters
    ----------
    timed_lines
        ``(start_seconds, text)`` cues in reading order.

    Returns
    -------
    tuple[list[str], list[float | None]]
        Parallel lists of tokens and their cue start times.
    """
    tokens: list[str] = []
    times: list[float | None] = []
    for cue_time, text in timed_lines:
        incoming = text.split()
        if not incoming:
            continue
        max_overlap = min(len(tokens), len(incoming))
        overlap = 0
        for k in range(max_overlap, 0, -1):
            if [t.lower() for t in tokens[-k:]] == [t.lower() for t in incoming[:k]]:
                overlap = k
                break
        for token in incoming[overlap:]:
            tokens.append(token)
            times.append(cue_time)
    return tokens, times


def _first_known_time(times: list[float | None], start: int) -> float | None:
    """Return the first non-``None`` time at or after index ``start``."""
    for time in times[start:]:
        if time is not None:
            return time
    return None


def _assemble_with_anchors(
    tokens: list[str],
    times: list[float | None],
    anchor_interval_s: float,
) -> str:
    """Join tokens into one sentence per line, interleaving sparse time anchors.

    An anchor line ``[t=HH:MM:SS]`` is emitted before the first sentence whose
    start time opens a new ``anchor_interval_s`` window. Streams with no known
    times (plain prose) get no anchors.

    Parameters
    ----------
    tokens
        The reconstructed token stream.
    times
        Per-token cue start times, parallel to ``tokens``.
    anchor_interval_s
        Minimum spacing, in seconds, between successive anchors.

    Returns
    -------
    str
        The assembled text, anchors and sentences newline-separated.
    """
    lines: list[str] = []
    sentence: list[str] = []
    sentence_start = 0
    next_anchor: float | None = None

    def flush(start_idx: int) -> None:
        nonlocal next_anchor
        if not sentence:
            return
        time = _first_known_time(times, start_idx)
        if time is not None and (next_anchor is None or time >= next_anchor):
            lines.append(f"[t={_format_hms(time)}]")
            next_anchor = time + anchor_interval_s
        lines.append(" ".join(sentence))

    for index, token in enumerate(tokens):
        if not sentence:
            sentence_start = index
        sentence.append(token)
        if _SENTENCE_END.search(token):
            flush(sentence_start)
            sentence = []
    if sentence:
        flush(sentence_start)
    return "\n".join(lines)


def clean_transcript(
    raw: str,
    anchor_interval_s: float = ANCHOR_INTERVAL_DEFAULT_S,
) -> CleanResult:
    """Clean a raw transcript into readable, deduplicated prose with anchors.

    Parameters
    ----------
    raw
        The unprocessed transcript in any supported format.
    anchor_interval_s
        Minimum spacing between ``[t=HH:MM:SS]`` anchors, in seconds. Anchors
        are emitted only for formats that carry timing (not plain prose).

    Returns
    -------
    CleanResult
        The cleaned text and its size metadata. ``word_count`` excludes anchor
        lines.

    Raises
    ------
    ValueError
        If the input contains no spoken text.
    """
    if not raw or not raw.strip():
        raise ValueError("transcript is empty")

    fmt = detect_format(raw)
    timed = _extract_timed_lines(raw, fmt)

    if fmt is TranscriptFormat.PLAIN:
        tokens = " ".join(text for _, text in timed).split()
        times: list[float | None] = [None] * len(tokens)
    else:
        tokens, times = _dedupe_rolling_timed(timed)

    if not tokens:
        raise ValueError("transcript contained no spoken text after cleaning")

    text = _assemble_with_anchors(tokens, times, anchor_interval_s)
    word_count = sum(
        len(line.split()) for line in text.splitlines() if not is_anchor_line(line)
    )
    estimated_minutes = max(1, round(word_count / WORDS_PER_MINUTE))
    return CleanResult(
        text=text,
        word_count=word_count,
        estimated_minutes=estimated_minutes,
        source_format=fmt,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments for the CLI entry point."""
    parser = argparse.ArgumentParser(description="Clean a raw transcript into readable prose.")
    parser.add_argument("input", type=Path, help="Path to the raw transcript file.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to write cleaned text.")
    parser.add_argument(
        "--anchor-interval",
        type=float,
        default=ANCHOR_INTERVAL_DEFAULT_S,
        metavar="SECONDS",
        help="Minimum spacing between [t=HH:MM:SS] anchors (default: %(default)s).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the cleaner as a CLI, returning a process exit code."""
    args = _parse_args(argv)
    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1
    raw = args.input.read_text(encoding="utf-8")
    try:
        result = clean_transcript(raw, anchor_interval_s=args.anchor_interval)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.output.write_text(result.text + "\n", encoding="utf-8")
    print(
        f"Cleaned {args.input.name} ({result.source_format.value}): "
        f"{result.word_count} words, ~{result.estimated_minutes} min -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
