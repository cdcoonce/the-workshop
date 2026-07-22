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

# Remove dist/<name> trees whose preset no longer exists, so a deleted preset
# can't leave an installable orphan behind.
.PHONY: prune-dist
prune-dist:
	@for d in dist/*/; do \
		[ -d "$$d" ] || continue; \
		b=$$(basename "$$d"); \
		case " $(PRESETS) " in *" $$b "*) : ;; *) echo "pruning stale dist/$$b"; rm -rf "$$d";; esac; \
	done

# Regenerate the marketplace index and rebuild every preset into dist/.
.PHONY: build
build: prune-dist
	uv run python -m scripts.build_marketplace
	@for p in $(PRESETS); do uv run python -m scripts.build_preset $$p >/dev/null; done

# Drift gate: docs must be fresh (build_docs --check) and a fresh rebuild of
# dist/marketplace must be a NO-OP on the working tree. Staleness is judged by
# content (scripts.dist_digest before vs after the rebuild), not by git status
# against HEAD — an uncommitted-but-correct dist/ (e.g. an afk slice's
# deliverable diff syncing shared core/ files into preset copies) passes; a
# source change whose regenerated output wasn't included still fails.
.PHONY: verify-generated
verify-generated:
	uv run python -m scripts.build_docs --check
	@before="$$(uv run python -m scripts.dist_digest)"; \
	$(MAKE) prune-dist; \
	uv run python -m scripts.build_marketplace >/dev/null; \
	for p in $(PRESETS); do uv run python -m scripts.build_preset $$p >/dev/null; done; \
	after="$$(uv run python -m scripts.dist_digest)"; \
	if [ "$$before" != "$$after" ]; then \
		echo "ERROR: dist/ or marketplace is stale — a fresh rebuild changed the generated output."; \
		echo "digest before rebuild: $$before"; \
		echo "digest after rebuild:  $$after"; \
		echo "Run 'make build' and include the regenerated files in your change:"; \
		git status --porcelain -- dist .claude-plugin/marketplace.json .agents/plugins/marketplace.json; \
		exit 1; \
	fi

# Full gate: the root suite, the daa-code-review analyzer suite (#141), the
# transcript-notes script suite, and the generated-docs/dist drift gate. The
# script suites live in isolated subtrees with a sibling `scripts` package and
# bare imports, so they run in their OWN rootdir (a separate pytest invocation)
# — collecting them in the root process collides on the `tests` package name.
.PHONY: test
test:
	uv run --with pytest python -m pytest -q tests
	cd core/skills/daa-code-review/scripts && uv run --with pytest --with ruff python -m pytest -q tests
	cd core/skills/transcript-notes/scripts && uv run --with pytest python -m pytest -q tests
	$(MAKE) verify-generated
