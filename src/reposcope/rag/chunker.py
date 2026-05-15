"""AST 代码切块 — 将 Python 文件按函数、类、方法切分为可检索的代码片段。

非 Python 文件（README、YAML、TOML 等）按整个文件切块。
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field


@dataclass
class CodeChunk:
    """单个代码片段。"""

    file: str            # 文件绝对路径
    name: str            # 函数/类/方法名（文件级为文件名）
    type: str            # "function" | "class" | "method" | "module" | "config"
    line_start: int
    line_end: int
    code: str            # 原始代码文本
    docstring: str       # 文档字符串（如有）
    signature: str       # 函数/类签名（如 def foo(x, y):）


@dataclass
class ChunkResults:
    """切块结果汇总。"""

    chunks: list[CodeChunk]
    total_files: int
    total_chunks: int


# ---------------------------------------------------------------------------
# 切块入口
# ---------------------------------------------------------------------------

CONFIG_EXTENSIONS = {".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".md", ".rst", ".txt"}


def find_config_files(root_path: str) -> list[str]:
    """在仓库根目录下查找配置文件（README、YAML、TOML 等）。

    Scanner 只返回 .py 文件，这些非 Python 文件需单独收集用于代码索引。
    """
    import os
    results: list[str] = []
    try:
        for entry in os.listdir(root_path):
            full = os.path.join(root_path, entry)
            if os.path.isfile(full):
                ext = os.path.splitext(entry)[1].lower()
                if ext in CONFIG_EXTENSIONS:
                    results.append(full)
    except OSError:
        pass
    return sorted(results)


def chunk_files(filepaths: list[str]) -> ChunkResults:
    """对文件列表进行 AST 切块。

    非 .py 文件作为整体模块级 chunk。
    """
    all_chunks: list[CodeChunk] = []
    for fp in filepaths:
        all_chunks.extend(_chunk_file(fp))
    return ChunkResults(
        chunks=all_chunks,
        total_files=len(filepaths),
        total_chunks=len(all_chunks),
    )


def _chunk_file(filepath: str) -> list[CodeChunk]:
    """单个文件切块。"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext != ".py":
        return _chunk_non_python(filepath, ext)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return _chunk_non_python(filepath, ext)

    chunks: list[CodeChunk] = []

    # 模块级 docstring
    module_doc = ast.get_docstring(tree) or ""

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            chunks.extend(_chunk_function(node, filepath, source, is_method=False))
        elif isinstance(node, ast.AsyncFunctionDef):
            chunks.extend(_chunk_function(node, filepath, source, is_method=False))
        elif isinstance(node, ast.ClassDef):
            chunks.append(_chunk_class(node, filepath, source))
            # 类方法
            for body_node in node.body:
                if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    chunks.extend(_chunk_function(
                        body_node, filepath, source,
                        is_method=True, class_name=node.name,
                    ))

    # 如果没有任何顶层定义，添加模块级 chunk
    if not chunks and source.strip():
        basename = os.path.basename(filepath)
        chunks.append(CodeChunk(
            file=filepath,
            name=os.path.splitext(basename)[0],
            type="module",
            line_start=1,
            line_end=len(source.splitlines()),
            code=source,
            docstring=module_doc,
            signature=f"# {basename}",
        ))

    return chunks


def _chunk_non_python(filepath: str, ext: str) -> list[CodeChunk]:
    """非 Python 文件作为整体 chunk。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except (UnicodeDecodeError, OSError):
        return []

    basename = os.path.basename(filepath)
    chunk_type = "config" if ext in {".yaml", ".yml", ".json", ".toml", ".cfg", ".ini"} else "module"

    return [CodeChunk(
        file=filepath,
        name=os.path.splitext(basename)[0],
        type=chunk_type,
        line_start=1,
        line_end=len(source.splitlines()),
        code=source,
        docstring="",
        signature=f"# {basename}",
    )]


# ---------------------------------------------------------------------------
# 函数 / 类切块
# ---------------------------------------------------------------------------

def _chunk_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    filepath: str,
    source: str,
    is_method: bool = False,
    class_name: str = "",
) -> list[CodeChunk]:
    """函数/方法 → CodeChunk。"""
    lines = source.splitlines()
    start = node.lineno
    end = (node.end_lineno or start)
    code = "\n".join(lines[start - 1:end])
    doc = ast.get_docstring(node) or ""

    # 签名
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args_str = _format_args(node)
    sig = f"{prefix} {node.name}({args_str}):"

    name = f"{class_name}.{node.name}" if is_method and class_name else node.name

    return [CodeChunk(
        file=filepath,
        name=name,
        type="method" if is_method else "function",
        line_start=start,
        line_end=end,
        code=code,
        docstring=doc,
        signature=sig,
    )]


def _chunk_class(node: ast.ClassDef, filepath: str, source: str) -> CodeChunk:
    """类 → CodeChunk。"""
    lines = source.splitlines()
    start = node.lineno
    end = (node.end_lineno or start)
    code = "\n".join(lines[start - 1:end])
    doc = ast.get_docstring(node) or ""

    bases = [ast.unparse(b) if hasattr(ast, "unparse") else _name_of(b) for b in node.bases]
    sig = f"class {node.name}({', '.join(bases)}):" if bases else f"class {node.name}:"

    return CodeChunk(
        file=filepath,
        name=node.name,
        type="class",
        line_start=start,
        line_end=end,
        code=code,
        docstring=doc,
        signature=sig,
    )


def _format_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """格式化函数参数列表。"""
    parts = []
    for arg in node.args.args:
        parts.append(arg.arg)
    if node.args.vararg:
        parts.append(f"*{node.args.vararg.arg}")
    if node.args.kwonlyargs:
        for arg in node.args.kwonlyargs:
            parts.append(arg.arg)
    if node.args.kwarg:
        parts.append(f"**{node.args.kwarg.arg}")
    return ", ".join(parts)


def _name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name_of(node.value)}.{node.attr}"
    return "?"
