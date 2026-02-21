from __future__ import annotations

from prlens_core.providers.base import BaseReviewer


class AnthropicReviewer(BaseReviewer):
    MODEL = "claude-sonnet-4-20250514"
    # temperature=0.3 for Anthropic — slightly higher than OpenAI's 0.2 to
    # allow more natural phrasing in review comments while keeping the output
    # deterministic enough for consistent JSON structure.
    TEMPERATURE = 0.3

    def __init__(self, api_key: str):
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for this provider. "
                "Install it with: pip install 'prlens[anthropic]'"
            )
        self.client = Anthropic(api_key=api_key)

    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        # Imported inside the method because the anthropic package is optional;
        # __init__ already validated it is installed before we reach here.
        from anthropic.types import TextBlock

        response = self.client.messages.create(
            model=self.MODEL,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=self.TEMPERATURE,
            max_tokens=self.MAX_TOKENS,
        )
        text_blocks = [block.text for block in response.content if isinstance(block, TextBlock)]
        return "".join(text_blocks).strip()
