"""GitHub token resolution with gh CLI fallback.

Why gh auth token fallback:
- In GitHub Actions, GITHUB_TOKEN is injected automatically — no per-dev config.
- For local runs, developers who already use the GitHub CLI (gh) are
  authenticated without needing to create or copy a PAT. This eliminates
  the single biggest friction point in prlens onboarding.

Resolution order (stops at first success):
  1. GITHUB_TOKEN environment variable (CI / explicit override)
  2. `gh auth token` (GitHub CLI session — works after `gh auth login`)
"""

from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def resolve_github_token() -> str | None:
    """Return a GitHub token or None if no valid source is available.

    Never raises — callers should check for None and emit a UsageError.
    """
    # 1. Explicit environment variable — highest precedence so CI can always
    #    override without touching shell profiles or the gh config store.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    # 2. GitHub CLI session — reuse the token that `gh auth login` stored.
    #    This is the zero-friction path for local developer use: if they
    #    can run `gh pr view`, they can run `prlens review` without extra setup.
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            gh_token = result.stdout.strip()
            if gh_token:
                logger.debug("Resolved GitHub token via gh CLI session.")
                return gh_token
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # gh is not installed or timed out — silently fall through.
        pass

    return None
