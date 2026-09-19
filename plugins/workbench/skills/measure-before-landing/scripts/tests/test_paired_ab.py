from __future__ import annotations

import json
import math
import os
import shlex
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from paired_ab import (  # noqa: E402
    CaseScore,
    analyze,
    main,
    mde_multiplier,
    pair_scores,
    sign_test_two_sided,
    student_t_ppf,
    t_lower_bound,
)


# ---------------------------------------------------------------------------
# Pure statistics: pinned values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n_pos", "n_neg", "expected"),
    [
        (3, 1, 0.625),
        (0, 0, 1.0),
        (5, 0, 0.0625),
        (1, 0, 1.0),
        (0, 5, 0.0625),
        (10, 0, 2 / 1024),
    ],
)
def test_sign_test_two_sided_pinned(n_pos, n_neg, expected):
    assert sign_test_two_sided(n_pos, n_neg) == pytest.approx(expected)


def test_mde_multiplier_pinned_at_64():
    assert mde_multiplier(64) == pytest.approx(2.516766, abs=1e-6)


def test_student_t_ppf_95_63_is_finite_and_above_1_6():
    value = student_t_ppf(0.95, 63)
    assert math.isfinite(value)
    assert value > 1.6


def test_student_t_ppf_median_is_zero():
    assert student_t_ppf(0.5, 10) == 0.0


def test_student_t_ppf_symmetric():
    assert student_t_ppf(0.05, 10) == -student_t_ppf(0.95, 10)


def test_t_lower_bound_zero_sd_returns_mean_exactly():
    assert t_lower_bound(3.75, 0.0, 12) == 3.75


# ---------------------------------------------------------------------------
# pair_scores
# ---------------------------------------------------------------------------


def test_pair_scores_raises_naming_missing_keys_on_mismatch():
    a = [CaseScore("q1", 1.0), CaseScore("q_a_only", 0.5)]
    b = [CaseScore("q1", 1.0), CaseScore("q_b_only", 0.5)]
    with pytest.raises(ValueError) as excinfo:
        pair_scores(a, b)
    message = str(excinfo.value)
    assert "q_a_only" in message
    assert "q_b_only" in message


def test_pair_scores_raises_on_duplicate_key():
    a = [CaseScore("q1", 1.0), CaseScore("q1", 2.0)]
    b = [CaseScore("q1", 1.0)]
    with pytest.raises(ValueError) as excinfo:
        pair_scores(a, b)
    assert "q1" in str(excinfo.value)


def test_pair_scores_returns_sorted_key_order():
    a = [CaseScore("z", 1.0), CaseScore("a", 2.0)]
    b = [CaseScore("z", 1.5), CaseScore("a", 2.5)]
    pairs = pair_scores(a, b)
    assert [key for key, _, _ in pairs] == ["a", "z"]
    assert pairs == [("a", 2.0, 2.5), ("z", 1.0, 1.5)]


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def test_analyze_four_discordant_three_one_split():
    pairs = [
        ("q1", 0.0, 1.0),  # b better
        ("q2", 0.0, 1.0),  # b better
        ("q3", 0.0, 1.0),  # b better
        ("q4", 1.0, 0.0),  # a better
    ]
    stats = analyze(pairs)
    assert stats.n_discordant == 4
    assert stats.n_b_better == 3
    assert stats.n_a_better == 1
    assert stats.sign_p == pytest.approx(0.625)


def test_analyze_single_pair_gives_infinite_mde_and_does_not_raise():
    stats = analyze([("q1", 1.0, 2.0)])
    assert stats.n_paired == 1
    assert stats.mde == math.inf
    assert stats.sd_delta == 0.0
    assert stats.stderr == 0.0
    assert stats.ci_lower == stats.mean_delta == 1.0


# ---------------------------------------------------------------------------
# CLI end-to-end helpers
# ---------------------------------------------------------------------------


def _write_prereg(tmp_path: Path, rel: str = "docs/prereg/plan.md", mtime_offset: float = -3600.0) -> str:
    prereg_path = tmp_path / rel
    prereg_path.parent.mkdir(parents=True, exist_ok=True)
    prereg_path.write_text("# pre-registration\n")
    stamp = time.time() + mtime_offset
    os.utime(prereg_path, (stamp, stamp))
    return rel


def _write_arm_script(tmp_path: Path, name: str, body: str) -> Path:
    script_path = tmp_path / name
    script_path.write_text(body)
    return script_path


def _cmd_for(script_path: Path, *args: str) -> str:
    parts = [shlex.quote(sys.executable), shlex.quote(str(script_path))]
    parts.extend(shlex.quote(a) for a in args)
    return " ".join(parts)


def _static_json_arm(rows: list[dict]) -> str:
    return "import json\n" f"print(json.dumps({{'rows': {rows!r}}}))\n"


def _write_spec(
    tmp_path: Path,
    *,
    prereg_rel: str | None,
    out_rel: str = "eval/ledgers",
    label: str = "test-label",
    threshold: float | None = None,
    fixture_cmd: str | None = None,
    cmd_a: str | None = "",
    cmd_b: str | None = "",
    include_cmds: bool = True,
    bracket_enabled: bool = True,
    tolerance: float = 0.0,
) -> Path:
    lines: list[str] = []
    if prereg_rel is not None:
        lines.append(f'prereg = "{prereg_rel}"')
    lines.append(f'out = "{out_rel}"')
    lines.append(f'label = "{label}"')
    if threshold is not None:
        lines.append(f"threshold = {threshold}")
    lines.append("")
    lines.append("[cases]")
    lines.append('path = "rows"')
    lines.append('key = "query"')
    lines.append('score = "recall"')
    lines.append("")
    if fixture_cmd is not None:
        lines.append("[fixture]")
        lines.append(f'fingerprint = "{fixture_cmd}"')
        lines.append("")
    lines.append("[arms.a]")
    lines.append('label = "arm-a"')
    if include_cmds:
        lines.append(f'cmd = "{cmd_a}"')
    lines.append("")
    lines.append("[arms.b]")
    lines.append('label = "arm-b"')
    if include_cmds:
        lines.append(f'cmd = "{cmd_b}"')
    lines.append("")
    lines.append("[bracket]")
    lines.append(f"enabled = {'true' if bracket_enabled else 'false'}")
    lines.append(f"tolerance = {tolerance}")
    lines.append("")
    spec_path = tmp_path / "spec.toml"
    spec_path.write_text("\n".join(lines))
    return spec_path


# ---------------------------------------------------------------------------
# End-to-end `run`: happy path
# ---------------------------------------------------------------------------


def test_run_end_to_end_writes_a_ledger_that_round_trips(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    script_a = _write_arm_script(
        tmp_path,
        "arm_a.py",
        _static_json_arm(
            [
                {"query": "q1", "recall": 0.5},
                {"query": "q2", "recall": 0.6},
                {"query": "q3", "recall": 0.4},
                {"query": "q4", "recall": 0.7},
                {"query": "q5", "recall": 0.5},
            ]
        ),
    )
    script_b = _write_arm_script(
        tmp_path,
        "arm_b.py",
        _static_json_arm(
            [
                {"query": "q1", "recall": 0.9},
                {"query": "q2", "recall": 0.95},
                {"query": "q3", "recall": 0.8},
                {"query": "q4", "recall": 1.0},
                {"query": "q5", "recall": 0.85},
            ]
        ),
    )
    fixture_script = _write_arm_script(
        tmp_path, "fixture.py", "print('stable-fixture-value')\n"
    )
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        fixture_cmd=_cmd_for(fixture_script),
    )

    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 0

    out = capsys.readouterr().out
    ledger_path = Path(out.splitlines()[0])
    assert ledger_path.exists()

    with ledger_path.open() as f:
        ledger = json.load(f)

    assert ledger["schema_version"] == 1
    assert ledger["label"] == "test-label"
    assert ledger["stats"]["n_paired"] == 5
    assert ledger["bracket"]["enabled"] is True
    assert ledger["fixture"]["captures"] == [
        "stable-fixture-value\n",
        "stable-fixture-value\n",
        "stable-fixture-value\n",
        "stable-fixture-value\n",
    ]
    assert len(ledger["pairs"]) == 5


def test_run_threshold_pass_and_fail_exit_codes(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    script_a = _write_arm_script(
        tmp_path,
        "arm_a.py",
        _static_json_arm([{"query": f"q{i}", "recall": 0.5} for i in range(8)]),
    )
    script_b = _write_arm_script(
        tmp_path,
        "arm_b.py",
        _static_json_arm([{"query": f"q{i}", "recall": 0.9} for i in range(8)]),
    )

    # Threshold comfortably below the observed delta (0.4): should PASS.
    spec_pass = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        label="pass-case",
        threshold=0.0,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_pass), "--cwd", str(tmp_path)])
    assert exit_code == 0

    # Threshold far above any plausible delta: should FAIL (still a valid run).
    spec_fail = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        label="fail-case",
        threshold=100.0,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_fail), "--cwd", str(tmp_path)])
    assert exit_code == 1


# ---------------------------------------------------------------------------
# VOID conditions
# ---------------------------------------------------------------------------


def test_void_prereg_key_missing(tmp_path, capsys):
    spec_path = _write_spec(tmp_path, prereg_rel=None, cmd_a="true", cmd_b="true")
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "prereg" in err


def test_void_prereg_file_does_not_exist(tmp_path, capsys):
    spec_path = _write_spec(
        tmp_path, prereg_rel="docs/prereg/nonexistent.md", cmd_a="true", cmd_b="true"
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "nonexistent.md" in err


def test_void_prereg_not_older_than_run_start(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path, mtime_offset=+3600.0)
    spec_path = _write_spec(tmp_path, prereg_rel=prereg_rel, cmd_a="true", cmd_b="true")
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "not older" in err


def test_void_fixture_fingerprint_changed(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    counter_path = tmp_path / "counter.bin"
    counter_path.write_text("")
    fixture_script = _write_arm_script(
        tmp_path,
        "growing_fingerprint.py",
        "import pathlib\n"
        f"p = pathlib.Path({str(counter_path)!r})\n"
        "with p.open('a') as f:\n"
        "    f.write('x')\n"
        "print(p.stat().st_size)\n",
    )
    script_a = _write_arm_script(
        tmp_path, "arm_a.py", _static_json_arm([{"query": "q1", "recall": 0.5}])
    )
    script_b = _write_arm_script(
        tmp_path, "arm_b.py", _static_json_arm([{"query": "q1", "recall": 0.6}])
    )
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        fixture_cmd=_cmd_for(fixture_script),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "fixture fingerprint changed" in err


def test_void_bracket_mean_mismatch(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    counter_path = tmp_path / "arm_a_counter.txt"
    varying_script = _write_arm_script(
        tmp_path,
        "varying_arm_a.py",
        "import json, pathlib\n"
        f"p = pathlib.Path({str(counter_path)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "print(json.dumps({'rows': [{'query': 'q1', 'recall': float(n)}]}))\n",
    )
    script_b = _write_arm_script(
        tmp_path, "arm_b.py", _static_json_arm([{"query": "q1", "recall": 0.5}])
    )
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(varying_script),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=True,
        tolerance=0.0,
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "bracket mean mismatch" in err


def test_void_arm_key_sets_differ(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    script_a = _write_arm_script(
        tmp_path, "arm_a.py", _static_json_arm([{"query": "q_a_only", "recall": 0.5}])
    )
    script_b = _write_arm_script(
        tmp_path, "arm_b.py", _static_json_arm([{"query": "q_b_only", "recall": 0.5}])
    )
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "q_a_only" in err
    assert "q_b_only" in err


def test_void_arm_exits_nonzero(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    script_a = _write_arm_script(tmp_path, "arm_a.py", "raise SystemExit(1)\n")
    script_b = _write_arm_script(
        tmp_path, "arm_b.py", _static_json_arm([{"query": "q1", "recall": 0.5}])
    )
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "exited" in err


def test_void_arm_emits_unparseable_json(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    script_a = _write_arm_script(tmp_path, "arm_a.py", "print('not json at all')\n")
    script_b = _write_arm_script(
        tmp_path, "arm_b.py", _static_json_arm([{"query": "q1", "recall": 0.5}])
    )
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "unparseable JSON" in err


def test_void_arm_cases_path_not_a_list(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    script_a = _write_arm_script(
        tmp_path, "arm_a.py", "import json\nprint(json.dumps({'rows': 'not-a-list'}))\n"
    )
    script_b = _write_arm_script(
        tmp_path, "arm_b.py", _static_json_arm([{"query": "q1", "recall": 0.5}])
    )
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "does not resolve to a list" in err


def test_void_fewer_than_one_paired_case(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    script_a = _write_arm_script(tmp_path, "arm_a.py", "import json\nprint(json.dumps({'rows': []}))\n")
    script_b = _write_arm_script(tmp_path, "arm_b.py", "import json\nprint(json.dumps({'rows': []}))\n")
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        cmd_a=_cmd_for(script_a),
        cmd_b=_cmd_for(script_b),
        bracket_enabled=False,
    )
    exit_code = main(["run", "--spec", str(spec_path), "--cwd", str(tmp_path)])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "VOID" in err
    assert "fewer than 1 paired case" in err


# ---------------------------------------------------------------------------
# `analyze` subcommand and mde -> null serialization
# ---------------------------------------------------------------------------


def test_analyze_subcommand_over_saved_arm_json(tmp_path, capsys):
    prereg_rel = _write_prereg(tmp_path)
    a_json = tmp_path / "a.json"
    b_json = tmp_path / "b.json"
    a_json.write_text(json.dumps({"rows": [{"query": "q1", "recall": 0.5}]}))
    b_json.write_text(json.dumps({"rows": [{"query": "q1", "recall": 0.9}]}))
    spec_path = _write_spec(
        tmp_path,
        prereg_rel=prereg_rel,
        include_cmds=False,
        bracket_enabled=False,
    )

    exit_code = main(
        [
            "analyze",
            "--spec",
            str(spec_path),
            "--a",
            str(a_json),
            "--b",
            str(b_json),
            "--cwd",
            str(tmp_path),
        ]
    )
    assert exit_code == 0

    out = capsys.readouterr().out
    ledger_path = Path(out.splitlines()[0])
    with ledger_path.open() as f:
        ledger = json.load(f)

    assert ledger["stats"]["n_paired"] == 1
    # mde is math.inf at n_paired == 1: must serialize as JSON null, never Infinity.
    assert ledger["stats"]["mde"] is None
    raw_text = ledger_path.read_text()
    assert "Infinity" not in raw_text
