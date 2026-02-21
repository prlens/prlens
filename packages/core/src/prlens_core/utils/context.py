"""Language-agnostic codebase context fetching for PR reviews.

All context is fetched via the GitHub API pinned to the PR's head SHA.
This guarantees that every file we read belongs to the exact same commit
snapshot as the PR being reviewed — no local filesystem, no cached state,
no branch mismatch. The head SHA is an immutable pointer; fetching with
`ref=head_sha` will always return the same bytes regardless of when or
where the tool runs (local machine, CI, GitHub Actions).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from github import GithubException

logger = logging.getLogger(__name__)

# Reduced from 20 to 10: every reviewed file triggers one get_commits() call.
# On a PR touching 20 files that is already 20 API calls before any content
# is fetched. Keeping lookback at 10 provides a strong coupling signal for
# most codebases while roughly halving the commit-API surface.
_MAX_COMMIT_LOOKBACK = 10

# Per-file content limits when injecting related files into the prompt.
# These truncate individual files — see _MAX_CONTEXT_CHARS for the total guard.
_COCHANGED_CHAR_LIMIT = 3_000
_SIBLING_CHAR_LIMIT = 2_000
_TEST_FILE_CHAR_LIMIT = 3_000

# Caps the repo map at 300 paths. A monorepo with 10,000 tracked files would
# produce ~300 KB of path strings — far beyond what adds value in a prompt.
# 300 paths gives the AI enough structural signal (layers, naming conventions,
# test coverage presence) without excessive token cost.
_REPO_MAP_LINE_LIMIT = 300

# Hard ceiling on the total rendered context injected per file review.
# Individual per-file limits above are the first line of defence; this guard
# catches cases where many sections each hit their individual cap and add up
# to an amount that would crowd out the diff and file content in the prompt.
# When this ceiling is breached, sections are dropped in priority order:
# sibling files first (weakest signal), then co-changed files, preserving
# the repo map and test file — the two highest-value, lowest-cost sections.
_MAX_CONTEXT_CHARS = 20_000

# Test/spec filename patterns covering the dominant conventions across ecosystems.
# Ordered by prevalence. We match on filename only — not file content or imports —
# so this works identically for Python, Go, TypeScript, Ruby, Rust, Java, etc.
# {stem} = filename without extension, {suffix} = extension including the dot.
_TEST_PATTERNS = [
    "test_{stem}{suffix}",  # Python:      test_reviewer.py
    "{stem}_test{suffix}",  # Go / Rust:   reviewer_test.go
    "{stem}.test{suffix}",  # JS / TS:     reviewer.test.ts
    "{stem}.spec{suffix}",  # JS / TS:     reviewer.spec.js
    "{stem}_spec{suffix}",  # Ruby:        reviewer_spec.rb
    "{stem}.test",  # Extensionless test files in some C/shell projects
]


@dataclass
class RepoContext:
    """All codebase context gathered for a single file review.

    Keeping this as a dataclass (rather than a plain dict) makes the fields
    explicit and self-documenting, and lets type checkers catch mistakes when
    context is passed through the call stack.
    """

    # Flat list of every tracked file path in the repo at head_sha.
    # Gives the AI structural awareness — layer boundaries, naming conventions,
    # presence of test directories — without consuming tokens on file content.
    repo_map: str = ""

    # Files historically committed alongside the file being reviewed.
    # Keys are file paths, values are truncated file content.
    cochanged_files: dict[str, str] = field(default_factory=dict)

    # Files from the same directory as the file being reviewed.
    # Keys are file paths, values are truncated file content.
    sibling_files: dict[str, str] = field(default_factory=dict)

    # The test/spec file paired with the file being reviewed, if one exists.
    test_file_path: str | None = None
    test_file_content: str | None = None


def build_repo_map(tree) -> str:
    """Return a flat list of all tracked file paths at the given tree snapshot.

    We include paths only — not file content — to give the AI a structural
    overview of the project without consuming excessive tokens. This lets it
    reason about layering violations (e.g. a utility module importing from a
    controller), naming conventions, and whether test coverage exists for a
    given module.

    Capped at _REPO_MAP_LINE_LIMIT lines: a monorepo with tens of thousands
    of files would produce hundreds of kilobytes of paths, which provides no
    additional signal beyond what a few hundred paths already convey.
    """
    lines = [f.path for f in tree.tree if f.type == "blob"]
    if len(lines) > _REPO_MAP_LINE_LIMIT:
        overflow = len(lines) - _REPO_MAP_LINE_LIMIT
        return "\n".join(lines[:_REPO_MAP_LINE_LIMIT]) + f"\n... [{overflow} more files not shown]"
    return "\n".join(lines)


def fetch_cochanged_files(
    repo,
    file_path: str,
    head_sha: str,
    max_files: int = 5,
) -> dict[str, str]:
    """Return files historically committed alongside this file, with content.

    Co-change coupling is language-agnostic: if two files are consistently
    modified in the same commits, they are architecturally coupled regardless
    of whether that coupling is expressed via imports, shared config, runtime
    contracts, or ownership conventions. This signal often catches
    relationships that import-parsing would miss — for example, a route
    handler and the middleware that guards it, or a model and its migration.

    Strategy:
    - Iterate lazily over the last _MAX_COMMIT_LOOKBACK commits touching
      file_path. Lazy iteration (enumerate + break) avoids forcing PyGithub
      to fetch additional API pages beyond what we need.
    - Count how many times each co-changed file appeared across those commits.
    - Fetch the top-N by frequency, pinned to head_sha.

    Files that no longer exist at head_sha (renamed, deleted) are silently
    skipped — GithubException handles that gracefully.
    """
    counter: Counter[str] = Counter()

    # Lazy iteration: we break after _MAX_COMMIT_LOOKBACK commits rather than
    # converting to list() first, which would force PyGithub to fetch the full
    # first page of results even if we only need a handful of commits.
    commits = repo.get_commits(sha=head_sha, path=file_path)
    for i, commit in enumerate(commits):
        if i >= _MAX_COMMIT_LOOKBACK:
            break
        for f in commit.files:
            if f.filename != file_path:
                counter[f.filename] += 1

    related: dict[str, str] = {}
    # Over-fetch candidates (max_files * 2) to account for files that may
    # have been deleted or renamed since those historical commits.
    for path, _ in counter.most_common(max_files * 2):
        try:
            raw = repo.get_contents(path, ref=head_sha).decoded_content.decode("utf-8", errors="replace")
            related[path] = raw[:_COCHANGED_CHAR_LIMIT]
        except GithubException:
            # File existed in a historical commit but not at head_sha — skip.
            continue
        if len(related) >= max_files:
            break

    return related


def fetch_directory_siblings(
    repo,
    file_path: str,
    head_sha: str,
    tree,
    max_files: int = 3,
) -> dict[str, str]:
    """Fetch a handful of files from the same directory as the file under review.

    Directory co-location is the simplest language-agnostic proximity signal:
    files in the same folder almost always share architectural context — they
    belong to the same layer (routes, models, handlers, components), implement
    the same interface pattern, or follow the same conventions. Showing the AI
    a few siblings helps it understand what "normal" looks like in that module
    and flag deviations.

    We pull from the already-fetched git tree rather than making an extra API
    call to list directory contents.
    """
    directory = str(Path(file_path).parent)
    siblings = [
        f.path for f in tree.tree if f.type == "blob" and str(Path(f.path).parent) == directory and f.path != file_path
    ][:max_files]

    related: dict[str, str] = {}
    for path in siblings:
        try:
            raw = repo.get_contents(path, ref=head_sha).decoded_content.decode("utf-8", errors="replace")
            related[path] = raw[:_SIBLING_CHAR_LIMIT]
        except GithubException:
            continue

    return related


def find_test_file(file_path: str, tree) -> str | None:
    """Locate the test or spec file paired with a source file.

    We match solely on filename patterns rather than parsing file content or
    import statements, making this approach work identically across all
    languages. The patterns in _TEST_PATTERNS cover the dominant conventions
    in Python, Go, Rust, TypeScript/JavaScript, Ruby, and Elixir.

    Giving the AI the test file serves two purposes:
    1. Avoid flagging behaviour that is already explicitly tested.
    2. Point out gaps — lines added in the diff that have no corresponding
       test coverage in the spec file.

    Returns the first matching path found in the tracked tree, or None.
    """
    stem = Path(file_path).stem
    suffix = Path(file_path).suffix
    tracked = {f.path for f in tree.tree if f.type == "blob"}

    for pattern in _TEST_PATTERNS:
        name = pattern.format(stem=stem, suffix=suffix)
        matches = [p for p in tracked if Path(p).name == name]
        if matches:
            return matches[0]

    return None


def build_context_section(repo_context: RepoContext | None) -> str:
    """Render codebase context into a prompt section shared by all providers.

    Lives here in context.py — alongside the data it renders — rather than
    in providers/base.py (the abstract interface). Placing rendering logic in
    the abstract interface would force any future provider that uses a
    different prompt format to work around a function it didn't ask for.

    Each subsection is labelled with a short explanation of *why* that context
    is present. This helps the model use the information purposefully rather
    than treating it as noise.

    When the total rendered size exceeds _MAX_CONTEXT_CHARS, lower-priority
    sections are dropped to protect the model's effective context window:
      sibling files (weakest signal) → co-changed files → repo map → test file.
    The test file is preserved last because it is the most directly actionable.
    """
    if repo_context is None:
        return ""

    # Build each section independently so we can drop lower-priority ones
    # without string-searching the rendered output.
    repo_map_section = ""
    if repo_context.repo_map:
        # Paths only — no content. The AI uses this to understand project
        # structure (layers, naming conventions, test coverage gaps) without
        # the token cost of full file contents.
        repo_map_section = (
            "## Repository File Tree\n"
            "Use this to understand the project structure, layer boundaries, "
            "and whether test files exist for the modules being changed.\n"
            f"```\n{repo_context.repo_map}\n```"
        )

    cochanged_section = ""
    if repo_context.cochanged_files:
        # Files committed alongside this one historically — strong signal of
        # architectural coupling regardless of language or import syntax.
        file_blocks = "\n\n".join(
            f"### {path}\n```\n{content}\n```" for path, content in repo_context.cochanged_files.items()
        )
        cochanged_section = (
            "## Files Frequently Changed Together With This File\n"
            "These files were modified in the same commits historically. "
            "They are likely coupled through shared contracts, configuration, "
            "or runtime dependencies. Use them to spot inconsistencies.\n\n" + file_blocks
        )

    sibling_section = ""
    if repo_context.sibling_files:
        # Files in the same directory establish what "normal" looks like for
        # this layer of the codebase — patterns, naming, error handling style.
        file_blocks = "\n\n".join(
            f"### {path}\n```\n{content}\n```" for path, content in repo_context.sibling_files.items()
        )
        sibling_section = (
            "## Sibling Files (same directory)\n"
            "These files share the same directory and likely follow the same "
            "conventions. Use them to flag deviations from established patterns.\n\n" + file_blocks
        )

    test_section = ""
    if repo_context.test_file_path and repo_context.test_file_content:
        # The paired test file serves two purposes: avoid flagging already-tested
        # behaviour, and identify new lines in the diff that lack coverage.
        test_section = (
            f"## Test / Spec File (`{repo_context.test_file_path}`)\n"
            "Use this to avoid flagging already-tested behaviour and to "
            "identify lines added in the diff that have no test coverage.\n"
            f"```\n{repo_context.test_file_content}\n```"
        )

    # Priority order from highest to lowest. We try progressively smaller
    # sets of sections until the total fits within _MAX_CONTEXT_CHARS.
    # Sibling files are the first to go (weakest coupling signal); the test
    # file is kept until last (most directly actionable for the reviewer).
    priority_sets = [
        [repo_map_section, cochanged_section, sibling_section, test_section],
        [repo_map_section, cochanged_section, test_section],
        [repo_map_section, test_section],
        [test_section],
    ]

    for candidate_set in priority_sets:
        parts = [s for s in candidate_set if s]
        if not parts:
            return ""
        rendered = "\n\n".join(parts)
        if len(rendered) <= _MAX_CONTEXT_CHARS:
            return "\n\n" + rendered + "\n"

    logger.warning(
        "Codebase context exceeds budget (%d chars) even after dropping all sections.",
        _MAX_CONTEXT_CHARS,
    )
    return ""


def gather_context(repo, file_path: str, head_sha: str, tree) -> RepoContext:
    """Collect all codebase context for a single file review.

    This function is the single entry point called by the review pipeline.
    Separating context gathering from the review call keeps reviewer.py clean
    and makes each strategy independently testable and replaceable.

    All GitHub API fetches are pinned to head_sha so every piece of context
    belongs to the same immutable snapshot of the codebase as the PR diff.
    """
    ctx = RepoContext(repo_map=build_repo_map(tree))

    ctx.cochanged_files = fetch_cochanged_files(repo, file_path, head_sha)
    ctx.sibling_files = fetch_directory_siblings(repo, file_path, head_sha, tree)

    test_path = find_test_file(file_path, tree)
    if test_path:
        try:
            raw = repo.get_contents(test_path, ref=head_sha).decoded_content.decode("utf-8", errors="replace")
            ctx.test_file_path = test_path
            ctx.test_file_content = raw[:_TEST_FILE_CHAR_LIMIT]
        except GithubException:
            # Test file is in the tree but not readable — not a fatal error.
            pass

    return ctx
