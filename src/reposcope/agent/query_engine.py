"""确定性查询引擎 — 基于 repo_summary.json 回答结构化问题。

不依赖 LLM，使用关键词匹配 + 预计算数据直接回答。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from reposcope.storage.repo_summary import RepoSummary, reconstruct_graph


@dataclass
class QueryResult:
    """查询结果。"""

    question: str
    answer: str
    matched_pattern: str   # 匹配到的模式名（用于调试）


class QueryEngine:
    """确定性查询引擎。

    基于 repo_summary.json 中的结构化数据，使用关键词匹配回答
    入口文件、依赖关系、循环依赖、模块分层等架构问题。

    注意：代码细节查询（"loss 在哪"、"forward 怎么实现" 等）
    已迁移至 CodeRAG 模块（code_rag.py），请使用 ask_code_rag()。
    """

    def __init__(self, summary: RepoSummary):
        self._s = summary
        self._g = reconstruct_graph(summary)

    def ask(self, question: str) -> QueryResult:
        """回答一个架构问题。"""
        q = question.lower().strip()

        for pattern, handler in _PATTERNS:
            if pattern(q):
                answer = handler(self, q)
                if answer:
                    return QueryResult(
                        question=question,
                        answer=answer,
                        matched_pattern=handler.__name__,
                    )

        return QueryResult(
            question=question,
            answer=self._fallback(),
            matched_pattern="fallback",
        )

    # ---- 查询方法 ----

    def _answer_entry_points(self, _q: str) -> str:
        entries = self._s.entry_candidates
        if not entries:
            return "未检测到候选入口模块。"
        lines = [f"共 {len(entries)} 个候选入口模块：", ""]
        for i, e in enumerate(entries, 1):
            lines.append(
                f"  {i}. {e['module']}  (得分: {e['score']:.2f})  "
                f"信号: {', '.join(e['signals'])}"
            )
        return "\n".join(lines)

    def _answer_core_modules(self, _q: str) -> str:
        cores = self._s.structural_core_candidates
        if not cores:
            return "未检测到结构核心模块候选。"
        lines = [f"共 {len(cores)} 个结构核心模块候选（按依赖图结构重要性排序）：", ""]
        for i, c in enumerate(cores, 1):
            role = self._s.module_categories.get(c["module"], "-")
            lines.append(
                f"  {i}. {c['module']}  (得分: {c['score']:.3f}, "
                f"被依赖: {c['in_degree']}, 角色: {role})"
            )
        return "\n".join(lines)

    def _answer_deps_of(self, q: str) -> str | None:
        target = self._extract_dep_source(q) or self._extract_module_name(q)
        if target is None:
            return None
        successors = sorted(self._g.successors(target)) if self._g.has_node(target) else []
        if not successors and not self._g.has_node(target):
            return f"模块 '{target}' 不在依赖图中。"
        if not successors:
            return f"'{target}' 没有导入任何内部模块。"
        return f"'{target}' 导入了以下内部模块：\n  " + "\n  ".join(successors)

    def _answer_importers_of(self, q: str) -> str | None:
        target = self._extract_importer_target(q)
        if target is None:
            return None
        predecessors = sorted(self._g.predecessors(target)) if self._g.has_node(target) else []
        if not predecessors and not self._g.has_node(target):
            return f"模块 '{target}' 不在依赖图中。"
        if not predecessors:
            return f"没有内部模块导入 '{target}'。"
        return f"以下模块导入了 '{target}'：\n  " + "\n  ".join(predecessors)

    def _answer_circular_deps(self, _q: str) -> str:
        deps = self._s.circular_deps
        if not deps:
            return "未检测到循环依赖，依赖图为 DAG。"
        lines = [f"检测到 {len(deps)} 个循环依赖：", ""]
        for i, cycle in enumerate(deps, 1):
            lines.append(f"  {i}. {' → '.join(cycle)} → {cycle[0]}")
        return "\n".join(lines)

    def _answer_layers(self, _q: str) -> str:
        layers = self._s.layers
        if not layers:
            return "未检测到拓扑分层。"
        lines = [f"共 {len(layers)} 层拓扑结构：", ""]
        for i, layer in enumerate(layers):
            label = "入口层（不依赖内部模块）" if i == 0 else f"第 {i} 层"
            lines.append(f"  Layer {i} ({label}):")
            for node in layer:
                role = self._s.module_categories.get(node, "-")
                node_label = f"    - {node}"
                if node == "":
                    node_label = "    - (根 __init__.py)"
                else:
                    node_label = f"    - {node}"
                lines.append(f"{node_label}  [{role}]")
            lines.append("")
        return "\n".join(lines)

    def _answer_categories(self, _q: str) -> str:
        cats = self._s.module_categories
        if not cats:
            return "未进行模块角色分类。"
        by_role: dict[str, list[str]] = {}
        for module, role in sorted(cats.items()):
            by_role.setdefault(role, []).append(module)
        lines = ["模块角色分类：", ""]
        role_order = ["entry", "orchestrator", "model", "utility", "package_init", "config", "leaf", "module"]
        for role in role_order:
            modules = by_role.pop(role, [])
            if modules:
                lines.append(f"  [{role}] ({len(modules)} 个):")
                for m in modules:
                    label = m if m else "(根 __init__.py)"
                    lines.append(f"    - {label}")
                lines.append("")
        for role, modules in sorted(by_role.items()):
            if modules:
                lines.append(f"  [{role}] ({len(modules)} 个):")
                for m in modules:
                    lines.append(f"    - {m}")
                lines.append("")
        return "\n".join(lines)

    def _answer_summary(self, _q: str) -> str:
        s = self._s
        dag = "是" if s.is_dag else f"否（{len(s.circular_deps)} 个循环依赖）"
        top_entry = s.entry_candidates[0]["module"] if s.entry_candidates else "无"
        top_core = s.structural_core_candidates[0]["module"] if s.structural_core_candidates else "无"
        lines = [
            "==== 架构概览 ====",
            "",
            f"  仓库路径: {s.repo_path}",
            f"  分析时间: {s.created_at}",
            "",
            f"  Python 文件: {s.python_file_count} 个  (遍历 {s.total_files_scanned}, 跳过 {s.skipped_file_count})",
            f"  模块节点:   {s.module_count} 个",
            f"  内部依赖边: {s.edge_count} 条",
            f"  导入:       {s.total_imports} 个 (内部 {s.internal_imports}, 外部 {s.external_imports}, 未知 {s.unknown_imports})",
            f"  类/函数:    {s.total_classes} / {s.total_functions}",
            f"  DAG:        {dag}",
            f"  拓扑深度:   {s.depth} 层",
            f"  顶级入口:   {top_entry}",
            f"  结构核心:   {top_core}",
            f"  含 main guard: {len(s.files_with_main_guard)} 个文件",
        ]
        return "\n".join(lines)

    def _answer_how_many(self, q: str) -> str | None:
        patterns = [
            (r"多少.*文件|几.*文件|文件.*多少", f"共 {self._s.python_file_count} 个 Python 文件"),
            (r"多少.*模块|几.*模块|模块.*多少", f"共 {self._s.module_count} 个模块节点"),
            (r"多少.*导入|几.*import|import.*多少", f"共 {self._s.total_imports} 个导入 (内部 {self._s.internal_imports}, 外部 {self._s.external_imports})"),
            (r"多少.*类|几.*class|class.*多少", f"共 {self._s.total_classes} 个类定义"),
            (r"多少.*函数|几.*def|函数.*多少", f"共 {self._s.total_functions} 个函数定义"),
            (r"多少.*层|几.*层", f"共 {self._s.depth} 层拓扑结构"),
        ]
        for pat, answer in patterns:
            if re.search(pat, q):
                return answer
        return None

    # 注意：代码细节查询（loss 在哪、forward 怎么实现等）已移至 CodeRAG 模块。
    # QueryEngine 专注于基于 repo_summary.json 的结构化问题。

    def _fallback(self) -> str:
        return self._answer_summary("") + (
            "\n\n提示：你可以问以下类型的问题：\n"
            "  - 入口在哪 / 入口文件是什么\n"
            "  - 核心模块有哪些\n"
            "  - X 依赖了哪些模块 / X 被哪些模块依赖\n"
            "  - 有没有循环依赖\n"
            "  - 拓扑分层 / 模块角色分类\n"
            "  - 架构概览 / 项目总结"
            "\n\n代码细节问题（如 loss 在哪、forward 怎么实现）"
            "系统会自动构建代码索引并搜索。"
        )

    # ---- 辅助 ----

    def _extract_importer_target(self, q: str) -> str | None:
        """从 'who depends on X' / '谁依赖 X' 中提取目标模块名 X。"""
        patterns = [
            r"who\s+depends\s+on\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?",
            r"who\s+imports\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?",
            r"谁\s*依赖\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?",
            r"谁\s*导入\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?",
            r"导入\s*者\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?",
            r"被\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?\s*(?:依赖|导入)",
            r"imported\s+by\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?",
        ]
        for pat in patterns:
            m = re.search(pat, q)
            if m:
                return m.group(1)
        return None

    def _extract_dep_source(self, q: str) -> str | None:
        """从 'X 依赖谁' / 'X imports' 中提取源模块名 X。"""
        patterns = [
            r"['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?\s*(?:依赖|导入了?|imports?|depend)",
            r"what\s+does\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?\s+import",
        ]
        for pat in patterns:
            m = re.search(pat, q)
            if m:
                return m.group(1)
        return None

    def _extract_module_name(self, q: str) -> str | None:
        """从问题中提取模块名。"""

        # 通用回退：提取所有候选标识符，排除保留词，取最后一个
        candidates = re.findall(r"[a-zA-Z_][a-zA-Z0-9_.]*", q)
        reserved = {
            "多少", "什么", "哪些", "哪个", "有没有", "入口", "entry", "point",
            "核心", "core", "依赖", "模块", "module", "文件", "项目", "架构",
            "who", "what", "depends", "imports", "imported", "on", "by",
            "does", "how", "many", "is", "are", "the", "there",
        }
        for name in reversed(candidates):
            if name.lower() not in reserved and len(name) > 1 and not name.isdigit():
                return name
        return None


# ---------------------------------------------------------------------------
# 模式 → 处理函数 映射
# ---------------------------------------------------------------------------

def _make_pattern(*keywords: str) -> Callable[[str], bool]:
    """创建关键词匹配函数：问题中包含任一关键词即匹配。"""
    def matcher(q: str) -> bool:
        return any(kw in q for kw in keywords)
    return matcher


_PATTERNS: list[tuple[Callable[[str], bool], Callable]] = [
    # 循环依赖
    (_make_pattern("循环依赖", "circular", "循环导入", "有环"),
     QueryEngine._answer_circular_deps),
    # 被依赖 / 导入者（前置：优先于通用依赖匹配）
    (_make_pattern("被", "导入者", "imported by", "谁依赖", "谁导入", "who depends", "who imports"),
     QueryEngine._answer_importers_of),
    # X 依赖谁
    (_make_pattern("依赖", "导入", "import", "depend"),
     QueryEngine._answer_deps_of),
    # 入口
    (_make_pattern("入口", "entry point", "main guard", "入口文件", "从哪里开始"),
     QueryEngine._answer_entry_points),
    # 核心模块
    (_make_pattern("核心模块", "core module", "最重要"),
     QueryEngine._answer_core_modules),
    # 拓扑分层
    (_make_pattern("分层", "layer", "拓扑", "层级"),
     QueryEngine._answer_layers),
    # 角色分类
    (_make_pattern("角色", "分类", "category", "标签"),
     QueryEngine._answer_categories),
    # 数量问题
    (_make_pattern("多少", "几个", "how many"),
     QueryEngine._answer_how_many),
    # 概览/总结
    (_make_pattern("概览", "总结", "summary", "总体", "整体", "架构", "介绍"),
     QueryEngine._answer_summary),
]
