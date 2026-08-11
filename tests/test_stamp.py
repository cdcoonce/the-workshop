"""Contract tests for `scripts/stamp.py`, the repo's only build component.

These are written as teeth-checks rather than green runs: for each guarantee
the stamper makes, the test introduces the defect the guarantee exists to catch
and asserts the stamper notices — by name, on stderr, with a non-zero exit.
A drift gate that has never been observed failing is not evidence of anything.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import stamp

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# The path map
# --------------------------------------------------------------------------


def test_owned_paths_covers_every_documented_path_class(flat_repo: Path):
    """The stamper's path map is the contract; nothing generated may sit outside it.

    Each entry here is one of the twelve path classes the stamper owns. A
    renderer added without a map entry writes a file nothing checks; a map
    entry without a renderer is a KeyError at stamp time. Pinning the classes
    keeps both halves honest.
    """
    owned = stamp.owned_paths(flat_repo)
    relative = {p.relative_to(flat_repo).as_posix() for p in owned}

    assert "plugins/demo/.codex-plugin/plugin.json" in relative
    assert "plugins/demo/.cortex-plugin/plugin.json" in relative
    assert "plugins/demo/README.md" in relative
    assert "plugins/demo/conventions.json" in relative
    assert "plugins/demo/hooks/hooks.json" in relative
    assert ".claude-plugin/marketplace.json" in relative
    assert ".agents/plugins/marketplace.json" in relative
    for page in ("skills", "hooks", "agents", "plugins", "methodology"):
        assert f"docs/reference/{page}.md" in relative


def test_the_two_marketplaces_are_not_the_same_document(flat_repo: Path):
    """Codex reads a different shape, and reads it silently.

    The Claude index carries `owner` and a string `source`. Codex wants a
    top-level `interface` block and a structured `source`/`policy`/`category`
    per entry. Emitting the Claude shape into `.agents/` costs nothing at stamp
    time and breaks discovery on one of the four surfaces the cutover verifies
    — a failure that only ever shows up on a machine, never in CI.
    """
    stamp.stamp(flat_repo)
    codex = json.loads((flat_repo / ".agents/plugins/marketplace.json").read_text())
    claude = json.loads((flat_repo / ".claude-plugin/marketplace.json").read_text())

    assert codex != claude
    assert codex["interface"]["displayName"]
    entry = codex["plugins"][0]
    assert entry["source"] == {"source": "local", "path": "./plugins/demo"}
    assert entry["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert entry["category"] == "Productivity"

    assert claude["owner"]["name"]
    assert claude["plugins"][0]["source"] == "./plugins/demo"


def test_marketplace_sources_point_at_served_directories(flat_repo: Path):
    """`./dist/<n>` was the built copy. There is no built copy."""
    stamp.stamp(flat_repo)
    for relpath in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
        assert "dist/" not in (flat_repo / relpath).read_text()


def test_the_claude_manifest_is_never_owned(flat_repo: Path):
    """`.claude-plugin/plugin.json` is the hand-written source of truth.

    If the stamper ever generated it, the version it reads and the version it
    writes would be the same file, and a bad render could silently rewrite the
    only place a plugin's version is declared.
    """
    owned = {p.relative_to(flat_repo).as_posix() for p in stamp.owned_paths(flat_repo)}
    assert "plugins/demo/.claude-plugin/plugin.json" not in owned


# --------------------------------------------------------------------------
# Generation markers and the overwrite refusal
# --------------------------------------------------------------------------


def test_every_stamped_file_carries_a_generation_marker(flat_repo: Path):
    stamp.stamp(flat_repo)
    for path in stamp.owned_paths(flat_repo):
        text = path.read_text(encoding="utf-8")
        assert stamp.GENERATED_MARKER in text, f"{path} shipped without a marker"


def test_json_marker_is_a_key_not_a_comment(flat_repo: Path):
    """JSON has no comments, so the marker has to be data — and stay parseable."""
    stamp.stamp(flat_repo)
    doc = json.loads((flat_repo / "plugins/demo/conventions.json").read_text())
    assert doc["_generated"] == "scripts/stamp.py"


def test_hooks_json_carries_no_field_codex_will_reject(flat_repo: Path):
    """Codex validates hooks.json strictly: `description` and `hooks`, nothing else.

    It rejects the whole file on an unknown top-level field rather than ignoring
    it, so a marker key that Claude Code tolerates takes every hook in the plugin
    down on the other platform (#682). The marker still has to be *somewhere* —
    the overwrite refusal keys on it — so it rides in `description`.
    """
    stamp.stamp(flat_repo)
    doc = json.loads((flat_repo / "plugins/demo/hooks/hooks.json").read_text())
    assert set(doc) <= {"description", "hooks"}, (
        f"hooks.json ships fields Codex will reject: {sorted(set(doc) - {'description', 'hooks'})}"
    )
    assert stamp.GENERATED_MARKER in doc["description"]


def test_refuses_to_overwrite_an_unmarked_file(flat_repo: Path, capsys):
    """A mis-mapped output must never silently consume hand-written work."""
    victim = flat_repo / "plugins" / "demo" / "README.md"
    victim.write_text("# Hand-written, and not the stamper's to take.\n")

    with pytest.raises(stamp.StampError) as excinfo:
        stamp.stamp(flat_repo)

    assert "plugins/demo/README.md" in str(excinfo.value)
    assert victim.read_text().startswith("# Hand-written")


def test_overwrites_its_own_output_without_complaint(flat_repo: Path):
    """The refusal keys on the marker, not on existence — restamping is routine."""
    stamp.stamp(flat_repo)
    readme = flat_repo / "plugins" / "demo" / "README.md"
    readme.write_text(readme.read_text().replace("demo-skill", "stale-name"))
    stamp.stamp(flat_repo)
    assert "demo-skill" in readme.read_text()


# --------------------------------------------------------------------------
# --check, teeth-checked once per owned path class
# --------------------------------------------------------------------------

DRIFT_CASES = [
    ("manifest", "plugins/demo/.codex-plugin/plugin.json"),
    ("conventions", "plugins/demo/conventions.json"),
    ("readme", "plugins/demo/README.md"),
    ("hooks.json", "plugins/demo/hooks/hooks.json"),
    ("marketplace", ".claude-plugin/marketplace.json"),
    ("docs/reference", "docs/reference/skills.md"),
]


@pytest.mark.parametrize("label,relpath", DRIFT_CASES, ids=[c[0] for c in DRIFT_CASES])
def test_check_names_the_drifted_path(flat_repo: Path, capsys, label, relpath):
    """Drift in each owned class must be caught, and the message must name the file.

    The gate this replaces printed two digests and left you to find the file
    yourself. Naming the path is the whole improvement, so it is what gets
    asserted — not merely the exit code.
    """
    stamp.stamp(flat_repo)
    target = flat_repo / relpath
    target.write_text(target.read_text() + "\ndrift\n")

    exit_code = stamp.main(["--check"], root=flat_repo)
    captured = capsys.readouterr()

    assert exit_code == 1, f"{label} drift did not fail the gate"
    assert relpath in captured.err + captured.out, f"{label} drift did not name the path"


def test_check_never_writes(flat_repo: Path):
    """--check has to be safe on a dirty tree and in CI, so it renders to memory."""
    stamp.stamp(flat_repo)
    target = flat_repo / "docs" / "reference" / "skills.md"
    drifted = target.read_text() + "\ndrift\n"
    target.write_text(drifted)

    stamp.main(["--check"], root=flat_repo)

    assert target.read_text() == drifted


def test_check_is_clean_immediately_after_a_stamp(flat_repo: Path):
    stamp.stamp(flat_repo)
    assert stamp.main(["--check"], root=flat_repo) == 0


def test_stamping_twice_changes_nothing(flat_repo: Path):
    """Rendering must be deterministic, or the gate flaps against itself."""
    stamp.stamp(flat_repo)
    first = {p: p.read_bytes() for p in stamp.owned_paths(flat_repo)}
    stamp.stamp(flat_repo)
    for path, content in first.items():
        assert path.read_bytes() == content, f"{path} is not deterministic"


# --------------------------------------------------------------------------
# Filesystem-driven hook wiring
# --------------------------------------------------------------------------


def test_dropping_a_hook_in_is_the_wiring(flat_repo: Path):
    """Adding a hook must require editing no other file — that is the design.

    Under the old build, a new hook meant a script plus a settings-base entry
    plus a manifest entry in every preset that wanted it. Three places to
    forget. Now the declaration lives in the script.
    """
    stamp.stamp(flat_repo)
    scripts_dir = flat_repo / "plugins" / "demo" / "hooks" / "scripts"
    (scripts_dir / "throwaway.py").write_text(
        '"""Stop hook: a throwaway."""\n\n'
        'WORKSHOP_HOOK = {"event": "Stop", "matcher": "never"}\n'
    )

    stamp.stamp(flat_repo)

    wiring = json.loads((flat_repo / "plugins/demo/hooks/hooks.json").read_text())
    commands = [
        h["command"]
        for entry in wiring["hooks"]["Stop"]
        for h in entry["hooks"]
    ]
    assert any("throwaway.py" in c for c in commands)
    assert any(entry.get("matcher") == "never" for entry in wiring["hooks"]["Stop"])


def test_a_module_without_a_declaration_is_not_a_hook(flat_repo: Path):
    """The leading-underscore convention is a hint; the declaration is the rule.

    `_git_baseline.py` is a shared library that lives in the hook directory
    because sibling imports resolve there at runtime. Wiring it would run it
    on every event.
    """
    scripts_dir = flat_repo / "plugins" / "demo" / "hooks" / "scripts"
    (scripts_dir / "_helper.py").write_text('"""Shared helper, not a hook."""\n')

    stamp.stamp(flat_repo)

    wiring = (flat_repo / "plugins/demo/hooks/hooks.json").read_text()
    assert "_helper.py" not in wiring


def test_a_hook_declaring_an_unknown_event_is_a_loud_failure(flat_repo: Path):
    """A typo'd event name would otherwise generate wiring that never fires."""
    scripts_dir = flat_repo / "plugins" / "demo" / "hooks" / "scripts"
    (scripts_dir / "typo.py").write_text(
        '"""A hook with a typo."""\n\nWORKSHOP_HOOK = {"event": "SesionStart"}\n'
    )

    with pytest.raises(stamp.StampError) as excinfo:
        stamp.stamp(flat_repo)

    assert "typo.py" in str(excinfo.value)
    assert "SesionStart" in str(excinfo.value)


def test_the_declaration_is_read_statically_not_imported(flat_repo: Path):
    """Hooks read stdin and call sys.exit at import time. Importing one hangs CI."""
    scripts_dir = flat_repo / "plugins" / "demo" / "hooks" / "scripts"
    (scripts_dir / "explodes.py").write_text(
        '"""Stop hook: detonates on import."""\n\n'
        'WORKSHOP_HOOK = {"event": "Stop"}\n\n'
        'raise SystemExit("this hook must never be imported")\n'
    )

    stamp.stamp(flat_repo)

    assert "explodes.py" in (flat_repo / "plugins/demo/hooks/hooks.json").read_text()


# --------------------------------------------------------------------------
# Plugin-root portability
# --------------------------------------------------------------------------


def test_hook_commands_do_not_fall_back_to_the_working_directory(flat_repo: Path):
    """`${CLAUDE_PLUGIN_ROOT:-.}` is the bug, not the fix.

    Cortex leaves `CLAUDE_PLUGIN_ROOT` unset (probed on 1.20.2, issue #634), so
    a `.` default resolves against the user's cwd — the hook runs, reads the
    wrong directory, and reports nothing. A bare `${CLAUDE_PLUGIN_ROOT}` with
    no default, which the persona hook used, is worse: it resolves to `/`.
    """
    stamp.stamp(flat_repo)
    wiring = (flat_repo / "plugins/demo/hooks/hooks.json").read_text()
    assert '${CLAUDE_PLUGIN_ROOT:-.}' not in wiring
    assert '"${CLAUDE_PLUGIN_ROOT}"/hooks' not in wiring


def test_every_hook_command_routes_through_run_hook(flat_repo: Path):
    """One resolver, in one file, for all nine plugins.

    `run-hook.sh` derives the plugin root from `${BASH_SOURCE[0]}`. Any command
    that invokes a hook script directly bypasses that and has to solve the
    resolution problem again, per platform.
    """
    stamp.stamp(flat_repo)
    wiring = json.loads((flat_repo / "plugins/demo/hooks/hooks.json").read_text())
    for entries in wiring["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                assert "run-hook.sh" in hook["command"], hook["command"]


# --------------------------------------------------------------------------
# Cross-plugin invariants
# --------------------------------------------------------------------------


def test_a_duplicate_slug_across_plugins_is_a_loud_failure(flat_repo: Path, make_plugin):
    """One plugin per slug, globally.

    `improve-skill` resolves a skill by a flat `plugins/*/skills/<slug>/` glob.
    Two hits means it silently edits one copy and ships the other.
    """
    make_plugin(flat_repo, "other", skills=["demo-skill"])

    with pytest.raises(stamp.StampError) as excinfo:
        stamp.stamp(flat_repo)

    message = str(excinfo.value)
    assert "demo-skill" in message
    assert "plugins/demo/skills/demo-skill" in message
    assert "plugins/other/skills/demo-skill" in message


def test_two_directories_claiming_one_plugin_name_is_a_loud_failure(
    flat_repo: Path, make_plugin
):
    """Directory names cannot collide; manifest names are free text and can.

    `name` is what the marketplace advertises and what
    `/plugin install <name>@the-workshop` resolves, so a duplicate renders an
    index the installer picks between arbitrarily.
    """
    twin = make_plugin(flat_repo, "demo-twin")
    manifest = twin / ".claude-plugin" / "plugin.json"
    manifest.write_text(manifest.read_text().replace('"demo-twin"', '"demo"'))

    with pytest.raises(stamp.StampError) as excinfo:
        stamp.stamp(flat_repo)

    message = str(excinfo.value)
    assert "demo" in message
    assert "plugins/demo-twin" in message


def test_a_manifest_without_a_name_is_a_loud_failure(flat_repo: Path):
    """Falling back to the directory name would install under a name the file never says."""
    manifest = flat_repo / "plugins" / "demo" / ".claude-plugin" / "plugin.json"
    manifest.write_text(json.dumps({"version": "1.0.0", "description": "x"}) + "\n")

    with pytest.raises(stamp.StampError) as excinfo:
        stamp.stamp(flat_repo)

    assert "plugins/demo/.claude-plugin/plugin.json" in str(excinfo.value)


def test_persona_artifacts_are_copies_of_the_workbench_canonicals(flat_repo: Path, make_plugin):
    """Persona plumbing has exactly one author, and it is not the persona.

    Workbench ships `inject_persona.py` it never runs so that the five personas
    cannot drift from each other — the cost, accepted with eyes open, is that
    editing persona plumbing bumps workbench.
    """
    workbench = make_plugin(flat_repo, "workbench", hooks=True)
    canonical = workbench / "hooks" / "inject_persona.py"
    canonical.write_text(
        '"""SessionStart hook: inject a persona."""\n\n'
        'WORKSHOP_HOOK = {"event": "SessionStart", "runner": "uv"}\n'
    )
    persona = make_plugin(flat_repo, "persona-demo")
    (persona / "output-styles").mkdir(parents=True, exist_ok=True)
    (persona / "output-styles" / "demo.md").write_text("---\nname: demo\n---\n\nBe terse.\n")

    stamp.stamp(flat_repo)

    copy = persona / "hooks" / "scripts" / "inject_persona.py"
    assert copy.exists()
    assert "WORKSHOP_HOOK" in copy.read_text()
    assert (persona / "hooks" / "run-hook.sh").exists()


# --------------------------------------------------------------------------
# The real tree
# --------------------------------------------------------------------------


def test_the_committed_tree_is_stamped(capsys):
    """The gate `make test` runs, exercised here against the actual repo."""
    assert stamp.main(["--check"], root=REPO_ROOT) == 0, capsys.readouterr().err


def test_stamp_is_runnable_as_a_module():
    """`make stamp` shells out to it; an import-time error must not hide here."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.stamp", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
