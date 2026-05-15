"""Source Reader — 按需读取源码文件的指定行范围。

用于在检索到相关代码 chunk 后，读取上下文（前后 N 行）或完整文件。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SourceSnippet:
    """源码片段。"""

    file: str
    line_start: int
    line_end: int
    code: str
    language: str  # "python" | "yaml" | "json" | "markdown" | "text"


def read_file(filepath: str) -> SourceSnippet | None:
    """读取整个文件。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except (UnicodeDecodeError, OSError):
        return None

    lines = source.splitlines()
    return SourceSnippet(
        file=filepath,
        line_start=1,
        line_end=len(lines),
        code=source,
        language=_detect_language(filepath),
    )


def read_lines(
    filepath: str,
    start: int,
    end: int,
    context: int = 0,
) -> SourceSnippet | None:
    """读取文件的指定行范围，可选附加上下文行。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except (UnicodeDecodeError, OSError):
        return None

    total = len(all_lines)
    ctx_start = max(1, start - context)
    ctx_end = min(total, end + context)

    # 标记原始范围
    selected_lines: list[str] = []
    for i in range(ctx_start - 1, ctx_end):
        line_no = i + 1
        prefix = "  " if context > 0 and (line_no < start or line_no > end) else "> "
        selected_lines.append(f"{prefix}{all_lines[i].rstrip()}")

    return SourceSnippet(
        file=filepath,
        line_start=ctx_start,
        line_end=ctx_end,
        code="\n".join(selected_lines),
        language=_detect_language(filepath),
    )


def read_config_files(filepaths: list[str]) -> list[SourceSnippet]:
    """批量读取配置文件（README、YAML、TOML、JSON 等）。"""
    config_exts = {".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".md", ".rst", ".txt"}
    snippets: list[SourceSnippet] = []
    for fp in filepaths:
        import os
        ext = os.path.splitext(fp)[1].lower()
        if ext in config_exts:
            snippet = read_file(fp)
            if snippet:
                snippets.append(snippet)
    return snippets


def _detect_language(filepath: str) -> str:
    import os
    ext = os.path.splitext(filepath)[1].lower()
    mapping = {
        ".py": "python", ".yaml": "yaml", ".yml": "yaml",
        ".json": "json", ".toml": "toml", ".cfg": "text",
        ".ini": "text", ".md": "markdown", ".rst": "markdown",
    }
    return mapping.get(ext, "text")
