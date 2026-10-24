#!/usr/bin/env python3
"""Deterministic pre-merge hold scanner.

Answers one question before a merge: has anyone recorded that this PR or MR
must not land? Reads PR/MR threads, closing-issue labels and, when one is
reachable, the owner's notes vault. No LLM call, no write, no network beyond
the ``gh``/``glab`` reads below. Standard library only.

Exit codes: 0 NO-HOLD-FOUND, 1 HOLD-FOUND, 2 SCAN-ERROR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

HOLD_FOUND = "HOLD-FOUND"
NO_HOLD_FOUND = "NO-HOLD-FOUND"
SCAN_ERROR = "SCAN-ERROR"
EXIT = {NO_HOLD_FOUND: 0, HOLD_FOUND: 1, SCAN_ERROR: 2}

# Measured 2026-09-26 over 717 afk/* PRs: recall 2/2, no false hit on a merged
# PR. Never add `blocked`, `regression`, `frozen` or `held` here: afk's own
# "Reviewer advisory (non-blocking)" header is 52 of 58 `blocked` hits.
THREAD_PATTERN = re.compile(r"holding (this|it)|do not merge|don['’]t merge|not merg(e|ing)|unmerged", re.I)
VAULT_HOLD_WORDS = re.compile(r"\b(held|hold|holding|frozen|freeze|reserv\w*|do not merge|revert\w*)\b", re.I)
ACK_PREFIX = "hold-scan: acknowledged"
HOLD_LABEL = "afk:hold"
STALE_AFTER = timedelta(days=14)
QUOTE_LIMIT = 300
PAGE_SIZE = 100
CONFIG_REL = Path(".workshop") / "hold-scan" / "hold-scan.toml"


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Run one ``gh``/``glab`` call. The single seam tests replace."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout, proc.stderr


def _now() -> datetime:
    """Current UTC time. The single clock tests replace."""
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Scan:
    """Accumulates hits, the acknowledgement and the scanned log for one run."""

    def __init__(self) -> None:
        self.hits: list[dict] = []
        self.acks: list[dict] = []
        self.scanned: list[dict] = []
        self.failed = False

    def note(self, name: str, status: str, detail: str) -> None:
        self.scanned.append({"name": name, "status": status, "detail": detail})

    def fail(self, name: str, detail: str) -> None:
        self.failed = True
        self.note(name, "failed", detail)

    def hit(self, source: str, url_or_path: str, quote_: str, timestamp: str | None) -> None:
        self.hits.append({"source": source, "url_or_path": url_or_path, "quote": quote_, "timestamp": timestamp})

    def call(self, argv: list[str]):
        """Run a call and parse its JSON stdout; record and return None on failure."""
        label = " ".join(argv)
        rc, out, err = _run(argv)
        if rc != 0:
            self.fail(label, f"exit {rc}: {err.strip()[:200]}")
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            self.fail(label, "output is not JSON")
            return None

    def pages(self, cli: str, endpoint: str):
        """Fetch ``endpoint`` page by page until a page has fewer than 100 items."""
        items: list = []
        page = 1
        while True:
            data = self.call([cli, "api", f"{endpoint}?per_page={PAGE_SIZE}&page={page}"])
            if not isinstance(data, list):
                if data is not None:
                    self.fail(f"{cli} api {endpoint}", "expected a JSON list")
                return None
            items.extend(data)
            if len(data) < PAGE_SIZE:
                return items
            page += 1


def _match_line(body: str) -> str | None:
    for line in body.splitlines():
        if THREAD_PATTERN.search(line):
            return line.strip()
    return None


def _is_ack(body: str) -> bool:
    return (body or "").split("\n", 1)[0].startswith(ACK_PREFIX)


def _later(created: str | None, updated: str | None) -> str | None:
    """The later of two timestamps, as the original string. An edit moves a hit forward."""
    a, b = _parse_ts(created), _parse_ts(updated)
    if a is None or (b is not None and b > a):
        return updated if b is not None else created
    return created


def _scan_texts(scan: Scan, items: list[dict], body_key: str, ts_key: str, url_of, can_ack: bool) -> None:
    """Turn thread items into hits and, for conversation comments, acknowledgements.

    A hit carries the later of its creation and ``updated_at`` time, so a hold edited
    into an old comment after an acknowledgement is not older than that acknowledgement.
    An acknowledgement keeps its creation time.
    """
    for item in items:
        body = item.get(body_key) or ""
        ts = item.get(ts_key)
        if can_ack and _is_ack(body):
            scan.acks.append({"url_or_path": url_of(item), "timestamp": ts})
            continue
        line = _match_line(body)
        if line is not None:
            scan.hit("thread", url_of(item), line, _later(ts, item.get("updated_at")))


def _depends_on(body: str) -> list[int]:
    nums: list[int] = []
    for line in (body or "").splitlines():
        m = re.match(r"^\s*(?:[-*]\s*)?(?:\*\*)?depends on\b(.*)$", line, re.I)
        if m:
            nums.extend(int(n) for n in re.findall(r"#(\d+)", m.group(1)))
    return nums


def _stale(scan: Scan, created: str | None, state: str | None, counts: list[int | None]) -> None:
    ts = _parse_ts(created)
    if ts is None or (state or "").lower() not in ("open", "opened"):
        return
    if any(c is None or c > 0 for c in counts):
        return
    if _now() - ts > STALE_AFTER:
        scan.note("stale-no-thread", "info", f"open since {created} with no conversation comments, reviews or inline comments")


# ---- GitHub -----------------------------------------------------------------


def scan_github(scan: Scan, repo: str, pr: int) -> list[int]:
    """Read a GitHub PR; return the searched numbers (the PR, closing issues, Depends-on targets)."""
    base = f"repos/{repo}"
    html = lambda it: it.get("html_url", "")  # noqa: E731
    counts: list[int | None] = []
    comments = scan.pages("gh", f"{base}/issues/{pr}/comments")
    counts.append(None if comments is None else len(comments))
    if comments is not None:
        _scan_texts(scan, comments, "body", "created_at", html, True)
        scan.note(f"{base}/issues/{pr}/comments", "read", f"{len(comments)} items")
    reviews = scan.pages("gh", f"{base}/pulls/{pr}/reviews")
    counts.append(None if reviews is None else len(reviews))
    if reviews is not None:
        _scan_texts(scan, reviews, "body", "submitted_at", html, False)
        scan.note(f"{base}/pulls/{pr}/reviews", "read", f"{len(reviews)} items")
    inline = scan.pages("gh", f"{base}/pulls/{pr}/comments")
    counts.append(None if inline is None else len(inline))
    if inline is not None:
        _scan_texts(scan, inline, "body", "created_at", html, False)
        scan.note(f"{base}/pulls/{pr}/comments", "read", f"{len(inline)} items")

    numbers = [pr]
    info = scan.call(["gh", "pr", "view", str(pr), "--repo", repo, "--json", "closingIssuesReferences,createdAt,state"])
    if info is not None:
        _stale(scan, info.get("createdAt"), info.get("state"), counts)
        for ref in info.get("closingIssuesReferences") or []:
            m = ref["number"]
            numbers.append(m)
            issue = _gh_issue(scan, repo, m, f"closing issue #{m}")
            if issue is None:
                continue
            for dep in _depends_on(issue.get("body") or ""):
                numbers.append(dep)
                _gh_issue(scan, repo, dep, f"#{dep} (Depends on of #{m})")
    return numbers


def _gh_issue(scan: Scan, repo: str, number: int, what: str):
    issue = scan.call(["gh", "issue", "view", str(number), "--repo", repo, "--json", "labels,body"])
    if issue is not None:
        names = [lab.get("name") for lab in issue.get("labels") or []]
        if HOLD_LABEL in names:
            scan.hit("label", f"https://github.com/{repo}/issues/{number}", f"{HOLD_LABEL} label on {what}", None)
    return issue


# ---- GitLab -----------------------------------------------------------------


def scan_gitlab(scan: Scan, project: str, mr: int) -> list[int]:
    """Read a GitLab MR; return the searched numbers."""
    base = f"projects/{quote(project, safe='')}"
    info = scan.call(["glab", "api", f"{base}/merge_requests/{mr}"])
    web = (info or {}).get("web_url", "")
    notes = scan.pages("glab", f"{base}/merge_requests/{mr}/notes")
    count = None
    if notes is not None:
        notes = [n for n in notes if not n.get("system")]
        count = len(notes)
        _scan_texts(scan, notes, "body", "created_at", lambda n: f"{web}#note_{n.get('id')}", True)
        scan.note(f"{base}/merge_requests/{mr}/notes", "read", f"{count} notes")
    if info is not None:
        _stale(scan, info.get("created_at"), info.get("state"), [count])
    numbers = [mr]
    closes = scan.pages("glab", f"{base}/merge_requests/{mr}/closes_issues")
    for issue in closes or []:
        m = issue.get("iid")
        numbers.append(m)
        if HOLD_LABEL in (issue.get("labels") or []):
            scan.hit("label", issue.get("web_url", ""), f"{HOLD_LABEL} label on closing issue #{m}", None)
        for dep in _depends_on(issue.get("description") or ""):
            numbers.append(dep)
            target = scan.call(["glab", "api", f"{base}/issues/{dep}"])
            if target is not None and HOLD_LABEL in (target.get("labels") or []):
                scan.hit("label", target.get("web_url", ""), f"{HOLD_LABEL} label on #{dep} (Depends on of #{m})", None)
    return numbers


# ---- Vault ------------------------------------------------------------------


def _walk_up(start: str) -> Path | None:
    p = Path(start).resolve()
    for d in (p, *p.parents):
        if (d / ".vault" / "vault.json").is_file():
            return d
    return None


def _load_config(scan: Scan) -> dict:
    cfg = Path(os.environ.get("HOME") or Path.home()) / CONFIG_REL
    if not cfg.is_file():
        return {}
    try:
        return tomllib.loads(cfg.read_text())
    except (tomllib.TOMLDecodeError, OSError) as exc:
        scan.fail(f"read {cfg}", f"malformed config: {exc}")
        return {}


def resolve_vault(scan: Scan, config: dict) -> Path | None:
    """Walk up for ``.vault/vault.json``, else ``vault_root`` from config, else None."""
    found = _walk_up(os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("PWD") or os.getcwd())
    if found is not None:
        scan.note("vault", "read", f"found by walk-up at {found}")
        return found
    root = config.get("vault_root")
    if root:
        root_path = Path(root)
        if (root_path / ".vault" / "vault.json").is_file():
            scan.note("vault", "read", f"found by config at {root_path}")
            return root_path
        scan.fail("vault", f"vault_root {root_path} lacks .vault/vault.json")
        return None
    scan.note("vault", "skipped", "no .vault/vault.json above the working directory and no vault_root configured")
    return None


def _frontmatter_owns(text: str, slug: str) -> bool:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        m = re.match(r"^(repo|description):\s*(.*)$", line)
        if m and slug in m.group(2):
            return True
    return False


def _section(text: str, start: re.Pattern, stop_prefixes: tuple[str, ...]) -> list[str]:
    """Return the body lines of each heading matching *start*, up to a stop heading."""
    out: list[str] = []
    cur: list[str] | None = None
    for line in text.splitlines():
        if cur is not None and line.startswith(stop_prefixes):
            out.append("\n".join(cur))
            cur = None
        if start.match(line):
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur is not None:
        out.append("\n".join(cur))
    return out


def _paragraphs(block: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", block) if p.strip()]


def _has_number(paragraph: str, numbers: set[int], prefixes: set[str]) -> bool:
    for m in re.finditer(r"#(\d+)", paragraph):
        if int(m.group(1)) not in numbers:
            continue
        run = re.search(r"[\w-]*$", paragraph[: m.start()]).group(0)
        if run:
            if run.lower() in prefixes:
                return True
            continue
        before = paragraph[m.start() - 1] if m.start() else ""
        if before not in ("-", "/"):
            return True
    return False


def scan_vault(scan: Scan, root: Path, slug: str, name: str, aliases: list[str], numbers: set[int]) -> None:
    """Scan the two vault scopes: status paragraphs, and open-hold entries in brain/Holds.md."""
    prefixes = {name.lower(), *(a.lower() for a in aliases)}

    def check(path: Path, block: str) -> None:
        for para in _paragraphs(block):
            if VAULT_HOLD_WORDS.search(para) and _has_number(para, numbers, prefixes):
                scan.hit("vault", str(path), para[:QUOTE_LIMIT], None)

    owned = 0
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if not _frontmatter_owns(text, slug):
            continue
        owned += 1
        for block in _section(text, re.compile(r"^## Current Status\s*$"), ("## ",)):
            check(path, block)
    scan.note("vault:owning-notes", "read", f"{owned} notes own {slug}")

    holds = root / "brain" / "Holds.md"
    if not holds.is_file():
        scan.note("vault:holds", "skipped", "brain/Holds.md not found")
        return
    names = "|".join(re.escape(n) for n in prefixes)
    word = re.compile(rf"\b(?:{names})\b", re.I)
    entries = _section(holds.read_text(errors="replace"), re.compile(r"^### "), ("### ", "## "))
    mine = [e for e in entries if word.search(e)]
    for entry in mine:
        if _has_number(entry, numbers, prefixes):
            scan.hit("vault", str(holds), entry.splitlines()[0].strip()[:QUOTE_LIMIT], None)
    scan.note("vault:holds", "read", f"{len(mine)} of {len(entries)} entries name {name}")


# ---- Driver -----------------------------------------------------------------


def run_scan(repo: str | None, pr: int | None, gitlab: str | None, mr: int | None) -> dict:
    scan = Scan()
    config = _load_config(scan)
    if gitlab:
        slug, numbers = gitlab, scan_gitlab(scan, gitlab, mr)
    else:
        slug, numbers = repo, scan_github(scan, repo, pr)
    name = slug.rsplit("/", 1)[-1]
    root = resolve_vault(scan, config)
    if root is not None:
        aliases = list((config.get("aliases") or {}).get(name, []))
        scan_vault(scan, root, slug, name, aliases, {n for n in numbers if isinstance(n, int)})
    if scan.hits:
        verdict = HOLD_FOUND
    elif scan.failed:
        verdict = SCAN_ERROR
    else:
        verdict = NO_HOLD_FOUND
    ack = max(scan.acks, key=lambda a: _parse_ts(a["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc), default=None)
    return {"verdict": verdict, "hits": scan.hits, "acknowledgement": ack, "scanned": scan.scanned}


def _summary(result: dict) -> str:
    lines = [f"hold-scan: {result['verdict']}"]
    for h in result["hits"]:
        lines.append(f"  [{h['source']}] {h['url_or_path']}: {h['quote']}")
    ack = result["acknowledgement"]
    if ack:
        lines.append(f"  acknowledgement: {ack['url_or_path']} ({ack['timestamp']})")
    for e in result["scanned"]:
        if e["status"] in ("failed", "skipped", "info"):
            lines.append(f"  {e['status']}: {e['name']} - {e['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan a PR/MR for recorded merge holds.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo", metavar="OWNER/NAME")
    target.add_argument("--gitlab", metavar="GROUP/PROJECT")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--mr", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.repo and args.pr is None:
        parser.error("--repo requires --pr")
    if args.gitlab and args.mr is None:
        parser.error("--gitlab requires --mr")
    result = run_scan(args.repo, args.pr, args.gitlab, args.mr)
    print(json.dumps(result, indent=2) if args.json else _summary(result))
    return EXIT[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
