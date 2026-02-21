# AI Providers

prlens supports two AI providers. Both use the same prompt structure, retry logic, and JSON output format — the only difference is the underlying SDK and model.

---

## Anthropic Claude (default)

| Property | Value |
|---|---|
| Model | `claude-sonnet-4-20250514` |
| Temperature | `0.3` |
| Max output tokens | `4096` |
| Required env var | `ANTHROPIC_API_KEY` |
| Install extra | `pip install 'prlens[anthropic]'` |

### Setup

```bash
pip install 'prlens[anthropic]'
export ANTHROPIC_API_KEY=sk-ant-...
```

### Config

```yaml
model: anthropic
```

### Getting an API Key

Create a key at [console.anthropic.com/keys](https://console.anthropic.com/keys). The `claude-sonnet-4-20250514` model is available on all paid plans.

---

## OpenAI GPT-4o

| Property | Value |
|---|---|
| Model | `gpt-4o` |
| Temperature | `0.2` |
| Max output tokens | `4096` |
| Required env var | `OPENAI_API_KEY` |
| Install extra | `pip install 'prlens[openai]'` |

### Setup

```bash
pip install 'prlens[openai]'
export OPENAI_API_KEY=sk-...
```

### Config

```yaml
model: openai
```

### Getting an API Key

Create a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys). GPT-4o access requires a funded account.

---

## Switching Providers

Override the config file for a single run:

```bash
prlens review --repo owner/repo --pr 42 --model openai
```

Or change the default in `.prlens.yml`:

```yaml
model: openai
```

---

## How Both Providers Work

Both providers share identical behaviour via the `BaseReviewer` class:

1. **System prompt** — injects the guidelines, sets the reviewer persona, and defines severity levels.
2. **User prompt** — includes the PR description, diff, full file content, and codebase context signals.
3. **API call with retry** — up to 3 attempts with exponential backoff (2s, 4s) on transient errors.
4. **JSON parsing** — strips any outer markdown fence (` ```json ``` `) from the response, then parses the JSON array. Backticks inside comment strings are preserved.

### Output Format

Providers are instructed to return a JSON array:

```json
[
  {
    "line": 42,
    "severity": "major",
    "comment": "Missing null check before dereferencing `user`.\n\n```python\nif user is None:\n    raise ValueError('user required')\n```"
  }
]
```

Comments may contain GitHub-flavored markdown — inline backticks for identifiers and triple-backtick fences with a language tag for code suggestions.

### Severity Levels

| Level | When to Use | GitHub Review Event |
|---|---|---|
| `critical` | Security vulnerability, data loss risk, crash | `REQUEST_CHANGES` |
| `major` | Logic bug, missing error handling, significant perf issue | `REQUEST_CHANGES` |
| `minor` | Code smell, unclear naming, missing type hint | `COMMENT` |
| `nitpick` | Style preference, minor formatting | `COMMENT` |

---

## Installing Both Providers

```bash
pip install 'prlens[all]'
```

You can then switch between providers via `--model` or by changing `model:` in `.prlens.yml` without reinstalling.
