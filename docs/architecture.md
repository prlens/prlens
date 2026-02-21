# Architecture

prlens is a Python monorepo with three independently installable packages and one GitHub Action.

---

## Package Layout

```
packages/
├── core/     prlens-core  — review engine (providers, context, orchestration)
├── store/    prlens-store — pluggable history backends
└── cli/      prlens       — CLI commands and entry point
apps/
└── github-action/         — composite GitHub Action
docs/                      — this documentation
```

Installing `prlens` (the CLI package) automatically pulls in `prlens-core` and `prlens-store`.

---

## Dependency Graph

```
prlens (CLI)
├── prlens-core
│   ├── PyGithub
│   ├── pyyaml
│   ├── python-dotenv
│   └── anthropic / openai  (optional extras)
└── prlens-store
    └── PyGithub
```

**Isolation rules:**
- `prlens-core` has no knowledge of stores or the CLI.
- `prlens-store` has no knowledge of the review engine or the CLI.
- `prlens` (CLI) bridges both via the `ReviewSummary` dataclass and `_build_store()` factory.

---

## Core Package (`prlens-core`)

### Providers

All providers implement the Template Method pattern via `BaseReviewer`:

```
BaseReviewer
├── review()             — public entry point (concrete)
├── _build_system_prompt — injects guidelines (concrete)
├── _build_user_prompt   — builds per-file prompt (concrete)
├── _call_with_retry     — 3 retries with backoff (concrete)
├── _parse               — strips outer fence, loads JSON (concrete)
└── _call_api            — one raw API call (abstract — implement per provider)

AnthropicReviewer(_call_api → anthropic SDK)
OpenAIReviewer(_call_api → openai SDK)
```

Subclasses implement **only** `__init__` (validate and store the SDK client) and `_call_api` (make one raw API call and return the text response).

### Review Orchestration (`reviewer.py`)

`run_review()` is the top-level function called by the CLI:

1. Fetch PR and detect incremental vs full review mode
2. Fetch the repository file tree once for the entire run (pinned to head SHA)
3. For each changed file:
   - Skip excluded files and non-code files
   - Fetch file content from GitHub API
   - Gather codebase context (`gather_context`)
   - Call `process_file()` → `reviewer.review()`
4. Determine the GitHub review event from highest severity
5. Post review comments in batches
6. Return `ReviewSummary` for the CLI to persist

### `ReviewSummary` Dataclass

`run_review()` returns a `ReviewSummary` rather than posting to the store directly. This keeps `prlens-core` free of any store dependency while giving the CLI layer everything it needs to persist the record.

```python
@dataclass
class ReviewSummary:
    repo: str
    pr_number: int
    head_sha: str
    event: str            # "APPROVE" | "COMMENT" | "REQUEST_CHANGES"
    reviewed_files: list[str]
    skipped_files: list[str]
    total_comments: int
    comments: list[dict]
    reviewed_at: str      # ISO 8601 UTC
```

---

## Store Package (`prlens-store`)

### Base Class

```python
class BaseStore(ABC):
    def save(self, record: ReviewRecord) -> None: ...
    def list_reviews(self, repo: str, pr_number: int | None) -> list[ReviewRecord]: ...
    def close(self) -> None: ...   # optional — default is a no-op
```

### Implementations

| Class | Backend | Notes |
|---|---|---|
| `NoOpStore` | None | Discards all records |
| `SQLiteStore` | Local SQLite file | Thread-safe via SQLite WAL |
| `GistStore` | GitHub Gist JSON | Append-only, requires gist-scoped token |

### Data Model

```python
@dataclass
class ReviewRecord:
    repo: str
    pr_number: int
    pr_title: str
    reviewer_model: str
    head_sha: str
    reviewed_at: str
    event: str
    total_comments: int
    files_reviewed: int
    comments: list[CommentRecord]

@dataclass
class CommentRecord:
    file: str
    line: int
    severity: str
    comment: str
```

---

## CLI Package (`prlens`)

### Entry Point

`prlens_cli.cli:main` — a Click group that:
1. Loads config via `load_config()`
2. Resolves a GitHub token via `resolve_github_token()`
3. Instantiates the store via `_build_store()`
4. Passes both via `ctx.obj` to subcommands
5. Calls `store.close()` on exit

### Commands

| Command | Module |
|---|---|
| `review` | `prlens_cli.commands.review` |
| `init` | `prlens_cli.commands.init` |
| `history` | `prlens_cli.commands.history` |
| `stats` | `prlens_cli.commands.stats` |

### Token Resolution (`auth.py`)

```
GITHUB_TOKEN env var  →  return
gh auth token         →  return
None                  →  caller raises UsageError
```

---

## Adding a New AI Provider

1. Create `packages/core/src/prlens_core/providers/your_provider.py`
2. Subclass `BaseReviewer` — implement only `__init__` and `_call_api`
3. Register in `packages/core/src/prlens_core/reviewer.py` inside `_get_reviewer()`
4. Add the provider name to `--model` choices in `packages/cli/src/prlens_cli/commands/review.py`
5. Add the optional SDK to `packages/core/pyproject.toml` under `[project.optional-dependencies]`
6. Write tests in `packages/core/tests/test_providers.py`

---

## Adding a New Store Backend

1. Create `packages/store/src/prlens_store/your_backend.py`
2. Subclass `BaseStore` — implement `save()` and `list_reviews()`
3. Register in `packages/cli/src/prlens_cli/cli.py` inside `_build_store()`
4. Write tests in `packages/store/tests/test_stores.py`

---

## Versioning

All three packages share the same version number, stored in the root `VERSION` file. Running `make release` bumps the version in `VERSION`, all three `pyproject.toml` files, and the dependency pins in `packages/cli/pyproject.toml`, then builds and uploads to PyPI.

---

## Running Tests

```bash
# All packages
pytest packages/core/tests packages/store/tests packages/cli/tests -v

# With coverage
pytest packages/core/tests packages/store/tests packages/cli/tests \
  --cov=prlens_core --cov=prlens_store --cov=prlens_cli \
  --cov-report=term-missing
```

## Code Style

Black (formatting) and flake8 (linting) run automatically on every commit via pre-commit hooks.

```bash
# Format
make format

# Lint
make lint

# All hooks
pre-commit run --all-files
```
