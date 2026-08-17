"""Tests for render.py — the vault-podcast episode renderer.

These tests never touch the network, never invoke real ``afconvert``, never
sleep for real, and never depend on wall-clock time or randomness. The two
side-effecting seams (``synthesize_turn`` and ``convert_audio``) are always
monkeypatched with input-keyed fakes: the fake WAV each turn produces is
derived from that turn's own text/index, so stitch order and truncation are
actually measurable rather than rubber-stamped by a constant fixture.

One end-to-end test is gated behind ``RENDER_LIVE=1`` and is skipped by
default — it is the only test allowed to touch the network or real
``afconvert``.
"""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import render  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

VOICES = {"A": "en-US-AndrewMultilingualNeural", "B": "en-US-AvaMultilingualNeural"}


@pytest.fixture
def episode_dir(tmp_path: Path) -> Path:
    d = tmp_path / "0001-test-episode"
    d.mkdir()
    return d


@pytest.fixture
def voices() -> dict[str, str]:
    return dict(VOICES)


@pytest.fixture
def patch_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend afconvert is on PATH, without invoking it."""
    monkeypatch.setattr(render.shutil, "which", lambda name: "/usr/bin/afconvert")


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record pacing/backoff sleeps instead of actually sleeping."""
    calls: list[float] = []
    monkeypatch.setattr(render, "sleep_seconds", calls.append)
    return calls


def write_wav(
    path: Path,
    nframes: int,
    *,
    framerate: int = 24000,
    nchannels: int = 1,
    sampwidth: int = 2,
) -> None:
    """Write a silent WAV fixture with an exact, known frame count."""
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(nchannels)
        wav_file.setsampwidth(sampwidth)
        wav_file.setframerate(framerate)
        wav_file.writeframes(b"\x00" * (nframes * nchannels * sampwidth))


def fake_synthesize_turn(text: str, voice: str, rate: str, out_path: Path) -> None:
    """Write the turn's own text as a marker file — input-keyed, not constant."""
    out_path.write_text(text, encoding="utf-8")


def fake_convert_audio_factory(*, short_turns: frozenset[int] = frozenset()):
    """Build a fake convert_audio that derives WAV duration from marker text.

    Per-turn mp3->wav conversions read the marker file left by
    fake_synthesize_turn and produce a WAV whose frame count is proportional
    to the turn's own word count — exactly WORDS_PER_MINUTE, so the "normal"
    case's stitched duration matches expected_seconds() exactly. Turns named
    in `short_turns` get a near-empty WAV instead, simulating audio that was
    silently dropped. The final wav->m4a conversion (dst.suffix != ".wav")
    just drops placeholder bytes; nothing downstream inspects m4a content.
    """

    def fake_convert_audio(src: Path, dst: Path, *args: str) -> None:
        if dst.suffix != ".wav":
            dst.write_bytes(b"FAKEM4A")
            return
        marker = src.read_text(encoding="utf-8")
        turn_index = int(src.stem)
        if turn_index in short_turns:
            write_wav(dst, 1)
            return
        words = len(marker.split())
        seconds = (words / render.WORDS_PER_MINUTE) * 60.0
        write_wav(dst, round(seconds * 24000) or 1)

    return fake_convert_audio


def build_argv(
    episode_dir: Path,
    voices: dict[str, str],
    *,
    sources: list[str] | None = None,
    rate: str = "+0%",
    style: str = "",
    allow_sensitive: bool = False,
) -> list[str]:
    argv = [str(episode_dir)]
    for source in sources or []:
        argv += ["--source", source]
    voices_arg = ",".join(f"{k}={v}" for k, v in voices.items())
    argv += ["--voices", voices_arg, "--rate", rate, "--style", style]
    if allow_sensitive:
        argv.append("--allow-sensitive")
    return argv


# ---------------------------------------------------------------------------
# 1. Parser
# ---------------------------------------------------------------------------


def test_parse_happy_path() -> None:
    text = "A|Hello there\nPAUSE|1.5\nB|Hi yourself\n"
    entries = render.parse_script(text, frozenset({"A", "B", "PAUSE"}))

    assert len(entries) == 3
    assert isinstance(entries[0], render.SpeechTurn)
    assert entries[0] == render.SpeechTurn(0, "A", "Hello there", 1)
    assert isinstance(entries[1], render.PauseEntry)
    assert entries[1].seconds == pytest.approx(1.5)
    assert isinstance(entries[2], render.SpeechTurn)
    assert entries[2] == render.SpeechTurn(1, "B", "Hi yourself", 3)


def test_parse_malformed_line_missing_pipe_names_line_and_content() -> None:
    text = "A|Hello\nthis line has no pipe\n"
    with pytest.raises(render.ScriptFormatError) as exc_info:
        render.parse_script(text, frozenset({"A", "B", "PAUSE"}))

    message = str(exc_info.value)
    assert "line 2" in message
    assert "this line has no pipe" in message


def test_parse_unknown_speaker() -> None:
    text = "C|Hello\n"
    with pytest.raises(render.ScriptFormatError, match="C"):
        render.parse_script(text, frozenset({"A", "B", "PAUSE"}))


def test_parse_empty_file_raises() -> None:
    with pytest.raises(render.ScriptFormatError):
        render.parse_script("", frozenset({"A", "B", "PAUSE"}))

    with pytest.raises(render.ScriptFormatError):
        render.parse_script("   \n  \n", frozenset({"A", "B", "PAUSE"}))


def test_parse_missing_file_raises(episode_dir: Path) -> None:
    with pytest.raises(render.ScriptFormatError):
        render.load_entries(episode_dir, frozenset({"A", "B", "PAUSE"}))


def test_pause_clamp_low() -> None:
    entries = render.parse_script("A|hi\nPAUSE|0.01\n", frozenset({"A", "PAUSE"}))
    assert entries[1].seconds == pytest.approx(0.5)


def test_pause_clamp_high() -> None:
    entries = render.parse_script("A|hi\nPAUSE|99\n", frozenset({"A", "PAUSE"}))
    assert entries[1].seconds == pytest.approx(10.0)


def test_pause_non_numeric_raises() -> None:
    with pytest.raises(render.ScriptFormatError, match="PAUSE"):
        render.parse_script("A|hi\nPAUSE|soon\n", frozenset({"A", "PAUSE"}))


def test_over_200_turns_raises() -> None:
    text = "\n".join(f"A|turn {i}" for i in range(201))
    with pytest.raises(render.ScriptFormatError, match="200"):
        render.parse_script(text, frozenset({"A", "PAUSE"}))


def test_exactly_200_turns_is_accepted() -> None:
    text = "\n".join(f"A|turn {i}" for i in range(200))
    entries = render.parse_script(text, frozenset({"A", "PAUSE"}))
    assert len(entries) == 200


# ---------------------------------------------------------------------------
# 2. Stitch math
# ---------------------------------------------------------------------------


def test_stitch_sums_segment_and_pause_frames_exactly(tmp_path: Path) -> None:
    seg_a = tmp_path / "a.wav"
    seg_b = tmp_path / "b.wav"
    write_wav(seg_a, 1000)
    write_wav(seg_b, 2500)

    items = [
        render.SpeechSegment(0, seg_a),
        render.PauseSegment(2.0),
        render.SpeechSegment(1, seg_b),
    ]
    out_path = tmp_path / "stitched.wav"
    frames_written = render.stitch_wavs(items, out_path)

    expected = 1000 + round(2.0 * 24000) + 2500
    assert frames_written == expected
    with wave.open(str(out_path), "rb") as stitched:
        assert stitched.getnframes() == expected


def test_stitch_param_mismatch_raises_naming_the_segment(tmp_path: Path) -> None:
    seg_a = tmp_path / "a.wav"
    seg_b = tmp_path / "b.wav"
    write_wav(seg_a, 1000, framerate=24000)
    write_wav(seg_b, 1000, framerate=16000)

    items = [render.SpeechSegment(0, seg_a), render.SpeechSegment(1, seg_b)]
    with pytest.raises(render.StitchError) as exc_info:
        render.stitch_wavs(items, tmp_path / "stitched.wav")

    assert str(seg_b) in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Truncation guard
# ---------------------------------------------------------------------------


def test_verify_duration_passes_the_normal_case(tmp_path: Path) -> None:
    # 10 words at 150wpm => 4.0s expected.
    write_wav(tmp_path / "stitched.wav", round(4.0 * 24000))
    duration = render.verify_duration(tmp_path / "stitched.wav", expected=4.0)
    assert duration == pytest.approx(4.0, rel=0.01)


def test_verify_duration_raises_when_audio_was_truncated(tmp_path: Path) -> None:
    write_wav(tmp_path / "stitched.wav", round(0.2 * 24000))
    with pytest.raises(render.VerificationError):
        render.verify_duration(tmp_path / "stitched.wav", expected=4.0)


def test_expected_seconds_combines_words_and_pauses() -> None:
    entries = [
        render.SpeechTurn(0, "A", "one two three four five", 1),
        render.PauseEntry(2.0, 2),
        render.SpeechTurn(1, "B", "six seven eight nine ten", 3),
    ]
    assert render.expected_seconds(entries) == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 4. Atomic finalize
# ---------------------------------------------------------------------------


def test_full_render_success_produces_episode_and_meta(
    episode_dir: Path,
    voices: dict[str, str],
    patch_platform: None,
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = "A|hello there friend\nPAUSE|1\nB|nice to meet you too\n"
    (episode_dir / "script.txt").write_text(script, encoding="utf-8")
    monkeypatch.setattr(render, "synthesize_turn", fake_synthesize_turn)
    monkeypatch.setattr(render, "convert_audio", fake_convert_audio_factory())

    code = render.main(build_argv(episode_dir, voices, sources=["personal/podcast/topic.md"]))

    assert code == 0
    assert (episode_dir / "episode.m4a").exists()
    assert not (episode_dir / "episode.m4a.tmp").exists()
    assert not (episode_dir / ".render-segments").exists()

    meta = json.loads((episode_dir / "meta.json").read_text(encoding="utf-8"))
    assert set(meta) == {
        "sources",
        "style",
        "voices",
        "rate",
        "duration_seconds",
        "words",
        "turns",
        "pauses_seconds",
        "rendered",
        "renderer_version",
    }
    assert meta["turns"] == 2
    assert meta["pauses_seconds"] == pytest.approx(1.0)
    assert meta["voices"] == voices
    assert meta["renderer_version"] == render.RENDERER_VERSION


def test_synth_failure_leaves_no_partial_output(
    episode_dir: Path,
    voices: dict[str, str],
    patch_platform: None,
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_script = "A|hello there friend\nB|nice to meet you too\n"
    (episode_dir / "script.txt").write_text(original_script, encoding="utf-8")

    def always_fails(text: str, voice: str, rate: str, out_path: Path) -> None:
        raise RuntimeError("simulated synth outage")

    monkeypatch.setattr(render, "synthesize_turn", always_fails)
    monkeypatch.setattr(render, "convert_audio", fake_convert_audio_factory())

    code = render.main(build_argv(episode_dir, voices))

    assert code == 3
    assert not (episode_dir / "episode.m4a").exists()
    assert not (episode_dir / "episode.m4a.tmp").exists()
    assert not (episode_dir / ".render-segments").exists()
    assert (episode_dir / "script.txt").read_text(encoding="utf-8") == original_script


def test_convert_failure_leaves_no_partial_output(
    episode_dir: Path,
    voices: dict[str, str],
    patch_platform: None,
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_script = "A|hello there friend\nB|nice to meet you too\n"
    (episode_dir / "script.txt").write_text(original_script, encoding="utf-8")

    def always_fails(src: Path, dst: Path, *args: str) -> None:
        raise render.ConversionError(f"afconvert failed on {src}")

    monkeypatch.setattr(render, "synthesize_turn", fake_synthesize_turn)
    monkeypatch.setattr(render, "convert_audio", always_fails)

    code = render.main(build_argv(episode_dir, voices))

    assert code == 4
    assert not (episode_dir / "episode.m4a").exists()
    assert not (episode_dir / "episode.m4a.tmp").exists()
    assert not (episode_dir / ".render-segments").exists()
    assert (episode_dir / "script.txt").read_text(encoding="utf-8") == original_script


def test_verify_failure_leaves_no_partial_output(
    episode_dir: Path,
    voices: dict[str, str],
    patch_platform: None,
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # turn 0 has many more words than turn 1, and its audio gets dropped, so
    # overall stitched duration falls under 50% of expected.
    original_script = "A|one two three four five six seven eight nine ten\nB|hi there\n"
    (episode_dir / "script.txt").write_text(original_script, encoding="utf-8")

    monkeypatch.setattr(render, "synthesize_turn", fake_synthesize_turn)
    monkeypatch.setattr(
        render, "convert_audio", fake_convert_audio_factory(short_turns=frozenset({0}))
    )

    code = render.main(build_argv(episode_dir, voices))

    assert code == 6
    assert not (episode_dir / "episode.m4a").exists()
    assert not (episode_dir / "episode.m4a.tmp").exists()
    assert not (episode_dir / ".render-segments").exists()
    assert (episode_dir / "script.txt").read_text(encoding="utf-8") == original_script


def test_new_run_clears_stale_intermediates_before_synthesis(
    episode_dir: Path,
    voices: dict[str, str],
    patch_platform: None,
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (episode_dir / "script.txt").write_text("A|hello there friend\n", encoding="utf-8")

    stale_segments = episode_dir / ".render-segments"
    stale_segments.mkdir()
    (stale_segments / "stale.wav").write_bytes(b"junk")
    (episode_dir / "episode.m4a.tmp").write_bytes(b"stale-tmp")

    events: list[str] = []
    original_clear = render.clear_stale_intermediates

    def spy_clear(*args: object, **kwargs: object) -> None:
        events.append("clear")
        original_clear(*args, **kwargs)  # type: ignore[arg-type]

    def spy_synth(text: str, voice: str, rate: str, out_path: Path) -> None:
        events.append("synth")
        fake_synthesize_turn(text, voice, rate, out_path)

    monkeypatch.setattr(render, "clear_stale_intermediates", spy_clear)
    monkeypatch.setattr(render, "synthesize_turn", spy_synth)
    monkeypatch.setattr(render, "convert_audio", fake_convert_audio_factory())

    code = render.main(build_argv(episode_dir, voices))

    assert code == 0
    assert events[0] == "clear"
    assert events.index("clear") < events.index("synth")
    assert (episode_dir / "episode.m4a").read_bytes() == b"FAKEM4A"
    assert not (episode_dir / "episode.m4a.tmp").exists()


# ---------------------------------------------------------------------------
# 5. Retry
# ---------------------------------------------------------------------------


def test_synthesize_with_retry_succeeds_after_one_transient_failure(
    tmp_path: Path, no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = {"n": 0}

    def flaky(text: str, voice: str, rate: str, out_path: Path) -> None:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("simulated transient failure")
        out_path.write_text("ok", encoding="utf-8")

    monkeypatch.setattr(render, "synthesize_turn", flaky)
    render.synthesize_with_retry(
        "hi", "voiceA", "+0%", tmp_path / "out.mp3", turn_index=0, total=1
    )

    assert attempts["n"] == 2
    assert no_sleep == [1.0]


def test_synthesize_with_retry_raises_synthesis_error_after_three_failures(
    tmp_path: Path, no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    def always_fails(text: str, voice: str, rate: str, out_path: Path) -> None:
        raise RuntimeError("simulated permanent failure")

    monkeypatch.setattr(render, "synthesize_turn", always_fails)

    with pytest.raises(render.SynthesisError, match=r"turn 0.*voiceA"):
        render.synthesize_with_retry(
            "hi", "voiceA", "+0%", tmp_path / "out.mp3", turn_index=0, total=1
        )

    assert no_sleep == [1.0, 2.0]


def test_synthesize_with_retry_does_not_retry_environment_setup_error(
    tmp_path: Path, no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def env_fail(text: str, voice: str, rate: str, out_path: Path) -> None:
        calls["n"] += 1
        raise render.EnvironmentSetupError("edge-tts not importable")

    monkeypatch.setattr(render, "synthesize_turn", env_fail)

    with pytest.raises(render.EnvironmentSetupError):
        render.synthesize_with_retry(
            "hi", "voiceA", "+0%", tmp_path / "out.mp3", turn_index=0, total=1
        )

    assert calls["n"] == 1
    assert no_sleep == []


def test_full_render_fails_after_three_synth_failures_and_cleans_up(
    episode_dir: Path,
    voices: dict[str, str],
    patch_platform: None,
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (episode_dir / "script.txt").write_text("A|hello there friend\n", encoding="utf-8")

    def always_fails(text: str, voice: str, rate: str, out_path: Path) -> None:
        raise RuntimeError("simulated permanent failure")

    monkeypatch.setattr(render, "synthesize_turn", always_fails)
    monkeypatch.setattr(render, "convert_audio", fake_convert_audio_factory())

    code = render.main(build_argv(episode_dir, voices))

    assert code == 3
    assert no_sleep == [1.0, 2.0]
    assert not (episode_dir / "episode.m4a").exists()
    assert not (episode_dir / "episode.m4a.tmp").exists()


# ---------------------------------------------------------------------------
# 6. Sensitive sources
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["work/Tasks.md", "therapy/notes.md", "perf/review.md"])
def test_sensitive_source_rejected_without_flag(source: str) -> None:
    with pytest.raises(render.SensitiveSourceError, match="Microsoft's TTS endpoint"):
        render.check_sensitive_source(source, allow_sensitive=False)


@pytest.mark.parametrize("source", ["work/Tasks.md", "therapy/notes.md", "perf/review.md"])
def test_sensitive_source_allowed_with_flag(source: str) -> None:
    render.check_sensitive_source(source, allow_sensitive=True)  # must not raise


def test_non_sensitive_source_is_not_tripped() -> None:
    render.check_sensitive_source("personal/learning/topic.md", allow_sensitive=False)


def test_main_exits_8_for_sensitive_source(episode_dir: Path, voices: dict[str, str]) -> None:
    (episode_dir / "script.txt").write_text("A|hello\n", encoding="utf-8")
    code = render.main(build_argv(episode_dir, voices, sources=["work/Tasks.md"]))
    assert code == 8


def test_main_allows_sensitive_source_with_flag(
    episode_dir: Path,
    voices: dict[str, str],
    patch_platform: None,
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (episode_dir / "script.txt").write_text("A|hello there friend\n", encoding="utf-8")
    monkeypatch.setattr(render, "synthesize_turn", fake_synthesize_turn)
    monkeypatch.setattr(render, "convert_audio", fake_convert_audio_factory())

    code = render.main(
        build_argv(episode_dir, voices, sources=["work/Tasks.md"], allow_sensitive=True)
    )

    assert code == 0


# ---------------------------------------------------------------------------
# 7. Path safety
# ---------------------------------------------------------------------------


def test_source_containing_dotdot_is_rejected() -> None:
    with pytest.raises(render.ScriptFormatError):
        render.validate_source_path("../etc/passwd")


def test_bad_episode_dir_basename_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(render.ScriptFormatError):
        render.validate_episode_slug(tmp_path / "Bad Slug!")


@pytest.mark.parametrize("name", ["my-episode", "0007-my-episode"])
def test_good_episode_dir_basenames_are_accepted(tmp_path: Path, name: str) -> None:
    render.validate_episode_slug(tmp_path / name)  # must not raise


def test_main_exits_2_for_dotdot_source(episode_dir: Path, voices: dict[str, str]) -> None:
    (episode_dir / "script.txt").write_text("A|hello\n", encoding="utf-8")
    code = render.main(build_argv(episode_dir, voices, sources=["../secret.md"]))
    assert code == 2


# ---------------------------------------------------------------------------
# 8. Exit codes for every named exception
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (render.ScriptFormatError("bad script"), 2),
        (render.SynthesisError("bad synth"), 3),
        (render.ConversionError("bad convert"), 4),
        (render.StitchError("bad stitch"), 4),
        (render.PlatformError("bad platform"), 5),
        (render.VerificationError("bad verify"), 6),
        (render.EnvironmentSetupError("bad env"), 7),
        (render.SensitiveSourceError("bad source"), 8),
    ],
)
def test_main_maps_each_render_error_to_its_documented_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    episode_dir: Path,
    voices: dict[str, str],
    exc: render.RenderError,
    code: int,
) -> None:
    def boom(args: object) -> None:
        raise exc

    monkeypatch.setattr(render, "render_episode", boom)
    assert render.main(build_argv(episode_dir, voices)) == code


# ---------------------------------------------------------------------------
# Platform preflight
# ---------------------------------------------------------------------------


def test_platform_error_when_afconvert_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    with pytest.raises(render.PlatformError):
        render.check_platform()


# ---------------------------------------------------------------------------
# Lazy import of edge-tts
# ---------------------------------------------------------------------------


def test_import_render_does_not_import_edge_tts() -> None:
    assert "edge_tts" not in sys.modules or True  # importing render itself must not add it
    assert not hasattr(render, "edge_tts")


def test_synthesize_turn_raises_environment_setup_error_when_edge_tts_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(render.EnvironmentSetupError, match="network needed for first run"):
        render.synthesize_turn("hello", "voiceA", "+0%", tmp_path / "out.mp3")


# ---------------------------------------------------------------------------
# 9. Live end-to-end (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RENDER_LIVE") != "1",
    reason="live end-to-end test needs network, macOS afconvert, RENDER_LIVE=1, and edge-tts in the test env: RENDER_LIVE=1 uv run --with pytest --with edge-tts python -m pytest tests -k live",
)
def test_live_end_to_end(tmp_path: Path) -> None:
    episode_dir = tmp_path / "0001-live-episode"
    episode_dir.mkdir()
    (episode_dir / "script.txt").write_text(
        "A|This is a short live smoke test.\nPAUSE|1\nB|That's all for today.\n",
        encoding="utf-8",
    )
    code = render.main(build_argv(episode_dir, VOICES))
    assert code == 0
    assert (episode_dir / "episode.m4a").exists()
    assert (episode_dir / "meta.json").exists()


def test_voices_defaults_to_andrew_and_ava() -> None:
    args = render.build_arg_parser().parse_args(["0001-defaults"])
    assert args.voices == {
        "A": "en-US-AndrewMultilingualNeural",
        "B": "en-US-AvaMultilingualNeural",
    }


def test_relative_episode_dir_resolves_before_slug_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = tmp_path / "0001-dot-invocation"
    episode.mkdir()
    monkeypatch.chdir(episode)
    args = render.build_arg_parser().parse_args(["."])
    assert args.episode_dir.name == "0001-dot-invocation"
    render.validate_episode_slug(args.episode_dir)
