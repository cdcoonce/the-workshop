# core/ — Shared Source

`core/` is the shared source every package builds from: universal skills, methodology docs, safety hooks, and agents. The build copies what each preset's manifest selects into `dist/<preset>/`, so one change here fans out to every package that includes it.

These two conventions govern edits under `core/`, and edits to any preset copy of something shared. Preset manifest fields and the agent `role` vocabulary stay in the root [CLAUDE.md](../CLAUDE.md).

## Syncing Shared Files Across core/ and Preset Copies

Some source files are duplicated between `core/` and one or more `presets/*/` directories (e.g. a skill or agent that every preset bundles a copy of). If you edit one of these shared/duplicated files, you must apply the same change to every copy — core and every preset that carries it — not just the copy you happened to open.

Before considering such a change done:

1. Edit the file identically in `core/` and in each preset copy.
2. Rebuild every preset: `uv run python -m scripts.build_preset <preset_name>` for each preset under `presets/`.
3. Run the smoke test on each rebuilt preset: `uv run python -m scripts.smoke_test <preset_name>`.
4. Confirm the rebuilt `dist/` output is byte-identical across preset copies of the shared file (e.g. via `diff`) — a change applied to only one copy will show up here as a divergence.

This convention exists because PR #142 fixed a bug in a shared file and had to keep all five `dist/` preset copies in sync with `core/`, verifying "every preset rebuilds byte-identically" before the fix was accepted. Skipping this step ships a fix to one copy while leaving the others silently stale.

Steps 2–4 are also machine-checked by `make verify-generated` (part of `make test`), which rebuilds every preset and fails on any `dist/` drift. Run it before you consider the change done; the manual `diff` above is the explanation of what the gate is checking, not a substitute for it.

## Output and Metadata Locations

Skills produce two kinds of output, and they go to two different places. Choosing
wrong either buries a repo artifact in a home directory or litters a target repo
with machine-local files.

1. **Repo-scoped artifacts** — output that describes, plans, or configures the
   target repository and is meant to be committed and reviewed alongside its code.
   These stay **inside the target repo** at their conventional paths:
   `docs/plans/` (plans), `docs/dev-cycle/*.state.md` and `docs/archive/`
   (dev-cycle state), `.claude/docs/project.md` (project context). Never relocate
   these to a home directory — a plan belongs to the repo it plans.

2. **Machine-local outputs and metadata** — output that belongs to the user or the
   machine rather than to any one repository: study documents, ingested notes,
   caches, personal indexes, and skill run-state that no target repo should carry.
   These default to **`~/.workshop/`** unless the invoking skill was given an
   explicit destination (a setting, env var, or argument). A skill in this
   category writes under a named subdirectory, e.g. `~/.workshop/transcript-notes/`,
   and treats a configured destination as authoritative when one is provided.

When adding a skill that writes output, classify it against these two categories
first. If the output is not a repo artifact, it defaults to `~/.workshop/<skill>/`;
do not invent a new home-directory location per skill.

This convention exists because an audit ahead of the first machine-local skill
(`transcript-notes`) found every existing output-writing skill correctly wrote
repo-scoped artifacts into the target repo, and no skill wrote scattered
machine-local output — so the rule codifies the split that was already implicit
before a second category of skill could diverge from it.
