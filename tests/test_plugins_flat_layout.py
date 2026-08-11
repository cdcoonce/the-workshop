"""Guards that shipped plugin instructions describe the layout that exists.

The flat reorg (#656) deleted `core/`, `presets/`, `dist/`, `build_preset.py`,
and `build_docs.py`. #650 made "zero stale-layout references under
`plugins/workshop-maintainer/`" a structural acceptance criterion, but nothing
asserted it, so the criterion was reported satisfied while 54 references
survived across 17 files -- see #640.

These are not stale comments. `add-the-workshop-hook` told the reader to put
shared logic in `core/hooks/`, register it in `core/settings-base.json`, and run
`build_preset` to compose into `dist/`. Every one of those paths is gone, so
following the skill start to finish produced nothing. A skill that reads
authoritative and is wrong is worse than a missing one.

Scope grew to `plugins/workbench/` in #661, which carried the same defect --
including five runnable `uv run python core/skills/.../*.py` commands that
could not resolve.

Note on writing the check: `git grep -E` silently matches NOTHING for `\\bcore/`
because git's ERE has no `\\b`. A guard written that way passes by matching
nothing -- the same defect class the reorg already fixed once in
`smoke_test.py`. This uses Python `re` with an explicit non-word lookbehind.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SCANNED_PLUGINS = ("workshop-maintainer", "workbench")

# Paths and tool names the flat reorg deleted. A leading non-word guard keeps
# `core/` from matching inside `score/`, which a bare substring search hits.
#
# These tokens only ever named THIS repo's tree, so any occurrence is a defect.
# `core/` is pinned to the subtrees that actually existed rather than left bare:
# `project-context` legitimately classifies modules as `core/leaf/orchestrator`,
# which is a taxonomy, not a path, and a bare `core/` cannot tell them apart.
# `dist/` is deliberately NOT here: it is a universal convention, and the
# shipped skills give generic guidance about other people's repos too.
STALE_LAYOUT = re.compile(
    r"(?<![A-Za-z0-9_])(core/(docs|hooks|skills|agents|settings-base)"
    r"|presets/|build_preset|build_docs)"
)

# `dist/` counts only where it names this repo's deleted generated tree. Three
# forms are legitimate and stay legitimate:
#   * a URL path -- `cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js`
#   * an explicitly relative path -- `gh release upload v1.0.0 ./dist/binary`
#   * an enumeration of generic build artifacts alongside `.venv/`,
#     `__pycache__/`, or `build/`, which is advice about any Python repo
# Rewriting correct content to satisfy a lint would be the wrong fix, so the
# exemptions live in the pattern where they can be read and tested, not in a
# per-path allowlist that hides which lines were waved through.
REPO_DIST = re.compile(r"(?<![A-Za-z0-9_./])dist/")
GENERIC_ARTIFACTS = re.compile(r"\.venv/|__pycache__/|build/")
URL = re.compile(r"https?://")

# The engine moved out of the vault's `.claude/scripts/` and into the plugin at
# `machinery/engine/` (#650), but 48 shipped invocations kept the old path and
# nothing caught them (#679). STALE_LAYOUT could not: `.claude/scripts/` is not
# a deleted-layout token, it is a live directory in other people's repos.
#
# So this guard is keyed to the engine's OWN filenames, read off disk rather
# than hardcoded, and fires only on `.claude/scripts/<an-engine-script>`. That
# narrowness is load-bearing in both directions:
#   * `vault-cold-read` legitimately names `.claude/scripts/guard_worktree.py`
#     as a TARGET-relative path in afk's deny-surface tuple -- a real file in
#     enrolled repos, nothing to do with our engine. A blanket
#     `\.claude/scripts/` pattern would rewrite correct content to satisfy a
#     lint, which is the wrong fix.
#   * keying to real filenames means an engine script added later is covered
#     the day it lands, with no second list to remember.
ENGINE_DIR = REPO_ROOT / "plugins" / "workbench" / "machinery" / "engine"


def _engine_script_names() -> list[str]:
    """Every script the engine ships, longest first so alternation is greedy.

    `rglob`, not `iterdir`: the engine has subdirectories (`queries/`), and a
    non-recursive scan would leave `queries/vault_query.py` uncovered -- a guard
    with a hole in it is the failure mode this whole file exists to prevent.
    """
    names = sorted(
        {
            p.name
            for p in ENGINE_DIR.rglob("*")
            if p.is_file() and p.suffix in {".py", ".sh"} and "__pycache__" not in p.parts
        },
        key=len,
        reverse=True,
    )
    if not names:  # pragma: no cover - a guard that matches nothing is the bug
        raise AssertionError(f"no engine scripts found under {ENGINE_DIR}")
    return names


STALE_ENGINE = re.compile(
    r"\.claude/scripts/(" + "|".join(re.escape(n) for n in _engine_script_names()) + r")"
)

TEXT_SUFFIXES = {".md", ".py", ".sh", ".json", ".toml", ".txt", ".yml", ".yaml"}


def _scan(plugin: str) -> list[str]:
    """Return `path:line: text` for every stale-layout reference in a plugin."""
    root = REPO_ROOT / "plugins" / plugin
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if URL.search(line):
                continue
            hit = STALE_LAYOUT.search(line) or (
                REPO_DIST.search(line) and not GENERIC_ARTIFACTS.search(line)
            )
            if hit:
                rel = path.relative_to(REPO_ROOT)
                findings.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    return findings


# The vendoring subsystem's whole job is to copy engine files INTO a vault at
# `.claude/scripts/`, so naming that path is its correct output, not a defect:
# `vendor-map.json` maps source->target, `rendered/` holds wiring already
# rendered against a target vault, `tools/` implements the copy, `scaffold/`
# templates it, and `tests/` pins all four. Rewriting any of them to satisfy
# this guard would break the subsystem to silence a lint.
#
# `machinery/engine/` is deliberately NOT exempt. It is runnable code, and a
# docstring that says "invoke this at <path that does not exist>" fails exactly
# the way a skill does -- #679 missed these only because it scanned `skills/`.
#
# KNOWN GAP, exempted rather than fixed here: `machinery/scaffold/` is not just
# vendoring data. `scaffold-map.json` still writes a new vault's OWNER config
# (`vault_scope.py`, `context_paths.py`, `budget_burn_config.py`,
# `content_routing.py`, `frontmatter_schema.json`) to `.claude/scripts/`, but
# `hooks/run-vault-hook.sh` puts only `<vault>/.vault/config` on PYTHONPATH. A
# vault scaffolded today therefore silently falls back to shipped defaults --
# a real defect, filed separately, and NOT a path this guard should silence
# once it is fixed. Fixing it changes vault-init's behaviour and belongs with
# its own tests, so it is out of scope for the #679 doc pass rather than
# out of scope forever.
VENDORING_PATHS = (
    "vendor-map.json",
    "machinery/rendered/",
    "machinery/tools/",
    "machinery/scaffold/",
    "machinery/tests/",
)


def _is_vendoring_artifact(rel: str) -> bool:
    return any(part in rel for part in VENDORING_PATHS)


def _scan_engine(plugin: str) -> list[str]:
    """Return `path:line: text` for every engine invocation at the deleted path."""
    root = REPO_ROOT / "plugins" / plugin
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        if _is_vendoring_artifact(path.relative_to(REPO_ROOT).as_posix()):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if STALE_ENGINE.search(line):
                rel = path.relative_to(REPO_ROOT)
                findings.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    return findings


def test_plugins_invoke_the_engine_where_it_actually_lives() -> None:
    """No shipped skill may tell a session to run the engine from `.claude/scripts/`.

    This is #679. The engine moved into the plugin; the invocations did not.
    A session following such a skill verbatim hits a missing path and has to
    improvise, and the steps that fail this way -- the `/garden` orphan lane,
    the `/find` reindex -- fail *quiet*, so nothing surfaces the miss.
    """
    findings: list[str] = []
    for plugin in SCANNED_PLUGINS:
        findings.extend(_scan_engine(plugin))

    assert not findings, (
        f"{len(findings)} shipped invocation(s) run an engine script from the "
        f"deleted `.claude/scripts/` path in {', '.join(SCANNED_PLUGINS)}. The "
        "engine ships at `machinery/engine/`; resolve it from the skill's "
        "announced base directory rather than restoring the old path:\n  "
        + "\n  ".join(findings)
    )


def test_engine_guard_fires_on_the_engine_and_spares_target_relative_paths() -> None:
    """Pin both directions -- the guard must not pass by matching nothing.

    A guard keyed to `.claude/scripts/` wholesale would also condemn
    `vault-cold-read`'s citation of afk's deny-surface tuple, where
    `.claude/scripts/guard_worktree.py` is a path in the *enrolled repo* being
    checked. Rewriting that would corrupt correct content; missing a real
    engine call would leave #679 open. Both are asserted.
    """
    # Real defects: engine scripts at the deleted path.
    assert STALE_ENGINE.search("uv run --script .claude/scripts/semantic_index.py search")
    assert STALE_ENGINE.search("python3 .claude/scripts/pulse.py $ARGUMENTS")
    assert STALE_ENGINE.search("uv run python .claude/scripts/graph_gardener.py --acquire-lock")

    # Not ours: a target-relative path naming a file in the repo under review.
    assert not STALE_ENGINE.search(
        "target-relative entries (`.afk/config.toml`, `.claude/scripts/guard_worktree.py`)"
    )
    # Not ours: the same engine name under a path we do not own.
    assert not STALE_ENGINE.search("their own .config/scripts/pulse.py wrapper")
    # The corrected form must not trip the guard it was written to satisfy.
    assert not STALE_ENGINE.search("uv run --script ../../machinery/engine/semantic_index.py")
    assert not STALE_ENGINE.search('uv run --script "<engine>/semantic_index.py" search')

    # A script in an engine SUBDIRECTORY is still an engine script.
    assert STALE_ENGINE.search("uv run .claude/scripts/vault_query.py")


# A skill's commands are composed and run one at a time, each in its own shell.
# An assignment made in one does not survive into the next, so a command spec
# that says `"$ENGINE/pulse.py"` expands to `/pulse.py` at run time -- the exact
# failure mode that made `$CLAUDE_PLUGIN_ROOT` unusable, reintroduced under a
# different name. Engine paths in shipped command specs must therefore be
# SUBSTITUTED placeholders, never shell variables.
# Scoped to `$ENGINE`, the anchor this repo introduced for the engine, and only
# where it is used as a PATH PREFIX -- `$ENGINE/x.py`, not prose mentioning the
# name. `$CLAUDE_PLUGIN_ROOT` is the same defect class but has three tangled
# call sites of its own (gitlab-mr-create documents two wrong forms and
# sync-gitlab-dev a third); that is #686's job, not this guard's, and widening
# this pattern to cover it would also condemn `add-the-workshop-hook`, which
# discusses the variable correctly because hooks are where it is defined.
SHELL_VAR_ENGINE = re.compile(r"\$\{?ENGINE\}?/")


def test_command_specs_do_not_defer_the_engine_path_to_a_shell_variable() -> None:
    """Shipped skill docs must substitute the engine path, not `$VAR` it.

    Scoped to skill-facing docs: hook *commands* legitimately use
    `${CLAUDE_PLUGIN_ROOT}` because the hook environment is where it is defined.
    """
    findings: list[str] = []
    for plugin in SCANNED_PLUGINS:
        root = REPO_ROOT / "plugins" / plugin / "skills"
        for path in sorted(root.rglob("*.md")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if SHELL_VAR_ENGINE.search(line):
                    rel = path.relative_to(REPO_ROOT)
                    findings.append(f"{rel}:{lineno}: {line.strip()[:110]}")

    assert not findings, (
        f"{len(findings)} shipped skill line(s) reference the engine through a shell "
        "variable. Each command runs in a fresh shell, so the variable is unset by "
        "the time the command runs and the path collapses to `/<script>`. Substitute "
        "the absolute path instead:\n  " + "\n  ".join(findings)
    )


def test_the_shell_variable_guard_is_pinned_in_both_directions() -> None:
    """It must catch the deferred forms and spare the substituted one."""
    assert SHELL_VAR_ENGINE.search('python3 "$ENGINE/pulse.py"')
    assert SHELL_VAR_ENGINE.search('uv run --script "${ENGINE}/semantic_index.py" search')
    # The corrected form: a placeholder the composer expands.
    assert not SHELL_VAR_ENGINE.search('python3 "<engine>/pulse.py"')
    assert not SHELL_VAR_ENGINE.search('python3 "/abs/path/machinery/engine/pulse.py"')
    # Prose naming the variable is not an invocation deferring to it.
    assert not SHELL_VAR_ENGINE.search("do not set $ENGINE in an earlier command")
    # Not a false positive on unrelated variables.
    assert not SHELL_VAR_ENGINE.search("pass $ARGUMENTS through to the workflow")


def test_the_vendoring_exemption_cannot_swallow_a_real_defect() -> None:
    """The exemption is a path filter, so pin what it does and does not cover.

    An exemption wide enough to cover the whole of `machinery/` would also hide
    stale invocations in `engine/`, which are the same defect as a skill's.
    """
    # Exempt: the vendoring subsystem, whose output is that path by design.
    assert _is_vendoring_artifact("plugins/workbench/machinery/vendor-map.json")
    assert _is_vendoring_artifact("plugins/workbench/machinery/rendered/codex-hooks.json")
    assert _is_vendoring_artifact("plugins/workbench/machinery/tools/machinery_sync.py")

    # Not exempt: runnable engine code, and every shipped instruction.
    assert not _is_vendoring_artifact("plugins/workbench/machinery/engine/graph_cli.py")
    assert not _is_vendoring_artifact(
        "plugins/workbench/skills/vault-find/references/command.md"
    )


def test_plugins_ship_no_references_to_the_deleted_layout() -> None:
    """Every scanned plugin's shipped text describes the tree that exists."""
    findings: list[str] = []
    for plugin in SCANNED_PLUGINS:
        findings.extend(_scan(plugin))

    assert not findings, (
        f"{len(findings)} reference(s) to the deleted layout "
        f"(core/, presets/, dist/, build_preset, build_docs) survive in "
        f"{', '.join(SCANNED_PLUGINS)}. These are shipped instructions that "
        "cannot resolve -- rewrite them for the flat tree rather than "
        "excluding the path:\n  " + "\n  ".join(findings)
    )


def test_stale_layout_pattern_does_not_fire_on_lookalikes() -> None:
    """The guard must not pass by over-matching, nor miss a real reference.

    Without the lookbehind, `core/` matches inside `score/` and the check
    fails on innocent text; without a check at all, `\\bcore/` under `git grep
    -E` matches nothing and the guard passes vacuously. Pin both directions.
    """
    assert not STALE_LAYOUT.search("see docs/skill-score/summary.md")
    assert not STALE_LAYOUT.search("the hardcore/soft split")
    # A taxonomy, not a path -- `project-context` classifies modules this way.
    assert not STALE_LAYOUT.search("classify modules (core/leaf/orchestrator)")
    assert STALE_LAYOUT.search("shared logic goes under `core/hooks/`")
    assert STALE_LAYOUT.search("run build_preset to compose")
    assert STALE_LAYOUT.search("edit presets/workbench/skills/foo")


def test_url_exemption_is_narrow() -> None:
    """URL lines are skipped, but a repo path on a URL-free line still fires."""
    assert URL.search("<script src='https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js'>")
    assert not URL.search("uv run python core/skills/blueprint/scripts/build_fixture.py")


def test_dist_counts_only_when_it_names_this_repos_tree() -> None:
    """`dist/` is ambiguous, so each exemption is pinned in both directions.

    The three legitimate forms must NOT fire, and a real reference to this
    repo's deleted generated tree must still fire -- otherwise the narrowing
    that lets correct generic guidance survive would also let the defect
    through.
    """
    # Legitimate: an explicitly relative path in generic `gh` usage.
    assert not REPO_DIST.search("gh release upload v1.0.0 ./dist/binary")
    # Legitimate: generic Python build artifacts to ignore in any repo.
    generic = "ignore `.venv/`, `__pycache__/`, `.eggs/`, `build/`, `dist/`."
    assert REPO_DIST.search(generic) and GENERIC_ARTIFACTS.search(generic)
    # Still a defect: this repo's own generated tree.
    real = "rebuilds every preset into dist/ and regenerates the marketplace"
    assert REPO_DIST.search(real) and not GENERIC_ARTIFACTS.search(real)
    assert REPO_DIST.search("never edit dist/ or an installed plugin cache")
