"""

内部模块依赖图 — 基于 parser 输出的 internal import 构建有向图。

节点 = 项目内的 Python 模块（以 module_path 标识）
边   = 内部 import 关系（A 导入 B）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import networkx as nx

from reposcope.parser.ast_extractor import FileASTResult
from reposcope.parser.import_classifier import ClassificationResult, _module_path


@dataclass
class ImportGraph:
    """项目内部模块依赖图。

    封装 networkx.DiGraph，节点为模块路径字符串，边为 import 关系。
    """

    graph: nx.DiGraph
    root_path: str
    _module_to_file: dict[str, str] = field(default_factory=dict, repr=False)
    _file_to_module: dict[str, str] = field(default_factory=dict, repr=False)

    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def has_module(self, module_path: str) -> bool:
        return self.graph.has_node(module_path)

    def get_file(self, module_path: str) -> str | None:
        """根据模块路径反查文件绝对路径。"""
        return self._module_to_file.get(module_path)

    def get_module(self, filepath: str) -> str | None:
        """根据文件路径反查模块路径。"""
        return self._file_to_module.get(filepath)


def build_import_graph(
    ast_results: list[FileASTResult],
    classification_results: list[ClassificationResult],
    root_path: str,
) -> ImportGraph:
    """构建项目内部模块依赖图。

    Args:
        ast_results: ASTExtractor.extract_all() 的输出（提供节点元数据）
        classification_results: classify_imports() 的输出（提供内部 import 边）
        root_path: 项目根目录绝对路径

    Returns:
        ImportGraph：包含节点和边的依赖图
    """
    g = nx.DiGraph()
    module_to_file: dict[str, str] = {}
    file_to_module: dict[str, str] = {}

    # ---- 第 1 步：创建所有节点 ----
    for result in ast_results:
        module_path = _module_path(result.file, root_path)
        module_to_file[module_path] = result.file
        file_to_module[result.file] = module_path

        g.add_node(
            module_path,
            file_path=result.file,
            classes=[c.name for c in result.classes],
            functions=[f.name for f in result.functions],
            has_main_guard=result.main_guard is not None,
        )

    # ---- 第 2 步：按文件索引分类结果 ----
    classified_by_file: dict[str, ClassificationResult] = {
        cr.file: cr for cr in classification_results
    }

    # ---- 第 3 步：添加边（仅 internal import） ----
    for result in ast_results:
        source_module = file_to_module[result.file]
        cr = classified_by_file.get(result.file)
        if cr is None:
            continue

        for imp in cr.imports:
            if imp.category != "internal":
                continue
            target_module = imp.resolved_module
            if target_module not in module_to_file:
                continue

            g.add_edge(
                source_module,
                target_module,
                imported_name=imp.name,
                line=imp.line,
            )

    return ImportGraph(
        graph=g,
        root_path=root_path,
        _module_to_file=module_to_file,
        _file_to_module=file_to_module,
    )


# ---------------------------------------------------------------------------
# 图查询辅助函数
# ---------------------------------------------------------------------------


def get_entry_points(graph: ImportGraph) -> list[str]:
    """返回包含 main guard 的模块路径列表（潜在入口点）。"""
    result: list[str] = []
    for node in graph.graph.nodes:
        if graph.graph.nodes[node].get("has_main_guard"):
            result.append(node)
    return result


def get_dependencies(graph: ImportGraph, module_path: str) -> list[str]:
    """返回指定模块的所有内部依赖（该模块导入了哪些内部模块）。"""
    if not graph.graph.has_node(module_path):
        return []
    return sorted(graph.graph.successors(module_path))


def get_importers(graph: ImportGraph, module_path: str) -> list[str]:
    """返回导入了指定模块的所有内部模块（谁依赖了该模块）。"""
    if not graph.graph.has_node(module_path):
        return []
    return sorted(graph.graph.predecessors(module_path))


def get_leaf_modules(graph: ImportGraph) -> list[str]:
    """返回叶节点模块：不导入任何内部模块的模块。"""
    return sorted(
        node for node in graph.graph.nodes
        if graph.graph.out_degree(node) == 0
    )


def get_root_modules(graph: ImportGraph) -> list[str]:
    """返回根模块：没有被任何内部模块导入的模块。"""
    return sorted(
        node for node in graph.graph.nodes
        if graph.graph.in_degree(node) == 0
    )


def get_module_summary(graph: ImportGraph, module_path: str) -> dict | None:
    """返回单个模块的摘要信息。"""
    if not graph.graph.has_node(module_path):
        return None
    node = graph.graph.nodes[module_path]
    return {
        "module": module_path,
        "file": node.get("file_path", ""),
        "classes": node.get("classes", []),
        "functions": node.get("functions", []),
        "has_main_guard": node.get("has_main_guard", False),
        "dependencies": get_dependencies(graph, module_path),
        "imported_by": get_importers(graph, module_path),
    }
