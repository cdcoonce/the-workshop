# Reading and Answering Review Threads

Exact commands for step 2 (Read) and step 6 (Respond). GitLab first — `glab mr note`
and a top-level PR comment are **not** thread replies and never satisfy step 6.

## GitLab

### Read the threads

```bash
glab api "projects/:id/merge_requests/<iid>/discussions?per_page=100"
```

`:id` is substituted with the current repo; add `-R group/project` to target another.

Each element carries the `id` you need for every later call:

```json
{
  "id": "72c6d79377129e71e252d418be70af21986d89e7",
  "individual_note": true,
  "resolvable": false,
  "notes": [{ "id": 3591541624, "body": "...", "system": true, "author": {...} }]
}
```

Filter before triaging — the endpoint returns bookkeeping, not just review findings:

- **`"system": true`** — GitLab's own notes ("mentioned in commit …", "changed target branch"). Never a finding.
- **`"resolvable": false`** with `individual_note: true` — a plain comment, not a review thread. It can be replied to but not resolved.
- **`"resolved": true`** on the thread's notes — already handled; leave it alone.

A one-line triage view:

```bash
glab api "projects/:id/merge_requests/<iid>/discussions?per_page=100" \
  --paginate | jq -r '.[] | select(.notes[0].system | not)
  | [.id, .notes[0].author.username, (.notes[0].position.new_path // "general"),
     (.notes[0].resolved // false), (.notes[0].body | gsub("\n"; " ") | .[0:80])]
  | @tsv'
```

### Reply in-thread

```bash
glab api --method POST \
  "projects/:id/merge_requests/<iid>/discussions/<discussion_id>/notes" \
  --field body="$(cat reply.md)"
```

Read the body from a file or a heredoc so real newlines survive; an inline
`--field body="line1\nline2"` posts a literal backslash-n.

### Resolve — only a Fix with green CI

```bash
glab api --method PUT \
  "projects/:id/merge_requests/<iid>/discussions/<discussion_id>" \
  --field resolved=true
```

Fails on a non-resolvable discussion. That is a signal, not an error to work
around: an individual note was never a review thread.

### The CI check that gates all of the above

```bash
git rev-parse HEAD                      # the SHA the replies will cite
glab ci list --sha "$(git rev-parse HEAD)"   # FULL sha; short sha silently returns nothing
glab ci get --pipeline-id <id>          # per-job status; --sha is not a valid flag here
```

`glab ci list` returning nothing means "no pipeline for this SHA" — usually an
unpushed commit — never "green". Confirm the query returns something on its first
pass before treating silence as success.

## GitHub

### Read the threads

REST gives review comments and their reply chains:

```bash
gh api repos/{owner}/{repo}/pulls/<n>/comments --paginate
```

`in_reply_to_id` marks replies; the roots are the findings. REST does **not**
expose resolution state — GraphQL does:

```bash
gh api graphql -f query='
  query($o:String!,$r:String!,$n:Int!){
    repository(owner:$o,name:$r){ pullRequest(number:$n){
      reviewThreads(first:100){ nodes{
        id isResolved isOutdated
        comments(first:1){ nodes{ databaseId path author{login} body } } } } } } }
' -F o={owner} -F r={repo} -F n=<n>
```

Two IDs, two jobs: the comment's `databaseId` replies, the thread's node `id` resolves.

### Reply in-thread

```bash
gh api --method POST \
  repos/{owner}/{repo}/pulls/<n>/comments/<root_comment_databaseId>/replies \
  -f body="$(cat reply.md)"
```

`gh pr comment` posts a top-level PR comment and does not answer the thread.

### Resolve — only a Fix with green CI

```bash
gh api graphql -f query='
  mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){
    thread{ id isResolved } } }
' -F id=<thread_node_id>
```

### The CI check that gates all of the above

```bash
gh pr checks <n> --watch
```

## Filing the follow-up issue for a Deferred finding

File it against the repo that owns the root cause, which is often not the MR's
repo — a bad column upstream is the upstream pipeline's issue.

```bash
# same repo
glab issue create --title "..." --description "$(cat issue.md)"

# another repo
glab issue create -R group/other-project --title "..." --description "$(cat issue.md)"

# GitHub
gh issue create -R owner/other-repo --title "..." --body-file issue.md
```

The body needs: the MR and thread it came from, the finding verbatim, why it was
out of scope there, and what a fix would touch. Capture the returned URL — the
reply is not complete without it. "I'd recommend filing an issue" is not a
Deferred disposition.

## Reply template

Keep it short and load-bearing. No apologies, no restating the reviewer's point
back to them, no em dashes.

**Fix**

> Fixed in `8a3f1c2`. `test_missing_site_returns_empty` covers the null path.
> Head is green (pipeline 1839204).

**Contested**

> Not reproducing this. `dim_account` is unique on `MEMBER` — `select count(*),
count(distinct member) from dim_account` returns 1,412 / 1,412 at `8a3f1c2`.
> Leaving as-is unless you're seeing something different.

**Deferred**

> Real, but the fix is a schema change well outside this MR. Filed
> group/project#214 against the pipeline that owns the column.

**Stale**

> This was fixed in `c8f7b6a` before the review landed. Re-ran the case at head,
> it passes.

**Acknowledged**

> Fair point, not taking it in this MR — it touches the shared loader and this
> change is scoped to the one model. No code changed for this thread.

Contested, Deferred, Stale, and Acknowledged replies get posted; their threads
stay open for the reviewer to close.
