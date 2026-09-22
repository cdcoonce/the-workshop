"""Paired A/B measurement tool for the measure-before-landing skill.

Runs (or re-analyzes) two arms over the same case set, pairs their per-case
scores by key, and reports a paired Student-t bound plus an exact sign test
on the discordant pairs. Refuses -- exit code 2, "VOID: <reason>" on stderr
-- rather than reporting a number it cannot stand behind: a missing or
too-new pre-registration, a fixture that drifted between arms, a bracket
mismatch, or arms that disagree on which cases exist are all VOIDs, not
verdicts. See SKILL.md in this skill directory for the spec file and ledger
schema this tool reads and writes.
"""

from __future__ import annotations

import argparse
import json
import math
import shlex
import statistics
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Statistics core, ported VERBATIM (docstrings included) from kaggriculture's
# `harness.stats` module -- `regularized_incomplete_beta` through
# `sample_skewness` below. Trimmed only where a docstring referenced
# kaggriculture-specific machinery (the rerun-ledger, the promotion gate)
# that has no counterpart here; the math and the numbers are unchanged.
# ---------------------------------------------------------------------------


def regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta ``I_x(a, b)``.

    Numerical Recipes' modified Lentz continued fraction, with the standard
    symmetry swap ``I_x(a,b) = 1 - I_{1-x}(b,a)`` on the slow-converging side.
    Used only to invert the Student-t CDF; the whole path is deterministic
    for a given input, which keeps every downstream bound reproducible.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    log_prefactor = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(log_prefactor) * _beta_continued_fraction(a, b, x) / a
    mirror = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + b * math.log1p(-x) + a * math.log(x)
    )
    return 1.0 - math.exp(mirror) * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Lentz evaluation of the incomplete-beta continued fraction (``betacf``)."""
    tiny = 1e-30
    eps = 3e-16
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0

    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d

    for m in range(1, 201):
        m2 = 2 * m
        numerator = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c

        numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break

    return h


def student_t_ppf(p: float, df: int) -> float:
    """Quantile function of Student's t with ``df`` degrees of freedom.

    Inverted by EXACTLY 200 bisections on the fixed bracket ``[0, 1000]``,
    returning the midpoint. A fixed iteration count on a fixed bracket makes
    the result a deterministic function of ``(p, df)`` on any platform whose
    libm agrees, rather than a function of a convergence race.
    """
    if df < 1:
        raise ValueError(f"student_t_ppf needs df >= 1, got {df}")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -student_t_ppf(1.0 - p, df)

    low, high = 0.0, 1000.0
    for _ in range(200):
        mid = 0.5 * (low + high)
        if _student_t_cdf(mid, df) < p:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def _student_t_cdf(t: float, df: int) -> float:
    """CDF of Student's t at ``t >= 0``."""
    x = df / (df + t * t)
    return 1.0 - 0.5 * regularized_incomplete_beta(x, df / 2.0, 0.5)


def t_lower_bound(mean: float, sd: float, n: int, alpha: float = 0.05) -> float:
    """One-sided ``1 - alpha`` Student-t lower confidence bound on a mean.

    A zero-dispersion sample returns ``mean`` EXACTLY -- no multiplication by
    ``t_crit``, so the bound cannot pick up a last-ulp floating point
    artefact.
    """
    if sd == 0.0:
        return mean
    return mean - student_t_ppf(1.0 - alpha, n - 1) * sd / math.sqrt(n)


def mde_multiplier(n: int, alpha: float = 0.05, power: float = 0.80) -> float:
    """``t_{1-alpha, n-1} + t_{power, n-1}``: standard errors needed for ``power``.

    The n-dependent form of the textbook ``z_{1-alpha} + z_{power}``. The
    normal constant understates the requirement at every finite ``n`` -- at
    n=64 the z-sum is 2.486475 against a t-sum of 2.516766, a 1.22%
    understatement of the effect the run can actually resolve. ``inf`` below
    n=2, where there is no dispersion estimate at all.
    """
    if n < 2:
        return math.inf
    return student_t_ppf(1.0 - alpha, n - 1) + student_t_ppf(power, n - 1)


def sample_skewness(values: list[float]) -> float:
    """Adjusted Fisher-Pearson sample skewness ``g1 * n / ((n-1)(n-2))``.

    Reported as a diagnostic only; it is never part of a pass/fail rule.
    """
    n = len(values)
    if n < 3:
        return 0.0
    mean = sum(values) / n
    sd = statistics.stdev(values)
    if sd == 0.0:
        return 0.0
    return n / ((n - 1) * (n - 2)) * sum(((value - mean) / sd) ** 3 for value in values)


def sign_test_two_sided(n_positive: int, n_negative: int) -> float:
    """Exact two-sided binomial sign test over discordant pairs, p = 0.5."""
    n = n_positive + n_negative
    if n == 0:
        return 1.0
    m = min(n_positive, n_negative)
    tail = sum(math.comb(n, k) for k in range(0, m + 1)) / 2**n
    return min(1.0, 2 * tail)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseScore:
    """One case's score in one arm."""

    key: str
    score: float


@dataclass(frozen=True)
class PairedStats:
    """The full paired-comparison result for one A/B run."""

    n_paired: int
    n_discordant: int
    n_b_better: int
    n_a_better: int
    mean_a: float
    mean_b: float
    mean_delta: float  # b - a
    sd_delta: float
    stderr: float
    skew_delta: float
    sign_p: float
    ci_lower: float  # one-sided (1-alpha) t lower bound on mean_delta
    alpha: float
    power: float
    mde: float  # mde_multiplier(n, alpha, power) * stderr
    mde_estimator: str


def pair_scores(a: list[CaseScore], b: list[CaseScore]) -> list[tuple[str, float, float]]:
    """Pair per-case scores between two arms by key, in sorted-key order.

    Raises ``ValueError`` naming the symmetric difference if the two arms'
    case-key sets differ, or if either arm has a duplicate key.
    """
    a_map: dict[str, float] = {}
    for case in a:
        if case.key in a_map:
            raise ValueError(f"duplicate key '{case.key}' in arm a")
        a_map[case.key] = case.score

    b_map: dict[str, float] = {}
    for case in b:
        if case.key in b_map:
            raise ValueError(f"duplicate key '{case.key}' in arm b")
        b_map[case.key] = case.score

    a_keys = set(a_map)
    b_keys = set(b_map)
    if a_keys != b_keys:
        symmetric_difference = sorted(a_keys ^ b_keys)
        raise ValueError(
            "arms a and b have different case-key sets; "
            f"symmetric difference: {symmetric_difference}"
        )

    return [(key, a_map[key], b_map[key]) for key in sorted(a_keys)]


def analyze(
    pairs: list[tuple[str, float, float]],
    alpha: float = 0.05,
    power: float = 0.80,
) -> PairedStats:
    """Paired A/B analysis: sign test over discordant pairs plus a t bound on the mean delta."""
    n_paired = len(pairs)
    deltas = [b - a for _, a, b in pairs]

    mean_a = sum(a for _, a, _ in pairs) / n_paired if n_paired else 0.0
    mean_b = sum(b for _, _, b in pairs) / n_paired if n_paired else 0.0
    mean_delta = sum(deltas) / n_paired if n_paired else 0.0

    n_discordant = sum(1 for delta in deltas if delta != 0.0)
    n_b_better = sum(1 for delta in deltas if delta > 0.0)
    n_a_better = sum(1 for delta in deltas if delta < 0.0)

    if n_paired < 2:
        sd_delta = 0.0
        stderr = 0.0
        ci_lower = mean_delta
        mde = math.inf
    else:
        sd_delta = statistics.stdev(deltas)
        stderr = sd_delta / math.sqrt(n_paired)
        ci_lower = t_lower_bound(mean_delta, sd_delta, n_paired, alpha)
        mde = mde_multiplier(n_paired, alpha, power) * stderr

    return PairedStats(
        n_paired=n_paired,
        n_discordant=n_discordant,
        n_b_better=n_b_better,
        n_a_better=n_a_better,
        mean_a=mean_a,
        mean_b=mean_b,
        mean_delta=mean_delta,
        sd_delta=sd_delta,
        stderr=stderr,
        skew_delta=sample_skewness(deltas),
        sign_p=sign_test_two_sided(n_b_better, n_a_better),
        ci_lower=ci_lower,
        alpha=alpha,
        power=power,
        mde=mde,
        mde_estimator="mean paired delta at this n and the observed sd_delta",
    )


# ---------------------------------------------------------------------------
# Spec / arm / ledger plumbing
# ---------------------------------------------------------------------------


class VoidError(Exception):
    """Raised to signal a run that cannot be trusted -- exit code 2."""


def load_spec(path: Path) -> dict:
    """Load and parse a TOML measurement spec."""
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as exc:
        raise VoidError(f"could not read spec file '{path}': {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise VoidError(f"could not parse spec file '{path}': {exc}") from exc


def require_key(spec: dict, key: str) -> object:
    if key not in spec:
        raise VoidError(f"spec missing required key '{key}'")
    return spec[key]


def require_nested(section: dict, section_name: str, key: str) -> object:
    if key not in section:
        raise VoidError(f"spec missing required key '{section_name}.{key}'")
    return section[key]


def check_prereg(spec: dict, cwd: Path, start_time: float) -> tuple[str, float, Path]:
    """Validate the prereg doc exists and predates the run.

    Returns ``(evidence, recorded_at, resolved_path)``. ``evidence`` is
    ``"git-commit"`` when the file's git commit time was used, else
    ``"mtime"``. A failing or missing git falls back to mtime rather than
    crashing.
    """
    if "prereg" not in spec:
        raise VoidError("prereg key missing from spec")
    prereg_path = Path(spec["prereg"])
    if not prereg_path.is_absolute():
        prereg_path = cwd / prereg_path
    if not prereg_path.exists():
        raise VoidError(f"prereg file does not exist: {prereg_path}")

    evidence = "mtime"
    recorded_at = prereg_path.stat().st_mtime
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", str(prereg_path)],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            recorded_at = float(result.stdout.strip())
            evidence = "git-commit"
    except OSError:
        pass

    if recorded_at >= start_time:
        raise VoidError(
            "prereg is not older than the run start: "
            f"prereg_recorded_at={recorded_at} run_start={start_time}"
        )
    return evidence, recorded_at, prereg_path


def extract_cases(raw_json: str, cases_spec: dict, arm_name: str) -> list[CaseScore]:
    """Parse an arm's stdout as JSON and walk ``cases.path`` to a list of cases."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise VoidError(f"arm '{arm_name}' emitted unparseable JSON: {exc}") from exc

    path = require_nested(cases_spec, "cases", "path")
    obj = data
    if path:
        for segment in str(path).split("."):
            if not isinstance(obj, dict) or segment not in obj:
                raise VoidError(f"arm '{arm_name}' cases.path '{path}' does not resolve to a list")
            obj = obj[segment]
    if not isinstance(obj, list):
        raise VoidError(f"arm '{arm_name}' cases.path '{path}' does not resolve to a list")

    key_field = require_nested(cases_spec, "cases", "key")
    score_field = require_nested(cases_spec, "cases", "score")
    cases: list[CaseScore] = []
    for row in obj:
        try:
            cases.append(CaseScore(key=str(row[key_field]), score=float(row[score_field])))
        except (KeyError, TypeError, ValueError) as exc:
            raise VoidError(
                f"arm '{arm_name}' case row missing/invalid '{key_field}' or "
                f"'{score_field}': {exc}"
            ) from exc
    return cases


def run_arm(cmd: str, cwd: Path, arm_name: str) -> str:
    """Run one arm's command, returning its stdout. A nonzero exit is a VOID."""
    result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise VoidError(f"arm '{arm_name}' exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def _json_safe(obj: object) -> object:
    """Recursively replace non-finite floats with ``None`` so JSON stays valid."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {key: _json_safe(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(value) for value in obj]
    return obj


def write_ledger(out_dir: Path, label: str, ledger: dict, now: datetime) -> Path:
    """Write the ledger JSON to ``<out_dir>/<UTC timestamp>-<label>.json``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    path = out_dir / f"{timestamp}-{label}.json"
    with path.open("w") as f:
        json.dump(_json_safe(ledger), f, indent=2)
        f.write("\n")
    return path


def _finish(
    *,
    spec: dict,
    cwd: Path,
    cases_a: list[CaseScore],
    cases_b: list[CaseScore],
    arm_a_spec: dict,
    arm_b_spec: dict,
    bracket_enabled: bool,
    tolerance: float,
    mean_a2: float | None,
    fixture_cmd: str | None,
    captures: list[str],
    prereg_info: tuple[str, float, Path],
) -> int:
    """Pair, analyze, void-check the bracket, write the ledger, and pick an exit code."""
    try:
        pairs = pair_scores(cases_a, cases_b)
    except ValueError as exc:
        raise VoidError(str(exc)) from exc

    if len(pairs) < 1:
        raise VoidError("fewer than 1 paired case")

    alpha = spec.get("alpha", 0.05)
    power = spec.get("power", 0.80)
    stats = analyze(pairs, alpha=alpha, power=power)

    if bracket_enabled and mean_a2 is not None and abs(stats.mean_a - mean_a2) > tolerance:
        raise VoidError(
            f"bracket mean mismatch: mean_a={stats.mean_a} mean_a2={mean_a2} "
            f"tolerance={tolerance}"
        )

    evidence, recorded_at, prereg_path = prereg_info
    now = datetime.now(timezone.utc)
    threshold = spec.get("threshold")

    ledger: dict = {
        "schema_version": 1,
        "label": spec["label"],
        "metric": spec.get("metric"),
        "generated_at": now.isoformat(),
        "prereg": {
            "path": str(prereg_path),
            "evidence": evidence,
            "recorded_at": recorded_at,
        },
        "arms": {
            "a": {
                "label": arm_a_spec.get("label"),
                "cmd": arm_a_spec.get("cmd"),
                "mean": stats.mean_a,
            },
            "b": {
                "label": arm_b_spec.get("label"),
                "cmd": arm_b_spec.get("cmd"),
                "mean": stats.mean_b,
            },
        },
        "bracket": {
            "enabled": bracket_enabled,
            "mean_a2": mean_a2,
            "tolerance": tolerance,
        },
        "fixture": {
            "fingerprint_cmd": fixture_cmd,
            "captures": captures,
        },
        "stats": asdict(stats),
        "verdict": {
            "threshold": threshold,
            "rule": "ci_lower > threshold" if threshold is not None else None,
            "passed": (stats.ci_lower > threshold) if threshold is not None else None,
        },
        "pairs": [{"key": key, "a": a, "b": b, "delta": b - a} for key, a, b in pairs],
    }

    out_dir = Path(spec["out"])
    if not out_dir.is_absolute():
        out_dir = cwd / out_dir
    ledger_path = write_ledger(out_dir, spec["label"], ledger, now)

    print(ledger_path)
    print(
        f"n_paired={stats.n_paired} mean_delta={stats.mean_delta:.6g} "
        f"ci_lower={stats.ci_lower:.6g} sign_p={stats.sign_p:.6g}"
    )
    if threshold is None:
        return 0
    passed = stats.ci_lower > threshold
    print(f"verdict: {'PASS' if passed else 'FAIL'} (ci_lower > {threshold})")
    return 0 if passed else 1


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd) if args.cwd else Path.cwd()
    spec = load_spec(Path(args.spec))
    start_time = time.time()
    prereg_info = check_prereg(spec, cwd, start_time)

    require_key(spec, "out")
    require_key(spec, "label")
    cases_spec = require_key(spec, "cases")
    require_nested(cases_spec, "cases", "path")
    require_nested(cases_spec, "cases", "key")
    require_nested(cases_spec, "cases", "score")
    arms_spec = require_key(spec, "arms")
    arm_a_spec = require_nested(arms_spec, "arms", "a")
    arm_b_spec = require_nested(arms_spec, "arms", "b")
    cmd_a = require_nested(arm_a_spec, "arms.a", "cmd")
    cmd_b = require_nested(arm_b_spec, "arms.b", "cmd")

    fixture_cmd = spec.get("fixture", {}).get("fingerprint")
    bracket_cfg = spec.get("bracket", {})
    bracket_enabled = bracket_cfg.get("enabled", True)
    tolerance = bracket_cfg.get("tolerance", 0.0)

    captures: list[str] = []

    def fingerprint() -> None:
        if fixture_cmd:
            result = subprocess.run(
                shlex.split(fixture_cmd), capture_output=True, text=True, cwd=cwd
            )
            captures.append(result.stdout)

    fingerprint()
    stdout_a = run_arm(str(cmd_a), cwd, "a")
    fingerprint()
    stdout_b = run_arm(str(cmd_b), cwd, "b")
    fingerprint()

    mean_a2: float | None = None
    if bracket_enabled:
        stdout_a2 = run_arm(str(cmd_a), cwd, "a (bracket)")
        fingerprint()
        cases_a2 = extract_cases(stdout_a2, cases_spec, "a (bracket)")
        if not cases_a2:
            raise VoidError("arm 'a (bracket)' produced 0 cases")
        mean_a2 = sum(c.score for c in cases_a2) / len(cases_a2)

    if fixture_cmd and captures:
        first = captures[0]
        for other in captures[1:]:
            if other != first:
                raise VoidError(f"fixture fingerprint changed: {first!r} != {other!r}")

    cases_a = extract_cases(stdout_a, cases_spec, "a")
    cases_b = extract_cases(stdout_b, cases_spec, "b")

    return _finish(
        spec=spec,
        cwd=cwd,
        cases_a=cases_a,
        cases_b=cases_b,
        arm_a_spec=arm_a_spec,
        arm_b_spec=arm_b_spec,
        bracket_enabled=bracket_enabled,
        tolerance=tolerance,
        mean_a2=mean_a2,
        fixture_cmd=fixture_cmd,
        captures=captures,
        prereg_info=prereg_info,
    )


def cmd_analyze(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd) if args.cwd else Path.cwd()
    spec = load_spec(Path(args.spec))
    start_time = time.time()
    prereg_info = check_prereg(spec, cwd, start_time)

    require_key(spec, "out")
    require_key(spec, "label")
    cases_spec = require_key(spec, "cases")
    require_nested(cases_spec, "cases", "path")
    require_nested(cases_spec, "cases", "key")
    require_nested(cases_spec, "cases", "score")
    arms_spec = spec.get("arms", {})
    arm_a_spec = arms_spec.get("a", {})
    arm_b_spec = arms_spec.get("b", {})

    stdout_a = Path(args.a).read_text()
    stdout_b = Path(args.b).read_text()
    cases_a = extract_cases(stdout_a, cases_spec, "a")
    cases_b = extract_cases(stdout_b, cases_spec, "b")

    bracket_cfg = spec.get("bracket", {})
    bracket_enabled = bracket_cfg.get("enabled", True)
    tolerance = bracket_cfg.get("tolerance", 0.0)

    mean_a2: float | None = None
    if args.a2:
        stdout_a2 = Path(args.a2).read_text()
        cases_a2 = extract_cases(stdout_a2, cases_spec, "a2")
        if not cases_a2:
            raise VoidError("arm 'a2' produced 0 cases")
        mean_a2 = sum(c.score for c in cases_a2) / len(cases_a2)

    return _finish(
        spec=spec,
        cwd=cwd,
        cases_a=cases_a,
        cases_b=cases_b,
        arm_a_spec=arm_a_spec,
        arm_b_spec=arm_b_spec,
        bracket_enabled=bracket_enabled,
        tolerance=tolerance,
        mean_a2=mean_a2,
        fixture_cmd=None,
        captures=[],
        prereg_info=prereg_info,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paired_ab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run both arms and analyze them")
    run_parser.add_argument("--spec", required=True)
    run_parser.add_argument("--cwd", default=None)
    run_parser.set_defaults(func=cmd_run)

    analyze_parser = subparsers.add_parser("analyze", help="analyze already-saved arm output")
    analyze_parser.add_argument("--spec", required=True)
    analyze_parser.add_argument("--a", required=True)
    analyze_parser.add_argument("--b", required=True)
    analyze_parser.add_argument("--a2", default=None)
    analyze_parser.add_argument("--cwd", default=None)
    analyze_parser.set_defaults(func=cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except VoidError as exc:
        print(f"VOID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
