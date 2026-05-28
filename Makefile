.PHONY: setup build verify-built install-hooks test lint coverage install install-codex pr-update bump release-prep

# Read VERSION at make invocation time
CURRENT_VERSION := $(shell cat VERSION 2>/dev/null || echo "0.0.0")

setup:          ## Create venv and install dev dependencies (uv → pip fallback)
	@if command -v uv >/dev/null 2>&1; then \
		uv venv && uv pip install pytest pytest-cov 'pytest-bdd>=7,<8' coverage[toml] ruff; \
	else \
		python3 -m venv .venv && .venv/bin/pip install pytest pytest-cov 'pytest-bdd>=7,<8' coverage[toml] ruff; \
	fi

build:          ## Compose providers/*.md (TRN-2004) and copy Codex skill (TRN-3043)
	@bash scripts/build_providers.sh
	@bash scripts/build_codex_skill.sh

verify-built:   ## Confirm generated artifacts match sources (TRN-2004 providers, TRN-3043 codex skill)
	@bash scripts/build_providers.sh --check
	@bash scripts/build_codex_skill.sh --check

install-hooks:  ## Install git pre-commit hook to run generated-artifact checks (TRN-2004, TRN-3043)
	@cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Installed pre-commit hook → .git/hooks/pre-commit"

test:           ## Run all tests (TRN-1001 + TRN-2004 build tests + TRN-2006 release workflow tests)
	$(MAKE) verify-built
	.venv/bin/pytest tests/ -v
	bash tests/test_build_providers.sh
	bash tests/test_release_workflow.sh
	bash tests/test_install_sh.sh
	bash tests/test_make_bump.sh
	bash tests/test_scan_rocket_issues.sh

lint:           ## Check and format code (TRN-1002)
	.venv/bin/ruff check dev/ scripts/ tests/
	.venv/bin/ruff format --check dev/ scripts/ tests/

coverage:       ## Measure line coverage with subprocess tracking (TRN-2023, fail-under 80%)
	.venv/bin/coverage erase
	COVERAGE_PROCESS_START=$(CURDIR)/.coveragerc .venv/bin/coverage run -m pytest tests/ -q
	.venv/bin/coverage combine
	.venv/bin/coverage report --include='scripts/*' --fail-under=80

install:        ## Install Trinity to ~/.claude/ (TRN-1005)
	@mkdir -p ~/.claude/skills/trinity/scripts
	@mkdir -p ~/.claude/skills/trinity/bin
	@mkdir -p ~/.claude/skills/trinity/providers
	@mkdir -p ~/.claude/agents
	cp SKILL.md ~/.claude/skills/trinity/SKILL.md
	cp -r scripts/. ~/.claude/skills/trinity/scripts/
	cp providers/registry.json ~/.claude/skills/trinity/providers/registry.json
	python3 scripts/install_from_manifest.py
	python3 ~/.claude/skills/trinity/scripts/install.py register-from-registry \
		~/.claude/skills/trinity/providers/registry.json \
		--global-config ~/.claude/trinity.json
	python3 ~/.claude/skills/trinity/scripts/install.py register gemini \
		--cli "gemini -p" \
		--global-config ~/.claude/trinity.json
	@echo "Installed Trinity $(CURRENT_VERSION)"

install-codex:  ## Install Trinity Codex adapter to ~/.codex/ and ~/.local/bin
	@mkdir -p ~/.codex/skills/trinity/scripts
	@mkdir -p ~/.codex/skills/trinity/bin
	@mkdir -p ~/.local/bin
	cp .agents/skills/trinity/SKILL.md ~/.codex/skills/trinity/SKILL.md
	cp .agents/trinity.codex.json ~/.codex/skills/trinity/trinity.codex.json
	cp -r scripts/. ~/.codex/skills/trinity/scripts/
	cp providers/bin/deepseek ~/.codex/skills/trinity/bin/deepseek
	cp bin/trinity ~/.local/bin/trinity
	chmod +x ~/.codex/skills/trinity/bin/deepseek ~/.local/bin/trinity
	python3 ~/.codex/skills/trinity/scripts/codex.py init-config \
		--global-config ~/.codex/trinity.json
	@echo "Installed Trinity Codex adapter $(CURRENT_VERSION)"

MODE ?= amend

TRINITY_PR_UPDATE_PR := $(value PR)
TRINITY_PR_UPDATE_MODE := $(value MODE)
TRINITY_PR_UPDATE_MESSAGE := $(value MESSAGE)
TRINITY_PR_UPDATE_REVIEW := $(value REVIEW)
TRINITY_PR_UPDATE_DRY_RUN := $(if $(filter 1 true yes,$(DRY_RUN)),1,0)
export TRINITY_PR_UPDATE_PR
export TRINITY_PR_UPDATE_MODE
export TRINITY_PR_UPDATE_MESSAGE
export TRINITY_PR_UPDATE_REVIEW
export TRINITY_PR_UPDATE_DRY_RUN


pr-update:      ## Validate, update current PR branch, push, and comment: make pr-update PR=20 MESSAGE="..."
	@test -n "$$TRINITY_PR_UPDATE_PR" || (echo "Usage: make pr-update PR=<num> MESSAGE=\"...\" [MODE=amend|commit|comment-only] [DRY_RUN=1] [REVIEW=\"...\"]"; exit 1)
	@test -n "$$TRINITY_PR_UPDATE_MESSAGE" || (echo "Usage: make pr-update PR=<num> MESSAGE=\"...\" [MODE=amend|commit|comment-only] [DRY_RUN=1] [REVIEW=\"...\"]"; exit 1)
	scripts/pr-update.sh


bump:           ## Bump version (TRN-1003): make bump VERSION=x.y.z
	@test -n "$(VERSION)" || (echo "Usage: make bump VERSION=x.y.z"; exit 1)
	@echo "$(VERSION)" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$$' || \
		(echo "Invalid semver: $(VERSION)"; exit 1)
	$(MAKE) build
	@echo "$(VERSION)" > VERSION
	@perl -i -pe 's/__version__ = ".*"/__version__ = "$(VERSION)"/' scripts/__init__.py
	@perl -i -pe 's/REQUIRED_VERSION=".*"/REQUIRED_VERSION="$(VERSION)"/' SKILL.md
	@perl -i -pe 's/^  "version": "[0-9]+\.[0-9]+\.[0-9]+",/  "version": "$(VERSION)",/' plugins/trinity/.codex-plugin/plugin.json
	@perl -i -pe 's#Trinity [0-9]+\.[0-9]+\.[0-9]+ installed to ~/\.claude/#Trinity $(VERSION) installed to ~/.claude/#' README.md
	@perl -i -pe 's/TRINITY_VERSION=[0-9]+\.[0-9]+\.[0-9]+/TRINITY_VERSION=$(VERSION)/' README.md
	@echo "Bumped to $(VERSION)"

release-prep:   ## Stage release-metadata commit + local tag (TRN-1004): no push, CI publishes
	@if git rev-parse -q --verify "refs/tags/v$(CURRENT_VERSION)" >/dev/null 2>&1; then \
		echo "Tag already exists: v$(CURRENT_VERSION)"; exit 1; \
	fi
	$(MAKE) verify-built
	$(MAKE) test
	$(MAKE) lint
	@git diff --quiet providers/ || (echo "release-prep: providers/ has uncommitted changes — run 'make build' and commit first"; exit 1)
	@git diff --quiet .agents/skills/trinity/SKILL.md plugins/trinity/skills/trinity/SKILL.md && \
		git diff --cached --quiet .agents/skills/trinity/SKILL.md plugins/trinity/skills/trinity/SKILL.md || \
		(echo "release-prep: Codex skill copy has uncommitted changes — run 'make build' and commit first"; exit 1)
	@git reset HEAD
	@git add VERSION scripts/__init__.py CHANGELOG.md SKILL.md plugins/trinity/.codex-plugin/plugin.json README.md
	@git commit -m "Release v$(CURRENT_VERSION)"
	@git tag "v$(CURRENT_VERSION)"
	@echo ""
	@echo "Prepared release commit + local tag v$(CURRENT_VERSION)."
	@echo "Next: git push origin <branch> v$(CURRENT_VERSION)"
	@echo "      then watch the Release workflow at github.com/frankyxhl/trinity/actions"
