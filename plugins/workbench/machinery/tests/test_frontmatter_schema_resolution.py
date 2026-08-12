"""The vault owner's `frontmatter_schema.json` must actually reach the engine.

Same shape as #691, a different mechanism. `vault_scope` was resolved by module
NAME and lost to a shipped module of the same name; the note-type schema is
resolved by a DIRECTORY relative to the engine's own `__file__`. Before the flat
reorg those were the same place — the engine was vendored into the vault, so
"next to the engine" *was* "in the vault". Afterwards the engine lives in the
installed plugin, and the lookup resolves inside the plugin's own payload: a
directory no owner writes to, where the file can never exist. The
`path.exists()` check then fails and the loader falls back to the shipped
defaults, silently (#696).

Every assertion here spawns a REAL subprocess. In-process assertions cannot do
this honestly: the resolved table is built once and cached, so a value cached by
an earlier test would decide the outcome instead of the lookup, which is the
whole subject. The prior guard called `load_note_type_schemas(config_dir=...)`
with an explicit path — an input that cannot separate "the owner's file was
found" from "the caller was told where to look", so it passed under both while
production found nothing.

Assertions are on the VALUE the engine resolves, never on the machinery meant to
deliver it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MACHINERY = Path(__file__).resolve().parent.parent
ENGINE = MACHINERY / "engine"

# A note type deliberately unlike any shipped default, so a passing assertion
# can only mean the owner's file was the source.
SENTINEL_TYPE = "sentinel-note-type"
SENTINEL_FIELDS = ["sentinel_field"]
OWNER_SCHEMA = {SENTINEL_TYPE: SENTINEL_FIELDS}

# A shipped default the owner's file does NOT define. The owner's schema
# replaces the table wholesale, so this must be ABSENT once the override
# arrives — which is what separates "the owner's file was read" from "the
# sentinel leaked in on top of the defaults".
SHIPPED_TYPE = "competency"


def _make_vault(root: Path, *, schema: str | None = json.dumps(OWNER_SCHEMA)) -> Path:
    """A directory shaped like a vault, optionally carrying an owner schema.

    `.vault/vault.json` is the marker deliberately: it is what
    `run-vault-hook.sh` walks up for and what `find_vault_root` keys on, and
    unlike a note-directory signature it assumes no particular taxonomy.
    """
    (root / ".vault").mkdir(parents=True, exist_ok=True)
    (root / ".vault" / "vault.json").write_text(
        '{"vault": "test", "plugin": "workbench", "min_plugin_version": "5.0.0"}\n',
        encoding="utf-8",
    )
    if schema is not None:
        config_dir = root / ".vault" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "frontmatter_schema.json").write_text(schema, encoding="utf-8")
    return root


_PROBE = """\
import sys
sys.path.insert(0, {engine!r})   # exactly what every vault hook entry point does
import frontmatter_engine
print(repr(sorted(frontmatter_engine.TYPE_FIELDS)))
"""


def _resolve(
    *,
    cwd: Path,
    vault: Path | None = None,
    set_pythonpath: bool = True,
    set_project_dir: bool = True,
) -> subprocess.CompletedProcess:
    """Resolve the note-type table in a fresh interpreter, hook-style.

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
        [sys.executable, "-c", _PROBE.format(engine=str(ENGINE))],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )


class TestOwnerSchemaReachesTheEngine:
    """The override has to survive the arrangement a real hook produces."""

    def test_owner_schema_replaces_the_shipped_table(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path / "vault")
        result = _resolve(cwd=vault, vault=vault)

        assert result.returncode == 0, result.stderr
        assert SENTINEL_TYPE in result.stdout, (
            "the owner's frontmatter_schema.json did not reach the engine; got "
            f"{result.stdout.strip()!r}"
        )
        assert SHIPPED_TYPE not in result.stdout, (
            "the owner's schema must REPLACE the shipped table, not merge with it"
        )

    def test_override_survives_without_pythonpath(self, tmp_path: Path) -> None:
        """Resolution must not depend on the ambient path at all.

        The owner config directory is on `PYTHONPATH` for `vault_scope`'s sake,
        which is an import-system concern. A JSON file is read by path and has
        no business depending on it — so an engine script run straight from a
        CLI, or a hook invoked by some other route, gets the owner's schema too.
        """
        vault = _make_vault(tmp_path / "vault")
        result = _resolve(cwd=vault, vault=vault, set_pythonpath=False)

        assert result.returncode == 0, result.stderr
        assert SENTINEL_TYPE in result.stdout

    def test_override_found_by_walking_up_from_a_subdirectory(
        self, tmp_path: Path
    ) -> None:
        """Sessions routinely start below the vault root, not at it."""
        vault = _make_vault(tmp_path / "vault")
        nested = vault / "work" / "active" / "some-project"
        nested.mkdir(parents=True)
        result = _resolve(cwd=nested, vault=vault, set_project_dir=False)

        assert result.returncode == 0, result.stderr
        assert SENTINEL_TYPE in result.stdout


class TestFallbackStaysSilentWhereItShould:
    """Two legitimate states resolve to the shipped defaults without complaint."""

    def test_a_vault_with_no_owner_schema_uses_the_defaults(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path / "vault", schema=None)
        result = _resolve(cwd=vault, vault=vault)

        assert result.returncode == 0, result.stderr
        assert SHIPPED_TYPE in result.stdout
        assert SENTINEL_TYPE not in result.stdout

    def test_importing_the_engine_outside_any_vault_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """The engine is imported by tooling that runs nowhere near a vault."""
        elsewhere = tmp_path / "not-a-vault"
        elsewhere.mkdir(parents=True)
        result = _resolve(cwd=elsewhere, vault=None)

        assert result.returncode == 0, result.stderr
        assert SHIPPED_TYPE in result.stdout


class TestMalformedOwnerSchemaStillFailsClosed:
    """Fail-closed here is deliberate, and opposite to the scope resolver.

    `vault_scope_resolved` degrades to defaults and reports, because a hook must
    not die on the owner's typo. This one raises: ignoring a broken schema would
    validate every custom note type against nothing, which looks exactly like a
    clean vault. That difference is intentional and must survive the move to
    vault-root resolution.
    """

    def test_malformed_json_raises_and_names_the_file(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path / "vault", schema="{not valid json")
        result = _resolve(cwd=vault, vault=vault)

        assert result.returncode != 0, (
            "a malformed owner schema must not be swallowed; got "
            f"{result.stdout.strip()!r}"
        )
        assert "frontmatter_schema.json" in result.stderr

    def test_wrong_shape_raises_and_names_the_file(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path / "vault", schema=json.dumps(["not", "a", "map"]))
        result = _resolve(cwd=vault, vault=vault)

        assert result.returncode != 0
        assert "frontmatter_schema.json" in result.stderr

    def test_a_broken_schema_is_distinguishable_from_an_absent_one(
        self, tmp_path: Path
    ) -> None:
        """The #691 distinction, restated for this loader.

        "Exists but unreachable" must never look like "absent". Here the two
        states are separated by outcome, not by a log line: absent resolves
        clean to the defaults, broken exits non-zero naming the file.
        """
        broken = _resolve(
            cwd=_make_vault(tmp_path / "broken", schema="{"),
            vault=tmp_path / "broken",
        )
        absent = _resolve(
            cwd=_make_vault(tmp_path / "absent", schema=None),
            vault=tmp_path / "absent",
        )

        assert broken.returncode != 0
        assert absent.returncode == 0
        assert SHIPPED_TYPE in absent.stdout
