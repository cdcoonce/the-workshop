# /// script
# requires-python = ">=3.12"
# dependencies = ["youtube-transcript-api>=1.0"]
# ///
"""Fetch a YouTube video's transcript into ``[HH:MM:SS]`` timestamped-plain text.

This is the optional Step 0 of the ``transcript-notes`` skill, used only when
the input is a YouTube URL or id rather than a supplied transcript file. Run it
with ``uv`` so the ``youtube-transcript-api`` dependency resolves from the inline
PEP 723 metadata above — no separate install step::

    uv run fetch_transcript.py <url-or-id> -o <output_file>

Caption selection prefers a manually-created English track, then generated
English, then any manual, then any generated track; the chosen language and
whether it was auto-generated are printed so the skill can record them in the
note's frontmatter. On no captions, a private/unavailable video, or a network
error the script reports the real error and exits non-zero — it never fabricates
a transcript.

The ``youtube_transcript_api`` import is deliberately lazy (inside
:func:`fetch_transcript`) so the pure helpers here import and unit-test without
the dependency present.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEFAULT_PREFERRED = ("en", "en-US", "en-GB")
_EMBED_PATH = re.compile(r"^/(embed|shorts|live)/([^/?]+)")


@dataclass(frozen=True)
class TrackInfo:
    """A caption track's identifying attributes for selection.

    Parameters
    ----------
    language_code
        The BCP-47 language code, e.g. ``"en"``.
    is_generated
        Whether the track is auto-generated rather than human-authored.
    """

    language_code: str
    is_generated: bool


def extract_video_id(url: str) -> str:
    """Extract the video id from a YouTube URL or a bare id.

    Parameters
    ----------
    url
        A YouTube watch/short/embed/live URL, ``youtu.be`` link, or bare id.

    Returns
    -------
    str
        The extracted 11-character video id (or the trimmed input when it is
        already a bare id).

    Raises
    ------
    ValueError
        If the input is empty.
    """
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("no URL or video id provided")

    parsed = urlparse(cleaned)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    if parsed.hostname and "youtube.com" in parsed.hostname:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
            if candidate:
                return candidate
        match = _EMBED_PATH.match(parsed.path)
        if match:
            return match.group(2)
    return cleaned


def select_track(
    tracks: list[TrackInfo],
    preferred: tuple[str, ...] = DEFAULT_PREFERRED,
) -> TrackInfo:
    """Choose the best caption track, preferring manual English.

    Priority order: a manual track in ``preferred`` language order, then a
    generated track in ``preferred`` order, then any manual track, then any
    generated track.

    Parameters
    ----------
    tracks
        The available caption tracks.
    preferred
        Language codes in descending preference. A track whose code starts
        with a preferred code (case-insensitive) matches.

    Returns
    -------
    TrackInfo
        The selected track.

    Raises
    ------
    ValueError
        If ``tracks`` is empty.
    """
    if not tracks:
        raise ValueError("no caption tracks available")

    def matches(track: TrackInfo, code: str) -> bool:
        return track.language_code.lower().startswith(code.lower())

    for want_generated in (False, True):
        for code in preferred:
            for track in tracks:
                if track.is_generated == want_generated and matches(track, code):
                    return track
    for track in tracks:
        if not track.is_generated:
            return track
    return tracks[0]


def format_transcript(snippets: list[tuple[float, str]]) -> str:
    """Format ``(start_seconds, text)`` snippets as timestamped-plain lines.

    Parameters
    ----------
    snippets
        Ordered ``(start, text)`` pairs, ``start`` in seconds.

    Returns
    -------
    str
        Newline-joined ``[HH:MM:SS] text`` lines with intra-snippet newlines
        flattened to spaces.

    Raises
    ------
    ValueError
        If ``snippets`` is empty.
    """
    if not snippets:
        raise ValueError("transcript has no snippets")

    lines: list[str] = []
    for start, text in snippets:
        hours, remainder = divmod(int(start), 3600)
        minutes, seconds = divmod(remainder, 60)
        flattened = " ".join(text.split())
        lines.append(f"[{hours:02d}:{minutes:02d}:{seconds:02d}] {flattened}")
    return "\n".join(lines)


def fetch_transcript(
    video_id: str,
    preferred: tuple[str, ...] = DEFAULT_PREFERRED,
) -> tuple[str, TrackInfo]:
    """Fetch and format a video's transcript from the network.

    Imports ``youtube_transcript_api`` lazily so this module's pure helpers can
    be imported and tested without the dependency installed.

    Parameters
    ----------
    video_id
        The YouTube video id.
    preferred
        Preferred caption language codes, most preferred first.

    Returns
    -------
    tuple[str, TrackInfo]
        The formatted timestamped-plain transcript and the chosen track.

    Raises
    ------
    RuntimeError
        If captions are unavailable, the video is private/unavailable, or a
        network error occurs. The original error message is preserved.
    """
    from youtube_transcript_api import YouTubeTranscriptApi  # noqa: PLC0415

    api = YouTubeTranscriptApi()
    try:
        listing = api.list(video_id)
        available = [
            TrackInfo(language_code=t.language_code, is_generated=t.is_generated)
            for t in listing
        ]
        chosen = select_track(available, preferred)
        fetched = listing.find_transcript([chosen.language_code]).fetch()
    except Exception as exc:  # noqa: BLE001 — surface any api/network failure verbatim
        raise RuntimeError(f"could not fetch transcript for {video_id}: {exc}") from exc

    snippets = [(snippet.start, snippet.text) for snippet in fetched]
    return format_transcript(snippets), chosen


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments for the CLI entry point."""
    parser = argparse.ArgumentParser(description="Fetch a YouTube transcript.")
    parser.add_argument("url", help="YouTube URL or bare video id.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to write the transcript.")
    parser.add_argument(
        "-l",
        "--language",
        action="append",
        help="Preferred caption language code(s); repeatable, most preferred first.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the fetcher as a CLI, returning a process exit code."""
    args = _parse_args(argv)
    try:
        video_id = extract_video_id(args.url)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    preferred = tuple(args.language) if args.language else DEFAULT_PREFERRED
    try:
        transcript, track = fetch_transcript(video_id, preferred)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.output.write_text(transcript + "\n", encoding="utf-8")
    kind = "generated" if track.is_generated else "manual"
    print(f"Saved transcript to {args.output}")
    print(f"video_id={video_id} track={track.language_code} ({kind})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
