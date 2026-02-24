"""Base reviewer implementing the Template Method pattern.

All providers share the same review algorithm:
    review() → _build_system_prompt() + _build_user_prompt()
             → _call_with_retry() → _call_api()   ← only this differs per provider
             → _parse()

Subclasses implement two things only:
  - __init__: validate and store the SDK client
  - _call_api: make one raw API call and return the text response

Everything else — prompt construction, JSON parsing, retry logic — lives here
so it is defined once and inherited consistently by every provider.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from prlens_core.utils.context import build_context_section

if TYPE_CHECKING:
    from prlens_core.utils.context import RepoContext

logger = logging.getLogger(__name__)

# Shared defaults — subclasses may override as class attributes if needed.
_MAX_RETRIES = 3
_MAX_TOKENS = 4096


class BaseReviewer(ABC):
    MAX_RETRIES: int = _MAX_RETRIES
    MAX_TOKENS: int = _MAX_TOKENS

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    def review(
        self,
        description: str,
        file_name: str,
        diff_patch: str,
        file_content: str,
        guidelines: str,
        repo_context: RepoContext | None = None,
    ) -> list[dict]:
        """Orchestrate a single-file review and return inline comments.

        Concrete here because the algorithm is identical for every provider:
        build prompts → call API with retry → parse JSON response.
        Only the raw API call (_call_api) is delegated to subclasses.
        """
        system = self._build_system_prompt(guidelines)
        user = self._build_user_prompt(description, file_name, diff_patch, file_content, repo_context)
        raw = self._call_with_retry(system, user)
        if raw is None:
            return []
        return self._parse(raw)

    # ------------------------------------------------------------------ #
    # Abstract — implement in each provider                               #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """Make a single API call and return the raw text response.

        This is the only method subclasses must implement. It should raise
        on failure — _call_with_retry handles retries and logging.
        """

    # ------------------------------------------------------------------ #
    # Shared implementations                                               #
    # ------------------------------------------------------------------ #

    def _call_with_retry(self, system_prompt: str, user_prompt: str) -> str | None:
        """Retry _call_api up to MAX_RETRIES times with exponential backoff.

        Separating retry logic from the raw API call means each provider's
        _call_api stays focused on a single attempt, and the backoff/logging
        behaviour is defined once rather than copied into every provider.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                return self._call_api(system_prompt, user_prompt)
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.error(
                        "%s API failed after %d attempts: %s",
                        self.__class__.__name__,
                        self.MAX_RETRIES,
                        e,
                    )
                    return None
                delay = 2**attempt
                logger.warning(
                    "%s API error (attempt %d/%d): %s. Retrying in %ds...",
                    self.__class__.__name__,
                    attempt + 1,
                    self.MAX_RETRIES,
                    e,
                    delay,
                )
                time.sleep(delay)

    def _build_system_prompt(self, guidelines: str) -> str:
        """Build the system prompt injected once per review call.

        Kept in base so all providers produce a consistent reviewer persona
        and rule set — the only variable is the guidelines content itself.
        """
        return f"""You are a strict and precise senior code reviewer.
Review the patch below and identify issues according to the guidelines.

{guidelines}

Rules:
- Focus on added lines (starting with '+') for direct violations.
- Also consider implications of removed lines (starting with '-') — e.g. deleted null checks,
  removed error handling, dropped permission guards.
- Do not comment on code that already follows best practices.
- Avoid assumptions when context is unclear. Be concise and actionable."""

    def _build_user_prompt(
        self,
        description: str,
        file_name: str,
        diff_patch: str,
        file_content: str,
        repo_context: RepoContext | None = None,
    ) -> str:
        """Build the per-file user prompt including any codebase context.

        Kept in base so both providers produce structurally identical prompts.
        The output format instructions are here rather than in the system
        prompt because they are specific to the file being reviewed, not to
        the reviewer's general behaviour.
        """
        context_section = build_context_section(repo_context)
        return f"""You are reviewing `{file_name}` in the context of the full repository.
{context_section}
## PR Description
{description}

## Diff
{diff_patch}

## Full File Content
{file_content}

### Output Format:
Respond with **only** a valid JSON list:

[
  {{
    "line": <line number in the new file (integer)>,
    "severity": "<critical|major|minor|nitpick>",
    "comment": "<concise, actionable comment — use GitHub-flavored markdown; wrap code in triple-backtick fences with a language tag>"  # noqa: E501
  }},
  ...
]

Severity guide:
- critical: security vulnerability, data loss risk, crash
- major: logic bug, missing error handling, significant performance issue
- minor: code smell, unclear naming, missing type hint
- nitpick: style preference, minor formatting

Markdown rules for the "comment" field:
- Use inline backticks for identifiers: `variable_name`, `function()`
- Use triple-backtick fences with a language tag for multi-line code suggestions:
  ```python\\ncode here\\n```
- Do not use HTML tags or any other formatting.

If there are no issues, return: []
Do not return any text outside the JSON block."""

    def _parse(self, raw: str) -> list[dict]:
        """Parse the model's raw text response into a list of comment dicts.

        Kept in base because the expected JSON schema is identical for every
        provider — stripping markdown fences and loading JSON is not
        provider-specific behaviour.
        """
        try:
            # Strip only the outer ```json ... ``` fence that the model wraps
            # the response in — NOT backticks inside comment string values.
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned.strip())
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(
                "%s: failed to parse response as JSON: %s",
                self.__class__.__name__,
                raw[:200],
            )
            return []
