"""
2、关键词索引 
代码索引 — 基于 TF-IDF 的轻量级代码检索。

不依赖外部向量数据库，使用纯 Python 实现关键词搜索。可随时替换为 FAISS / Chroma 等向量索引。

优点是轻量、快、无外部依赖。
缺点是更依赖关键词匹配，可能不如语义向量搜索灵活，但对于代码这种结构化文本，TF-IDF 往往表现不错。

"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass

from .chunker import CodeChunk, ChunkResults
 

@dataclass
class SearchResult:
    """单条检索结果。"""

    chunk: CodeChunk
    score: float      # 0.0 ~ 1.0


class CodeIndex:
    """基于 TF-IDF 的代码片段索引。"""

    def __init__(self, chunk_results: ChunkResults):
        self._chunks = chunk_results.chunks
        self._idf: dict[str, float] = {}
        self._inverted: dict[str, list[int]] = defaultdict(list)
        self._doc_norms: list[float] = []
        self._build()

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        chunk_types: list[str] | None = None,
    ) -> list[SearchResult]:
        """检索与查询最相关的代码片段。

        Args:
            query: 搜索关键词
            top_k: 返回结果数
            chunk_types: 可选过滤（如 ["function", "class", "method"]）
        """
        query_terms = _tokenize(query)
        if not query_terms:
            return []

        # TF-IDF vector for query
        n_terms = len(query_terms)
        query_tf: dict[str, float] = {}
        for t in query_terms:
            query_tf[t] = query_tf.get(t, 0) + 1.0 / n_terms

        query_vec: dict[str, float] = {}
        for t, tf_val in query_tf.items():
            query_vec[t] = tf_val * self._idf.get(t, 0)
        query_norm = math.sqrt(sum(w * w for w in query_vec.values()))

        # Score each chunk
        scores: list[tuple[int, float]] = []
        for idx, chunk in enumerate(self._chunks):
            if chunk_types and chunk.type not in chunk_types:
                continue
            score = self._score_chunk(idx, query_vec, query_norm)
            if score > 0:
                scores.append((idx, score))

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
        """按名称精确/模糊匹配查找代码片段。"""
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

    def _build(self) -> None:
        N = len(self._chunks)
        doc_freq: dict[str, int] = defaultdict(int)
        doc_vectors: list[dict[str, float]] = []  # TF-IDF weighted term→weight per doc

        # 逐文档计算词频，统计文档频率
        for chunk in self._chunks:
            text = f"{chunk.name} {chunk.signature} {chunk.docstring} {chunk.code}"
            terms = _tokenize(text)
            tf: dict[str, float] = {}
            for t in terms:
                tf[t] = tf.get(t, 0) + 1
            n_terms = len(terms) if terms else 1
            for t in tf:
                tf[t] = tf[t] / n_terms
            for t in set(terms):
                doc_freq[t] += 1
            doc_vectors.append(tf)

        # IDF
        for term, df in doc_freq.items():
            self._idf[term] = math.log((N + 1) / (df + 1)) + 1

        # Build TF-IDF vectors, norms, and inverted index
        for idx, tf in enumerate(doc_vectors):
            vec: dict[str, float] = {}
            for t, tf_val in tf.items():
                w = tf_val * self._idf.get(t, 0)
                vec[t] = w
                self._inverted[t].append(idx)
            norm = math.sqrt(sum(w * w for w in vec.values()))
            self._doc_norms.append(norm)
            doc_vectors[idx] = vec  # store weighted vector

        self._doc_vectors = doc_vectors

    def _score_chunk(self, idx: int, query_vec: dict[str, float], query_norm: float) -> float:
        """计算 query 与 chunk 的余弦相似度。"""
        doc_norm = self._doc_norms[idx]
        if doc_norm == 0 or query_norm == 0:
            return 0.0

        doc_vec = self._doc_vectors[idx]
        dot = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in query_vec)

        return dot / (query_norm * doc_norm)


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """简单分词：按 CamelCase / snake_case 拆分标识符，过滤停用词。"""
    # 提取标识符
    identifiers = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    tokens: list[str] = []
    for ident in identifiers:
        # 拆分 snake_case
        for part in ident.split("_"):
            part = part.strip().lower()
            if part and part not in _STOP_WORDS and len(part) > 1:
                tokens.append(part)
            elif part and len(part) == 1 and part in {"x", "y", "z", "n", "k", "v"}:
                tokens.append(part)  # 常见数学变量保留

        # 拆分 CamelCase
        camel_parts = re.findall(r"[A-Z][a-z]+|[a-z]+|[A-Z]+", ident)
        for cp in camel_parts:
            cp = cp.strip().lower()
            if cp and cp not in _STOP_WORDS and len(cp) > 1:
                tokens.append(cp)

    return tokens


_STOP_WORDS: set[str] = {
    "the", "is", "are", "a", "an", "and", "or", "not", "in", "of", "to",
    "for", "with", "as", "at", "by", "on", "be", "it", "this", "that",
    "from", "if", "else", "elif", "while", "return", "def", "class",
    "import", "self", "none", "true", "false", "pass", "break", "continue",
    "try", "except", "finally", "raise", "yield", "lambda", "global",
    "nonlocal", "assert", "del", "print",
}
