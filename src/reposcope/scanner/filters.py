"""目录和文件的过滤规则。

所有函数都是确定性的，不依赖 LLM。
"""

from __future__ import annotations

import os

DEFAULT_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
    "venv",
    ".venv",
    "env",
    ".env",
    ".tox",
    ".eggs",
    "build",
    "dist",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "egg-info",
    "__pypackages__",
}

PYTHON_EXTENSIONS = {".py"}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".mp3", ".mp4", ".avi", ".mov",
    ".o", ".a", ".lib", ".obj",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat",
}

DEFAULT_MAX_FILE_SIZE_KB = 500


def should_skip_directory(dirname: str, extra_skip: set | None = None) -> bool:
    """判断目录是否应被跳过。"""
    skip = DEFAULT_SKIP_DIRS.copy()
    if extra_skip:
        skip.update(extra_skip)
    return dirname in skip or dirname.startswith(".")


def should_skip_file(
    filepath: str,
    file_size: int | None = None,
    max_size_kb: int = DEFAULT_MAX_FILE_SIZE_KB,
) -> tuple[bool, str]:
    """判断文件是否应被跳过。返回 (是否跳过, 原因)。"""
    _, ext = os.path.splitext(filepath)

    if ext.lower() in SKIP_EXTENSIONS:
        return True, f"非 Python 文件类型: {ext}"
    if ext.lower() == "":
        return True, "无扩展名，疑似二进制文件"
    if ext.lower() not in PYTHON_EXTENSIONS:
        return True, f"非 .py 文件: {ext}"

    if file_size is not None and file_size > max_size_kb * 1024:
        return True, f"文件过大 ({file_size / 1024:.0f}KB > {max_size_kb}KB)"

    return False, ""
