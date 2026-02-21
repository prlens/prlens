# PR Lens Documentation

AI-powered GitHub PR code reviewer for teams. Reviews each changed file against your coding guidelines using Claude or GPT-4o, posts inline comments on GitHub, and keeps a shared history of past reviews.

---

## Topics

| Topic | Description |
|---|---|
| [Installation](installation.md) | Install prlens and its dependencies |
| [Quick Start](quickstart.md) | Get your first review running in minutes |
| [Configuration](configuration.md) | `.prlens.yml` reference — all keys and defaults |
| [CLI Reference](cli.md) | `review`, `init`, `history`, `stats` commands |
| [GitHub Action](github-action.md) | Automated CI reviews on every pull request |
| [AI Providers](providers.md) | Claude (Anthropic) and GPT-4o (OpenAI) |
| [History Stores](stores.md) | NoOp, SQLite, and Gist backends |
| [Guidelines](guidelines.md) | Default guidelines and how to write your own |
| [Codebase Context](codebase-context.md) | How prlens makes reviews codebase-aware |
| [Architecture](architecture.md) | Package layout and contribution guide |

---

## How It Works

1. **Fetch** — prlens fetches the PR diff and each changed file from the GitHub API, pinned to the PR's head SHA.
2. **Contextualise** — For each file it gathers three codebase signals: the repository file tree, files historically changed together, and the paired test file.
3. **Review** — It sends the diff, file content, context, and your guidelines to the configured AI provider.
4. **Post** — Inline review comments are posted via the GitHub Review API. A summary comment shows severity counts per file and how long the review took.
5. **Persist** — If a store is configured, the review record is saved for later querying with `prlens history` and `prlens stats`.
