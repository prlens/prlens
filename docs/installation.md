# Installation

## Requirements

- Python 3.9 or later
- A GitHub account with access to the repository you want to review
- An API key for at least one AI provider (Anthropic or OpenAI)

---

## Install from PyPI

Install with your preferred AI provider:

```bash
pip install 'prlens[anthropic]'   # Claude (default)
pip install 'prlens[openai]'      # GPT-4o
pip install 'prlens[all]'         # both providers
```

Installing `prlens` automatically pulls in `prlens-core` and `prlens-store`.

---

## GitHub Token

prlens needs a GitHub token to fetch PR diffs and post review comments.

**Option A — Environment variable (CI / explicit):**
```bash
export GITHUB_TOKEN=ghp_...
```

**Option B — GitHub CLI (zero-friction local use):**

If you already use `gh`, prlens will reuse your existing session automatically:
```bash
gh auth login   # run once
# no GITHUB_TOKEN needed after this
```

The token must have `pull_requests: write` permission on the target repository.

---

## AI Provider Keys

Set the API key for your chosen provider:

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI GPT-4o
export OPENAI_API_KEY=sk-...
```

---

## Verify Installation

```bash
prlens --version
prlens --help
```

---

## Next Steps

- [Quick Start](quickstart.md) — run your first review
- [Configuration](configuration.md) — set up `.prlens.yml`
- [GitHub Action](github-action.md) — automate reviews on every PR
