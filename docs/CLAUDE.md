# CLAUDE.md — RepoScope Agent

## 项目定位

RepoScope Agent 是一个面向 Python 代码仓库的结构理解 Agent。
核心思想：底层用确定性 Python 工具完成文件扫描、AST 解析、import 图构建、
入口识别和核心模块候选排序；LLM 只负责自然语言问题理解和回答生成。

**362 项测试** | **32 源文件** | **5 层架构**

---

## 架构总览

```
reposcope/
  scanner/       V1: 文件扫描 + 过滤
  parser/        V1: AST 提取 + import 分类
  graph/         V1: import 依赖图 (networkx)
  analyzer/      V1: 入口检测 + 核心模块排序 + 架构画像
  storage/       V1: repo_summary.json 持久化

  rag/           V3: 代码检索
    chunker.py         AST 切块 (function/class/method)
    index_tfidf.py     TF-IDF 关键词检索
    index_embedding.py 向量语义检索 (sentence-transformers)
    retriever.py       Code RAG (检索 → 增强 → 生成)
    flow_tracer.py     模块级流程追踪
    reader.py          源码读取 (按行号+上下文)

  report/        V2: 文档生成
    mermaid.py         Mermaid 依赖图
    structure.py       STRUCTURE.md

  agent/         V2/V3: Agent 智能层
    langgraph_agent.py  LangGraph Agent (默认主线)
    llm_client.py       统一 LLM 工厂 (DeepSeek/Anthropic/Qwen/CC-Switch)
    memory_tool.py      多轮对话记忆 (可插拔 Tool)
    tools.py            Tool Registry (legacy 手写版用)
    query_engine.py     确定性快速路径 (0 LLM)
    verification.py     证据检查
    llm_agent.py        旧版简单问答 (不在 CLI 路径)
    core.py             手写 ReAct baseline (--native 调试用)

  cli.py         命令行入口
```

---

## 数据流

```
用户问题
  │
  ├── 快速路径: QueryEngine 命中? → 直接返回 (0 LLM 调用)
  │
  └── 未命中:
        ├── 自动检测代码/流程问题 → 构建代码索引 (带缓存)
        ├── 有 API Key → LangGraph Agent (默认) / 手写版 (--native)
        │     ├── classify: 1 次轻量 LLM 调用判断 react/plan/reflect
        │     ├── agent ⇄ tools 循环 (search_code → read_source → synthesize)
        │     └── synthesize: 不绑定工具的 LLM 生成最终自然语言回答
        └── 无 API Key → 确定性回退 (代码搜索 + 流程追踪)
```

---

## CLI 命令

```bash
# 完整分析
reposcope analyze <repo>

# 问答 (自动路由)
reposcope ask <repo> "入口在哪"            # 快速路径, 0 LLM
reposcope ask <repo> "loss 在哪里实现"     # Agent 自动调 search_code + read_source
reposcope ask <repo> "从 main 到 server 的流程"  # 自动走流程追踪

# 高级选项
reposcope ask <repo> "问题" --verbose     # 显示工具调用轨迹
reposcope ask <repo> "问题" --native      # 手写 ReAct 版本 (调试用)
reposcope ask <repo> "问题" -c            # 预构建代码索引 (可选优化)
reposcope ask <repo> "问题" -e            # 向量语义索引

# 文档生成
reposcope graph <repo>                    # Mermaid 依赖图
reposcope structure <repo>                # STRUCTURE.md
```

---

## LLM 配置

通过环境变量配置，不写死模型或 API Key。详见 `agent/llm_client.py`。

```bash
# 默认 DeepSeek
$env:DEEPSEEK_API_KEY="sk-..."

# Anthropic
$env:REPOSCOPE_LLM_PROVIDER="anthropic"
$env:REPOSCOPE_MODEL="claude-sonnet-4-6"
$env:REPOSCOPE_API_KEY_ENV="ANTHROPIC_API_KEY"
$env:ANTHROPIC_API_KEY="sk-ant-..."

# CC-Switch
$env:REPOSCOPE_BASE_URL="http://localhost:8080/v1"
$env:REPOSCOPE_MODEL="deepseek-chat"
$env:REPOSCOPE_API_KEY="your-key"

# 通义千问
$env:REPOSCOPE_MODEL="qwen-plus"
$env:REPOSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:DASHSCOPE_API_KEY="sk-..."
```

---

## 测试

```bash
conda run -n reposcope python -m pytest tests/ -v
```

| 套件 | 数量 | 覆盖 |
|------|------|------|
| test_scanner.py | 18 | 文件扫描 + 过滤 |
| test_parser.py | 50 | AST 提取 + import 分类 |
| test_graph.py | 38 | 依赖图 + 查询 |
| test_analyzer.py | 49 | 入口 + 核心 + 架构 |
| test_storage.py | 35 | JSON 持久化 + 往返 |
| test_agent.py | 172 | QueryEngine + RAG + Flow + Mermaid + Structure + Verification + LangGraph + Memory |

---

## 当前完成度

| 层 | 状态 | 关键文件 |
|----|------|---------|
| V1 分析管线 | ✅ 完成 | scanner, parser, graph, analyzer, storage |
| V2 结构问答 | ✅ 完成 | query_engine, verification |
| V2 文档生成 | ✅ 完成 | mermaid, structure |
| V3 Code RAG | ✅ 完成 | chunker, index_tfidf, index_embedding, retriever, reader, flow_tracer |
| V3 Agent | ✅ 完成 | langgraph_agent, llm_client, memory_tool, tools, core |
| CLI | ✅ 完成 | analyze, ask, graph, structure |

---

## 下一步建议

| 优先级 | 任务 |
|--------|------|
| P1 | 流式输出 (LangGraph `astream_events`) |
| P1 | Agent 错误处理 (工具失败时的优雅降级) |
| P2 | 配置文件 `.reposcope/config.yaml` |
| P2 | README.md (项目对外文档) |
| P3 | 更多 Agent 循环的 mock 测试 |
