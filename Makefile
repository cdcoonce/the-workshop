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

# Full gate: the root suite plus the daa-code-review analyzer suite (#141).
# The analyzer tests live in an isolated subtree with a sibling `scripts`
# package and bare imports, so they run in their OWN rootdir (a second pytest
# invocation) — collecting them in the root process collides on the `tests`
# package name. They also shell out to `ruff`, hence `--with ruff`.
.PHONY: test
test:
	uv run --with pytest python -m pytest -q tests
	cd core/skills/daa-code-review/scripts && uv run --with pytest --with ruff python -m pytest -q tests
