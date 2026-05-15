"""
AST 提取器 — 使用 Python ast 标准库提取代码结构。

提取每个 .py 文件中的 import、class、function、main guard。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class ASTItem:
    """单个 AST 提取项。"""

    file: str
    line: int
    name: str
    type: str  # "import" | "class" | "function" | "main_guard"
    module: str | None = None   # import 来源模块（仅 import 类型）
    level: int | None = None    # 相对导入层级（仅 import 类型）


@dataclass
class FileASTResult:
    """单个文件的 AST 提取结果。"""

    file: str
    imports: list[ASTItem] = field(default_factory=list)
    classes: list[ASTItem] = field(default_factory=list)
    functions: list[ASTItem] = field(default_factory=list)
    main_guard: ASTItem | None = None


class ASTExtractor:
    """从 Python 文件中提取代码结构。"""

    def extract(self, filepath: str) -> FileASTResult:
        """解析单个 Python 文件，返回其结构信息。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
        except (UnicodeDecodeError, OSError):
            return FileASTResult(file=filepath)

        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            return FileASTResult(file=filepath)

        imports: list[ASTItem] = []
        classes: list[ASTItem] = []
        functions: list[ASTItem] = []
        main_guard: ASTItem | None = None

        for node in ast.iter_child_nodes(tree):
            items = self._process_stmt(node, filepath)
            for item in items:
                if item.type == "import":
                    imports.append(item)
                elif item.type == "class":
                    classes.append(item)
                elif item.type == "function":
                    functions.append(item)
                elif item.type == "main_guard":
                    main_guard = item

        return FileASTResult(
            file=filepath,
            imports=imports,
            classes=classes,
            functions=functions,
            main_guard=main_guard,
        )

    def extract_all(self, filepaths: list[str]) -> list[FileASTResult]:
        """批量提取多个文件的结构信息。"""
        return [self.extract(fp) for fp in filepaths]

    def _process_stmt(self, node: ast.stmt, filepath: str) -> list[ASTItem]:
        """处理单个顶层语句节点，返回提取项列表。"""
        if isinstance(node, ast.Import):
            return self._handle_import(node, filepath)
        if isinstance(node, ast.ImportFrom):
            return self._handle_import_from(node, filepath)
        if isinstance(node, ast.ClassDef):
            return [self._handle_class(node, filepath)]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [self._handle_function(node, filepath)]
        if isinstance(node, ast.If):
            item = self._handle_main_guard(node, filepath)
            return [item] if item else []
        return []

    def _handle_import(self, node: ast.Import, filepath: str) -> list[ASTItem]:
        """处理 `import X` / `import X as Y` 语句。

        一个 import 语句可能导入多个模块（如 `import os, sys`），
        展开为多个 ASTItem。
        """
        return [
            ASTItem(
                file=filepath,
                line=node.lineno,
                name=alias.asname or alias.name,
                type="import",
                module=alias.name,
                level=0,
            )
            for alias in node.names
        ]

    def _handle_import_from(self, node: ast.ImportFrom, filepath: str) -> list[ASTItem]:
        """处理 `from X import Y` / `from .X import Y` 语句。

        一个 from-import 语句可能导入多个名称（如 `from os import path, join`），
        展开为多个 ASTItem。
        """
        return [
            ASTItem(
                file=filepath,
                line=node.lineno,
                name=alias.asname or alias.name,
                type="import",
                module=node.module or "",
                level=node.level,
            )
            for alias in node.names
        ]

    def _handle_class(self, node: ast.ClassDef, filepath: str) -> ASTItem:
        return ASTItem(
            file=filepath,
            line=node.lineno,
            name=node.name,
            type="class",
        )

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, filepath: str) -> ASTItem:
        return ASTItem(
            file=filepath,
            line=node.lineno,
            name=node.name,
            type="function",
        )

    def _handle_main_guard(self, node: ast.If, filepath: str) -> ASTItem | None:
        """检测 `if __name__ == "__main__":` 模式。"""
        if not isinstance(node.test, ast.Compare):
            return None
        if len(node.test.ops) != 1:
            return None
        if not isinstance(node.test.ops[0], ast.Eq):
            return None

        left = node.test.left
        if not (isinstance(left, ast.Name) and left.id == "__name__"):
            return None

        right = node.test.comparators[0]
        if not (isinstance(right, ast.Constant) and right.value == "__main__"):
            return None

        return ASTItem(
            file=filepath,
            line=node.lineno,
            name="__main__",
            type="main_guard",
        )
