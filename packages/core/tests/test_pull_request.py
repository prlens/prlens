"""Tests for GitHub pull request helper functions."""

from unittest.mock import MagicMock

from prlens_core.gh.pull_request import get_incremental_files, get_last_reviewed_sha

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
