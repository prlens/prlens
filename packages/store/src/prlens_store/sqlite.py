"""SQLiteStore — local file-based store for power users and CI caching.

Why SQLite as the local store:
- Batteries included: ships with Python, no extra dependencies.
- Fast random access: indexed queries on repo/pr_number are microseconds,
  not a full JSON file parse like GistStore.
- Good for single-developer workflows where the Gist overhead isn't needed.
- Can also serve as a CI cache (write to a path shared between jobs).

Schema:
  reviews  — one row per completed PR review (no sub-table for comments to
             keep queries simple and avoid JOINs in read paths).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING

from prlens_store.base import BaseStore
from prlens_store.models import CommentRecord, ReviewRecord

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo            TEXT NOT NULL,
    pr_number       INTEGER NOT NULL,
    pr_title        TEXT,
    reviewer_model  TEXT,
    head_sha        TEXT,
    reviewed_at     TEXT,
    event           TEXT,
    total_comments  INTEGER DEFAULT 0,
    files_reviewed  INTEGER DEFAULT 0,
    comments_json   TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_reviews_repo ON reviews (repo);
CREATE INDEX IF NOT EXISTS idx_reviews_pr   ON reviews (repo, pr_number);
"""


class SQLiteStore(BaseStore):
    """Stores review history in a local SQLite database file.

    The database file path defaults to `.prlens.db` in the current working
    directory. Configure via .prlens.yml: `store_path: /path/to/prlens.db`.
    """

    def __init__(self, db_path: str = ".prlens.db"):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def save(self, record: ReviewRecord) -> None:
        comments_json = json.dumps(
            [{"file": c.file, "line": c.line, "severity": c.severity, "comment": c.comment} for c in record.comments]
        )
        self._conn.execute(
            """
            INSERT INTO reviews
              (repo, pr_number, pr_title, reviewer_model, head_sha,
               reviewed_at, event, total_comments, files_reviewed, comments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.repo,
                record.pr_number,
                record.pr_title,
                record.reviewer_model,
                record.head_sha,
                record.reviewed_at,
                record.event,
                record.total_comments,
                record.files_reviewed,
                comments_json,
            ),
        )
        self._conn.commit()

    def list_reviews(self, repo: str, pr_number: int | None = None) -> list[ReviewRecord]:
        if pr_number is not None:
            rows = self._conn.execute(
                "SELECT * FROM reviews WHERE repo=? AND pr_number=? ORDER BY reviewed_at",
                (repo, pr_number),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM reviews WHERE repo=? ORDER BY reviewed_at",
                (repo,),
            ).fetchall()

        return [self._row_to_record(r) for r in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ReviewRecord:
        comments_data = json.loads(row["comments_json"] or "[]")
        comments = [
            CommentRecord(
                file=c.get("file", ""),
                line=c.get("line", 0),
                severity=c.get("severity", "minor"),
                comment=c.get("comment", ""),
            )
            for c in comments_data
        ]
        return ReviewRecord(
            repo=row["repo"],
            pr_number=row["pr_number"],
            pr_title=row["pr_title"] or "",
            reviewer_model=row["reviewer_model"] or "",
            head_sha=row["head_sha"] or "",
            reviewed_at=row["reviewed_at"] or "",
            event=row["event"] or "",
            total_comments=row["total_comments"],
            files_reviewed=row["files_reviewed"],
            comments=comments,
        )
