"""Tests for the core review pipeline: process_file and run_review."""

import types
from unittest.mock import MagicMock

import pytest

from prlens_core.reviewer import (
    ReviewSummary,
    _get_reviewer,
    flush_to_file,
    print_shadow_comments,
    process_file,
    run_review,
)

# A minimal patch with one added line at new-file line 2.
# get_diff_positions produces {2: 2} for this patch.
SIMPLE_PATCH = "@@ -1,2 +1,3 @@\n line1\n+new line\n line2\n"


def make_file(filename="src/foo.py", status="modified"):
    return types.SimpleNamespace(filename=filename, status=status)


class StubReviewer:
    def __init__(self, comments):
        self._comments = comments

    def review(self, **kwargs):
        return self._comments


# ---------------------------------------------------------------------------
# process_file
# ---------------------------------------------------------------------------


class TestProcessFile:
    def test_skips_deleted_file(self):
        result = process_file(StubReviewer([]), "", "", make_file(status="removed"), SIMPLE_PATCH, "", [])
        assert result == []

    def test_skips_empty_patch(self):
        result = process_file(StubReviewer([]), "", "", make_file(), "", "", [])
        assert result == []

    def test_valid_comment_included(self):
        reviewer = StubReviewer([{"line": 2, "severity": "minor", "comment": "bad name"}])
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [])
        assert len(result) == 1
        assert result[0]["path"] == "src/foo.py"
        assert result[0]["severity"] == "minor"
        assert "**[MINOR]**" in result[0]["body"]
        assert result[0]["line"] == 2

    def test_comment_for_line_not_in_diff_skipped(self):
        reviewer = StubReviewer([{"line": 99, "severity": "minor", "comment": "bad"}])
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [])
        assert result == []

    def test_comment_missing_line_skipped(self):
        reviewer = StubReviewer([{"severity": "minor", "comment": "bad"}])
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [])
        assert result == []

    def test_comment_missing_text_skipped(self):
        reviewer = StubReviewer([{"line": 2, "severity": "minor"}])
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [])
        assert result == []

    def test_invalid_severity_defaults_to_minor(self):
        reviewer = StubReviewer([{"line": 2, "severity": "blocker", "comment": "issue"}])
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [])
        assert result[0]["severity"] == "minor"
        assert "**[MINOR]**" in result[0]["body"]

    def test_duplicate_in_queued_skipped(self):
        reviewer = StubReviewer([{"line": 2, "severity": "minor", "comment": "bad name"}])
        queued = {("src/foo.py", 2, "bad name")}
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [], queued)
        assert result == []

    def test_comment_added_to_queued_set(self):
        reviewer = StubReviewer([{"line": 2, "severity": "minor", "comment": "bad name"}])
        queued = set()
        process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [], queued)
        assert ("src/foo.py", 2, "bad name") in queued

    def test_duplicate_existing_github_comment_skipped(self):
        reviewer = StubReviewer([{"line": 2, "severity": "minor", "comment": "bad name"}])
        existing = MagicMock()
        existing.path = "src/foo.py"
        existing.line = 2
        existing.body = "bad name"
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [existing])
        assert result == []

    def test_existing_comment_with_none_line_uses_original_line(self):
        """Comments whose line is None (after force-push) should still be detected via original_line."""
        reviewer = StubReviewer([{"line": 2, "severity": "minor", "comment": "bad name"}])
        existing = MagicMock()
        existing.path = "src/foo.py"
        existing.line = None
        existing.original_line = 2
        existing.body = "bad name"
        result = process_file(reviewer, "", "", make_file(), SIMPLE_PATCH, "", [existing])
        assert result == []


# ---------------------------------------------------------------------------
# run_review — early-exit paths
# ---------------------------------------------------------------------------


def _base_config():
    return {
        "github_token": "tok",
        "model": "anthropic",
        "anthropic_api_key": "key",
        "openai_api_key": None,
        "review_draft_prs": False,
        "exclude": [],
        "max_chars_per_file": 20000,
        "batch_limit": 60,
        "guidelines": None,
    }


class TestRunReviewEarlyExits:
    def test_skips_draft_pr(self, mocker):
        mock_pr = MagicMock()
        mock_pr.draft = True
        mock_repo = MagicMock()
        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=None)

        result = run_review("owner/repo", 1, _base_config(), repo_obj=mock_repo)

        assert result is None
        mock_pr.create_review.assert_not_called()

    def test_no_new_commits_returns_early(self, mocker):
        sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = sha
        mock_repo = MagicMock()
        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=sha)

        result = run_review("owner/repo", 1, _base_config(), repo_obj=mock_repo)

        assert result is None
        mock_pr.create_review.assert_not_called()

    def test_shadow_mode_does_not_post(self, mocker):
        sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        mock_file = MagicMock()
        mock_file.filename = "src/foo.py"
        mock_file.status = "modified"
        mock_file.patch = SIMPLE_PATCH

        content_mock = MagicMock()
        content_mock.decoded_content = b"file content"
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = content_mock

        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=None)
        mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="guidelines")
        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = []
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

        run_review("owner/repo", 1, _base_config(), shadow=True, repo_obj=mock_repo)

        mock_pr.create_review.assert_not_called()

    def test_full_review_bypasses_incremental(self, mocker):
        """--full-review should skip SHA lookup and review all files."""
        sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        mock_file = MagicMock()
        mock_file.filename = "src/foo.py"
        mock_file.status = "modified"
        mock_file.patch = SIMPLE_PATCH

        content_mock = MagicMock()
        content_mock.decoded_content = b"content"
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = content_mock

        get_last_sha = mocker.patch("prlens_core.reviewer.get_last_reviewed_sha")
        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="guidelines")
        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = []
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

        run_review("owner/repo", 1, _base_config(), shadow=True, force_full=True, repo_obj=mock_repo)

        get_last_sha.assert_not_called()


# ---------------------------------------------------------------------------
# _get_reviewer
# ---------------------------------------------------------------------------


class TestGetReviewer:
    def test_returns_anthropic_reviewer(self, mocker):
        mock_cls = mocker.patch("prlens_core.reviewer.AnthropicReviewer")
        _get_reviewer({"model": "anthropic", "anthropic_api_key": "ant-key"})
        mock_cls.assert_called_once_with(api_key="ant-key")

    def test_returns_openai_reviewer(self, mocker):
        mock_cls = mocker.patch("prlens_core.reviewer.OpenAIReviewer")
        _get_reviewer({"model": "openai", "openai_api_key": "oai-key"})
        mock_cls.assert_called_once_with(api_key="oai-key")

    def test_raises_for_unknown_model(self):
        with pytest.raises(ValueError, match="Unknown model provider"):
            _get_reviewer({"model": "gemini", "anthropic_api_key": None})


# ---------------------------------------------------------------------------
# flush_to_file
# ---------------------------------------------------------------------------


class TestFlushToFile:
    def test_writes_comment_to_log(self, tmp_path):
        log = tmp_path / "review.log"
        flush_to_file("owner/repo", 42, [{"path": "foo.py", "position": 3, "body": "bad code"}], str(log))
        content = log.read_text()
        assert "owner/repo#42" in content
        assert "foo.py" in content
        assert '"position": 3' in content

    def test_appends_multiple_comments(self, tmp_path):
        log = tmp_path / "review.log"
        comments = [
            {"path": "a.py", "position": 1, "body": "issue A"},
            {"path": "b.py", "position": 2, "body": "issue B"},
        ]
        flush_to_file("owner/repo", 1, comments, str(log))
        lines = log.read_text().splitlines()
        assert len(lines) == 2

    def test_appends_to_existing_file(self, tmp_path):
        log = tmp_path / "review.log"
        log.write_text("existing entry\n")
        flush_to_file("owner/repo", 1, [{"path": "x.py", "position": 1, "body": "note"}], str(log))
        lines = log.read_text().splitlines()
        assert lines[0] == "existing entry"
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# print_shadow_comments
# ---------------------------------------------------------------------------


class TestPrintShadowComments:
    def test_no_comments_prints_message(self, mocker):
        mock_print = mocker.patch("prlens_core.reviewer.console.print")
        print_shadow_comments([])
        printed = " ".join(str(a) for call in mock_print.call_args_list for a in call.args)
        assert "no comments" in printed.lower()

    def test_with_comments_prints_each_entry(self, mocker):
        mock_print = mocker.patch("prlens_core.reviewer.console.print")
        comments = [
            {"path": "foo.py", "line": 5, "severity": "critical", "body": "**[CRITICAL]** bad", "code": "x = 1"},
            {"path": "bar.py", "line": 10, "severity": "minor", "body": "**[MINOR]** style", "code": ""},
        ]
        print_shadow_comments(comments)
        all_output = " ".join(str(a) for call in mock_print.call_args_list for a in call.args)
        assert "foo.py" in all_output
        assert "bar.py" in all_output
        assert "2 comment" in all_output


# ---------------------------------------------------------------------------
# run_review — posting flow
# ---------------------------------------------------------------------------


def _setup_run_review(mocker, reviewer_comments=None, file_fetch_error=None, big_content=False):
    """Common setup for run_review posting-flow tests."""
    sha = "a" * 40
    mock_pr = MagicMock()
    mock_pr.draft = False
    mock_pr.head.sha = sha
    mock_pr.body = ""
    mock_pr.get_review_comments.return_value = []

    mock_file = MagicMock()
    mock_file.filename = "src/foo.py"
    mock_file.status = "modified"
    mock_file.patch = SIMPLE_PATCH

    mock_repo = MagicMock()
    if file_fetch_error:
        from github import GithubException

        mock_repo.get_contents.side_effect = GithubException(404, "Not Found")
    else:
        content_data = b"x" * 30000 if big_content else b"file content"
        content_mock = MagicMock()
        content_mock.decoded_content = content_data
        mock_repo.get_contents.return_value = content_mock

    # Explicitly mock get_git_tree so tests are not silently relying on
    # MagicMock auto-creating attributes. An empty tree means gather_context
    # produces an empty RepoContext — no context API calls, predictable output.
    mock_tree = MagicMock()
    mock_tree.tree = []
    mock_repo.get_git_tree.return_value = mock_tree

    mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
    mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=None)
    mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
    mocker.patch("prlens_core.reviewer.load_guidelines", return_value="guidelines")
    mocker.patch("prlens_core.reviewer.flush_to_file")

    mock_reviewer = MagicMock()
    mock_reviewer.review.return_value = reviewer_comments or []
    mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

    return mock_pr, mock_repo


class TestRunReviewPosting:
    def test_posts_approve_auto_confirm(self, mocker):
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=[])
        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)
        mock_pr.create_review.assert_called_once()
        assert mock_pr.create_review.call_args.kwargs["event"] == "APPROVE"

    def test_returns_review_summary(self, mocker):
        """run_review must return a ReviewSummary for the CLI to persist history."""
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=[])
        result = run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)
        assert isinstance(result, ReviewSummary)
        assert result.repo == "owner/repo"
        assert result.pr_number == 1

    def test_approve_declined_by_user_skips_post(self, mocker):
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=[])
        mocker.patch("builtins.input", return_value="n")
        run_review("owner/repo", 1, _base_config(), repo_obj=mock_repo)
        mock_pr.create_review.assert_not_called()

    def test_approve_confirmed_by_user_posts(self, mocker):
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=[])
        mocker.patch("builtins.input", return_value="y")
        run_review("owner/repo", 1, _base_config(), repo_obj=mock_repo)
        mock_pr.create_review.assert_called_once()
        assert mock_pr.create_review.call_args.kwargs["event"] == "APPROVE"

    def test_posts_request_changes_for_critical(self, mocker):
        comments = [{"line": 2, "severity": "critical", "comment": "critical issue"}]
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=comments)
        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)
        mock_pr.create_review.assert_called()
        assert mock_pr.create_review.call_args.kwargs["event"] == "REQUEST_CHANGES"

    def test_comments_declined_by_user_skips_post(self, mocker):
        comments = [{"line": 2, "severity": "minor", "comment": "style issue"}]
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=comments)
        mocker.patch("builtins.input", return_value="n")
        run_review("owner/repo", 1, _base_config(), repo_obj=mock_repo)
        mock_pr.create_review.assert_not_called()

    def test_file_fetch_error_recorded_in_summary(self, mocker):
        mock_pr, mock_repo = _setup_run_review(mocker, file_fetch_error=True)
        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)
        # Review is still posted (APPROVE since no line comments), body has error info
        body = mock_pr.create_review.call_args.kwargs["body"]
        assert "error" in body

    def test_large_patch_is_truncated(self, mocker):
        sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        mock_file = MagicMock()
        mock_file.filename = "src/big.py"
        mock_file.status = "modified"
        mock_file.patch = "@@ -1 +1 @@\n+" + "x" * 25000  # patch > 20000 chars

        content_mock = MagicMock()
        content_mock.decoded_content = b"short"
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = content_mock

        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=None)
        mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="")
        mocker.patch("prlens_core.reviewer.flush_to_file")

        captured_patch = {}

        def capture_review(**kwargs):
            captured_patch["diff_patch"] = kwargs.get("diff_patch", "")
            return []

        mock_reviewer = MagicMock()
        mock_reviewer.review.side_effect = capture_review
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)

        assert "truncated" in captured_patch["diff_patch"]

    def test_pr_not_found_raises_value_error(self, mocker):
        from github import GithubException

        mock_repo = MagicMock()
        mocker.patch("prlens_core.reviewer.get_pull", side_effect=GithubException(404, "Not Found"))

        with pytest.raises(ValueError, match="not found"):
            run_review("owner/repo", 999, _base_config(), repo_obj=mock_repo)

    def test_repo_tree_fetched_once_per_run(self, mocker):
        """get_git_tree must be called exactly once per PR run, not once per file.
        Fetching the tree per-file would multiply API calls with the number of
        changed files, which is unnecessary — the tree is constant for a given SHA.
        """
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=[])
        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)
        mock_repo.get_git_tree.assert_called_once()

    def test_review_proceeds_when_tree_fetch_fails(self, mocker):
        """A failed get_git_tree must not abort the review — context is optional."""
        sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        mock_file = MagicMock()
        mock_file.filename = "src/foo.py"
        mock_file.status = "modified"
        mock_file.patch = SIMPLE_PATCH

        content_mock = MagicMock()
        content_mock.decoded_content = b"content"
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = content_mock
        # Simulate a transient GitHub error on the tree fetch
        mock_repo.get_git_tree.side_effect = Exception("rate limited")

        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=None)
        mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="guidelines")
        mocker.patch("prlens_core.reviewer.flush_to_file")
        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = []
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

        # Must not raise — review continues with no codebase context
        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)
        mock_pr.create_review.assert_called_once()

    def test_batch_limit_splits_into_multiple_reviews(self, mocker):
        # Generate 3 comments with batch_limit=2 → 2 create_review calls
        reviewer_comments = [{"line": 2, "severity": "minor", "comment": f"issue {i}"} for i in range(3)]
        mock_pr, mock_repo = _setup_run_review(mocker, reviewer_comments=reviewer_comments)
        config = _base_config()
        config["batch_limit"] = 2
        run_review("owner/repo", 1, config, auto_confirm=True, repo_obj=mock_repo)
        assert mock_pr.create_review.call_count == 2

    def test_incremental_fallback_on_github_exception(self, mocker):
        """When incremental compare fails, run_review falls back to full diff."""
        from github import GithubException

        base_sha = "b" * 40
        head_sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = head_sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        content_mock = MagicMock()
        content_mock.decoded_content = b"content"
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = content_mock

        mock_file = MagicMock()
        mock_file.filename = "src/foo.py"
        mock_file.status = "modified"
        mock_file.patch = SIMPLE_PATCH

        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=base_sha)
        mocker.patch(
            "prlens_core.reviewer.get_incremental_files",
            side_effect=GithubException(422, "Unprocessable"),
        )
        mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="")
        mocker.patch("prlens_core.reviewer.flush_to_file")

        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = []
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)

        # get_diff was called as fallback
        mock_pr.create_review.assert_called_once()

    def test_incremental_success_uses_compare_files(self, mocker):
        """When incremental compare succeeds, diff files come from get_incremental_files."""
        base_sha = "b" * 40
        head_sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = head_sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        mock_file = MagicMock()
        mock_file.filename = "src/foo.py"
        mock_file.status = "modified"
        mock_file.patch = SIMPLE_PATCH

        content_mock = MagicMock()
        content_mock.decoded_content = b"content"
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = content_mock

        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=base_sha)
        mocker.patch("prlens_core.reviewer.get_incremental_files", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="")
        mocker.patch("prlens_core.reviewer.flush_to_file")

        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = []
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)

        mock_pr.create_review.assert_called_once()
        # Summary body should contain incremental SHA info
        body = mock_pr.create_review.call_args.kwargs["body"]
        assert base_sha[:7] in body

    def test_excluded_file_recorded_as_skipped(self, mocker):
        """Files matching exclude patterns are skipped and appear in the summary."""
        sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        mock_file = MagicMock()
        mock_file.filename = "yarn.lock"
        mock_file.status = "modified"
        mock_file.patch = SIMPLE_PATCH

        mock_repo = MagicMock()

        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=None)
        mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="")
        mocker.patch("prlens_core.reviewer.flush_to_file")
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=MagicMock())

        config = _base_config()
        config["exclude"] = ["*.lock"]
        run_review("owner/repo", 1, config, auto_confirm=True, repo_obj=mock_repo)

        body = mock_pr.create_review.call_args.kwargs["body"]
        assert "skipped" in body

    def test_large_file_content_is_truncated(self, mocker):
        """File content exceeding max_chars_per_file is truncated before review."""
        sha = "a" * 40
        mock_pr = MagicMock()
        mock_pr.draft = False
        mock_pr.head.sha = sha
        mock_pr.body = ""
        mock_pr.get_review_comments.return_value = []

        mock_file = MagicMock()
        mock_file.filename = "src/big.py"
        mock_file.status = "modified"
        mock_file.patch = SIMPLE_PATCH

        content_mock = MagicMock()
        content_mock.decoded_content = b"y" * 25000  # exceeds 20000 default
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = content_mock

        mocker.patch("prlens_core.reviewer.get_pull", return_value=mock_pr)
        mocker.patch("prlens_core.reviewer.get_last_reviewed_sha", return_value=None)
        mocker.patch("prlens_core.reviewer.get_diff", return_value=[mock_file])
        mocker.patch("prlens_core.reviewer.load_guidelines", return_value="")
        mocker.patch("prlens_core.reviewer.flush_to_file")

        captured = {}

        def capture_review(**kwargs):
            captured["file_content"] = kwargs.get("file_content", "")
            return []

        mock_reviewer = MagicMock()
        mock_reviewer.review.side_effect = capture_review
        mocker.patch("prlens_core.reviewer._get_reviewer", return_value=mock_reviewer)

        run_review("owner/repo", 1, _base_config(), auto_confirm=True, repo_obj=mock_repo)

        assert "truncated" in captured["file_content"]
