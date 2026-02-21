# Configuration

prlens is configured via a `.prlens.yml` file in your repository root. All keys are optional — sensible defaults are applied when a key is absent.

---

## Full Reference

```yaml
# AI provider: anthropic | openai
model: anthropic

# Review history store: noop (default) | sqlite | gist
store: noop

# SQLite store — path to the database file (only used when store: sqlite)
store_path: .prlens.db

# Gist store — Gist ID created by `prlens init` (only used when store: gist)
# gist_id: abc123def456

# Path to your team's coding guidelines (Markdown). If omitted, prlens uses
# its built-in backend guidelines.
# guidelines: docs/review-guidelines.md

# Maximum characters fed to the AI per file (diff + full file content).
# Longer files are truncated with a notice.
max_chars_per_file: 20000

# Maximum inline comments per GitHub review API call.
# Reviews exceeding this are split into batches.
batch_limit: 60

# Review draft PRs. Set to true to include drafts.
review_draft_prs: false

# Files and directories to skip — fnmatch globs or directory names.
# exclude:
#   - migrations/
#   - "*.min.js"
#   - "*.lock"
#   - "*.pb.go"
#   - vendor/
```

---

## Key Reference

| Key | Type | Default | Description |
|---|---|---|---|
| `model` | string | `anthropic` | AI provider: `anthropic` or `openai` |
| `store` | string | `noop` | History backend: `noop`, `sqlite`, or `gist` |
| `store_path` | string | `.prlens.db` | SQLite file path (only used with `store: sqlite`) |
| `gist_id` | string | — | GitHub Gist ID (only used with `store: gist`) |
| `guidelines` | string | — | Path to a Markdown guidelines file |
| `max_chars_per_file` | int | `20000` | Character limit per file before truncation |
| `batch_limit` | int | `60` | Max comments per GitHub API review call |
| `review_draft_prs` | bool | `false` | Whether to review draft PRs |
| `exclude` | list | `[]` | fnmatch patterns for files/directories to skip |

---

## Config File Location

By default prlens looks for `.prlens.yml` in the current working directory. Override with:

```bash
prlens --config path/to/custom.yml review --repo owner/repo --pr 42
```

Or set the environment variable:

```bash
export PRLENS_CONFIG=path/to/custom.yml
```

---

## CLI Overrides

Flags passed on the command line take precedence over `.prlens.yml`:

```bash
# Use a different provider just for this run
prlens review --repo owner/repo --pr 42 --model openai

# Use a different guidelines file just for this run
prlens review --repo owner/repo --pr 42 --guidelines ./strict-guidelines.md
```

---

## Exclude Patterns

The `exclude` list accepts:

- **Directory prefixes** — `migrations/`, `vendor/`
  Matches any file whose path starts with or contains that directory segment.
- **Glob patterns on the full path** — `src/generated/*.py`
- **Glob patterns on the basename** — `*.lock`, `*.min.js`

```yaml
exclude:
  - migrations/
  - vendor/
  - "*.lock"
  - "*.min.js"
  - "*.pb.go"
  - "*.generated.*"
  - src/generated/
```

---

## Store Configuration

See [History Stores](stores.md) for full details on each backend.

### SQLite (local, solo use)

```yaml
store: sqlite
store_path: .prlens.db   # optional, this is the default
```

### Gist (team, zero infrastructure)

```yaml
store: gist
gist_id: abc123def456    # created automatically by `prlens init`
```

The Gist store requires a GitHub token with `gist` scope. The built-in `GITHUB_TOKEN` in GitHub Actions does not have this — use a PAT stored as a repository secret.
