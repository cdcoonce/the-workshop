#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["edge-tts"]
# ///
"""Render a two-voice podcast episode from a plain-text script.

Pipeline: PARSE (script.txt) -> PREFLIGHT (path/sensitivity safety,
afconvert-on-PATH check, clear stale intermediates) -> SYNTH (serial,
paced, retried edge-tts calls) -> CONVERT (afconvert mp3 -> wav per turn)
-> STITCH (pure-Python wav concat, silence injected for PAUSE) -> VERIFY
(silent-truncation guard) -> FINALIZE (wav -> m4a, atomic rename,
meta.json).

``synthesize_turn`` and ``convert_audio`` are the only functions that touch
the network or a subprocess; everything else is pure Python over stdlib
``wave``. ``edge_tts`` is imported lazily, inside ``synthesize_turn`` only,
so this module stays importable without the package installed.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NamedTuple

RENDERER_VERSION = "0.1.0"
WORDS_PER_MINUTE = 150
MAX_TURNS = 200
PAUSE_MIN_SECONDS = 0.5
PAUSE_MAX_SECONDS = 10.0
SYNTH_MAX_ATTEMPTS = 3
SYNTH_BACKOFF_SECONDS = (1.0, 2.0)
SYNTH_PACING_SECONDS = 0.5
VERIFY_MIN_RATIO = 0.5
SENSITIVE_COMPONENTS = frozenset({"work", "perf", "therapy"})
SLUG_RE = re.compile(r"^(?:[0-9]{4}-)?[a-z0-9-]+$")
AFCONVERT_WAV_ARGS = ("-f", "WAVE", "-d", "LEI16@24000", "-c", "1")
AFCONVERT_M4A_ARGS = ("-f", "m4af", "-d", "aac")

# Exceptions. Each carries the exit code main() reports it with:
#   ScriptFormatError=2  SynthesisError=3  ConversionError/StitchError=4
#   PlatformError=5  VerificationError=6  EnvironmentSetupError=7
#   SensitiveSourceError=8

class RenderError(Exception):
    """Base for every failure render.py knows how to name and exit on."""

    exit_code = 1

class ScriptFormatError(RenderError):
    """script.txt missing/empty/malformed, unknown speaker, bad PAUSE, >200 turns."""

    exit_code = 2

class SynthesisError(RenderError):
    """A turn is still failing after retries."""

    exit_code = 3

class ConversionError(RenderError):
    """afconvert exited non-zero."""

    exit_code = 4

class StitchError(RenderError):
    """WAV segments disagree on framerate/channels/sampwidth."""

    exit_code = 4

class PlatformError(RenderError):
    """afconvert is not on PATH (this tool is macOS-only)."""

    exit_code = 5

class VerificationError(RenderError):
    """Stitched duration is suspiciously short — a silent-truncation guard."""

    exit_code = 6

class EnvironmentSetupError(RenderError):
    """edge-tts could not be imported at synth time."""

    exit_code = 7

class SensitiveSourceError(RenderError):
    """A --source path touches a sensitive vault area without --allow-sensitive."""

    exit_code = 8

@dataclass(frozen=True)
class SpeechTurn:
    index: int
    speaker: str
    text: str
    line_no: int

@dataclass(frozen=True)
class PauseEntry:
    seconds: float
    line_no: int

ScriptEntry = SpeechTurn | PauseEntry

@dataclass(frozen=True)
class SpeechSegment:
    turn_index: int
    wav_path: Path

@dataclass(frozen=True)
class PauseSegment:
    seconds: float

StitchItem = SpeechSegment | PauseSegment

class WavParams(NamedTuple):
    nchannels: int
    sampwidth: int
    framerate: int

# PARSE — one entry per non-blank line: "SPEAKER|text" or "PAUSE|<seconds>".

def parse_script(text: str, speakers: frozenset[str]) -> list[ScriptEntry]:
    """Parse script.txt content; raises ScriptFormatError naming the bad line."""
    if not text.strip():
        raise ScriptFormatError("script.txt is empty")

    entries: list[ScriptEntry] = []
    turn_count = 0
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        entry, turn_count = _parse_line(raw_line, line, line_no, speakers, turn_count)
        entries.append(entry)

    if turn_count == 0:
        raise ScriptFormatError("script.txt has no speaker turns")
    return entries

def _parse_line(
    raw_line: str, line: str, line_no: int, speakers: frozenset[str], turn_count: int
) -> tuple[ScriptEntry, int]:
    if "|" not in line:
        raise ScriptFormatError(f"line {line_no}: missing '|' separator: {raw_line!r}")

    speaker, _, payload = line.partition("|")
    payload = payload.strip()

    if speaker == "PAUSE":
        return PauseEntry(_parse_pause_seconds(payload, line_no), line_no), turn_count

    if speaker not in speakers:
        raise ScriptFormatError(f"line {line_no}: unknown speaker {speaker!r}: {raw_line!r}")

    turn_count += 1
    if turn_count > MAX_TURNS:
        raise ScriptFormatError(f"line {line_no}: exceeds max {MAX_TURNS} turns: {raw_line!r}")
    return SpeechTurn(turn_count - 1, speaker, payload, line_no), turn_count

def _parse_pause_seconds(payload: str, line_no: int) -> float:
    try:
        seconds = float(payload)
    except ValueError as exc:
        raise ScriptFormatError(f"line {line_no}: bad PAUSE value {payload!r}") from exc
    return min(max(seconds, PAUSE_MIN_SECONDS), PAUSE_MAX_SECONDS)

def load_entries(episode_dir: Path, speakers: frozenset[str]) -> list[ScriptEntry]:
    script_path = episode_dir / "script.txt"
    if not script_path.exists():
        raise ScriptFormatError(f"missing script.txt: {script_path}")
    return parse_script(script_path.read_text(encoding="utf-8"), speakers)

def expected_seconds(entries: list[ScriptEntry]) -> float:
    """Expected speaking time: total words at WORDS_PER_MINUTE, plus pauses."""
    words = sum(len(e.text.split()) for e in entries if isinstance(e, SpeechTurn))
    pauses = sum(e.seconds for e in entries if isinstance(e, PauseEntry))
    return (words / WORDS_PER_MINUTE) * 60.0 + pauses

# Path / slug / sensitivity safety

def validate_episode_slug(episode_dir: Path) -> None:
    if ".." in episode_dir.parts:
        raise ScriptFormatError(f"episode-dir contains '..': {episode_dir}")
    if not SLUG_RE.match(episode_dir.name):
        raise ScriptFormatError(f"episode-dir basename is not a valid slug: {episode_dir.name!r}")

def validate_source_path(source: str) -> None:
    if ".." in Path(source).parts:
        raise ScriptFormatError(f"--source contains '..': {source}")

def check_sensitive_source(source: str, *, allow_sensitive: bool) -> None:
    if allow_sensitive:
        return
    hit = set(Path(source).parts) & SENSITIVE_COMPONENTS
    if hit:
        raise SensitiveSourceError(
            f"--source {source!r} touches sensitive area {sorted(hit)}; episode text is "
            "transmitted to Microsoft's TTS endpoint. Pass --allow-sensitive to proceed."
        )

def check_platform() -> None:
    """Preflight: afconvert must be on PATH before any synthesis work starts."""
    if shutil.which("afconvert") is None:
        raise PlatformError("afconvert not found on PATH (macOS-only tool)")

# SYNTH / CONVERT seams — the only functions that touch network or subprocess.

def synthesize_turn(text: str, voice: str, rate: str, out_path: Path) -> None:
    """Render one turn's speech to *out_path* via a lazily-imported edge-tts."""
    if importlib.util.find_spec("edge_tts") is None:
        raise EnvironmentSetupError(
            "edge-tts is not importable — network needed for first run to fetch the package"
        )
    import edge_tts

    async def _run() -> None:
        await edge_tts.Communicate(text, voice, rate=rate).save(str(out_path))

    asyncio.run(_run())

def convert_audio(src: Path, dst: Path, *afconvert_args: str) -> None:
    """Convert *src* to *dst* via afconvert. Never shell=True — an argv list only."""
    argv = ["afconvert", *afconvert_args, str(src), str(dst)]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ConversionError(f"afconvert failed on {src}: {result.stderr.strip()}")

def sleep_seconds(seconds: float) -> None:
    time.sleep(seconds)

def synthesize_with_retry(
    text: str, voice: str, rate: str, out_path: Path, *, turn_index: int, total: int
) -> None:
    """Retry transient synth failures with backoff.

    EnvironmentSetupError skips retries — a missing package won't fix itself,
    and retrying would mask exit code 7 behind 3. ``except Exception`` here is
    this module's one deliberate broad catch: a third-party synthesis
    boundary with no narrower contract to catch.
    """
    for attempt in range(SYNTH_MAX_ATTEMPTS):
        try:
            synthesize_turn(text, voice, rate, out_path)
            return
        except EnvironmentSetupError:
            raise
        except Exception as exc:
            if attempt == SYNTH_MAX_ATTEMPTS - 1:
                raise SynthesisError(
                    f"turn {turn_index} (voice {voice}) failed after "
                    f"{SYNTH_MAX_ATTEMPTS} attempts: {exc}"
                ) from exc
            sleep_seconds(SYNTH_BACKOFF_SECONDS[attempt])

def run_synthesis(
    entries: list[ScriptEntry], voices: dict[str, str], rate: str, segments_dir: Path
) -> list[StitchItem]:
    """SYNTH + CONVERT: turn each entry into a stitch-ready item, in order."""
    turns = [e for e in entries if isinstance(e, SpeechTurn)]
    total = len(turns)
    items: list[StitchItem] = []
    for entry in entries:
        if isinstance(entry, PauseEntry):
            items.append(PauseSegment(entry.seconds))
            continue
        if entry.index > 0:
            sleep_seconds(SYNTH_PACING_SECONDS)
        voice = voices[entry.speaker]
        print(f"[{entry.index + 1}/{total}] {entry.speaker} {voice}", file=sys.stderr)
        mp3_path = segments_dir / f"{entry.index:03d}.mp3"
        wav_path = segments_dir / f"{entry.index:03d}.wav"
        synthesize_with_retry(
            entry.text, voice, rate, mp3_path, turn_index=entry.index, total=total
        )
        convert_audio(mp3_path, wav_path, *AFCONVERT_WAV_ARGS)
        items.append(SpeechSegment(entry.index, wav_path))
    return items

# STITCH — pure Python, stdlib wave only.

def stitch_wavs(items: list[StitchItem], out_path: Path) -> int:
    """Concatenate WAV segments + PAUSE-injected silence; return total frames.

    Raises StitchError, naming the offending segment, on a framerate/
    channels/sampwidth mismatch against the segment that set the format.
    """
    params: WavParams | None = None
    frames_written = 0
    with wave.open(str(out_path), "wb") as out_wav:
        for item in items:
            if isinstance(item, SpeechSegment):
                params, n_frames = _stitch_speech(out_wav, item, params)
            else:
                params, n_frames = _stitch_pause(out_wav, item, params)
            frames_written += n_frames
    return frames_written

def _stitch_speech(
    out_wav: wave.Wave_write, item: SpeechSegment, params: WavParams | None
) -> tuple[WavParams, int]:
    with wave.open(str(item.wav_path), "rb") as seg:
        seg_params = WavParams(seg.getnchannels(), seg.getsampwidth(), seg.getframerate())
        if params is None:
            out_wav.setnchannels(seg_params.nchannels)
            out_wav.setsampwidth(seg_params.sampwidth)
            out_wav.setframerate(seg_params.framerate)
        elif seg_params != params:
            raise StitchError(
                f"{item.wav_path}: params {seg_params} do not match expected {params}"
            )
        n_frames = seg.getnframes()
        out_wav.writeframes(seg.readframes(n_frames))
    return seg_params, n_frames

def _stitch_pause(
    out_wav: wave.Wave_write, item: PauseSegment, params: WavParams | None
) -> tuple[WavParams, int]:
    if params is None:
        raise StitchError("PAUSE precedes any speech segment; no format reference yet")
    n_frames = round(item.seconds * params.framerate)
    out_wav.writeframes(b"\x00" * (n_frames * params.nchannels * params.sampwidth))
    return params, n_frames

# VERIFY — pure Python silent-truncation guard.

def verify_duration(stitched_path: Path, expected: float) -> float:
    with wave.open(str(stitched_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        framerate = wav_file.getframerate()
    duration = frames / framerate if framerate else 0.0
    if duration < VERIFY_MIN_RATIO * expected:
        raise VerificationError(
            f"stitched duration {duration:.1f}s is under "
            f"{VERIFY_MIN_RATIO:.0%} of expected {expected:.1f}s — a turn's audio may be missing"
        )
    return duration

# FINALIZE

def finalize(stitched_wav: Path, tmp_m4a: Path, final_m4a: Path) -> None:
    convert_audio(stitched_wav, tmp_m4a, *AFCONVERT_M4A_ARGS)
    tmp_m4a.rename(final_m4a)

def clear_stale_intermediates(segments_dir: Path, stitched_wav: Path, tmp_m4a: Path) -> None:
    """Remove any leftovers from an interrupted prior run. Never touches script.txt."""
    if segments_dir.exists():
        shutil.rmtree(segments_dir)
    if stitched_wav.exists():
        stitched_wav.unlink()
    if tmp_m4a.exists():
        tmp_m4a.unlink()

def write_meta(
    meta_path: Path,
    *,
    sources: list[str],
    style: str,
    voices: dict[str, str],
    rate: str,
    duration_seconds: float,
    entries: list[ScriptEntry],
) -> None:
    turns = [e for e in entries if isinstance(e, SpeechTurn)]
    pauses = [e for e in entries if isinstance(e, PauseEntry)]
    meta = {
        "sources": sources,
        "style": style,
        "voices": voices,
        "rate": rate,
        "duration_seconds": round(duration_seconds, 2),
        "words": sum(len(t.text.split()) for t in turns),
        "turns": len(turns),
        "pauses_seconds": round(sum(p.seconds for p in pauses), 2),
        "rendered": date.today().isoformat(),
        "renderer_version": RENDERER_VERSION,
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

# Orchestration

def render_episode(args: argparse.Namespace) -> None:
    episode_dir: Path = args.episode_dir
    validate_episode_slug(episode_dir)
    for source in args.sources:
        validate_source_path(source)
    for source in args.sources:
        check_sensitive_source(source, allow_sensitive=args.allow_sensitive)
    check_platform()

    speakers = frozenset(args.voices) | {"PAUSE"}
    entries = load_entries(episode_dir, speakers)

    segments_dir = episode_dir / ".render-segments"
    stitched_wav = episode_dir / ".render-stitched.wav"
    tmp_m4a = episode_dir / "episode.m4a.tmp"
    final_m4a = episode_dir / "episode.m4a"

    clear_stale_intermediates(segments_dir, stitched_wav, tmp_m4a)
    segments_dir.mkdir(parents=True, exist_ok=True)

    try:
        items = run_synthesis(entries, args.voices, args.rate, segments_dir)
        stitch_wavs(items, stitched_wav)
        duration = verify_duration(stitched_wav, expected_seconds(entries))
        finalize(stitched_wav, tmp_m4a, final_m4a)
    finally:
        clear_stale_intermediates(segments_dir, stitched_wav, tmp_m4a)

    write_meta(
        episode_dir / "meta.json",
        sources=args.sources,
        style=args.style,
        voices=args.voices,
        rate=args.rate,
        duration_seconds=duration,
        entries=entries,
    )

def _parse_voices_arg(spec: str) -> dict[str, str]:
    voices: dict[str, str] = {}
    for pair in spec.split(","):
        if "=" not in pair:
            raise argparse.ArgumentTypeError(f"bad --voices entry {pair!r}; expected SPEAKER=voice")
        speaker, _, voice = pair.partition("=")
        voices[speaker] = voice
    return voices

DEFAULT_VOICES_SPEC = "A=en-US-AndrewMultilingualNeural,B=en-US-AvaMultilingualNeural"


def _resolved_path(raw: str) -> Path:
    """Resolve before slug validation so `.` names its real directory."""
    return Path(raw).resolve()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a two-voice podcast episode.")
    parser.add_argument("episode_dir", type=_resolved_path)
    parser.add_argument("--source", dest="sources", action="append", default=[])
    parser.add_argument("--voices", type=_parse_voices_arg, default=DEFAULT_VOICES_SPEC)
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--style", default="")
    parser.add_argument("--allow-sensitive", action="store_true")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        render_episode(args)
    except RenderError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
