# Codebase-Aware Reviews

prlens injects three types of codebase context into every file review. This allows the AI to reason beyond the diff — catching architectural coupling, missing test coverage, and convention violations that are only visible when the file is seen in the context of the whole repo.

All context is fetched from the GitHub API pinned to the PR's head SHA. The AI never sees stale data.

---

## Context Signals

### 1. Repository File Tree (Repo Map)

**What it is:** A flat list of all file paths tracked in the repository at the PR's head SHA.

**How it helps:**
- The AI can reason about layer boundaries (`services/`, `handlers/`, `models/`)
- Spots naming convention violations relative to similar files
- Identifies whether a paired test file is expected to exist
- Detects when a new file belongs in a different directory

**Limit:** Capped at 300 paths in very large repositories.

**Example prompt injection:**
```
## Repository File Tree
src/auth/service.py
src/auth/handler.py
src/auth/models.py
tests/auth/test_service.py
tests/auth/test_handler.py
```

---

### 2. Co-Changed Files

**What it is:** Files that have been committed alongside the file being reviewed in recent git history.

**How it helps:**
- Detects architectural coupling that isn't expressed via imports
  (e.g. a route handler always changes with a middleware file)
- Prompts the AI to check that related files have been updated consistently
- Flags when only one side of a frequently co-changed pair was modified in this PR

**How it's computed:**
- Looks back at the last 10 commits that touched the file
- Selects the top 5 files by co-change frequency
- Truncates each file's content to 3,000 characters

**Example prompt injection:**
```
## Frequently Changed Together
### src/auth/middleware.py
[file content truncated to 3000 chars]
```

---

### 3. Sibling Files (Same Directory)

**What it is:** Up to 3 other files from the same directory as the file being reviewed.

**How it helps:**
- Establishes the local conventions and patterns for that module
- Helps the AI flag when the changed file deviates from how similar files in the same directory are structured

**Limit:** Up to 3 siblings, content truncated to 2,000 characters each.

---

### 4. Paired Test File

**What it is:** The test file that corresponds to the file being reviewed, located by naming convention.

**How it helps:**
- Avoids flagging behaviour that is already covered by tests
- Spots when new code in the diff has no corresponding test case
- Provides the AI with the expected contract for the module

**Naming patterns checked (in order):**

| Pattern | Example |
|---|---|
| `test_{stem}{suffix}` | `test_auth.py` for `auth.py` |
| `{stem}_test{suffix}` | `auth_test.go` for `auth.go` |
| `{stem}.test{suffix}` | `auth.test.ts` for `auth.ts` |
| `{stem}.spec{suffix}` | `auth.spec.js` for `auth.js` |
| `{stem}_spec{suffix}` | `auth_spec.rb` for `auth.rb` |

The test file is searched across the entire repository tree, not just the same directory.

**Limit:** Content truncated to 3,000 characters.

---

## Context Budget

Total context across all signals is capped at **20,000 characters** to keep prompts within model limits. When the budget is exceeded, signals are dropped in this priority order (lowest to highest value):

1. **Drop sibling files** — weakest signal, most commonly redundant
2. **Drop co-changed files** — valuable but large; dropped next
3. **Keep repo map + test file** — highest value per token
4. **Final fallback** — test file only

---

## When Context Is Unavailable

Context gathering is non-fatal. If the GitHub API returns an error (e.g. repository is too large, rate limit, permission issue), the review continues without context. The AI still reviews the diff and file content — it just won't have the codebase signals.

---

## Language Agnostic

Context signals are derived entirely from **git history** and **file path patterns** — no import parsing, no AST analysis, no language-specific tooling. prlens works identically for Python, Go, TypeScript, Ruby, Rust, Java, and any other language.
