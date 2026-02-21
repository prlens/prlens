"""Tests for file filtering utilities."""

from prlens_core.utils.code import is_code_file


class TestIsCodeFile:
    def test_python_file_is_code(self):
        assert is_code_file("app/services/user.py") is True

    def test_js_file_is_code(self):
        assert is_code_file("src/components/Button.tsx") is True

    def test_image_is_not_code(self):
        assert is_code_file("assets/logo.png") is False

    def test_font_is_not_code(self):
        assert is_code_file("static/fonts/Inter.woff2") is False

    def test_archive_is_not_code(self):
        assert is_code_file("dist/bundle.tar.gz") is False

    def test_lock_file_is_not_code(self):
        assert is_code_file("poetry.lock") is False
        assert is_code_file("Pipfile.lock") is False

    def test_case_insensitive(self):
        assert is_code_file("image.PNG") is False
