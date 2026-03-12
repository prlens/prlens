"""Tests for prlens-store implementations."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from prlens_store.gist import GistStore
from prlens_store.models import CommentRecord, ReviewRecord
from prlens_store.noop import NoOpStore
from prlens_store.sqlite import SQLiteStore
from prlens_store.webhook import WebhookStore


def _make_record(repo="owner/repo", pr_number=1, total_comments=2, event="COMMENT"):
    return ReviewRecord(
        repo=repo,
        pr_number=pr_number,
        pr_title="Fix auth bug",
        reviewer_model="anthropic",
        head_sha="a" * 40,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        event=event,
        total_comments=total_comments,
        files_reviewed=1,
        comments=[
            CommentRecord(file="src/auth.py", line=42, severity="major", comment="Missing null check"),
        ],
    )


# ---------------------------------------------------------------------------
# NoOpStore
# ---------------------------------------------------------------------------


class TestNoOpStore:
    def test_save_does_not_raise(self):
        store = NoOpStore()
        store.save(_make_record())  # must not raise

    def test_list_reviews_returns_empty(self):
        store = NoOpStore()
        store.save(_make_record())
        assert store.list_reviews("owner/repo") == []

    def test_list_reviews_with_pr_number_returns_empty(self):
        store = NoOpStore()
        assert store.list_reviews("owner/repo", pr_number=1) == []


# ---------------------------------------------------------------------------
# SQLiteStore
# ---------------------------------------------------------------------------


class TestSQLiteStore:
    def test_save_and_list(self, tmp_path):
        store = SQLiteStore(db_path=str(tmp_path / "test.db"))
        record = _make_record()
        store.save(record)

        results = store.list_reviews("owner/repo")
        assert len(results) == 1
        assert results[0].repo == "owner/repo"
        assert results[0].pr_number == 1
        assert results[0].total_comments == 2
        store.close()

    def test_list_by_pr_number(self, tmp_path):
        store = SQLiteStore(db_path=str(tmp_path / "test.db"))
        store.save(_make_record(pr_number=1))
        store.save(_make_record(pr_number=2))

        results = store.list_reviews("owner/repo", pr_number=1)
        assert len(results) == 1
        assert results[0].pr_number == 1
        store.close()

    def test_list_different_repo_isolated(self, tmp_path):
        store = SQLiteStore(db_path=str(tmp_path / "test.db"))
        store.save(_make_record(repo="owner/repo-a"))
        store.save(_make_record(repo="owner/repo-b"))

        results = store.list_reviews("owner/repo-a")
        assert len(results) == 1
        assert results[0].repo == "owner/repo-a"
        store.close()

    def test_comments_roundtrip(self, tmp_path):
        store = SQLiteStore(db_path=str(tmp_path / "test.db"))
        record = _make_record()
        store.save(record)

        results = store.list_reviews("owner/repo")
        assert len(results[0].comments) == 1
        comment = results[0].comments[0]
        assert comment.file == "src/auth.py"
        assert comment.line == 42
        assert comment.severity == "major"
        assert comment.comment == "Missing null check"
        store.close()

    def test_empty_repo_returns_empty_list(self, tmp_path):
        store = SQLiteStore(db_path=str(tmp_path / "test.db"))
        assert store.list_reviews("owner/nonexistent") == []
        store.close()

    def test_multiple_saves_accumulate(self, tmp_path):
        store = SQLiteStore(db_path=str(tmp_path / "test.db"))
        store.save(_make_record(pr_number=1))
        store.save(_make_record(pr_number=2))
        store.save(_make_record(pr_number=3))

        results = store.list_reviews("owner/repo")
        assert len(results) == 3
        store.close()

    def test_persists_across_connections(self, tmp_path):
        """Data written by one SQLiteStore instance must be readable by another."""
        db_path = str(tmp_path / "test.db")
        store_a = SQLiteStore(db_path=db_path)
        store_a.save(_make_record())
        store_a.close()

        store_b = SQLiteStore(db_path=db_path)
        results = store_b.list_reviews("owner/repo")
        assert len(results) == 1
        store_b.close()


# ---------------------------------------------------------------------------
# GistStore
# ---------------------------------------------------------------------------


def _make_gist_mock(existing_records: list[dict] | None = None):
    """Return a mock Gist object with prlens_history.json pre-populated."""
    gist = MagicMock()
    if existing_records is None:
        gist.files = {}
    else:
        file_mock = MagicMock()
        file_mock.content = json.dumps(existing_records)
        gist.files = {"prlens_history.json": file_mock}
    return gist


def _make_gist_store():
    """Return a GistStore with a mocked Github client."""
    # Github is a local import inside __init__, so bypass it entirely
    # by constructing the object and injecting the mock client directly.
    store = object.__new__(GistStore)
    store._gist_id = "abc123"
    store._gh = MagicMock()
    return store


class TestGistStore:
    def test_save_appends_record(self):
        store = _make_gist_store()
        gist = _make_gist_mock(existing_records=[])
        store._gh.get_gist.return_value = gist

        store.save(_make_record())

        gist.edit.assert_called_once()
        content = json.loads(gist.edit.call_args[1]["files"]["prlens_history.json"]["content"])
        assert len(content) == 1
        assert content[0]["repo"] == "owner/repo"

    def test_save_appends_to_existing_records(self):
        existing = [GistStore._to_dict(_make_record(pr_number=1))]
        store = _make_gist_store()
        gist = _make_gist_mock(existing_records=existing)
        store._gh.get_gist.return_value = gist

        store.save(_make_record(pr_number=2))

        content = json.loads(gist.edit.call_args[1]["files"]["prlens_history.json"]["content"])
        assert len(content) == 2

    def test_save_does_not_raise_on_exception(self, capsys):
        store = _make_gist_store()
        store._gh.get_gist.side_effect = Exception("network error")

        store.save(_make_record())  # must not raise

        captured = capsys.readouterr()
        assert "Warning" in captured.out

    def test_list_reviews_returns_matching_repo(self):
        records = [
            GistStore._to_dict(_make_record(repo="owner/repo-a")),
            GistStore._to_dict(_make_record(repo="owner/repo-b")),
        ]
        store = _make_gist_store()
        store._gh.get_gist.return_value = _make_gist_mock(existing_records=records)

        results = store.list_reviews("owner/repo-a")
        assert len(results) == 1
        assert results[0].repo == "owner/repo-a"

    def test_list_reviews_filters_by_pr_number(self):
        records = [
            GistStore._to_dict(_make_record(pr_number=1)),
            GistStore._to_dict(_make_record(pr_number=2)),
        ]
        store = _make_gist_store()
        store._gh.get_gist.return_value = _make_gist_mock(existing_records=records)

        results = store.list_reviews("owner/repo", pr_number=1)
        assert len(results) == 1
        assert results[0].pr_number == 1

    def test_list_reviews_returns_empty_on_exception(self):
        store = _make_gist_store()
        store._gh.get_gist.side_effect = Exception("network error")

        results = store.list_reviews("owner/repo")
        assert results == []

    def test_list_reviews_handles_missing_file(self):
        store = _make_gist_store()
        store._gh.get_gist.return_value = _make_gist_mock(existing_records=None)

        results = store.list_reviews("owner/repo")
        assert results == []

    def test_to_dict_from_dict_roundtrip(self):
        record = _make_record()
        d = GistStore._to_dict(record)
        restored = GistStore._from_dict(d)

        assert restored.repo == record.repo
        assert restored.pr_number == record.pr_number
        assert restored.event == record.event
        assert len(restored.comments) == len(record.comments)
        assert restored.comments[0].file == record.comments[0].file
        assert restored.comments[0].severity == record.comments[0].severity

    def test_save_ci_warning_shown_in_github_actions(self, capsys, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        store = _make_gist_store()
        store._gh.get_gist.side_effect = Exception("401 Unauthorized")

        store.save(_make_record())

        captured = capsys.readouterr()
        assert "GITHUB_TOKEN" in captured.out or "PAT" in captured.out

    def test_save_no_ci_hint_outside_github_actions(self, capsys, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        store = _make_gist_store()
        store._gh.get_gist.side_effect = Exception("401 Unauthorized")

        store.save(_make_record())

        captured = capsys.readouterr()
        assert "GITHUB_TOKEN" not in captured.out


# ---------------------------------------------------------------------------
# WebhookStore
# ---------------------------------------------------------------------------


def _make_mock_response(status=200):
    """Return a mock HTTP response context manager."""
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestWebhookStore:
    def test_save_posts_json(self, capsys):
        store = WebhookStore(url="http://example.com/hook")
        with patch("urllib.request.urlopen", return_value=_make_mock_response()) as mock_open:
            store.save(_make_record())

        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert req.full_url == "http://example.com/hook"
        assert req.get_header("Content-type") == "application/json"

    def test_payload_contains_review_fields(self):
        store = WebhookStore(url="http://example.com/hook")
        captured_data = {}

        def fake_urlopen(req, timeout=None):
            captured_data["body"] = json.loads(req.data)
            return _make_mock_response()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            store.save(_make_record())

        body = captured_data["body"]
        assert body["repo"] == "owner/repo"
        assert body["pr_number"] == 1
        assert body["event"] == "COMMENT"
        assert body["total_comments"] == 2
        assert body["files_reviewed"] == 1
        assert len(body["comments"]) == 1
        assert body["comments"][0]["file"] == "src/auth.py"

    def test_hmac_signature_header_set_when_secret_provided(self):
        store = WebhookStore(url="http://example.com/hook", secret="mysecret")
        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers["sig"] = req.get_header("X-prlens-signature")
            return _make_mock_response()

        record = _make_record()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            store.save(record)

        assert captured_headers["sig"] is not None
        assert captured_headers["sig"].startswith("sha256=")

        # Verify the HMAC is correct
        payload = json.dumps(WebhookStore._to_dict(record)).encode()
        expected_sig = "sha256=" + hmac.new(b"mysecret", payload, hashlib.sha256).hexdigest()
        assert captured_headers["sig"] == expected_sig

    def test_no_signature_header_when_secret_absent(self):
        store = WebhookStore(url="http://example.com/hook")
        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers["sig"] = req.get_header("X-prlens-signature")
            return _make_mock_response()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            store.save(_make_record())

        assert captured_headers["sig"] is None

    def test_save_does_not_raise_on_network_error(self, capsys):
        from urllib.error import URLError

        store = WebhookStore(url="http://example.com/hook")
        with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            store.save(_make_record())  # must not raise

        captured = capsys.readouterr()
        assert "Warning" in captured.out

    def test_save_warns_on_http_error_status(self, capsys):
        store = WebhookStore(url="http://example.com/hook")
        with patch("urllib.request.urlopen", return_value=_make_mock_response(status=500)):
            store.save(_make_record())

        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "500" in captured.out

    def test_list_reviews_returns_empty(self):
        store = WebhookStore(url="http://example.com/hook")
        assert store.list_reviews("owner/repo") == []
        assert store.list_reviews("owner/repo", pr_number=1) == []

    def test_to_dict_roundtrip(self):
        record = _make_record()
        d = WebhookStore._to_dict(record)

        assert d["repo"] == record.repo
        assert d["pr_number"] == record.pr_number
        assert d["pr_title"] == record.pr_title
        assert d["reviewer_model"] == record.reviewer_model
        assert d["head_sha"] == record.head_sha
        assert d["reviewed_at"] == record.reviewed_at
        assert d["event"] == record.event
        assert d["total_comments"] == record.total_comments
        assert d["files_reviewed"] == record.files_reviewed
        assert len(d["comments"]) == 1
        assert d["comments"][0]["file"] == "src/auth.py"
        assert d["comments"][0]["line"] == 42
        assert d["comments"][0]["severity"] == "major"
