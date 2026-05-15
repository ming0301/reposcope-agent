"""分析结果持久化 — 保存/加载 repo_summary.json。

汇总 scanner、parser、graph、analyzer 四层输出为单一 JSON 文件，
支持保存和加载，便于离线审查和跨会话对比。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import networkx as nx

from reposcope.analyzer.architecture import ArchitectureProfile
from reposcope.analyzer.entry_detector import (
    CoreModuleCandidate,
    EntryCandidate,
    detect_entries,
    rank_core_modules,
)
from reposcope.graph.import_graph import (
    ImportGraph,
    build_import_graph,
)
from reposcope.parser.ast_extractor import ASTExtractor, FileASTResult
from reposcope.parser.import_classifier import (
    ClassificationResult,
    classify_imports,
)
from reposcope.scanner.file_scanner import ScanResult, scan_directory


# ---------------------------------------------------------------------------
# RepoSummary dataclass
# ---------------------------------------------------------------------------


@dataclass
class RepoSummary:
    """项目分析完整摘要。"""

    # ---- 元数据 ----
    repo_path: str
    created_at: str

    # ---- Scanner ----
    total_files_scanned: int
    python_file_count: int
    skipped_file_count: int
    python_files: list[str]
    skipped_files: list[dict]          # 跳过文件明细（最多 200 条）
    skipped_reason_counts: dict[str, int]  # 跳过原因汇总 {"非 Python 文件类型": 342, ...}

    # ---- Parser ----
    total_imports: int
    internal_imports: int
    external_imports: int
    unknown_imports: int
    total_classes: int
    total_functions: int
    files_with_main_guard: list[str]

    # ---- Graph ----
    module_count: int
    edge_count: int
    graph_data: dict   # networkx node_link_data 格式

    # ---- Analyzer ----
    is_dag: bool
    circular_deps: list[list[str]]
    depth: int
    layers: list[list[str]]
    module_categories: dict[str, str]
    entry_candidates: list[dict]
    structural_core_candidates: list[dict]


# ---------------------------------------------------------------------------
# 构建 RepoSummary
# ---------------------------------------------------------------------------


def build_repo_summary(
    scan_result: ScanResult,
    ast_results: list[FileASTResult],
    classification_results: list[ClassificationResult],
    import_graph: ImportGraph,
    architecture_profile: ArchitectureProfile,
    entry_candidates: list[EntryCandidate],
    core_candidates: list[CoreModuleCandidate],
) -> RepoSummary:
    """从各模块输出构建 RepoSummary。"""
    # ---- Parser 聚合 ----
    total_imports = 0
    internal_imports = 0
    external_imports = 0
    unknown_imports = 0
    for cr in classification_results:
        for imp in cr.imports:
            total_imports += 1
            if imp.category == "internal":
                internal_imports += 1
            elif imp.category == "external":
                external_imports += 1
            else:
                unknown_imports += 1

    total_classes = sum(len(r.classes) for r in ast_results)
    total_functions = sum(len(r.functions) for r in ast_results)
    files_with_mg = sorted(
        r.file for r in ast_results if r.main_guard is not None
    )

    # ---- Graph ----
    graph_data = nx.node_link_data(import_graph.graph)

    # ---- Scanner: 汇总 + 截断 ----
    MAX_SKIPPED_DETAIL = 200
    reason_counts: dict[str, int] = {}
    for s in scan_result.skipped:
        reason = s.get("reason", "未知")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    skipped_detail = scan_result.skipped[:MAX_SKIPPED_DETAIL]

    # ---- Analyzer ----
    entry_dicts = [_entry_to_dict(e) for e in entry_candidates]
    core_dicts = [_core_to_dict(c) for c in core_candidates]

    return RepoSummary(
        repo_path=scan_result.root_path,
        created_at=datetime.now(timezone.utc).isoformat(),
        total_files_scanned=scan_result.total_scanned,
        python_file_count=len(scan_result.python_files),
        skipped_file_count=len(scan_result.skipped),
        python_files=scan_result.python_files,
        skipped_files=skipped_detail,
        skipped_reason_counts=reason_counts,
        total_imports=total_imports,
        internal_imports=internal_imports,
        external_imports=external_imports,
        unknown_imports=unknown_imports,
        total_classes=total_classes,
        total_functions=total_functions,
        files_with_main_guard=files_with_mg,
        module_count=architecture_profile.module_count,
        edge_count=architecture_profile.edge_count,
        graph_data=graph_data,
        is_dag=architecture_profile.is_dag,
        circular_deps=architecture_profile.circular_deps,
        depth=architecture_profile.depth,
        layers=architecture_profile.layers,
        module_categories=architecture_profile.categories,
        entry_candidates=entry_dicts,
        structural_core_candidates=core_dicts,
    )


def build_repo_summary_full(root_path: str) -> RepoSummary:
    """从零开始执行完整分析管线并构建 RepoSummary。

    这是一个便捷函数，适合 CLI 一次性调用。
    """
    from reposcope.scanner import ScannerConfig
    from reposcope.analyzer.architecture import profile_architecture

    # Step 1: Scanner
    scan_result = scan_directory(root_path, ScannerConfig())

    # Step 2: Parser
    extractor = ASTExtractor()
    ast_results = extractor.extract_all(scan_result.python_files)
    classification_results = classify_imports(ast_results, root_path)

    # Step 3: Graph
    import_graph = build_import_graph(ast_results, classification_results, root_path)

    # Step 4: Analyzer
    arch_profile = profile_architecture(import_graph, ast_results)
    entries = detect_entries(import_graph, ast_results)
    cores = rank_core_modules(import_graph)

    return build_repo_summary(
        scan_result=scan_result,
        ast_results=ast_results,
        classification_results=classification_results,
        import_graph=import_graph,
        architecture_profile=arch_profile,
        entry_candidates=entries,
        core_candidates=cores,
    )


# ---------------------------------------------------------------------------
# 保存 / 加载
# ---------------------------------------------------------------------------


def save_repo_summary(summary: RepoSummary, filepath: str) -> None:
    """将 RepoSummary 保存为 JSON 文件。"""
    data = _summary_to_dict(summary)
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_repo_summary(filepath: str) -> RepoSummary:
    """从 JSON 文件加载 RepoSummary。"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _dict_to_summary(data)


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------


def _entry_to_dict(e: EntryCandidate) -> dict:
    return {"module": e.module, "file": e.file, "score": e.score, "signals": e.signals}


def _core_to_dict(c: CoreModuleCandidate) -> dict:
    return {
        "module": c.module,
        "file": c.file,
        "score": c.score,
        "in_degree": c.in_degree,
        "out_degree": c.out_degree,
        "betweenness": c.betweenness,
        "pagerank": c.pagerank,
    }


def _summary_to_dict(s: RepoSummary) -> dict:
    return {
        "repo_path": s.repo_path,
        "created_at": s.created_at,
        "scanner": {
            "total_files_scanned": s.total_files_scanned,
            "python_file_count": s.python_file_count,
            "skipped_file_count": s.skipped_file_count,
            "python_files": s.python_files,
            "skipped_files": s.skipped_files,
            "skipped_reason_counts": s.skipped_reason_counts,
        },
        "parser": {
            "total_imports": s.total_imports,
            "internal_imports": s.internal_imports,
            "external_imports": s.external_imports,
            "unknown_imports": s.unknown_imports,
            "total_classes": s.total_classes,
            "total_functions": s.total_functions,
            "files_with_main_guard": s.files_with_main_guard,
        },
        "graph": {
            "module_count": s.module_count,
            "edge_count": s.edge_count,
            "graph_data": s.graph_data,
        },
        "analyzer": {
            "is_dag": s.is_dag,
            "circular_deps": s.circular_deps,
            "depth": s.depth,
            "layers": s.layers,
            "module_categories": s.module_categories,
            "entry_candidates": s.entry_candidates,
            "structural_core_candidates": s.structural_core_candidates,
        },
    }


def _dict_to_summary(d: dict) -> RepoSummary:
    s = d["scanner"]
    p = d["parser"]
    g = d["graph"]
    a = d["analyzer"]
    return RepoSummary(
        repo_path=d["repo_path"],
        created_at=d["created_at"],
        total_files_scanned=s["total_files_scanned"],
        python_file_count=s["python_file_count"],
        skipped_file_count=s["skipped_file_count"],
        python_files=s["python_files"],
        skipped_files=s["skipped_files"],
        skipped_reason_counts=s.get("skipped_reason_counts", {}),
        total_imports=p["total_imports"],
        internal_imports=p["internal_imports"],
        external_imports=p["external_imports"],
        unknown_imports=p["unknown_imports"],
        total_classes=p["total_classes"],
        total_functions=p["total_functions"],
        files_with_main_guard=p["files_with_main_guard"],
        module_count=g["module_count"],
        edge_count=g["edge_count"],
        graph_data=g["graph_data"],
        is_dag=a["is_dag"],
        circular_deps=a["circular_deps"],
        depth=a["depth"],
        layers=a["layers"],
        module_categories=a["module_categories"],
        entry_candidates=a["entry_candidates"],
        structural_core_candidates=a["structural_core_candidates"],
    )


# ---------------------------------------------------------------------------
# 从 RepoSummary 重建对象
# ---------------------------------------------------------------------------


def reconstruct_graph(summary: RepoSummary) -> nx.DiGraph:
    """从 RepoSummary 的 graph_data 重建 networkx DiGraph。"""
    return nx.node_link_graph(summary.graph_data)
