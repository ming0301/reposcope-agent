"""LangGraph Agent — 基于 StateGraph + Pydantic tools + 原生 tool calling。

与 core.py（手写 ReAct 循环）的区别：
  1. Pydantic BaseModel 定义工具输入 schema（LLM 精确知道每个参数类型）
  2. Anthropic 原生 tool_use（不用正则解析 Action）
  3. StateGraph 管理流程（节点+条件边，比 for 循环更清晰）
  4. 每条工具描述经 LLM 自动选择，不依赖关键词匹配路由
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from typing import Any, Literal

# 屏蔽 LangChain 框架的 deprecation warning
warnings.filterwarnings("ignore", message=".*allowed_objects.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph")

from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing_extensions import TypedDict, Annotated


# ===================================================================
# Pydantic 工具输入 Schema
# ===================================================================

class SearchCodeInput(BaseModel):
    """搜索代码的参数。"""
    query: str = Field(description="搜索关键词。例如: 'loss function', 'train', 'forward', 'data loader'")


class TraceFlowInput(BaseModel):
    """追踪模块流程的参数。"""
    question: str = Field(description="流程问题，需包含起止模块。例如: '从 main 到 server 的流程'")


class ReadSourceInput(BaseModel):
    """读取源码的参数。"""
    file_and_lines: str = Field(description="文件路径，可选行号。例如: 'server.py' 或 'server.py:40-60'")


# ===================================================================
# 工具函数（纯 Python，不依赖 LangChain）
# ===================================================================

def _search_code(query: str, code_index) -> str:
    if code_index is None:
        return "错误: 代码索引未构建。"
    from reposcope.rag.retriever import retrieve
    ctx = retrieve(query, code_index, top_k=10)  # 多取几个，再过滤
    if not ctx.chunks:
        return f"未找到与 '{query}' 相关的代码片段。"

    # 优先 .py 文件，过滤 .txt/.md 等文档文件
    py_chunks = [c for c in ctx.chunks if c.file.endswith(".py")]
    if not py_chunks:
        # 如果确实没有 .py 结果，用全部结果但标注
        py_chunks = ctx.chunks

    lines = []
    shown = 0
    for c in py_chunks[:5]:
        s = ctx.search_results[ctx.chunks.index(c)].score if c in ctx.chunks else 0
        line_range = f"{c.file}:{c.line_start}-{c.line_end}"
        lines.append(f"{shown+1}. [{c.type}] {c.name} ({line_range}) score={s:.3f}")
        if c.docstring:
            lines.append(f"   {c.docstring[:100]}")
        shown += 1

    # 过滤掉的非 .py 结果给提示
    skipped = len(ctx.chunks) - len(py_chunks)
    if skipped > 0:
        lines.append(f"\n({skipped} 个非 Python 文件结果已过滤)")

    # 提示 Agent 可以进一步读取源码
    if py_chunks:
        top = py_chunks[0]
        lines.append(f"\n提示：使用 read_source(\"{top.file}:{max(1, top.line_start-5)}-{top.line_end+5}\") 读取 {top.name} 的完整实现。")
    return "\n".join(lines)


def _trace_flow(question: str, summary, code_index) -> str:
    if summary is None:
        return "错误: 项目摘要未加载。"
    from reposcope.rag.flow_tracer import trace_flow as _tf
    return _tf(question, code_index, summary).explanation


def _read_source(file_and_lines: str, repo_path: str = "") -> str:
    """读取源码，带行号前缀。支持相对路径（自动拼接 repo_path）。"""
    import os as _os

    # 分离路径和行号
    path_part = file_and_lines
    line_part = ""
    if ":" in file_and_lines:
        # 小心 Windows 路径如 D:\code\... — 只有最后一个 : 是行号分隔
        # 策略：如果 : 后面是纯数字（可能带 -），则作为行号处理
        last_colon = file_and_lines.rfind(":")
        after_colon = file_and_lines[last_colon + 1:]
        if after_colon and (after_colon[0].isdigit() if after_colon else False):
            path_part = file_and_lines[:last_colon]
            line_part = after_colon

    # 相对路径 → 拼接 repo_path
    if repo_path and not _os.path.isabs(path_part):
        path_part = _os.path.join(repo_path, path_part)

    full_ref = f"{path_part}:{line_part}" if line_part else path_part

    if line_part:
        try:
            if "-" in line_part:
                parts = line_part.split("-", 1)
                s = int(parts[0])
                e = int(parts[1]) if parts[1].strip() else s + 80
                code = _read_with_line_numbers(path_part, s, e)
            else:
                code = _read_with_line_numbers(path_part, int(line_part), int(line_part))
            if code:
                return f"=== {full_ref} ===\n{code}"
        except (ValueError, IndexError):
            return f"行号格式错误: {full_ref}（期望格式如 server.py:40-60 或 server.py:200-）"

    # 无行号 → 读文件前 80 行
    code = _read_with_line_numbers(path_part, 1, 80)
    if code:
        return f"=== {full_ref}:1-80 ===\n{code}"
    return f"无法读取: {full_ref}（已尝试绝对路径: {_os.path.abspath(path_part)}）"


def _read_with_line_numbers(filepath: str, start: int, end: int) -> str | None:
    """读取文件行范围，每行带行号前缀。

    自动处理颠倒的行号范围（如 50-2 → 2-50）。
    """
    if start > end:
        start, end = end, start
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except (UnicodeDecodeError, OSError):
        return None
    ctx_start = max(1, start - 3)
    ctx_end = min(len(all_lines), end + 3)
    out: list[str] = []
    for i in range(ctx_start - 1, ctx_end):
        line_no = i + 1
        marker = ">>>" if start <= line_no <= end else "   "
        out.append(f"{marker} {line_no:4d}: {all_lines[i].rstrip()}")
    return "\n".join(out)


# ===================================================================
# State
# ===================================================================

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    round_count: int
    final_answer: str
    _trace: list  # 工具调用轨迹（仅 verbose 模式）


# ===================================================================
# Agent
# ===================================================================

class RepoScopeAgent:
    """LangGraph Agent — 生产级编排。

    用法:
        agent = RepoScopeAgent(summary, code_index=index)
        result = agent.run("loss 在哪里实现")

        # 多轮对话
        memory = MemoryTool(max_turns=5)
        agent = RepoScopeAgent(summary, code_index=index, memory=memory)
        agent.run("loss在哪")
        agent.run("它怎么计算")  # LLM 可调 recall_context 获取上轮
    """

    def __init__(self, summary, *, code_index=None, model=None, verbose=False, memory=None):
        self._summary = summary
        self._code_index = code_index
        self._verbose = verbose
        self._memory = memory  # 可选 MemoryTool
        from reposcope.agent.llm_client import get_llm
        self._llm = get_llm(model=model, temperature=0)
        self._tools = self._build_tools()
        self._graph = self._build_graph()

    # ---- 入口 ----

    def run(self, question: str) -> dict:
        """运行 Agent，返回 {"answer": str, "rounds": int, "trace": list}。

        注意：Memory 注入和保存由 session 层统一处理，
        本方法只负责 Agent 图执行。
        """
        trace: list[str] = []
        state = self._graph.invoke({
            "messages": [{"role": "user", "content": question}],
            "round_count": 0,
            "final_answer": "",
            "_trace": trace,
        })
        answer = state.get("final_answer", "")
        if not answer or not answer.strip():
            answer = "（未能生成回答，请重试或使用更具体的问题）"

        return {
            "answer": answer,
            "rounds": state["round_count"],
            "trace": trace,
        }

    def run_stream(self, question: str):
        """流式运行 Agent，逐步骤 yield 事件。

        yield 格式:
            {"type": "tool_start", "name": "search_code", "args": {...}}
            {"type": "tool_result", "content": "..."}
            {"type": "thinking", "round": N}
            {"type": "synthesize"}
            {"type": "answer", "content": "..."}
            {"type": "done", "answer": "...", "rounds": N}
        """
        state = {
            "messages": [{"role": "user", "content": question}],
            "round_count": 0,
            "final_answer": "",
            "_trace": [],
        }

        last_round = 0
        for chunk in self._graph.stream(state, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                msgs = node_update.get("messages", [])
                new_round = node_update.get("round_count", last_round)

                for msg in msgs:
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            yield {
                                "type": "tool_start",
                                "name": tc["name"],
                                "args": tc.get("args", {}),
                                "round": new_round,
                            }

                # Check for tool results (ToolMessage)
                for msg in msgs:
                    if hasattr(msg, "type") and msg.type == "tool":
                        content = msg.content if hasattr(msg, "content") else ""
                        yield {
                            "type": "tool_result",
                            "content": content[:300],
                            "round": new_round,
                        }

                if node_name == "synthesize":
                    yield {"type": "synthesize", "round": new_round}

                if "final_answer" in node_update and node_update["final_answer"]:
                    yield {
                        "type": "answer",
                        "content": node_update["final_answer"],
                        "round": new_round,
                    }

                if new_round > last_round and not msgs:
                    yield {"type": "thinking", "round": new_round}

                last_round = new_round
                # Update state for next iteration
                for k, v in node_update.items():
                    if k in ("messages", "round_count", "final_answer", "_trace"):
                        state[k] = v

        # Extract final answer from accumulated state
        answer = state.get("final_answer", "")
        if not answer:
            # Fallback: find last AI message with content
            for msg in reversed(state.get("messages", [])):
                if hasattr(msg, "content") and msg.content and not (
                    hasattr(msg, "tool_calls") and msg.tool_calls
                ):
                    answer = msg.content
                    break

        if not answer or not answer.strip():
            answer = "（未能生成回答，请重试或使用更具体的问题）"

        yield {
            "type": "done",
            "answer": answer,
            "rounds": state.get("round_count", 0),
        }

    def _enrich_question(self, question: str) -> str:
        """有历史记忆时注入上下文。

        注意：当前 Memory 注入统一由 session 层处理。
        此方法保留供直接使用 Agent（不经过 session）的场景。
        """
        if self._memory and not self._memory.is_empty():
            ctx = self._memory.recall()
            return (
                f"[历史对话上下文]\n{ctx}\n\n"
                f"[当前问题]\n{question}"
            )
        return question

    # ---- 工具构建 ----

    def _build_tools(self) -> list[StructuredTool]:
        s = self._summary
        ci = self._code_index

        tools = [
            StructuredTool.from_function(
                func=lambda query: _search_code(query, ci),
                name="search_code",
                description="搜索 Python 项目中的函数、类、方法实现。输入英文关键词如 'loss function', 'train', 'forward', 'data loader'",
                args_schema=SearchCodeInput,
            ),
            StructuredTool.from_function(
                func=lambda question: _trace_flow(question, s, ci),
                name="trace_flow",
                description="追踪模块间的依赖路径和流程。输入需含起止模块名，如 '从 main 到 server 的流程'",
                args_schema=TraceFlowInput,
            ),
            StructuredTool.from_function(
                func=lambda file_and_lines, rp=s.repo_path if s else "": _read_source(file_and_lines, repo_path=rp),
                name="read_source",
                description="读取指定文件的源码。支持相对路径（如 'server.py'）和绝对路径，可选行号如 'server.py:40-60'",
                args_schema=ReadSourceInput,
            ),
        ]

        # 可选 Memory Tool：有历史时 LLM 可调用 recall_context
        if self._memory:
            from pydantic import BaseModel, Field as PydanticField
            class RecallInput(BaseModel):
                unused: str = PydanticField(default="", description="忽略此参数")
            tools.append(StructuredTool.from_function(
                func=self._memory.recall,
                name="recall_context",
                description="查看之前的对话历史。用于理解用户的追问或指代（如'它'、'那个函数'）。仅在有历史对话时可用。",
                args_schema=RecallInput,
            ))

        return tools

    # ---- Graph 构建 ----

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        llm_with_tools = self._llm.bind_tools(self._tools)
        tool_node = ToolNode(self._tools)
        MAX_ROUNDS = 6

        # === agent 节点：带工具绑定，负责思考+调工具 ===
        def agent_node(state: AgentState) -> dict:
            system = (
                "你是 RepoScope Agent，Python 代码仓库分析助手。\n"
                "消息开头有 [TOOL_POLICY] 标签控制工具调用权限：\n"
                "  [TOOL_POLICY] NO_TOOLS → 禁止调用任何工具，直接输出最终回答。\n"
                "  [TOOL_POLICY] ALLOW_CODE_TOOLS → 可调用 search_code（只一次）/ read_source / trace_flow。\n"
                "其他规则：\n"
                "1. 如果 search_code 返回空，诚实告知并建议相近搜索词。\n"
                "2. 回答时引用 >>> 标记行的确切行号。\n"
                "3. 不要使用 markdown 格式。"
            )
            if state["round_count"] >= MAX_ROUNDS - 2:
                system += (
                    "\n\n你即将达到最大步数限制。"
                    "本轮必须停止调用工具，直接用中文总结你的发现。"
                )
            msgs = [{"role": "system", "content": system}] + list(state["messages"])
            response = llm_with_tools.invoke(msgs)
            # 记录工具调用
            trace = state.get("_trace", [])
            if hasattr(response, "tool_calls") and response.tool_calls:
                for tc in response.tool_calls:
                    trace.append(f"[{state['round_count']+1}] → {tc['name']}({tc['args']})")
            else:
                trace.append(f"[{state['round_count']+1}] → (thinking)")
            return {
                "messages": [response],
                "round_count": state["round_count"] + 1,
                "_trace": trace,
            }

        # === synthesize 节点：不绑定工具，用清洁消息生成最终回答 ===
        def synthesize_node(state: AgentState) -> dict:
            trace = state.get("_trace", [])
            trace.append("[synthesize] 生成最终回答")
            system = (
                "你是 RepoScope Agent。请基于上面的工具调用结果，"
                "用中文生成一个简洁、完整的最终回答。\n"
                "规则：\n"
                "1. 对于模块/功能类问题，尽量涵盖：定义位置、调用位置、触发条件、核心步骤、作用。\n"
                "2. 如果有部分源码未读取，不要反复强调——基于已有信息回答。\n"
                "3. 如果用户提到的概念在代码中不存在，不要编造。可以提示未发现，"
                "并根据已知信息建议相近的可能（如'整流模块未发现，如果是蒸馏模块，请看 server.py'）。\n"
                "4. 只在第一次提到时标注文件名，不要在每个步骤后标注（第X行）。\n"
                "5. 不要使用 markdown 格式，用纯文本。"
            )
            clean = _build_clean_messages(state["messages"])
            clean.insert(0, {"role": "system", "content": system})
            response = self._llm.invoke(clean)
            return {
                "messages": [response],
                "final_answer": response.content if hasattr(response, "content") else str(response),
                "_trace": trace,
            }

        # === 条件边 ===
        def should_continue(state: AgentState) -> Literal["tools", "synthesize"]:
            last = state["messages"][-1]
            has_pending = hasattr(last, "tool_calls") and last.tool_calls

            if has_pending and state["round_count"] < MAX_ROUNDS:
                return "tools"

            # 无 pending tool_calls，或已达最大轮数 → 进入 synthesize
            return "synthesize"

        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)
        workflow.add_node("synthesize", synthesize_node)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges(
            "agent", should_continue,
            {"tools": "tools", "synthesize": "synthesize"},
        )
        workflow.add_edge("tools", "agent")
        workflow.add_edge("synthesize", END)

        return workflow.compile()


# ===================================================================
# 清洁消息构造（供 synthesize 使用）
# ===================================================================

def _build_clean_messages(raw_messages: list) -> list[dict]:
    """从 LangGraph 消息列表中提取干净的消息。

    规则：
      - 保留 HumanMessage（用户问题）
      - 保留 ToolMessage（工具返回结果）
      - 保留 AIMessage 中 content 非空且无 tool_calls 的（LLM 文本回复）
      - 跳过 AIMessage 中带 tool_calls 的（工具调用指令本身不含答案）
    """
    clean: list[dict] = []
    for msg in raw_messages:
        role = _get_role(msg)

        if role == "tool":
            clean.append({"role": "user", "content": f"[工具返回] {msg.content}"})
        elif role == "human":
            clean.append({"role": "user", "content": msg.content})
        elif role == "ai":
            has_tools = hasattr(msg, "tool_calls") and msg.tool_calls
            text = msg.content if hasattr(msg, "content") else ""
            if text and not has_tools:
                clean.append({"role": "assistant", "content": text})
            # 带 tool_calls 的 AIMessage 跳过——它们只是工具调用指令

    return clean


def _get_role(msg) -> str:
    """判断 LangChain 消息的角色。"""
    type_name = type(msg).__name__.lower()
    if "human" in type_name:
        return "human"
    if "tool" in type_name:
        return "tool"
    if "ai" in type_name or "assistant" in type_name:
        return "ai"
    if "system" in type_name:
        return "system"
    # 兜底：检查 content 和 tool_calls
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        return "ai"
    return "ai"
