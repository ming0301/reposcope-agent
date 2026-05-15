"""

RepoScope Session — 面向演示和真实使用的 Python API。

一个 Session 实例 = 一个仓库 + 一个 Agent + 持续的多轮对话记忆。

用法:
    from reposcope.session import RepoScopeSession

    session = RepoScopeSession("D:/code/FedReID/FedReID-master")
    print(session.ask("loss 在哪里实现"))
    print(session.ask("它怎么计算的"))          # 自动利用上一轮记忆
    print(session.ask("训练流程怎  么走"))
    session.print_summary()                     # 打印架构摘要
"""

from __future__ import annotations

import os


class RepoScopeSession:
    """仓库分析会话。

    封装 repo_summary 加载、代码索引构建、MemoryTool 和 Agent 实例管理。
    用户只需传入 repo_path，之后连续调用 ask() 即可。
    """

    def __init__(
        self,
        repo_path: str,
        *,
        model: str | None = None,
        verbose: bool = False,
        max_turns: int = 10,
    ):
        self._repo_path = os.path.abspath(repo_path)
        self._verbose = verbose

        # 1. 加载或提示 analyze
        self._summary = self._load_summary()

        # 2. 构建代码索引（自动缓存）
        self._code_index = self._build_index()

        # 3. 创建 MemoryTool（同 session 内持续生效）
        from reposcope.agent.memory_tool import MemoryTool
        self._memory = MemoryTool(max_turns=max_turns)

        # 4. 创建 Agent（单例，复用）
        from reposcope.agent.langgraph_agent import RepoScopeAgent
        self._agent = RepoScopeAgent(
            self._summary,
            code_index=self._code_index,
            model=model,
            verbose=verbose,
            memory=self._memory,
        )

    # ---- 核心 API ----

    def ask(self, question: str) -> str:
        """统一证据驱动问答。

        管道: QueryEngine 前置探查 → Agent 带上下文决策 → LLM 最终回答。
        不区分问题类型，Agent 根据 QueryEngine 结果自行判断
        是否需要进一步调 search_code / read_source。
        """
        # 1. QueryEngine 前置探查（0 LLM 调用，<1ms）
        from reposcope.agent.query_engine import QueryEngine
        qe_result = QueryEngine(self._summary).ask(question)

        # 2. 构建上下文 + [TOOL_POLICY] 标签
        if qe_result.matched_pattern != "fallback":
            ctx = (
                f"[TOOL_POLICY] NO_TOOLS\n"
                f"[结构分析结果 — 已直接命中]\n{qe_result.answer}"
            )
        else:
            ctx = (
                f"[TOOL_POLICY] ALLOW_CODE_TOOLS\n"
                f"[项目架构概览 — 结构分析未直接命中]\n{qe_result.answer}"
            )

        # 3. 注入 Memory 上下文 + 结构上下文 → Agent
        enriched = self._build_enriched(question, ctx)
        result = self._agent.run(enriched)
        answer = result["answer"]

        if self._verbose:
            trace = result.get("trace", [])
            if trace:
                print(f"\n── 工具调用轨迹 ({result['rounds']} 轮) ──")
                for t in trace:
                    print(f"  {t}")

        self._memory.save(question, answer)
        return answer

    def ask_stream(self, question: str):
        """流式版 ask()——与 ask() 完全相同的管道，但逐步骤 yield 事件。

        供 chat --verbose 使用，不绕过 Session 主链路。
        """
        from reposcope.agent.query_engine import QueryEngine
        qe_result = QueryEngine(self._summary).ask(question)

        if qe_result.matched_pattern != "fallback":
            ctx = (
                f"[TOOL_POLICY] NO_TOOLS\n"
                f"[结构分析结果 — 已直接命中]\n{qe_result.answer}"
            )
        else:
            ctx = (
                f"[TOOL_POLICY] ALLOW_CODE_TOOLS\n"
                f"[项目架构概览 — 结构分析未直接命中]\n{qe_result.answer}"
            )

        enriched = self._build_enriched(question, ctx)
        answer = ""
        for event in self._agent.run_stream(enriched):
            yield event
            if event["type"] == "done":
                answer = event["answer"]

        self._memory.save(question, answer)

    def _build_enriched(self, question: str, ctx: str) -> str:
        """构建 Agent 输入：memory + 结构上下文 + 用户问题。"""
        parts = []
        if not self._memory.is_empty():
            parts.append(f"[历史对话]\n{self._memory.recall()}")
        parts.append(ctx)
        parts.append(f"[用户问题]\n{question}")
        return "\n\n".join(parts)

    # ---- 信息 ----

    @property
    def repo_path(self) -> str:
        return self._repo_path

    @property
    def memory(self):
        return self._memory

    def summary(self) -> dict:
        """返回项目架构摘要。"""
        s = self._summary
        return {
            "repo_path": s.repo_path,
            "python_files": s.python_file_count,
            "modules": s.module_count,
            "internal_edges": s.edge_count,
            "depth": s.depth,
            "is_dag": s.is_dag,
            "entry_points": [e["module"] for e in s.entry_candidates[:5]],
            "structural_core": [c["module"] for c in s.structural_core_candidates[:5]],
        }

    def print_summary(self) -> None:
        """打印架构摘要到终端。"""
        s = self.summary()
        dag = "是" if s["is_dag"] else "否"
        print(f"仓库: {s['repo_path']}")
        print(f"  Python 文件: {s['python_files']}, 模块: {s['modules']}, 内部边: {s['internal_edges']}")
        print(f"  DAG: {dag}, 深度: {s['depth']}")
        print(f"  入口: {', '.join(s['entry_points'][:3])}")
        print(f"  结构核心: {', '.join(s['structural_core'][:3])}")

    def _load_summary(self):
        """加载 repo_summary.json。不存在时抛出 RuntimeError。"""
        json_path = os.path.join(self._repo_path, ".reposcope", "repo_summary.json")
        if not os.path.isfile(json_path):
            raise FileNotFoundError(
                f"未找到分析结果: {json_path}\n"
                f"请先运行: reposcope analyze \"{self._repo_path}\""
            )

        from reposcope.storage.repo_summary import load_repo_summary
        return load_repo_summary(json_path)

    def _build_index(self):
        """构建代码索引（带缓存，文件列表不变则复用）。"""
        import hashlib
        import pickle

        from reposcope.agent import chunk_files
        from reposcope.rag.chunker import find_config_files
        from reposcope.rag.index_hybrid import HybridCodeIndex

        all_files = list(self._summary.python_files)
        config_files = find_config_files(self._summary.repo_path)
        all_files.extend(config_files)

        # 缓存 key
        files_hash = hashlib.md5(
            "".join(sorted(all_files)).encode()
        ).hexdigest()[:12]
        cache_dir = os.path.join(self._repo_path, ".reposcope")
        cache_path = os.path.join(cache_dir, f"code_index_hybrid_{files_hash}.pkl")

        # 尝试加载缓存
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    index = pickle.load(f)
                if self._verbose:
                    print(f"(从缓存加载代码索引)")
                return index
            except Exception:
                pass

        # 构建
        if self._verbose:
            print("(正在构建代码索引...)")
        chunk_results = chunk_files(all_files)
        index = HybridCodeIndex(chunk_results)

        # 保存缓存
        os.makedirs(cache_dir, exist_ok=True)
        for old in os.listdir(cache_dir):
            if old.startswith("code_index_hybrid_") and old.endswith(".pkl"):
                os.remove(os.path.join(cache_dir, old))
        with open(cache_path, "wb") as f:
            pickle.dump(index, f)

        if self._verbose:
            print(f"(索引完成: {chunk_results.total_files} 文件 → "
                  f"{chunk_results.total_chunks} 个代码片段)")
        return index
