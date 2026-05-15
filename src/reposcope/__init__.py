"""RepoScope Agent — Python 仓库结构理解 Agent."""

import warnings

# 屏蔽 LangChain/LangGraph 框架的 allowed_objects deprecation warning
# 必须在任何 langgraph/langchain import 之前执行
warnings.filterwarnings("ignore", message=r".*allowed_objects.*")

__version__ = "0.1.0"
