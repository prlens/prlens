"""CLI entry point for prlens.

Commands:
  review   — run AI review on a pull request (the original prlens command)
  init     — interactive setup wizard for new teams
  history  — display past review records from the configured store
  stats    — aggregate comment patterns across review history
"""

from __future__ import annotations

import importlib.metadata

import click
from rich.console import Console

from prlens_cli.commands.history import history_cmd
from prlens_cli.commands.init import init_cmd
from prlens_cli.commands.review import review_cmd
from prlens_cli.commands.stats import stats_cmd

console = Console()


def _build_store(config: dict):
    """Instantiate the configured store from .prlens.yml settings.

    Store selection hierarchy:
      store: gist   → GistStore  (requires gist_id and github_token)
      store: sqlite → SQLiteStore (requires store_path or uses .prlens.db)
      (default)     → NoOpStore  (no persistence — existing behaviour)

    This factory lives in cli.py so neither prlens_core nor prlens_store
    know about the CLI config format.
    """
    from prlens_store.noop import NoOpStore

    store_type = config.get("store", "noop")

    if store_type == "gist":
        from prlens_store.gist import GistStore

        gist_id = config.get("gist_id")
        token = config.get("github_token")
        if not gist_id or not token:
            console.print("[yellow]GistStore requires gist_id and a GitHub token. Falling back to no store.[/yellow]")
            return NoOpStore()
        return GistStore(gist_id=gist_id, token=token)

    if store_type == "sqlite":
        from prlens_store.sqlite import SQLiteStore

        db_path = config.get("store_path", ".prlens.db")
        return SQLiteStore(db_path=db_path)

    return NoOpStore()


@click.group()
@click.version_option(
    version=importlib.metadata.version("prlens"),
    prog_name="prlens",
)
@click.option(
    "--config",
    "config_path",
    default=".prlens.yml",
    show_default=True,
    help="Path to the configuration file.",
    envvar="PRLENS_CONFIG",
)
@click.pass_context
def main(ctx: click.Context, config_path: str):
    """AI-powered GitHub PR code reviewer for teams."""
    from prlens_core.config import load_config
    from prlens_cli.auth import resolve_github_token

    ctx.ensure_object(dict)

    config = load_config(config_path)

    # Resolve token early so all subcommands share the same resolution.
    token = resolve_github_token()
    if token:
        config["github_token"] = token

    store = _build_store(config)
    ctx.obj["store"] = store
    ctx.obj["config"] = config
    ctx.call_on_close(store.close)


main.add_command(review_cmd)
main.add_command(init_cmd)
main.add_command(history_cmd)
main.add_command(stats_cmd)
