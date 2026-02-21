# Guidelines

Guidelines are Markdown files that tell the AI reviewer what to look for. prlens ships with built-in defaults; teams can override them with their own file.

---

## Built-in Defaults

prlens ships two default guideline files:

| File | Content |
|---|---|
| `backend.md` | Python, REST APIs, Django, database queries, error handling, testing |
| `frontend.md` | React/JS state management, component architecture, API handling, constants |

When no `guidelines` key is set in `.prlens.yml`, the backend guidelines are used.

---

## Using Custom Guidelines

Point `guidelines` in `.prlens.yml` to any Markdown file:

```yaml
guidelines: docs/review-guidelines.md
```

The path is relative to the directory where you run `prlens` (typically your repository root).

Override for a single run without changing `.prlens.yml`:

```bash
prlens review --repo owner/repo --pr 42 --guidelines ./strict-guidelines.md
```

---

## Writing Effective Guidelines

Guidelines are injected verbatim into the AI system prompt. The AI reads them before reviewing any file, so structure them like a checklist a senior reviewer would follow.

### Recommended Structure

```markdown
## Security
- Never log sensitive data (passwords, tokens, PII).
- Validate all user input at the boundary.
- Use parameterised queries — no string interpolation in SQL.

## Error Handling
- All external calls must have explicit error handling.
- Use typed exceptions, not bare `except Exception`.
- Never swallow errors silently.

## Code Style
- Functions should do one thing.
- Max 50 lines per function.
- Use `snake_case` for variables and functions, `PascalCase` for classes.

## Testing
- New business logic must have a unit test.
- Test file mirrors the source path: `src/auth.py` → `tests/test_auth.py`.
```

### Tips

- **Be specific and actionable.** Vague rules like "write clean code" produce vague comments.
- **Use examples where possible.** The AI responds well to concrete right/wrong patterns.
- **Keep it focused.** A guideline file that tries to cover everything produces noisy reviews. Focus on the things that actually cause bugs or incidents on your team.
- **Language-specific sections.** If your repo mixes languages, add a `## Python` and a `## TypeScript` section.
- **Avoid tool-specific rules.** Guidelines work best when they describe what to do, not which linter to use.

---

## Using Guidelines from a Central Repository

For teams that maintain a single set of guidelines across multiple repos, check out the guidelines repo in your CI workflow before running prlens. See [GitHub Action — Central Guidelines](github-action.md#using-guidelines-from-a-central-repository) for a complete example.

---

## Viewing the Built-in Guidelines

The default guidelines are in the `prlens-core` package:

```
packages/core/src/prlens_core/guidelines/
├── backend.md
└── frontend.md
```

Copy and customise them as a starting point:

```bash
python -c "import prlens_core; import os; print(os.path.dirname(prlens_core.__file__))"
# → /path/to/site-packages/prlens_core
# Copy from prlens_core/guidelines/backend.md
```
