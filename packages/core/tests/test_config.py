"""Tests for configuration loading."""

import pytest

from prlens_core.config import load_config, load_guidelines


def test_defaults_applied_when_no_config_file(tmp_path):
    config = load_config(config_path=str(tmp_path / "nonexistent.yml"))
    assert config["model"] == "anthropic"
    assert config["batch_limit"] == 60
    assert config["guidelines"] is None
    assert config["exclude"] == []
    assert config["review_draft_prs"] is False


def test_config_file_overrides_defaults(tmp_path):
    cfg = tmp_path / ".lens.yml"
    cfg.write_text("model: openai\nbatch_limit: 30\n")
    config = load_config(config_path=str(cfg))
    assert config["model"] == "openai"
    assert config["batch_limit"] == 30


def test_exclude_patterns_loaded(tmp_path):
    cfg = tmp_path / ".lens.yml"
    cfg.write_text("exclude:\n  - migrations/\n  - '*.lock'\n")
    config = load_config(config_path=str(cfg))
    assert "migrations/" in config["exclude"]
    assert "*.lock" in config["exclude"]


def test_review_draft_prs_loaded(tmp_path):
    cfg = tmp_path / ".lens.yml"
    cfg.write_text("review_draft_prs: true\n")
    config = load_config(config_path=str(cfg))
    assert config["review_draft_prs"] is True


def test_cli_overrides_config_file(tmp_path):
    cfg = tmp_path / ".lens.yml"
    cfg.write_text("model: openai\n")
    config = load_config(config_path=str(cfg), cli_overrides={"model": "anthropic"})
    assert config["model"] == "anthropic"


def test_none_cli_overrides_ignored(tmp_path):
    cfg = tmp_path / ".lens.yml"
    cfg.write_text("model: openai\n")
    config = load_config(config_path=str(cfg), cli_overrides={"model": None})
    assert config["model"] == "openai"


def test_custom_guidelines_path(tmp_path):
    guidelines_file = tmp_path / "my-guidelines.md"
    guidelines_file.write_text("# Custom Guidelines\n- Rule 1")
    cfg = tmp_path / ".lens.yml"
    cfg.write_text(f"guidelines: {guidelines_file}\n")
    config = load_config(config_path=str(cfg))
    content = load_guidelines(config)
    assert "Custom Guidelines" in content


def test_builtin_guidelines_loaded_as_fallback():
    config = load_config(config_path="nonexistent.yml")
    content = load_guidelines(config)
    assert len(content) > 0


def test_missing_custom_guidelines_raises(tmp_path):
    config = {"guidelines": str(tmp_path / "does-not-exist.md")}
    with pytest.raises(FileNotFoundError):
        load_guidelines(config)


def test_env_vars_loaded(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
    config = load_config(config_path="nonexistent.yml")
    assert config["github_token"] == "gh-token"
    assert config["anthropic_api_key"] == "ant-key"
    assert config["openai_api_key"] == "oai-key"


def test_exclude_list_is_not_shared_reference(tmp_path):
    """Mutating one config's exclude list must not affect another."""
    config_a = load_config(config_path=str(tmp_path / "nonexistent.yml"))
    config_b = load_config(config_path=str(tmp_path / "nonexistent.yml"))
    config_a["exclude"].append("migrations/")
    assert config_b["exclude"] == []


def test_github_app_env_vars_loaded(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\n...")
    config = load_config(config_path="nonexistent.yml")
    assert config["github_app_id"] == "12345"
    assert config["github_app_private_key"] == "-----BEGIN RSA PRIVATE KEY-----\n..."


def test_github_app_private_key_loaded_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    key_file = tmp_path / "prlens-app.pem"
    key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nFAKEKEY\n-----END RSA PRIVATE KEY-----\n")
    cfg = tmp_path / ".prlens.yml"
    cfg.write_text(f"github_app_private_key_path: {key_file}\n")
    config = load_config(config_path=str(cfg))
    assert "FAKEKEY" in config["github_app_private_key"]


def test_env_var_takes_precedence_over_key_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "env-key-content")
    key_file = tmp_path / "prlens-app.pem"
    key_file.write_text("file-key-content")
    cfg = tmp_path / ".prlens.yml"
    cfg.write_text(f"github_app_private_key_path: {key_file}\n")
    config = load_config(config_path=str(cfg))
    assert config["github_app_private_key"] == "env-key-content"


def test_key_file_not_read_when_path_missing(tmp_path):
    cfg = tmp_path / ".prlens.yml"
    cfg.write_text(f"github_app_private_key_path: {tmp_path / 'nonexistent.pem'}\n")
    config = load_config(config_path=str(cfg))
    assert config["github_app_private_key"] is None
