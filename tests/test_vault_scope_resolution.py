"""The vault owner's `vault_scope.py` must actually reach the engine.

`vault_scope_resolved` is the only door between engine code and the vault
owner's scope config, and its fallback to shipped defaults is deliberately
SILENT: a vault whose scaffold predates a name should degrade, not crash on
import. That silence is exactly why resolution has to be tested on the VALUE it
returns and never on the machinery meant to deliver it. A resolver that never
sees the owner's file at all is, from outside, indistinguishable from a vault
that set no overrides — both return the default, both exit clean, both log
nothing.

The prior guard for this behaviour asserted only that `run-vault-hook.sh`
exports the owner config directory onto `PYTHONPATH`. That input cannot
separate "the override arrived" from "the override was shadowed", so it passed
under both while the override was in fact discarded (#691).

So every assertion here spawns a REAL subprocess that arranges `sys.path`
exactly as a vault hook entry point does — engine directory prepended,
owner config directory on `PYTHONPATH` — and asserts on the value that comes
back. In-process assertions cannot do this honestly: `vault_scope` would
already sit in `sys.modules` from an earlier test, so module caching would
decide the outcome instead of path ordering, which is the whole subject.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE = REPO_ROOT / "plugins" / "workbench" / "machinery" / "engine"

# The shipped default for the name used as the sentinel throughout. Asserting
# against it is what makes the tests discriminating: a sentinel that happened
# to equal the default would pass whether or not the owner's file was read.
SHIPPED_GOVERNED_DIRS = ("brain", "work", "personal", "org", "perf", "reference")

# Deliberately unlike any plausible default, so a passing assertion can only
# mean the owner's file was the source.
OWNER_GOVERNED_DIRS = ("sentinel_owner_dir",)

_OWNER_CONFIG = f"""\
GOVERNED_NOTE_DIRS = {OWNER_GOVERNED_DIRS!r}
"""


def _make_vault(root: Path, *, owner_config: str | None = _OWNER_CONFIG) -> Path:
    """A directory shaped like a vault: the marker, and optionally owner config.

    `.vault/vault.json` is the marker deliberately — it is what
    `run-vault-hook.sh` walks up looking for, and unlike a note-directory
    signature it does not assume any particular taxonomy.
    """
    (root / ".vault").mkdir(parents=True, exist_ok=True)
    (root / ".vault" / "vault.json").write_text(
        '{"vault": "test", "plugin": "workbench", "min_plugin_version": "5.0.0"}\n',
        encoding="utf-8",
    )
    if owner_config is not None:
        config_dir = root / ".vault" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "vault_scope.py").write_text(owner_config, encoding="utf-8")
    return root


_PROBE = """\
import sys
sys.path.insert(0, {engine!r})   # exactly what every vault hook entry point does
import vault_scope_resolved as resolved
print(repr(getattr(resolved, {name!r})))
"""


def _resolve(
    name: str,
    *,
    cwd: Path,
    vault: Path | None = None,
    set_pythonpath: bool = True,
    set_project_dir: bool = True,
) -> subprocess.CompletedProcess:
    """Resolve one scope name in a fresh interpreter, hook-style.

    Mirrors `run-vault-hook.sh`: `CLAUDE_PROJECT_DIR` points at the vault root
    and the owner config directory goes on `PYTHONPATH`. The engine directory
    is prepended inside the probe, which is what the hook entry points do and
    what puts the engine ahead of `PYTHONPATH` on `sys.path`.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if vault is not None:
        if set_pythonpath:
            env["PYTHONPATH"] = str(vault / ".vault" / "config")
        if set_project_dir:
            env["CLAUDE_PROJECT_DIR"] = str(vault)
    return subprocess.run(
        [sys.executable, "-c", _PROBE.format(engine=str(ENGINE), name=name)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )


class TestOwnerConfigWins:
    """The override has to survive the path ordering a real hook produces."""

    def test_owner_override_beats_shipped_default(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path / "vault")
        result = _resolve("GOVERNED_NOTE_DIRS", cwd=vault, vault=vault)

        assert result.returncode == 0, result.stderr
        assert repr(OWNER_GOVERNED_DIRS) in result.stdout, (
            "the owner's GOVERNED_NOTE_DIRS did not reach the engine; got "
            f"{result.stdout.strip()!r}"
        )
        assert repr(SHIPPED_GOVERNED_DIRS) not in result.stdout

    def test_override_survives_without_pythonpath(self, tmp_path: Path) -> None:
        """Resolution must not depend on the ambient path at all.

        `PYTHONPATH` was the intended delivery mechanism and it demonstrably
        could not do the job. Anchoring on the vault root instead means the
        override arrives whether or not the runner sets it — so a hook invoked
        by some other path, or an engine script run straight from a CLI, gets
        the owner's rules too.
        """
        vault = _make_vault(tmp_path / "vault")
        result = _resolve(
            "GOVERNED_NOTE_DIRS", cwd=vault, vault=vault, set_pythonpath=False
        )

        assert result.returncode == 0, result.stderr
        assert repr(OWNER_GOVERNED_DIRS) in result.stdout

    def test_override_found_by_walking_up_from_a_subdirectory(
        self, tmp_path: Path
    ) -> None:
        """Sessions routinely start below the vault root, not at it."""
        vault = _make_vault(tmp_path / "vault")
        nested = vault / "work" / "active" / "some-project"
        nested.mkdir(parents=True)
        result = _resolve(
            "GOVERNED_NOTE_DIRS",
            cwd=nested,
            vault=vault,
            set_project_dir=False,
        )

        assert result.returncode == 0, result.stderr
        assert repr(OWNER_GOVERNED_DIRS) in result.stdout


class TestFallbackStillDegradesSilently:
    """The silent fallback is a feature for stale scaffolds. It must survive."""

    def test_name_the_owner_does_not_define_falls_back(self, tmp_path: Path) -> None:
        """Per-name resolution: a stale scaffold degrades per name, not wholesale."""
        vault = _make_vault(tmp_path / "vault")
        result = _resolve("BATCH_MODEL", cwd=vault, vault=vault)

        assert result.returncode == 0, result.stderr
        assert "claude-haiku-4-5" in result.stdout

    def test_vault_without_owner_config_uses_defaults(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path / "vault", owner_config=None)
        result = _resolve("GOVERNED_NOTE_DIRS", cwd=vault, vault=vault)

        assert result.returncode == 0, result.stderr
        assert repr(SHIPPED_GOVERNED_DIRS) in result.stdout

    def test_outside_any_vault_import_succeeds_on_defaults(
        self, tmp_path: Path
    ) -> None:
        """Engine code imports in the repo's own suite, with no vault anywhere."""
        elsewhere = tmp_path / "not-a-vault"
        elsewhere.mkdir()
        result = _resolve("GOVERNED_NOTE_DIRS", cwd=elsewhere)

        assert result.returncode == 0, result.stderr
        assert repr(SHIPPED_GOVERNED_DIRS) in result.stdout

    def test_unknown_name_raises_attribute_error(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path / "vault")
        result = _resolve("NO_SUCH_SCOPE_NAME", cwd=vault, vault=vault)

        assert result.returncode != 0
        assert "AttributeError" in result.stderr


class TestUnloadableConfigIsVisible:
    """Exists-but-broken must not look identical to absent."""

    def test_broken_owner_config_is_reported(self, tmp_path: Path) -> None:
        """A config that cannot load is the one case that must not stay silent.

        Absent config is a legitimate state and degrades quietly by design.
        Present-but-unloadable is a defect in the owner's own file, and the
        owner is the only one who can fix it — so it has to surface.
        """
        vault = _make_vault(
            tmp_path / "vault", owner_config="GOVERNED_NOTE_DIRS = (  # unclosed\n"
        )
        result = _resolve("GOVERNED_NOTE_DIRS", cwd=vault, vault=vault)

        # Asserted on the diagnostic's own wording, not merely on the string
        # "vault_scope" appearing somewhere in stderr. An unhandled SyntaxError
        # traceback names the file too, so the looser assertion passes when the
        # config CRASHES the process — the opposite of the behaviour under test.
        assert "did not load" in result.stderr, (
            "a broken owner config produced no diagnostic; it is indistinguishable "
            f"from having no config at all. stderr={result.stderr!r}"
        )
        assert "falling back to shipped defaults" in result.stderr

    def test_broken_owner_config_still_fails_open(self, tmp_path: Path) -> None:
        """Hooks fail open by contract: a broken config must not kill the session."""
        vault = _make_vault(
            tmp_path / "vault", owner_config="GOVERNED_NOTE_DIRS = (  # unclosed\n"
        )
        result = _resolve("GOVERNED_NOTE_DIRS", cwd=vault, vault=vault)

        assert result.returncode == 0, result.stderr
        assert repr(SHIPPED_GOVERNED_DIRS) in result.stdout


class TestPathologicalOwnerConfigCannotHangTheEngine:
    """Fail open covers hostile shapes, not just typos."""

    def test_self_referential_config_does_not_recurse(self, tmp_path: Path) -> None:
        """An owner config that reaches the resolver while loading must terminate.

        The resolver executes the owner's file inside its own attribute lookup.
        If the cache were only written after that finished, a config touching
        `vault_scope_resolved` mid-execution would re-enter the load and
        recurse until the interpreter gave out — taking the session with it.
        """
        vault = _make_vault(
            tmp_path / "vault",
            owner_config=(
                "import vault_scope_resolved\n"
                "_ = vault_scope_resolved.TASKS_DIR\n"
                f"GOVERNED_NOTE_DIRS = {OWNER_GOVERNED_DIRS!r}\n"
            ),
        )
        result = _resolve("GOVERNED_NOTE_DIRS", cwd=vault, vault=vault)

        assert result.returncode == 0, result.stderr
        assert "RecursionError" not in result.stderr
        assert repr(OWNER_GOVERNED_DIRS) in result.stdout

    def test_deleted_working_directory_does_not_crash_the_engine(
        self, tmp_path: Path
    ) -> None:
        """`os.getcwd()` raises when cwd is gone; import must still succeed.

        This module is imported at engine startup, so an exception here is not
        a degraded scope surface — it is a hook that never ran.
        """
        doomed = tmp_path / "doomed"
        doomed.mkdir()
        probe = (
            f"import os, sys, shutil\n"
            f"os.chdir({str(doomed)!r})\n"
            f"shutil.rmtree({str(doomed)!r})\n"
            f"sys.path.insert(0, {str(ENGINE)!r})\n"
            "import vault_scope_resolved as r\n"
            "print(repr(r.GOVERNED_NOTE_DIRS))\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("CLAUDE_PROJECT_DIR", None)
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, result.stderr
        assert repr(SHIPPED_GOVERNED_DIRS) in result.stdout


class TestNothingShippedCanShadowOwnerConfig:
    def test_engine_ships_no_module_named_vault_scope(self) -> None:
        """The root cause of #691, guarded at the payload.

        The engine carried a `vault_scope` stand-in so in-repo code could
        satisfy `import vault_scope` without a vault present. It shipped in the
        plugin payload too, and because every hook entry point prepends the
        engine directory to `sys.path`, it won the name lookup ahead of the
        owner's config on `PYTHONPATH` — permanently. Resolution no longer goes
        through the module name, and nothing under the engine may reclaim it.
        """
        assert not (ENGINE / "vault_scope.py").exists(), (
            "engine/vault_scope.py shadows the vault owner's config on sys.path; "
            "resolution anchors on the vault root instead"
        )
