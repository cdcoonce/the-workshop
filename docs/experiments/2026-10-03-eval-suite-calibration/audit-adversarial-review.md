# adversarial-review audit pack

## A2: per-execution findings, with the items each finding credits on its own (location AND regex)

Lens wording used (conductor-written domain lens; test and spec lenses verbatim from pr-lens-review.md):

- **domain**: Your lens is commit-graph and history semantics ONLY. For every place DIFF decides which commits are pushed, which commit is the squash base, how a range of commits is split or classified, or which of two commits is the ancestor of the other, work at least one concrete case by hand (a small history with a pushed prefix and an unpushed tail) and check the code against your result. Attend to off-by-one on range boundaries, the direction of every comparison, and flags that could be inverted. Ignore anything that is not a decision about commit history.

- **test**: Your lens is whether the new tests would catch the bug they claim to. For each added test, determine whether it fails against BASE. A test that passes on the pre-change tree asserts nothing. Also flag tests that assert the implementation back to itself rather than the required behavior.

- **spec**: Your lens is SPEC versus DIFF, in both directions. Report requirements SPEC states that DIFF does not satisfy, AND changes in DIFF that SPEC never asked for. Unrequested changes are findings — untested scope no one reviewed against a requirement.


### A2 / noskill-1 — mechanical: D1=miss, D2=miss, D3=miss, D4=hit, D5=miss
- transcript aab6d7a4 parsed=True findings=3
  - F1 [sync_boundary_squash.py:147] credits=none — Off-by-one in classify_pushed_prefix. It returns `first_unpushed + 1` where it should return `first_unpushed`, so the pushed-run length is one too high. With nothing pushed, `[False, False, False]` gives 1, not 0 (the test expects
  - F2 [sync_boundary_squash.py:158] credits=none — The staged-but-uncommitted guard promised in the spec is missing from squash(). Nothing runs `git diff --cached --quiet`. The test `test_staged_uncommitted_changes_skip_squash` and a teeth mutant both expect it. Because `reset --s
  - F3 [command.md:3] credits=['D4'] — The PR modifies the vault-sync skill, although the description says `plugins/workbench/skills/vault-sync/**` is untouched because it belongs to companion issue #893. The added line tells /sync to run the 'sync boundary squash' wit

### A2 / noskill-2 — mechanical: D1=hit, D2=miss, D3=miss, D4=hit, D5=hit
- transcript ac331ccb parsed=True findings=3
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns `first_unpushed + 1`, but it is meant to return the count of leading pushed commits, which is `first_unpushed`. The test's own expectations and the teeth mutant's `find` text (`return first_unpushed`
  - F2 [sync_boundary_squash.py:233] credits=['D5'] — The staged-but-uncommitted guard is missing. The PR description promises it, and test_staged_uncommitted_changes_skip_squash and a teeth mutant both depend on it. squash() never runs `git diff --cached --quiet` before `reset --sof
  - F3 [command.md:3] credits=['D4'] — The PR edits vault-sync/references/command.md by adding a line about running the sync boundary squash. The description says `plugins/workbench/skills/vault-sync/**` is untouched because that is companion issue #893's footprint. Th

### A2 / noskill-3 — mechanical: D1=hit, D2=miss, D3=miss, D4=hit, D5=hit
- transcript afb71a94 parsed=True findings=3
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — Off-by-one in classify_pushed_prefix. It returns `first_unpushed + 1`, but it should return `first_unpushed`, the length of the leading pushed run. This contradicts the docstring and the unit test, which expects `[]` to give 0, `[
  - F2 [sync_boundary_squash.py:156] credits=['D5'] — The staged-but-uncommitted-changes guard is missing, although the spec lists it as a skip condition and the PR's own teeth file and test (`test_staged_uncommitted_changes_skip_squash`) expect a `git diff --cached --quiet` check. B
  - F3 [command.md:3] credits=['D4'] — The PR edits `vault-sync/references/command.md`, but the description says `plugins/workbench/skills/vault-sync/**` is untouched because that is companion issue #893's footprint. The added line also tells `/sync` to run a squash sc

### A2 / skill-1 — mechanical: D1=hit, D2=hit, D3=hit, D4=hit, D5=miss
- transcript aa273ec9 parsed=True findings=3
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns first_unpushed + 1 instead of first_unpushed, so the pushed-prefix length is off by one. With no commit pushed ([False, False, False]) it returns 1. With one pushed ([True, False, False]) it returns 
  - F2 [test_sync_boundary_squash.py:353] credits=none — test_staged_uncommitted_changes_skip_squash asserts action == 'skipped' and 'staged' in the reason. The script has no staged-changes guard, though the spec lists one. With a staged file, reset --soft followed by commit -C folds it
  - F3 [test_sync_boundary_squash.py:152] credits=['D3'] — The assertion `assert len(session) >= 1` is vacuous. It is true for any repository state, including the pre-change tree where nothing is squashed (3 commits), so it cannot show that the squash produced exactly one commit. The acce
- transcript af126cc1 parsed=True findings=2
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns `first_unpushed + 1`, which is one more than the length of the leading pushed run. The docstring, the unit tests ([] -> 0, [False,False,False] -> 0, [True,False,False] -> 1) and the teeth mutant, who
  - F2 [sync_boundary_squash.py:207] credits=['D2'] — The ancestry test for pushed-ness is inverted. `_is_ancestor(remote_head, sha)` asks whether the remote tip is an ancestor of the session commit. A session commit is on the remote when it is an ancestor of the remote tip, so the c
- transcript afede536 parsed=True findings=5
  - F1 [command.md:3] credits=['D4'] — The spec says `plugins/workbench/skills/vault-sync/**` is untouched because it belongs to companion issue #893. This diff adds a line to /sync's command.md: 'Before pulling, run the sync boundary squash if the wrap-up skill has no
  - F2 [sync_boundary_squash.py:238] credits=none — classify_pushed_prefix is off by one. Its docstring says it returns the length of the leading pushed run, but it returns first_unpushed + 1. With 3 session commits all unpushed, the flags are [F,F,F] and it returns 1, so pushed=1,
  - F3 [sync_boundary_squash.py:330] credits=none — The ancestry test is reversed. A commit is on the remote when it is an ancestor of the remote tip, but the code calls _is_ancestor(remote_head, sha), asking whether the remote tip is an ancestor of the session commit. Typical stat
  - F4 [sync_boundary_squash.py:276] credits=none — The spec lists 'staged-but-uncommitted changes' as a guard that reports `skipped` and changes nothing. squash() never checks the index. It only checks for in-progress operations. If the index has staged changes when the script run
  - F5 [tests.md:9] credits=none — The diff reformats the whole T01-T28 Behavioral Contract table and the RED Baseline table (re-padded columns, new alignment). It also rewrites the intro paragraph. The spec asked only for a new T29 row. The reformatting is unreque

### A2 / skill-2 — mechanical: D1=hit, D2=hit, D3=miss, D4=hit, D5=hit
- transcript a588fae2 parsed=True findings=4
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns `first_unpushed + 1`, but its docstring and the test's expected values say it returns the length of the leading pushed run. For [False, False, False] it returns 1 instead of 0, and for [] it returns 
  - F2 [sync_boundary_squash.py:166] credits=['D5'] — The script has no staged-changes guard, although the spec lists 'staged-but-uncommitted changes' as a skip case. Nothing runs `git diff --cached --quiet`. With staged changes, `reset --soft` followed by `commit -C head` sweeps the
  - F3 [sync_boundary_squash.teeth.json:52] credits=none — The 'staged-but-uncommitted changes no longer skip' mutant's `find` text (the `git diff --cached --quiet` block) does not exist in sync_boundary_squash.py. The mutant cannot be applied, so the claimed 10/10 kills and the anchor ch
  - F4 [command.md:3] credits=['D4'] — The diff adds a line to vault-sync/references/command.md. The spec says `plugins/workbench/skills/vault-sync/**` is untouched because it belongs to companion issue #893. No test or gate covers this, and the edit also tells /sync t
- transcript a7a6dad2 parsed=True findings=3
  - F1 [sync_boundary_squash.py:207] credits=['D2'] — The ancestry test points the wrong way. A session commit is pushed when it is an ancestor of the remote tip, so the check should be `_is_ancestor(sha, remote_head)`. The code calls `_is_ancestor(remote_head, sha)`. Worked case: ba
  - F2 [sync_boundary_squash.py:115] credits=['D1'] — Off-by-one in `classify_pushed_prefix`: it returns `first_unpushed + 1`, but the length of the leading pushed run is `first_unpushed`. Case 1, nothing pushed: flags [F,F,F] gives 1 instead of 0. `report.pushed` is 1 and `unpushed`
  - F3 [sync_boundary_squash.py:225] credits=none — `squash_base = base if prefix == 0 else session[prefix - 1]` depends on `prefix` being the pushed count. Because `classify_pushed_prefix` over-reports by 1, `prefix == 0` is unreachable. With nothing pushed, the squash base is `se
- transcript ad5fb215 parsed=True findings=4
  - F1 [command.md:3] credits=['D4'] — The spec says `plugins/workbench/skills/vault-sync/**` is untouched because that is companion issue #893's footprint. This diff adds a line to /sync's command.md: 'Before pulling, run the sync boundary squash if the wrap-up skill 
  - F2 [sync_boundary_squash.py:115] credits=['D1'] — `classify_pushed_prefix` is off by one: it returns `first_unpushed + 1` where it should return `first_unpushed`. The count of leading pushed commits is therefore one too high. Three unpushed commits `[F,F,F]` give prefix 1, so `sq
  - F3 [sync_boundary_squash.py:158] credits=['D5'] — The spec lists staged-but-uncommitted changes as a guard that reports `skipped` and changes nothing. `squash()` has no `git diff --cached` check. The teeth mutant and `test_staged_uncommitted_changes_skip_squash` both reference a 
  - F4 [tests.md:3] credits=none — The spec asks only for a new T29 row in tests.md. The diff also rewrites the intro sentence and re-pads every row of the Behavioral Contract table and the RED Baseline table. That is whole-table reformatting nobody asked for, and 

### A2 / skill-3 — mechanical: D1=hit, D2=hit, D3=hit, D4=hit, D5=hit
- transcript a684198b parsed=True findings=4
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns first_unpushed + 1, but the caller treats the result as the count of pushed commits (squash_base = base if prefix == 0 else session[prefix - 1]). The correct return value is first_unpushed, and the t
  - F2 [sync_boundary_squash.py:158] credits=['D5'] — The spec lists 'staged-but-uncommitted changes' as a skip guard, and the command.md text and the teeth.json mutant at diff line 473 both claim it exists. squash() has no `git diff --cached` check. With staged changes, `reset --sof
  - F3 [command.md:3] credits=['D4'] — The spec says plugins/workbench/skills/vault-sync/** is untouched because that is companion issue #893's footprint, but the diff adds a line to this file. The added instruction ('run the sync boundary squash if the wrap-up skill h
  - F4 [tests.md:5] credits=none — The spec asks only for a new T29 row. The diff also reflows the whole existing T01-T28 behavioral table and the RED Baseline table (column padding and separator rows), and rewrites the intro paragraph. These are unrequested edits 
- transcript aad18930 parsed=True findings=2
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — Off-by-one in classify_pushed_prefix. The function documents 'length of the leading pushed run' but returns first_unpushed + 1. Hand case: session [A(pushed), B, C, D] has flags [T,F,F,F], so first_unpushed=1 and the function retu
  - F2 [sync_boundary_squash.py:207] credits=['D2'] — The ancestry test is inverted. A session commit is on the remote when it is an ancestor of the remote head, but the code calls _is_ancestor(remote_head, sha), which asks whether the remote head is an ancestor of the session commit
- transcript ac5d98fb parsed=True findings=5
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns `first_unpushed + 1`, which is off by one, but the tests assert the correct prefix lengths. For `[]` and `[False, False, False]` it returns 1 where the parametrized test expects 0. For `[True, False,
  - F2 [sync_boundary_squash.py:158] credits=['D5'] — The staged-but-uncommitted guard is missing from the script, although the spec, command.md and the teeth file all rely on it. There is no `git diff --cached` check anywhere. With staged changes, the script resets --soft and then c
  - F3 [test_sync_boundary_squash.py:363] credits=none — In test_staged_uncommitted_changes_skip_squash, `assert "staged" in report["reason"]` fails with the current script. The script reports 'squashed commit failed verification; repository restored' because the explicit staged guard d
  - F4 [sync_boundary_squash.teeth.json:52] credits=none — The 'staged-but-uncommitted changes no longer skip' mutant has a `find` anchor (`staged = _run_git("diff", "--cached", "--quiet")` ... `staged but uncommitted changes present...`) that does not exist in sync_boundary_squash.py. Th
  - F5 [test_sync_boundary_squash.py:151] credits=['D3'] — In test_collapses_three_unpushed_commits_into_one, `assert len(session) >= 1` is vacuous. Three commits collapsing to one requires `== 1`. A squash that left 2 or 3 commits would still satisfy this line. Only the later `HEAD^ == b

### A2 / skill-4 — mechanical: D1=hit, D2=hit, D3=hit, D4=hit, D5=hit
- transcript a4681311 parsed=True findings=2
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — Off-by-one in classify_pushed_prefix. It returns first_unpushed + 1, but the length of the leading pushed run is first_unpushed. Hand case with session [c1,c2,c3,c4] and only c1 pushed: flags are [T,F,F,F], first_unpushed is 1, an
  - F2 [sync_boundary_squash.py:207] credits=['D2'] — Ancestor direction is inverted when classifying pushed commits. `_is_ancestor(remote_head, sha)` asks whether the remote tip is an ancestor of the session commit. A session commit is pushed when it is an ancestor of the remote tip
- transcript a539d763 parsed=True findings=5
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns `first_unpushed + 1` where the length of the leading pushed run is `first_unpushed`. It is off by one. All-unpushed input (`[False, False, False]`) returns 1 instead of 0. squash() then sets pushed=1
  - F2 [sync_boundary_squash.py:156] credits=['D5'] — squash() has no staged-but-uncommitted-changes guard, although the spec lists it as a skip condition and the teeth file mutates a `git diff --cached --quiet` block. With a staged file and 2+ unpushed commits, the script does `rese
  - F3 [sync_boundary_squash.teeth.json:52] credits=none — The staged-guard mutant's `find` text (the `staged = _run_git("diff", "--cached", "--quiet")` block) does not exist in sync_boundary_squash.py, so the mutant cannot be applied. The `return first_unpushed` anchor at line 94 also no
  - F4 [test_sync_boundary_squash.py:151] credits=['D3'] — `assert len(session) >= 1` is vacuous for the "exactly one commit" requirement: it passes whether the squash collapsed 3 commits to 1 or left all 3. Acceptance (a) needs `== 1`. Only the later `HEAD^ == base` assertion implies it,
  - F5 [command.md:3] credits=['D4'] — The diff adds a line to vault-sync/references/command.md, but the spec says `plugins/workbench/skills/vault-sync/**` is untouched (companion issue #893's footprint). The spec's claim is false, and no test covers this file.
- transcript af288b7e parsed=True findings=5
  - F1 [sync_boundary_squash.py:330] credits=none — The pushed test is inverted. `_is_ancestor(remote_head, sha)` asks whether the remote tip is an ancestor of the session commit. A commit is on the remote when it is an ancestor of the remote tip, so the arguments should be `(sha, 
  - F2 [sync_boundary_squash.py:238] credits=none — `classify_pushed_prefix` returns `first_unpushed + 1`, but its docstring says it returns the length of the leading pushed run, so it should return `first_unpushed`. With 3 session commits and none pushed it returns 1, so `squash_b
  - F3 [sync_boundary_squash.py:154] credits=none — The spec lists staged-but-uncommitted changes as a guard that reports `skipped`, and the teeth file's mutant 'staged-but-uncommitted changes no longer skip the squash' anchors on a `git diff --cached --quiet` block. No such guard 
  - F4 [command.md:3] credits=['D4'] — The spec says `plugins/workbench/skills/vault-sync/**` is untouched because it is companion issue #893's footprint, but the diff adds a new instruction line to the /sync command doc. The line tells /sync to run the sync boundary s
  - F5 [tests.md:49] credits=none — The PR rewrites the whole Behavioral Contract table and the RED Baseline table (re-padding every existing row T01-T28 and P1-P7), where the spec asked only for a new T29 row. These whitespace rewrites touch about 40 unrelated line

### A2 / skill-5 — mechanical: D1=hit, D2=hit, D3=hit, D4=hit, D5=hit
- transcript a46b3f37 parsed=True findings=6
  - F1 [sync_boundary_squash.py:207] credits=['D2'] — The pushed test has its arguments reversed. `_is_ancestor(remote_head, sha)` asks whether the remote tip is an ancestor of the session commit. A commit is pushed when it is an ancestor of the remote tip. Example: the remote tip is
  - F2 [sync_boundary_squash.py:115] credits=['D1'] — `classify_pushed_prefix` returns `first_unpushed + 1`, which is off by one against the spec and the committed unit test (`[False,False,False] -> 0`, `[True,False,False] -> 1`, `[True,True] -> 2`). With 3 unpushed commits and nothi
  - F3 [sync_boundary_squash.py:233] credits=['D5'] — The spec requires staged-but-uncommitted changes to report `skipped` and change nothing. There is no `git diff --cached` guard in `squash()`. The teeth mutant and `test_staged_uncommitted_changes_skip_squash` both reference a guar
  - F4 [command.md:3] credits=['D4'] — The spec states that `plugins/workbench/skills/vault-sync/**` is untouched because it belongs to companion issue #893. The diff adds a line to vault-sync's command.md telling /sync to run the sync boundary squash. This is an unreq
  - F5 [tests.md:3] credits=none — The spec asks only for a new T29 row. The diff also rewrites the file's introductory paragraph. It reflows and re-pads every existing T01-T28 row and the RED baseline table, with whitespace and column-width churn only. These chang
  - F6 [test_sync_boundary_squash.py:152] credits=['D3'] — Acceptance (a) requires exactly one commit between the base and HEAD after a squash. This test asserts only `len(session) >= 1`, which holds even if nothing was squashed, so a regression to 'no squash' passes. The other tests do u
- transcript a7ce3d84 parsed=True findings=5
  - F1 [test_sync_boundary_squash.py:151] credits=['D3'] — Acceptance test (a) is meant to prove that 3+ unpushed commits collapse to exactly one commit, but it asserts `len(session) >= 1`. That holds for any non-empty range, including an unsquashed 3-commit one. The exactly-one claim the
  - F2 [sync_boundary_squash.py:115] credits=['D1'] — `classify_pushed_prefix` returns `first_unpushed + 1`, so its result is one too high on every path. `[False, False, False]` gives 1, not 0, and `[True, True]` gives 3, not 2. With nothing pushed, `squash_base` becomes `session[0]`
  - F3 [sync_boundary_squash.py:153] credits=['D5'] — The script has no staged-but-uncommitted-changes guard, although the spec lists it as a skip case and `test_staged_uncommitted_changes_skip_squash` expects `skipped` with 'staged' in the reason. Scenario: 2+ unpushed session commi
  - F4 [sync_boundary_squash.teeth.json:53] credits=none — The 'staged-but-uncommitted changes' mutant's `find` text (`staged = _run_git("diff", "--cached", "--quiet")` and the lines after it) does not exist in `sync_boundary_squash.py`. The mutation cannot be applied, so the claim that i
  - F5 [command.md:3] credits=['D4'] — The PR description says `vault-sync/**` is untouched because it is companion issue #893's footprint, but the diff adds a line here. The line tells `/sync` to run a sync boundary squash that this skill has no script or invocation d
- transcript aba4f8e3 parsed=True findings=3
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — Off-by-one in classify_pushed_prefix. It returns `first_unpushed + 1`, but the length of the leading pushed run is `first_unpushed`. Hand case with flags [F,F,F] (nothing pushed): first_unpushed=0, so prefix=1 and the script repor
  - F2 [sync_boundary_squash.py:207] credits=['D2'] — Ancestry direction is inverted when classifying pushed commits. `_is_ancestor(remote_head, sha)` asks whether the remote tip is an ancestor of the session commit, which is true for commits NEWER than the remote tip. A commit is pu
  - F3 [sync_boundary_squash.py:164] credits=['D5'] — The staged-but-uncommitted guard is missing from squash(). The spec lists it as a skip condition, and the teeth file's mutant targets a `git diff --cached --quiet` check that does not exist in the code. If the index has staged cha

### A2 / skill-6 — mechanical: D1=hit, D2=hit, D3=hit, D4=hit, D5=hit
- transcript a332e518 parsed=True findings=2
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — Off-by-one in classify_pushed_prefix. It returns first_unpushed + 1, but the leading pushed run has length first_unpushed. Take session [c0,c1,c2,c3] with nothing pushed: flags are [F,F,F,F], first_unpushed is 0, and the function 
  - F2 [sync_boundary_squash.py:207] credits=['D2'] — The ancestry test for 'pushed' is inverted. A session commit is on the remote when it is an ancestor of the remote head, so the call should be _is_ancestor(sha, remote_head). The code calls _is_ancestor(remote_head, sha), which is
- transcript a6c8f73b parsed=True findings=4
  - F1 [sync_boundary_squash.py:115] credits=['D1'] — classify_pushed_prefix returns `first_unpushed + 1` where it should return `first_unpushed`, so the pushed-run length is off by one. Nothing pushed (`[False]*3`) gives 1 instead of 0. The `prefix == 0` branch that selects `base` a
  - F2 [sync_boundary_squash.py:233] credits=['D5'] — The spec requires a guard that reports `skipped` when there are staged-but-uncommitted changes, and the PR description lists it. squash() has no `git diff --cached` check. If a file is staged and 2 or more unpushed session commits
  - F3 [command.md:3] credits=['D4'] — The spec states that `plugins/workbench/skills/vault-sync/**` is untouched, because that is companion issue #893's footprint. The diff adds a line to vault-sync/references/command.md: 'Before pulling, run the sync boundary squash 
  - F4 [tests.md:3] credits=none — The spec asks only for a new row T29. The diff also rewrites the intro paragraph so it now describes the sync-boundary squash. It reflows the whole Behavioral Contract table (rows T01-T28 re-padded, header and separator changed) a
- transcript aad81af6 parsed=True findings=5
  - F1 [test_sync_boundary_squash.py:353] credits=none — test_staged_uncommitted_changes_skip_squash expects action == 'skipped' with 'staged' in the reason. The added script has no staged-changes guard anywhere in squash(). With two session commits and a staged file, the script runs re
  - F2 [sync_boundary_squash.teeth.json:53] credits=none — The 'staged-but-uncommitted changes no longer skip' mutant has a find string (the diff --cached --quiet block) that does not exist in sync_boundary_squash.py. The mutation cannot apply, so it can never be 'killed' on the staged te
  - F3 [sync_boundary_squash.py:147] credits=none — classify_pushed_prefix returns first_unpushed + 1 instead of first_unpushed, so it is off by one. The added parametrized test expects [] -> 0, [F,F,F] -> 0, [T,F,F] -> 1 and [T,T] -> 2, which the code does not return. In squash(),
  - F4 [test_sync_boundary_squash.py:152] credits=['D3'] — The assertion `len(session) >= 1` in test_collapses_three_unpushed_commits_into_one is vacuous, since HEAD always sits above base. The intended check is exactly one commit. The test only catches an un-squashed range through the la
  - F5 [command.md:3] credits=['D4'] — The PR adds a line to vault-sync/references/command.md, but the spec says plugins/workbench/skills/vault-sync/** is untouched and belongs to companion issue #893. No test covers this change. The added instruction ('run the sync bo

## A1 / noskill-1  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=miss
  1. Bash: git status --short && git branch -a && git log --oneline -10 && ls
  2. Bash: git show d92ba6f && find src tests -type f | grep -v pyc && cat pytest.ini
  3. Bash: cat src/settlement/*.py tests/test_rounding.py && python -m pytest -q 2>&1 | tail -5; python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.rounding import round_amount ⏎ from decimal import Decimal ⏎ for x in [1.005,2.675,0.125,0.5,1.015,1.025,2.5e-3,-1.005,-0.125,1.0049,0.285,1e
  4. Bash: (python3 -m pytest -q 2>&1 | tail -5 || true); (uvx pytest -q 2>&1 | tail -8); git stash list | head -2; git status --short ⏎ # pre-fix behaviour of the "half-cent" test on main ⏎ git show main:src/settlement/rounding.py; python3 -c "print(round(1.005,2), round(0.125,2))"
  5. Bash: cp -r . ../../fxcheck 2>/dev/null; cd ../../fxcheck && git checkout -q main -- src && git checkout -q fix/settlement-rounding -- tests 2>/dev/null; git checkout -q d92ba6f -- tests; uvx pytest -q -p no:cacheprovider 2>&1 | tail -5 ⏎ cd .. && python3 - <<'E' ⏎ import sys; sys.path.insert(0,'fx/src') 
  6. Bash: find . -name __pycache__ -prune -exec rm -rf {} + ; git status --short; git log --oneline -1; python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.invoice import line_total, invoice_total ⏎ print(line_total(0.125,1), line_total(0.025,5), invoice_total([(0.125,1)]), invoice_total(

## A1 / noskill-2  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit
  1. Bash: git status | head; git branch -a; git log --oneline | head; ls -la
  2. Bash: cat pytest.ini; find src tests -type f | grep -v pyc; git show d92ba6f; git show d21b56d --stat; python3 -m pytest -q 2>&1 | tail -15
  3. Bash: cat src/settlement/invoice.py tests/test_rounding.py; (uv run --with pytest python -m pytest -q 2>&1 || python3 -m venv /tmp/x 2>&1) | tail -15 ⏎ python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from decimal import Decimal, ROUND_HALF_UP ⏎ from settlement.rounding import round_amount ⏎ for v
  4. Bash: git stash list >/dev/null; git checkout -q d21b56d -- src && uv run --with pytest python -m pytest -q 2>&1 | tail -4; git checkout -q HEAD -- src; git status --short ⏎ python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.invoice import line_total, invoice_total ⏎ print(line_total
  5. Bash: rm -rf src/settlement/__pycache__ tests/__pycache__ .pytest_cache; git status --short

## A1 / noskill-3  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=miss
  1. Bash: git status --short && git branch -a && git log --oneline -10 && git diff main...HEAD --stat 2>&1 | tail -20; ls
  2. Bash: git show HEAD && cat src/settlement/rounding.py && ls -R src tests pytest.ini && cat pytest.ini
  3. Bash: python -m pytest -q 2>&1 | tail -20
  4. Bash: cat src/settlement/invoice.py src/settlement/__init__.py tests/test_rounding.py; (python3 -m pytest -q 2>&1 || uv run --with pytest pytest -q 2>&1) | tail -15 ⏎ cat > /private/tmp/claude-501/-Users-cdcoonce-Developer-GitHub-the-vault--claude-worktrees-jolly-lederberg-8b2390/72f33bbd-59b6-40ac-8e40-8

## A1 / skill-1  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit
  1. Bash: git status --short && git branch --show-current && git log --oneline -8 && ls
  2. Bash: git show d92ba6f && find src tests -type f | head -50 && cat pytest.ini
  3. Bash: cat src/settlement/*.py tests/test_rounding.py && python -m pytest -q 2>&1 | tail -5 ⏎ python - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.rounding import round_amount ⏎ from decimal import Decimal ⏎ for x in [1.005,2.675,0.125,0.5,1.015,2.5,0.045,1.125,-1.005,-0.125,1.135]: ⏎   
  4. Bash: (uv run --with pytest python -m pytest -q 2>&1 || python3 -m pytest -q 2>&1) | tail -8 ⏎ python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.invoice import invoice_total, line_total ⏎ print(line_total(0.125,1), line_total(1.005,1), invoice_total([(0.125,1)]), invoice_total([(0.0
  5. Bash: git stash -q 2>/dev/null; git checkout -q d92ba6f~1 -- src && uv run --with pytest python -m pytest -q 2>&1 | tail -3; git checkout -q HEAD -- src && git status --short

## A1 / skill-2  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit
  1. Bash: git status --short && git branch -a && git log --oneline -10 && ls -la
  2. Bash: cat pytest.ini && find src tests -type f | xargs ls -la && git show d92ba6f && git log --format='%H %an %ad %s' && git diff main..HEAD --stat
  3. Bash: cat src/settlement/invoice.py src/settlement/rounding.py tests/test_rounding.py; python3 -m pytest -q 2>&1 | tail -15 ⏎ python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.rounding import round_amount ⏎ for x in [0.005,0.015,0.025,0.035,0.045,1.005,2.675,1.015,1.025,10.125,0.125
  4. Bash: (uv run --with pytest python -m pytest -q 2>&1 | tail -8); git status --short ⏎ python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src'); sys.path.insert(0,'tests') ⏎ import test_rounding as t ⏎ for n in dir(t): ⏎     if n.startswith('test_'): ⏎         try: getattr(t,n)(); print('PASS',n) ⏎         e
  5. Bash: git stash -u -q -m tmp-fx 2>/dev/null; git checkout -q d21b56d -- src/settlement/rounding.py && (uv run --with pytest python -m pytest -q -p no:cacheprovider 2>&1 | tail -3); git checkout -q HEAD -- src/settlement/rounding.py; git status --short; find . -name __pycache__ -not -path './.git/*' -exec 
  6. Bash: git stash drop -q && find . -name __pycache__ -not -path './.git/*' -exec rm -rf {} + ; git stash list; git status --short; git log --oneline -1

## A1 / skill-3  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=miss
  1. Bash: git status --short | head; git branch -a; git log --oneline -10; ls -la
  2. Bash: cat pytest.ini; find src tests -type f | grep -v pyc; git show d92ba6f; git diff main fix/settlement-rounding --stat
  3. Bash: cat src/settlement/*.py tests/test_rounding.py; python3 -m pytest -q 2>&1 | tail -15; git show d21b56d --stat | head -20
  4. Bash: (uv run --with pytest python -m pytest -q 2>&1 | tail -15); echo ---; PYTHONPATH=src python3 - <<'E' ⏎ from decimal import Decimal, ROUND_HALF_UP ⏎ from settlement.rounding import round_amount ⏎ from settlement.invoice import line_total, invoice_total ⏎ for x in [1.005, 2.675, 0.125, 0.375, 1.015, 1
  5. Bash: D=$(mktemp -d) && git worktree add -q $D d92ba6f --detach && cp $D/../fx/tests/test_rounding.py /dev/null; git show d21b56d:src/settlement/rounding.py > $D/src/settlement/rounding.py && (cd $D && uv run --with pytest python -m pytest -q 2>&1 | tail -5); echo "--- invoice old vs new"; PYTHONPATH=src 
  6. Bash: git worktree list; git status --short

## A1 / skill-4  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=hit, A1-defect-missed-call-site=miss
  1. Bash: git status --short | head; git branch -a; git log --oneline -10; ls
  2. Bash: git show d92ba6f; find src tests -type f | head -50; cat pytest.ini
  3. Bash: cat src/settlement/*.py tests/test_rounding.py; python3 -m pytest -q 2>&1 | tail -5; python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.rounding import round_amount ⏎ for x in [1.005,2.675,0.125,0.5,1.015,2.5e-3,-1.005,-0.125,1.045,0.285]: ⏎     print(x, round(x,2), round_amoun
  4. Bash: (uv run --with pytest python -m pytest -q 2>&1 | tail -8); python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.invoice import invoice_total, line_total ⏎ from settlement.rounding import round_amount ⏎ print(line_total(0.335,1), line_total(1.005,1), invoice_total([(0.125,1)]), in
  5. Bash: d=$(mktemp -d) && git worktree add -q --detach $d main && cp tests/test_rounding.py $d/tests/ && (cd $d && uv run --with pytest python -m pytest -q 2>&1 | tail -3); git worktree remove --force $d; git status --short

## A1 / skill-5  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit
  1. Bash: git status --short | head; git branch -a; git log --oneline -8; ls
  2. Bash: git show d92ba6f; cat pytest.ini; find src tests -type f | grep -v pyc
  3. Bash: cat src/settlement/invoice.py tests/test_rounding.py; python -m pytest -q 2>&1 | tail -5 ⏎ python - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from decimal import Decimal, ROUND_HALF_UP ⏎ from settlement.rounding import round_amount ⏎ for x in [1.005,2.675,0.125,0.375,1.015,2.5/100,0.285,1.045,1
  4. Bash: git log -3 --format='%h %s' main; git show d21b56d --stat | tail -8
  5. Bash: (uv run --with pytest python -m pytest -q 2>&1 | tail -5) ⏎ echo ---old impl vs new tests ⏎ python - <<'E' ⏎ import sys; sys.path.insert(0,'src'); sys.path.insert(0,'tests') ⏎ import settlement.rounding as r ⏎ r.round_amount=lambda a: round(a,2)   # pre-fix behaviour ⏎ import test_rounding as t ⏎ t.

## A1 / skill-6  — counted
mechanical: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit
  1. Bash: git status --short | head; git branch -a; git log --oneline -10; ls
  2. Bash: git show d92ba6f; find src tests pytest.ini -type f | grep -v pyc; cat pytest.ini
  3. Bash: cat src/settlement/invoice.py tests/test_rounding.py; python -m pytest -q 2>&1 | tail -5 ⏎ python - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.rounding import round_amount as n ⏎ from decimal import Decimal ⏎ for x in [0.125,0.375,2.675,1.005,0.015,0.025,0.035,1.115,2.5,0.5,-0.12
  4. Bash: git status --short; (uv run --with pytest python -m pytest -q 2>&1 | tail -5);  ⏎ python - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.invoice import line_total, invoice_total ⏎ print(line_total(0.125,1), line_total(1.005,1), invoice_total([(0.125,1),(0.125,1)]), invoice_total([(1
  5. Bash: git checkout -q fix/settlement-rounding && git show d21b56d:src/settlement/rounding.py > /tmp/x 2>/dev/null; mkdir -p ../teeth && cp -r src tests pytest.ini ../teeth/ && git show d21b56d:src/settlement/rounding.py > ../teeth/src/settlement/rounding.py && (cd ../teeth && uv run --with pytest python -

## A3 / skill-1  — counted
mechanical: A3=miss
  1. Bash: git status --short && git branch -a && git log --oneline --all --graph | head -20 && ls -la && git diff main...HEAD --stat
  2. Bash: git diff main...HEAD && cat src/settlement/rounding.py && find src tests -type f | grep -v pyc && cat tests/test_rounding.py pytest.ini
  3. Bash: cat src/settlement/invoice.py && python3 -m pytest -q 2>&1 | tail -5; python3 -c " ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.rounding import round_amount ⏎ from decimal import Decimal ⏎ print(Decimal(1.005), round_amount(1.005), round(1.005,2), round_amount(2.675), round_amount(0.125)

## A3 / skill-2  — counted
mechanical: A3=miss
  1. Bash: git status --short && git branch -a && git log --oneline -10 && git diff main...HEAD --stat && ls
  2. Bash: git diff main...HEAD && cat src/settlement/*.py && ls -R src tests && cat pytest.ini && python3 -m pytest -q 2>&1 | tail -15
  3. Bash: PYTHONPATH=src python3 -c " ⏎ from settlement.rounding import round_amount as n ⏎ from decimal import Decimal ⏎ for x in [1.005,2.675,0.125,0.135,1.015,2.5e-3+1.0]: ⏎     print(x, Decimal(x), n(x), round(x,2)) ⏎ from settlement.invoice import line_total ⏎ print(line_total(0.335,1), line_total(1.005,

## A3 / skill-3  — counted
mechanical: A3=miss
  1. Bash: git status --short && git branch -a && git log --oneline -10 && git diff main...HEAD --stat && ls
  2. Bash: git diff main...HEAD && find src tests -type f | grep -v pyc && cat pytest.ini && cat src/settlement/*.py
  3. Bash: python -m pytest -q 2>&1 | tail -3; PYTHONPATH=src python -c " ⏎ from settlement.rounding import round_amount as r ⏎ from settlement.invoice import line_total ⏎ for x in (1.005,2.675,0.125,0.375,1.015,2.5/100*1): print(x, round(x,2), r(x)) ⏎ print(line_total(0.0125,10), line_total(1.005,1)) ⏎ from d

## A3 / skill-4  — counted
mechanical: A3=miss
  1. Bash: git status --short | head; git branch -a; git log --oneline -8; echo ---; git diff main...HEAD --stat; ls -la
  2. Bash: git diff main...HEAD; echo ----; find src tests -type f | grep -v pyc; cat pytest.ini; for f in $(find src -name '*.py'); do echo "=== $f"; cat $f; done
  3. Bash: python3 -m pytest -q 2>&1 | tail -5; python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from settlement.rounding import round_amount ⏎ from settlement.invoice import line_total ⏎ for x in [1.005,2.675,0.125,0.5,1.015,2.5,0.045]: ⏎     print(x, "new:",round_amount(x), "old:",round(x,2)) ⏎ print

## A3 / skill-5  — counted
mechanical: A3=miss
  1. Bash: git status --short && git branch -a && git log --oneline -8 && git diff main...HEAD --stat && ls
  2. Bash: git diff main...HEAD && find . -path ./.git -prune -o -type f -print && cat pytest.ini && cat src/settlement/*.py
  3. Bash: python3 -m pytest -q 2>&1 | tail -3; python3 - <<'E' ⏎ import sys; sys.path.insert(0,'src') ⏎ from decimal import Decimal ⏎ from settlement.rounding import round_amount ⏎ from settlement.invoice import line_total, invoice_total ⏎ print(Decimal(1.005)) ⏎ for x in (1.005, 2.675, 0.125, 0.285): print(x

## A3 / skill-6  — counted
mechanical: A3=miss
  1. Bash: git status --short && git branch -a && git log --oneline -10 && git diff main...HEAD --stat && ls
  2. Bash: git diff main...HEAD && find . -path ./.git -prune -o -type f -print && cat src/settlement/*.py && cat pytest.ini && python -m pytest -q 2>&1 | tail -15
  3. Bash: (uv run --with pytest python -m pytest -q 2>&1 | tail -5); PYTHONPATH=src python3 -c " ⏎ from settlement.rounding import round_amount as r ⏎ from settlement.invoice import line_total ⏎ from decimal import Decimal ⏎ print(Decimal(1.005)) ⏎ for x in (1.005,2.675,0.125,0.135,2.5e-1+0.005): print(x, r(x
