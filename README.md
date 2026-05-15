# RepoScope Agent

面向 Python 科研代码仓库的结构理解 Agent —— 确定性分析 + Hybrid Code RAG + LangGraph Agent。


RepoScope Agent **不是**通用聊天机器人。它是一个专门为"读懂陌生 Python 项目"而设计的 Agent——先通过确定性分析管线提取项目结构，再通过混合检索找到相关代码，最后让 LLM 基于证据生成回答。

---

## 解决什么问题

阅读一个陌生的 Python 科研代码仓库（联邦学习、行人重识别、模型复现等）时：

| 痛点 | RepoScope 怎么解决 |
|------|-------------------|
| 几百个 .py 文件，不知道入口在哪 | 确定性管线自动检测入口、核心模块、依赖关系 |
| "loss 在哪实现"、"训练流程怎么串" | 混合检索定位代码 + LLM 读源码解释 |
| 中文问题搜不到英文代码 | HybridCodeIndex = 语义向量 + TF-IDF + 符号名，跨语言匹配 |
| LLM 直接读代码会编造 | 所有回答带文件路径和行号证据，可追溯 |
| 每次重新索引太慢 | 代码索引自动缓存，文件不变秒级加载 |

---

## 整体架构

```
                         用户问题
                            │
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
    ▼                       ▼                       ▼
reposcope analyze      reposcope ask          reposcope chat
(一次性分析)           (单次问答)             (多轮对话+记忆)

                            │
              ┌─────────────┴─────────────┐
              │     Session 统一管道       │
              │  QueryEngine → Agent → LLM │
              └─────────────┬─────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
    ▼                       ▼                       ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ 确定性分析管线 │    │  Hybrid RAG  │    │ LangGraph    │
│ (V1)         │    │  (V3)        │    │ Agent (V3)   │
└──────────────┘    └──────────────┘    └──────────────┘
```

### 确定性分析管线 (V1)

```
Scanner → Parser → Graph → Analyzer → Storage
  │         │        │         │          │
  │         │        │         │          └→ repo_summary.json
  │         │        │         └→ 入口检测/核心排序/架构画像
  │         │        └→ import 依赖图 (nx.DiGraph)
  │         └→ AST 提取 + internal/external/unknown 分类
  └→ 文件扫描 + 过滤 (.git/venv/node_modules)
```

全确定性，0 次 LLM 调用，毫秒级完成。结果保存为 `repo_summary.json`。

### QueryEngine — 结构问题快速路径

对于"入口在哪""有没有循环依赖""核心模块有哪些"等确定性结构问题，QueryEngine 直接从 `repo_summary.json` 查找答案，**0 次 LLM 调用**，<1ms 返回。

QueryEngine 的结果同时作为 Agent 的前置上下文——Agent 带着结构信息去搜代码，比盲目搜索精准得多。

### Hybrid Code RAG (V3)

```
HybridCodeIndex
  ├── Semantic Retrieval (语义)
  │     └── EmbeddingIndex.search()
  │           跨语言向量匹配 (sentence-transformers)
  │           "服务器加权聚合" → aggregate_models
  │           （未安装 sentence-transformers 时自动跳过）
  │
  └── Lexical Retrieval (词法)
        ├── CodeIndex.search()
        │     TF-IDF 关键词检索
        └── CodeIndex.search_by_name()
              符号名精确匹配 (函数名/类名/方法名)

RRF (Reciprocal Rank Fusion) 融合排序 → top_k
```

**当前是纯本地混合检索**，不依赖外部向量数据库。后续可扩展 FAISS / Chroma / pgvector 替换 EmbeddingIndex 后端。

### LangGraph Agent (V3)

```
StateGraph:
  agent ──→ conditional_edge
              ├── tools ──→ agent (循环, max 6 轮)
              └── synthesize ──→ END
```

- **3 个工具**: `search_code`, `read_source`, `trace_flow`
- **synthesize 节点**: 不绑定工具，强制 LLM 基于收集到的证据生成自然语言回答
- **[TOOL_POLICY] 标签**: `NO_TOOLS` 时禁止调工具，`ALLOW_CODE_TOOLS` 时才允许——避免简单问题浪费 LLM 调用

### Session + Memory

```python
from reposcope.session import RepoScopeSession

session = RepoScopeSession("/path/to/project")
session.ask("loss 在哪")      # → "client.py:127"
session.ask("它怎么计算的")    # "它" 自动指代上轮的 loss
```

- Memory 作为可插拔 Tool，不侵入 Agent 循环
- `ask_stream()` 支持流式输出（`chat --verbose` 走同一管道）

---

## 三个核心命令

```bash
# 1. 一次性分析（生成 repo_summary.json）
python -m reposcope.cli analyze D:/code/MyProject

# 2. 单次问答（自动路由：结构 → 代码 → LLM）
python -m reposcope.cli ask D:/code/MyProject "loss 在哪里实现"

# 3. 多轮对话（带记忆，--verbose 显示工具调用过程）
python -m reposcope.cli chat D:/code/MyProject --verbose
```

---

## Quick Start

```bash
# 安装
pip install -e .

# LLM 配置（默认 DeepSeek）
$env:DEEPSEEK_API_KEY="sk-..."

# 分析 + 对话
python -m reposcope.cli analyze D:/code/MyProject
python -m reposcope.cli chat D:/code/MyProject
```

### 多厂商 LLM

```bash
# Anthropic Claude
$env:REPOSCOPE_LLM_PROVIDER="anthropic"
$env:ANTHROPIC_API_KEY="sk-ant-..."

# CC-Switch / 通义千问 / 其他 OpenAI-compatible
$env:REPOSCOPE_BASE_URL="http://localhost:8080/v1"
$env:REPOSCOPE_MODEL="deepseek-chat"
$env:REPOSCOPE_API_KEY="your-key"
```

---

## 项目目录

```
reposcope/
  scanner/       V1: 文件扫描 + 过滤
  parser/        V1: AST 提取 + import 分类
  graph/         V1: import 依赖图
  analyzer/      V1: 入口检测 + 核心排序 + 架构画像
  storage/       V1: repo_summary.json 持久化

  rag/           V3: Hybrid Code RAG
    chunker.py          AST 切块
    index_tfidf.py      TF-IDF 词法检索
    index_embedding.py  向量语义检索
    index_hybrid.py     混合检索器 (RRF 融合)
    retriever.py        RAG 管线
    flow_tracer.py      模块流程追踪
    reader.py           源码读取

  report/        V2: Mermaid + STRUCTURE.md

  agent/         V2/V3: Agent 智能层
    langgraph_agent.py   LangGraph Agent (主线)
    llm_client.py        统一 LLM 工厂
    memory_tool.py       多轮记忆 (可插拔 Tool)
    query_engine.py      结构快速路径
    verification.py      证据检查

  session.py     Python API
  cli.py         命令行入口
```

---

## 技术亮点

1. **确定性管线 + Agent 双层架构**：结构事实不靠 LLM 猜，靠 AST/图算法算
2. **HybridCodeIndex**：语义向量 + TF-IDF + 符号名，RRF 融合，跨语言匹配
3. **LangGraph StateGraph + 原生 tool_use**：Pydantic 工具 schema，synthesize 节点强制证据回答
4. **[TOOL_POLICY] 标签机制**：程序层面控制 Agent 工具权限，不靠自然语言约束
5. **Memory 作为可插拔 Tool**：不侵入核心循环，不需要时零开销
6. **多厂商 LLM**：DeepSeek/Anthropic/Qwen/CC-Switch，环境变量切换

---

## 测试

```bash
python -m pytest tests/ -v    # 374 passed
```

| 套件 | 数量 |
|------|------|
| scanner | 18 |
| parser | 50 |
| graph | 38 |
| analyzer | 49 |
| storage | 35 |
| agent (RAG + Flow + Mermaid + Structure + Verification + LangGraph + Memory + Hybrid) | 184 |

---

## 后续计划

| 优先级 | 计划 |
|--------|------|
| P1 | 静态函数调用图 |
| P1 | FAISS/Chroma 向量索引后端 |
| P2 | LangGraph checkpointer (对话持久化) |
| P2 | Web UI (Streamlit) |
| P3 | GitHub URL 自动 clone + 分析 |
