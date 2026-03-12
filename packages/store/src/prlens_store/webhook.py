"""WebhookStore — push review events to any HTTP endpoint.

Each completed review POSTs a ReviewRecord as JSON. The receiving end
can be Datadog, Grafana, Slack, n8n, an internal dashboard, or any HTTP
service — prlens is agnostic to what happens downstream.

Optional HMAC-SHA256 request signing lets the receiver verify payloads
originate from prlens (same pattern used by GitHub, Stripe, etc.).

list_reviews() always returns [] — webhooks are push-only. The history
and stats commands work best with SQLiteStore or GistStore.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.request
from typing import TYPE_CHECKING

from prlens_store.base import BaseStore

if TYPE_CHECKING:
    from prlens_store.models import ReviewRecord

logger = logging.getLogger(__name__)


class WebhookStore(BaseStore):
    """Delivers each review as a JSON POST to a configured HTTP endpoint.

    Configure via .prlens.yml:
        store: webhook
        webhook_url: https://hooks.example.com/prlens
        webhook_secret: your-secret   # optional — enables HMAC-SHA256 signing
        webhook_timeout: 10           # optional — seconds, default 10
    """

    def __init__(self, url: str, secret: str | None = None, timeout: int = 10):
        self._url = url
        self._secret = secret
        self._timeout = timeout

    def save(self, record: ReviewRecord) -> None:
        payload = json.dumps(self._to_dict(record)).encode()
        headers = {"Content-Type": "application/json"}
        if self._secret:
            sig = hmac.new(self._secret.encode(), payload, hashlib.sha256).hexdigest()
            headers["X-Prlens-Signature"] = f"sha256={sig}"
        try:
            req = urllib.request.Request(self._url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status >= 400:
                    logger.warning("WebhookStore: HTTP %d from %s", resp.status, self._url)
                    print(f"Warning: webhook returned HTTP {resp.status}")
        except Exception as e:
            logger.warning("WebhookStore.save() failed: %s", e)
            print(f"Warning: could not deliver review event to webhook ({type(e).__name__}: {e})")

    def list_reviews(self, repo: str, pr_number: int | None = None) -> list[ReviewRecord]:
        return []  # push-only — query not supported

    @staticmethod
    def _to_dict(record: ReviewRecord) -> dict:
        return {
            "repo": record.repo,
            "pr_number": record.pr_number,
            "pr_title": record.pr_title,
            "reviewer_model": record.reviewer_model,
            "head_sha": record.head_sha,
            "reviewed_at": record.reviewed_at,
            "event": record.event,
            "total_comments": record.total_comments,
            "files_reviewed": record.files_reviewed,
            "comments": [
                {"file": c.file, "line": c.line, "severity": c.severity, "comment": c.comment} for c in record.comments
            ],
        }
