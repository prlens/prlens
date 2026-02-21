# GitHub Action

prlens provides a composite GitHub Action that runs automatically on every pull request. No server, no polling — just drop in a workflow file.

---

## Quick Setup

### Option A — `prlens init` (recommended)

Run `prlens init` locally and answer yes when asked to generate the workflow file. It creates `.github/workflows/prlens.yml` with the correct permissions, secrets, and trigger configuration.

### Option B — Manual

Create `.github/workflows/prlens.yml` in any repository:

```yaml
name: PR Lens Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write

    steps:
      - uses: actions/checkout@v4

      - uses: codingdash/prlens/.github/actions/review@main
        with:
          model: anthropic
          github-token: ${{ secrets.GITHUB_TOKEN }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Then add `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) to your repository secrets:
**Settings → Secrets and variables → Actions → New repository secret**

---

## Action Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `model` | No | `anthropic` | AI provider: `anthropic` or `openai` |
| `github-token` | **Yes** | — | GitHub token with `pull-requests: write` |
| `anthropic-api-key` | No | `""` | Required when `model: anthropic` |
| `openai-api-key` | No | `""` | Required when `model: openai` |
| `guidelines` | No | `""` | Path to a Markdown guidelines file (relative to repo root) |
| `config-path` | No | `.prlens.yml` | Path to `.prlens.yml` (relative to repo root) |
| `full-review` | No | `false` | Set to `true` to re-review all files on every run |

---

## How the PR Number is Determined

The action uses GitHub's built-in event context — no configuration needed:

- `github.repository` → `owner/repo`
- `github.event.pull_request.number` → the PR that triggered the workflow

Both are injected automatically by the Actions runner when the workflow triggers on a `pull_request` event.

---

## GITHUB_TOKEN vs Personal Access Token

The built-in `GITHUB_TOKEN` (provided automatically by GitHub Actions) is sufficient to post review comments. It acts as the `github-actions[bot]` user, not as any real developer.

```yaml
github-token: ${{ secrets.GITHUB_TOKEN }}   # default — use this
```

To have comments appear as a specific user (a dedicated bot account, for example), create a Personal Access Token (PAT) for that account with `pull_requests: write`, store it as a secret (e.g. `PRLENS_GITHUB_TOKEN`), and use it instead:

```yaml
github-token: ${{ secrets.PRLENS_GITHUB_TOKEN }}   # custom user
```

> **Note:** If you use the Gist store, the built-in `GITHUB_TOKEN` does **not** have Gist permissions. You must use a PAT with `gist` scope. See [History Stores — Gist](stores.md#gist-store).

---

## Using Guidelines from a Central Repository

If your team maintains guidelines in a shared repository rather than each individual repo, check out that repository first.

### Private guidelines repo

```yaml
steps:
  - uses: actions/checkout@v4

  - uses: actions/checkout@v4
    with:
      repository: your-org/engineering-standards
      path: .guidelines
      token: ${{ secrets.GUIDELINES_REPO_TOKEN }}  # PAT with contents: read
      sparse-checkout: |
        guidelines/code-review.md

  - uses: codingdash/prlens/.github/actions/review@main
    with:
      model: anthropic
      github-token: ${{ secrets.GITHUB_TOKEN }}
      anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
      guidelines: .guidelines/guidelines/code-review.md
```

### Public guidelines repo

```yaml
  - uses: actions/checkout@v4
    with:
      repository: your-org/engineering-standards
      path: .guidelines
      # no token needed for public repos

  - uses: codingdash/prlens/.github/actions/review@main
    with:
      guidelines: .guidelines/guidelines/code-review.md
      # ... other inputs
```

---

## Using OpenAI

```yaml
- uses: codingdash/prlens/.github/actions/review@main
  with:
    model: openai
    github-token: ${{ secrets.GITHUB_TOKEN }}
    openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

---

## Full Example with All Options

```yaml
name: PR Lens Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write

    steps:
      - uses: actions/checkout@v4

      - uses: codingdash/prlens/.github/actions/review@main
        with:
          model: anthropic
          github-token: ${{ secrets.GITHUB_TOKEN }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          guidelines: docs/review-guidelines.md
          config-path: .prlens.yml
          full-review: 'false'
```

---

## Secrets Checklist

| Secret | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | If using Claude | Add in repo Settings → Secrets → Actions |
| `OPENAI_API_KEY` | If using GPT-4o | Add in repo Settings → Secrets → Actions |
| `GITHUB_TOKEN` | **Auto-provided** | Do not add manually |
| `PRLENS_GITHUB_TOKEN` | Only if using a custom bot user | PAT with `pull_requests: write` |
| `GUIDELINES_REPO_TOKEN` | Only if guidelines repo is private | PAT with `contents: read` on guidelines repo |
