PYTHON_VERSION := 3.12.2
VENV_NAME := prlens-3.12.2

.SILENT:

.PHONY: pyenv
pyenv:
	echo "[1/4] Installing python version $(PYTHON_VERSION)"
	@pyenv install -s "$(PYTHON_VERSION)"
	echo "[2/4] Installing virtual environment $(VENV_NAME)"
	# Check if the virtual environment exists
	@if ! pyenv virtualenvs | grep -q "$(VENV_NAME)"; then \
		pyenv virtualenv "$(PYTHON_VERSION)" "$(VENV_NAME)"; \
	fi
	echo "[3/4] Installing pip"
	@pip install --quiet --upgrade pip
	echo "[4/4] Installing packages"
	@pip install --quiet -e packages/core[dev,all] -e packages/store[dev] -e packages/cli[dev]
	echo "All set!"


.PHONY: install
install:
	make pyenv
	pip install -e packages/core[dev,all] -e packages/store[dev] -e packages/cli[dev]
	pre-commit install

.PHONY: test
test:
	pytest packages/core/tests packages/store/tests packages/cli/tests -v

.PHONY: lint
lint:
	flake8 packages/core/src packages/store/src packages/cli/src --max-line-length=120

.PHONY: format
format:
	black packages/core/src packages/store/src packages/cli/src \
	      packages/core/tests packages/store/tests packages/cli/tests

.PHONY: release
release:
	@CURRENT=$$(cat VERSION); \
	echo "Current version: $$CURRENT"; \
	read -p "New version: " NEW; \
	if [ -z "$$NEW" ]; then echo "Aborted: no version entered."; exit 1; fi; \
	echo "Bumping $$CURRENT → $$NEW"; \
	echo "$$NEW" > VERSION; \
	sed -i '' "s/^version = \"$$CURRENT\"/version = \"$$NEW\"/" packages/core/pyproject.toml; \
	sed -i '' "s/^version = \"$$CURRENT\"/version = \"$$NEW\"/" packages/store/pyproject.toml; \
	sed -i '' "s/^version = \"$$CURRENT\"/version = \"$$NEW\"/" packages/cli/pyproject.toml; \
	sed -i '' "s/prlens-core>=[0-9.]*/prlens-core>=$$NEW/" packages/cli/pyproject.toml; \
	sed -i '' "s/prlens-store>=[0-9.]*/prlens-store>=$$NEW/" packages/cli/pyproject.toml; \
	sed -i '' "s|review@v$$CURRENT|review@v$$NEW|" README.md; \
	sed -i '' "s/default: '$$CURRENT'/default: '$$NEW'/" .github/actions/review/action.yml; \
	echo "Installing build tools..."; \
	pip install --quiet --upgrade build twine; \
	echo "Building packages..."; \
	rm -rf dist/; \
	python -m build packages/core  --outdir dist/ --quiet; \
	python -m build packages/store --outdir dist/ --quiet; \
	python -m build packages/cli   --outdir dist/ --quiet; \
	echo "Built:"; \
	ls dist/; \
	read -p "Upload to PyPI? [y/N] " CONFIRM; \
	if [ "$$CONFIRM" = "y" ] || [ "$$CONFIRM" = "Y" ]; then \
		twine upload dist/*; \
	else \
		echo "Skipped upload. Run 'twine upload dist/*' when ready."; \
	fi
