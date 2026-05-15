"""安全的 Python 文件扫描器。

遍历仓库目录，返回经过过滤的 Python 文件列表及跳过记录。
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field

from .filters import (
    DEFAULT_MAX_FILE_SIZE_KB,
    should_skip_directory,
    should_skip_file,
)


@dataclass
class ScannerConfig:
    """扫描配置。"""

    max_file_size_kb: int = DEFAULT_MAX_FILE_SIZE_KB
    extra_skip_dirs: set = field(default_factory=set)
    follow_symlinks: bool = False


@dataclass
class ScanResult:
    """扫描结果。"""

    root_path: str
    python_files: list[str]   # 通过过滤的 .py 文件绝对路径
    skipped: list[dict]       # 被跳过的文件及其原因
    total_scanned: int        # 遍历到的文件总数


def _is_symlink(path: str) -> bool:
    """判断是否符号链接（Windows 上可能是 junction）。"""
    try:
        return os.path.islink(path) or bool(os.stat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False


def scan_directory(root_path: str, config: ScannerConfig | None = None) -> ScanResult:
    """递归扫描仓库目录，返回过滤后的 Python 文件列表。"""
    if config is None:
        config = ScannerConfig()

    root_path = os.path.abspath(root_path)

    if not os.path.isdir(root_path):
        raise NotADirectoryError(f"路径不存在或不是目录: {root_path}")

    python_files: list[str] = []
    skipped: list[dict] = []
    total_scanned = 0

    #从 root_path 开始，递归遍历所有子目录和文件
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=config.follow_symlinks):
        # 就地过滤目录，避免进入跳过目录
        dirnames[:] = [
            d for d in dirnames
            if not should_skip_directory(d, config.extra_skip_dirs)
        ]

        # 跳过隐藏目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        for filename in filenames:
            total_scanned += 1
            filepath = os.path.join(dirpath, filename)

            # 跳过符号链接
            if _is_symlink(filepath):
                skipped.append({"path": filepath, "reason": "符号链接"})
                continue

            try:
                file_size = os.path.getsize(filepath)
            except OSError:
                skipped.append({"path": filepath, "reason": "无法读取文件信息"})
                continue

            skip, reason = should_skip_file(filepath, file_size, config.max_file_size_kb)
            if skip:
                skipped.append({"path": filepath, "reason": reason})
                continue

            python_files.append(filepath)

    return ScanResult(
        root_path=root_path,
        python_files=sorted(python_files),
        skipped=skipped,
        total_scanned=total_scanned,
    )
