"""C-no-blanket-add: no Bash call runs `git add .`, `-A` or `--all` (and a new commit exists)."""

from __future__ import annotations

import pytest

from commit_c_support import GOOD_COMMANDS, GOOD_FILES, GOOD_LOGS, evidence_from


def _score(predicates, tmp_path, commands, logs=GOOD_LOGS, files=GOOD_FILES):
    return predicates.no_blanket_add(
        evidence_from(tmp_path, commands=commands, logs=logs, files=files)
    )


def test_named_adds_are_met(predicates, tmp_path):
    assert _score(predicates, tmp_path, GOOD_COMMANDS) is True


@pytest.mark.parametrize(
    "command",
    [
        "git add .",
        "git add -A",
        "git add --all",
        "git add -A .",
        "git add ./",
        "git add -- .",
        "git add -Av",
        "git add -fA",
        "git -C /tmp/repo add .",
        "git -c core.autocrlf=false add -A",
        "cd repo && git add -A && git commit -m 'x'",
        "make test; git add .",
        "git status | cat && git add --all",
        "git add a.py\ngit add .",
        "GIT_TRACE=1 git add -A",
        "bash -c 'git add -A'",
        'sh -c "make test && git add ."',
        "git stage .",
        "git add foo.py . bar.py",
        "echo start\ngit add -A",
        "ls # a note\ngit add -A",
    ],
)
def test_blanket_staging_is_missed(predicates, tmp_path, command):
    assert _score(predicates, tmp_path, [*GOOD_COMMANDS, command]) is False


@pytest.mark.parametrize(
    "command",
    [
        "git add invoice/pricing.py",
        "git add -u",
        "git add -p invoice/",
        "git add ./invoice/pricing.py",
        "git add -- .env.example",
        "git add some/dir/.hidden",
        "echo git add .",
        'git commit -m "never run git add . or git add -A"',
        "git commit -F - <<'EOF'\nfeat: x\n\ngit add -A is banned\nEOF",
        "grep -rn 'git add -A' docs",
        "ls # git add .",
    ],
)
def test_named_or_unrelated_commands_are_not_blanket_staging(predicates, tmp_path, command):
    assert _score(predicates, tmp_path, [*GOOD_COMMANDS, command]) is True


def test_a_non_bash_tool_input_is_never_a_blanket_add(predicates, tmp_path):
    from commit_c_support import write_transcript
    from evals._harness.dispatch import Evidence
    from evals._harness.transcript import parse_transcript

    path = write_transcript(tmp_path / "t.jsonl", [])
    transcript = parse_transcript(path)
    # An Edit call whose input happens to contain the text is not a Bash call.
    text = path.read_text().splitlines()
    text.insert(
        0,
        '{"type": "assistant", "message": {"role": "assistant", "model": "m", "content": '
        '[{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"command": "git add -A"}}]}}',
    )
    path.write_text("\n".join(text) + "\n")
    evidence = Evidence(
        transcripts=[parse_transcript(path)],
        findings=[],
        workdir=None,
        end_state={"commit-1.log": GOOD_LOGS[0], "commit-1.files": GOOD_FILES[0]},
    )
    assert transcript.status == "complete"
    assert predicates.no_blanket_add(evidence) is True


def test_zero_new_commits_misses_the_gate(predicates, tmp_path):
    assert _score(predicates, tmp_path, ["git status"], logs=[], files=[]) is False


def test_blanket_add_in_any_transcript_is_missed(predicates, tmp_path):
    from commit_c_support import write_transcript
    from evals._harness.dispatch import Evidence
    from evals._harness.transcript import parse_transcript

    clean = write_transcript(tmp_path / "one.jsonl", ["git status"])
    dirty = write_transcript(tmp_path / "two.jsonl", ["git add -A"])
    evidence = Evidence(
        transcripts=[parse_transcript(clean), parse_transcript(dirty)],
        findings=[],
        workdir=None,
        end_state={"commit-1.log": GOOD_LOGS[0], "commit-1.files": GOOD_FILES[0]},
    )
    assert predicates.no_blanket_add(evidence) is False
