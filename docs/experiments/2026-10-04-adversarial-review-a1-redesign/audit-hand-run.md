# adversarial-review A1 redesign hand-run: audit pack (2026-10-04)

Case: evals/adversarial-review/A1 at dev 905b74d (fixture fingerprint b9a46fe1efca2d118aa93f3757e96189628d30819524aae74e90159407e08bd0). Sonnet (general-purpose) case agents: 6 skill-arm executions (dispatch prompt = the harness's build_dispatch_prompt, i.e. 'Use the workbench:adversarial-review skill for this task.' plus the A1 prompt) and 3 no-skill-arm executions (build_no_skill_prompt), each preceded by one fixture-path line because the Agent tool cannot set a working directory. One fresh fixture per execution, built by the case's own build_fixture.py. Every transcript was status=complete, copied after its completion notice and cmp-verified. No retries, no replacements. The raw transcripts are machine-local and are not committed; this pack is the record.

Items: A1-coverage-bound (gate candidate): a line-start `## Could not verify` section that names a listed surface (src/settlement/__init__.py, src/settlement/invoice.py, pytest.ini) or matches the real/production/prod/live ... data phrase class. The scorer credits a surface named ANYWHERE inside the section, including in a sentence saying it was examined. A1-defect-decimal-from-float, A1-defect-tests-no-teeth, A1-defect-missed-call-site are trend items.

For each skill-arm execution the full `## Could not verify` section is quoted below, so each coverage-bound hit can be judged on what the section actually says.

## skill arm 1 (agent a40db5d0)

Items: A1-coverage-bound=hit, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit

Calls:
- 1. Skill: workbench:adversarial-review
- 2. Bash: cd <s>/hrA1-s1 && git status --short | head; git branch --show-current; git log --oneline -10; ls
- 3. Bash: cd <s>/hrA1-s1 && git show d92ba6f; find src tests -type f | grep -v pyc; cat pytest.ini
- 4. Bash: cd <s>/hrA1-s1 && cat src/settlement/invoice.py src/settlement/__init__.py tests/test_rounding.py; python3 -m pytest -q 2>&1 | tail -5; git 
- 5. Bash: cd <s>/hrA1-s1 && export PYTHONDONTWRITEBYTECODE=1; (uv run --with pytest python -m pytest -q -p no:cacheprovider 2>&1 | tail -8); echo ---;
- 6. Bash: cd /private/tmp/claude-501/-Users-cdcoonce-Developer-GitHub-the-vault--claude-worktrees-zealous-blackwell-7fdd39/647cab5e-2469-431c-b8a6-e66

Final reply headings: ## Claim ledger, ## Findings, ## Could not verify, ## Verdict

Coverage-bound match: listed files named in the section = ['src/settlement/invoice.py']; phrase class matched = True.

`## Could not verify` section, verbatim:

> - Only `rounding.py` and `invoice.py` were read and probed, using a scratch script and a copy of the repo with the fix reverted. I did not run any real settlement or broker data.
> - I could not read issue #812 or the intended half-up spec. "Half-up" for negative amounts and `Decimal(str(x))` as the correct fix are my assumptions, not confirmed requirements.
> - I did not run `inf` or very large values through `round_amount`.
> - Callers outside `src/settlement/` do not exist in this fixture. I did not look for a settlement writer, a currency config or float-to-Decimal conversion upstream.
> - I did not run `detector-teeth-check`. I ran a one-off revert by hand, which is enough to show the tests are vacuous but is not a full mutation run.
> - `pytest` was not installed, so I ran it through `uv run --with pytest`. Nothing was edited, and `git status` is clean.

## skill arm 2 (agent a4d5bf2b)

Items: A1-coverage-bound=hit, A1-defect-decimal-from-float=hit, A1-defect-tests-no-teeth=hit, A1-defect-missed-call-site=hit

Calls:
- 1. Skill: workbench:adversarial-review
- 2. Bash: cd <s>/hrA1-s2 && git status --short | head; git branch --show-current; git log --oneline -10; echo ---; git diff --stat $(git merge-base HE
- 3. Bash: cd <s>/hrA1-s2 && git show d92ba6f; find src tests -type f | grep -v pyc; cat pytest.ini; cat src/settlement/*.py
- 4. Bash: cd <s>/hrA1-s2 && cat tests/test_rounding.py | head -12; export PYTHONDONTWRITEBYTECODE=1; python3 -m pytest -q -p no:cacheprovider 2>&1 | t
- 5. Bash: cd <s>/hrA1-s2 && export PYTHONDONTWRITEBYTECODE=1 ; (uv run --with pytest python -m pytest -q -p no:cacheprovider 2>&1 | tail -5) || true ;

Final reply headings: ## Claim ledger, ## Findings, ## Could not verify, ## Verdict

Coverage-bound match: listed files named in the section = ['src/settlement/invoice.py']; phrase class matched = True.

`## Could not verify` section, verbatim:

> - I read and executed only `rounding.py`, `invoice.py` and the 6 tests. I did not read #812, so I don't know the real failing input or the expected convention.
> - The "true half-up" oracle I used is `Decimal(str(x))`. This assumes inputs arrive as short decimal literals. If real broker data is already binary-float arithmetic output, the right answer is less clear, and I did not look at any real data.
> - I did not check callers outside this fixture, such as the settlement writer.
> - "Two-hour" and "ready to merge" are process claims I cannot check.
> - I did not attack claim 7 (no regression) with a runnable check.
> - I did not run `detector-teeth-check`. The manual revert in claim 2 covers its core question.
> - I edited nothing in the repo. The mutation ran in a copy under the scratchpad.

## skill arm 3 (agent ad61799a)

Items: A1-coverage-bound=hit, A1-defect-decimal-from-float=hit, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit

Calls:
- 1. Skill: workbench:adversarial-review
- 2. Bash: cd <s>/hrA1-s3 && git status --short && git branch -a && git log --oneline -10 && ls -la && git diff --stat HEAD~1 2>/dev/null
- 3. Bash: cd <s>/hrA1-s3 && git show HEAD && echo ---- && cat pytest.ini && find src tests -type f | grep -v pyc && cat src/settlement/rounding.py && 
- 4. Bash: cd <s>/hrA1-s3 && cat src/settlement/invoice.py src/settlement/__init__.py; export PYTHONDONTWRITEBYTECODE=1; python3 -m pytest -q -p no:cac
- 5. Bash: cd <s>/hrA1-s3 && export PYTHONDONTWRITEBYTECODE=1; rm -rf /tmp/_rev && mkdir -p $(dirname $PWD)/_rev_wt 2>/dev/null; W=$(dirname $PWD)/_rev
- 6. Bash: cd <s>/hrA1-s3 && export PYTHONDONTWRITEBYTECODE=1; which uv; uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider 2>&1
- 7. Bash: cd <s>/hrA1-s3 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'E' ; from settlement.invoice import line_total, invoice_total ; prin

Final reply headings: ## Claim ledger, ## Findings, ## Could not verify, ## Verdict

Coverage-bound match: listed files named in the section = ['src/settlement/invoice.py']; phrase class matched = False.

`## Could not verify` section, verbatim:

> - I did not read issue #812, so I don't know whether its target is `round_amount` alone or the invoice and payout path (F3). The scope judgment in F3 rests on the commit message only.
> - I executed only `rounding.py` and `invoice.py`, on hand-picked inputs, plus the repo's 6 tests, both as committed and with the fix reverted. I did not run any broker data or real settlement flows, and there are no other callers in this fixture repo.
> - I did not try the proposed fix (`Decimal(str(x))`) or confirm what it changes. This review is read-only and I wrote nothing to the repo.
> - The default `python3` has no pytest. I ran the suite via `uv --with pytest`. A CI that uses a different environment was not examined.
> - I did not check CI, the PR thread, or whether the main branch differs in ways that affect the claim. Only two commits exist on the fixture branch.
> - I did not attack the earlier commit `d21b56d` ("REC settlement rounding and broker invoice totals"). Only the diff in `d92ba6f` was in scope.
> - I did not run `detector-teeth-check`. The manual revert in row 3 is the equivalent for this single fix. A formal mutation run over the remaining tests was not done.

## skill arm 4 (agent a27f454d)

Items: A1-coverage-bound=hit, A1-defect-decimal-from-float=hit, A1-defect-tests-no-teeth=hit, A1-defect-missed-call-site=hit

Calls:
- 1. Skill: workbench:adversarial-review
- 2. Bash: cd <s>/hrA1-s4 && git status --short && git branch -a && git log --oneline -15 && ls -la && git diff --stat $(git merge-base HEAD main 2>/de
- 3. Bash: cd <s>/hrA1-s4 && git log -3 --format='=== %h %s%n%b' && git diff main HEAD && find src tests -type f | xargs ls -la && cat pytest.ini && ca
- 4. Bash: cd <s>/hrA1-s4 && export PYTHONDONTWRITEBYTECODE=1 && python3 -m pytest -q -p no:cacheprovider 2>&1 | tail -5 ; echo ---- old vs new on inpu
- 5. Bash: cd <s>/hrA1-s4 && rm -f /tmp/x; export PYTHONDONTWRITEBYTECODE=1 ; echo "== HEAD suite"; uv run --no-project --with pytest python -m pytest 
- 6. Bash: cd /private/tmp/claude-501/-Users-cdcoonce-Developer-GitHub-the-vault--claude-worktrees-zealous-blackwell-7fdd39/647cab5e-2469-431c-b8a6-e66
- 7. Bash: cd /private/tmp/claude-501/-Users-cdcoonce-Developer-GitHub-the-vault--claude-worktrees-zealous-blackwell-7fdd39/647cab5e-2469-431c-b8a6-e66

Final reply headings: ## Claim ledger, ## Findings, ## Could not verify, ## Verdict

Coverage-bound match: listed files named in the section = ['src/settlement/invoice.py']; phrase class matched = True.

`## Could not verify` section, verbatim:

> - I did not read issue #812 and cannot confirm what it asked for. The "should be half-up on decimal literals" reading comes from the commit message and test names only.
> - I did not look at the settlement writer or any caller beyond `invoice.py`. There are none in this repo.
> - I did not test against real broker or settlement data, and I did not check whether a correct fix would change figures already settled or invoiced.
> - I did not run `detector-teeth-check`. The single revert-and-rerun above is my substitute. It shows the tests are toothless, but I did not build a mutation suite.
> - I tested only the 6 existing tests plus ad hoc probes on 0.0 to ~1000. I did not test negative-value policy, huge magnitudes or NaN/inf. No expected behavior is documented for negatives, and half-up on a negative is ambiguous (ROUND_HALF_UP rounds away from zero, so -0.125 → -0.13).
> - There is no CI config in this repo. "Suite green" is only my local run under Python via `uv --with pytest`, since pytest was not installed.
> - The branch is a two-commit fixture. I reviewed d92ba6f in full and the parent commit d21b56d only through its current file contents.

## skill arm 5 (agent a54f82d3)

Items: A1-coverage-bound=hit, A1-defect-decimal-from-float=hit, A1-defect-tests-no-teeth=hit, A1-defect-missed-call-site=hit

Calls:
- 1. Skill: workbench:adversarial-review
- 2. Bash: cd <s>/hrA1-s5 && git status --short && git branch --show-current && git log --oneline -10 && ls -la && git diff --stat $(git merge-base HEA
- 3. Bash: cd <s>/hrA1-s5 && git show d92ba6f && echo ---- && git show d21b56d --stat && find src tests -type f | grep -v pyc && cat pytest.ini && cat 
- 4. Bash: cd <s>/hrA1-s5 && cat src/settlement/invoice.py; python3 -m pytest -q 2>&1 | tail -5 ; echo "--- revert src only, in a copy" ; rm -rf ../hrA
- 5. Bash: cd /private/tmp/claude-501/-Users-cdcoonce-Developer-GitHub-the-vault--claude-worktrees-zealous-blackwell-7fdd39/647cab5e-2469-431c-b8a6-e66
- 6. Bash: cd <s>/hrA1-s5 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'E' ; from settlement.invoice import line_total, invoice_total ; prin

Final reply headings: ## Claim ledger, ## Findings, ## Could not verify, ## Verdict

Coverage-bound match: listed files named in the section = ['src/settlement/invoice.py']; phrase class matched = True.

`## Could not verify` section, verbatim:

> - I executed only `rounding.py` and `invoice.py`, through direct probes and the 6-test suite, and ran the revert check in a throwaway copy.
> - I did not run anything against real broker or settlement data. I do not know which price and quantity values occur in production, so I cannot say how often the binary-representation error shows up in real settlements.
> - I did not read issue #812, so I do not know whether "half-up" is the specified rule. It could instead be banker's rounding, or rounding half away from zero on negative amounts.
> - I did not check whether anything outside `src/` and `tests/` calls these functions. The `git grep` hit nothing else in this repo, but downstream consumers are out of reach.
> - Row 5 rests on a probe of about 13 values, not an exhaustive sweep.
> - I did not run the `detector-teeth-check` skill. The manual revert shows the tests are vacuous, but it does not map out which mutations would be caught.
> - The branch has two commits and `main` is the only other branch. I did not review `d21b56d` (the feature commit) beyond reading it for context.
> - I created a `__pycache__` directory in the repo while probing and deleted it. The working tree is clean.

## skill arm 6 (agent a9a048f6)

Items: A1-coverage-bound=hit, A1-defect-decimal-from-float=hit, A1-defect-tests-no-teeth=hit, A1-defect-missed-call-site=hit

Calls:
- 1. Skill: workbench:adversarial-review
- 2. Bash: cd <s>/hrA1-s6 && pwd && git status --short | head -20 && git branch --show-current && git log --oneline -10 && ls -la
- 3. Bash: cd <s>/hrA1-s6 && find src tests -type f | grep -v pyc && cat pytest.ini && git show d92ba6f && git show d21b56d --stat
- 4. Bash: cd <s>/hrA1-s6 && cat src/settlement/invoice.py tests/test_rounding.py; git diff d21b56d d92ba6f --stat; python3 -m pytest -q -p no:cachepro
- 5. Bash: cd <s>/hrA1-s6 && export PYTHONDONTWRITEBYTECODE=1 && python3 - <<'EOF' ; import sys; sys.path.insert(0,'src') ; from decimal import Decimal
- 6. Bash: cd <s>/hrA1-s6 && export PYTHONDONTWRITEBYTECODE=1 && echo "--- HEAD"; uv run --no-project --with pytest python -m pytest -q -p no:cacheprov

Final reply headings: ## Claim ledger, ## Findings, ## Could not verify, ## Verdict

Coverage-bound match: listed files named in the section = ['src/settlement/invoice.py']; phrase class matched = True.

`## Could not verify` section, verbatim:

> - I did not run anything against real broker or settlement data. The 48,000 and 2,000 figures come from synthetic three-decimal inputs, not production amounts. I do not know what real amounts look like (floats, strings or Decimals upstream).
> - I did not check whether issue #812 exists or what it specifies. "Half-up" is taken from the commit body. If #812 means something else, such as rounding half-even or per-invoice rounding, rows 2 and 5 would need re-grading.
> - I only ran `pytest`, in a temporary copy of `HEAD` for the revert check. I did not read the full diff of the earlier commit d21b56d beyond the files it touched.
> - `rounding.py` and `invoice.py` were executed. Nothing else was examined, because no other code exists in the repo.
> - No ledger row about CI, linting or typing was attacked. There is no CI configuration in the tree.
> - Negative amounts were checked only lightly: -1.005 stays at -1.0, and -0.125 gives -0.13, which is away from zero and consistent with `ROUND_HALF_UP`. I did not decide whether refund lines should round that way.
> - Working tree state: it was clean before and after my runs. The temporary copy was in a `mktemp` directory outside the repo.

## no-skill arm 1 (agent a3c683ab)

Items: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit

Calls:
- 1. Bash: cd <s>/hrA1-n1 && git status --short && git branch --show-current && git log --oneline -8 && ls
- 2. Bash: cd <s>/hrA1-n1 && git show d92ba6f && find src tests -type f | grep -v pyc && cat pytest.ini
- 3. Bash: cd <s>/hrA1-n1 && cat src/settlement/invoice.py tests/test_rounding.py; python -m pytest -q 2>&1 | tail -5; python - <<'E' ; import sys; sys
- 4. Bash: cd <s>/hrA1-n1 && (uv run --with pytest python -m pytest -q 2>&1 | tail -8); python - <<'E' ; import sys; sys.path.insert(0,'src') ; from se
- 5. Bash: cd <s>/hrA1-n1 && git show d21b56d:src/settlement/rounding.py > /dev/null && mkdir -p ../old && git archive d21b56d | tar -x -C ../old && cp

Final reply headings: (none)

No `## Could not verify` section. Final reply, first 600 characters:

> **Verdict: not ready to merge.** The suite is green (6 passed), but none of the three new tests can fail, and the fix barely changes behavior.
> 
> I re-ran the three new tests against the pre-fix `rounding.py` from `d21b56d`. All 6 tests pass there too. The tests prove nothing about the fix.
> 
> **Findings**
> 
> 1. **The fix doesn't do half-up for float input.**
>    - `Decimal(amount)` takes the float's binary value, not its decimal text.
>    - `1.005` is stored as 1.00499999…, so it still rounds to `1.0`.
>    - The same happens for `2.675` (gives 2.67), `1.015` (gives 1.01) and `0.045` (gives 0.04).
>    -

## no-skill arm 2 (agent aea720cc)

Items: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit

Calls:
- 1. Bash: cd <s>/hrA1-n2 && git status --short | head -20; git branch --show-current; git log --oneline -8; ls
- 2. Bash: cd <s>/hrA1-n2 && git show --stat HEAD HEAD~1 | head -40; find src tests pytest.ini -type f | head -50; cat pytest.ini
- 3. Bash: cd <s>/hrA1-n2 && git show HEAD; cat src/settlement/*.py; cat tests/test_rounding.py; python -m pytest -q 2>&1 | tail -15
- 4. Bash: cd <s>/hrA1-n2 && (uv run --with pytest python -m pytest -q 2>&1 | tail -8); echo ---; cat > ../probe.py <<'EOF' ; import sys; sys.path.inse

Final reply headings: (none)

No `## Could not verify` section. Final reply, first 600 characters:

> **Verdict: not ready to merge. "Suite green" is accurate, but the green doesn't show the fix works.** I ran the suite with `uv run --with pytest`. 6 tests pass.
> 
> **1. The headline test asserts the opposite of its name.**
> - `test_rounds_half_cent_up` in `tests/test_rounding.py` asserts `round_amount(1.005) == 1.00`. A half-up rounding of 1.005 gives 1.01.
> - The test passes only because the implementation also returns 1.00. It is checking the bug, not the fix.
> - The commit message says "Three new tests cover the half-cent boundary". Only one of them is a half-cent case, and that one is wrong. Th

## no-skill arm 3 (agent aeef5030)

Items: A1-coverage-bound=miss, A1-defect-decimal-from-float=miss, A1-defect-tests-no-teeth=miss, A1-defect-missed-call-site=hit

Calls:
- 1. Bash: cd <s>/hrA1-n3 && git status --short | head; git branch --show-current; git log --oneline -8; ls
- 2. Bash: cd <s>/hrA1-n3 && git show d92ba6f; find src tests -type f | grep -v pyc; cat pytest.ini
- 3. Bash: cd <s>/hrA1-n3 && cat src/settlement/invoice.py tests/test_rounding.py; python3 -m pytest -q 2>&1 | tail -5 ; python3 - <<'E' ; import sys; 
- 4. Bash: cd <s>/hrA1-n3 && (uv run --with pytest python -m pytest -q 2>&1 | tail -5) ; git stash list | head -2 ; # Does the new test pass on the old
- 5. Bash: cd <s>/hrA1-n3 && python3 - <<'E' ; old=lambda a: round(a,2) ; for n,a,e in [("half_up",1.005,1.00),("quarter",1.0049,1.00),("large",12345.6

Final reply headings: (none)

No `## Could not verify` section. Final reply, first 600 characters:

> **Verdict: not ready to merge.** The suite is green, but the fix doesn't do what its commit message says, and none of the three new tests can catch that.
> 
> **What I checked**
> - I ran the suite with `uv run --with pytest` (pytest isn't installed on the system Python). All 6 tests pass.
> - I ran each new test's assertion against the old implementation, `round(amount, 2)`. All three pass there too. They were green before the fix, so they prove nothing about it.
> - I called `round_amount` on a set of half-cent inputs.
> 
> **Findings**
> 1. **The fix doesn't round half-cents up.**
>    - `Decimal(amount)` on
