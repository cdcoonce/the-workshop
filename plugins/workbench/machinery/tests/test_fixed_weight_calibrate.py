"""Tests for the fixed-weight calibration script (slice 8, #1335).

The oracle is ``fixtures/cost_ledger_calibration/EXPECTED.json``, derived by hand from
the spec before the code: five matched pairs of fresh sessions, ids invented, text
placeholder. Refusal and edge cases are built in ``tmp_path`` by copying the fixture and
changing one thing, or from a two-pair scenario with ``--min-runs 2``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import cost_ledger
import fixed_weight
import fixed_weight_calibrate as calibrate
import transcript_reader

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "cost_ledger_calibration"
ROOT = FIXTURE / "projects"
WANT = json.loads((FIXTURE / "EXPECTED.json").read_text())
FULL = [f"cal-f{i}" for i in range(1, 6)]
BARE = [f"cal-b{i}" for i in range(1, 6)]
DATE = "2026-11-14"
IDENTIFIERS = (*FULL, *BARE, "cx-alpha", "cx-beta", "cost_ledger_calibration", "cal-fa1")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE / "fixed_weight_calibrate.py"), *args],
        capture_output=True, text=True,
    )


def arms(full: list[str] = FULL, bare: list[str] = BARE) -> list[str]:
    return ["--full", *full, "--bare", *bare]


def calibrate_args(root: Path, out: Path, *extra: str, full: list[str] = FULL,
                   bare: list[str] = BARE) -> list[str]:
    return [*arms(full, bare), "--projects-root", str(root), "--out", str(out), "--date", DATE, *extra]


def _ids_in(args: list[str]) -> list[str]:
    """Every id on the command line: the words after --full and --bare."""
    ids: list[str] = []
    take = False
    for word in args:
        if word.startswith("--"):
            take = word in ("--full", "--bare")
        elif take:
            ids.append(word)
    return ids


def _fixture_names() -> tuple[str, ...]:
    """Every session id and project key the fixture holds, read from its files."""
    names = {p.name for p in ROOT.iterdir()}
    for path in ROOT.rglob("*.jsonl"):
        names.add(path.stem)
    for path in ROOT.rglob("*"):
        if path.is_dir():
            names.add(path.name)
    return tuple(sorted(names - {"subagents"}))


def refuse(proc: subprocess.CompletedProcess, out: Path, hide: tuple[str, ...] = IDENTIFIERS) -> None:
    hide = tuple(dict.fromkeys((*hide, *_ids_in(list(proc.args[2:])), *_fixture_names())))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not out.exists()
    assert list(out.parent.glob("*")) == [], "a refusal must leave no temp file behind"
    lines = proc.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("fixed_weight_calibrate:")
    for needle in hide:
        assert needle not in proc.stderr, needle
    assert "Traceback" not in proc.stderr
    assert proc.stdout == ""


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out" / "factor.json"
    path.parent.mkdir()
    return path


@pytest.fixture
def copy_root(tmp_path: Path) -> Path:
    dest = tmp_path / "projects"
    shutil.copytree(ROOT, dest)
    return dest


# ---------------------------------------------------------------------------
# builders (370 characters are 100 tokens at 3.7 characters per token)
# ---------------------------------------------------------------------------
def rec_call(sid: str, n: int, usage: tuple[int, int, int, int], version: str | None = None) -> dict:
    inp, w5, w1, cr = usage
    rec = {
        "type": "assistant", "uuid": f"zu-{sid}-{n}", "requestId": f"zr-{sid}-{n}",
        "message": {"id": f"zm-{sid}-{n}", "model": "claude-opus-4-8", "usage": {
            "input_tokens": inp, "output_tokens": 1, "cache_read_input_tokens": cr,
            "cache_creation_input_tokens": w5 + w1,
            "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}},
        "timestamp": "2026-11-11T01:00:00Z",
    }
    if version is not None:
        rec["version"] = version
    return rec


def rec_listing(chars: int, version: str | None = None) -> dict:
    rec = {"type": "attachment", "attachment": {"type": "skill_listing"},
           "rendered": [{"content": "x" * chars}], "timestamp": "2026-11-11T00:00:00Z"}
    if version is not None:
        rec["version"] = version
    return rec


def write_session(root: Path, project: str, sid: str, records: list[dict]) -> None:
    path = root / project / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def two_pairs(root: Path, version: str | None = "9.9.9", full_chars: tuple[int, int] = (740, 1110),
              bare_chars: tuple[int, int] = (370, 370),
              full_usage=((10, 100, 0, 0), (10, 0, 300, 0)),
              bare_usage=((10, 50, 0, 0), (10, 0, 0, 100))) -> None:
    """Pairs with predicted differences 100 and 200 tokens at the default ratio."""
    for i in range(2):
        write_session(root, "-zz-proj", f"zf{i}", [
            rec_listing(full_chars[i], version), rec_call(f"zf{i}", 1, full_usage[i], version)])
        write_session(root, "-zz-proj", f"zb{i}", [
            rec_listing(bare_chars[i], version), rec_call(f"zb{i}", 1, bare_usage[i], version)])


TWO = ["--full", "zf0", "zf1", "--bare", "zb0", "zb1", "--min-runs", "2", "--date", DATE]


def run_two(root: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return run(*TWO, "--projects-root", str(root), "--out", str(out), *extra)


# ---------------------------------------------------------------------------
# the fixture against the hand oracle
# ---------------------------------------------------------------------------
class TestOracle:
    def test_factor_file_matches_the_hand_oracle_byte_for_byte(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out))
        assert proc.returncode == 0, proc.stderr
        want = json.dumps(WANT["factor_file"], sort_keys=True, indent=2) + "\n"
        assert out.read_text() == want

    def test_stdout_matches_the_hand_oracle(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out))
        assert proc.stdout == WANT["stdout"].replace("{OUT}", str(out))
        assert proc.stderr == ""

    def test_ratio_of_sums_is_not_mean_or_median_of_ratios(self, out: Path) -> None:
        run(*calibrate_args(ROOT, out))
        got = json.loads(out.read_text())
        assert got["factor"] == 1.29
        assert got["factor"] not in (1.31, 1.2)
        assert (got["low"], got["high"]) == (0.9, 2.0)

    def test_deterministic_stdout_and_file(self, tmp_path: Path) -> None:
        outs = [tmp_path / "a.json", tmp_path / "b.json"]
        procs = [run(*calibrate_args(ROOT, o)) for o in outs]
        assert outs[0].read_bytes() == outs[1].read_bytes()
        assert procs[0].stdout.replace(str(outs[0]), "X") == procs[1].stdout.replace(str(outs[1]), "X")

    def test_pair_order_is_the_order_given(self, out: Path) -> None:
        both = (FULL[::-1], BARE[::-1])
        proc = run(*calibrate_args(ROOT, out, full=both[0], bare=both[1]))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(out.read_text())["factor"] == 1.29  # a consistent reorder keeps the pairs

    def test_swapped_pairing_changes_the_result(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out, bare=BARE[::-1]))
        assert proc.returncode == 2 or json.loads(out.read_text())["low"] != 0.9

    def test_redaction_in_file_and_stdout(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out))
        text = out.read_text() + proc.stdout.replace(str(out), "")
        for needle in IDENTIFIERS + (str(ROOT), "projects"):
            assert needle not in text, needle

    def test_file_is_written_whole_with_no_temp_left(self, out: Path) -> None:
        run(*calibrate_args(ROOT, out))
        assert [p.name for p in out.parent.iterdir()] == ["factor.json"]
        assert out.read_text().endswith("}\n") and not out.read_text().endswith("\n\n")

    def test_the_estimator_accepts_its_own_file(self, out: Path) -> None:
        run(*calibrate_args(ROOT, out))
        cal = fixed_weight.load_calibration(out, required=True)
        assert (cal.factor, cal.low, cal.high) == (1.29, 0.9, 2.0)
        assert (cal.date, cal.claude_code_version, cal.runs_per_arm) == (DATE, "9.9.9", 5)


# ---------------------------------------------------------------------------
# C4, C5: what is measured and what is predicted
# ---------------------------------------------------------------------------
class TestMeasuredAndPredicted:
    def test_first_call_in_file_order_and_both_cache_lifetimes(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root)
        # a later, huge call must not count; a usage-less assistant record first must be skipped
        for sid in ("zf0", "zb1"):
            path = root / "-zz-proj" / f"{sid}.jsonl"
            lines = path.read_text().splitlines()
            nousage = {"type": "assistant", "uuid": "zu-n", "requestId": "zr-n",
                       "message": {"id": "zm-n", "model": "claude-opus-4-8"}}
            path.write_text("\n".join([lines[0], json.dumps(nousage), *lines[1:],
                                       json.dumps(rec_call(sid, 9, (500000, 0, 0, 0)))]) + "\n")
        proc = run_two(root, out)
        assert proc.returncode == 0, proc.stderr
        got = json.loads(out.read_text())
        # full 110 and 310, bare 60 and 110: measured differences 50 and 200, predicted 100 and 200
        assert got["measured_tokens_diff"]["min"] == 50.0 and got["measured_tokens_diff"]["max"] == 200.0
        assert got["factor"] == round(250 / 300, 6)
        assert (got["low"], got["high"]) == (0.5, 1.0)

    def test_subagent_files_are_ignored(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root)
        sub = root / "-zz-proj" / "zf0" / "subagents" / "agent-zza.jsonl"
        sub.parent.mkdir(parents=True)
        sub.write_text(json.dumps(rec_call("zf0", 5, (900000, 0, 0, 0))) + "\n"
                       + json.dumps(rec_listing(99999)) + "\n")
        plain = tmp_path / "plain.json"
        assert run_two(root, out).returncode == 0
        shutil.rmtree(sub.parent.parent)
        assert run_two(root, plain).returncode == 0
        assert out.read_bytes() == plain.read_bytes()

    def test_subagent_file_with_an_earlier_or_larger_first_call_never_supplies_the_measure(
        self, tmp_path: Path, out: Path
    ) -> None:
        root = tmp_path / "p"
        two_pairs(root)
        for sid, n in (("zf0", 1), ("zb1", 2)):
            sub = root / "-zz-proj" / sid / "subagents" / "agent-zza.jsonl"
            sub.parent.mkdir(parents=True)
            early = {**rec_call(sid, 7, (800000, 0, 0, 0)), "timestamp": "2026-11-10T00:00:00Z"}
            sub.write_text(json.dumps(early) + "\n")
        # main files only: full 110 and 310, bare 60 and 110 -> differences 50 and 200
        assert run_two(root, out).returncode == 0
        got = json.loads(out.read_text())
        assert (got["measured_tokens_diff"]["min"], got["measured_tokens_diff"]["max"]) == (50.0, 200.0)

    def test_predicted_ignores_an_existing_calibration_file_at_the_default_path(
        self, tmp_path: Path
    ) -> None:
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / fixed_weight.CALIBRATION_FILE).write_text(json.dumps({"factor": 3.0}))
        target = tmp_path / "result.json"
        with mock.patch.object(cost_ledger, "_config_dir", lambda: cfg):
            rc = calibrate.main([*calibrate_args(ROOT, target)])
        assert rc == 0
        got = json.loads(target.read_text())
        assert got["factor"] == 1.29
        assert got["predicted_tokens_diff"] == WANT["factor_file"]["predicted_tokens_diff"]

    def test_predicted_uses_the_module_chars_per_token(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root)
        with mock.patch.object(fixed_weight, "CHARS_PER_TOKEN", 1.0):
            assert calibrate.main([*TWO, "--projects-root", str(root), "--out", str(out)]) == 0
        got = json.loads(out.read_text())
        assert got["chars_per_token"] == 1.0
        assert got["predicted_tokens_diff"] == {"max": 740.0, "mean": 555.0, "min": 370.0}

    def test_session_without_snapshot_is_counted_across_both_arms(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root)
        snap = {"type": "attachment", "attachment": {"type": "prompt_snapshot", "systemPrompt": "x", "tools": []},
                "timestamp": "2026-11-11T00:00:00Z"}
        for sid in ("zf0", "zb0"):
            path = root / "-zz-proj" / f"{sid}.jsonl"
            path.write_text(json.dumps(snap) + "\n" + path.read_text())
        proc = run_two(root, out)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(out.read_text())["sessions_without_snapshot"] == 2

    def test_reads_only_through_transcript_reader(self, out: Path) -> None:
        spy = mock.Mock(wraps=transcript_reader.read)
        with mock.patch.object(transcript_reader, "read", spy):
            rc = calibrate.main([*calibrate_args(ROOT, out)])
        assert rc == 0 and spy.call_count == 1
        assert callable(spy.call_args.kwargs.get("on_record"))
        source = (ENGINE / "fixed_weight_calibrate.py").read_text()
        assert ".jsonl" not in source and "iter_records" not in source and "discover(" not in source


class TestFixedWeightPublicFunction:
    def test_total_fixed_tokens_sums_components_at_a_factor(self) -> None:
        sizes = fixed_weight.FileSizes()
        sizes.add("skill_listing", 370)
        sizes.add("system_prompt", 740)
        assert fixed_weight.total_fixed_tokens(sizes, chars_per_token=3.7) == pytest.approx(300)
        assert fixed_weight.total_fixed_tokens(sizes, factor=2.0, chars_per_token=3.7) == pytest.approx(600)
        assert fixed_weight.total_fixed_tokens(sizes) == pytest.approx(1110 / fixed_weight.CHARS_PER_TOKEN)
        assert fixed_weight.total_fixed_tokens(fixed_weight.FileSizes()) == 0


# ---------------------------------------------------------------------------
# C1, C2, C3: arguments and finding sessions
# ---------------------------------------------------------------------------
class TestRefusalsFindingSessions:
    def test_unknown_id_names_its_position_in_its_arm(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out, full=[*FULL[:2], "cal-nope", *FULL[3:]]))
        refuse(proc, out)
        assert "full[3]" in proc.stderr

    def test_an_unknown_id_given_on_the_command_line_is_never_echoed(self, out: Path) -> None:
        unknown = "zq-never-in-any-list-7731"
        assert unknown not in IDENTIFIERS and unknown not in _fixture_names()
        for arm in ("full", "bare"):
            kw = {arm: [unknown, *(FULL if arm == "full" else BARE)[1:]]}
            proc = run(*calibrate_args(ROOT, out, **kw))
            refuse(proc, out)
            assert unknown not in proc.stdout + proc.stderr
            assert f"{arm}[1]" in proc.stderr

    def test_unknown_bare_id_names_the_bare_position(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out, bare=[*BARE[:4], "cal-nope"]))
        refuse(proc, out)
        assert "bare[5]" in proc.stderr

    def test_id_in_two_projects_is_refused_without_naming_them(self, copy_root: Path, out: Path) -> None:
        shutil.copy(copy_root / "-cx-alpha" / "cal-f1.jsonl", copy_root / "-cx-beta" / "cal-f1.jsonl")
        proc = run(*calibrate_args(copy_root, out))
        refuse(proc, out, hide=(*IDENTIFIERS, str(copy_root)))
        assert "full[1]" in proc.stderr

    def test_subagent_file_alone_does_not_count_as_a_session(self, copy_root: Path, out: Path) -> None:
        sub = copy_root / "-cx-alpha" / "cal-ghost" / "subagents" / "agent-cal-ga.jsonl"
        sub.parent.mkdir(parents=True)
        sub.write_text(json.dumps(rec_call("cal-ghost", 1, (1, 0, 0, 0))) + "\n")
        proc = run(*calibrate_args(copy_root, out, full=[*FULL[:4], "cal-ghost"]))
        refuse(proc, out, hide=("cal-ghost", *IDENTIFIERS))
        assert "full[5]" in proc.stderr

    def test_id_twice_within_an_arm(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out, full=[*FULL[:4], FULL[0]]))
        refuse(proc, out)

    def test_id_in_both_arms(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out, bare=[*BARE[:4], FULL[0]]))
        refuse(proc, out)

    def test_unequal_arms(self, out: Path) -> None:
        refuse(run(*calibrate_args(ROOT, out, bare=BARE[:4])), out)

    def test_fewer_than_min_runs_default_five(self, out: Path) -> None:
        refuse(run(*calibrate_args(ROOT, out, full=FULL[:4], bare=BARE[:4])), out)

    def test_min_runs_flag_raises_the_bar(self, out: Path) -> None:
        refuse(run(*calibrate_args(ROOT, out, "--min-runs", "6")), out)

    def test_min_runs_flag_lowers_the_bar_to_two_but_no_lower(self, out: Path) -> None:
        ok = run(*calibrate_args(ROOT, out, "--min-runs", "2", full=FULL[:2], bare=BARE[:2]))
        assert ok.returncode == 0, ok.stderr
        out.unlink()
        refuse(run(*calibrate_args(ROOT, out, "--min-runs", "1", full=FULL[:1], bare=BARE[:1])), out)

    def test_one_run_default_refused(self, out: Path) -> None:
        refuse(run(*calibrate_args(ROOT, out, full=FULL[:1], bare=BARE[:1])), out)

    def test_bad_date_refused(self, out: Path) -> None:
        proc = run(*arms(), "--projects-root", str(ROOT), "--out", str(out), "--date", "2026-13-40")
        refuse(proc, out)

    def test_projects_root_not_a_directory(self, tmp_path: Path, out: Path) -> None:
        proc = run(*calibrate_args(tmp_path / "absent", out))
        assert proc.returncode == 2 and not out.exists()
        assert len(proc.stderr.strip().splitlines()) == 1


# ---------------------------------------------------------------------------
# C4, C6: measuring and the factor
# ---------------------------------------------------------------------------
class TestRefusalsMeasuring:
    def test_session_without_a_usable_call(self, copy_root: Path, out: Path) -> None:
        path = copy_root / "-cx-beta" / "cal-b1.jsonl"
        keep = [ln for ln in path.read_text().splitlines() if '"usage"' not in ln]
        path.write_text("\n".join(keep) + "\n")
        proc = run(*calibrate_args(copy_root, out))
        refuse(proc, out, hide=(*IDENTIFIERS, str(copy_root)))
        assert "bare[1]" in proc.stderr

    def test_predicted_sum_not_positive(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, full_chars=(370, 370))
        refuse(run_two(root, out), out)

    def test_measured_sum_not_positive(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, full_usage=((10, 0, 0, 0), (10, 0, 0, 0)))
        refuse(run_two(root, out), out)

    def test_one_pair_with_predicted_not_positive_while_sum_is_(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, full_chars=(370, 1480))  # first pair predicts 0
        refuse(run_two(root, out), out)

    def test_one_pair_negative_measured_difference_refuses_naming_its_position(
        self, tmp_path: Path, out: Path
    ) -> None:
        root = tmp_path / "p"
        two_pairs(root, full_usage=((10, 20, 0, 0), (10, 0, 800, 0)))  # pair 1 measures below bare
        proc = run_two(root, out)
        refuse(proc, out, hide=(*IDENTIFIERS, "zf0", "zb0", str(root)))
        assert "pair[1]" in proc.stderr

    def test_negative_measured_pair_in_second_position_is_named(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, full_usage=((10, 100, 0, 0), (10, 0, 50, 0)))  # pair 2: 60 against bare 110
        proc = run_two(root, out)
        refuse(proc, out)
        assert "pair[2]" in proc.stderr

    def test_zero_measured_difference_refuses(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, full_usage=((10, 50, 0, 0), (10, 0, 300, 0)))  # pair 1 ties its bare partner
        proc = run_two(root, out)
        refuse(proc, out)
        assert "pair[1]" in proc.stderr

    def test_unequal_arms_at_or_above_min_runs(self, out: Path) -> None:
        proc = run(*calibrate_args(ROOT, out, "--min-runs", "2", full=FULL[:3], bare=BARE[:2]))
        refuse(proc, out)
        proc = run(*calibrate_args(ROOT, out, "--min-runs", "5", full=FULL[:5], bare=BARE[:5]))
        assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# a file the script writes is a file the estimator accepts
# ---------------------------------------------------------------------------
def _variant_equal_ratios(root: Path) -> list[str]:
    two_pairs(root, full_usage=((10, 100, 0, 0), (10, 0, 300, 0)),
              bare_usage=((10, 0, 0, 0), (10, 0, 0, 0)))
    return list(TWO)


def _variant_default(root: Path) -> list[str]:
    two_pairs(root)
    return list(TWO)


def _variant_wide_ratios(root: Path) -> list[str]:
    two_pairs(root, full_usage=((10, 5000, 0, 0), (10, 0, 70, 0)), bare_usage=((10, 0, 0, 0), (10, 0, 0, 0)))
    return list(TWO)


def _variant_flag_version(root: Path) -> list[str]:
    two_pairs(root, version=None)
    return [*TWO, "--claude-code-version", "3.2.1"]


class TestWrittenFileIsAccepted:
    @pytest.mark.parametrize("variant", [_variant_default, _variant_equal_ratios, _variant_wide_ratios,
                                         _variant_flag_version])
    def test_estimator_loads_and_the_cli_runs_on_whatever_the_script_writes(
        self, variant, tmp_path: Path, out: Path
    ) -> None:
        root = tmp_path / "p"
        args = variant(root)
        proc = run(*args, "--projects-root", str(root), "--out", str(out))
        assert proc.returncode == 0, proc.stderr
        cal = fixed_weight.load_calibration(out, required=True)
        assert 0 < cal.low <= cal.factor <= cal.high
        cli = subprocess.run(
            [sys.executable, str(ENGINE / "cost_ledger.py"), "--fixed-weight", "--calibration", str(out),
             "--projects-root", str(ROOT), "--since", "2026-01-01", "--until", "2026-12-31"],
            capture_output=True, text=True,
        )
        assert "needs finite numbers" not in cli.stderr and "calibration" not in cli.stderr.lower(), cli.stderr

    def test_the_oracle_fixture_file_is_accepted(self, out: Path) -> None:
        assert run(*calibrate_args(ROOT, out)).returncode == 0
        assert fixed_weight.load_calibration(out, required=True).low == 0.9


# ---------------------------------------------------------------------------
# C7: the Claude Code version
# ---------------------------------------------------------------------------
class TestVersion:
    def test_taken_from_the_transcripts(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version="1.2.3")
        assert run_two(root, out).returncode == 0
        assert json.loads(out.read_text())["claude_code_version"] == "1.2.3"

    def test_taken_from_the_flag_when_no_session_has_one(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version=None)
        proc = run_two(root, out, "--claude-code-version", "4.5.6")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(out.read_text())["claude_code_version"] == "4.5.6"

    def test_required_when_nothing_records_one(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version=None)
        refuse(run_two(root, out), out)

    def test_flag_equal_to_the_transcripts_is_accepted(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version="1.2.3")
        assert run_two(root, out, "--claude-code-version", "1.2.3").returncode == 0

    def test_flag_differing_from_the_transcripts_is_refused(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version="1.2.3")
        refuse(run_two(root, out, "--claude-code-version", "9.9.0"), out)

    def test_two_versions_across_sessions_refused(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version="1.2.3")
        path = root / "-zz-proj" / "zb1.jsonl"
        path.write_text(path.read_text().replace('"1.2.3"', '"1.2.4"'))
        refuse(run_two(root, out), out)
        refuse(run_two(root, out, "--claude-code-version", "1.2.3"), out)

    def test_two_versions_inside_one_session_refused(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version="1.2.3")
        path = root / "-zz-proj" / "zf0.jsonl"
        first, *rest = path.read_text().splitlines()
        path.write_text("\n".join([first.replace('"1.2.3"', '"0.0.1"'), *rest]) + "\n")
        refuse(run_two(root, out), out)

    def test_session_with_no_version_among_sessions_with_one_is_fine(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version="1.2.3")
        path = root / "-zz-proj" / "zb0.jsonl"
        path.write_text(path.read_text().replace(', "version": "1.2.3"', ""))
        assert "version" not in path.read_text()
        assert run_two(root, out).returncode == 0

    def test_version_in_a_subagent_file_does_not_count(self, tmp_path: Path, out: Path) -> None:
        root = tmp_path / "p"
        two_pairs(root, version=None)
        sub = root / "-zz-proj" / "zf0" / "subagents" / "agent-zza.jsonl"
        sub.parent.mkdir(parents=True)
        sub.write_text(json.dumps({**rec_call("zf0", 5, (1, 0, 0, 0)), "version": "7.7.7"}) + "\n")
        refuse(run_two(root, out), out)


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------
class TestDefaults:
    def test_out_defaults_to_the_estimators_default_calibration_path(self, tmp_path: Path) -> None:
        with mock.patch.object(cost_ledger, "_config_dir", lambda: tmp_path):
            rc = calibrate.main([*arms(), "--projects-root", str(ROOT), "--date", DATE])
        assert rc == 0
        assert json.loads((tmp_path / fixed_weight.CALIBRATION_FILE).read_text())["factor"] == 1.29

    def test_date_defaults_to_the_injected_today(self, out: Path) -> None:
        from datetime import date
        rc = calibrate.main([*arms(), "--projects-root", str(ROOT), "--out", str(out)],
                            today=date(2030, 1, 2))
        assert rc == 0 and json.loads(out.read_text())["date"] == "2030-01-02"

    def test_existing_out_file_is_replaced_whole(self, out: Path) -> None:
        out.write_text("old")
        assert run(*calibrate_args(ROOT, out)).returncode == 0
        assert json.loads(out.read_text())["runs_per_arm"] == 5

    def test_refusal_leaves_an_existing_out_file_untouched(self, out: Path) -> None:
        out.write_text("old")
        proc = run(*calibrate_args(ROOT, out, bare=BARE[:4]))
        assert proc.returncode == 2 and out.read_text() == "old"


# ---------------------------------------------------------------------------
# the procedure document (P1 to P3) and the wiring (R5)
# ---------------------------------------------------------------------------
REFERENCES = HERE.parent.parent / "skills" / "vault-budget" / "references"
PROCEDURE = (REFERENCES / "cost-ledger-calibration.md").read_text(encoding="utf-8")


class TestProcedureDocument:
    def test_has_the_pieces_a_cold_reader_needs(self) -> None:
        for needle in (
            "claude --version", "Reply with the single word: ok", "--session-id",
            "claude plugin disable", "claude plugin enable", "alternating", "full, bare, full, bare",
            "at least 5", "fixed_weight_calibrate.py",
            "Numbers only", "factor, low, high, runs per arm, Claude Code version, date",
        ):
            assert needle in PROCEDURE, needle

    def test_warns_that_disabling_the_plugin_reaches_every_session_and_names_the_script(self) -> None:
        assert "every Claude Code session started anywhere on the machine" in PROCEDURE
        assert "Close your other Claude Code sessions" in PROCEDURE
        assert "plugins/workbench/machinery/engine/fixed_weight_calibrate.py" in PROCEDURE
        assert ".claude/scripts/" not in PROCEDURE
        assert 'python3 "<engine>/fixed_weight_calibrate.py"' in PROCEDURE
        assert "pair[2]" in PROCEDURE

    def test_states_what_the_factor_does_and_does_not_cover(self) -> None:
        assert "first call of a main session" in PROCEDURE
        assert "one Claude Code version" in PROCEDURE
        assert "subagent files included" in PROCEDURE and "known to differ" in PROCEDURE

    def test_unverified_commands_are_marked(self) -> None:
        assert PROCEDURE.count("UNVERIFIED") >= 3

    def test_uses_the_plugin_subcommands_listed_in_local_help(self) -> None:
        for sub in ("claude plugin disable", "claude plugin enable", "claude plugin list"):
            assert sub in PROCEDURE

    def test_linked_from_command_and_schema_documents(self) -> None:
        assert "cost-ledger-calibration.md" in (REFERENCES / "command.md").read_text(encoding="utf-8")
        assert "cost-ledger-calibration.md" in (REFERENCES / "cost-ledger-schema.md").read_text(encoding="utf-8")
        assert "fixed_weight_calibrate.py" in (REFERENCES / "command.md").read_text(encoding="utf-8")

    def test_vendor_map_lists_the_script(self) -> None:
        text = (HERE.parent / "vendor-map.json").read_text(encoding="utf-8")
        entries = json.loads(text)
        flat = json.dumps(entries)
        assert '"engine/fixed_weight_calibrate.py"' in flat
        assert '".claude/scripts/fixed_weight_calibrate.py"' in flat
