.PHONY: setup build verify-built install-hooks test lint install bump release

# Read VERSION at make invocation time
CURRENT_VERSION := $(shell cat VERSION 2>/dev/null || echo "0.0.0")

setup:          ## Create venv and install dev dependencies
	uv venv
	uv pip install pytest ruff

build:          ## Compose providers/*.md from _base/ partials and *.delta.md (TRN-2004)
	@bash scripts/build_providers.sh

verify-built:   ## Confirm committed providers/*.md matches partial sources (TRN-2004)
	@bash scripts/build_providers.sh --check

install-hooks:  ## Install git pre-commit hook to run verify-built (TRN-2004)
	@cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Installed pre-commit hook → .git/hooks/pre-commit"

test:           ## Run all tests (TRN-1001 + TRN-2004 build tests)
	$(MAKE) verify-built
	.venv/bin/pytest tests/ -v
	bash tests/test_build_providers.sh

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
		--cli "codex exec --skip-git-repo-check" \
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

release:        ## Cut a release (TRN-1004): make release (reads VERSION from file)
	@command -v gh >/dev/null 2>&1 || (echo "gh CLI required: brew install gh"; exit 1)
	@if git rev-parse -q --verify "refs/tags/v$(CURRENT_VERSION)" >/dev/null 2>&1; then \
		echo "Tag already exists: v$(CURRENT_VERSION)"; exit 1; \
	fi
	$(MAKE) test
	$(MAKE) lint
	@git reset HEAD
	@git add VERSION scripts/__init__.py CHANGELOG.md SKILL.md
	@git commit -m "Release v$(CURRENT_VERSION)"
	@git tag "v$(CURRENT_VERSION)"
	@git push || \
		(git tag -d "v$(CURRENT_VERSION)"; git reset --soft HEAD~1; \
		 echo "Branch push failed — commit rolled back (4 files are staged), local tag deleted"; exit 1)
	@git push origin "v$(CURRENT_VERSION)" || \
		(echo "Tag push failed — branch is on remote, tag is local only. Run: git push origin v$(CURRENT_VERSION)"; exit 1)
	@NOTES=$$(awk '/^## \[$(CURRENT_VERSION)\]/{found=1; next} found && /^## \[/{exit} found{print}' CHANGELOG.md); \
		gh release create "v$(CURRENT_VERSION)" --title "v$(CURRENT_VERSION)" --notes "$$NOTES" || \
		echo "WARNING: tag pushed but gh release failed. Run: gh release create v$(CURRENT_VERSION) --title v$(CURRENT_VERSION) manually"
