# Built-in defenses

Every item here is built into `ci_watch.py` and covered by its test suite, so
wrapping the invocation in a defense of your own adds nothing but a second
thing to be wrong.

- **Transient `glab` failures** — stderr noise, empty stdout, or a nonzero
  exit — skip one tick instead of killing the watcher; only a long run of them
  ends the watch, as indeterminate.
- **Abbreviated SHAs** are expanded before querying: an abbreviated
  `pipelines?sha=` matches nothing and reads as pending forever.
- **The project path** is derived from the remote URL and passed explicitly,
  so glab's alphabetical multi-remote inference is never consulted.
- **Job listings** paginate past 100 jobs and include trigger jobs (bridges),
  so a red downstream pipeline cannot pass as green, and a listing that could
  not be fetched completely never counts as "every job green".
- **A pipeline stuck on a manual job** ends the watch instead of holding it for
  the full timeout, and the verdict names the job holding it. With
  `--manual-gate JOB`, a pipeline resting on named gates passes — but never
  while a job is red, a blocking manual job is left unnamed, no named gate is
  actually waiting, or automatic work (pending, running, scheduled) remains.
  Jobs still `created` behind a waiting gate are listed as not run.
- **A ref whose `workflow.rules` cannot match a branch push** ends the watch
  with that reason instead of waiting out the timeout — confirmed across
  several empty polls first, so an open MR's pipeline arriving late is never
  called unreachable, and any rule shape the check cannot evaluate confidently
  leaves the previous waiting behaviour exactly as it was.
- **A merged MR** is followed to the commit heading its target branch: the
  merge commit, the squash commit when the merge was squashed instead, and the
  MR's own diff-head SHA when it was fast-forwarded (a `merge_method: ff`
  project creates neither), with a fresh timeout budget for the post-merge
  watch.
- **A SHA carrying several pipelines** — an MR-head pipeline and a branch
  pipeline — is judged across every ref's newest pipeline, so a green MR
  pipeline cannot mask a red branch pipeline on the same commit; a retried run
  on the same ref still supersedes the old one. `--ref` is enforced on each
  returned pipeline's own `ref`, not only in the query: GitLab's `ref=` filter
  also returns MR pipelines whose source branch is that ref — a `dev → main`
  promotion MR's, listed first.
