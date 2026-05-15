"""向量索引 — 基于 sentence-transformers 的语义代码检索。

与 CodeIndex 实现完全相同的 search/search_by_name/get_chunks_by_file 接口，
可直接替换 CodeIndex 而无需修改 code_rag.py。

优势：
  - 跨语言语义匹配（中文"联邦聚合" → 英文"aggregate_weights"）
  - 同义词理解（"model" ≈ "network" ≈ "architecture"）
  - 不受关键词拼写限制
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .chunker import CodeChunk, ChunkResults


@dataclass
class SearchResult:
    """单条检索结果（与 code_index.SearchResult 格式一致）。"""

    chunk: CodeChunk
    score: float


class EmbeddingIndex:
    """基于 sentence-transformers 的语义代码索引。

    接口与 CodeIndex 完全对齐：
      - search(query, top_k, chunk_types) → list[SearchResult]
      - search_by_name(name_pattern, chunk_types) → list[CodeChunk]
      - get_chunks_by_file(filepath) → list[CodeChunk]
    """

    def __init__(
        self,
        chunk_results: ChunkResults,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    ):
        self._chunks = chunk_results.chunks
        self._model = _get_model(model_name)
        self._embeddings = self._build_embeddings()

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        chunk_types: list[str] | None = None,
        min_score: float = 0.15,
    ) -> list[SearchResult]:
        """语义检索：将 query embed 后与所有 chunk 做余弦相似度排序。

        Args:
            query: 搜索文本
            top_k: 返回结果数
            chunk_types: 可选过滤
            min_score: 最低相似度阈值（低于此分数视为噪声）
        """
        if not query or not query.strip():
            return []

        query_vec = self._model.encode([query])[0]

        # 余弦相似度
        scores: list[tuple[int, float]] = []
        for idx, emb in enumerate(self._embeddings):
            if chunk_types and self._chunks[idx].type not in chunk_types:
                continue
            sim = _cosine_sim(query_vec, emb)
            if sim >= min_score:
                scores.append((idx, sim))

        scores.sort(key=lambda x: -x[1])
        return [
            SearchResult(chunk=self._chunks[idx], score=round(s, 4))
            for idx, s in scores[:top_k]
        ]

    def search_by_name(
        self,
        name_pattern: str,
        *,
        chunk_types: list[str] | None = None,
    ) -> list[CodeChunk]:
        """按名称精确/模糊匹配（与 CodeIndex 逻辑一致）。"""
        results: list[CodeChunk] = []
        pat_lower = name_pattern.lower()
        for c in self._chunks:
            if chunk_types and c.type not in chunk_types:
                continue
            if pat_lower in c.name.lower():
                results.append(c)
        return results

    def get_chunks_by_file(self, filepath: str) -> list[CodeChunk]:
        """获取指定文件的所有 chunk。"""
        return [c for c in self._chunks if c.file == filepath]

    # ---- 内部 ----

    def _build_embeddings(self):
        """为每个 chunk 构建向量。嵌入内容：name + signature + docstring。"""
        texts: list[str] = []
        for c in self._chunks:
            text = f"{c.name}: {c.signature}"
            if c.docstring:
                text += f" -- {c.docstring}"
            texts.append(text)

        # 批量编码
        return self._model.encode(texts, show_progress_bar=False)


# ---------------------------------------------------------------------------
# 模型懒加载（全局单例，避免每次创建 EmbeddingIndex 都重新加载模型）
# ---------------------------------------------------------------------------

_MODEL_INSTANCE: Optional[object] = None
_MODEL_NAME: Optional[str] = None


def _get_model(model_name: str):
    global _MODEL_INSTANCE, _MODEL_NAME
    if _MODEL_INSTANCE is not None and _MODEL_NAME == model_name:
        return _MODEL_INSTANCE
    from sentence_transformers import SentenceTransformer
    _MODEL_INSTANCE = SentenceTransformer(model_name)
    _MODEL_NAME = model_name
    return _MODEL_INSTANCE


# ---------------------------------------------------------------------------
# 余弦相似度
# ---------------------------------------------------------------------------

def _cosine_sim(a, b) -> float:
    import numpy as np
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
