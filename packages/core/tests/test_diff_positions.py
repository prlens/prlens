"""Tests for diff position calculation — critical for correct GitHub comment placement."""

from prlens_core.reviewer import get_diff_positions, get_patch_line_content


def test_single_hunk():
    patch = """\
@@ -1,3 +1,4 @@
 line one
+line two added
 line three
 line four"""
    positions = get_diff_positions(patch)
    # @@ is not counted; " line one" = pos 1, "+line two added" = pos 2
    assert positions[2] == 2  # new file line 2 is at diff position 2


def test_position_is_cumulative_across_hunks():
    """diff_position must NOT reset between hunks — GitHub API requires cumulative positions."""
    patch = """\
@@ -1,2 +1,3 @@
 context a
+added in hunk 1
 context b
@@ -10,2 +11,3 @@
 context c
+added in hunk 2
 context d"""
    positions = get_diff_positions(patch)
    # Hunk 1: " context a" = pos 1, "+added in hunk 1" = pos 2 → file line 2
    assert positions[2] == 2
    # Hunk 2 (positions are cumulative, @@ not counted):
    # pos 3=" context b", pos 4=" context c", pos 5="+added in hunk 2" → file line 12
    assert positions[12] == 5


def test_removed_lines_do_not_increment_new_file_line():
    patch = """\
@@ -1,3 +1,2 @@
 context
-removed line
+added line"""
    positions = get_diff_positions(patch)
    # " context" = pos 1 (file line 1), "-removed" = pos 2 (no new file line)
    # "+added line" = pos 3 → file line 2
    assert positions[2] == 3


def test_empty_patch():
    assert get_diff_positions("") == {}


def test_no_added_lines():
    patch = """\
@@ -1,2 +1,1 @@
 context line
-removed line"""
    positions = get_diff_positions(patch)
    assert positions == {}


def test_malformed_hunk_header_does_not_raise():
    """A @@ line that cannot be parsed sets file_line to None — no mapping, no crash."""
    patch = "@@ bad header @@\n+line one"
    positions = get_diff_positions(patch)
    assert positions == {}


class TestGetPatchLineContent:
    PATCH = "@@ -1,3 +1,4 @@\n context\n-removed\n+added line\n context2\n"

    def test_returns_added_line_content(self):
        assert get_patch_line_content(self.PATCH, 2) == "added line"

    def test_returns_context_line_content(self):
        assert get_patch_line_content(self.PATCH, 1) == " context"[1:]

    def test_returns_empty_string_when_line_not_found(self):
        assert get_patch_line_content(self.PATCH, 99) == ""

    def test_skips_removed_lines(self):
        """Removed lines (-) must not consume a new-file line number."""
        patch = "@@ -1,3 +1,2 @@\n context\n-removed\n+new"
        assert get_patch_line_content(patch, 2) == "new"

    def test_malformed_header_returns_empty(self):
        """A bad @@ header sets file_line to None so nothing matches."""
        patch = "@@ oops @@\n+line"
        assert get_patch_line_content(patch, 1) == ""
