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

PRESETS := $(notdir $(wildcard presets/*))

# Regenerate the living reference docs (docs/reference/ + README tables) from
# component source. Run after changing any skill, hook, agent, or preset.
.PHONY: docs
docs:
	uv run python -m scripts.build_docs

# Regenerate the marketplace index and rebuild every preset into dist/.
.PHONY: build
build:
	uv run python -m scripts.build_marketplace
	@for p in $(PRESETS); do uv run python -m scripts.build_preset $$p >/dev/null; done

# Drift gate: docs must be fresh (build_docs --check) and dist/marketplace must
# match a fresh rebuild. Fails if any generated output diverges from source, so
# a component change that skips `make docs && make build` can't land green.
.PHONY: verify-generated
verify-generated:
	uv run python -m scripts.build_docs --check
	uv run python -m scripts.build_marketplace
	@for p in $(PRESETS); do uv run python -m scripts.build_preset $$p >/dev/null; done
	@dirty="$$(git status --porcelain -- dist .claude-plugin/marketplace.json .agents/plugins/marketplace.json)"; \
	if [ -n "$$dirty" ]; then \
		echo "ERROR: dist/ or marketplace is stale — run 'make build' and commit:"; \
		echo "$$dirty"; \
		exit 1; \
	fi

# Full gate: the root suite, the daa-code-review analyzer suite (#141), and the
# generated-docs/dist drift gate. The analyzer tests live in an isolated subtree
# with a sibling `scripts` package and bare imports, so they run in their OWN
# rootdir (a second pytest invocation) — collecting them in the root process
# collides on the `tests` package name. They also shell out to `ruff`, hence
# `--with ruff`.
.PHONY: test
test:
	uv run --with pytest python -m pytest -q tests
	cd core/skills/daa-code-review/scripts && uv run --with pytest --with ruff python -m pytest -q tests
	$(MAKE) verify-generated
