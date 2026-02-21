"""review command — run AI review on a pull request."""

from __future__ import annotations

import click
from rich.console import Console

from prlens_core.gh.pull_request import get_pull, get_pull_requests, get_repo
from prlens_core.reviewer import ReviewSummary, run_review
from prlens_store.models import CommentRecord, ReviewRecord

console = Console()


def _summary_to_record(summary: ReviewSummary, pr_title: str, model: str) -> ReviewRecord:
    """Map a ReviewSummary returned by run_review() to a ReviewRecord for the store.

    The CLI layer owns this mapping — prlens_core has no store knowledge and
    prlens_store has no core knowledge. The CLI bridges the two.
    """
    return ReviewRecord(
        repo=summary.repo,
        pr_number=summary.pr_number,
        pr_title=pr_title,
        reviewer_model=model,
        head_sha=summary.head_sha,
        reviewed_at=summary.reviewed_at,
        event=summary.event,
        total_comments=summary.total_comments,
        files_reviewed=len(summary.reviewed_files),
        comments=[
            CommentRecord(
                file=c.get("path", ""),
                line=c.get("line", 0),
                severity=c.get("severity", "minor"),
                comment=c.get("body", ""),
            )
            for c in summary.comments
        ],
    )


@click.command("review")
@click.option("--repo", required=True, help="GitHub repository in owner/name format.")
@click.option(
    "--pr",
    "pr_number",
    type=int,
    default=None,
    help="Pull request number. Omit to list open PRs interactively.",
)
@click.option(
    "--model",
    type=click.Choice(["anthropic", "openai"]),
    default=None,
    help="AI model provider. Overrides config file.",
)
@click.option(
    "--guidelines",
    "guidelines_path",
    default=None,
    help="Path to a Markdown guidelines file. Overrides config file.",
)
@click.option(
    "--config",
    "config_path",
    default=".prlens.yml",
    show_default=True,
    help="Path to the configuration file.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts.")
@click.option(
    "--shadow",
    "-s",
    is_flag=True,
    help="Dry-run mode: print review comments without posting to GitHub.",
)
@click.option(
    "--full-review",
    "full_review",
    is_flag=True,
    help="Review all changed files even if a previous review exists.",
)
@click.pass_context
def review_cmd(
    ctx,
    repo: str,
    pr_number: int | None,
    model: str | None,
    guidelines_path: str | None,
    config_path: str,
    yes: bool,
    shadow: bool,
    full_review: bool,
):
    """AI-powered GitHub PR code reviewer.

    Fetches a pull request, reviews each changed file against your coding
    guidelines using Claude or GPT-4o, and posts inline comments on GitHub.

    \b
    Required environment variables:
      GITHUB_TOKEN         GitHub personal access token (or use gh CLI)
      ANTHROPIC_API_KEY    Required when using --model anthropic
      OPENAI_API_KEY       Required when using --model openai
    """
    from prlens_core.config import load_config
    from prlens_cli.auth import resolve_github_token

    config = load_config(config_path, cli_overrides={"model": model, "guidelines": guidelines_path})

    # Resolve token: env var first, then gh CLI session.
    token = resolve_github_token()
    if not token:
        raise click.UsageError(
            "No GitHub token found. Set GITHUB_TOKEN or run `gh auth login` first.\n"
            "Create a token at https://github.com/settings/tokens"
        )
    config["github_token"] = token

    if config["model"] == "anthropic" and not config.get("anthropic_api_key"):
        raise click.UsageError("ANTHROPIC_API_KEY environment variable is not set.")
    if config["model"] == "openai" and not config.get("openai_api_key"):
        raise click.UsageError("OPENAI_API_KEY environment variable is not set.")

    this_repo = get_repo(repo, token=token)

    if pr_number is None:
        prs = list(get_pull_requests(this_repo))
        if not prs:
            console.print("[yellow]No open pull requests found.[/yellow]")
            return
        console.print("\nOpen pull requests:")
        for pr in prs:
            console.print(f"  [bold]#{pr.number}[/bold]  {pr.title}")
        pr_number = click.prompt("\nEnter the pull request number", type=int)

    # Fetch PR title for the store record before running the review.
    pr_obj = get_pull(this_repo, pr_number)
    pr_title = pr_obj.title or ""

    summary = run_review(
        repo=repo,
        pr_number=pr_number,
        config=config,
        auto_confirm=yes,
        shadow=shadow,
        force_full=full_review,
        repo_obj=this_repo,
    )

    # Persist to store — only if the review completed (not draft-skip / no-new-commits).
    if summary is not None:
        store = ctx.obj.get("store") if ctx.obj else None
        if store is not None:
            record = _summary_to_record(summary, pr_title, config["model"])
            store.save(record)
