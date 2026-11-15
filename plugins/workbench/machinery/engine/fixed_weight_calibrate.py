#!/usr/bin/env python3
"""fixed_weight_calibrate — turn matched fresh sessions into the calibration factor.

Two arms of fresh sessions run the same one-line prompt: ``full`` (the whole setup) and
``bare`` (the workbench plugin disabled). The first API call of a fresh session sends
the fixed context and little else, so the measured token difference between a full and
a bare session is the true weight of what the plugin adds. The estimator predicts that
same difference from characters; the ratio of the two sums is the factor
``cost_ledger.py --fixed-weight`` multiplies its token estimates by.

Usage:
    python3 fixed_weight_calibrate.py --full ID [ID ...] --bare ID [ID ...]
        [--projects-root DIR] [--out PATH] [--min-runs N]
        [--claude-code-version V] [--date YYYY-MM-DD]

Pair i is the i-th id of ``--full`` with the i-th of ``--bare``. All transcript reading
goes through ``transcript_reader.read``; this module opens no transcript file. The factor
file carries numbers, a date and a version string only: no session id, project key or
path. A refusal exits 2 with one stderr line, names an id only by its position in its arm
(``full[2]``, counted from 1), and writes nothing.

Stdlib only; imports ``cost_ledger``, ``fixed_weight`` and ``transcript_reader``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

import cost_ledger
import fixed_weight
import transcript_reader

DEFAULT_MIN_RUNS = 5
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class Refusal(Exception):
    """A calibration that cannot be made; the message is the one stderr line."""


@dataclass
class _Session:
    """What one wanted main file shows: where it is, its first call, its sizes, versions."""

    projects: set[str] = field(default_factory=set)
    measured: int | None = None
    versions: set[str] = field(default_factory=set)
    sizes: fixed_weight.Collector = field(default_factory=fixed_weight.Collector)


class _Hook:
    """The ``on_record`` hook: sees every record, keeps only what main files of wanted ids need."""

    def __init__(self, wanted: set[str]) -> None:
        self.wanted = wanted
        self.sessions: dict[tuple[str, str], _Session] = {}
        self._first_call: set[tuple[str, str]] = set()

    def __call__(self, info: transcript_reader.FileInfo, rec: dict) -> None:
        if info.is_subagent or info.session_id not in self.wanted:
            return
        key = (info.project, info.session_id)
        state = self.sessions.setdefault(key, _Session())
        state.projects.add(info.project)
        state.sizes(info, rec)
        version = rec.get("version")
        if isinstance(version, str) and version:
            state.versions.add(version)
        if key not in self._first_call:
            call = transcript_reader.CallCollector().add(info, rec)
            if call is not None:
                self._first_call.add(key)
                state.measured = (
                    call.input_tokens + call.cache_write_tokens + call.cache_read_tokens
                )


def _parse_date(text: str) -> str:
    if not _DAY.fullmatch(text):
        raise Refusal("--date must be YYYY-MM-DD")
    try:
        _date.fromisoformat(text)
    except ValueError:
        raise Refusal("--date must be a real calendar day") from None
    return text


def _check_arms(full: list[str], bare: list[str], min_runs: int) -> None:
    if min_runs < 2:
        raise Refusal("--min-runs must be at least 2")
    if len(full) != len(bare):
        raise Refusal(f"the arms differ in size: {len(full)} full, {len(bare)} bare")
    if len(full) < min_runs:
        raise Refusal(f"{len(full)} runs per arm; at least {min_runs} are needed (--min-runs)")
    seen: dict[str, str] = {}
    for name, ids in (("full", full), ("bare", bare)):
        for pos, sid in enumerate(ids, start=1):
            if sid in seen:
                raise Refusal(f"{name}[{pos}] repeats {seen[sid]}: an id may be given once")
            seen[sid] = f"{name}[{pos}]"


def _fixed_tokens(state: _Session) -> tuple[float, bool]:
    """Predicted fixed tokens of the one main file in ``state`` and whether it had a snapshot."""
    (sizes,) = state.sizes.files.values()
    return fixed_weight.total_fixed_tokens(sizes, factor=1.0), sizes.has_snapshot


def _round(x: float, places: int = 6) -> float:
    return round(x, places)


def calibrate(
    root: Path,
    full: list[str],
    bare: list[str],
    *,
    min_runs: int = DEFAULT_MIN_RUNS,
    claude_code_version: str | None = None,
    day: str,
) -> dict:
    """The factor-file object for the two arms, or raise ``Refusal``."""
    _check_arms(full, bare, min_runs)
    hook = _Hook(set(full) | set(bare))
    transcript_reader.read(Path(root), on_record=hook)

    found: dict[tuple[str, int], _Session] = {}
    for arm, ids in (("full", full), ("bare", bare)):
        for pos, sid in enumerate(ids, start=1):
            matches = [s for (_, s_id), s in hook.sessions.items() if s_id == sid]
            if not matches:
                raise Refusal(f"{arm}[{pos}] matches no main session file")
            if len(matches) > 1:
                raise Refusal(f"{arm}[{pos}] matches main session files in more than one project")
            if matches[0].measured is None:
                raise Refusal(f"{arm}[{pos}] has no assistant call with usable usage")
            found[(arm, pos)] = matches[0]

    measured, predicted, without_snapshot = [], [], 0
    for pos in range(1, len(full) + 1):
        tokens = {}
        for arm in ("full", "bare"):
            state = found[(arm, pos)]
            fixed, has_snapshot = _fixed_tokens(state)
            tokens[arm] = (state.measured, fixed)
            without_snapshot += 0 if has_snapshot else 1
        measured.append(tokens["full"][0] - tokens["bare"][0])
        predicted.append(tokens["full"][1] - tokens["bare"][1])

    if any(p <= 0 for p in predicted):
        raise Refusal("a pair predicts no more fixed tokens in full than in bare; check the arms")
    if sum(measured) <= 0:
        raise Refusal("the full arm measured no more tokens than the bare arm")
    ratios = [m / p for m, p in zip(measured, predicted)]

    versions = set().union(*(s.versions for s in found.values()))
    if len(versions) > 1:
        raise Refusal("the sessions record more than one Claude Code version; use one version")
    recorded = next(iter(versions), None)
    if recorded is None:
        if not claude_code_version:
            raise Refusal("no session records a Claude Code version; pass --claude-code-version")
        version = claude_code_version
    elif claude_code_version and claude_code_version != recorded:
        raise Refusal("--claude-code-version differs from the version the sessions record")
    else:
        version = recorded
    if not fixed_weight.valid_version(version):
        raise Refusal("the Claude Code version must be letters, digits and . _ + - only")

    return {
        "factor": _round(sum(measured) / sum(predicted)),
        "low": _round(min(ratios)),
        "high": _round(max(ratios)),
        "runs_per_arm": len(full),
        "date": day,
        "claude_code_version": version,
        "chars_per_token": fixed_weight.CHARS_PER_TOKEN,
        "measured_tokens_diff": {
            "mean": _round(statistics.fmean(measured), 3),
            "min": _round(float(min(measured)), 3),
            "max": _round(float(max(measured)), 3),
            "stdev": _round(statistics.stdev(measured), 3),
        },
        "predicted_tokens_diff": {
            "mean": _round(statistics.fmean(predicted), 3),
            "min": _round(min(predicted), 3),
            "max": _round(max(predicted), 3),
        },
        "sessions_without_snapshot": without_snapshot,
    }


def dumps(obj: dict) -> str:
    """The factor file text: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2) + "\n"


def _write_whole(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` all or nothing: a temp file beside it, then a rename."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def summary(obj: dict, out: Path) -> str:
    m, p = obj["measured_tokens_diff"], obj["predicted_tokens_diff"]
    return (
        f"runs per arm: {obj['runs_per_arm']}\n"
        f"Claude Code version: {obj['claude_code_version']}\n"
        f"mean measured token difference: {m['mean']:.3f}\n"
        f"mean predicted token difference: {p['mean']:.3f}\n"
        f"calibration factor: {obj['factor']:.6f} "
        f"(low {obj['low']:.6f}, high {obj['high']:.6f})\n"
        f"sessions without a snapshot: {obj['sessions_without_snapshot']}\n"
        f"wrote {out}\n"
    )


def main(argv: list[str] | None = None, *, today: _date | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calibrate the fixed-weight estimator.")
    ap.add_argument("--full", nargs="+", required=True, metavar="ID", help="session ids of the full arm")
    ap.add_argument("--bare", nargs="+", required=True, metavar="ID", help="session ids of the bare arm")
    ap.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--out", default=None, metavar="PATH", help="factor file (default: the estimator's)")
    ap.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS, metavar="N")
    ap.add_argument("--claude-code-version", default=None, metavar="V")
    ap.add_argument("--date", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)
    try:
        day = _parse_date(args.date) if args.date is not None else (today or _date.today()).isoformat()
        root = Path(args.projects_root)
        if not root.is_dir():
            raise Refusal("--projects-root is not a directory")
        out = Path(args.out) if args.out is not None else cost_ledger.default_calibration_path()
        obj = calibrate(
            root, args.full, args.bare,
            min_runs=args.min_runs, claude_code_version=args.claude_code_version, day=day,
        )
        if not all(math.isfinite(obj[k]) for k in ("factor", "low", "high")):
            raise Refusal("the factor is not a finite number")
        try:
            _write_whole(out, dumps(obj))
        except OSError as exc:
            raise Refusal(f"cannot write the factor file: {exc.strerror or exc}") from None
    except Refusal as exc:
        print(f"fixed_weight_calibrate: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(summary(obj, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
