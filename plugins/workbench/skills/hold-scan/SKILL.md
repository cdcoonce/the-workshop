---
name: hold-scan
description: >
  Checks whether anyone recorded that a PR or MR must not land: thread text, afk:hold labels, and an optional notes vault. Use before merging any PR or MR, or before trusting a "ready to merge" brief. Read-only.
disable-model-invocation: true
---

# Hold scan

A merge brief grades the diff. A hold is usually recorded somewhere the diff
never shows: a PR conversation comment, a label on the closing issue, a line
in the owner's notes. On 2026-09-26 three agent PRs (cdcoonce/breakroom #112
and #142, and one in a private repo) merged against holds recorded only in
prose. This skill reads those places, deterministically, before the merge.

It makes no LLM call, imports only the standard library, and writes nothing.
The only network use is the `gh`/`glab` reads listed below.

## Run it

```bash
python3 "<skill base dir>/scripts/hold_scan.py" --repo OWNER/NAME --pr N --json
python3 "<skill base dir>/scripts/hold_scan.py" --gitlab GROUP/PROJECT --mr N --json
```

`<skill base dir>` is the absolute path this skill's loader announces. Without
`--json` it prints a short human summary.

| Exit | Verdict         | Meaning                                                                    |
| ---- | --------------- | -------------------------------------------------------------------------- |
| `1`  | `HOLD-FOUND`    | at least one hit, even if another call failed (the failure is in `scanned`) |
| `2`  | `SCAN-ERROR`    | no hit, but a call failed: the answer is unknown, never read it as clear    |
| `0`  | `NO-HOLD-FOUND` | every source read, nothing found                                            |

## Output

`--json` prints exactly four top-level keys.

- `verdict`: as above.
- `hits`: each is `{source, url_or_path, quote, timestamp}`. `source` is `thread`, `label` or `vault`. `timestamp` is null for `label` and `vault`.
- `acknowledgement`: `{url_or_path, timestamp}` of the newest PR/MR conversation comment whose first line starts with `hold-scan: acknowledged`, else null. The scanner only reports it and never counts it as a hit. What an acknowledgement clears is the consumer's policy (the refuse-held-merge hook), not this script's.
- `scanned`: one `{name, status, detail}` per source. `status` is `read`, `skipped`, `failed` or `info`. A failed entry's `name` is the exact command. `stale-no-thread` (`info`) marks an open PR over 14 days old with no comments, reviews or inline comments; it never changes the verdict.

## Sources

1. **Thread text.** Conversation comments, reviews and inline review comments (GitLab: non-system MR notes), paged 100 at a time until a short page. A body is a hit on `holding (this|it)|do not merge|don't merge|not merg(e|ing)|unmerged`, case-insensitive. The quote is the matching line.
   - Never add `blocked`, `regression`, `frozen` or `held`. Measured on 717 `afk/*` PRs: 52 of 58 `blocked` hits were afk's "Reviewer advisory (non-blocking)" header, and `regression` was a hold in 1 of 26.
   - Closing issues' comments are not read. Their precision was never measured, and issue threads carry spec-review verdicts. An unmeasured source is not armed.
2. **Labels.** `afk:hold` on a closing issue, or on a `Depends on` target of one (one level deep), is a hit. `requires:human` never is.
3. **Vault (optional).** Resolved by walking up from `CLAUDE_PROJECT_DIR` (else `PWD`) for `.vault/vault.json`, else `vault_root` in `~/.workshop/hold-scan/hold-scan.toml`, else skipped. The skill works on a machine with no vault. A configured `vault_root` without `.vault/vault.json`, or malformed TOML, is a failed call.
   - Scope is two places: the `## Current Status` section of each note whose frontmatter `repo:` or `description:` contains `OWNER/NAME`, and each `### ` entry of `brain/Key Decisions.md` naming the repo (or an alias) as a whole word.
   - A hit is a paragraph holding a searched number (the PR, its closing issues, their `Depends on` targets) and a hold word (`held|hold|holding|frozen|freeze|reserv*|do not merge|revert*`). A number counts only whole (`#23` is not `#236`) and only bare or prefixed by the repo name or an alias (`hcc#42` is never household-app's).
   - Config shape: top-level `vault_root = "/abs/path"`, and `[aliases]` keyed by repo NAME, e.g. `household-app = ["happ"]`.

## Known false positive

Not fixed, recorded: on the real vault a ragmark decision entry names #114 in a
paragraph containing "frozen corpus", so ragmark PR #129 (which closes #114)
gets a vault hit. A vault hit is evidence to read, not a verdict. Read the
quoted paragraph before deciding.

## What this skill does not do

No hook (the merge hook is a consumer of this output), no acknowledgement
policy, no write to GitHub, GitLab or the vault, and no wiring into other
skills.
