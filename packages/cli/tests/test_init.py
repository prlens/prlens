"""Unit tests for the init command and its helper functions.

Helper functions (_detect_repo_from_git, _create_team_gist, _write_config,
_get_version, _write_workflow) are tested in isolation without going through
Click so failures point directly to the broken logic.

The TestInitCmd class tests the full Click command via CliRunner to verify that
prompts, branching, and side-effects (files written, messages printed) all
wire together correctly.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from prlens_cli.cli import main
from prlens_cli.commands.init import (
    _create_team_gist,
    _detect_repo_from_git,
    _get_version,
    _write_config,
    _write_workflow,
)

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _patch_cli(mocker):
    """Patch the Click group-level setup that runs before every subcommand.

    The main() group calls load_config, resolve_github_token, and _build_store
    before dispatching to any subcommand — including init_cmd which doesn't
    use these values itself. Patching them prevents filesystem/network I/O
    and keeps tests hermetic.
    """
    from prlens_store.noop import NoOpStore

    mocker.patch(
        "prlens_core.config.load_config",
        return_value={"model": "anthropic", "github_token": "tok", "store": "noop"},
    )
    mocker.patch("prlens_cli.auth.resolve_github_token", return_value="tok")
    mock_store = MagicMock(spec=NoOpStore)
    mocker.patch("prlens_cli.cli._build_store", return_value=mock_store)
    return mock_store


# ---------------------------------------------------------------------------
# _detect_repo_from_git
# ---------------------------------------------------------------------------


def _git_result(stdout: str, returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


class TestDetectRepoFromGit:
    def test_https_url_returns_slug(self):
        with patch("subprocess.run", return_value=_git_result("https://github.com/owner/repo.git\n")):
            assert _detect_repo_from_git() == "owner/repo"

    def test_ssh_url_returns_slug(self):
        with patch("subprocess.run", return_value=_git_result("git@github.com:owner/repo.git\n")):
            assert _detect_repo_from_git() == "owner/repo"

    def test_https_url_without_dot_git_suffix(self):
        with patch("subprocess.run", return_value=_git_result("https://github.com/owner/repo\n")):
            assert _detect_repo_from_git() == "owner/repo"

    def test_non_github_remote_returns_none(self):
        with patch("subprocess.run", return_value=_git_result("https://gitlab.com/owner/repo.git\n")):
            assert _detect_repo_from_git() is None

    def test_slug_without_slash_returns_none(self):
        # URL that resolves to a bare repo name with no owner — treated as invalid.
        with patch("subprocess.run", return_value=_git_result("https://github.com/repo\n")):
            assert _detect_repo_from_git() is None

    def test_git_nonzero_exit_returns_none(self):
        with patch("subprocess.run", return_value=_git_result("", returncode=1)):
            assert _detect_repo_from_git() is None

    def test_git_not_found_returns_none(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _detect_repo_from_git() is None

    def test_git_timeout_returns_none(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            assert _detect_repo_from_git() is None


# ---------------------------------------------------------------------------
# _create_team_gist
# ---------------------------------------------------------------------------


def _gh_result(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


class TestCreateTeamGist:
    def test_success_returns_gist_id(self):
        with patch("subprocess.run", return_value=_gh_result("https://gist.github.com/abc123def456\n")):
            assert _create_team_gist("owner/repo") == "abc123def456"

    def test_trailing_slash_in_url_stripped(self):
        with patch("subprocess.run", return_value=_gh_result("https://gist.github.com/abc123def456/\n")):
            assert _create_team_gist("owner/repo") == "abc123def456"

    def test_gh_not_found_returns_none(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _create_team_gist("owner/repo") is None

    def test_gh_timeout_returns_none(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 15)):
            assert _create_team_gist("owner/repo") is None

    def test_gh_nonzero_exit_returns_none(self):
        with patch("subprocess.run", return_value=_gh_result(returncode=1, stderr="auth error")):
            assert _create_team_gist("owner/repo") is None

    def test_creates_private_gist(self):
        """The --public=false flag must be present so the Gist is private."""
        with patch("subprocess.run", return_value=_gh_result("https://gist.github.com/gid\n")) as mock_run:
            _create_team_gist("owner/repo")
        cmd = " ".join(mock_run.call_args.args[0])
        assert "--public=false" in cmd

    def test_repo_name_in_gist_description(self):
        """The Gist description must include the repo slug for identification."""
        with patch("subprocess.run", return_value=_gh_result("https://gist.github.com/gid\n")) as mock_run:
            _create_team_gist("owner/repo")
        cmd = " ".join(mock_run.call_args.args[0])
        assert "owner/repo" in cmd


# ---------------------------------------------------------------------------
# _write_config
# ---------------------------------------------------------------------------


class TestWriteConfig:
    def test_creates_new_config_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_config({"model": "anthropic"})
        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["model"] == "anthropic"

    def test_merges_with_existing_config_preserves_other_keys(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".prlens.yml").write_text("model: openai\nbatch_limit: 30\n")
        _write_config({"model": "anthropic"})
        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["model"] == "anthropic"  # overridden
        assert config["batch_limit"] == 30  # preserved

    def test_overrides_matching_keys(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".prlens.yml").write_text("store: sqlite\n")
        _write_config({"store": "gist", "gist_id": "abc"})
        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["store"] == "gist"
        assert config["gist_id"] == "abc"

    def test_handles_empty_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".prlens.yml").write_text("")
        _write_config({"model": "anthropic"})
        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["model"] == "anthropic"

    def test_output_is_valid_yaml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_config({"model": "openai", "store": "sqlite", "store_path": "/tmp/r.db"})
        parsed = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert parsed["store_path"] == "/tmp/r.db"


# ---------------------------------------------------------------------------
# _get_version
# ---------------------------------------------------------------------------


class TestGetVersion:
    def test_returns_version_from_package_metadata(self):
        with patch("importlib.metadata.version", return_value="1.2.3"):
            assert _get_version() == "1.2.3"

    def test_returns_non_empty_fallback_on_error(self):
        with patch("importlib.metadata.version", side_effect=Exception("not installed")):
            result = _get_version()
        assert isinstance(result, str) and len(result) > 0


# ---------------------------------------------------------------------------
# _write_workflow
# ---------------------------------------------------------------------------


class TestWriteWorkflow:
    def test_creates_workflow_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_workflow("anthropic", "ANTHROPIC_API_KEY")
        assert (tmp_path / ".github" / "workflows" / "prlens.yml").exists()

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / ".github").exists()
        _write_workflow("anthropic", "ANTHROPIC_API_KEY")
        assert (tmp_path / ".github" / "workflows").is_dir()

    def test_anthropic_api_key_env_in_workflow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_workflow("anthropic", "ANTHROPIC_API_KEY")
        content = (tmp_path / ".github" / "workflows" / "prlens.yml").read_text()
        assert "ANTHROPIC_API_KEY" in content

    def test_openai_api_key_env_in_workflow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_workflow("openai", "OPENAI_API_KEY")
        content = (tmp_path / ".github" / "workflows" / "prlens.yml").read_text()
        assert "OPENAI_API_KEY" in content

    def test_provider_in_install_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_workflow("openai", "OPENAI_API_KEY")
        content = (tmp_path / ".github" / "workflows" / "prlens.yml").read_text()
        assert "openai" in content

    def test_version_substituted_in_install_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("prlens_cli.commands.init._get_version", return_value="9.9.9"):
            _write_workflow("anthropic", "ANTHROPIC_API_KEY")
        content = (tmp_path / ".github" / "workflows" / "prlens.yml").read_text()
        assert "9.9.9" in content

    def test_workflow_contains_prlens_review_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_workflow("anthropic", "ANTHROPIC_API_KEY")
        content = (tmp_path / ".github" / "workflows" / "prlens.yml").read_text()
        assert "prlens review" in content

    def test_workflow_triggers_on_pull_request(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_workflow("anthropic", "ANTHROPIC_API_KEY")
        content = (tmp_path / ".github" / "workflows" / "prlens.yml").read_text()
        assert "pull_request" in content


# ---------------------------------------------------------------------------
# init_cmd (full Click integration)
# ---------------------------------------------------------------------------


class TestInitCmd:
    def test_repo_flag_skips_git_detection(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        detect = mocker.patch("prlens_cli.commands.init._detect_repo_from_git")

        CliRunner().invoke(main, ["init", "--repo", "custom/repo"], input="anthropic\nnone\nN\n")

        detect.assert_not_called()

    def test_detected_repo_shown_in_output(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        result = CliRunner().invoke(main, ["init"], input="anthropic\nnone\nN\n")

        assert "owner/repo" in result.output

    def test_prompts_for_repo_when_not_detected(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value=None)

        result = CliRunner().invoke(
            main, ["init"], input="typed/repo\nanthropomorphic\nanthropomorphic\nanthropomorphic\nanthropomorphic\n"
        )

        assert "repository" in result.output.lower()

    def test_anthropic_provider_written_to_config(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(main, ["init"], input="anthropic\nnone\nN\n")

        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["model"] == "anthropic"

    def test_openai_provider_written_to_config(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(main, ["init"], input="openai\nnone\nN\n")

        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["model"] == "openai"

    def test_sqlite_store_written_to_config(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(main, ["init"], input="anthropic\nsqlite\n.prlens.db\nN\n")

        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["store"] == "sqlite"

    def test_sqlite_default_path_omits_store_path_key(self, mocker, tmp_path, monkeypatch):
        """Entering the default '.prlens.db' must NOT write a store_path key."""
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(main, ["init"], input="anthropic\nsqlite\n.prlens.db\nN\n")

        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert "store_path" not in config

    def test_sqlite_custom_path_written_to_config(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(main, ["init"], input="anthropic\nsqlite\n/data/reviews.db\nN\n")

        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config.get("store_path") == "/data/reviews.db"

    def test_gist_store_writes_gist_id_on_success(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")
        mocker.patch("prlens_cli.commands.init._create_team_gist", return_value="gist42")

        CliRunner().invoke(main, ["init"], input="anthropic\ngist\nN\n")

        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["store"] == "gist"
        assert config["gist_id"] == "gist42"

    def test_gist_store_shows_warning_on_failure(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")
        mocker.patch("prlens_cli.commands.init._create_team_gist", return_value=None)

        result = CliRunner().invoke(main, ["init"], input="anthropic\ngist\nN\n")

        assert "manually" in result.output.lower() or "failed" in result.output.lower()

    def test_workflow_file_created_when_confirmed(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(main, ["init"], input="anthropic\nnone\nY\n")

        assert (tmp_path / ".github" / "workflows" / "prlens.yml").exists()

    def test_workflow_file_not_created_when_declined(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(main, ["init"], input="anthropic\nnone\nN\n")

        assert not (tmp_path / ".github").exists()

    def test_api_key_reminder_shown_when_workflow_created(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        result = CliRunner().invoke(main, ["init"], input="anthropic\nnone\nY\n")

        assert "ANTHROPIC_API_KEY" in result.output

    def test_setup_complete_message_shown(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        result = CliRunner().invoke(main, ["init"], input="anthropic\nnone\nN\n")

        assert "Setup complete" in result.output

    def test_review_command_hint_shown_at_end(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_cli(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        result = CliRunner().invoke(main, ["init"], input="anthropic\nnone\nN\n")

        assert "prlens review" in result.output
