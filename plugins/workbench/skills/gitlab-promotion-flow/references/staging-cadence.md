# The staging cadence (repo-local variant)

Some repos declare a standing `staging` hop in their own `CLAUDE.md` — that
declaration is what opts a repo in, and its wording wins over this page:

```
<type>/<slug> ──MR──▶ dev ──refresh MR──▶ staging ──promote MR──▶ main
   (one concern)     (CI green,          (CI green,          (1 approval,
                      no approval;        no approval)         CI green; main
                      dev instance)                            CI = prod release)
```

Where this cadence is live it **replaces the `release/vX.Y.Z` freeze
mechanic**: `staging` is the standing frozen promotion source, and the
promotion MR runs `staging → main` instead of `dev → main`.

## Rules

- **Refresh `staging` only by a `dev → staging` MR** (CI green, no approval),
  and **only while no `staging → main` promotion MR is open**. An MR's diff
  tracks its source branch head, so a mid-review refresh changes what the
  approver is reading — the exact drift the release-branch mechanic exists to
  prevent.
- **The one approval gate does not move.** The 1-approval `any_approver` rule
  stays scoped to the `main` protected branch, so it gates `staging → main`;
  the refresh hop adds no approval, and `main` is never easier to reach than
  before.
- **`staging` runs no branch pipeline.** CI gates both hops as MR pipelines,
  and `main`'s branch pipeline remains the production release; `staging`
  deploys nothing of its own.
- **Both title-file hops take their title from `gitlab-mr-create`'s
  `--title-file`** — the refresh as well as the promotion. The refresh MR's
  source branch is `dev` itself, so `HEAD` is a merge commit (or a release
  bot's `chore(release): vX.Y.Z`); neither describes the hop.
- **Review fixes found during a promotion land on `dev` first**, through the
  normal branch → MR flow, then cherry-pick forward to `staging`. Never fix
  directly on `staging`: forgetting the back-merge silently regresses `dev`.
- **`staging` is protected** — push/merge for Maintainers only, force-push
  disabled. Direct pushes to it are for cherry-picks only; the refresh from
  `dev` is always a merge, never a reset.
