from .langgraph_agent import RepoScopeAgent
from .llm_client import get_api_key, get_llm, require_api_key
from .memory_tool import MemoryTool
from .query_engine import QueryEngine, QueryResult
from .verification import (
    ClaimCheck,
    VerificationReport,
    verify_response,
)

# 向后兼容：从顶层模块 re-export
from reposcope.rag import (
    CodeChunk,
    CodeIndex,
    ChunkResults,
    EmbeddingIndex,
    HybridCodeIndex,
    FlowTraceResult,
    RAGAnswer,
    SearchResult,
    SourceSnippet,
    ask_code_rag,
    build_code_prompt,
    chunk_files,
    find_config_files,
    read_file,
    read_lines,
    retrieve,
    trace_flow,
)
from reposcope.report import (
    generate_mermaid,
    generate_structure_md,
    save_mermaid_file,
    save_structure_md,
)

__all__ = [
    "ask_code_rag",
    "build_code_prompt",
    "chunk_files",
    "ChunkResults",
    "ClaimCheck",
    "CodeChunk",
    "CodeIndex",
    "EmbeddingIndex",
    "find_config_files",
    "HybridCodeIndex",
    "FlowTraceResult",
    "MemoryTool",
    "RepoScopeAgent",
    "generate_mermaid",
    "get_api_key",
    "get_llm",
    "require_api_key",
    "generate_structure_md",
    "QueryEngine",
    "QueryResult",
    "RAGAnswer",
    "read_file",
    "read_lines",
    "retrieve",
    "save_mermaid_file",
    "save_structure_md",
    "SearchResult",
    "SourceSnippet",
    "trace_flow",
    "VerificationReport",
    "verify_response",
]
