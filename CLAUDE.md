# The Workshop

This file is auto-loaded every conversation. It defines how coding agents should work in this repo.

## What This Repo Is

A toolkit of coding-agent plugins, targeting Claude Code, Codex, and Cortex Code (CoCo) as first-class outputs. The nine directories under `plugins/` are self-contained plugins — manifests, skills, agents, hooks, and settings — and the platforms read them straight from source. Nothing is built or copied anywhere.

See [ROADMAP.md](ROADMAP.md) for the multi-platform goal and design principle, [COMPATIBILITY.md](COMPATIBILITY.md) for per-platform requirements, and [.claude/docs/project.md](.claude/docs/project.md) for detailed project context (tech stack, data flow, architecture patterns).

Every directory under `plugins/` is a shipped plugin, so a stray file or directory there is a defect.

## Commands

- Regenerate everything generated: `make stamp`
- Check for generated-file drift without writing: `make stamp-check`
- Smoke test one plugin: `uv run python -m scripts.smoke_test <plugin_name>`

`scripts/stamp.py` is the only build component. It owns a fixed map of
generated paths, marks every file it writes, and refuses to overwrite a file
that lacks its marker — so a mis-mapped output cannot silently consume
hand-written work. Anything not in that map is hand-authored.

## Avoiding Capability-Blocked Bash Calls During Unattended Execution

The `afk` executor runs slices unattended under `permission_mode = "acceptEdits"` (see `.afk/config.toml`): Edit and Write calls auto-approve, but Bash calls the harness flags as needing interactive approval — `gh`/network commands, and piped or chained (`|`, `&&`, `;`) commands — do not auto-approve, and fail immediately with no human present to grant them. A slice whose plan depends on the output of one of these calls cannot proceed once the call is rejected.

Before shelling out to `gh` (issue/PR lookup, comments, status checks) or chaining Bash commands with `|`/`&&`/`;`/`2>&1`:

1. Check whether the needed information is already in context — the issue title, body, and labels are already included in the task prompt; do not re-fetch them with `gh issue view`.
2. Prefer a single, unpiped command (`git log`, `grep`, `find`) over a chained one; run separate commands instead of combining them with a pipe.
3. If a task genuinely requires `gh`/network access or command chaining that no single unpiped Bash call can express, stop and record the gap in `.afk/question.md` rather than issuing the call and letting the slice fail.

This convention exists because issue #259 found the executor had quarantined 7 slices as `capability` — agents repeatedly issued `gh`/piped Bash calls that require interactive approval unattended execution cannot grant, instead of working from the context already provided or a simpler command.

## Escalating to .afk/question.md Only After Exhausting Available Context

This file's conventions sometimes instruct the agent to stop and write to `.afk/question.md` when it hits a specific blocker — for example, the capability-blocked Bash rule above, when a task genuinely needs `gh`/network access or command chaining no single unpiped call can express. Each such instruction is a legitimate escape hatch — but only once the blocking fact is genuinely absent from the repository, not merely absent from what the agent has read so far.

Before writing to `.afk/question.md` for any blocker:

1. Grep this file for a section that already addresses the specific blocker in front of you — do not assume a precedent exists without checking, and do not assume one is missing just because it isn't the first thing you recall.
2. Re-read the issue title, body, and labels already supplied in the task prompt; do not treat a detail restated there as missing.
3. Check `git log`/`git show` on recent `AFK: implement issue #N` commits for a directly analogous prior change this issue is extending or correcting.

Escalate only when, after this check, the blocking fact truly cannot be found anywhere in the repository — a credential, a URL not present in the issue or codebase, or a decision that trades off two valid approaches with no existing precedent to follow.

This convention exists because issue #260 found the executor had quarantined 3 slices as `question` — recurrence at this level suggested agents were treating ambiguity as a hard blocker before checking whether it was already resolved by an existing CLAUDE.md convention or by the issue text already in context.

## Code Style

- Type hints on all function signatures
- Numpy-style docstrings for public functions

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

## Planning

Write plans to `docs/plans/{file_name}.md`. Archive completed plans to `docs/archive/`.

## Branch and Promotion Policy

This repo **integrates on GitHub**.

- **`origin` is GitHub; `gitlab` is a downstream copy.** Confirm with
  `git remote -v` before branching — do not assume, and do not trust `origin`
  to be the integration remote in a clone you did not configure. A clone that
  had these reversed branched work off a GitLab `dev` that was 56 commits
  behind, which silently deleted merged skills from the working tree; the
  remotes were renamed afterwards so `origin` means the integration remote
  here.
- **Branch off `dev`**, one concern per branch, named `<type>/<kebab-slug>` using
  Conventional Commit types (`feat/`, `fix/`, `docs/`, `refactor/`, `test/`,
  `chore/`, `ci/`, `perf/`, `style/`). No vendor or agent prefixes.
- **Open a pull request into `dev`.** Never commit to `dev` directly.
- **Promote `dev` → `main`** with a pull request once dev CI is green. `main` is
  the release branch: never push to it directly, and never merge a feature
  branch straight into it.
- **Both branches are protected.** The `test` check must pass and the branch
  must be up to date with its base before a merge is allowed.
- Before any push or pull request, confirm the target branch from these project
  instructions and `.github/workflows/`; do not infer it from the repository's
  default branch.
- To sync local `main` after a promotion, use `git fetch origin main:main` —
  it updates the local ref without moving HEAD, so the working checkout stays
  on whatever branch it was already on.

### GitLab (downstream copy)

GitLab is no longer kept in sync by an automated mirror job — `git push gitlab
<branch>` by hand when an update is wanted, there is no scheduled or
push-triggered sync. Once pushed, GitLab-side promotion mirrors the standard
work-repo pattern used elsewhere: branch → MR → `dev` (1 approval required,
enforced by a GitLab approval rule scoped to the `dev` protected branch), then
`dev` → `main` is a solo CI-green merge — no extra approval gate. GitLab CI
(`.gitlab-ci.yml`) runs the same `make test` gate on `dev`, `main`, and every
merge request.

Before a pull request is ready, `make stamp` and `make test` must both pass,
with the regenerated files included in the change. `make test` covers the root
suite, every auto-discovered skill-script suite, the vault machinery suite, the
`stamp --check` drift gate, and the version-bump gate.

## Plugin Versioning

A plugin's version is how an installed copy learns there is anything to take:
`claude plugin update` compares it. **Change a plugin's shipped content without
bumping its version and the change reaches nobody** — it merges green, promotes
green, and silently never arrives. `make test` fails on this
(`scripts/check_version_bumps.py`).

The version lives in the hand-written `plugins/<name>/.claude-plugin/plugin.json`;
the two stamped platform manifests carry the same value. The gate diffs
`plugins/<name>/` against the release branch, excluding stamper-owned paths and
nothing else — generated content is a pure function of hand-authored content, so
a real change already trips the gate through its source.

**Hand-authored payload counts wherever it ships from, including
`plugins/<name>/machinery/`.** That directory was once excluded wholesale, on
the reading that it was vendored payload versioned upstream. The flat reorg
made that false: `machinery/engine/` _is_ the upstream, hand-authored and
shipped, with no source elsewhere in the tree to trip the gate on its behalf —
so the exclusion removed the only signal there was, and engine fixes merged and
promoted green while reaching zero installed vaults. Deriving the exclusion set
from the stamper's own path map is what keeps that from growing back; a second
hand-kept list is how it drifts.

The consumer is an owner with the plugin installed, and what they depend on is
the component surface: which skills, agents, and hooks exist, and what triggers
them.

- **Major** — something they rely on breaks. A skill, agent, or hook **removed**
  or renamed (its trigger phrases go with it, so their invocations silently stop
  matching); one **moved to a different plugin**, which an owner who has only the
  losing plugin installed experiences as a removal; a hook that now blocks where
  it did not; owner data changing location.
- **Minor** — new capability, nothing existing changes. A skill, agent, or hook
  **added**; new guidance inside an existing skill.
- **Patch** — fixes that change neither the surface nor the triggers. A script
  bug, corrected instructions, reworded docs.

Below 1.0, the minor position is the breaking signal: `0.1.3 → 0.2.0`, not
`1.0.0`.

The gate enforces two things it can see. That shipped content changed at all —
any hand-authored payload, skills and agents and hooks and engine alike — which
is what demands a bump. And the shipped component inventory, which sets how big
that bump must be: a removal demands major, an addition at least minor.

It still cannot see a behavioural break inside a component that kept its name.
An engine fix and a corrected typo look identical to it; both are hand-authored
changes to an unchanged inventory, so both clear at patch. Judge those
yourself — an unchanged inventory only means patch is the _floor_.

One bump covers everything that lands on `dev` between promotions — the check
compares against `main`, not against the PR base.

## Agents

Agents are specialized role definitions (`AGENT.md` with YAML frontmatter) that give subagents domain expertise. Each agent is self-contained -- skills are declared directly in the agent's frontmatter via `skills.add`/`skills.remove`.

An agent's `role` must be one of `implementer`, `reviewer`, `analyst`,
`qa-tester`, `skill-writer`, or `strategy`. This vocabulary is enforced for every
agent by `VALID_ROLES` in `scripts/smoke_test.py`; keep the two in sync.

For the current roster — every agent, its role, its skills, and the plugin that
ships it — see the generated [docs/reference/agents.md](docs/reference/agents.md);
regenerate it with `make stamp`.

### Plugin membership

Membership is the filesystem. A plugin ships exactly the skills in its own
`skills/` directory, the agents in its own `agents/`, and the hooks in its own
`hooks/scripts/` — there is no manifest field declaring what to include, and no
mechanism for one plugin to inherit a component from another.

**One plugin per slug, globally.** A skill or agent lives in exactly one plugin,
chosen by audience: universal, data, and vault work goes to `workbench`;
self-maintenance goes to `workshop-maintainer`; a persona's or advisor's own
payload goes to that plugin. Two plugins shipping the same slug is a repo defect,
not a distribution choice — `make stamp` fails on it, and `improve-skill`
resolves a skill by a flat `plugins/*/skills/<slug>/` glob that aborts on a
second hit.

A plugin's `.claude-plugin/plugin.json` is hand-written and carries only `name`,
`version`, `description`, and optionally `conventions`. Everything else about a
plugin is derived from what is in its directory.
