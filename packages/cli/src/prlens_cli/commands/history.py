"""history command — display past review records from the store."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("history")
@click.option("--repo", required=True, help="GitHub repository (owner/name).")
@click.option("--pr", "pr_number", type=int, default=None, help="Filter by PR number.")
@click.option("--limit", default=20, show_default=True, help="Maximum number of records to show.")
@click.pass_context
def history_cmd(ctx, repo: str, pr_number: int | None, limit: int):
    """Show past AI review records for a repository.

    Reads from the configured store (Gist or SQLite). Run `prlens init` to
    set up a store if you haven't already.
    """
    from prlens_store.noop import NoOpStore

    store = ctx.obj.get("store") if ctx.obj else None
    if store is None or isinstance(store, NoOpStore):
        raise click.UsageError(
            "No store configured. Add 'store: sqlite' or 'store: gist' to .prlens.yml, "
            "or run `prlens init` to set one up."
        )

    records = store.list_reviews(repo, pr_number=pr_number)
    if not records:
        console.print("[yellow]No review records found.[/yellow]")
        return

    # Show most recent first, capped at --limit.
    records = list(reversed(records))[:limit]

    table = Table(title=f"Review History — {repo}", show_header=True, header_style="bold cyan")
    table.add_column("PR", style="bold", width=6)
    table.add_column("Title", max_width=40)
    table.add_column("SHA", width=8)
    table.add_column("Event", width=16)
    table.add_column("Comments", justify="right", width=10)
    table.add_column("Reviewed At", width=20)

    _event_style = {
        "APPROVE": "green",
        "COMMENT": "yellow",
        "REQUEST_CHANGES": "red",
    }

    for r in records:
        event_style = _event_style.get(r.event, "white")
        table.add_row(
            f"#{r.pr_number}",
            r.pr_title[:40] if r.pr_title else "",
            r.head_sha[:7],
            f"[{event_style}]{r.event}[/{event_style}]",
            str(r.total_comments),
            r.reviewed_at[:19].replace("T", " "),
        )

    console.print(table)
