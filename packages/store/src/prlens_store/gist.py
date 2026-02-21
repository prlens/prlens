"""GistStore — zero-infrastructure team review history via GitHub Gist.

Why Gist as the primary team store:
- Zero infra: no DB to provision, no server to maintain, no S3 bucket to manage.
- Built-in access control: Gist ACL == GitHub org membership — every dev with
  a GitHub account can read the team's review history without a separate login.
- Append-only JSON: each CI run appends a record; any team member can pull it
  with `prlens history --repo owner/repo`.
- Works in GitHub Actions: the GITHUB_TOKEN secret that Actions already injects
  has Gist read/write scope — no per-dev PAT needed.

Data format: a single JSON file named `prlens_history.json` inside the Gist.
The file contains a JSON array of ReviewRecord dicts, newest entries appended.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from prlens_store.base import BaseStore
from prlens_store.models import CommentRecord, ReviewRecord

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_GIST_FILENAME = "prlens_history.json"


class GistStore(BaseStore):
    """Stores review history in a GitHub Gist as an append-only JSON array.

    Each save() appends one ReviewRecord to the Gist file. list_reviews()
    reads the full array and filters in memory — suitable for teams with
    hundreds or low thousands of review records. For very high-volume teams
    (>10k records), switch to SQLiteStore.

    The Gist ID is stored in .prlens.yml under `gist_id`. Running
    `prlens init` creates the Gist and writes the ID to .prlens.yml
    automatically.
    """

    def __init__(self, gist_id: str, token: str):
        try:
            from github import Github
        except ImportError:
            raise ImportError("PyGithub is required for GistStore. Install prlens-store.")
        self._gist_id = gist_id
        self._gh = Github(token)

    def _get_gist(self):
        return self._gh.get_gist(self._gist_id)

    def save(self, record: ReviewRecord) -> None:
        """Append a review record to the Gist JSON file."""
        try:
            gist = self._get_gist()
            existing = self._read_records(gist)
            existing.append(self._to_dict(record))
            gist.edit(files={_GIST_FILENAME: {"content": json.dumps(existing, indent=2)}})
        except Exception as e:
            # Never abort the review because persistence failed.
            # The review was already posted to GitHub — that's the critical path.
            logger.warning("GistStore.save() failed (%s): %s", type(e).__name__, e)
            import os

            msg = f"Warning: could not persist review history to Gist ({type(e).__name__}: {e})"
            if os.environ.get("GITHUB_ACTIONS") == "true":
                msg += (
                    "\nThe built-in GITHUB_TOKEN does not have Gist permissions. "
                    "Use a PAT with 'gist' scope stored as a repository secret."
                )
            print(msg)

    def list_reviews(self, repo: str, pr_number: int | None = None) -> list[ReviewRecord]:
        """Return review records for a repo, optionally filtered by PR."""
        try:
            gist = self._get_gist()
            records = self._read_records(gist)
        except Exception as e:
            logger.warning("GistStore.list_reviews() failed: %s", e)
            return []

        results = [self._from_dict(r) for r in records if r.get("repo") == repo]
        if pr_number is not None:
            results = [r for r in results if r.pr_number == pr_number]
        return results

    def _read_records(self, gist) -> list[dict]:
        """Read the current JSON array from the Gist file, or return []."""
        file_obj = gist.files.get(_GIST_FILENAME)
        if file_obj is None:
            return []
        try:
            return json.loads(file_obj.content) or []
        except (json.JSONDecodeError, AttributeError):
            return []

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

    @staticmethod
    def _from_dict(d: dict) -> ReviewRecord:
        return ReviewRecord(
            repo=d.get("repo", ""),
            pr_number=d.get("pr_number", 0),
            pr_title=d.get("pr_title", ""),
            reviewer_model=d.get("reviewer_model", ""),
            head_sha=d.get("head_sha", ""),
            reviewed_at=d.get("reviewed_at", ""),
            event=d.get("event", ""),
            total_comments=d.get("total_comments", 0),
            files_reviewed=d.get("files_reviewed", 0),
            comments=[
                CommentRecord(
                    file=c.get("file", ""),
                    line=c.get("line", 0),
                    severity=c.get("severity", "minor"),
                    comment=c.get("comment", ""),
                )
                for c in d.get("comments", [])
            ],
        )
