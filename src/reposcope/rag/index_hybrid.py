"""混合检索器 — 词法检索 + 语义检索的 RRF 融合。

HybridCodeIndex:
  ├── Lexical Retrieval (词法)
  │     ├── CodeIndex.search()       — TF-IDF 关键词
  │     └── CodeIndex.search_by_name() — 符号名匹配
  └── Semantic Retrieval (语义)
        └── EmbeddingIndex.search()  — 跨语言语义 (容错: 未安装则跳过)

接口与 CodeIndex / EmbeddingIndex 完全一致:
  - search(query, top_k, chunk_types) → list[SearchResult]
  - search_by_name(name_pattern, chunk_types) → list[CodeChunk]
  - get_chunks_by_file(filepath) → list[CodeChunk]
"""

from __future__ import annotations

import re

from .chunker import CodeChunk, ChunkResults
from .index_tfidf import CodeIndex, SearchResult


class HybridCodeIndex:
    """混合检索器：词法 + 语义，RRF 融合排序。"""

    def __init__(self, chunk_results: ChunkResults):
        self._lexical = CodeIndex(chunk_results)
        self._semantic = self._init_semantic(chunk_results)
        self._chunks = chunk_results.chunks

    @staticmethod
    def _init_semantic(chunk_results: ChunkResults):
        """初始化语义索引，失败时返回 None（容错）。"""
        try:
            from .index_embedding import EmbeddingIndex
            return EmbeddingIndex(chunk_results)
        except Exception:
            return None

    # ---- 主接口 ----

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        chunk_types: list[str] | None = None,
    ) -> list[SearchResult]:
        """混合检索：语义 + 词法(TF-IDF + 符号名) → RRF 融合。"""
        has_chinese = _contains_chinese(query)

        # 1. 语义检索（容错：未安装 sentence-transformers 则跳过）
        semantic_results: list[SearchResult] = []
        if self._semantic is not None:
            semantic_results = self._semantic.search(
                query, top_k=top_k * 2, chunk_types=chunk_types,
            )

        # 2. 词法检索 — TF-IDF
        lexical_results = self._lexical.search(
            query, top_k=top_k * 2, chunk_types=chunk_types,
        )

        # 3. 词法检索 — 符号名匹配
        symbols = _extract_symbols(query)
        symbol_chunks: list[CodeChunk] = []
        for sym in symbols:
            symbol_chunks.extend(
                self._lexical.search_by_name(sym, chunk_types=chunk_types)
            )

        seen = set()
        symbol_results: list[SearchResult] = []
        for c in symbol_chunks:
            cid = id(c)
            if cid not in seen:
                seen.add(cid)
                symbol_results.append(SearchResult(chunk=c, score=1.0))

        # 4. RRF 融合
        merged = _rrf_fuse(
            semantic_results,
            lexical_results,
            symbol_results,
            k=60,
            semantic_weight=1.5 if has_chinese else 1.0,
            lexical_weight=1.0 if has_chinese else 1.5,
            symbol_weight=2.0,  # 符号名精确匹配权重最高
        )

        return merged[:top_k]

    def search_by_name(
        self,
        name_pattern: str,
        *,
        chunk_types: list[str] | None = None,
    ) -> list[CodeChunk]:
        return self._lexical.search_by_name(name_pattern, chunk_types=chunk_types)

    def get_chunks_by_file(self, filepath: str) -> list[CodeChunk]:
        return self._lexical.get_chunks_by_file(filepath)


# ===================================================================
# RRF 融合
# ===================================================================

def _rrf_fuse(
    semantic: list[SearchResult],
    lexical: list[SearchResult],
    symbol: list[SearchResult],
    k: int = 60,
    semantic_weight: float = 1.0,
    lexical_weight: float = 1.0,
    symbol_weight: float = 2.0,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion：合并多个排序列表。

    公式: RRF(chunk) = Σ w / (k + rank_i)
    """
    scores: dict[int, float] = {}
    chunk_map: dict[int, CodeChunk] = {}

    for rank, r in enumerate(semantic, 1):
        cid = id(r.chunk)
        scores[cid] = scores.get(cid, 0) + semantic_weight / (k + rank)
        chunk_map[cid] = r.chunk

    for rank, r in enumerate(lexical, 1):
        cid = id(r.chunk)
        scores[cid] = scores.get(cid, 0) + lexical_weight / (k + rank)
        chunk_map[cid] = r.chunk

    for rank, r in enumerate(symbol, 1):
        cid = id(r.chunk)
        scores[cid] = scores.get(cid, 0) + symbol_weight / (k + rank)
        chunk_map[cid] = r.chunk

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [
        SearchResult(chunk=chunk_map[cid], score=round(s, 4))
        for cid, s in ranked
    ]


# ===================================================================
# 辅助
# ===================================================================

def _contains_chinese(text: str) -> bool:
    """判断文本是否包含中文字符。"""
    return any('一' <= ch <= '鿿' for ch in text)


def _extract_symbols(text: str) -> list[str]:
    """从自然语言文本中提取可能的英文符号名。"""
    candidates = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b', text)
    stop = {
        'the', 'and', 'for', 'with', 'from', 'that', 'this', 'what',
        'where', 'when', 'which', 'how', 'does', 'are', 'can', 'will',
        'code', 'file', 'function', 'method', 'class', 'module',
        'implement', 'implementation', 'train', 'test', 'data',
        'model', 'loss', 'your', 'have', 'been', 'they', 'them',
        'about', 'into', 'over', 'after', 'before', 'between',
    }
    return [c for c in candidates if c.lower() not in stop]
