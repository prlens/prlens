"""Tests for reviewer helper functions."""

from prlens_core.reviewer import _build_summary, _determine_event, _is_excluded


class TestIsExcluded:
    def test_exact_filename_match(self):
        assert _is_excluded("yarn.lock", ["yarn.lock"]) is True

    def test_glob_basename_match(self):
        assert _is_excluded("path/to/yarn.lock", ["*.lock"]) is True

    def test_glob_full_path_match(self):
        assert _is_excluded("src/generated/schema.py", ["src/generated/*.py"]) is True

    def test_directory_prefix_at_root(self):
        assert _is_excluded("migrations/0001_initial.py", ["migrations/"]) is True

    def test_directory_prefix_nested(self):
        assert _is_excluded("app/migrations/0001_initial.py", ["migrations"]) is True

    def test_no_false_positive_on_similar_name(self):
        # "test" pattern should not match "test_helpers.py" at root
        assert _is_excluded("test_helpers.py", ["tests/"]) is False

    def test_not_excluded_when_no_patterns(self):
        assert _is_excluded("src/main.py", []) is False

    def test_not_excluded_when_no_match(self):
        assert _is_excluded("src/main.py", ["migrations/", "*.lock"]) is False

    def test_basename_only_match(self):
        # "yarn.lock" as an exact pattern should match "src/yarn.lock" via basename check
        assert _is_excluded("src/yarn.lock", ["yarn.lock"]) is True


class TestDetermineEvent:
    def test_approve_when_no_comments(self):
        assert _determine_event([]) == "APPROVE"

    def test_request_changes_on_critical(self):
        assert _determine_event([{"severity": "critical"}]) == "REQUEST_CHANGES"

    def test_request_changes_on_major(self):
        assert _determine_event([{"severity": "major"}]) == "REQUEST_CHANGES"

    def test_comment_on_minor_only(self):
        assert _determine_event([{"severity": "minor"}, {"severity": "nitpick"}]) == "COMMENT"

    def test_request_changes_when_mixed_with_critical(self):
        comments = [{"severity": "nitpick"}, {"severity": "critical"}, {"severity": "minor"}]
        assert _determine_event(comments) == "REQUEST_CHANGES"

    def test_defaults_missing_severity_to_minor(self):
        assert _determine_event([{}]) == "COMMENT"


def _make_comment(path: str, severity: str = "minor") -> dict:
    return {"path": path, "severity": severity, "line": 1, "body": "x", "position": 1}


class TestBuildSummary:
    def test_shows_reviewed_count(self):
        summary = [{"filename": "foo.py", "count": 1, "skipped": False, "error": None}]
        comments = [_make_comment("foo.py", "minor")]
        body = _build_summary(summary, comments, 30.0)
        assert "**1** file(s) reviewed" in body

    def test_shows_skipped_count(self):
        summary = [{"filename": "yarn.lock", "count": 0, "skipped": True, "error": None}]
        body = _build_summary(summary, [], 5.0)
        assert "skipped" in body

    def test_lists_files_with_comments(self):
        summary = [
            {"filename": "src/foo.py", "count": 2, "skipped": False, "error": None},
            {"filename": "src/bar.py", "count": 0, "skipped": False, "error": None},
        ]
        comments = [_make_comment("src/foo.py", "major"), _make_comment("src/foo.py", "minor")]
        body = _build_summary(summary, comments, 60.0)
        assert "src/foo.py" in body
        assert "2 |" in body  # total column

    def test_severity_columns_in_table(self):
        summary = [{"filename": "src/foo.py", "count": 2, "skipped": False, "error": None}]
        comments = [_make_comment("src/foo.py", "critical"), _make_comment("src/foo.py", "major")]
        body = _build_summary(summary, comments, 10.0)
        assert "Critical" in body
        assert "Major" in body

    def test_clean_files_noted(self):
        summary = [{"filename": "src/bar.py", "count": 0, "skipped": False, "error": None}]
        body = _build_summary(summary, [], 8.0)
        assert "Clean" in body

    def test_shows_errors_count_and_filenames(self):
        summary = [{"filename": "src/bad.py", "count": 0, "skipped": False, "error": "404 Not Found"}]
        body = _build_summary(summary, [], 3.0)
        assert "error" in body.lower()
        assert "src/bad.py" in body
        assert "404 Not Found" in body

    def test_incremental_info_shown_in_summary(self):
        summary = [{"filename": "src/foo.py", "count": 1, "skipped": False, "error": None}]
        comments = [_make_comment("src/foo.py", "minor")]
        info = {"base_sha": "abc1234567890", "head_sha": "def9876543210"}
        body = _build_summary(summary, comments, 45.0, incremental_info=info)
        assert "abc1234" in body
        assert "def9876" in body

    def test_no_incremental_info_when_not_provided(self):
        summary = [{"filename": "src/foo.py", "count": 1, "skipped": False, "error": None}]
        comments = [_make_comment("src/foo.py", "minor")]
        body = _build_summary(summary, comments, 20.0)
        assert "Incremental" not in body

    def test_elapsed_time_shown_in_seconds(self):
        summary = [{"filename": "f.py", "count": 0, "skipped": False, "error": None}]
        body = _build_summary(summary, [], 45.0)
        assert "45s" in body

    def test_elapsed_time_shown_in_minutes(self):
        summary = [{"filename": "f.py", "count": 0, "skipped": False, "error": None}]
        body = _build_summary(summary, [], 90.0)
        assert "1.5 min" in body

    def test_verdict_no_issues(self):
        summary = [{"filename": "f.py", "count": 0, "skipped": False, "error": None}]
        body = _build_summary(summary, [], 10.0)
        assert "No issues found" in body

    def test_verdict_critical_issues(self):
        summary = [{"filename": "f.py", "count": 1, "skipped": False, "error": None}]
        comments = [_make_comment("f.py", "critical")]
        body = _build_summary(summary, comments, 10.0)
        assert "critical" in body
        assert "changes required" in body
