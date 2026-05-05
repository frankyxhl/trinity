.PHONY: setup build verify-built install-hooks test lint install install-codex pr-update bump release-prep

# Read VERSION at make invocation time
CURRENT_VERSION := $(shell cat VERSION 2>/dev/null || echo "0.0.0")

setup:          ## Create venv and install dev dependencies (uv → pip fallback)
	@if command -v uv >/dev/null 2>&1; then \
		uv venv && uv pip install pytest ruff; \
	else \
		python3 -m venv .venv && .venv/bin/pip install pytest ruff; \
	fi

build:          ## Compose providers/*.md from _base/ partials and *.delta.md (TRN-2004)
	@bash scripts/build_providers.sh

verify-built:   ## Confirm committed providers/*.md matches partial sources (TRN-2004)
	@bash scripts/build_providers.sh --check

install-hooks:  ## Install git pre-commit hook to run verify-built (TRN-2004)
	@cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Installed pre-commit hook → .git/hooks/pre-commit"

test:           ## Run all tests (TRN-1001 + TRN-2004 build tests + TRN-2006 release workflow tests)
	$(MAKE) verify-built
	.venv/bin/pytest tests/ -v
	bash tests/test_build_providers.sh
	bash tests/test_release_workflow.sh
	bash tests/test_make_bump.sh

lint:           ## Check and format code (TRN-1002)
	.venv/bin/ruff check dev/ scripts/ tests/
	.venv/bin/ruff format --check dev/ scripts/ tests/

install:        ## Install Trinity to ~/.claude/ (TRN-1005)
	@mkdir -p ~/.claude/skills/trinity/scripts
	@mkdir -p ~/.claude/skills/trinity/bin
	@mkdir -p ~/.claude/agents
	cp SKILL.md ~/.claude/skills/trinity/SKILL.md
	cp -r scripts/. ~/.claude/skills/trinity/scripts/
	cp providers/glm.md ~/.claude/agents/trinity-glm.md
	cp providers/codex.md ~/.claude/agents/trinity-codex.md
	cp providers/gemini.md ~/.claude/agents/trinity-gemini.md
	cp providers/openrouter.md ~/.claude/agents/trinity-openrouter.md
	cp providers/deepseek.md ~/.claude/agents/trinity-deepseek.md
	cp providers/bin/deepseek ~/.claude/skills/trinity/bin/deepseek
	cp providers/bin/openrouter ~/.claude/skills/trinity/bin/openrouter
	chmod +x ~/.claude/skills/trinity/bin/deepseek ~/.claude/skills/trinity/bin/openrouter
	python3 ~/.claude/skills/trinity/scripts/install.py register glm \
		--cli "droid exec --model glm-5" \
		--global-config ~/.claude/trinity.json
	python3 ~/.claude/skills/trinity/scripts/install.py register codex \
		--cli "codex exec --skip-git-repo-check -m gpt-5.5" \
		--global-config ~/.claude/trinity.json
	python3 ~/.claude/skills/trinity/scripts/install.py register gemini \
		--cli "gemini -p" \
		--global-config ~/.claude/trinity.json
	python3 ~/.claude/skills/trinity/scripts/install.py register openrouter \
		--cli "$(HOME)/.claude/skills/trinity/bin/openrouter -p" \
		--global-config ~/.claude/trinity.json
	python3 ~/.claude/skills/trinity/scripts/install.py register deepseek \
		--cli "$(HOME)/.claude/skills/trinity/bin/deepseek -p" \
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
export TRINITY_PR_UPDATE_PR
export TRINITY_PR_UPDATE_MODE
export TRINITY_PR_UPDATE_MESSAGE
export TRINITY_PR_UPDATE_REVIEW

pr-update:      ## Validate, update current PR branch, push, and comment: make pr-update PR=20 MESSAGE="..."
	@test -n "$$TRINITY_PR_UPDATE_PR" || (echo "Usage: make pr-update PR=<num> MESSAGE=\"...\" [MODE=amend|commit|comment-only] [DRY_RUN=1] [REVIEW=\"...\"]"; exit 1)
	@test -n "$$TRINITY_PR_UPDATE_MESSAGE" || (echo "Usage: make pr-update PR=<num> MESSAGE=\"...\" [MODE=amend|commit|comment-only] [DRY_RUN=1] [REVIEW=\"...\"]"; exit 1)
	python3 dev/pr_update.py --pr "$$TRINITY_PR_UPDATE_PR" --message "$$TRINITY_PR_UPDATE_MESSAGE" --mode "$$TRINITY_PR_UPDATE_MODE" \
		$(if $(filter 1 true yes,$(DRY_RUN)),--dry-run,) \
		$(if $(strip $(value REVIEW)),--review "$$TRINITY_PR_UPDATE_REVIEW",)

bump:           ## Bump version (TRN-1003): make bump VERSION=x.y.z
	@test -n "$(VERSION)" || (echo "Usage: make bump VERSION=x.y.z"; exit 1)
	@echo "$(VERSION)" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$$' || \
		(echo "Invalid semver: $(VERSION)"; exit 1)
	$(MAKE) build
	@echo "$(VERSION)" > VERSION
	@perl -i -pe 's/__version__ = ".*"/__version__ = "$(VERSION)"/' scripts/__init__.py
	@perl -i -pe 's/REQUIRED_VERSION=".*"/REQUIRED_VERSION="$(VERSION)"/' SKILL.md
	@perl -i -pe 's/^  "version": "[0-9]+\.[0-9]+\.[0-9]+",/  "version": "$(VERSION)",/' plugins/trinity/.codex-plugin/plugin.json
	@echo "Bumped to $(VERSION)"

release-prep:   ## Stage release-metadata commit + local tag (TRN-1004): no push, CI publishes
	@if git rev-parse -q --verify "refs/tags/v$(CURRENT_VERSION)" >/dev/null 2>&1; then \
		echo "Tag already exists: v$(CURRENT_VERSION)"; exit 1; \
	fi
	$(MAKE) verify-built
	$(MAKE) test
	$(MAKE) lint
	@git diff --quiet providers/ || (echo "release-prep: providers/ has uncommitted changes — run 'make build' and commit first"; exit 1)
	@git reset HEAD
	@git add VERSION scripts/__init__.py CHANGELOG.md SKILL.md plugins/trinity/.codex-plugin/plugin.json
	@git commit -m "Release v$(CURRENT_VERSION)"
	@git tag "v$(CURRENT_VERSION)"
	@echo ""
	@echo "Prepared release commit + local tag v$(CURRENT_VERSION)."
	@echo "Next: git push origin <branch> v$(CURRENT_VERSION)"
	@echo "      then watch the Release workflow at github.com/frankyxhl/trinity/actions"
