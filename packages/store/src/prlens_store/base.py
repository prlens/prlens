"""Abstract store interface.

Any team-specific storage backend (Gist, SQLite, Postgres, S3) implements
this interface. The CLI depends on BaseStore — not on a concrete backend —
so backends are swappable without touching CLI code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prlens_store.models import ReviewRecord


class BaseStore(ABC):
    """Pluggable persistence layer for review history.

    Implementations must be safe to call from CI environments where no
    interactive credentials are available — all auth must happen via
    constructor arguments or environment variables resolved at init time.
    """

    @abstractmethod
    def save(self, record: ReviewRecord) -> None:
        """Persist a completed review record."""

    @abstractmethod
    def list_reviews(self, repo: str, pr_number: int | None = None) -> list[ReviewRecord]:
        """Return reviews for a repo, optionally filtered by PR number.

        Returns an empty list if no reviews exist — never raises.
        """

    def close(self) -> None:
        """Release any resources held by the store (connections, file handles).

        Optional — subclasses that need cleanup should override this.
        Default is a no-op so callers can always call close() safely.
        """
