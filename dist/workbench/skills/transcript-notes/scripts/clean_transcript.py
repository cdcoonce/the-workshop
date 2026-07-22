"""Deterministically clean a raw transcript into readable prose.

This is Step 1 of the ``transcript-notes`` skill: a stdlib-only pass that runs
before any model reconstruction. It auto-detects the transcript format
(WebVTT, SRT, ``[HH:MM:SS]`` timestamped-plain, or plain prose), strips cue
metadata and timestamps, removes the rolling-overlap duplication that YouTube
auto-captions produce, joins caption fragments into sentences, and reports the
word count and an estimated lecture length.

The cleaner never paraphrases or drops content beyond duplicated caption
overlap and structural metadata — the reconstruction pass downstream owns all
interpretation. Run as a CLI::

    python clean_transcript.py <input_file> -o <output_file>

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

_VTT_TIMING = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}")
_SRT_TIMING = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
_LEADING_TIMESTAMP = re.compile(r"^\[?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{3})?\]?\s*")
_INLINE_TAGS = re.compile(r"</?[cbiuv][^>]*>|<\d{2}:\d{2}:\d{2}[.,]\d{3}>")
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?$")


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


def _extract_text_lines(raw: str, fmt: TranscriptFormat) -> list[str]:
    """Strip metadata and timestamps, returning bare spoken-text lines."""
    out: list[str] = []
    for line in raw.splitlines():
        if _is_metadata_line(line, fmt):
            continue
        text = _INLINE_TAGS.sub("", line)
        if fmt is TranscriptFormat.TIMESTAMPED:
            text = _LEADING_TIMESTAMP.sub("", text)
        text = text.strip()
        if text:
            out.append(text)
    return out


def _dedupe_rolling(lines: list[str]) -> list[str]:
    """Collapse YouTube's rolling-overlap caption duplication.

    Consecutive caption cues repeat a sliding window of words. This rebuilds a
    single token stream, appending only the non-overlapping tail of each line
    (an exact-duplicate line contributes nothing).

    Parameters
    ----------
    lines
        Spoken-text lines in reading order.

    Returns
    -------
    list[str]
        A single reconstructed line (or empty list for empty input).
    """
    tokens: list[str] = []
    for line in lines:
        incoming = line.split()
        if not incoming:
            continue
        max_overlap = min(len(tokens), len(incoming))
        overlap = 0
        for k in range(max_overlap, 0, -1):
            if [t.lower() for t in tokens[-k:]] == [t.lower() for t in incoming[:k]]:
                overlap = k
                break
        tokens.extend(incoming[overlap:])
    return [" ".join(tokens)] if tokens else []


def _assemble_sentences(text: str) -> str:
    """Split a continuous token stream into one sentence per line."""
    words = text.split()
    sentences: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if _SENTENCE_END.search(word):
            sentences.append(" ".join(current))
            current = []
    if current:
        sentences.append(" ".join(current))
    return "\n".join(sentences)


def clean_transcript(raw: str) -> CleanResult:
    """Clean a raw transcript into readable, deduplicated prose.

    Parameters
    ----------
    raw
        The unprocessed transcript in any supported format.

    Returns
    -------
    CleanResult
        The cleaned text and its size metadata.

    Raises
    ------
    ValueError
        If the input contains no spoken text.
    """
    if not raw or not raw.strip():
        raise ValueError("transcript is empty")

    fmt = detect_format(raw)
    lines = _extract_text_lines(raw, fmt)

    if fmt is TranscriptFormat.PLAIN:
        text = _assemble_sentences(" ".join(lines))
    else:
        merged = _dedupe_rolling(lines)
        text = _assemble_sentences(merged[0]) if merged else ""

    if not text.strip():
        raise ValueError("transcript contained no spoken text after cleaning")

    word_count = len(text.split())
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the cleaner as a CLI, returning a process exit code."""
    args = _parse_args(argv)
    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1
    raw = args.input.read_text(encoding="utf-8")
    try:
        result = clean_transcript(raw)
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
