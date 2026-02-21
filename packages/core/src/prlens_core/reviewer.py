"""Core PR review orchestration."""

from __future__ import annotations

import fnmatch
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from github import GithubException
from rich.console import Console

from prlens_core.config import load_guidelines
from prlens_core.gh.pull_request import get_diff, get_incremental_files, get_last_reviewed_sha, get_pull, get_repo
from prlens_core.providers.anthropic import AnthropicReviewer
from prlens_core.providers.openai import OpenAIReviewer
from prlens_core.utils.code import is_code_file
from prlens_core.utils.context import RepoContext, gather_context

console = Console()
logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"critical": 3, "major": 2, "minor": 1, "nitpick": 0}


@dataclass
class ReviewSummary:
    """Result returned by run_review — carries enough data for the CLI to persist history.

    Decoupled from prlens_store so prlens_core has no dependency on the store layer.
    The CLI converts this to a ReviewRecord before persisting.
    """

    repo: str
    pr_number: int
    head_sha: str
    event: str  # "APPROVE" | "COMMENT" | "REQUEST_CHANGES"
    reviewed_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    total_comments: int = 0
    comments: list[dict] = field(default_factory=list)
    reviewed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _get_reviewer(config: dict):
    model = config["model"]
    if model == "anthropic":
        return AnthropicReviewer(api_key=config["anthropic_api_key"])
    if model == "openai":
        return OpenAIReviewer(api_key=config["openai_api_key"])
    raise ValueError(f"Unknown model provider: {model!r}. Choose 'anthropic' or 'openai'.")


def _is_excluded(filename: str, patterns: list[str]) -> bool:
    """Return True if filename matches any exclude pattern.

    Supports:
    - fnmatch globs on the full path: "src/generated/*.py"
    - fnmatch globs on the basename: "*.lock", "*.min.js"
    - Directory names/prefixes: "migrations/", "tests" (matches any file within that tree)
    """
    for pattern in patterns:
        if fnmatch.fnmatch(filename, pattern):
            return True
        # Basename match: "*.lock" matches "path/to/yarn.lock"
        if fnmatch.fnmatch(filename.rsplit("/", 1)[-1], pattern):
            return True
        # Directory prefix: "migrations" or "migrations/" matches "app/migrations/0001.py"
        prefix = pattern.rstrip("/") + "/"
        if filename.startswith(prefix) or ("/" + prefix) in filename:
            return True
    return False


def _determine_event(comments: list[dict]) -> str:
    """Choose the GitHub review event based on the highest severity present."""
    if not comments:
        return "APPROVE"
    severities = {c.get("severity", "minor") for c in comments}
    if severities & {"critical", "major"}:
        return "REQUEST_CHANGES"
    return "COMMENT"


def _build_summary(
    file_summary: list[dict],
    all_comments: list[dict],
    elapsed_seconds: float,
    incremental_info: dict | None = None,
) -> str:
    """Build the top-level review body posted as the GitHub review description."""
    reviewed = [f for f in file_summary if not f["skipped"] and f["error"] is None]
    skipped = [f for f in file_summary if f["skipped"]]
    errors = [f for f in file_summary if f["error"] is not None]

    # Per-file severity counts.
    severities = ("critical", "major", "minor", "nitpick")
    file_counts: dict[str, dict[str, int]] = {}
    for c in all_comments:
        sev = c.get("severity", "minor")
        path = c.get("path", "")
        if path not in file_counts:
            file_counts[path] = {s: 0 for s in severities}
        file_counts[path][sev] = file_counts[path].get(sev, 0) + 1

    # Overall severity totals.
    totals: dict[str, int] = {s: 0 for s in severities}
    for counts in file_counts.values():
        for s in severities:
            totals[s] += counts.get(s, 0)
    total_comments = sum(totals.values())

    # Elapsed time.
    elapsed_min = elapsed_seconds / 60
    if elapsed_min < 1:
        time_str = f"{int(elapsed_seconds)}s"
    else:
        time_str = f"{elapsed_min:.1f} min"

    lines = ["## Review summary\n"]

    if incremental_info:
        base = incremental_info["base_sha"][:7]
        head = incremental_info["head_sha"][:7]
        lines.append(f"_Incremental review: `{base}` → `{head}`_\n")

    # Short auto-generated verdict.
    if total_comments == 0:
        verdict = "No issues found. The changes look good."
    else:
        parts = []
        if totals["critical"]:
            parts.append(f"{totals['critical']} critical")
        if totals["major"]:
            parts.append(f"{totals['major']} major")
        if totals["minor"]:
            parts.append(f"{totals['minor']} minor")
        if totals["nitpick"]:
            parts.append(f"{totals['nitpick']} nitpick")
        issue_str = ", ".join(parts)
        flagged = sorted(file_counts, key=lambda p: sum(file_counts[p].values()), reverse=True)
        top = f"`{flagged[0]}`" if flagged else ""
        if totals["critical"] or totals["major"]:
            verdict = f"{issue_str} issue(s) — changes required. Most flagged: {top}."
        else:
            verdict = f"{issue_str} suggestion(s). Most flagged: {top}."
    lines.append(f"> {verdict}\n")

    # Stats line.
    lines.append(
        f"**{len(reviewed)}** file(s) reviewed"
        + (f", **{len(skipped)}** skipped" if skipped else "")
        + (f", **{len(errors)}** error(s)" if errors else "")
        + f" · **{total_comments}** comment(s) · reviewed in {time_str}\n"
    )

    # Per-file severity table.
    files_with_comments = [f for f in reviewed if f["count"] > 0]
    if files_with_comments:
        lines.append("| File | Critical | Major | Minor | Nitpick | Total |")
        lines.append("|------|:--------:|:-----:|:-----:|:-------:|:-----:|")
        for f in files_with_comments:
            fc = file_counts.get(f["filename"], {s: 0 for s in severities})
            lines.append(
                f"| `{f['filename']}` "
                f"| {fc.get('critical', 0) or '—'} "
                f"| {fc.get('major', 0) or '—'} "
                f"| {fc.get('minor', 0) or '—'} "
                f"| {fc.get('nitpick', 0) or '—'} "
                f"| {f['count']} |"
            )

    clean_files = [f for f in reviewed if f["count"] == 0]
    if clean_files:
        lines.append(f"\n_Clean: {len(clean_files)} file(s) with no issues._")

    if errors:
        lines.append("\n**Could not fetch:**")
        for f in errors:
            lines.append(f"- `{f['filename']}`: {f['error']}")

    return "\n".join(lines)


def get_diff_positions(patch_text: str) -> dict[int, int]:
    """
    Maps new-file line numbers to their cumulative GitHub diff positions.

    GitHub's review comment API requires positions that are cumulative across
    the entire patch, not reset per hunk. The @@ header line is NOT counted —
    position 1 is the first content line immediately below the @@ header.
    """
    positions: dict[int, int] = {}
    diff_position = 0
    file_line: int | None = None

    for line in patch_text.splitlines():
        if line.startswith("@@"):
            try:
                new_file_range = line.split("+")[1].split(" ")[0]
                file_line = int(new_file_range.split(",")[0])
            except Exception:
                file_line = None
            continue  # @@ header is not counted in diff positions

        diff_position += 1

        if line.startswith("+") and not line.startswith("+++"):
            if file_line is not None:
                positions[file_line] = diff_position
                file_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass  # Removed line — does not advance the new-file line counter
        else:
            if file_line is not None:
                file_line += 1

    return positions


def get_patch_line_content(patch_text: str, target_line: int) -> str:
    """Return the source content of a specific new-file line number from a patch."""
    file_line: int | None = None
    for line in patch_text.splitlines():
        if line.startswith("@@"):
            try:
                new_file_range = line.split("+")[1].split(" ")[0]
                file_line = int(new_file_range.split(",")[0])
            except Exception:
                file_line = None
            continue
        if line.startswith("-") and not line.startswith("---"):
            continue  # removed line — no new-file line number
        if file_line is not None:
            if file_line == target_line:
                return line[1:] if line and line[0] in ("+", " ") else line
            file_line += 1
    return ""


def already_commented(
    existing_comments,
    file_path: str,
    file_line: int,
    comment_text: str,
    queued: set[tuple] | None = None,
) -> bool:
    """Check whether an identical comment already exists on the PR for this file+line.

    Checks both GitHub's existing review comments and any comments queued in the
    current run (to catch duplicates across batch boundaries or within a single file).
    """
    text = comment_text.strip()
    if queued is not None and (file_path, file_line, text) in queued:
        return True
    for c in existing_comments:
        # c.line is None for comments whose line no longer exists in the current diff
        # (e.g. after a force-push). Fall back to original_line in that case.
        comment_line = c.line if c.line is not None else getattr(c, "original_line", None)
        if c.path == file_path and comment_line == file_line and text in c.body.strip():
            return True
    return False


def process_file(
    reviewer,
    guidelines: str,
    pr_body: str,
    file,
    patch: str,
    file_content: str,
    existing_comments: list,
    queued: set[tuple] | None = None,
    repo_context: RepoContext | None = None,
) -> list[dict]:
    if file.filename is None or not patch:
        return []
    if file.status not in ("modified", "added"):
        return []

    diff_positions = get_diff_positions(patch)
    comments = reviewer.review(
        description=pr_body,
        file_name=file.filename,
        diff_patch=patch,
        file_content=file_content,
        guidelines=guidelines,
        # repo_context enriches the review with codebase-wide signals:
        # co-change history, directory siblings, and the paired test file.
        # None is safe — providers degrade gracefully when context is absent.
        repo_context=repo_context,
    )

    results = []
    for comment in comments:
        line = comment.get("line")
        text = comment.get("comment", "")
        severity = comment.get("severity", "minor")
        if severity not in _SEVERITY_RANK:
            severity = "minor"
        if not line or not text:
            continue
        if line not in diff_positions:
            logger.debug("Skipping comment for line %d (not in diff positions)", line)
            continue
        if already_commented(existing_comments, file.filename, line, text, queued):
            logger.debug("Skipping duplicate comment for line %d", line)
            continue
        body = f"**[{severity.upper()}]**\n\n{text}"
        results.append(
            {
                "path": file.filename,
                "position": diff_positions[line],
                "body": body,
                "line": line,
                "severity": severity,
                "code": get_patch_line_content(patch, line),
            }
        )
        if queued is not None:
            queued.add((file.filename, line, text.strip()))

    return results


def print_shadow_comments(comments: list[dict]) -> None:
    """Print review comments to the terminal without posting to GitHub."""
    _severity_color = {"critical": "red", "major": "yellow", "minor": "blue", "nitpick": "dim"}
    if not comments:
        console.print("[yellow]Shadow mode: no comments generated.[/yellow]")
        return
    console.print(f"\n[bold]Shadow review — {len(comments)} comment(s) (not posted)[/bold]\n")
    for c in comments:
        severity = c.get("severity", "minor")
        color = _severity_color.get(severity, "white")
        console.print(
            f"[bold cyan]{c['path']}[/bold cyan]  line [bold]{c['line']}[/bold]  "
            f"[{color}]{severity.upper()}[/{color}]"
        )
        code = c.get("code", "").strip()
        if code:
            console.print(f"  [dim]{code}[/dim]")
        console.print(f"  {c['body']}")
        console.print()


def flush_to_file(repo_name: str, pr_id: int, comments: list[dict], log_path: str = "comments.log"):
    with open(log_path, "a", encoding="utf-8") as f:
        for comment in comments:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            path = comment.get("path", "unknown")
            position = comment.get("position", "")
            text = comment.get("body", "").replace('"', '\\"')
            f.write(
                f"[{timestamp}] - {repo_name}#{pr_id} : {path} - " f'{{"position": {position}, "comment": "{text}"}}\n'
            )


def run_review(
    repo: str,
    pr_number: int,
    config: dict,
    auto_confirm: bool = False,
    shadow: bool = False,
    force_full: bool = False,
    repo_obj=None,
) -> ReviewSummary | None:
    """Run the full PR review pipeline and return a ReviewSummary.

    Returns None only on unrecoverable early exits (draft skip, no new commits).
    Returns a ReviewSummary in all other cases, including shadow mode.
    The CLI layer uses this to persist review history to the configured store.
    """
    this_repo = repo_obj if repo_obj is not None else get_repo(repo, token=config["github_token"])

    try:
        this_pr = get_pull(this_repo, pr_number)
    except GithubException:
        raise ValueError(f"PR #{pr_number} not found in {repo}.")

    if this_pr.draft and not config.get("review_draft_prs", False):
        console.print("[yellow]Skipping draft PR. Set review_draft_prs: true in .prlens.yml to review drafts.[/yellow]")
        return None

    head_sha = this_pr.head.sha
    incremental_info: dict | None = None

    if not force_full:
        last_sha = get_last_reviewed_sha(this_pr)
        if last_sha:
            if last_sha == head_sha:
                console.print("[yellow]No new commits since the last review. Nothing to do.[/yellow]")
                return None
            try:
                diff_files = sorted(get_incremental_files(this_repo, last_sha, head_sha), key=lambda f: f.filename)
                incremental_info = {"base_sha": last_sha, "head_sha": head_sha}
                console.print(
                    f"[cyan]Incremental review: {last_sha[:7]} → {head_sha[:7]} "
                    f"({len(diff_files)} file(s) changed)[/cyan]"
                )
            except GithubException:
                console.print(
                    "[yellow]Could not compute incremental diff (force push?). Falling back to full review.[/yellow]"
                )
                diff_files = sorted(get_diff(this_pr), key=lambda f: f.filename)
        else:
            diff_files = sorted(get_diff(this_pr), key=lambda f: f.filename)
    else:
        diff_files = sorted(get_diff(this_pr), key=lambda f: f.filename)

    pr_body = this_pr.body or ""
    reviewer = _get_reviewer(config)
    guidelines = load_guidelines(config)
    max_chars = config.get("max_chars_per_file", 20000)
    batch_limit = config.get("batch_limit", 60)
    exclude_patterns = config.get("exclude", [])

    total = len(diff_files)

    existing_comments = list(this_pr.get_review_comments())
    queued: set[tuple] = set()

    # Fetch the full git tree once for the entire PR run, not per file.
    # The tree gives us two things cheaply: a flat list of all tracked paths
    # for the repo map, and the set of paths needed to locate test files by
    # naming convention — both without any per-file API calls.
    # We pin to head_sha so the tree is consistent with every other fetch.
    try:
        repo_tree = this_repo.get_git_tree(head_sha, recursive=True)
        console.print("[dim]Fetched repository tree for codebase context.[/dim]")
    except Exception as e:
        # Non-fatal: if the tree fetch fails (very large repo, permissions),
        # we fall back to no codebase context rather than aborting the review.
        logger.warning("Could not fetch repo tree; codebase context will be skipped: %s", e)
        repo_tree = None

    all_comments: list[dict] = []
    file_summary: list[dict] = []
    review_start = time.monotonic()

    for i, file in enumerate(diff_files, 1):
        if _is_excluded(file.filename, exclude_patterns) or not is_code_file(file.filename):
            console.print(f"  Skipping: {file.filename}")
            file_summary.append({"filename": file.filename, "count": 0, "skipped": True, "error": None})
            continue

        console.print(f"\n[[{i}/{total}]] Reviewing: {file.filename}")

        try:
            file_content = this_repo.get_contents(file.filename, ref=this_pr.head.sha).decoded_content.decode(
                "utf-8", errors="replace"
            )
        except GithubException as e:
            console.print(f"  [red]Could not fetch file: {e}[/red]")
            file_summary.append({"filename": file.filename, "count": 0, "skipped": False, "error": str(e)})
            continue

        patch = file.patch or ""
        if len(patch) > max_chars:
            patch = patch[:max_chars] + "\n... [diff truncated]"
        if len(file_content) > max_chars:
            file_content = file_content[:max_chars] + "\n... [file truncated]"

        # Gather codebase context for this file using language-agnostic signals:
        # co-change history from git commits, directory siblings, and the paired
        # test file located by naming convention. All fetches are pinned to
        # head_sha — the same immutable snapshot as the diff and file content —
        # so the AI never sees an inconsistent view of the codebase.
        # If repo_tree is None (fetch failed above), gather_context returns an
        # empty RepoContext and the review proceeds without extra context.
        repo_context = gather_context(this_repo, file.filename, head_sha, repo_tree) if repo_tree else None

        new_comments = process_file(
            reviewer, guidelines, pr_body, file, patch, file_content, existing_comments, queued, repo_context
        )
        all_comments.extend(new_comments)
        file_summary.append({"filename": file.filename, "count": len(new_comments), "skipped": False, "error": None})
        console.print(f"  {len(new_comments)} comment(s) found.")

    event = _determine_event(all_comments)

    if shadow:
        print_shadow_comments(all_comments)
        console.print(f"[bold]Shadow review complete. {len(all_comments)} comment(s) would be posted.[/bold]")
        return ReviewSummary(
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
            event=event,
            reviewed_files=[f["filename"] for f in file_summary if not f["skipped"] and f["error"] is None],
            skipped_files=[f["filename"] for f in file_summary if f["skipped"]],
            total_comments=len(all_comments),
            comments=all_comments,
        )

    elapsed = time.monotonic() - review_start
    sha_marker = f"\n<!-- prlens-sha: {head_sha} -->"
    summary_body = _build_summary(file_summary, all_comments, elapsed, incremental_info) + sha_marker

    if not all_comments:
        if not auto_confirm:
            answer = input("No issues found. Post APPROVE review? (y/n): ").strip().lower()
            if answer != "y":
                return None
        this_pr.create_review(body=summary_body, event="APPROVE")
        console.print("\n[green]Review posted: APPROVE[/green]")
    else:
        if not auto_confirm:
            answer = input(f"Post {len(all_comments)} comment(s) as {event}? (y/n): ").strip().lower()
            if answer != "y":
                return None

        batches = [all_comments[i : i + batch_limit] for i in range(0, len(all_comments), batch_limit)]
        total_posted = 0
        for idx, batch in enumerate(batches):
            is_last = idx == len(batches) - 1
            batch_body = (
                summary_body
                if is_last
                else f"Review in progress ({total_posted + len(batch)}/{len(all_comments)} comments)..."
            )
            batch_event = event if is_last else "COMMENT"
            flush_to_file(repo, pr_number, batch)
            api_comments = [{"path": c["path"], "position": c["position"], "body": c["body"]} for c in batch]
            this_pr.create_review(body=batch_body, event=batch_event, comments=api_comments)
            total_posted += len(batch)

        reviewed_count = sum(1 for f in file_summary if not f["skipped"] and f["error"] is None)
        console.print(
            f"\n[green]Review posted: {event}. {total_posted} comment(s) across {reviewed_count} file(s).[/green]"
        )

    return ReviewSummary(
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        event=event,
        reviewed_files=[f["filename"] for f in file_summary if not f["skipped"] and f["error"] is None],
        skipped_files=[f["filename"] for f in file_summary if f["skipped"]],
        total_comments=len(all_comments),
        comments=all_comments,
    )
