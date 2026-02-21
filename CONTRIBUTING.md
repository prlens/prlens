# Contributing to prlens

Thank you for your interest in contributing! This document covers how to set up a development environment, run tests, and submit changes.

## Repository Structure

prlens is a monorepo with three packages:

```
packages/
├── core/     prlens-core  — review engine (providers, context, orchestration)
├── store/    prlens-store — pluggable history backends
└── cli/      prlens       — CLI commands (review, init, history, stats)
apps/
└── github-action/         — composite GitHub Action
```

## Development Setup

```bash
git clone https://github.com/codingdash/prlens.git
cd prlens

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install all packages in editable mode with dev and provider dependencies
pip install -e packages/core[dev,all] -e packages/store[dev] -e packages/cli[dev]

# Install pre-commit hooks
pre-commit install
```

Or via Make:

```bash
make install
```

## Running Tests

```bash
# All packages at once
pytest packages/core/tests packages/store/tests packages/cli/tests -v

# Single package
pytest packages/core/tests -v
pytest packages/store/tests -v
pytest packages/cli/tests -v
```

## Code Style

This project uses [Black](https://black.readthedocs.io/) for formatting and [flake8](https://flake8.pycqa.org/) for linting. Both run automatically on every commit via pre-commit.

```bash
# Format
black packages/core/src packages/store/src packages/cli/src \
      packages/core/tests packages/store/tests packages/cli/tests

# Lint
flake8 packages/core/src packages/store/src packages/cli/src --max-line-length=120

# All pre-commit hooks
pre-commit run --all-files
```

## Adding a New AI Provider

1. Create `packages/core/src/prlens_core/providers/your_provider.py`
2. Subclass `BaseReviewer` from `prlens_core/providers/base.py` — implement only `__init__` and `_call_api`
3. Register it in `packages/core/src/prlens_core/reviewer.py` inside `_get_reviewer()`
4. Add the provider name to the `--model` choice in `packages/cli/src/prlens_cli/commands/review.py`
5. Add the optional SDK to `packages/core/pyproject.toml` under `[project.optional-dependencies]`
6. Write provider-specific tests in `packages/core/tests/test_providers.py`

## Adding a New Store Backend

1. Create `packages/store/src/prlens_store/your_backend.py`
2. Subclass `BaseStore` from `prlens_store/base.py` — implement `save()` and `list_reviews()`
3. Register it in `packages/cli/src/prlens_cli/cli.py` inside `_build_store()`
4. Add tests in `packages/store/tests/test_stores.py`

## Adding or Updating Guidelines

Default guidelines live in `packages/core/src/prlens_core/guidelines/`. These are meant to be sensible defaults for most teams — keep them generic, avoiding tool-specific or organisation-specific references. Teams can always override them via `.prlens.yml`.

## Submitting a Pull Request

1. Fork the repository and create a feature branch.
2. Write tests for any new behaviour.
3. Ensure `pytest` and `pre-commit run --all-files` both pass.
4. Open a pull request with a clear description of the change and its motivation.
