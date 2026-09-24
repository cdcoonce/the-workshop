"""Resolve the vault sync target: the remote branch session work integrates into.

Every vault sync path once took that from HEAD's short branch name, which is
only true in the primary checkout on ``main``. The desktop app runs sessions in
linked worktrees on unpublished ``claude/*`` branches, and Codex runs them on a
detached HEAD; there the branch name names nothing on the remote, so pulls
failed, the entry-replay fallback refused, the sync-boundary squash rewrote
commits the remote already had, and a bare ``git push`` stranded wrap-ups on
stray remote branches. One rule now answers for every path:

1. HEAD is on a branch whose configured upstream is on ``remote`` -> that
   branch. Read from ``branch.<name>.remote``/``.merge``, never ``@{u}``, which
   fails whenever the remote-tracking ref is missing.
2. HEAD is on a branch that exists on ``remote`` under its own name (fresh
   ``ls-remote``) -> that branch.
3. Otherwise -- a detached HEAD or an unpublished branch -> ``remote``'s
   default branch, read fresh from ``ls-remote --symref <remote> HEAD``. When
   the remote names none, the target is unresolved: ``main`` is never guessed
   and a possibly stale ``refs/remotes/<remote>/HEAD`` is never trusted.

Rules 1-2 reproduce the old answer wherever it worked; rule 3 fires only where
the branch name pointed at nothing.

Each skill ships self-contained, so this file exists byte-for-byte in both
``vault-sync/scripts/`` and ``vault-wrap-up/scripts/``; a root test enforces the
identity, and the engine's ``sync_manager`` holds the same rule inline, bound to
it by a shared behavior matrix.

Run directly, it prints the resolved target for /sync's pull and push steps.
Exit codes: 0 resolved, 1 unresolved, 2 usage errors.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_HEADS = "refs/heads/"


class UnresolvedTarget(RuntimeError):
    """No rule could name the branch this checkout's work integrates into."""


@dataclass(frozen=True)
class SyncTarget:
    """Where this checkout's session work goes.

    ``branch`` is the local branch (None when HEAD is detached) -- the one a
    rewrite moves. ``target`` is the branch on the remote that pulls rebase
    onto and pushes land on. ``source`` names the rule that chose it:
    ``upstream``, ``same-name``, or ``remote-default``.
    """

    branch: str | None
    target: str
    source: str


def _git(args: list[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def resolve(remote: str = "origin", cwd: Path | None = None) -> SyncTarget:
    """Resolve the sync target for the checkout at ``cwd``.

    Parameters
    ----------
    remote:
        Remote whose branches the session integrates with.
    cwd:
        Directory inside the checkout; None means the process working directory.

    Returns
    -------
    SyncTarget
        The local branch, the remote target branch, and the rule that chose it.

    Raises
    ------
    UnresolvedTarget
        When ``ls-remote`` fails or the remote names no default branch.
    """
    head = _git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
    branch = head.stdout.strip() if head.returncode == 0 else None

    if branch:
        up_remote = _git(["config", "--get", f"branch.{branch}.remote"], cwd).stdout.strip()
        up_merge = _git(["config", "--get", f"branch.{branch}.merge"], cwd).stdout.strip()
        if up_remote == remote and up_merge.startswith(_HEADS):
            return SyncTarget(branch, up_merge[len(_HEADS):], "upstream")

        ref = _HEADS + branch
        listed = _git(["ls-remote", "--", remote, ref], cwd)
        if listed.returncode != 0:
            raise UnresolvedTarget(
                f"fresh ls-remote of {remote} failed ({listed.stderr.strip() or 'no output'})"
            )
        if any(line.partition("\t")[2] == ref for line in listed.stdout.splitlines()):
            return SyncTarget(branch, branch, "same-name")

    symref = _git(["ls-remote", "--symref", "--", remote, "HEAD"], cwd)
    if symref.returncode != 0:
        raise UnresolvedTarget(
            f"fresh ls-remote of {remote} failed ({symref.stderr.strip() or 'no output'})"
        )
    for line in symref.stdout.splitlines():
        if not line.startswith("ref: "):
            continue
        name, _, what = line[len("ref: "):].partition("\t")
        if what == "HEAD" and name.startswith(_HEADS):
            return SyncTarget(branch, name[len(_HEADS):], "remote-default")
    where = f"branch {branch!r} has no upstream and" if branch else "HEAD is detached and"
    raise UnresolvedTarget(f"{where} {remote} names no default branch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the remote branch this checkout's vault session work integrates into."
    )
    parser.add_argument("--remote", default="origin", help="remote to resolve against")
    args = parser.parse_args(argv)

    if _git(["rev-parse", "--git-dir"], None).returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        return 2
    try:
        found = resolve(args.remote)
    except UnresolvedTarget as exc:
        print(json.dumps({"remote": args.remote, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"remote": args.remote, **asdict(found)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
