"""init command — interactive setup wizard for new teams.

Why an init wizard:
- Eliminates per-dev friction: runs once, writes .prlens.yml and optionally
  creates a GitHub Actions workflow so every subsequent dev just clones and runs.
- Creates the team Gist automatically so the reviewer doesn't need to know
  the GitHub API to set up shared history.
- Generates .github/workflows/prlens.yml so CI reviews are zero-config after
  `git push`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import click
import yaml
from rich.console import Console

console = Console()

_WORKFLOW_TEMPLATE = """\
name: PR Lens Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install prlens
        run: pip install "prlens[{provider}]=={version}"

      - name: Run PR review
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}
          {api_key_env}: ${{{{ secrets.{api_key_env} }}}}
        run: |
          prlens review \\
            --repo ${{{{ github.repository }}}} \\
            --pr ${{{{ github.event.pull_request.number }}}} \\
            --yes
"""


@click.command("init")
@click.option("--repo", default=None, help="GitHub repository (owner/name). Auto-detected from git remote.")
def init_cmd(repo: str | None):
    """Set up prlens for your team.

    Creates .prlens.yml, optionally creates a shared GitHub Gist for team
    history, and generates a GitHub Actions workflow.
    """
    console.print("\n[bold cyan]prlens init[/bold cyan] — team setup wizard\n")

    # --- Detect repo from git remote ---
    if repo is None:
        repo = _detect_repo_from_git()
        if repo:
            console.print(f"[dim]Detected repository: {repo}[/dim]")
        else:
            repo = click.prompt("GitHub repository (owner/name)")

    # --- Choose provider ---
    provider = click.prompt(
        "AI provider",
        type=click.Choice(["anthropic", "openai"]),
        default="anthropic",
    )

    api_key_env = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"

    # --- Choose store backend ---
    console.print("\nReview history store:")
    console.print("  [bold]none[/bold]    — no persistence (default)")
    console.print("  [bold]sqlite[/bold]  — local SQLite file (good for solo use)")
    console.print("  [bold]gist[/bold]    — shared GitHub Gist, zero infrastructure (recommended for teams)")
    store_type = click.prompt(
        "Store backend",
        type=click.Choice(["none", "sqlite", "gist"]),
        default="none",
    )

    config: dict = {"model": provider}
    gist_id = None

    if store_type == "sqlite":
        db_path = click.prompt("SQLite database path", default=".prlens.db")
        config["store"] = "sqlite"
        if db_path != ".prlens.db":
            config["store_path"] = db_path
        console.print(f"[green]SQLite store configured at {db_path}[/green]")

    elif store_type == "gist":
        console.print(
            "\n[yellow]Note:[/yellow] Gist store requires a token with [bold]gist[/bold] scope. "
            "The built-in GITHUB_TOKEN in Actions does not cover Gists — "
            "use a PAT stored as a repository secret (e.g. PRLENS_GITHUB_TOKEN)."
        )
        gist_id = _create_team_gist(repo)
        if gist_id:
            console.print(f"[green]Created team Gist: {gist_id}[/green]")
            config["store"] = "gist"
            config["gist_id"] = gist_id
        else:
            console.print("[yellow]Gist creation failed — add gist_id manually to .prlens.yml[/yellow]")

    # --- Write .prlens.yml ---
    _write_config(config)
    console.print("[green]Created .prlens.yml[/green]")

    # --- GitHub Actions workflow ---
    setup_ci = click.confirm("\nGenerate .github/workflows/prlens.yml for GitHub Actions?", default=True)
    if setup_ci:
        _write_workflow(provider, api_key_env)
        console.print("[green]Created .github/workflows/prlens.yml[/green]")
        console.print(
            f"\n[yellow]Remember to add [bold]{api_key_env}[/bold] to your "
            "GitHub repository secrets (Settings → Secrets → Actions).[/yellow]"
        )

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("Run a review with: [bold]prlens review --repo {repo} --pr <number>[/bold]".format(repo=repo))


def _detect_repo_from_git() -> str | None:
    """Try to detect the GitHub repo slug from the git remote URL."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        # Handle both HTTPS and SSH remotes:
        # https://github.com/owner/repo.git  →  owner/repo
        # git@github.com:owner/repo.git      →  owner/repo
        if "github.com" not in url:
            return None
        slug = url.split("github.com")[-1].lstrip("/:").removesuffix(".git")
        return slug if "/" in slug else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _create_team_gist(repo: str) -> str | None:
    """Create a private Gist for team review history and return its ID."""
    import tempfile
    import os

    try:
        # Write to a temp file named prlens_history.json so the Gist file
        # gets the correct name from the start (gh names files after their path).
        with tempfile.NamedTemporaryFile(mode="w", suffix="_prlens_history.json", delete=False) as tmp:
            tmp.write("[]")
            tmp_path = tmp.name

        # Rename so gh picks up the right filename.
        named_path = os.path.join(os.path.dirname(tmp_path), "prlens_history.json")
        os.rename(tmp_path, named_path)

        try:
            result = subprocess.run(
                [
                    "gh",
                    "gist",
                    "create",
                    "--public=false",
                    "--desc",
                    f"prlens review history for {repo}",
                    named_path,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        finally:
            if os.path.exists(named_path):
                os.unlink(named_path)

        if result.returncode == 0:
            gist_url = result.stdout.strip()
            return gist_url.rstrip("/").split("/")[-1]
        logger.warning("gh gist create failed: %s", result.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _write_config(config: dict) -> None:
    """Write or update .prlens.yml, preserving any existing keys."""
    path = Path(".prlens.yml")
    existing: dict = {}
    if path.exists():
        import yaml as _yaml

        existing = _yaml.safe_load(path.read_text()) or {}
    existing.update(config)
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))


def _get_version() -> str:
    """Read the current prlens version from the installed package metadata."""
    try:
        from importlib.metadata import version
        return version("prlens")
    except Exception:
        return "0.1.8"


def _write_workflow(provider: str, api_key_env: str) -> None:
    """Write the GitHub Actions workflow file."""
    workflow_dir = Path(".github/workflows")
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "prlens.yml"
    workflow_path.write_text(
        _WORKFLOW_TEMPLATE.format(provider=provider, api_key_env=api_key_env, version=_get_version())
    )
