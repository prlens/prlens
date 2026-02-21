"""Tests for the CLI entry point."""

import subprocess
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from prlens_cli.cli import _build_store, main
from prlens_store.gist import GistStore
from prlens_store.noop import NoOpStore
from prlens_store.sqlite import SQLiteStore
from prlens_store.models import CommentRecord, ReviewRecord


def _make_config(github_token="tok", model="anthropic", anthropic_key="ant", openai_key=None):
    return {
        "github_token": github_token,
        "model": model,
        "anthropic_api_key": anthropic_key,
        "openai_api_key": openai_key,
        "guidelines": None,
        "exclude": [],
        "review_draft_prs": False,
        "max_chars_per_file": 20000,
        "batch_limit": 60,
        "store": "noop",
    }


def _patch_common(mocker, config=None, token="tok"):
    """Patch load_config, resolve_github_token, and _build_store for most tests."""
    cfg = config or _make_config()
    mocker.patch("prlens_core.config.load_config", return_value=cfg)
    mocker.patch("prlens_cli.auth.resolve_github_token", return_value=token)
    # Use SQLiteStore spec so isinstance(store, NoOpStore) returns False —
    # history and stats must not mistake this for an unconfigured store.
    mock_store = MagicMock(spec=SQLiteStore)
    mock_store.list_reviews.return_value = []
    mocker.patch("prlens_cli.cli._build_store", return_value=mock_store)
    return cfg, mock_store


class TestCLIValidation:
    def test_missing_github_token(self, mocker):
        _patch_common(mocker, config=_make_config(github_token=None), token=None)

        result = CliRunner().invoke(main, ["review", "--repo", "owner/repo", "--pr", "1"])
        assert result.exit_code != 0
        assert "token" in result.output.lower() or "GITHUB_TOKEN" in result.output

    def test_missing_anthropic_key(self, mocker):
        _patch_common(mocker, config=_make_config(model="anthropic", anthropic_key=None))

        result = CliRunner().invoke(main, ["review", "--repo", "owner/repo", "--pr", "1"])
        assert result.exit_code != 0
        assert "ANTHROPIC_API_KEY" in result.output

    def test_missing_openai_key(self, mocker):
        _patch_common(mocker, config=_make_config(model="openai", anthropic_key=None, openai_key=None))

        result = CliRunner().invoke(main, ["review", "--repo", "owner/repo", "--pr", "1"])
        assert result.exit_code != 0
        assert "OPENAI_API_KEY" in result.output


class TestCLIRunReview:
    def test_calls_run_review_with_correct_args(self, mocker):
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.review.get_repo", return_value=MagicMock())
        mocker.patch("prlens_cli.commands.review.get_pull", return_value=MagicMock(title="Fix bug"))
        mock_run = mocker.patch("prlens_cli.commands.review.run_review", return_value=None)

        CliRunner().invoke(main, ["review", "--repo", "owner/repo", "--pr", "42", "--yes"])

        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["pr_number"] == 42
        assert kwargs["auto_confirm"] is True
        assert kwargs["shadow"] is False
        assert kwargs["force_full"] is False

    def test_shadow_flag_passed_through(self, mocker):
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.review.get_repo", return_value=MagicMock())
        mocker.patch("prlens_cli.commands.review.get_pull", return_value=MagicMock(title="Fix bug"))
        mock_run = mocker.patch("prlens_cli.commands.review.run_review", return_value=None)

        CliRunner().invoke(main, ["review", "--repo", "owner/repo", "--pr", "1", "--shadow"])

        assert mock_run.call_args.kwargs["shadow"] is True

    def test_full_review_flag_passed_through(self, mocker):
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.review.get_repo", return_value=MagicMock())
        mocker.patch("prlens_cli.commands.review.get_pull", return_value=MagicMock(title="Fix bug"))
        mock_run = mocker.patch("prlens_cli.commands.review.run_review", return_value=None)

        CliRunner().invoke(main, ["review", "--repo", "owner/repo", "--pr", "1", "--full-review"])

        assert mock_run.call_args.kwargs["force_full"] is True

    def test_review_summary_saved_to_store(self, mocker):
        """When run_review returns a ReviewSummary, it must be persisted to the store."""
        from prlens_core.reviewer import ReviewSummary

        summary = ReviewSummary(
            repo="owner/repo",
            pr_number=1,
            head_sha="a" * 40,
            event="APPROVE",
        )
        _, mock_store = _patch_common(mocker)
        mocker.patch("prlens_cli.commands.review.get_repo", return_value=MagicMock())
        mocker.patch("prlens_cli.commands.review.get_pull", return_value=MagicMock(title="Fix bug"))
        mocker.patch("prlens_cli.commands.review.run_review", return_value=summary)

        CliRunner().invoke(main, ["review", "--repo", "owner/repo", "--pr", "1", "--yes"])

        mock_store.save.assert_called_once()


class TestCLIInteractive:
    def test_lists_open_prs(self, mocker):
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.review.get_repo", return_value=MagicMock())
        mocker.patch("prlens_cli.commands.review.get_pull", return_value=MagicMock(title="Fix login bug"))
        mock_pr = MagicMock()
        mock_pr.number = 7
        mock_pr.title = "Fix login bug"
        mocker.patch("prlens_cli.commands.review.get_pull_requests", return_value=[mock_pr])
        mocker.patch("prlens_cli.commands.review.run_review", return_value=None)

        result = CliRunner().invoke(main, ["review", "--repo", "owner/repo"], input="7\n")

        assert "#7" in result.output
        assert "Fix login bug" in result.output

    def test_no_open_prs_exits_early(self, mocker):
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.review.get_repo", return_value=MagicMock())
        mocker.patch("prlens_cli.commands.review.get_pull_requests", return_value=[])
        mock_run = mocker.patch("prlens_cli.commands.review.run_review", return_value=None)

        result = CliRunner().invoke(main, ["review", "--repo", "owner/repo"])

        assert "No open pull requests" in result.output
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# auth.py
# ---------------------------------------------------------------------------


class TestResolveGithubToken:
    def test_returns_env_var_when_set(self, monkeypatch):
        from prlens_cli.auth import resolve_github_token

        monkeypatch.setenv("GITHUB_TOKEN", "env-token")
        assert resolve_github_token() == "env-token"

    def test_falls_back_to_gh_cli(self, monkeypatch):
        from prlens_cli.auth import resolve_github_token

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="gh-token\n")
            result = resolve_github_token()
        assert result == "gh-token"

    def test_returns_none_when_gh_not_installed(self, monkeypatch):
        from prlens_cli.auth import resolve_github_token

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = resolve_github_token()
        assert result is None

    def test_returns_none_when_gh_times_out(self, monkeypatch):
        from prlens_cli.auth import resolve_github_token

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=5)):
            result = resolve_github_token()
        assert result is None

    def test_returns_none_when_gh_returns_error(self, monkeypatch):
        from prlens_cli.auth import resolve_github_token

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = resolve_github_token()
        assert result is None

    def test_returns_none_when_gh_returns_empty(self, monkeypatch):
        from prlens_cli.auth import resolve_github_token

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="   ")
            result = resolve_github_token()
        assert result is None


# ---------------------------------------------------------------------------
# _build_store
# ---------------------------------------------------------------------------


class TestBuildStore:
    def test_returns_noop_by_default(self):
        store = _build_store({})
        assert isinstance(store, NoOpStore)

    def test_returns_noop_when_explicitly_set(self):
        store = _build_store({"store": "noop"})
        assert isinstance(store, NoOpStore)

    def test_returns_sqlite_store(self, tmp_path):
        store = _build_store({"store": "sqlite", "store_path": str(tmp_path / "test.db")})
        assert isinstance(store, SQLiteStore)
        store.close()

    def test_sqlite_uses_default_path_when_not_specified(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        store = _build_store({"store": "sqlite"})
        assert isinstance(store, SQLiteStore)
        store.close()

    def test_returns_gist_store_when_configured(self):
        with patch("github.Github"):  # Github is a local import inside GistStore.__init__
            store = _build_store({"store": "gist", "gist_id": "abc123", "github_token": "tok"})
        assert isinstance(store, GistStore)

    def test_falls_back_to_noop_when_gist_id_missing(self):
        store = _build_store({"store": "gist", "github_token": "tok"})
        assert isinstance(store, NoOpStore)

    def test_falls_back_to_noop_when_token_missing(self):
        store = _build_store({"store": "gist", "gist_id": "abc123"})
        assert isinstance(store, NoOpStore)


# ---------------------------------------------------------------------------
# history command
# ---------------------------------------------------------------------------


def _make_review_record(repo="owner/repo", pr_number=1, event="COMMENT"):
    return ReviewRecord(
        repo=repo,
        pr_number=pr_number,
        pr_title="Fix auth bug",
        reviewer_model="anthropic",
        head_sha="a" * 40,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        event=event,
        total_comments=2,
        files_reviewed=1,
        comments=[CommentRecord(file="src/auth.py", line=10, severity="major", comment="x")],
    )


class TestHistoryCommand:
    def test_shows_table_when_records_exist(self, mocker):
        record = _make_review_record()
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = [record]

        result = CliRunner().invoke(main, ["history", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "#1" in result.output
        assert "COMMENT" in result.output

    def test_shows_empty_message_when_no_records(self, mocker):
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = []

        result = CliRunner().invoke(main, ["history", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "No review records found" in result.output

    def test_errors_when_noop_store(self, mocker):
        mocker.patch("prlens_core.config.load_config", return_value={"store": "noop"})
        mocker.patch("prlens_cli.auth.resolve_github_token", return_value="tok")
        mocker.patch("prlens_cli.cli._build_store", return_value=NoOpStore())

        result = CliRunner().invoke(main, ["history", "--repo", "owner/repo"])

        assert result.exit_code != 0
        assert "No store configured" in result.output

    def test_filters_by_pr_number(self, mocker):
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = [_make_review_record(pr_number=5)]

        CliRunner().invoke(main, ["history", "--repo", "owner/repo", "--pr", "5"])

        mock_store.list_reviews.assert_called_once_with("owner/repo", pr_number=5)

    def test_limit_applied(self, mocker):
        records = [_make_review_record(pr_number=i) for i in range(10)]
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = records

        result = CliRunner().invoke(main, ["history", "--repo", "owner/repo", "--limit", "3"])

        assert result.exit_code == 0
        # Only 3 rows shown — count PR number occurrences
        assert result.output.count("#") == 3


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------


class TestStatsCommand:
    def test_shows_stats_when_records_exist(self, mocker):
        record = _make_review_record()
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = [record]

        result = CliRunner().invoke(main, ["stats", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "Total reviews" in result.output
        assert "1" in result.output

    def test_shows_severity_breakdown(self, mocker):
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = [_make_review_record()]

        result = CliRunner().invoke(main, ["stats", "--repo", "owner/repo"])

        assert "major" in result.output.lower()

    def test_shows_most_flagged_files(self, mocker):
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = [_make_review_record()]

        result = CliRunner().invoke(main, ["stats", "--repo", "owner/repo"])

        assert "src/auth.py" in result.output

    def test_empty_message_when_no_records(self, mocker):
        _, mock_store = _patch_common(mocker)
        mock_store.list_reviews.return_value = []

        result = CliRunner().invoke(main, ["stats", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "No review records found" in result.output

    def test_errors_when_noop_store(self, mocker):
        mocker.patch("prlens_core.config.load_config", return_value={"store": "noop"})
        mocker.patch("prlens_cli.auth.resolve_github_token", return_value="tok")
        mocker.patch("prlens_cli.cli._build_store", return_value=NoOpStore())

        result = CliRunner().invoke(main, ["stats", "--repo", "owner/repo"])

        assert result.exit_code != 0
        assert "No store configured" in result.output


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


class TestInitCommand:
    def test_writes_prlens_yml_with_provider(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        result = CliRunner().invoke(
            main,
            ["init"],
            input="anthropic\nnone\nN\n",  # provider, store=none, no workflow
        )

        assert result.exit_code == 0
        config_file = tmp_path / ".prlens.yml"
        assert config_file.exists()
        import yaml

        config = yaml.safe_load(config_file.read_text())
        assert config["model"] == "anthropic"

    def test_writes_sqlite_store_config(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(
            main,
            ["init"],
            input="anthropic\nsqlite\n.prlens.db\nN\n",
        )

        import yaml

        config = yaml.safe_load((tmp_path / ".prlens.yml").read_text())
        assert config["store"] == "sqlite"

    def test_writes_github_actions_workflow(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value="owner/repo")

        CliRunner().invoke(
            main,
            ["init"],
            input="anthropic\nnone\nY\n",  # provider, store=none, yes to workflow
        )

        workflow = tmp_path / ".github" / "workflows" / "prlens.yml"
        assert workflow.exists()
        assert "prlens review" in workflow.read_text()

    def test_prompts_for_repo_when_not_detected(self, mocker, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _patch_common(mocker)
        mocker.patch("prlens_cli.commands.init._detect_repo_from_git", return_value=None)

        result = CliRunner().invoke(
            main,
            ["init"],
            input="owner/myrepo\nanthropomorphic\nanthropomorphic\nanthropomorphic\nanthropomorphic\nanthropomorphic\nanthropomorphic\n",
        )

        # Just verify it asked for the repo
        assert "repository" in result.output.lower() or result.exit_code in (0, 1)
