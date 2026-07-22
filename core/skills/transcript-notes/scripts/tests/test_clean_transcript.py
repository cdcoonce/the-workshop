"""Tests for the deterministic transcript cleaner.

The cleaner auto-detects the transcript format, strips cue metadata and
timestamps, removes YouTube's rolling-overlap duplication from caption-derived
formats, joins fragments into sentences, and reports size. Plain prose passes
through without the caption-specific overlap dedup.
"""

import pytest

from clean_transcript import (
    CleanResult,
    TranscriptFormat,
    clean_transcript,
    detect_format,
)

VTT_ROLLING = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
the quick brown

00:00:02.000 --> 00:00:04.000 align:start position:0%
the quick brown fox jumps

00:00:04.000 --> 00:00:06.000
fox jumps over the lazy dog.
"""

SRT_SIMPLE = """1
00:00:01,000 --> 00:00:04,000
Gradient descent is an

2
00:00:04,000 --> 00:00:07,000
optimization algorithm.
"""

TIMESTAMPED_PLAIN = """[00:00:00] softmax normalizes the
[00:00:02] softmax normalizes the scores
[00:00:04] into a probability distribution.
"""

PLAIN_PROSE = """Attention is all you need.
The transformer dispenses with recurrence entirely.
"""


class TestDetectFormat:
    """Format auto-detection across the four accepted shapes."""

    def test_detects_vtt_by_header(self):
        assert detect_format(VTT_ROLLING) is TranscriptFormat.VTT

    def test_detects_srt_by_index_and_comma_timing(self):
        assert detect_format(SRT_SIMPLE) is TranscriptFormat.SRT

    def test_detects_timestamped_plain(self):
        assert detect_format(TIMESTAMPED_PLAIN) is TranscriptFormat.TIMESTAMPED

    def test_detects_plain_prose(self):
        assert detect_format(PLAIN_PROSE) is TranscriptFormat.PLAIN


class TestCleanResultShape:
    """The result carries text plus size metadata and the detected format."""

    def test_returns_clean_result(self):
        result = clean_transcript(SRT_SIMPLE)
        assert isinstance(result, CleanResult)
        assert result.source_format is TranscriptFormat.SRT

    def test_word_count_counts_words(self):
        result = clean_transcript(PLAIN_PROSE)
        assert result.word_count == 11

    def test_estimated_minutes_uses_150_wpm(self):
        raw = "word " * 300
        result = clean_transcript(raw)
        assert result.estimated_minutes == 2

    def test_empty_input_raises(self):
        with pytest.raises(ValueError):
            clean_transcript("   \n  \n")


class TestMetadataStripping:
    """Timestamps, cue settings, indices, and headers never survive."""

    def test_vtt_header_and_timings_removed(self):
        text = clean_transcript(VTT_ROLLING).text
        assert "WEBVTT" not in text
        assert "-->" not in text
        assert "align:start" not in text
        assert "00:00:02" not in text

    def test_srt_indices_and_timings_removed(self):
        text = clean_transcript(SRT_SIMPLE).text
        assert "-->" not in text
        assert not any(line.strip() == "1" for line in text.splitlines())

    def test_timestamped_prefixes_removed(self):
        text = clean_transcript(TIMESTAMPED_PLAIN).text
        assert "[00:00:00]" not in text
        assert "00:00:02" not in text


class TestRollingOverlapDedup:
    """Caption formats collapse YouTube's rolling repetition; prose does not."""

    def test_vtt_rolling_overlap_collapsed(self):
        text = clean_transcript(VTT_ROLLING).text.lower()
        # The phrase "the quick brown" is repeated across cues; it should
        # appear once, not three times.
        assert text.count("the quick brown") == 1
        assert "fox jumps over the lazy dog" in text

    def test_timestamped_overlap_collapsed(self):
        text = clean_transcript(TIMESTAMPED_PLAIN).text.lower()
        assert text.count("softmax normalizes the") == 1
        assert "probability distribution" in text

    def test_plain_prose_not_overlap_merged(self):
        # Two distinct sentences that share no rolling overlap must both remain.
        text = clean_transcript(PLAIN_PROSE).text
        assert "Attention is all you need" in text
        assert "dispenses with recurrence" in text


class TestSentenceAssembly:
    """Fragments join into sentences ending at terminal punctuation."""

    def test_fragments_join_into_one_sentence(self):
        text = clean_transcript(SRT_SIMPLE).text
        assert "Gradient descent is an optimization algorithm." in text

    def test_no_orphaned_fragment_lines(self):
        # No output line should be a bare fragment with no terminal punctuation
        # when a following fragment completes it.
        lines = [ln for ln in clean_transcript(SRT_SIMPLE).text.splitlines() if ln.strip()]
        assert lines == ["Gradient descent is an optimization algorithm."]
