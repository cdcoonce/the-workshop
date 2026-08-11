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
# nobody who has it installed. Compares against the release branch, so one bump
# covers everything that lands on dev between promotions.
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
	$(MAKE) stamp-check
	$(MAKE) verify-versions
