"""

入口检测与核心模块排序。

基于图结构和 AST 元数据，识别：
  - 候选入口文件（main guard、根模块、高扇出模块）
  - 核心模块（高被依赖、高介数中心性、高 PageRank）
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from reposcope.graph.import_graph import ImportGraph
from reposcope.parser.ast_extractor import FileASTResult


@dataclass
class EntryCandidate:
    """候选入口模块。"""

    module: str
    file: str
    score: float          # 0.0 ~ 1.0，综合得分
    signals: list[str]    # 命中信号列表


@dataclass
class CoreModuleCandidate:
    """核心模块候选。"""

    module: str
    file: str
    score: float          # 0.0 ~ 1.0，综合重要性得分
    in_degree: int        # 被依赖次数
    out_degree: int       # 依赖他人次数
    betweenness: float    # 介数中心性
    pagerank: float       # PageRank 值


# ---------------------------------------------------------------------------
# 入口检测
# ---------------------------------------------------------------------------

def detect_entries(
    graph: ImportGraph,
    ast_results: list[FileASTResult],
) -> list[EntryCandidate]:
    """检测候选入口模块。

    信号与权重：
      - main_guard 存在：+0.40
      - 根模块（无入边）：+0.25
      - 高扇出（out-degree 在前 25%）：+0.20
      - 模块名含 "main"：+0.10
      - 叶模块且有函数定义（可能是脚本）：+0.05
    """
    g = graph.graph
    if g.number_of_nodes() == 0:
        return []

    candidates: dict[str, EntryCandidate] = {}

    # 预计算阈值
    out_degrees = [g.out_degree(n) for n in g.nodes]
    out_degrees.sort()
    high_out_threshold = _percentile(out_degrees, 75) if out_degrees else 0

    # 建立 module → FileASTResult 索引
    ast_by_module: dict[str, FileASTResult] = {}
    for r in ast_results:
        m = graph.get_module(r.file)
        if m is not None:
            ast_by_module[m] = r

    for node in g.nodes:
        # 跳过空模块名（根 __init__.py 无实际模块路径意义）
        if node == "":
            continue

        signals: list[str] = []
        score = 0.0

        # 信号 1：main_guard
        if g.nodes[node].get("has_main_guard"):
            signals.append("main_guard")
            score += 0.40

        # 信号 2：根模块 是否位于项目根层级
        if g.in_degree(node) == 0:
            signals.append("root_module")
            score += 0.25

        # 信号 3：高扇出 是否依赖很多模块
        if g.out_degree(node) >= high_out_threshold and high_out_threshold > 0:
            signals.append("high_out_degree")
            score += 0.20

        # 信号 4：模块名含 "main" 文件名是否包含 main
        if "main" in node.lower():
            signals.append("has_main_in_name")
            score += 0.10

        # 信号 5：叶模块 + 有函数定义 
        if g.out_degree(node) == 0:
            node_funcs = g.nodes[node].get("functions", [])
            if node_funcs:
                signals.append("leaf_with_functions")
                score += 0.05

        if signals:
            candidates[node] = EntryCandidate(
                module=node,
                file=g.nodes[node].get("file_path", ""),
                score=min(score, 1.0),
                signals=signals,
            )

    return sorted(candidates.values(), key=lambda c: c.score, reverse=True)


# ---------------------------------------------------------------------------
# 核心模块排序
#入度 in_degree：有多少模块依赖它
#介数中心性 betweenness：它是否处在依赖路径中间
#PageRank：它在整个依赖网络中的综合重要性
# ---------------------------------------------------------------------------

def rank_core_modules(graph: ImportGraph) -> list[CoreModuleCandidate]:
    """对模块做综合重要性排序。

    综合得分 = 0.40 * 归一化入度 + 0.30 * 介数中心性 + 0.30 * PageRank
    """
    g = graph.graph
    if g.number_of_nodes() == 0:
        return []

    # 入度归一化
    max_in = max((g.in_degree(n) for n in g.nodes), default=1)
    in_degree_norm: dict[str, float] = {}
    for n in g.nodes:
        in_degree_norm[n] = g.in_degree(n) / max_in if max_in > 0 else 0.0

    # 介数中心性
    try:
        betweenness = nx.betweenness_centrality(g, normalized=True)
    except Exception:
        betweenness = {n: 0.0 for n in g.nodes}

    # PageRank
    try:
        pagerank = nx.pagerank(g)
    except Exception:
        pagerank = {n: 0.0 for n in g.nodes}

    results: list[CoreModuleCandidate] = []
    for node in g.nodes:
        score = (
            0.40 * in_degree_norm[node]
            + 0.30 * betweenness[node]
            + 0.30 * pagerank[node]
        )
        results.append(CoreModuleCandidate(
            module=node,
            file=g.nodes[node].get("file_path", ""),
            score=round(score, 4),
            in_degree=g.in_degree(node),
            out_degree=g.out_degree(node),
            betweenness=round(betweenness[node], 4),
            pagerank=round(pagerank[node], 4),
        ))

    return sorted(results, key=lambda c: c.score, reverse=True)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list, pct: int) -> float:
    """计算百分位数（线性插值）。"""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])
