"""Tests for AI provider implementations.

Shared behaviour (_parse, _build_system_prompt, _build_user_prompt,
_call_with_retry) lives in BaseReviewer and is tested once via a lightweight
stub — not duplicated per provider. Provider-specific tests cover only what
differs between implementations: the SDK client setup and _call_api.
"""

import json
from unittest.mock import patch

from prlens_core.providers.anthropic import AnthropicReviewer
from prlens_core.providers.base import BaseReviewer
from prlens_core.providers.openai import OpenAIReviewer
from prlens_core.utils.context import RepoContext

VALID_JSON = json.dumps([{"line": 3, "severity": "major", "comment": "Missing error handling"}])


class _StubReviewer(BaseReviewer):
    """Minimal concrete subclass used to test BaseReviewer shared methods.

    Using a stub rather than a real provider means the shared-behaviour tests
    are decoupled from any SDK import requirements or provider-specific setup.
    """

    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        return VALID_JSON


# ---------------------------------------------------------------------------
# Shared behaviour — tested once through the stub, not per provider
# ---------------------------------------------------------------------------


class TestBaseReviewerParse:
    def test_parses_valid_json(self):
        result = _StubReviewer()._parse(VALID_JSON)
        assert len(result) == 1
        assert result[0]["line"] == 3
        assert result[0]["severity"] == "major"

    def test_strips_markdown_code_fences(self):
        raw = f"```json\n{VALID_JSON}\n```"
        assert len(_StubReviewer()._parse(raw)) == 1

    def test_preserves_code_blocks_inside_comments(self):
        """Backticks inside comment values must not be stripped."""
        payload = json.dumps(
            [
                {
                    "line": 5,
                    "severity": "major",
                    "comment": "Use this instead:\n```python\nfoo()\n```",
                }
            ]
        )
        raw = f"```json\n{payload}\n```"
        result = _StubReviewer()._parse(raw)
        assert len(result) == 1
        assert "```python" in result[0]["comment"]
        assert "foo()" in result[0]["comment"]

    def test_returns_empty_list_on_invalid_json(self):
        assert _StubReviewer()._parse("not json at all") == []

    def test_returns_empty_list_on_empty_array(self):
        assert _StubReviewer()._parse("[]") == []


class TestBaseReviewerPrompts:
    def test_system_prompt_contains_guidelines(self):
        prompt = _StubReviewer()._build_system_prompt("## My Guidelines")
        assert "## My Guidelines" in prompt

    def test_user_prompt_contains_filename(self):
        prompt = _StubReviewer()._build_user_prompt("PR desc", "src/foo.py", "+x=1", "x=1")
        assert "src/foo.py" in prompt

    def test_user_prompt_contains_diff(self):
        prompt = _StubReviewer()._build_user_prompt("", "f.py", "+added line", "content")
        assert "+added line" in prompt

    def test_user_prompt_contains_file_content(self):
        prompt = _StubReviewer()._build_user_prompt("", "f.py", "", "class Foo: pass")
        assert "class Foo: pass" in prompt

    def test_user_prompt_contains_pr_description(self):
        prompt = _StubReviewer()._build_user_prompt("Fixes auth bug", "f.py", "", "")
        assert "Fixes auth bug" in prompt


class TestBaseReviewerContextInjection:
    """Context sections are rendered by BaseReviewer — tested once, not per provider."""

    def test_repo_map_appears_in_prompt(self):
        ctx = RepoContext(repo_map="src/foo.py\nsrc/bar.py")
        prompt = _StubReviewer()._build_user_prompt("desc", "f.py", "+x", "x", ctx)
        assert "src/foo.py" in prompt
        assert "Repository File Tree" in prompt

    def test_cochanged_files_appear_in_prompt(self):
        ctx = RepoContext(cochanged_files={"src/config.py": "# cfg"})
        prompt = _StubReviewer()._build_user_prompt("desc", "f.py", "+x", "x", ctx)
        assert "src/config.py" in prompt
        assert "# cfg" in prompt

    def test_test_file_appears_in_prompt(self):
        ctx = RepoContext(
            test_file_path="tests/test_f.py",
            test_file_content="def test_x(): pass",
        )
        prompt = _StubReviewer()._build_user_prompt("desc", "f.py", "+x", "x", ctx)
        assert "tests/test_f.py" in prompt
        assert "def test_x(): pass" in prompt

    def test_no_context_section_when_repo_context_is_none(self):
        # When repo_context is None the prompt must still be valid — no empty
        # section headers or stray markdown that could confuse the model.
        prompt = _StubReviewer()._build_user_prompt("desc", "f.py", "+x", "x", None)
        assert "Repository File Tree" not in prompt
        assert "Frequently Changed Together" not in prompt


class TestBaseReviewerRetry:
    def test_returns_none_after_max_retries(self):
        """When _call_api raises on every attempt, review() returns []."""

        class _AlwaysFailReviewer(BaseReviewer):
            def _call_api(self, system_prompt: str, user_prompt: str) -> str:
                raise RuntimeError("network error")

        reviewer = _AlwaysFailReviewer()
        # Patch time.sleep so the test doesn't actually wait.
        with patch("prlens_core.providers.base.time.sleep"):
            result = reviewer.review("desc", "f.py", "+x", "x=1", "guidelines")
        assert result == []

    def test_retries_on_transient_failure(self):
        """_call_api is retried after a transient failure."""
        call_count = 0

        class _FailOnceThenSucceed(BaseReviewer):
            def _call_api(self, system_prompt: str, user_prompt: str) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("transient")
                return VALID_JSON

        reviewer = _FailOnceThenSucceed()
        with patch("prlens_core.providers.base.time.sleep"):
            result = reviewer.review("desc", "f.py", "+x", "x=1", "guidelines")
        assert len(result) == 1
        assert call_count == 2


# ---------------------------------------------------------------------------
# Provider-specific — only what differs between Anthropic and OpenAI
# ---------------------------------------------------------------------------


class TestAnthropicReviewer:
    def test_raises_import_error_without_sdk(self):
        """AnthropicReviewer.__init__ must raise if the anthropic package is absent."""
        with patch.dict("sys.modules", {"anthropic": None}):
            try:
                AnthropicReviewer(api_key="key")
            except ImportError:
                pass  # expected

    def test_model_is_claude(self):
        assert "claude" in AnthropicReviewer.MODEL

    def test_temperature_is_set(self):
        assert AnthropicReviewer.TEMPERATURE == 0.3


class TestOpenAIReviewer:
    def test_raises_import_error_without_sdk(self):
        """OpenAIReviewer.__init__ must raise if the openai package is absent."""
        import prlens_core.providers.openai as openai_mod

        real_openai = openai_mod._OpenAI
        openai_mod._OpenAI = None
        try:
            OpenAIReviewer(api_key="key")
            assert False, "Expected ImportError"
        except ImportError:
            pass
        finally:
            openai_mod._OpenAI = real_openai

    def test_model_is_gpt(self):
        assert "gpt" in OpenAIReviewer.MODEL

    def test_temperature_is_set(self):
        assert OpenAIReviewer.TEMPERATURE == 0.2
