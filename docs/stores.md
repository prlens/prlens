# History Stores

prlens can persist review records so you can query past reviews with `prlens history` and `prlens stats`. Three backends are available.

---

## Choosing a Backend

| Backend | Best For | Infrastructure | Shared Across Team |
|---|---|---|---|
| `noop` | One-off reviews, no history needed | None | No |
| `sqlite` | Solo developers, local history | Local file | No |
| `gist` | Teams, zero infra | GitHub Gist | Yes |

---

## NoOp Store (default)

The default store. Discards all review records — reviews are posted to GitHub but not persisted anywhere.

```yaml
store: noop   # or omit entirely
```

No configuration needed. `prlens history` and `prlens stats` will return an error if the store is `noop`.

---

## SQLite Store

Stores review history in a local SQLite database file.

```yaml
store: sqlite
store_path: .prlens.db   # optional — this is the default path
```

### Setup

Add the above to `.prlens.yml`. The database file is created automatically on first use.

### Usage

```bash
prlens history --repo owner/repo
prlens history --repo owner/repo --pr 42
prlens stats   --repo owner/repo
```

### Notes

- The database file is local — history is not shared across machines or team members.
- Add `.prlens.db` to `.gitignore` if you don't want to commit it.
- Safe to delete the file to reset history; it will be recreated.

---

## Gist Store

Stores review history in a private GitHub Gist as an append-only JSON array. Zero infrastructure — any team member with GitHub access can read the shared history.

```yaml
store: gist
gist_id: abc123def456   # created by `prlens init`
```

### Setup with `prlens init` (recommended)

Run `prlens init` and select `gist` as the store. prlens automatically creates a private Gist and writes the `gist_id` to `.prlens.yml`.

```bash
prlens init
# → Store backend: gist
# → Created team Gist: abc123def456
```

Commit `.prlens.yml` — every team member and CI run will now share the same history.

### Manual Setup

1. Create a private Gist containing a file named `prlens_history.json` with content `[]`.
2. Copy the Gist ID from the URL (`gist.github.com/<username>/<gist-id>`).
3. Add to `.prlens.yml`:
   ```yaml
   store: gist
   gist_id: <your-gist-id>
   ```

### Token Requirements

The Gist store requires a GitHub token with **`gist` scope**.

| Context | Token | Has Gist Scope? |
|---|---|---|
| Local (`GITHUB_TOKEN` env var) | Your PAT | Only if you included `gist` scope when creating it |
| Local (`gh auth login` fallback) | gh CLI token | Yes — `gh` tokens have gist scope by default |
| GitHub Actions (`GITHUB_TOKEN`) | Auto-provided | **No** — Actions tokens are repo-scoped only |

**For GitHub Actions:** Create a PAT with `gist` scope, store it as a repository secret (e.g. `PRLENS_GITHUB_TOKEN`), and use it in your workflow:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.PRLENS_GITHUB_TOKEN }}
```

### Data Format

The Gist contains a single file `prlens_history.json` — a JSON array where each element is a review record:

```json
[
  {
    "repo": "owner/repo",
    "pr_number": 42,
    "pr_title": "Add user authentication",
    "reviewer_model": "anthropic",
    "head_sha": "abc1234...",
    "reviewed_at": "2025-01-15T10:30:00+00:00",
    "event": "REQUEST_CHANGES",
    "total_comments": 3,
    "files_reviewed": 2,
    "comments": [
      {
        "file": "src/auth.py",
        "line": 42,
        "severity": "major",
        "comment": "Missing null check"
      }
    ]
  }
]
```

### Failure Handling

If the Gist store fails to persist a record (e.g. wrong token scope), the error is printed as a warning but the review is **not** aborted — the review comments are already posted to GitHub. The Gist write is best-effort.

---

## Querying History

Both SQLite and Gist support the same query interface:

```bash
# Show last 20 reviews for a repo
prlens history --repo owner/repo

# Filter to a specific PR
prlens history --repo owner/repo --pr 42

# Show up to 50 records
prlens history --repo owner/repo --limit 50

# Aggregated stats
prlens stats --repo owner/repo

# Show top 20 most flagged files
prlens stats --repo owner/repo --top 20
```
