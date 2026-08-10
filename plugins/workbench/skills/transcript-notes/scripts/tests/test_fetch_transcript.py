"""Tests for the YouTube transcript fetcher's offline logic.

Only the pure, network-free pieces are exercised here: video-id extraction,
English-preferred track selection, and the ``[HH:MM:SS]`` line formatting. The
live fetch (which imports ``youtube_transcript_api`` lazily) is never called in
CI, so the module must import without that dependency installed.
"""

import pytest

from fetch_transcript import (
    TrackInfo,
    extract_video_id,
    format_transcript,
    select_track,
)


class TestExtractVideoId:
    """Video-id extraction across YouTube URL shapes and bare ids."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=ROEad3SDI9Q",
            "https://youtu.be/ROEad3SDI9Q",
            "https://www.youtube.com/embed/ROEad3SDI9Q",
            "https://www.youtube.com/shorts/ROEad3SDI9Q",
            "https://www.youtube.com/live/ROEad3SDI9Q",
            "https://youtube.com/watch?v=ROEad3SDI9Q&t=42s",
        ],
    )
    def test_extracts_id_from_url_forms(self, url):
        assert extract_video_id(url) == "ROEad3SDI9Q"

    def test_bare_id_passes_through(self):
        assert extract_video_id("ROEad3SDI9Q") == "ROEad3SDI9Q"

    def test_surrounding_whitespace_trimmed(self):
        assert extract_video_id("  ROEad3SDI9Q\n") == "ROEad3SDI9Q"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            extract_video_id("   ")


class TestSelectTrack:
    """English-preferred selection with graceful fallback."""

    def test_prefers_manual_english_over_generated_english(self):
        tracks = [
            TrackInfo("en", is_generated=True),
            TrackInfo("en", is_generated=False),
        ]
        assert select_track(tracks) == TrackInfo("en", is_generated=False)

    def test_generated_english_when_no_manual(self):
        tracks = [
            TrackInfo("fr", is_generated=False),
            TrackInfo("en", is_generated=True),
        ]
        assert select_track(tracks) == TrackInfo("en", is_generated=True)

    def test_falls_back_to_any_manual_when_no_english(self):
        tracks = [
            TrackInfo("de", is_generated=True),
            TrackInfo("fr", is_generated=False),
        ]
        assert select_track(tracks) == TrackInfo("fr", is_generated=False)

    def test_falls_back_to_any_generated_last(self):
        tracks = [TrackInfo("de", is_generated=True)]
        assert select_track(tracks) == TrackInfo("de", is_generated=True)

    def test_honors_custom_preferred_language(self):
        tracks = [
            TrackInfo("en", is_generated=False),
            TrackInfo("es", is_generated=False),
        ]
        assert select_track(tracks, preferred=("es",)) == TrackInfo("es", is_generated=False)

    def test_no_tracks_raises(self):
        with pytest.raises(ValueError):
            select_track([])


class TestFormatTranscript:
    """Snippet formatting into timestamped-plain lines the cleaner accepts."""

    def test_formats_hms_prefix(self):
        lines = format_transcript([(0.0, "hello there"), (5.4, "general kenobi")])
        assert lines == "[00:00:00] hello there\n[00:00:05] general kenobi"

    def test_rolls_over_into_hours(self):
        lines = format_transcript([(3661.0, "an hour in")])
        assert lines == "[01:01:01] an hour in"

    def test_collapses_internal_newlines_in_snippet(self):
        lines = format_transcript([(0.0, "line one\nline two")])
        assert lines == "[00:00:00] line one line two"

    def test_empty_snippets_raises(self):
        with pytest.raises(ValueError):
            format_transcript([])


def test_module_imports_without_youtube_dependency():
    """The module must import even when youtube_transcript_api is absent."""
    import fetch_transcript

    assert hasattr(fetch_transcript, "fetch_transcript")
