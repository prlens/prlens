"""Tests for GitHub pull request helper functions."""

from unittest.mock import MagicMock, patch

from prlens_core.gh.pull_request import get_incremental_files, get_last_reviewed_sha, get_repo

SHA = "a" * 40
SHA2 = "b" * 40


def _review_with_body(body):
    r = MagicMock()
    r.body = body
    return r


class TestGetLastReviewedSha:
    def test_returns_none_when_no_reviews(self):
        pr = MagicMock()
        pr.get_reviews.return_value = []
        assert get_last_reviewed_sha(pr) is None

    def test_returns_none_when_no_marker_in_body(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [_review_with_body("LGTM!")]
        assert get_last_reviewed_sha(pr) is None

    def test_returns_sha_when_marker_present(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [_review_with_body(f"Good review\n<!-- prlens-sha: {SHA} -->")]
        assert get_last_reviewed_sha(pr) == SHA

    def test_returns_most_recent_sha_when_multiple_reviews(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [
            _review_with_body(f"<!-- prlens-sha: {SHA} -->"),
            _review_with_body(f"<!-- prlens-sha: {SHA2} -->"),
        ]
        assert get_last_reviewed_sha(pr) == SHA2

    def test_handles_none_body(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [_review_with_body(None)]
        assert get_last_reviewed_sha(pr) is None

    def test_ignores_reviews_without_marker(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [
            _review_with_body("No marker here"),
            _review_with_body(f"<!-- prlens-sha: {SHA} -->"),
        ]
        assert get_last_reviewed_sha(pr) == SHA


class TestGetIncrementalFiles:
    def test_calls_compare_and_returns_files(self):
        mock_files = [MagicMock(), MagicMock()]
        repo = MagicMock()
        repo.compare.return_value.files = mock_files

        result = get_incremental_files(repo, SHA, SHA2)

        repo.compare.assert_called_once_with(SHA, SHA2)
        assert result == mock_files


class TestGetRepo:
    def test_pat_path_when_only_token_provided(self):
        mock_repo = MagicMock()
        with patch("prlens_core.gh.pull_request.Github") as mock_github:
            mock_github.return_value.get_repo.return_value = mock_repo
            result = get_repo("owner/repo", token="ghp_xxx")
        mock_github.assert_called_once_with("ghp_xxx")
        mock_github.return_value.get_repo.assert_called_once_with("owner/repo")
        assert result is mock_repo

    def test_app_auth_path_when_app_id_and_private_key_provided(self):
        mock_repo = MagicMock()
        mock_installation = MagicMock()
        mock_installation.id = 999
        mock_gi = MagicMock()
        mock_gi.get_repo_installation.return_value = mock_installation
        mock_gi.get_github_for_installation.return_value.get_repo.return_value = mock_repo

        mock_app_auth = MagicMock()

        with patch("prlens_core.gh.pull_request.Github"):
            with patch("github.Auth.AppAuth", return_value=mock_app_auth) as mock_auth_cls:
                with patch("github.GithubIntegration", return_value=mock_gi) as mock_gi_cls:
                    result = get_repo("owner/repo", app_id="12345", private_key="-----BEGIN RSA PRIVATE KEY-----\n...")

        mock_auth_cls.assert_called_once_with(12345, "-----BEGIN RSA PRIVATE KEY-----\n...")
        mock_gi_cls.assert_called_once_with(auth=mock_app_auth)
        mock_gi.get_repo_installation.assert_called_once_with("owner", "repo")
        mock_gi.get_github_for_installation.assert_called_once_with(999)
        mock_gi.get_github_for_installation.return_value.get_repo.assert_called_once_with("owner/repo")
        assert result is mock_repo

    def test_falls_back_to_pat_when_app_id_missing(self):
        mock_repo = MagicMock()
        with patch("prlens_core.gh.pull_request.Github") as mock_github:
            mock_github.return_value.get_repo.return_value = mock_repo
            result = get_repo("owner/repo", token="tok", app_id=None, private_key="key")
        mock_github.assert_called_once_with("tok")
        assert result is mock_repo

    def test_falls_back_to_pat_when_private_key_missing(self):
        mock_repo = MagicMock()
        with patch("prlens_core.gh.pull_request.Github") as mock_github:
            mock_github.return_value.get_repo.return_value = mock_repo
            result = get_repo("owner/repo", token="tok", app_id="12345", private_key=None)
        mock_github.assert_called_once_with("tok")
        assert result is mock_repo
