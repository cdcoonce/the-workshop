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
    is_anchor_line,
)


def _timestamped(cues: list[tuple[int, str]]) -> str:
    """Build a ``[HH:MM:SS] text`` transcript from (start_seconds, text) cues."""
    lines = []
    for start, text in cues:
        h, rem = divmod(start, 3600)
        m, s = divmod(rem, 60)
        lines.append(f"[{h:02d}:{m:02d}:{s:02d}] {text}")
    return "\n".join(lines) + "\n"

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
        # when a following fragment completes it. Anchor lines are ignored here.
        lines = [
            ln
            for ln in clean_transcript(SRT_SIMPLE).text.splitlines()
            if ln.strip() and not is_anchor_line(ln)
        ]
        assert lines == ["Gradient descent is an optimization algorithm."]


class TestAnchorTimestamps:
    """Caption formats keep sparse [t=HH:MM:SS] anchors; plain prose has none."""

    def test_caption_format_emits_leading_anchor(self):
        text = clean_transcript(SRT_SIMPLE).text
        anchors = [ln for ln in text.splitlines() if is_anchor_line(ln)]
        assert anchors == ["[t=00:00:01]"]

    def test_timestamped_format_emits_anchor(self):
        text = clean_transcript(TIMESTAMPED_PLAIN).text
        assert any(is_anchor_line(ln) for ln in text.splitlines())

    def test_plain_prose_has_no_anchors(self):
        text = clean_transcript(PLAIN_PROSE).text
        assert not any(is_anchor_line(ln) for ln in text.splitlines())

    def test_anchor_precedes_its_sentence(self):
        lines = clean_transcript(SRT_SIMPLE).text.splitlines()
        assert lines[0] == "[t=00:00:01]"
        assert lines[1] == "Gradient descent is an optimization algorithm."

    def test_anchor_interval_controls_density(self):
        # Cues every 10s across 0..300s, each a distinct one-word sentence so
        # rolling-overlap dedup keeps them all.
        cues = [(t, f"seg{t // 10}.") for t in range(0, 301, 10)]
        raw = _timestamped(cues)
        coarse = clean_transcript(raw, anchor_interval_s=120).text
        fine = clean_transcript(raw, anchor_interval_s=60).text
        n_coarse = sum(is_anchor_line(ln) for ln in coarse.splitlines())
        n_fine = sum(is_anchor_line(ln) for ln in fine.splitlines())
        # 120s spacing over 300s → anchors at 0,120,240 (3); 60s → 0..300 (6).
        assert n_coarse == 3
        assert n_fine == 6
        assert n_fine > n_coarse

    def test_anchor_rolls_over_into_hours(self):
        text = clean_transcript(_timestamped([(3661, "an hour in.")])).text
        assert "[t=01:01:01]" in text

    def test_word_count_excludes_anchor_lines(self):
        # Two three-word sentences; the anchor must not inflate the count.
        raw = _timestamped([(0, "alpha beta gamma."), (200, "delta epsilon zeta.")])
        result = clean_transcript(raw)
        assert result.word_count == 6
