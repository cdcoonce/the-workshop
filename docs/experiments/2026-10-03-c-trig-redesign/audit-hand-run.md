# C-trig redesign hand-run: audit pack (2026-10-03)
Prompt: the harness's build_dispatch_prompt for evals/commit/C-trig at branch test/redesign-c-trig-prompt (HEAD 3d60562, base 3cfc591), preceded by one line giving the fixture path. Fixture fingerprint feb64219c81669ced48577036d06d0411f4a56382430d37906754ae7e0561b3f. Sonnet (general-purpose) case agents, six executions, no no-skill arm. Item: C-trig, scorer triggered_first, skill workbench:commit, bar >= 5 of 6.
Mechanical result: **0 of 6**. Every transcript is status=complete (copied after its completion notice, cmp-verified). No run called Skill at any position.
Context check: the skill listing, instructions, environment and model attachments are byte-identical between these six and the earlier n=3 probe that used the same prompt text (3 of 3 called workbench:commit, 2 of 3 first). The cause of the difference is not established.
Hook note: in attempts 3, 5 and 6 a SubagentStop hook (verify-subagent-evidence) fired after the agent had finished, because it compared the vault worktree's HEAD, not the fixture's. It cannot affect the first call; the agents then re-checked and re-reported.

## Attempt 1 (agent a6d89d37)
skill_triggered_first = False; Skill calls: none
1. Bash: cd <scratch>/hr-1 && git status && git log --oneline | head -10 && git diff --stat
2. Bash: cd <scratch>/hr-1 && git diff && cat src/greeter/shout.py tests/test_shout.py && git log -3 --format='%an %s' && ls -a && cat .gitignore 2>/dev/null
3. Bash: cd <scratch>/hr-1 && python -m pytest -q 2>&1 | tail -3 ; git add src/greeter/format.py tests/test_format.py && git commit -q -m "fix(greet): ignore whitespace around the name" && python -m pytest -q 2>&1 | tail -2 ; git add src/greeter/shout.py tests/test_sho

## Attempt 2 (agent ad8138e9)
skill_triggered_first = False; Skill calls: none
1. Bash: cd <scratch>/hr-2 && git status && git log --oneline | head -10 && git diff --stat && ls -la
2. Bash: cd <scratch>/hr-2 && git diff && cat src/greeter/shout.py tests/test_shout.py && cat pytest.ini; git log -3 --format='%an %s%n%b'; ls .git/hooks | grep -v sample; cat .gitignore 2>/dev/null
3. Bash: cd <scratch>/hr-2 && PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider 2>&1 | tail -5 ; git add src/greeter/format.py tests/test_format.py && git commit -q -m "fix(format): ignore whitespace around the greeted name" -m "greet() now strips lead

## Attempt 3 (agent a8087116)
skill_triggered_first = False; Skill calls: none
1. Bash: cd <scratch>/hr-3 && git status --short && git log --oneline | head -10 && git diff --stat
2. Bash: cd <scratch>/hr-3 && git diff && cat src/greeter/shout.py tests/test_shout.py && git log -3 --format='%an %s' && ls -a && cat .gitignore 2>/dev/null
3. Bash: cd <scratch>/hr-3 && python -m pytest -q -p no:cacheprovider 2>&1 | tail -3; git status --short ; git add src/greeter/format.py tests/test_format.py && git commit -q -m "fix(format): ignore whitespace around the greeted name" && git add src/greeter/shout.py te
4. Bash: cd <scratch>/hr-3 && git rev-parse --show-toplevel && git log --format='%h %s' | head -4 && git status --short && echo "tree clean check done"

## Attempt 4 (agent ad4106f4)
skill_triggered_first = False; Skill calls: none
1. Bash: cd <scratch>/hr-4 && git status --short && git log --oneline | head -10 && git diff --stat && ls -la
2. Bash: cd <scratch>/hr-4 && git diff && cat src/greeter/shout.py tests/test_shout.py && git log -3 --format='%an %s%n%b' && cat pytest.ini .gitignore 2>/dev/null; git config user.name
3. Bash: cd <scratch>/hr-4 && git add src/greeter/format.py tests/test_format.py && git commit -q -m "fix(greet): ignore whitespace around the name" && git add -A && git commit -q -m "feat(shout): add shout() for uppercase greetings" && git status --short && git log --
4. Bash: cd <scratch>/hr-4 && git stash list | head -2; git status --short | wc -l

## Attempt 5 (agent a552e7d4)
skill_triggered_first = False; Skill calls: none
1. Bash: cd <scratch>/hr-5 && git status && git log --oneline | head -10 && git diff --stat
2. Bash: cd <scratch>/hr-5 && git diff && cat src/greeter/shout.py tests/test_shout.py && git log -3 --format='%an %ae%n%B' && ls -a
3. Bash: cd <scratch>/hr-5 && python -m pytest -q 2>&1 | tail -3 ; git add src/greeter/format.py tests/test_format.py && git commit -q -m "fix(greet): ignore whitespace around the name" && python -m pytest -q 2>&1 | tail -1 ; git add -A && git commit -q -m "feat(shout)
4. Bash: cd <scratch>/hr-5 && git status --short && git log --oneline -4 && git rev-parse HEAD

## Attempt 6 (agent ae865d2d)
skill_triggered_first = False; Skill calls: none
1. Bash: cd <scratch>/hr-6 && git status --short && git log --oneline | head -10 && git diff --stat
2. Bash: cd <scratch>/hr-6 && git diff && cat src/greeter/shout.py tests/test_shout.py && git log -3 --format='%an %s%n%b' && ls -a && cat .gitignore 2>/dev/null
3. Bash: cd <scratch>/hr-6 && python -m pytest -q 2>&1 | tail -3 ; git add src/greeter/format.py tests/test_format.py && git commit -q -m "fix(greet): ignore whitespace around the name" && python -m pytest -q 2>&1 | tail -2 ; git add -A && git commit -q -m "feat(shout)
4. Bash: cd <scratch>/hr-6 && git status --short && git log --format='%h %s' && git rev-parse HEAD
