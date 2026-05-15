"""Code RAG — 完整的检索增强生成管线。

Retrieve: 从 CodeIndex 检索相关代码片段（TF-IDF + 符号名搜索）
Augment:  将代码片段格式化为 LLM 可读的上下文
Generate: 调用 LLM 基于代码上下文生成自然语言解释

这是 V3 的核心：不只是在代码库里"搜索"，而是让 LLM
阅读检索到的代码并给出可理解的解释。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reposcope.storage.repo_summary import RepoSummary
from .index_tfidf import CodeIndex, SearchResult
from .chunker import CodeChunk
from .reader import read_file


@dataclass
class RAGContext:
    """RAG 上下文：检索到的代码片段 + 源文件。"""

    chunks: list[CodeChunk]
    search_results: list[SearchResult] = field(default_factory=list)


@dataclass
class RAGAnswer:
    """RAG 回答结果。"""

    question: str
    answer: str                     # LLM 生成的自然语言回答
    chunks_used: list[CodeChunk]    # 注入 prompt 的代码片段
    search_scores: list[float]      # 对应的检索得分


# ---------------------------------------------------------------------------
# 检索策略
# ---------------------------------------------------------------------------

def retrieve(
    question: str,
    index: CodeIndex,
    top_k: int = 5,
) -> RAGContext:
    """从代码索引中检索与问题最相关的代码片段。

    使用组合策略：
      1. TF-IDF 关键词搜索（主要）
      2. 符号名精确/模糊匹配（补充，如 "forward" → 找名为 forward 的方法）
    """
    if not question or not question.strip():
        return RAGContext(chunks=[], search_results=[])

    # 策略 1：TF-IDF 全句搜索
    tfidf_results = index.search(question, top_k=top_k)

    # 策略 2：符号名搜索（从问题中提取可能的函数/类名）
    name_results: list[CodeChunk] = []
    name_candidates = _extract_symbol_names(question)
    for name in name_candidates:
        name_results.extend(index.search_by_name(name))

    # 合并去重（TF-IDF 优先，符号名补充）
    seen_ids: set[int] = set()
    chunks: list[CodeChunk] = []
    scores: list[SearchResult] = []

    for r in tfidf_results:
        cid = id(r.chunk)
        if cid not in seen_ids:
            seen_ids.add(cid)
            chunks.append(r.chunk)
            scores.append(r)

    for c in name_results:
        cid = id(c)
        if cid not in seen_ids:
            seen_ids.add(cid)
            chunks.append(c)
            scores.append(SearchResult(chunk=c, score=0.0))

    # 限制数量
    return RAGContext(
        chunks=chunks[:top_k + 3],
        search_results=scores[:top_k + 3],
    )


# ---------------------------------------------------------------------------
# Augment：构建 LLM prompt
# ---------------------------------------------------------------------------

def build_code_prompt(
    question: str,
    context: RAGContext,
    summary: RepoSummary,
) -> str:
    """将检索到的代码片段和项目结构信息组装为 LLM prompt。

    Args:
        question: 用户原始问题
        context: 检索到的代码上下文
        summary: 项目架构摘要（提供导航信息）

    Returns:
        完整的 user prompt 文本
    """
    parts: list[str] = []

    # 项目导航信息
    parts.append("## 项目结构导航")
    parts.append(f"- 仓库: {summary.repo_path}")
    parts.append(f"- 模块数: {summary.module_count}，入口候选: "
                 f"{', '.join(e['module'] for e in summary.entry_candidates[:3])}")
    top_core = summary.structural_core_candidates[0]["module"] if summary.structural_core_candidates else "N/A"
    parts.append(f"- 结构核心模块: {top_core}")
    parts.append("")

    # 检索到的代码片段
    if context.chunks:
        parts.append(f"## 检索到的相关代码片段 ({len(context.chunks)} 个)")
        parts.append("")

    for i, chunk in enumerate(context.chunks, 1):
        # 文件路径（缩短显示）
        file_short = _short_path(chunk.file, summary.repo_path)

        parts.append(f"### 片段 {i}: `{chunk.name}` "
                     f"({chunk.type}, `{file_short}:{chunk.line_start}-{chunk.line_end}`)")
        parts.append("")

        # 签名
        parts.append(f"```python")
        parts.append(chunk.signature)
        if chunk.docstring:
            parts.append(f'    """{chunk.docstring}"""')
        parts.append(f"```")
        parts.append("")

        # 代码体（限制长度）
        code_lines = chunk.code.splitlines()
        # 跳过签名行（已在上面显示）
        body_start = 1 if chunk.type in ("function", "method", "class") else 0
        body_lines = code_lines[body_start:body_start + 50]  # 最多 50 行
        if body_lines:
            parts.append("```python")
            for line in body_lines:
                parts.append(line)
            if len(code_lines) - body_start > 50:
                parts.append(f"# ... (共 {len(code_lines) - body_start} 行，已截断)")
            parts.append("```")
        parts.append("")

    # 用户问题
    parts.append("## 用户问题")
    parts.append(question)
    parts.append("")

    # 指令
    parts.append("## 回答要求")
    parts.append("1. 基于上面检索到的代码片段回答问题，引用具体的文件名、函数名和行号。")
    parts.append("2. 解释代码的逻辑和关键步骤，用中文。")
    parts.append("3. 如果代码片段不足以完整回答问题，请诚实说明并建议进一步搜索的方向。")
    parts.append("4. 保持回答简洁，聚焦用户问的要点。")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Generate：调用 LLM
# ---------------------------------------------------------------------------

def ask_code_rag(
    question: str,
    index: CodeIndex,
    summary: RepoSummary,
    *,
    model: str = "claude-sonnet-4-6",
    api_key: str | None = None,
    max_tokens: int = 2048,
    top_k: int = 5,
) -> RAGAnswer:
    """完整的 Code RAG 流程：检索 → 增强 → 生成。

    Args:
        question: 用户问题
        index: 代码索引
        summary: 项目摘要
        model: LLM 模型
        api_key: API key
        max_tokens: 最大输出 token
        top_k: 检索返回的 chunk 数量

    Returns:
        RAGAnswer，包含 LLM 回答和使用的代码片段
    """
    import os

    api_key = api_key or os.environ.get("REPOSCOPE_API_KEY")
    if not api_key:
        raise ValueError(
            "Code RAG 需要 API Key。"
            "请设置 REPOSCOPE_API_KEY 环境变量，"
            "或使用 --deterministic 回退到代码检索模式。"
        )

    try:
        import anthropic
    except ImportError:
        raise ImportError("需要安装 anthropic SDK: pip install anthropic")

    # Step 1: Retrieve
    context = retrieve(question, index, top_k=top_k)

    # Step 2: Augment
    prompt = build_code_prompt(question, context, summary)

    # Step 3: Generate
    system = (
        "你是一个 Python 代码分析助手。你会收到用户的问题和相关代码片段。"
        "请基于代码片段回答问题，引用具体的文件名、函数名和行号。"
        "用中文回答，保持简洁有条理。"
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    text_blocks = [
        block.text for block in response.content
        if hasattr(block, "text")
    ]

    return RAGAnswer(
        question=question,
        answer="\n".join(text_blocks),
        chunks_used=context.chunks,
        search_scores=[r.score for r in context.search_results],
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _extract_symbol_names(text: str) -> list[str]:
    """从自然语言文本中提取可能的函数/类名。"""
    import re
    # CamelCase 或 snake_case 标识符（至少 3 字符）
    candidates = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b", text)
    # 过滤常见英文词和疑问词
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "what",
        "where", "when", "which", "how", "does", "are", "can", "will",
        "code", "file", "your", "have", "been", "were", "they", "them",
        "about", "into", "over", "after", "before", "between", "under",
        "loss", "train", "test", "data", "model", "main",
    }
    return [c for c in candidates if c.lower() not in stop]


def _short_path(filepath: str, root: str) -> str:
    """缩短文件路径显示。"""
    import os
    try:
        return os.path.relpath(filepath, root)
    except ValueError:
        return filepath
