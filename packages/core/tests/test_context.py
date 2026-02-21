"""Tests for language-agnostic codebase context gathering.

Each function in context.py is tested in isolation so failures are easy to
localise — the unit tests here do not depend on the review pipeline.
"""

import types
from unittest.mock import MagicMock

from github import GithubException

from prlens_core.utils.context import (
    RepoContext,
    _MAX_COMMIT_LOOKBACK,
    _MAX_CONTEXT_CHARS,
    _REPO_MAP_LINE_LIMIT,
    build_context_section,
    build_repo_map,
    fetch_cochanged_files,
    fetch_directory_siblings,
    find_test_file,
    gather_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tree(*paths: str):
    """Return a mock git tree whose blobs have the given paths."""
    tree = MagicMock()
    tree.tree = [types.SimpleNamespace(path=p, type="blob") for p in paths]
    return tree


def _make_tree_with_dirs(*entries):
    """Return a mock tree containing both blob and tree (directory) entries."""
    tree = MagicMock()
    tree.tree = [types.SimpleNamespace(path=e[0], type=e[1]) for e in entries]
    return tree


def _make_commit(*filenames: str):
    """Return a mock commit whose changed files are the given filenames."""
    commit = MagicMock()
    commit.files = [types.SimpleNamespace(filename=f) for f in filenames]
    return commit


def _make_content(text: str = "content"):
    """Return a mock GitHub contents object with the given decoded text."""
    mock = MagicMock()
    mock.decoded_content = text.encode()
    return mock


# ---------------------------------------------------------------------------
# build_repo_map
# ---------------------------------------------------------------------------


class TestBuildRepoMap:
    def test_returns_blob_paths(self):
        tree = _make_tree("src/foo.py", "src/bar.py")
        result = build_repo_map(tree)
        assert "src/foo.py" in result
        assert "src/bar.py" in result

    def test_excludes_non_blob_entries(self):
        # Tree-type entries (directories) must not appear in the map — they
        # would add noise without giving the AI useful structural signal.
        tree = _make_tree_with_dirs(
            ("src/", "tree"),
            ("src/foo.py", "blob"),
        )
        result = build_repo_map(tree)
        assert "src/foo.py" in result
        assert "src/" not in result.splitlines()

    def test_empty_tree_returns_empty_string(self):
        assert build_repo_map(_make_tree()) == ""

    def test_truncates_at_line_limit(self):
        # Produce _REPO_MAP_LINE_LIMIT + 5 paths to trigger truncation.
        paths = [f"src/file_{i}.py" for i in range(_REPO_MAP_LINE_LIMIT + 5)]
        tree = _make_tree(*paths)
        result = build_repo_map(tree)
        lines = result.splitlines()
        # The truncation notice is always the last line.
        assert "more files not shown" in lines[-1]
        # Only _REPO_MAP_LINE_LIMIT content lines before the notice.
        assert len(lines) == _REPO_MAP_LINE_LIMIT + 1

    def test_exactly_at_limit_is_not_truncated(self):
        paths = [f"src/file_{i}.py" for i in range(_REPO_MAP_LINE_LIMIT)]
        result = build_repo_map(_make_tree(*paths))
        assert "more files not shown" not in result


# ---------------------------------------------------------------------------
# find_test_file
# ---------------------------------------------------------------------------


class TestFindTestFile:
    def test_python_prefix_pattern(self):
        # test_{stem}{suffix} — dominant Python convention
        tree = _make_tree("tests/test_reviewer.py", "prlens_core/reviewer.py")
        assert find_test_file("prlens_core/reviewer.py", tree) == "tests/test_reviewer.py"

    def test_go_suffix_pattern(self):
        # {stem}_test{suffix} — Go / Rust convention
        tree = _make_tree("reviewer_test.go", "reviewer.go")
        assert find_test_file("reviewer.go", tree) == "reviewer_test.go"

    def test_ts_dot_test_pattern(self):
        # {stem}.test{suffix} — Jest / Vitest convention
        tree = _make_tree("src/reviewer.test.ts", "src/reviewer.ts")
        assert find_test_file("src/reviewer.ts", tree) == "src/reviewer.test.ts"

    def test_js_spec_pattern(self):
        # {stem}.spec{suffix} — Jasmine / Mocha convention
        tree = _make_tree("src/reviewer.spec.js", "src/reviewer.js")
        assert find_test_file("src/reviewer.js", tree) == "src/reviewer.spec.js"

    def test_ruby_spec_pattern(self):
        # {stem}_spec{suffix} — RSpec convention
        tree = _make_tree("spec/reviewer_spec.rb", "lib/reviewer.rb")
        assert find_test_file("lib/reviewer.rb", tree) == "spec/reviewer_spec.rb"

    def test_no_match_returns_none(self):
        tree = _make_tree("src/other.py")
        assert find_test_file("src/reviewer.py", tree) is None

    def test_no_false_positive_on_unrelated_test_file(self):
        # test_other.py shares no stem with reviewer.py — must not match.
        tree = _make_tree("tests/test_other.py")
        assert find_test_file("prlens_core/reviewer.py", tree) is None

    def test_empty_tree_returns_none(self):
        assert find_test_file("src/foo.py", _make_tree()) is None

    def test_returns_first_match_when_multiple_patterns_match(self):
        # Both test_foo.py and foo_test.py are present; the higher-priority
        # pattern (test_{stem}) should win.
        tree = _make_tree("tests/test_foo.py", "foo_test.py")
        result = find_test_file("src/foo.py", tree)
        assert result == "tests/test_foo.py"


# ---------------------------------------------------------------------------
# fetch_directory_siblings
# ---------------------------------------------------------------------------


class TestFetchDirectorySiblings:
    def test_returns_files_from_same_directory(self):
        tree = _make_tree(
            "prlens_core/reviewer.py",
            "prlens_core/config.py",
            "prlens_core/cli.py",
            "tests/test_foo.py",  # different directory — must be excluded
        )
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = _make_content("# config")

        result = fetch_directory_siblings(mock_repo, "prlens_core/reviewer.py", "sha", tree, max_files=5)

        assert "prlens_core/config.py" in result
        assert "prlens_core/cli.py" in result
        # Different directory must not appear
        assert "tests/test_foo.py" not in result

    def test_excludes_the_file_itself(self):
        # The file under review must never appear as its own sibling.
        tree = _make_tree("src/foo.py")
        mock_repo = MagicMock()
        result = fetch_directory_siblings(mock_repo, "src/foo.py", "sha", tree)
        assert "src/foo.py" not in result

    def test_respects_max_files(self):
        tree = _make_tree("src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/reviewer.py")
        mock_repo = MagicMock()
        mock_repo.get_contents.return_value = _make_content()

        result = fetch_directory_siblings(mock_repo, "src/reviewer.py", "sha", tree, max_files=2)
        assert len(result) <= 2

    def test_skips_unfetchable_files(self):
        # A file in the tree that no longer exists at head_sha (e.g. deleted
        # in a later commit) must be silently skipped, not raise.
        tree = _make_tree("src/reviewer.py", "src/gone.py")
        mock_repo = MagicMock()
        mock_repo.get_contents.side_effect = GithubException(404, "Not Found")

        result = fetch_directory_siblings(mock_repo, "src/reviewer.py", "sha", tree)
        assert result == {}

    def test_returns_empty_for_file_with_no_siblings(self):
        tree = _make_tree("src/reviewer.py")
        mock_repo = MagicMock()
        result = fetch_directory_siblings(mock_repo, "src/reviewer.py", "sha", tree)
        assert result == {}


# ---------------------------------------------------------------------------
# fetch_cochanged_files
# ---------------------------------------------------------------------------


class TestFetchCochangedFiles:
    def test_returns_most_frequently_cochanged_file(self):
        # config.py appears in 2 of 3 commits alongside reviewer.py; it should
        # be ranked above cli.py which appears only once.
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = [
            _make_commit("prlens_core/reviewer.py", "prlens_core/config.py"),
            _make_commit("prlens_core/reviewer.py", "prlens_core/config.py"),
            _make_commit("prlens_core/reviewer.py", "prlens_core/cli.py"),
        ]
        mock_repo.get_contents.return_value = _make_content("# content")

        result = fetch_cochanged_files(mock_repo, "prlens_core/reviewer.py", "sha", max_files=1)

        assert "prlens_core/config.py" in result
        assert "prlens_core/cli.py" not in result  # max_files=1 means only the top hit

    def test_excludes_the_file_itself(self):
        # The file under review appears in every commit by definition — it
        # must never be included as a co-changed file.
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = [
            _make_commit("prlens_core/reviewer.py", "prlens_core/reviewer.py"),
        ]
        mock_repo.get_contents.return_value = _make_content()

        result = fetch_cochanged_files(mock_repo, "prlens_core/reviewer.py", "sha")
        assert "prlens_core/reviewer.py" not in result

    def test_skips_files_deleted_since_historical_commit(self):
        # A file that appeared in a past commit but no longer exists at
        # head_sha should be silently skipped, not raise.
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = [
            _make_commit("prlens_core/reviewer.py", "prlens_core/old_module.py"),
        ]
        mock_repo.get_contents.side_effect = GithubException(404, "Not Found")

        result = fetch_cochanged_files(mock_repo, "prlens_core/reviewer.py", "sha")
        assert result == {}

    def test_returns_empty_for_new_file_with_no_history(self):
        # A brand-new file has no commit history — no co-change data, no crash.
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = []

        result = fetch_cochanged_files(mock_repo, "prlens_core/brand_new.py", "sha")
        assert result == {}

    def test_respects_max_files(self):
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = [
            _make_commit("src/a.py", "src/b.py", "src/c.py", "src/d.py"),
        ]
        mock_repo.get_contents.return_value = _make_content()

        result = fetch_cochanged_files(mock_repo, "src/main.py", "sha", max_files=2)
        assert len(result) <= 2

    def test_lazy_iteration_stops_at_lookback_limit(self):
        # Commit history is longer than _MAX_COMMIT_LOOKBACK. We must stop
        # iterating early rather than consuming all pages from the API.

        # Provide more commits than the limit.
        commits = [_make_commit("src/main.py", f"src/other_{i}.py") for i in range(_MAX_COMMIT_LOOKBACK + 20)]
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = commits
        mock_repo.get_contents.return_value = _make_content()

        fetch_cochanged_files(mock_repo, "src/main.py", "sha")

        # Each commit we processed results in one get_contents call.
        # We must have processed at most _MAX_COMMIT_LOOKBACK commits.
        assert mock_repo.get_commits.call_count == 1  # single get_commits() call


# ---------------------------------------------------------------------------
# build_context_section
# ---------------------------------------------------------------------------


class TestBuildContextSection:
    def test_none_returns_empty_string(self):
        assert build_context_section(None) == ""

    def test_empty_context_returns_empty_string(self):
        assert build_context_section(RepoContext()) == ""

    def test_repo_map_included_with_header(self):
        ctx = RepoContext(repo_map="src/foo.py\nsrc/bar.py")
        result = build_context_section(ctx)
        assert "src/foo.py" in result
        assert "Repository File Tree" in result

    def test_cochanged_files_included_with_header(self):
        ctx = RepoContext(cochanged_files={"src/config.py": "# cfg"})
        result = build_context_section(ctx)
        assert "src/config.py" in result
        assert "# cfg" in result
        assert "Frequently Changed Together" in result

    def test_sibling_files_included_with_header(self):
        ctx = RepoContext(sibling_files={"src/sibling.py": "# sib"})
        result = build_context_section(ctx)
        assert "src/sibling.py" in result
        assert "# sib" in result
        assert "Sibling" in result

    def test_test_file_included_with_header(self):
        ctx = RepoContext(
            test_file_path="tests/test_foo.py",
            test_file_content="def test_x(): pass",
        )
        result = build_context_section(ctx)
        assert "tests/test_foo.py" in result
        assert "def test_x(): pass" in result
        assert "Test / Spec" in result

    def test_test_file_omitted_when_content_is_none(self):
        # Path set but no content — the section must not appear to avoid
        # a heading with an empty code block confusing the model.
        ctx = RepoContext(test_file_path="tests/test_foo.py", test_file_content=None)
        result = build_context_section(ctx)
        assert "Test / Spec" not in result

    def test_drops_siblings_when_over_budget(self):
        # Fill the context beyond _MAX_CONTEXT_CHARS using sibling content
        # so the guard has to drop the sibling section.
        large = "x" * _MAX_CONTEXT_CHARS
        ctx = RepoContext(
            repo_map="src/foo.py",
            sibling_files={"src/big.py": large},
        )
        result = build_context_section(ctx)
        # Sibling section dropped but repo map kept.
        assert "Repository File Tree" in result
        assert "Sibling" not in result

    def test_all_sections_present_when_within_budget(self):
        ctx = RepoContext(
            repo_map="src/foo.py",
            cochanged_files={"src/config.py": "# cfg"},
            sibling_files={"src/other.py": "# other"},
            test_file_path="tests/test_foo.py",
            test_file_content="def test_x(): pass",
        )
        result = build_context_section(ctx)
        assert "Repository File Tree" in result
        assert "Frequently Changed Together" in result
        assert "Sibling" in result
        assert "Test / Spec" in result


# ---------------------------------------------------------------------------
# gather_context
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_returns_repo_context_with_repo_map(self):
        tree = _make_tree("src/foo.py", "src/bar.py")
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = []

        ctx = gather_context(mock_repo, "src/foo.py", "sha", tree)

        assert isinstance(ctx, RepoContext)
        assert "src/foo.py" in ctx.repo_map
        assert "src/bar.py" in ctx.repo_map

    def test_finds_and_fetches_test_file(self):
        # tests/test_foo.py matches "src/foo.py" via the test_{stem} pattern.
        tree = _make_tree("src/foo.py", "tests/test_foo.py")
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = []
        mock_repo.get_contents.return_value = _make_content("def test_x(): pass")

        ctx = gather_context(mock_repo, "src/foo.py", "sha", tree)

        assert ctx.test_file_path == "tests/test_foo.py"
        assert "def test_x(): pass" in ctx.test_file_content

    def test_no_test_file_when_none_exists(self):
        tree = _make_tree("src/foo.py")
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = []

        ctx = gather_context(mock_repo, "src/foo.py", "sha", tree)

        assert ctx.test_file_path is None
        assert ctx.test_file_content is None

    def test_test_file_fetch_failure_does_not_raise(self):
        # If the test file is in the tree but unreadable, gather_context must
        # still return a valid (partial) RepoContext rather than propagating
        # the exception and aborting the entire review.
        tree = _make_tree("src/foo.py", "tests/test_foo.py")
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = []
        mock_repo.get_contents.side_effect = GithubException(403, "Forbidden")

        ctx = gather_context(mock_repo, "src/foo.py", "sha", tree)

        assert ctx.test_file_path is None

    def test_cochanged_files_populated_from_commit_history(self):
        tree = _make_tree("src/foo.py", "src/bar.py")
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = [
            _make_commit("src/foo.py", "src/bar.py"),
        ]
        mock_repo.get_contents.return_value = _make_content("# bar")

        ctx = gather_context(mock_repo, "src/foo.py", "sha", tree)

        assert "src/bar.py" in ctx.cochanged_files

    def test_sibling_files_populated_from_same_directory(self):
        tree = _make_tree("src/foo.py", "src/sibling.py")
        mock_repo = MagicMock()
        mock_repo.get_commits.return_value = []
        mock_repo.get_contents.return_value = _make_content("# sibling")

        ctx = gather_context(mock_repo, "src/foo.py", "sha", tree)

        assert "src/sibling.py" in ctx.sibling_files
