"""No-op store — the default when no store is configured.

Preserves existing prlens behaviour: reviews are posted to GitHub but not
persisted anywhere. Using a NoOpStore rather than None lets the CLI always
call store.save() without conditional checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prlens_store.base import BaseStore

if TYPE_CHECKING:
    from prlens_store.models import ReviewRecord


class NoOpStore(BaseStore):
    """Silently discards all records — zero configuration required.

    This is the default store. Teams that want history and stats switch to
    GistStore (prlens init) or SQLiteStore (.prlens.yml: store: sqlite).
    """

    def save(self, record: ReviewRecord) -> None:
        pass  # intentional no-op

    def list_reviews(self, repo: str, pr_number: int | None = None) -> list[ReviewRecord]:
        return []
