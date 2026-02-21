# prlens-store

Pluggable review history backends for [prlens](https://github.com/codingdash/prlens) — AI-powered GitHub PR code reviewer for teams.

## What's in this package

| Backend | Class | Description |
|---|---|---|
| `noop` | `NoOpStore` | Default — no persistence, zero config |
| `gist` | `GistStore` | Shared GitHub Gist, zero infrastructure |
| `sqlite` | `SQLiteStore` | Local SQLite file |

## Installation

```bash
pip install prlens-store
```

This package is a library dependency of [`prlens`](https://pypi.org/project/prlens/). Install `prlens` directly unless you are embedding history storage in your own tool.

## Usage

```python
from prlens_store.sqlite import SQLiteStore

store = SQLiteStore(".prlens.db")
records = store.list_reviews("owner/repo")
store.close()
```

## Links

- [Documentation & CLI](https://github.com/codingdash/prlens)
- [Changelog](https://github.com/codingdash/prlens/releases)
- [Issues](https://github.com/codingdash/prlens/issues)
