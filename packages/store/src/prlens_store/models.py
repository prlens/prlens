"""Review history data models.

Decoupled from prlens_core so the store layer can be used independently
and prlens_core has no knowledge of persistence concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommentRecord:
    """A single inline review comment persisted to the store."""

    file: str
    line: int
    severity: str
    comment: str


@dataclass
class ReviewRecord:
    """A completed PR review persisted to the store.

    Created by the CLI layer after run_review() returns a ReviewSummary.
    The CLI maps ReviewSummary → ReviewRecord before calling store.save().
    """

    repo: str
    pr_number: int
    pr_title: str
    reviewer_model: str
    head_sha: str
    reviewed_at: str  # ISO-8601 UTC timestamp
    event: str  # "APPROVE" | "COMMENT" | "REQUEST_CHANGES"
    total_comments: int
    files_reviewed: int
    comments: list[CommentRecord] = field(default_factory=list)
