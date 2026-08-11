#!/usr/bin/env python3
"""SessionEnd hook: warn when a session ends with HEAD off the repo's trunk branch.

A nightly `afk` run refuses to proceed unless HEAD already sits on the repo's
trunk branch (issue #561) — it will not reset a checkout it doesn't own. That
guard is correct, but it gives no signal at the moment a session leaves HEAD
elsewhere: on `main` after a promotion sync, or on a feature branch left
mid-work. The cost lands hours later, in a nightly log nobody reads.

This hook is warn-only: it prints to stderr and always exits 0. `SessionEnd`
does not exist on Codex (COMPATIBILITY.md), so the hook is inert there.

Reads the *target repo's* `.afk/config.toml` — a repo without that file is not
afk-enrolled and gets nothing. `[hooks] warn_off_trunk = false` opts a repo
out (default on when the key is absent); the top-level `trunk_branch` key
names the trunk (default `"main"` when absent — no branch name is hardcoded
as *the* trunk, since it varies per repo).

Fails open everywhere: no git, no `.afk/config.toml`, malformed TOML, detached
HEAD, or a linked worktree checkout all exit 0 silently. Any other exception
also exits 0 — a hook that breaks session end is worse than the bug it reports.
"""

# scripts/stamp.py reads this declaration to generate hooks/hooks.json.
WORKSHOP_HOOK = {"event": "SessionEnd"}

import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

raw_payload = sys.stdin.read()
if not raw_payload.strip():
    data = {}
else:
    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError:
        sys.exit(0)
    if not isinstance(data, dict):
        # Fail open: a payload that isn't a JSON object isn't ours to act on.
        sys.exit(0)

cwd = Path(data.get("cwd") or ".").resolve()


def _git(*args: str):
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


try:
    repo_root = _git("rev-parse", "--show-toplevel")
    if repo_root is None:
        sys.exit(0)

    config_path = Path(repo_root) / ".afk" / "config.toml"
    if not config_path.exists():
        sys.exit(0)

    with config_path.open("rb") as f:
        config = tomllib.load(f)

    hooks_config = config.get("hooks")
    warn_off_trunk = (
        hooks_config.get("warn_off_trunk") if isinstance(hooks_config, dict) else None
    )
    if warn_off_trunk is False:
        sys.exit(0)

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch is None or branch == "HEAD":
        sys.exit(0)  # detached HEAD

    git_dir = _git("rev-parse", "--git-dir")
    common_dir = _git("rev-parse", "--git-common-dir")
    if git_dir is None or common_dir is None:
        sys.exit(0)
    if (cwd / git_dir).resolve() != (cwd / common_dir).resolve():
        sys.exit(0)  # linked worktree — not the checkout the nightly resets

    trunk = config.get("trunk_branch")
    trunk = trunk if trunk is not None else "main"

    if branch == trunk:
        sys.exit(0)

    print(
        f"warn-off-trunk: session ended on '{branch}', not the trunk branch "
        f"'{trunk}'. The afk nightly will refuse to run until HEAD is back on "
        f"'{trunk}'.",
        file=sys.stderr,
    )
    sys.exit(0)
except Exception:
    sys.exit(0)
