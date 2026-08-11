#!/usr/bin/env python3
"""Post-edit hook: auto-format and lint edited files with whatever toolchain is
present — Ruff (Python), Prettier (web/markup/config), ESLint (JS/TS), Stylelint
(CSS). Each tool is guarded by file extension and no-ops when the tool is absent,
so the single workbench hook covers every project type the old per-preset hooks
did (Ruff-only / +Prettier / +ESLint+Stylelint) without misformatting a project
that lacks a given tool."""

# scripts/stamp.py reads this to generate hooks/hooks.json.
WORKSHOP_HOOK = {"event": "PostToolUse", "matcher": "edit|write|multi_edit|Edit|Write|MultiEdit"}

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    # Fail open: a malformed/empty stdin payload should no-op, not traceback.
    sys.exit(0)

if not isinstance(data, dict):
    # Fail open: a payload that isn't a JSON object isn't ours to act on.
    sys.exit(0)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path:
    sys.exit(0)

actions = []


def run(cmd, label):
    """Run a command silently, ignoring failures (missing tool or nonzero exit)."""
    try:
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            actions.append(label)
    except FileNotFoundError:
        pass


# Ruff on Python files
if file_path.endswith(".py") and shutil.which("ruff"):
    run(["ruff", "check", "--fix", file_path], "ruff-check")
    run(["ruff", "format", file_path], "ruff-format")

_PRETTIER_CONFIG_NAMES = (
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.json5",
    ".prettierrc.yml",
    ".prettierrc.yaml",
    ".prettierrc.toml",
    ".prettierrc.js",
    ".prettierrc.cjs",
    ".prettierrc.mjs",
    "prettier.config.js",
    "prettier.config.cjs",
    "prettier.config.mjs",
    "prettier.config.ts",
    "prettier.config.cts",
    "prettier.config.mts",
)


def prettier_is_configured(path):
    """True when some ancestor directory declares a Prettier config.

    Prettier is the only tool this hook runs that acts on a project which never
    asked for it. Ruff is guarded by ``shutil.which``; ESLint and Stylelint need
    their own config to do anything. Prettier formats happily with built-in
    defaults, and ``npx --no-install`` resolves it from the machine-wide npx
    cache once anything has ever pulled it — so an unguarded ``--write`` rewrote
    Markdown and JSON in EVERY repo on the machine, including repos whose own
    gate checks neither file type, where the change is unreviewed and uncaught.
    Observed: a one-word Markdown edit in a uv/Python repo came back with 17
    changed lines, de-indenting list continuations and flipping ``*em*`` to
    ``_em_`` in prose the edit never touched.

    That violates this module's own stated contract — "without misformatting a
    project that lacks a given tool". Tool PRESENCE was guarded; project OPT-IN
    was not, and for Prettier those are different questions.

    Mirrors Prettier's own upward config search, including the ``prettier`` key
    in ``package.json``. Deliberately NOT ``.editorconfig``: Prettier reads it
    for a few options, but its presence signals nothing about wanting Prettier —
    plenty of repos carry one and have never used it. A bare ``package.json``
    likewise means "this is a Node project", not "format my Markdown".

    Escape hatch for a project that wants the old behavior: an empty
    ``.prettierrc`` containing ``{}``.
    """
    directory = os.path.dirname(os.path.abspath(path))
    while True:
        for name in _PRETTIER_CONFIG_NAMES:
            if os.path.exists(os.path.join(directory, name)):
                return True
        package_json = os.path.join(directory, "package.json")
        if os.path.exists(package_json):
            try:
                with open(package_json, encoding="utf-8") as handle:
                    if "prettier" in json.load(handle):
                        return True
            except (OSError, ValueError):
                # A malformed or unreadable package.json is not an opt-in, and
                # must not take the hook down — keep searching upward.
                pass
        parent = os.path.dirname(directory)
        if parent == directory:
            return False
        directory = parent


# Prettier on web, markup, and config files — only where the project declares a
# Prettier config (npx --no-install no-ops if absent)
if file_path.endswith(
    (".html", ".css", ".js", ".ts", ".jsx", ".tsx", ".md", ".json")
) and prettier_is_configured(file_path):
    run(["npx", "--no-install", "prettier", "--write", file_path], "prettier")

# ESLint on JS/TS files
if file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
    run(["npx", "--no-install", "eslint", "--fix", file_path], "eslint")

# Stylelint on CSS files
if file_path.endswith(".css"):
    run(["npx", "--no-install", "stylelint", "--fix", file_path], "stylelint")

if actions:
    print(f"Hook ran: {', '.join(actions)} on {os.path.basename(file_path)}", file=sys.stderr)
