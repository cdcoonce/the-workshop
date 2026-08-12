"""Every `make` target this repo tells anyone to run must actually exist.

Shipped skills are executed literally. `workshop-skill-creator` and
`land-skill-candidate` both *end* on `make docs` / `make build`, so the last
thing either skill did was fail with "No rule to make target" — and the reader
was out of instructions at exactly the point they needed one (#703).

The dead targets are reorg residue. `make docs` rendered the reference catalogs
and `make build` composed every preset into `dist/`; #650/#656 deleted `dist/`
and collapsed both into `scripts/stamp.py`. The Makefile was updated. The prose
telling people to invoke it was not, and nothing connected the two: `make test`
runs the targets that exist and never reads the sentences naming them.

Two decisions make this checkable at all:

* **The valid set is PARSED from the Makefile**, never restated. A second
  hand-kept list would drift exactly the way the prose did, and would let this
  file pass while describing a Makefile that no longer exists.
* **Only backticked invocations count.** An earlier draft matched `make\\s+<word>`
  anywhere and read `make sure the branch is clean`, `make their intent
  explicit`, and other projects' `make all` in imported design docs as calls
  into this Makefile. Enumerating the English that can follow "make" is not a
  winnable list. A backtick is the author saying "this is a literal command",
  which is precisely the claim that has to be true.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

# A span between backticks — the author's own marker that this is a command.
BACKTICKED = re.compile(r"`([^`]+)`")
# `make <target>` inside such a span. Findall, not match: one span can carry a
# chain (`make docs && make build`), and every link in it has to resolve.
MAKE_TARGET = re.compile(r"\bmake\s+([a-z][a-z0-9-]*)")
# The imperative form, for places backticks cannot reach — chiefly a test's
# failure message, which is a Python string and marks nothing up. "run make X"
# is as unambiguous an instruction as a backtick, and it is what
# `test_machinery_wiring`'s freshness assertion hands a developer mid-failure.
RUN_MAKE = re.compile(r"\brun\s+`?make\s+([a-z][a-z0-9-]*)")


def _targets_in_line(line: str) -> list[str]:
    """Every make target this line instructs someone to run.

    Two forms, both explicit: inside backticks, or after the word "run". An
    earlier draft matched `make\\s+<word>` bare and read `make sure the branch
    is clean` and other projects' `make all` as calls into this Makefile.
    """
    found = [
        target for span in BACKTICKED.findall(line) for target in MAKE_TARGET.findall(span)
    ]
    found.extend(RUN_MAKE.findall(line))
    return found

# Where a documented command reaches someone who will run it: shipped plugin
# payload, the repo's operating docs, and the generated-reference tree.
#
# `docs/plans/`, `docs/archive/`, `docs/brainstorms/`, and `docs/superpowers/`
# are deliberately out of scope. They are historical records and imported
# design notes — `docs/superpowers/plans/` describes another project's `make
# all` — and rewriting a historical document to satisfy a lint would falsify
# the record rather than fix anything.
SCANNED_ROOTS = (
    "plugins",
    "docs/reference",
    "tests",
    "README.md",
    "CLAUDE.md",
    "COMPATIBILITY.md",
    "ROADMAP.md",
)

TEXT_SUFFIXES = {".md", ".py", ".sh", ".toml", ".txt", ".yml", ".yaml"}
SKIP_PARTS = {"__pycache__", ".venv"}


def makefile_targets() -> set[str]:
    """Every target the Makefile actually declares.

    Read off the Makefile so removing or renaming a target immediately turns
    the documentation naming it red, rather than leaving this assertion
    describing a Makefile that is no longer there.
    """
    targets = set()
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-zA-Z][a-zA-Z0-9_-]*)\s*:(?!=)", line)
        if match:
            targets.add(match.group(1))
    targets.discard("PHONY")
    if not targets:  # pragma: no cover - a guard that parses nothing is the bug
        raise AssertionError(f"parsed no targets from {MAKEFILE}")
    return targets


def _scanned_files() -> list[Path]:
    """Every text file a documented command could reach a reader from."""
    files: list[Path] = []
    for entry in SCANNED_ROOTS:
        path = REPO_ROOT / entry
        if path.is_file():
            files.append(path)
            continue
        if not path.is_dir():
            continue
        files.extend(
            candidate
            for candidate in sorted(path.rglob("*"))
            if candidate.is_file()
            and candidate.suffix in TEXT_SUFFIXES
            and not SKIP_PARTS & set(candidate.parts)
        )
    return files


def find_unknown_targets() -> list[str]:
    """`path:line: make <target>` for every explicit call to a dead target.

    This file is the one exemption, and it has to be: its subject IS the
    targets that do not exist, so its docstring and its both-directions
    assertions name them on purpose. Scanning itself would make the guard
    permanently red on its own explanation.
    """
    valid = makefile_targets()
    seen: set[str] = set()
    findings: list[str] = []
    for path in _scanned_files():
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for target in _targets_in_line(line):
                if target in valid:
                    continue
                rel = path.relative_to(REPO_ROOT)
                # One line can match both arms (``run `make docs` ``); report
                # the site once rather than once per pattern that saw it.
                finding = f"{rel}:{lineno}: make {target}"
                if finding not in seen:
                    seen.add(finding)
                    findings.append(finding)
    return findings


def test_every_documented_make_target_exists() -> None:
    """No shipped instruction may name a target the Makefile does not have.

    This is #703. `make docs` and `make build` died with the composition build;
    three shipped `workshop-maintainer` skills kept telling agents to run them,
    and two of those skills end on that step.
    """
    findings = find_unknown_targets()

    assert not findings, (
        f"{len(findings)} documented command(s) name a make target that does "
        f"not exist. The Makefile declares: {', '.join(sorted(makefile_targets()))}. "
        "`make stamp` regenerates everything generated:\n  " + "\n  ".join(findings)
    )


def test_the_target_set_is_parsed_from_the_makefile() -> None:
    """Pin the parse in both directions, so it cannot pass by matching nothing.

    A parse returning everything waves through any string; one returning
    nothing raises. Between those sits the real risk — a pattern that silently
    drops real targets, so a correct `make stamp` reads as a defect and someone
    "fixes" working documentation.
    """
    targets = makefile_targets()

    assert {"stamp", "test", "lint", "stamp-check"} <= targets
    # The two the reorg deleted. If either is ever restored, this file should
    # stop flagging it — which is the point of parsing rather than hardcoding.
    assert "docs" not in targets
    assert "build" not in targets
    # `.PHONY` is a directive, not something anyone runs.
    assert "PHONY" not in targets


def test_the_scan_reaches_shipped_skills_and_repo_docs() -> None:
    """A scan that walks nothing reports success having read nothing."""
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _scanned_files()}

    assert "README.md" in scanned
    assert "plugins/workshop-maintainer/skills/land-skill-candidate/SKILL.md" in scanned
    assert "docs/reference/build-and-wiring.md" in scanned
    # The freshness failure message lives here — a Python string, not markup.
    assert "tests/test_machinery_wiring.py" in scanned


def test_only_explicit_invocations_are_read_as_commands() -> None:
    """Pin the narrowing in both directions.

    Bare English must not be read as a target — the first draft of this file
    flagged 40+ such lines across advisor skills and imported design docs,
    which would have meant rewriting correct prose to satisfy a lint. An
    explicit command on the same line still must be caught.
    """
    prose = "make sure the branch is clean and make their intent explicit"
    assert not _targets_in_line(prose)

    assert _targets_in_line("Run `make stamp && make test` before you make it final") == [
        "stamp",
        "test",
    ]
    # The imperative form, which is how a failure message phrases it.
    assert _targets_in_line("committed rendered/x is stale — run make stamp") == ["stamp"]
