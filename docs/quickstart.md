# Quick Start

## Option A — Team setup with `prlens init` (recommended)

Run once in your repository. The wizard configures everything interactively.

```bash
pip install 'prlens[anthropic]'
prlens init
```

The wizard will:
1. Auto-detect your GitHub repository from `git remote`
2. Ask which AI provider to use (`anthropic` or `openai`)
3. Ask which history store to use (`none`, `sqlite`, or `gist`)
4. Optionally generate `.github/workflows/prlens.yml` for CI

After `init`, commit `.prlens.yml` (and the workflow file if generated). Every developer on the team can then run reviews with no extra setup if they have `gh` installed and are logged in.

---

## Option B — Manual quick start

```bash
pip install 'prlens[anthropic]'

export GITHUB_TOKEN=ghp_...
export ANTHROPIC_API_KEY=sk-ant-...

prlens review --repo owner/repo --pr 42
```

---

## Running a Review

```bash
# Review a specific PR
prlens review --repo owner/repo --pr 42

# Pick a PR interactively from the list of open PRs
prlens review --repo owner/repo

# Dry run — print comments without posting to GitHub
prlens review --repo owner/repo --pr 42 --shadow

# Skip confirmation prompts (useful in scripts)
prlens review --repo owner/repo --pr 42 --yes

# Re-review all files regardless of previous reviews
prlens review --repo owner/repo --pr 42 --full-review
```

---

## What Happens After a Review

prlens posts two things to the GitHub PR:

1. **Inline comments** — one comment per issue, anchored to the specific line in the diff. Each comment starts with a severity badge (`[CRITICAL]`, `[MAJOR]`, `[MINOR]`, `[NITPICK]`).

2. **Review summary** — a top-level review body with:
   - A one-line verdict
   - A per-file table showing issue counts by severity
   - Time taken to complete the review

The review event is set automatically:
- `APPROVE` — no issues found
- `COMMENT` — only minor / nitpick issues
- `REQUEST_CHANGES` — at least one critical or major issue

---

## Incremental Reviews

By default, prlens only reviews files changed since the last review. It tracks progress via an HTML comment (`<!-- prlens-sha: ... -->`) embedded in the review summary. Use `--full-review` to override and re-review all files.

---

## Next Steps

- [Configuration](configuration.md) — customise `.prlens.yml`
- [GitHub Action](github-action.md) — automate on every PR
- [Guidelines](guidelines.md) — write guidelines for your team
- [History Stores](stores.md) — persist and query review history
