from __future__ import annotations

try:
    from openai import OpenAI as _OpenAI
except ImportError:
    _OpenAI = None  # type: ignore[assignment,misc]

from prlens_core.providers.base import BaseReviewer


class OpenAIReviewer(BaseReviewer):
    MODEL = "gpt-4o"
    # temperature=0.2 for OpenAI — lower than Anthropic's 0.3 to lean toward
    # more deterministic, structured JSON output from GPT-4o.
    TEMPERATURE = 0.2

    def __init__(self, api_key: str):
        if _OpenAI is None:
            raise ImportError(
                "The 'openai' package is required for this provider. " "Install it with: pip install 'prlens[openai]'"
            )
        self.client = _OpenAI(api_key=api_key)

    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.TEMPERATURE,
            max_tokens=self.MAX_TOKENS,
        )
        return response.choices[0].message.content
