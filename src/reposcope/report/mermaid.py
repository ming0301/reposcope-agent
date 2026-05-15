"""Mermaid 依赖图生成 — 将 import graph 渲染为 Mermaid flowchart 语法。

生成的 .mmd 文本可直接粘贴到 https://mermaid.live 查看，或在支持
Mermaid 的 Markdown 渲染器中展示。
"""

from __future__ import annotations

import os

import networkx as nx

from reposcope.graph.import_graph import ImportGraph
from reposcope.storage.repo_summary import RepoSummary, reconstruct_graph


# 节点样式（按模块角色分类）
_CATEGORY_STYLE: dict[str, str] = {
    "entry":          "fill:#ffcccc,stroke:#cc0000,stroke-width:2px,color:#000",
    "orchestrator":   "fill:#cce5ff,stroke:#004085,stroke-width:2px,color:#000",
    "model":          "fill:#d4edda,stroke:#155724,color:#000",
    "utility":        "fill:#fff3cd,stroke:#856404,color:#000",
    "package_init":   "fill:#e2e3e5,stroke:#383d41,stroke-dasharray:5,color:#000",
    "config":         "fill:#f8f9fa,stroke:#6c757d,color:#000",
    "leaf":           "fill:#f8f9fa,stroke:#6c757d,color:#000",
}

_DEFAULT_STYLE = "fill:#f8f9fa,stroke:#6c757d,color:#000"


def _node_id(module_path: str) -> str:
    """将模块路径转为合法的 Mermaid 节点 ID。"""
    if not module_path:
        return "ROOT_INIT"
    return module_path.replace(".", "_").replace("-", "_")


def _node_label(module_path: str) -> str:
    """节点显示标签。"""
    if not module_path:
        return "(根 __init__.py)"
    return module_path


def generate_mermaid(
    graph_or_summary: ImportGraph | RepoSummary,
    *,
    direction: str = "TD",
    title: str | None = None,
    module_categories: dict[str, str] | None = None,
) -> str:
    """生成 Mermaid flowchart 语法。

    Args:
        graph_or_summary: ImportGraph 或 RepoSummary（自动提取图）
        direction: 布局方向，TD（上→下）或 LR（左→右）
        title: 可选图表标题
        module_categories: 模块角色分类 {module_path: category}，用于着色

    Returns:
        Mermaid flowchart 语法的完整字符串
    """
    if isinstance(graph_or_summary, RepoSummary):
        g = reconstruct_graph(graph_or_summary)
        cats = graph_or_summary.module_categories
    else:
        g = graph_or_summary.graph
        cats = module_categories or {}

    lines: list[str] = []
    lines.append(f"flowchart {direction}")

    if title:
        safe_title = title.replace('"', "'")
        lines.append(f'  title["{safe_title}"]')
        lines.append("")

    # 定义样式类
    defined_styles: set[str] = set()
    for cat, style in _CATEGORY_STYLE.items():
        if any(cats.get(n) == cat for n in g.nodes):
            lines.append(f"  classDef {cat} {style}")
            defined_styles.add(cat)

    if defined_styles:
        lines.append("")

    # 节点（按拓扑顺序排列便于阅读）
    nodes_sorted = _topological_order(g)
    for i, node in enumerate(nodes_sorted):
        nid = _node_id(node)
        label = _node_label(node)
        # 转义标签中的引号
        safe_label = label.replace('"', "'")
        lines.append(f'  {nid}["{safe_label}"]')

    if nodes_sorted:
        lines.append("")

    # 边
    for u, v in g.edges:
        uid = _node_id(u)
        vid = _node_id(v)
        lines.append(f"  {uid} --> {vid}")

    if g.edges:
        lines.append("")

    # 应用样式
    for node in nodes_sorted:
        cat = cats.get(node, "")
        if cat in defined_styles:
            lines.append(f"  class {_node_id(node)} {cat};")

    return "\n".join(lines)


def _topological_order(g: nx.DiGraph) -> list[str]:
    """返回节点的拓扑排序（用于 Mermaid 节点声明的阅读顺序）。"""
    try:
        return list(nx.topological_sort(g))
    except nx.NetworkXUnfeasible:
        return sorted(g.nodes)


def save_mermaid_file(
    output: str,
    graph_or_summary: ImportGraph | RepoSummary,
    *,
    direction: str = "TD",
    title: str | None = None,
) -> str:
    """生成 Mermaid 语法并保存为 .mmd 文件。

    Returns:
        写入的文件路径
    """
    content = generate_mermaid(
        graph_or_summary,
        direction=direction,
        title=title,
    )
    # 确保以 .mmd 结尾
    if not output.endswith(".mmd"):
        output += ".mmd"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(content)
    return output
