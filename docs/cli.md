# CLI Reference

```
Usage: prlens [OPTIONS] COMMAND [ARGS]...

  AI-powered GitHub PR code reviewer for teams.

Options:
  --version      Show the version and exit.
  --config TEXT  Path to the configuration file.  [default: .prlens.yml]
  --help         Show this message and exit.

Commands:
  review   Run AI review on a pull request
  init     Interactive team setup wizard
  history  Show past review records
  stats    Aggregated comment statistics
```

---

## `prlens review`

Run an AI review on a pull request. Fetches the PR diff, reviews each changed file against your guidelines, and posts inline comments on GitHub.

```
Usage: prlens review [OPTIONS]

Options:
  --repo TEXT                GitHub repository (owner/name).  [required]
  --pr INTEGER               Pull request number. Omit to pick interactively.
  --model [anthropic|openai] AI provider. Overrides config file.
  --guidelines PATH          Markdown guidelines file. Overrides config file.
  --config TEXT              Config file path.  [default: .prlens.yml]
  -y, --yes                  Skip confirmation prompts.
  -s, --shadow               Dry-run: print comments without posting to GitHub.
  --full-review              Review all files even if a previous review exists.
```

### Required Environment Variables

| Variable | When Required |
|---|---|
| `GITHUB_TOKEN` | Always (or `gh auth login` fallback) |
| `ANTHROPIC_API_KEY` | When `model: anthropic` |
| `OPENAI_API_KEY` | When `model: openai` |

### Examples

```bash
# Review PR #42
prlens review --repo owner/repo --pr 42

# Pick a PR interactively
prlens review --repo owner/repo

# Dry run — see what would be posted
prlens review --repo owner/repo --pr 42 --shadow

# Automate with no prompts
prlens review --repo owner/repo --pr 42 --yes

# Re-review all files (ignore previous review)
prlens review --repo owner/repo --pr 42 --full-review

# Use a specific provider for this run
prlens review --repo owner/repo --pr 42 --model openai

# Use custom guidelines for this run
prlens review --repo owner/repo --pr 42 --guidelines ./strict.md
```

### Review Events

The GitHub review event is determined by the highest severity comment:

| Highest Severity | Event |
|---|---|
| None | `APPROVE` |
| `nitpick` or `minor` | `COMMENT` |
| `major` or `critical` | `REQUEST_CHANGES` |

### Batching

If the number of comments exceeds `batch_limit` (default: 60), prlens splits the review into multiple API calls. Intermediate batches are posted as `COMMENT`; the final batch carries the computed event (`APPROVE`, `COMMENT`, or `REQUEST_CHANGES`).

---

## `prlens init`

Interactive setup wizard. Configures prlens for your team by creating `.prlens.yml`, optionally setting up a review history store, and generating a GitHub Actions workflow.

```
Usage: prlens init [OPTIONS]

Options:
  --repo TEXT  GitHub repository (owner/name). Auto-detected from git remote.
```

### Wizard Prompts

1. **Repository** — auto-detected from `git remote get-url origin`. Supports both HTTPS and SSH remotes.
2. **AI provider** — `anthropic` (default) or `openai`.
3. **Store backend**:
   - `none` (default) — no persistence
   - `sqlite` — local SQLite file; prompts for path (default: `.prlens.db`)
   - `gist` — shared GitHub Gist; creates the Gist automatically via `gh` CLI
4. **GitHub Actions workflow** — optionally generates `.github/workflows/prlens.yml`.

### What `init` Creates

| File | Always | Notes |
|---|---|---|
| `.prlens.yml` | Yes | Preserves existing keys if file already exists |
| `.github/workflows/prlens.yml` | Optional | Prompted during wizard |
| GitHub Gist | Optional | Only if `gist` store selected; requires `gh` CLI |

### Notes on Gist Store

- Requires `gh` CLI to be installed and authenticated (`gh auth login`).
- The built-in `GITHUB_TOKEN` in GitHub Actions does **not** have Gist permissions — you will need a PAT with `gist` scope stored as a repository secret.

---

## `prlens history`

Display past review records from the configured store.

```
Usage: prlens history [OPTIONS]

Options:
  --repo TEXT      GitHub repository (owner/name).  [required]
  --pr INTEGER     Filter by PR number.
  --limit INTEGER  Maximum records to show.  [default: 20]
```

Requires a store backend to be configured (`sqlite` or `gist`). Raises an error if the store is `noop`.

Records are shown newest-first in a Rich table with columns: PR#, Title, SHA, Event, Comments, Reviewed At.

### Examples

```bash
# Show recent reviews
prlens history --repo owner/repo

# Show reviews for a specific PR
prlens history --repo owner/repo --pr 42

# Show up to 50 records
prlens history --repo owner/repo --limit 50
```

---

## `prlens stats`

Aggregate review comment statistics for a repository.

```
Usage: prlens stats [OPTIONS]

Options:
  --repo TEXT   GitHub repository (owner/name).  [required]
  --top INTEGER Number of top entries per category.  [default: 10]
```

Requires a store backend to be configured (`sqlite` or `gist`). Raises an error if the store is `noop`.

### Output

- **Summary** — total reviews, total comments, average comments per review.
- **Severity Breakdown** — count and percentage for critical, major, minor, nitpick.
- **Most Flagged Files** — top N files by total comment count.

### Examples

```bash
# Show stats for a repo
prlens stats --repo owner/repo

# Show top 20 flagged files
prlens stats --repo owner/repo --top 20
```

---

## Token Resolution

prlens resolves the GitHub token in this order:

1. `GITHUB_TOKEN` environment variable — highest precedence.
2. `gh auth token` — reuses the token from an active `gh auth login` session.
3. If neither is available, the command exits with an error.

This means developers who already use the GitHub CLI need no extra token setup.
