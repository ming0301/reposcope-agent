"""模块级流程追踪 — 基于 import graph + Code RAG 的结构推断。

核心思路：
  1. 在 import graph 中查找 source → target 的模块依赖路径
  2. 对路径上的每个模块检索关键函数/类/方法
  3. 将路径和代码证据组装为 LLM prompt，生成流程解释

边界声明（重要）：
  - 这是基于静态 import graph 和代码检索的"结构推断"
  - import graph 的边 = "模块 A 导入了模块 B 的某些符号"，不等于 A 一定调用了 B
  - 不等同于真实运行时调用顺序
  - 不做函数体 AST 级别 Call 解析，不做跨文件调用图
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import networkx as nx

from reposcope.storage.repo_summary import RepoSummary, reconstruct_graph


@dataclass
class FlowPath:
    """一条模块依赖路径。"""

    modules: list[str]          # 路径上的模块名列表
    length: int                 # 路径长度（边数）


@dataclass
class ModuleEvidence:
    """路径上一个模块的代码证据。"""

    module: str
    key_functions: list[str]    # 关键函数/类名 + file:line
    top_chunks: list[dict]      # 检索到的代码片段摘要


@dataclass
class FlowTraceResult:
    """流程追踪结果。"""

    question: str
    source: str | None
    target: str | None
    paths: list[FlowPath]
    evidence: dict[str, ModuleEvidence]  # module → evidence
    explanation: str                     # LLM 生成的解释文本
    disclaimer: str                      # 边界声明


# ---- 边界声明（所有输出必须包含） ----
_BOUNDARY_DISCLAIMER = (
    "[重要说明] 以上流程是基于静态 import 依赖图的结构推断，"
    "不代表真实运行时函数调用顺序。import graph 中的边表示"
    "模块间存在导入关系（如 A 导入了 B 的某些符号），"
    "不精确证明 A 中的某函数一定会调用 B 中的某函数。"
    "如需精确调用链，需做 AST 函数体级别的 Call 解析。"
)


# ---------------------------------------------------------------------------
# Step 1: 从问题中提取 source / target
# ---------------------------------------------------------------------------

def _extract_endpoints(question: str, all_modules: set[str]) -> tuple[str | None, str | None]:
    """从自然语言问题中提取 source 和 target 模块名。

    支持模式：
      - "从 X 到 Y"
      - "X to Y" / "X → Y"
      - "X 和 Y 之间"
    """
    patterns = [
        r"(?:从|from)\s+`?([a-zA-Z_][a-zA-Z0-9_.]*)`?\s*(?:到|to|→)\s*`?([a-zA-Z_][a-zA-Z0-9_.]*)`?",
        r"`?([a-zA-Z_][a-zA-Z0-9_.]*)`?\s*(?:和|and)\s*`?([a-zA-Z_][a-zA-Z0-9_.]*)`?\s*(?:之间|的|关系|连接)",
        r"`?([a-zA-Z_][a-zA-Z0-9_.]*)`?\s*→\s*`?([a-zA-Z_][a-zA-Z0-9_.]*)`?",
    ]
    for pat in patterns:
        m = re.search(pat, question, re.IGNORECASE)
        if m:
            src, tgt = m.group(1), m.group(2)
            # 验证是否为已知模块
            if src in all_modules and tgt in all_modules:
                return src, tgt
            # 模糊匹配：尝试在已知模块中找到包含该名称的模块
            src_match = _fuzzy_match_module(src, all_modules)
            tgt_match = _fuzzy_match_module(tgt, all_modules)
            if src_match and tgt_match:
                return src_match, tgt_match
    return None, None


def _fuzzy_match_module(hint: str, modules: set[str]) -> str | None:
    """模糊匹配模块名：精确匹配 > 后缀匹配 > 包含匹配。"""
    if hint in modules:
        return hint
    for m in modules:
        if m.endswith("." + hint) or m == hint:
            return m
    for m in modules:
        if hint in m:
            return m
    return None


# ---------------------------------------------------------------------------
# Step 2: 在 import graph 中查找路径
# ---------------------------------------------------------------------------

def find_paths(
    graph: nx.DiGraph,
    source: str,
    target: str,
    max_depth: int = 5,
    max_paths: int = 3,
) -> list[FlowPath]:
    """在 import graph 中查找 source → target 的所有简单路径。

    Args:
        graph: 模块依赖图（DiGraph）
        source: 起始模块名
        target: 目标模块名
        max_depth: 最大路径长度（边数）
        max_paths: 最多返回路径数

    Returns:
        FlowPath 列表，按长度升序（最短路径优先）
    """
    if not graph.has_node(source) or not graph.has_node(target):
        return []

    try:
        raw_paths = list(nx.all_simple_paths(
            graph, source=source, target=target, cutoff=max_depth,
        ))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    # 按长度排序，取最短的几条
    raw_paths.sort(key=len)
    return [
        FlowPath(modules=path, length=len(path) - 1)
        for path in raw_paths[:max_paths]
    ]


# ---------------------------------------------------------------------------
# Step 3: 收集路径上各模块的代码证据
# ---------------------------------------------------------------------------

def collect_evidence(
    paths: list[FlowPath],
    index,  # CodeIndex | EmbeddingIndex（只要实现了 search_by_name 即可）
) -> dict[str, ModuleEvidence]:
    """对路径上的每个模块，检索其关键函数/类。

    Args:
        paths: 找到的模块路径
        index: 代码索引（CodeIndex 或 EmbeddingIndex）

    Returns:
        {module: ModuleEvidence} 映射
    """
    # 收集路径上所有唯一模块
    all_modules: set[str] = set()
    for path in paths:
        all_modules.update(path.modules)

    evidence: dict[str, ModuleEvidence] = {}

    for module in all_modules:
        # 检索该模块的 class 定义
        classes = index.search_by_name(module.split(".")[-1], chunk_types=["class"])

        # 检索该模块的顶层 function
        funcs = index.search_by_name(module.split(".")[-1], chunk_types=["function"])

        # 取模块名对应的文件
        file_chunks = index.get_chunks_by_file("")  # 后续通过 file 匹配
        # 更直接：从 search_by_name 的 chunks 中筛选属于该 module 的
        key_items: list[str] = []
        top_chunks: list[dict] = []

        all_hits = classes[:2] + funcs[:2]
        seen = set()
        for c in all_hits:
            cid = f"{c.name}:{c.file}"
            if cid in seen:
                continue
            seen.add(cid)

            # 验证 chunk 确实属于这个模块
            chunk_module = _file_to_module_hint(c.file, module)
            if chunk_module:
                key_items.append(f"{c.type} `{c.name}` ({_short_file(c.file)}:{c.line_start})")
                top_chunks.append({
                    "name": c.name,
                    "type": c.type,
                    "file": c.file,
                    "line": c.line_start,
                    "signature": c.signature[:120],
                })

        if key_items:
            evidence[module] = ModuleEvidence(
                module=module,
                key_functions=key_items,
                top_chunks=top_chunks,
            )

    return evidence


def _file_to_module_hint(filepath: str, module_hint: str) -> bool:
    """检查 filepath 是否大致属于 module_hint。"""
    import os
    basename = os.path.splitext(os.path.basename(filepath))[0]
    module_last = module_hint.split(".")[-1]
    return basename == module_last or module_hint.replace(".", os.sep) in filepath


def _short_file(filepath: str) -> str:
    import os
    parts = filepath.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]


# ---------------------------------------------------------------------------
# Step 4: 组装 LLM prompt
# ---------------------------------------------------------------------------

def build_flow_prompt(
    question: str,
    paths: list[FlowPath],
    evidence: dict[str, ModuleEvidence],
    summary: RepoSummary,
) -> str:
    """组装流程解释 prompt。"""
    parts: list[str] = []

    parts.append("## 任务：基于模块依赖关系推断项目流程")
    parts.append("")
    parts.append("用户问题：" + question)
    parts.append("")

    # 找到的路径
    parts.append(f"## 在 import 依赖图中找到 {len(paths)} 条候选路径")
    parts.append("（边的含义：模块 A 导入了模块 B 的某些符号）")
    parts.append("")
    for i, path in enumerate(paths, 1):
        chain = " → ".join(path.modules)
        parts.append(f"  路径 {i} (长度={path.length}): {chain}")
    parts.append("")

    # 代码证据
    if evidence:
        parts.append("## 路径上各模块的关键代码")
        parts.append("（通过代码检索获得，用于理解每个模块的职责）")
        parts.append("")
        for module, ev in evidence.items():
            parts.append(f"### {module}")
            for item in ev.key_functions:
                parts.append(f"  - {item}")
            parts.append("")

    # 边界声明
    parts.append("## 重要约束")
    parts.append(_BOUNDARY_DISCLAIMER)
    parts.append("")

    # 回答指令
    parts.append("## 回答要求")
    parts.append("1. 基于上面的 import 路径和代码证据，用中文解释可能的执行流程。")
    parts.append("2. 明确说明这是基于静态 import 结构的推断，不代表运行时调用顺序。")
    parts.append("3. 如果有多条路径，说明哪条最短/最常见。")
    parts.append("4. 引用具体的文件名和函数名作为证据。")
    parts.append("5. 如果路径不完整或证据不足，诚实说明。")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Step 5: 完整流程追踪
# ---------------------------------------------------------------------------

def trace_flow(
    question: str,
    index,  # CodeIndex | EmbeddingIndex
    summary: RepoSummary,
    *,
    api_key: str | None = None,
    model: str = "claude-sonnet-4-6",
    max_depth: int = 5,
) -> FlowTraceResult:
    """执行完整的模块级流程追踪。

    1. 从问题中提取 source/target
    2. 在 import graph 中找路径
    3. 收集路径上的代码证据
    4. 调用 LLM 生成解释
    """
    import os
    g = reconstruct_graph(summary)
    all_modules = set(summary.module_categories.keys())

    # Step 1: 提取端点
    source, target = _extract_endpoints(question, all_modules)

    # Step 2: 找路径
    paths: list[FlowPath] = []
    if source and target:
        paths = find_paths(g, source, target, max_depth=max_depth)

    # Step 3: 收集证据
    evidence: dict[str, ModuleEvidence] = {}
    if paths:
        evidence = collect_evidence(paths, index)

    # Step 4: LLM 生成解释
    api_key = api_key or os.environ.get("REPOSCOPE_API_KEY")
    if api_key and paths:
        try:
            import anthropic
            prompt = build_flow_prompt(question, paths, evidence, summary)
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system="你是一个 Python 项目结构分析助手。请基于模块依赖路径和代码证据，帮助用户理解项目的执行流程。",
                messages=[{"role": "user", "content": prompt}],
            )
            explanation = "\n".join(
                block.text for block in response.content if hasattr(block, "text")
            )
        except Exception:
            explanation = _build_deterministic_explanation(question, paths, evidence)
    else:
        explanation = _build_deterministic_explanation(question, paths, evidence)

    return FlowTraceResult(
        question=question,
        source=source,
        target=target,
        paths=paths,
        evidence=evidence,
        explanation=explanation,
        disclaimer=_BOUNDARY_DISCLAIMER,
    )


def _build_deterministic_explanation(
    question: str,
    paths: list[FlowPath],
    evidence: dict[str, ModuleEvidence],
) -> str:
    """无 LLM 时的确定性输出。"""
    lines: list[str] = []

    if not paths:
        lines.append("未能在 import 依赖图中找到相关模块路径。")
        lines.append("")
        lines.append("可能原因：")
        lines.append("  1. 指定的起点/终点模块名不准确")
        lines.append("  2. 模块间不存在直接或间接的导入依赖关系")
        lines.append("  3. 依赖路径超过当前最大搜索深度")
        lines.append("")
        lines.append("建议：请使用更具体的模块名重试。")
        lines.append("可以在问题中写 '从 X 到 Y' 格式指定起止模块。")
        return "\n".join(lines)

    lines.append("## 模块级依赖路径推断")
    lines.append("")
    lines.append(f"在 import 依赖图中找到 {len(paths)} 条候选路径：")
    lines.append("")
    for i, path in enumerate(paths, 1):
        chain = " → ".join(path.modules)
        lines.append(f"  {i}. {chain} (长度={path.length})")
    lines.append("")

    if evidence:
        lines.append("## 路径上各模块的关键代码")
        lines.append("")
        for module, ev in evidence.items():
            lines.append(f"### {module}")
            for item in ev.key_functions:
                lines.append(f"  - {item}")
            lines.append("")

    lines.append(_BOUNDARY_DISCLAIMER)
    lines.append("")
    lines.append("提示：设置 REPOSCOPE_API_KEY 环境变量后，")
    lines.append("  可启用 LLM 生成更详细的自然语言流程解释。")

    return "\n".join(lines)
