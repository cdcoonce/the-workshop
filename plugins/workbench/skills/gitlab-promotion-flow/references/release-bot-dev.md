# Landing MRs on a `dev` a release bot commits to

This applies when the project merges by fast-forward and every push to `dev`
runs a first-stage job that commits a version bump (`chore(release): vX.Y.Z`)
back onto `dev` with `git push -o ci.skip`, failing if that push fails. Four
things follow:

- **Every merge moves `dev` twice** — to the MR's head, then to the release
  commit. A fast-forward needs the next MR based on that release commit, so the
  next MR is rebased only once the previous merge's pipeline has pushed it.
- **The release commit never gets a pipeline.** `ci.skip` leaves no pipeline
  record at all; its tree was verified by its parent's `dev` pipeline. Watching
  the branch head (`ci_watch.py branch dev`) resolves that commit and waits out
  the whole timeout — watch the merged MR (`ci_watch.py mr IID`) instead.
- **An open `dev → main` promotion MR shares every SHA.** Its source branch is
  `dev`, so each `dev` push also runs a promotion-MR pipeline on the same
  commit, and GitLab's `pipelines?ref=dev` returns that one too — listed first.
  A check that trusts the first pipeline listed for a SHA verifies the wrong
  pipeline; the watcher matches each pipeline's own `ref` instead.
- **A promote button parks every `dev` pipeline.** Declared under `rules:` with
  `when: manual` and no `allow_failure: true`, it blocks, so the pipeline rests
  at `manual` with every other job done and no watch can pass it. Fix the job
  rather than the watch: `allow_failure: true`, or remove it — a button that
  pushes with the CI job token starts no pipeline on `main`, so it cannot
  deploy at all. Promote by merge request instead.

## Per MR, in queue order

Run from the target repo. `<ci_watch>` is
`python3 "<gitlab-ci-watch base directory>/scripts/ci_watch.py"`, backgrounded
as that skill describes; `<repo>` is `group/project`, and `<project>` is the
same path URL-encoded (`group%2Fproject`). Stop at any step that fails.

1. **Rebase onto `dev`.** `glab mr rebase <iid> -R <repo>`, then re-read
   `glab api "projects/<project>/merge_requests/<iid>?include_rebase_in_progress=true"`
   until `rebase_in_progress` is false. A non-null `merge_error` means rebase
   locally; otherwise that response's `sha` is the head to verify.
2. **MR pipeline green.** `<ci_watch> sha <sha>` exits 0.
3. **Merge exactly that head.**
   `glab mr merge <iid> --sha <sha> --auto-merge=false --yes -R <repo>`. A head
   that moved after step 2 is refused rather than merged, and so is an MR that
   `dev` moved past again; both go back to step 1.
4. **`dev` green.** `<ci_watch> mr <iid>` exits 0. That verdict also proves the
   release commit landed, so the next MR starts at step 1 with nothing else to
   wait for.

## After the queue

The promotion MR's head is now a release commit with no pipeline of its own.
Run one — `glab api -X POST "projects/<project>/merge_requests/<iid>/pipelines"`
— and watch the returned `id` with `<ci_watch> pipeline <id>`.
