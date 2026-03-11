from __future__ import annotations

import re

from github import Github

_SHA_MARKER_RE = re.compile(r"<!-- prlens-sha: ([0-9a-f]{40}) -->")


def get_repo(repo_name: str, token: str = None, app_id=None, private_key: str = None):
    if app_id and private_key:
        from github import Auth, GithubIntegration

        owner, repo = repo_name.split("/", 1)
        auth = Auth.AppAuth(int(app_id), private_key)
        gi = GithubIntegration(auth=auth)
        installation = gi.get_repo_installation(owner, repo)
        return gi.get_github_for_installation(installation.id).get_repo(repo_name)
    return Github(token).get_repo(repo_name)


def get_pull(repo, pr_number: int):
    return repo.get_pull(pr_number)


def get_pull_requests(repo, state: str = "open"):
    return repo.get_pulls(state=state)


def get_diff(pr):
    return pr.get_files()


def get_last_reviewed_sha(pr) -> str | None:
    """Return the most recent HEAD SHA stored by prlens in a review body, or None."""
    last_sha = None
    for review in pr.get_reviews():
        match = _SHA_MARKER_RE.search(review.body or "")
        if match:
            last_sha = match.group(1)
    return last_sha


def get_incremental_files(repo, base_sha: str, head_sha: str):
    """Return files changed between two commits using GitHub's compare API."""
    comparison = repo.compare(base_sha, head_sha)
    return comparison.files
