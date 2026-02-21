"""stats command — aggregate patterns across review history."""

from __future__ import annotations

from collections import Counter

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("stats")
@click.option("--repo", required=True, help="GitHub repository (owner/name).")
@click.option("--top", default=10, show_default=True, help="Number of top entries to show per category.")
@click.pass_context
def stats_cmd(ctx, repo: str, top: int):
    """Show aggregated review statistics for a repository.

    Reports the most frequently flagged files, severity distribution, and
    which PR authors have the most review comments — useful for identifying
    systemic issues and prioritising guideline improvements.
    """
    from prlens_store.noop import NoOpStore

    store = ctx.obj.get("store") if ctx.obj else None
    if store is None or isinstance(store, NoOpStore):
        raise click.UsageError(
            "No store configured. Add 'store: sqlite' or 'store: gist' to .prlens.yml, "
            "or run `prlens init` to set one up."
        )

    records = store.list_reviews(repo)
    if not records:
        console.print("[yellow]No review records found for this repository.[/yellow]")
        return

    total_reviews = len(records)
    total_comments = sum(r.total_comments for r in records)
    severity_counter: Counter[str] = Counter()
    file_counter: Counter[str] = Counter()

    for record in records:
        for comment in record.comments:
            severity_counter[comment.severity] += 1
            file_counter[comment.file] += 1

    # --- Summary ---
    console.print(f"\n[bold]Review stats for [cyan]{repo}[/cyan][/bold]")
    console.print(f"  Total reviews:  {total_reviews}")
    console.print(f"  Total comments: {total_comments}")
    if total_reviews:
        console.print(f"  Avg per review: {total_comments / total_reviews:.1f}")

    # --- Severity breakdown ---
    if severity_counter:
        sev_table = Table(title="Severity Breakdown", show_header=True)
        sev_table.add_column("Severity", style="bold")
        sev_table.add_column("Count", justify="right")
        sev_table.add_column("% of total", justify="right")
        _sev_style = {"critical": "red", "major": "yellow", "minor": "blue", "nitpick": "dim"}
        for sev in ["critical", "major", "minor", "nitpick"]:
            count = severity_counter.get(sev, 0)
            pct = f"{count / total_comments * 100:.1f}%" if total_comments else "0%"
            style = _sev_style.get(sev, "white")
            sev_table.add_row(f"[{style}]{sev}[/{style}]", str(count), pct)
        console.print(sev_table)

    # --- Most flagged files ---
    if file_counter:
        file_table = Table(title=f"Top {top} Most Flagged Files", show_header=True)
        file_table.add_column("File")
        file_table.add_column("Comments", justify="right")
        for file_path, count in file_counter.most_common(top):
            file_table.add_row(file_path, str(count))
        console.print(file_table)
