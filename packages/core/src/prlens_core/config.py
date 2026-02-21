import os
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_CONFIG: dict = {
    "model": "anthropic",
    "max_chars_per_file": 20000,
    "batch_limit": 60,
    "guidelines": None,  # None = use built-in default; set to a path string to override
    "exclude": [],  # fnmatch patterns or directory names to skip (e.g. "migrations/", "*.min.js")
    "review_draft_prs": False,
}

BUILTIN_GUIDELINES_DIR = Path(__file__).parent / "guidelines"
_BUILTIN_DEFAULT = BUILTIN_GUIDELINES_DIR / "backend.md"


def load_config(config_path: str = ".prlens.yml", cli_overrides: Optional[dict] = None) -> dict:
    """
    Load configuration by merging (in order of precedence):
      1. Built-in defaults
      2. .prlens.yml in the current directory
      3. CLI argument overrides
    """
    config = {**DEFAULT_CONFIG, "exclude": list(DEFAULT_CONFIG["exclude"])}

    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            file_config = yaml.safe_load(f) or {}
        config.update(file_config)

    if cli_overrides:
        for key, value in cli_overrides.items():
            if value is not None:
                config[key] = value

    # Resolve credentials from environment variables
    config["github_token"] = os.environ.get("GITHUB_TOKEN")
    config["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY")
    config["openai_api_key"] = os.environ.get("OPENAI_API_KEY")

    return config


def load_guidelines(config: dict) -> str:
    """
    Load review guidelines.

    If ``guidelines`` is set in config, loads from that path (relative to cwd).
    Otherwise falls back to the built-in default.
    """
    custom_path = config.get("guidelines")
    if custom_path:
        p = Path(custom_path)
        if not p.exists():
            raise FileNotFoundError(f"Guidelines file not found: {custom_path}")
        return p.read_text()

    if _BUILTIN_DEFAULT.exists():
        return _BUILTIN_DEFAULT.read_text()

    raise FileNotFoundError("No guidelines configured and built-in default is missing.")
