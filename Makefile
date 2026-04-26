.PHONY: setup build verify-built install-hooks test lint install bump release-prep

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

lint:           ## Check and format code (TRN-1002)
	.venv/bin/ruff check scripts/ tests/
	.venv/bin/ruff format --check scripts/ tests/

install:        ## Install Trinity to ~/.claude/ (TRN-1005)
	@mkdir -p ~/.claude/skills/trinity/scripts
	@mkdir -p ~/.claude/agents
	cp SKILL.md ~/.claude/skills/trinity/SKILL.md
	cp -r scripts/. ~/.claude/skills/trinity/scripts/
	cp providers/glm.md ~/.claude/agents/trinity-glm.md
	cp providers/codex.md ~/.claude/agents/trinity-codex.md
	cp providers/gemini.md ~/.claude/agents/trinity-gemini.md
	cp providers/openrouter.md ~/.claude/agents/trinity-openrouter.md
	cp providers/deepseek.md ~/.claude/agents/trinity-deepseek.md
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
		--cli "openrouter_cy -p" \
		--global-config ~/.claude/trinity.json
	python3 ~/.claude/skills/trinity/scripts/install.py register deepseek \
		--cli "deepseek_cy -p" \
		--global-config ~/.claude/trinity.json
	@echo "Installed Trinity $(CURRENT_VERSION)"

bump:           ## Bump version (TRN-1003): make bump VERSION=x.y.z
	@test -n "$(VERSION)" || (echo "Usage: make bump VERSION=x.y.z"; exit 1)
	@echo "$(VERSION)" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$$' || \
		(echo "Invalid semver: $(VERSION)"; exit 1)
	$(MAKE) build
	@echo "$(VERSION)" > VERSION
	@sed -i '' 's/__version__ = ".*"/__version__ = "$(VERSION)"/' scripts/__init__.py
	@sed -i '' 's/REQUIRED_VERSION=".*"/REQUIRED_VERSION="$(VERSION)"/' SKILL.md
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
	@git add VERSION scripts/__init__.py CHANGELOG.md SKILL.md
	@git commit -m "Release v$(CURRENT_VERSION)"
	@git tag "v$(CURRENT_VERSION)"
	@echo ""
	@echo "Prepared release commit + local tag v$(CURRENT_VERSION)."
	@echo "Next: git push origin <branch> v$(CURRENT_VERSION)"
	@echo "      then watch the Release workflow at github.com/frankyxhl/trinity/actions"
