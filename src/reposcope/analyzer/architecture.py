"""架构特征提取 — 循环依赖检测、拓扑分层、模块角色分类。"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from reposcope.graph.import_graph import ImportGraph
from reposcope.parser.ast_extractor import FileASTResult


@dataclass
class ArchitectureProfile:
    """项目架构画像。"""

    module_count: int
    edge_count: int
    is_dag: bool
    circular_deps: list[list[str]]
    depth: int                       # 拓扑层数
    layers: list[list[str]]          # 从外到内的拓扑层
    categories: dict[str, str]       # module → category
    entry_points: list[str]          # 带 main_guard 的模块
    root_modules: list[str]          # 无入边的模块
    leaf_modules: list[str]          # 无出边的模块


# ---------------------------------------------------------------------------
# 架构画像入口
# ---------------------------------------------------------------------------

def profile_architecture(
    graph: ImportGraph,
    ast_results: list[FileASTResult],
) -> ArchitectureProfile:
    """生成项目的架构画像。"""
    g = graph.graph

    # 建立 module → FileASTResult 索引
    ast_by_module: dict[str, FileASTResult] = {}
    for r in ast_results:
        m = graph.get_module(r.file)
        if m is not None:
            ast_by_module[m] = r

    circular = detect_circular_deps(graph)
    layers = compute_layers(graph)
    categories = categorize_modules(graph, ast_by_module)

    entry_points = sorted(
        n for n in g.nodes if g.nodes[n].get("has_main_guard")
    )
    root_modules = sorted(n for n in g.nodes if g.in_degree(n) == 0)
    leaf_modules = sorted(n for n in g.nodes if g.out_degree(n) == 0)

    return ArchitectureProfile(
        module_count=g.number_of_nodes(),
        edge_count=g.number_of_edges(),
        is_dag=len(circular) == 0,
        circular_deps=circular,
        depth=len(layers),
        layers=layers,
        categories=categories,
        entry_points=entry_points,
        root_modules=root_modules,
        leaf_modules=leaf_modules,
    )


# ---------------------------------------------------------------------------
# 循环依赖检测
# ---------------------------------------------------------------------------

def detect_circular_deps(graph: ImportGraph) -> list[list[str]]:
    """检测项目中的循环依赖。

    使用 networkx 的 simple_cycles 算法，返回所有简单环。
    """
    g = graph.graph
    try:
        cycles = list(nx.simple_cycles(g))
    except Exception:
        return []
    # 按环长度排序，便于阅读
    cycles.sort(key=len)
    return cycles


# ---------------------------------------------------------------------------
# 拓扑分层
# ---------------------------------------------------------------------------

def compute_layers(graph: ImportGraph) -> list[list[str]]:
    """将模块按拓扑层级分组。

    Layer 0: 不依赖任何内部模块的模块（最外层）
    Layer N: 依赖链最深层的模块

    有环图会先被破环处理。
    """
    g = graph.graph.copy()
    layers: list[list[str]] = []

    remaining = set(g.nodes)
    while remaining:
        # 找到当前无入边的节点
        layer = sorted(
            n for n in remaining if g.in_degree(n) == 0
        )
        if not layer:
            # 存在环：选入度最小的节点强制放入当前层以打破僵局
            min_in = min(g.in_degree(n) for n in remaining)
            layer = sorted(n for n in remaining if g.in_degree(n) == min_in)
        layers.append(layer)
        remaining -= set(layer)
        g.remove_nodes_from(layer)

    return layers


# ---------------------------------------------------------------------------
# 模块角色分类
# ---------------------------------------------------------------------------

def categorize_modules(
    graph: ImportGraph,
    ast_by_module: dict[str, FileASTResult],
) -> dict[str, str]:
    """为每个模块分配一个角色标签。

    分类规则（按优先级）：
      entry         — 有 main_guard
      config        — 无 class、无 function、无内部依赖
      model         — 定义了 class
      utility       — 被 2+ 模块依赖，定义了 function，出度低
      package_init  — 文件名为 __init__.py
      orchestrator  — 出度 >= 2 且在前 25%
      leaf          — 无内部依赖
      module        — 以上都不符合（兜底）
    """
    g = graph.graph
    if g.number_of_nodes() == 0:
        return {}

    out_degrees = sorted(g.out_degree(n) for n in g.nodes)
    high_out_threshold = _percentile(out_degrees, 75) if out_degrees else 0

    result: dict[str, str] = {}
    for node in g.nodes:
        attrs = g.nodes[node]
        filepath = attrs.get("file_path", "")
        classes = attrs.get("classes", [])
        functions = attrs.get("functions", [])
        in_deg = g.in_degree(node)
        out_deg = g.out_degree(node)

        if attrs.get("has_main_guard"):
            result[node] = "entry"
        elif not classes and not functions and out_deg == 0:
            result[node] = "config"
        elif classes:
            result[node] = "model"
        elif functions and in_deg >= 2 and out_deg <= 1:
            result[node] = "utility"
        elif _is_init_file(filepath):
            result[node] = "package_init"
        elif out_deg >= max(high_out_threshold, 2) and high_out_threshold > 0:
            result[node] = "orchestrator"
        elif out_deg == 0:
            result[node] = "leaf"
        else:
            result[node] = "module"

    return result


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list, pct: int) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


def _is_init_file(filepath: str) -> bool:
    """判断文件是否为 __init__.py。"""
    import os
    return os.path.basename(filepath) == "__init__.py"
