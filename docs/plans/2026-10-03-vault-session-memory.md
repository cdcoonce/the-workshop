# Vault session memory boundaries

## Problem and scope

Two observed failures affect session continuity. The notebook parser accepts
Claude transcripts but returns empty text for native Codex `response_item`
messages. SessionStart chooses the newest same-context notebook regardless of
its session, reproducing the existing [the-vault#111](https://github.com/cdcoonce/the-vault/issues/111).

The approved local fix retains the existing notebook API and the current
freshness, handoff and skeleton checks. It adds native Codex message parsing and
limits startup notebook selection to the exact current session identity. No
predecessor mapping is established in the repository; when a clear or new session
has no usable own notebook, the curated handoff remains the fallback. Filesystem
recency alone is not evidence of session continuity.

## Implementation and verification

1. Add a failing native Codex transcript regression, then support its
   `response_item` / `message` envelope and `input_text` / `output_text` blocks.
   Retain Claude parsing; ignore duplicate event messages and non-conversation
   records. Cover malformed records and existing truncation behavior.
2. Add a failing startup test with an own notebook and a fresher foreign
   notebook, then select only the exact current identity. Cover missing or
   invalid identities, context boundaries, skeletons and freshness fallbacks.
3. Run focused notebook/startup tests and the machinery suite. Startup tests use
   temporary vaults and replace sync and unrelated context providers; they never
   run live hooks, contact a remote or invoke a model.

No installed cache, live registration, notebook retention, plugin provenance
or sync-policy changes belong to this slice. The coordinating
agent owns the plugin version, generated files and full delivery gate. No
commit, push or deployment is authorized by this plan.

## Local result

Implemented the adapter and ownership boundary. The parser also exposes
`latest_turn_from_text` so a notebook worker can hash and parse one transcript
snapshot; `valid_session_id` is shared with writers to keep their identity
boundary consistent.

Observed red cases before the corresponding fixes: native Codex text returned
`("", "")`; a non-object JSON record raised `AttributeError`; startup emitted the
fresher foreign notebook; eight missing/invalid identities emitted unowned files.
The final focused run passed **39 tests** across `test_notebook_core.py`,
`test_notebook_distill.py` and `test_session_start_ownership.py`, using cached
machinery Python with `-B -m pytest -q -p no:cacheprovider`. A read-only probe of
the real Codex rollout now returns nonempty user and assistant text. Combined
machinery and delivery gates remain with the coordinating agent.

## Approved addendum: enforce the digest byte ceiling

The audit's byte-budget defect was authorized as a further bounded fix.
`context_loader.py` compared UTF-8 bytes but clipped characters, then appended an
unbudgeted notice. New CJK/emoji fixtures failed at 16,051 and 21,356 bytes against
the declared 8,000-byte ceiling.

The section allocation now reserves UTF-8 bytes for the notice and separators;
content clipping includes its ellipsis and never splits a code point. Ordinary
headings remain visible. If a heading exceeds its section allowance, it is
clipped; when the number of headings exhausts the allowance, empty clipped
sections are omitted. An oversized source notice is also clipped. The strict
bound takes priority in these exceptional inputs; no new content-priority or
overall SessionStart budgeting policy is introduced.

The context-loader suite passes **48 tests**, including strict CJK/emoji bounds,
idempotence, normal heading preservation, small Unicode no-op behavior, oversized
headings/notices and excessive section counts. The excessive-heading case first
exposed and then verified the fix for a leading-space idempotence defect in the
new clipper. A further 84 pure in-memory boundary probes all respected the limit
and idempotence. Existing loose byte assertions were tightened to exactly 8,000.
