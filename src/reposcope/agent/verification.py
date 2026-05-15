"""Verification 证据检查 — 检验 LLM 输出的每个事实断言在 repo_summary.json 中是否有支撑。

防止 LLM 幻觉（编造不存在的模块、错误的依赖关系等），
为回答的可靠性提供可追溯的证据链。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reposcope.storage.repo_summary import RepoSummary, reconstruct_graph


@dataclass
class ClaimCheck:
    """单条断言的验证结果。"""

    claim: str            # 提取到的原始断言
    status: str           # "verified" | "contradicted" | "unverifiable"
    evidence: str         # 支撑或反驳的数据


@dataclass
class VerificationReport:
    """验证报告。"""

    checks: list[ClaimCheck]
    verified_count: int = 0
    contradicted_count: int = 0
    unverifiable_count: int = 0
    passed: bool = True   # 无 contradicted 即为通过


def verify_response(response: str, summary: RepoSummary) -> VerificationReport:
    """验证 LLM 回答中的所有可检查断言。

    Args:
        response: LLM 的回答文本
        summary: 预分析的 RepoSummary

    Returns:
        VerificationReport，包含每条断言的检查结果
    """
    g = reconstruct_graph(summary)
    checks: list[ClaimCheck] = []

    # 提取各类型断言并检查
    checks.extend(_check_module_existence(response, summary, g))
    checks.extend(_check_dependency_claims(response, summary, g))
    checks.extend(_check_entry_claims(response, summary))
    checks.extend(_check_count_claims(response, summary))
    checks.extend(_check_dag_claims(response, summary))
    checks.extend(_check_category_claims(response, summary))
    checks.extend(_check_circular_claims(response, summary))
    checks.extend(_check_layer_claims(response, summary))

    verified = sum(1 for c in checks if c.status == "verified")
    contradicted = sum(1 for c in checks if c.status == "contradicted")
    unverifiable = sum(1 for c in checks if c.status == "unverifiable")

    return VerificationReport(
        checks=checks,
        verified_count=verified,
        contradicted_count=contradicted,
        unverifiable_count=unverifiable,
        passed=contradicted == 0,
    )


# ---------------------------------------------------------------------------
# 断言提取器 + 验证器
# ---------------------------------------------------------------------------

def _check_module_existence(
    response: str, summary: RepoSummary, g
) -> list[ClaimCheck]:
    """检查回答中提到的模块名是否在图中存在。"""
    checks: list[ClaimCheck] = []
    all_modules = set(summary.module_categories.keys())

    # 匹配中英文语境下的模块名：`models.user`、'module'、"X 模块"
    patterns = [
        r"`([a-zA-Z_][a-zA-Z0-9_.]*)`",        # 反引号包裹
        r"['\"]([a-zA-Z_][a-zA-Z0-9_.]{2,})['\"]",  # 引号包裹（至少 2 字符）
    ]
    seen: set[str] = set()
    for pat in patterns:
        for m in re.finditer(pat, response):
            name = m.group(1)
            if name in seen or len(name) < 2:
                continue
            seen.add(name)

            # 只有像模块名的才检查（含点或常见命名模式）
            if "." in name or "_" in name or name[0].islower():
                if name in all_modules:
                    checks.append(ClaimCheck(
                        claim=f"模块 '{name}' 存在",
                        status="verified",
                        evidence=f"模块 '{name}' 在依赖图中",
                    ))
                elif name not in {"true", "false", "none"}:
                    checks.append(ClaimCheck(
                        claim=f"模块 '{name}' 存在",
                        status="contradicted",
                        evidence=f"模块 '{name}' 不在依赖图中（共 {summary.module_count} 个已知模块）",
                    ))

    return checks


def _check_dependency_claims(
    response: str, summary: RepoSummary, g
) -> list[ClaimCheck]:
    """检查依赖关系断言：'X 依赖 Y' / 'X imports Y' / 'X 被 Y 导入'。"""
    checks: list[ClaimCheck] = []
    all_modules = set(summary.module_categories.keys())

    # 模式：模块A → 模块B 的依赖关系
    patterns = [
        # "X 依赖 Y" / "X depends on Y" / "X imports Y"
        r"`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?\s*(?:依赖|depends?\s+on|imports?)\s+`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?",
        # "Y 被 X 依赖" / "Y is imported by X"
        r"`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?\s*(?:被|is\s+imported\s+by)\s+`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?",
        # "X → Y" 箭头
        r"`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?\s*→\s*`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?",
    ]

    for pat in patterns:
        for m in re.finditer(pat, response, re.IGNORECASE):
            src, tgt = m.group(1), m.group(2)

            # 确认两个名称都是已知模块
            if src not in all_modules or tgt not in all_modules:
                continue

            if g.has_edge(src, tgt):
                checks.append(ClaimCheck(
                    claim=f"'{src}' 依赖 '{tgt}'",
                    status="verified",
                    evidence=f"图中存在边 {src} → {tgt}",
                ))
            else:
                checks.append(ClaimCheck(
                    claim=f"'{src}' 依赖 '{tgt}'",
                    status="contradicted",
                    evidence=f"图中不存在边 {src} → {tgt}",
                ))

    return checks


def _check_entry_claims(response: str, summary: RepoSummary) -> list[ClaimCheck]:
    """检查入口断言：'X 是入口' / 'main 是入口文件'。"""
    checks: list[ClaimCheck] = []
    entry_modules = {e["module"] for e in summary.entry_candidates}

    # "X 是入口" / "entry point is X" / "入口文件是 X"
    pat = r"`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?\s*(?:是|为).{0,5}(?:入口|entry)"
    for m in re.finditer(pat, response):
        name = m.group(1)
        if name in entry_modules:
            checks.append(ClaimCheck(
                claim=f"'{name}' 是入口",
                status="verified",
                evidence=f"'{name}' 在入口候选列表中（得分 {_entry_score(name, summary)}）",
            ))
        elif name in summary.module_categories:
            checks.append(ClaimCheck(
                claim=f"'{name}' 是入口",
                status="contradicted",
                evidence=f"'{name}' 不在入口候选列表中",
            ))

    return checks


def _check_count_claims(response: str, summary: RepoSummary) -> list[ClaimCheck]:
    """检查数量断言：'共 N 个模块' / '有 N 个文件'。"""
    checks: list[ClaimCheck] = []

    count_patterns = [
        (r"(?:共|有|包含)\s*(\d+)\s*(?:个)?\s*(?:Python\s*)?(?:模块|module)", "module_count"),
        (r"(?:共|有|包含)\s*(\d+)\s*(?:个)?\s*(?:Python\s*)?(?:文件|file)", "python_file_count"),
        (r"(?:共|有|包含)\s*(\d+)\s*(?:个)?\s*(?:内部)?(?:依赖|边|edge)", "edge_count"),
        (r"(?:共|有|包含)\s*(\d+)\s*(?:个)?\s*(?:类|class)", "total_classes"),
        (r"(?:共|有|包含)\s*(\d+)\s*(?:个)?\s*(?:函数|function)", "total_functions"),
        (r"(?:共|有|包含)\s*(\d+)\s*(?:个)?\s*(?:入口|entry)", "entry_count"),
    ]

    actual = {
        "module_count": summary.module_count,
        "python_file_count": summary.python_file_count,
        "edge_count": summary.edge_count,
        "total_classes": summary.total_classes,
        "total_functions": summary.total_functions,
        "entry_count": len(summary.entry_candidates),
    }

    for pat, key in count_patterns:
        for m in re.finditer(pat, response):
            claimed = int(m.group(1))
            actual_val = actual[key]
            if claimed == actual_val:
                checks.append(ClaimCheck(
                    claim=f"{key}={claimed}",
                    status="verified",
                    evidence=f"实际值: {actual_val}",
                ))
            else:
                checks.append(ClaimCheck(
                    claim=f"{key}={claimed}",
                    status="contradicted",
                    evidence=f"声称 {claimed}，实际 {actual_val}",
                ))

    return checks


def _check_dag_claims(response: str, summary: RepoSummary) -> list[ClaimCheck]:
    """检查 DAG 断言。"""
    checks: list[ClaimCheck] = []

    # "是 DAG" / "是 DAG（有向无环图）" / "没有循环"
    if re.search(r"(?:是|为)\s*DAG|有向无环|没有.*(?:循环|环)", response):
        if summary.is_dag:
            checks.append(ClaimCheck(
                claim="项目依赖图是 DAG",
                status="verified",
                evidence="图中无循环依赖",
            ))
        else:
            checks.append(ClaimCheck(
                claim="项目依赖图是 DAG",
                status="contradicted",
                evidence=f"存在 {len(summary.circular_deps)} 个循环依赖",
            ))

    # "存在循环依赖" / "有循环"
    if re.search(r"(?:存在|有|检测到).*(?:循环|环)", response):
        if not summary.is_dag:
            checks.append(ClaimCheck(
                claim="项目存在循环依赖",
                status="verified",
                evidence=f"检测到 {len(summary.circular_deps)} 个循环: {summary.circular_deps}",
            ))
        else:
            checks.append(ClaimCheck(
                claim="项目存在循环依赖",
                status="contradicted",
                evidence="图中无循环依赖，为 DAG",
            ))

    return checks


def _check_category_claims(response: str, summary: RepoSummary) -> list[ClaimCheck]:
    """检查角色分类断言：'X 是 model' / 'X 属于 utility'。"""
    checks: list[ClaimCheck] = []
    cats = summary.module_categories

    # "X 是 Y 类型" / "X 的角色是 Y" / "X 属于 Y"
    pat = r"`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?\s*(?:是|属于|为|的角色是).{0,5}?`?([a-zA-Z_一-鿿]+)`?"
    for m in re.finditer(pat, response):
        name, claimed_role = m.group(1), m.group(2)
        # 映射中文角色名到英文
        role_map = {
            "入口": "entry", "模型": "model", "工具": "utility",
            "配置": "config", "包初始化": "package_init", "叶子": "leaf",
            "编排": "orchestrator",
        }
        role = role_map.get(claimed_role, claimed_role)
        actual_role = cats.get(name)

        if actual_role is None:
            continue
        if actual_role == role:
            checks.append(ClaimCheck(
                claim=f"'{name}' 的角色是 {role}",
                status="verified",
                evidence=f"分类结果: {actual_role}",
            ))
        else:
            checks.append(ClaimCheck(
                claim=f"'{name}' 的角色是 {role}",
                status="contradicted",
                evidence=f"声称 {role}，实际 {actual_role}",
            ))

    return checks


def _check_circular_claims(response: str, summary: RepoSummary) -> list[ClaimCheck]:
    """检查循环依赖断言中提到的具体环。"""
    checks: list[ClaimCheck] = []

    # "X → Y → Z → X" 形式的环
    pat = r"([a-zA-Z_][a-zA-Z0-9_.]{2,}(?:\s*→\s*[a-zA-Z_][a-zA-Z0-9_.]{2,})+)"
    for m in re.finditer(pat, response):
        chain = m.group(1)
        nodes = [n.strip() for n in re.split(r"\s*→\s*", chain)]
        # 检查是否真的是环的一部分
        found = False
        for cycle in summary.circular_deps:
            cycle_set = set(cycle)
            if set(nodes).issubset(cycle_set):
                found = True
                break
        if found:
            checks.append(ClaimCheck(
                claim=f"循环依赖: {' → '.join(nodes)}",
                status="verified",
                evidence="该环在检测结果中",
            ))
        else:
            checks.append(ClaimCheck(
                claim=f"循环依赖: {' → '.join(nodes)}",
                status="contradicted",
                evidence="未在循环依赖检测结果中找到该环",
            ))

    return checks


def _check_layer_claims(response: str, summary: RepoSummary) -> list[ClaimCheck]:
    """检查分层断言：'X 在第 N 层'。"""
    checks: list[ClaimCheck] = []

    # "X 在 Layer N" / "X 在第 N 层"
    pat = r"`?([a-zA-Z_][a-zA-Z0-9_.]{2,})`?\s*(?:在|位于)\s*(?:Layer\s*|第)\s*(\d+)"
    for m in re.finditer(pat, response):
        name, layer_str = m.group(1), m.group(2)
        claimed_layer = int(layer_str)

        actual_layer = None
        for i, layer in enumerate(summary.layers):
            if name in layer:
                actual_layer = i
                break

        if actual_layer is None:
            continue
        if actual_layer == claimed_layer:
            checks.append(ClaimCheck(
                claim=f"'{name}' 在第 {claimed_layer} 层",
                status="verified",
                evidence=f"拓扑分层: Layer {actual_layer}",
            ))
        else:
            checks.append(ClaimCheck(
                claim=f"'{name}' 在第 {claimed_layer} 层",
                status="contradicted",
                evidence=f"声称 Layer {claimed_layer}，实际 Layer {actual_layer}",
            ))

    return checks


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _entry_score(module: str, summary: RepoSummary) -> str:
    for e in summary.entry_candidates:
        if e["module"] == module:
            return f"{e['score']:.2f}"
    return "?"
