"""Memory Tool — 多轮对话记忆，作为可插拔 Tool 注入 Agent。

设计理念（借鉴 HelloAgent）：
  - Memory 是一个 Tool，不是硬编码在 Agent 循环里的状态
  - LLM 需要历史上下文时主动调用 recall_context
  - Agent 循环完全不变——只多注册一个工具

用法:
    memory = MemoryTool(max_turns=5)
    agent = RepoScopeAgent(summary, code_index=index, memory=memory)
    agent.run("loss在哪")    # 自动保存
    agent.run("它怎么计算")   # LLM 可调用 recall_context 获取上轮上下文
"""

from __future__ import annotations


class MemoryTool:
    """多轮对话记忆。

    内部维护最近 N 轮对话。每次 run() 自动保存。
    LLM 通过 recall_context 工具获取历史上下文。
    """

    def __init__(self, max_turns: int = 5):
        self._turns: list[dict] = []
        self._max_turns = max_turns

    def save(self, question: str, answer: str) -> None:
        """保存一轮对话（由 Agent.run() 自动调用）。"""
        self._turns.append({"question": question, "answer": answer})
        if len(self._turns) > self._max_turns:
            self._turns = self._turns[-self._max_turns:]

    def recall(self, _unused: str = "") -> str:
        """返回最近 N 轮对话上下文。

        作为 LangChain Tool 暴露给 LLM。
        LLM 在处理指代不明的追问（如 "它怎么计算"）时调用此工具。
        """
        if not self._turns:
            return "(暂无历史对话)"

        lines = ["以下是最近的对话历史："]
        for i, t in enumerate(self._turns, 1):
            q_short = t["question"][:200]
            a_short = t["answer"][:300]
            lines.append(f"\n--- 第 {i} 轮 ---")
            lines.append(f"用户: {q_short}")
            lines.append(f"助手: {a_short}")

        lines.append("\n(以上是历史对话。请基于这些上下文理解用户的追问。)")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return len(self._turns) == 0
