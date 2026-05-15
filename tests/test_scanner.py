"""测试 scanner 模块。"""

import os
import pytest

from reposcope.scanner.filters import (
    should_skip_directory,
    should_skip_file,
    DEFAULT_MAX_FILE_SIZE_KB,
)
from reposcope.scanner.file_scanner import ScannerConfig, scan_directory


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample_project")


class TestFilters:
    def test_skip_known_dirs(self):
        for d in ["__pycache__", ".git", "venv", ".venv", "node_modules", ".mypy_cache"]:
            assert should_skip_directory(d) is True

    def test_not_skip_normal_dirs(self):
        for d in ["src", "tests", "models", "utils", "my_project"]:
            assert should_skip_directory(d) is False

    def test_skip_hidden_dirs(self):
        for d in [".secret", ".config"]:
            assert should_skip_directory(d) is True

    def test_skip_binary_extensions(self):
        for ext in [".pyc", ".dll", ".so", ".exe", ".dat", ".bin"]:
            skip, reason = should_skip_file(f"test{ext}")
            assert skip is True, f"应跳过 {ext}"
            assert reason != ""

    def test_skip_large_file(self):
        skip, reason = should_skip_file("large.py", file_size=600 * 1024, max_size_kb=500)
        assert skip is True
        assert "过大" in reason

    def test_accept_normal_py(self):
        skip, reason = should_skip_file("main.py", file_size=1024)
        assert skip is False
        assert reason == ""

    def test_accept_py_with_different_case(self):
        skip, _ = should_skip_file("Main.PY", file_size=1024)
        assert skip is False

    def test_skip_no_extension(self):
        skip, reason = should_skip_file("Makefile", file_size=100)
        assert skip is True


class TestFileScanner:
    def test_scan_finds_all_py_files(self):
        result = scan_directory(FIXTURE_DIR)
        files = [os.path.basename(f) for f in result.python_files]

        assert "main.py" in files
        assert "config.py" in files
        assert "helpers.py" in files
        assert "user.py" in files
        assert "__init__.py" in files

    def test_scan_skips_pycache(self):
        result = scan_directory(FIXTURE_DIR)
        for f in result.python_files:
            assert "__pycache__" not in f

    def test_scan_skips_venv(self):
        result = scan_directory(FIXTURE_DIR)
        for f in result.python_files:
            assert "venv" not in f

    def test_scan_skips_large_file(self):
        result = scan_directory(FIXTURE_DIR)
        for f in result.python_files:
            assert "large_file" not in f

    def test_scan_skips_binary(self):
        result = scan_directory(FIXTURE_DIR)
        for f in result.python_files:
            assert "binary" not in f

    def test_scan_result_structure(self):
        result = scan_directory(FIXTURE_DIR)
        assert result.root_path == os.path.abspath(FIXTURE_DIR)
        assert result.total_scanned > 0
        assert len(result.python_files) >= 7  # main, config, 3x __init__, helpers, user
        assert any(s for s in result.skipped if "过大" in s["reason"])

    def test_invalid_path_raises(self):
        with pytest.raises(NotADirectoryError):
            scan_directory("/nonexistent/path/to/nowhere")

    def test_custom_max_size(self):
        config = ScannerConfig(max_file_size_kb=10)
        result = scan_directory(FIXTURE_DIR, config)
        # large_file.py 会被跳过，其他 Python 文件正常扫描
        assert len(result.python_files) >= 7

    def test_extra_skip_dirs(self):
        config = ScannerConfig(extra_skip_dirs={"utils"})
        result = scan_directory(FIXTURE_DIR, config)
        for f in result.python_files:
            assert "utils" not in f

    def test_all_skipped_have_reason(self):
        result = scan_directory(FIXTURE_DIR)
        for s in result.skipped:
            assert "path" in s
            assert "reason" in s
            assert s["reason"] != ""
