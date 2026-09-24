# afk fleet git conventions — apply the committed .gitconfig to this clone.
#
# Self-contained (no afk-driver dependency): wires include.path idempotently,
# so `git config` settings in .gitconfig (e.g. fetch.prune) take effect here.
# The afk executor also applies this automatically during its cycle preflight.
.PHONY: setup
setup:
	@git config --local --get-all include.path | grep -qx '../.gitconfig' \
		|| git config --local --add include.path '../.gitconfig'
	@echo "wired git conventions (.gitconfig)"

PLUGINS := $(notdir $(wildcard plugins/*))

# Lint the repo's own Python (tooling, tests, hook scripts) against the
# high-signal rule set pinned in pyproject.toml. Scoped to real defects, so a
# clean run means something; see the [tool.ruff.lint] comment for why E501 is out.
.PHONY: lint
lint:
	uv run --with ruff ruff check scripts tests plugins

# Delivery gate: a plugin whose shipped content changed must also declare a new
# version, or `claude plugin update` offers nothing and the change reaches
# nobody who has it installed. Defaults to the release branch, which is what a
# push to dev or main wants. CI overrides it with the PR's target branch on pull
# requests (#568), so a PR into dev must out-version dev itself: run
# `VERSION_BASE=origin/dev make test` before opening one.
.PHONY: verify-versions
verify-versions:
	uv run python -m scripts.check_version_bumps --base $(VERSION_BASE)

VERSION_BASE ?= origin/main

# The repo's only build component. `stamp` writes every generated file from the
# hand-written truth in the tree (each plugin's `.claude-plugin/plugin.json`,
# SKILL.md/AGENT.md frontmatter, and each hook script's own WORKSHOP_HOOK
# declaration). `stamp-check` renders the same path map in memory and fails,
# naming the file and printing a diff, on anything committed stale.
.PHONY: stamp
stamp:
	uv run python -m scripts.stamp

.PHONY: stamp-check
stamp-check:
	uv run python -m scripts.stamp --check

# Teeth-spec drift gate: a detector-teeth-check spec anchors each mutant on an
# exact source string, so a refactor of the quoted code stales it with every
# suite still green (#941 found two by hand). Resolves every committed spec's
# anchors via `teeth_check.py --check-anchors` — no baseline, no mutant runs.
# Specs are DISCOVERED from the index (`*.teeth.json`, `teeth-spec-*.json`),
# so a new one is gated the moment it is committed. `file` paths resolve
# against the spec's own directory, so no per-spec cwd is needed here.
.PHONY: check-teeth-anchors
check-teeth-anchors:
	uv run python -m scripts.check_teeth_anchors

# Vault machinery suite: the vault's engine scripts ship as workbench payload
# (plugins/workbench/machinery/). Like the skill-script suites, the tests live
# in an isolated subtree beside the code they exercise and run in their OWN
# rootdir (a separate pytest invocation from machinery/). Deps mirror the
# vault's dev group (pytest/hypothesis/numpy) plus its pyyaml runtime
# dependency, wired with `uv run --with` exactly as the skill-script runner
# does. graphmark is graph_cli's own pinned dependency — without it the
# alias-resolver suite importorskips itself and CI reports green on tests it
# never ran.
.PHONY: test-machinery
test-machinery:
	cd plugins/workbench/machinery && uv run --with pytest --with hypothesis --with numpy --with pyyaml --with 'graphmark>=0.6,<0.7' python -m pytest -q tests

# graphmark version-matrix parity: the rest of the machinery suite runs under
# graphmark 0.6 (graph_cli's own pinned floor), but command.md and the
# vault's own ci/vault_health.py gate both pin graphmark>=0.7,<0.8 — the
# wrap-up collector's `gate` check (plugins/workbench/machinery/engine/
# wrap_up_audit.py) reads graphmark.config.CheckPolicy and graphmark.check,
# and 0.6/0.7 can disagree on edge fixtures. Runs only that one suite, under
# 0.7, so a real disagreement fails loudly here instead of shipping unnoticed.
#
# Deliberately NOT `cd plugins/workbench/machinery` first: that directory is
# its own uv project (pyproject.toml pins graphmark>=0.6,<0.7) with a synced
# `.venv/` already on disk. `uv run --with 'graphmark>=0.7,<0.8'` from
# INSIDE it resolves 0.7.2 correctly but then silently imports 0.6.0 from
# that pre-existing `.venv` anyway — verified with `uv run -v`, which shows
# `Selecting: graphmark==0.7.2` immediately followed by an import from
# `machinery/.venv/lib/.../graphmark/__init__.py` (0.6.0). `--no-project` and
# `--isolated` do not change this. Running from the repo root instead (whose
# own `.venv`/pyproject never mention graphmark) has no such shadow — the
# `--with` overlay is what actually gets imported. Confirmed by literally
# counting: this file collects 71 tests total, 3 of them gated
# `@NEEDS_GRAPHMARK_07`; running the wrong way silently reports 68 passed +
# 3 skipped, no error, looking like a clean run.
.PHONY: test-wrap-up-gate-parity
test-wrap-up-gate-parity:
	uv run --with pytest --with hypothesis --with numpy --with pyyaml --with 'graphmark>=0.7,<0.8' python -m pytest -q plugins/workbench/machinery/tests/test_wrap_up_audit.py

# Same graphmark version-matrix parity target, for the cold-read evidence
# resolver's wikilink resolution (plugins/workbench/machinery/engine/
# cold_read_evidence.py, via graph_cli.diagnose). command.md pins
# graphmark>=0.7,<0.8 for this script too. Same shadow-bug reasoning as
# test-wrap-up-gate-parity above: deliberately NOT `cd
# plugins/workbench/machinery` first, or the `--with 'graphmark>=0.7,<0.8'`
# overlay silently imports that directory's own pinned 0.6.0 `.venv`
# instead — confirmed the same way, by printing
# `importlib.metadata.version("graphmark")` inside the pytest process
# (test_graphmark_07_wikilink_resolution_matches_06).
.PHONY: test-cold-read-evidence-wikilink-parity
test-cold-read-evidence-wikilink-parity:
	uv run --with pytest --with hypothesis --with numpy --with pyyaml --with 'graphmark>=0.7,<0.8' python -m pytest -q plugins/workbench/machinery/tests/test_cold_read_evidence.py

# Full gate: the root suite, every skill-script suite, and the machinery suite.
# Skill-script suites live in isolated subtrees with a sibling `scripts` package
# and bare imports, so they run in their OWN rootdir (a separate pytest
# invocation) — collecting them in the root process collides on the `tests`
# package name. They are DISCOVERED automatically
# (scripts.discover_skill_test_suites), so a new skill's tests can never fall
# out of the gate by a forgotten Makefile line.
.PHONY: test
test:
	$(MAKE) lint
	uv run --with pytest python -m pytest -q tests
	uv run python -m scripts.discover_skill_test_suites
	$(MAKE) test-machinery
	$(MAKE) test-wrap-up-gate-parity
	$(MAKE) test-cold-read-evidence-wikilink-parity
	$(MAKE) check-teeth-anchors
	$(MAKE) stamp-check
	$(MAKE) verify-versions
