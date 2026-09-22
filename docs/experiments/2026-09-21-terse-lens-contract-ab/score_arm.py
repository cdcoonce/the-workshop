"""Score one arm of the terse-lens-contract A/B from saved raw lens outputs.

Reads ``<raw dir>/<lens>-r<rep>.txt`` (the verbatim final reply of each lens
subagent), and emits two harness-consumable case files:

- output volume:  one case per (lens, rep), score = -len(reply) in characters,
  so a higher score means less reviewer output and the paired delta (b - a)
  is the savings.
- detection:      one case per (defect, rep), score = 1.0 when any finding
  from that rep's three lenses matches the defect, else 0.0.

Matching rule (fixed pre-run; also documented in fixture/defects.json): a
finding matches a defect when its file endswith file_suffix AND (its line
falls inside line_window OR regex matches its description, case-insensitive).
When line_window is null the file requirement is dropped and the regex runs
against description and file together (D4 is any touch of the anti-scope
file; D5 is an absence with no line to cite).

A reply with no parseable JSON object counts as zero findings and its parse
failure is recorded in the emitted JSON under ``parse_errors``; its character
count still scores the output metric.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LENSES = ("domain", "test_veracity", "spec_conformance")


def extract_findings(text: str) -> tuple[list[dict], bool]:
    """Pull the findings list from the first JSON object in ``text``."""
    candidates = []
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates.extend(fenced)
    brace = text.find("{")
    if brace != -1:
        candidates.append(text[brace : text.rfind("}") + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        findings = obj.get("findings")
        if isinstance(findings, list):
            rows = [f for f in findings if isinstance(f, dict)]
            return rows, True
    return [], False


def finding_matches(finding: dict, defect: dict) -> bool:
    file_str = str(finding.get("file", ""))
    desc = str(finding.get("description", ""))
    regex = re.compile(defect["regex"], re.IGNORECASE)
    window = defect.get("line_window")
    if window is None:
        return bool(regex.search(desc + " " + file_str))
    if not file_str.endswith(defect["file_suffix"]):
        return False
    line = finding.get("line")
    in_window = isinstance(line, (int, float)) and window[0] <= int(line) <= window[1]
    return in_window or bool(regex.search(desc))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, help="directory of <lens>-r<rep>.txt files")
    parser.add_argument("--defects", required=True)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--out-output", required=True)
    parser.add_argument("--out-detection", required=True)
    args = parser.parse_args()

    raw_dir = Path(args.raw)
    defects = json.loads(Path(args.defects).read_text())["defects"]

    output_cases: list[dict] = []
    detection_cases: list[dict] = []
    parse_errors: list[str] = []

    for rep in range(1, args.reps + 1):
        pooled: list[dict] = []
        for lens in LENSES:
            path = raw_dir / f"{lens}-r{rep}.txt"
            text = path.read_text()
            output_cases.append({"key": f"{lens}:r{rep}", "score": -len(text)})
            findings, ok = extract_findings(text)
            if not ok:
                parse_errors.append(str(path))
            pooled.extend(findings)
        for defect in defects:
            hit = any(finding_matches(f, defect) for f in pooled)
            detection_cases.append({"key": f"{defect['id']}:r{rep}", "score": 1.0 if hit else 0.0})

    Path(args.out_output).write_text(
        json.dumps({"cases": output_cases, "parse_errors": parse_errors}, indent=2)
    )
    Path(args.out_detection).write_text(
        json.dumps({"cases": detection_cases, "parse_errors": parse_errors}, indent=2)
    )
    print(
        f"scored {len(output_cases)} output cases, {len(detection_cases)} detection cases, "
        f"{len(parse_errors)} parse errors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
