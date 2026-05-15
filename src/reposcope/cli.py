
"""RepoScope CLI — 命令行入口。"""

from __future__ import annotations

import argparse
import os
import sys


def cmd_scan(args):
    """扫描仓库，列出所有 Python 文件。"""
    from reposcope.scanner import ScannerConfig, scan_directory

    config = ScannerConfig(max_file_size_kb=args.max_size_kb)
    result = scan_directory(args.path, config)

    print(f"\n 仓库: {result.root_path}")
    print(f"  遍历文件: {result.total_scanned}")
    print(f"  Python 文件: {len(result.python_files)}")
    print(f"  跳过: {len(result.skipped)}")

    if args.verbose:
        print("\n=== Python 文件 == ")
        for f in result.python_files:
            print(f"  {f}")
        print("\n=== 跳过文件 ===")
        for s in result.skipped:
            print(f"  {s['path']}  ({s['reason']})")


def cmd_analyze(args):
    """执行完整仓库结构分析并保存 repo_summary.json。"""
    from reposcope.storage import build_repo_summary_full, save_repo_summary

    repo_path = os.path.abspath(args.path)
    output_path = args.output or os.path.join(repo_path, ".reposcope", "repo_summary.json")

    print(f"\nRepoScope Agent — 正在分析仓库: {repo_path}\n")

    # 执行完整管线
    summary = build_repo_summary_full(repo_path)

    # 保存 JSON
    save_repo_summary(summary, output_path)

    # 控制台输出
    _print_summary(summary, verbose=args.verbose, output_path=output_path)

    # 警告：无内部 import 可能意味着 project root 不对
    if summary.internal_imports == 0 and summary.python_file_count > 1:
        _print_root_path_warning(repo_path)


def _print_summary(summary, *, verbose: bool, output_path: str) -> None:
    """打印分析结果摘要（优先使用 rich，不可用时回退纯文本）。"""
    try:
        _print_summary_rich(summary, verbose=verbose, output_path=output_path)
    except ImportError:
        _print_summary_plain(summary, verbose=verbose, output_path=output_path)


def _print_root_path_warning(repo_path: str) -> None:
    """当 internal_imports == 0 时，提示用户检查 project root。"""
    try:
        from rich.console import Console
        console = Console()
        console.print()
        console.print(
            "[bold yellow]⚠ 警告: 未检测到任何内部 import（internal_imports = 0）。[/bold yellow]\n"
            "这可能意味着当前指定的路径不是 Python 项目的正确根目录。\n"
            f"  当前路径: {repo_path}\n"
            "  建议尝试指定项目内层目录（如包含 setup.py / pyproject.toml 的目录），\n"
            "  或使用 --output 手动指定已生成的 JSON 路径。"
        )
    except ImportError:
        print(f"""
⚠ 警告: 未检测到任何内部 import（internal_imports = 0）。
这可能意味着当前路径不是 Python 项目的正确根目录。
  当前路径: {repo_path}
  建议尝试指定项目 层目录（如包含 setup.py / pyproject.toml 的目录）。""")


# ---------------------------------------------------------------------------
# rich 格式化输出
# ---------------------------------------------------------------------------

def _print_summary_rich(summary, *, verbose: bool, output_path: str) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()

    # 标题
    title = Text("RepoScope Agent — 分析完成", style="bold green")
    console.print(Panel(title, subtitle=f"时间: {summary.created_at}"))
    console.print()

    # Scanner 表格
    scanner_table = Table(title="Scanner", title_style="bold cyan")
    scanner_table.add_column("指标", style="dim")
    scanner_table.add_column("数值", justify="right")
    scanner_table.add_row("遍历文件总数", str(summary.total_files_scanned))
    scanner_table.add_row("Python 文件数", str(summary.python_file_count))
    scanner_table.add_row("跳过文件数", str(summary.skipped_file_count))
    console.print(scanner_table)
    console.print()

    # Parser 表格
    parser_table = Table(title="Parser", title_style="bold cyan")
    parser_table.add_column("指标", style="dim")
    parser_table.add_column("数值", justify="right")
    parser_table.add_row("导入总数", str(summary.total_imports))
    parser_table.add_row("  内部导入 (internal)", str(summary.internal_imports))
    parser_table.add_row("  外部导入 (external)", str(summary.external_imports))
    parser_table.add_row("  未知导入 (unknown)", str(summary.unknown_imports))
    parser_table.add_row("类定义数", str(summary.total_classes))
    parser_table.add_row("函数定义数", str(summary.total_functions))
    parser_table.add_row("含 main guard 的文件", str(len(summary.files_with_main_guard)))
    console.print(parser_table)
    console.print()

    # Graph 表格
    graph_table = Table(title="Graph", title_style="bold cyan")
    graph_table.add_column("指标", style="dim")
    graph_table.add_column("数值", justify="right")
    graph_table.add_row("模块节点数", str(summary.module_count))
    graph_table.add_row("内部依赖边数", str(summary.edge_count))
    console.print(graph_table)
    console.print()

    # Analyzer 表格
    analyzer_table = Table(title="Analyzer", title_style="bold cyan")
    analyzer_table.add_column("指标", style="dim")
    analyzer_table.add_column("数值", justify="right")
    dag_label = "[green]是[/green]" if summary.is_dag else "[red]否（存在循环依赖）[/red]"
    analyzer_table.add_row("有向无环图 (DAG)", dag_label)
    analyzer_table.add_row("循环依赖数", str(len(summary.circular_deps)))
    analyzer_table.add_row("拓扑深度", str(summary.depth))
    analyzer_table.add_row("入口候选数", str(len(summary.entry_candidates)))
    analyzer_table.add_row("结构核心候选数", str(len(summary.structural_core_candidates)))
    console.print(analyzer_table)
    console.print()

    # 结构核心候选 Top 5
    if summary.structural_core_candidates:
        core_table = Table(title="结构核心模块候选 (Top 5)", title_style="bold yellow")
        core_table.add_column("#", style="dim")
        core_table.add_column("模块")
        core_table.add_column("得分", justify="right")
        core_table.add_column("被依赖", justify="right")
        core_table.add_column("角色")
        for i, c in enumerate(summary.structural_core_candidates[:5], 1):
            role = summary.module_categories.get(c["module"], "-")
            core_table.add_row(
                str(i), c["module"], f"{c['score']:.3f}",
                str(c["in_degree"]), role,
            )
        console.print(core_table)
        console.print()

    # 入口候选
    if summary.entry_candidates:
        entry_table = Table(title="入口候选模块", title_style="bold yellow")
        entry_table.add_column("模块")
        entry_table.add_column("得分", justify="right")
        entry_table.add_column("信号")
        for e in summary.entry_candidates:
            entry_table.add_row(e["module"], f"{e['score']:.2f}", ", ".join(e["signals"]))
        console.print(entry_table)
        console.print()

    # 循环依赖警告
    if summary.circular_deps:
        console.print("[bold red]⚠ 检测到循环依赖:[/bold red]")
        for cycle in summary.circular_deps:
            console.print(f"  {' → '.join(cycle)}")
        console.print()

    # 详细模式
    if verbose:
        _print_verbose_rich(summary, console)

    # 输出路径
    console.print(f"[dim]分析结果已保存至: {output_path}[/dim]")


def _print_verbose_rich(summary, console) -> None:
    """rich 详细输出。"""
    # 模块角色分类
    from rich.table import Table
    cat_table = Table(title="模块角色分类", title_style="bold cyan")
    cat_table.add_column("模块")
    cat_table.add_column("角色")
    for module, role in sorted(summary.module_categories.items()):
        cat_table.add_row(module, role)
    console.print(cat_table)
    console.print()

    # 拓扑分层
    console.print("[bold cyan]拓扑分层:[/bold cyan]")
    for i, layer in enumerate(summary.layers):
        console.print(f"  Layer {i}: {', '.join(layer)}")
    console.print()

    # Python 文件列表
    console.print(f"[bold cyan]Python 文件 ({summary.python_file_count}):[/bold cyan]")
    for f in summary.python_files:
        console.print(f"  {f}")

    # 跳过文件
    if summary.skipped_files:
        console.print(f"\n[bold cyan]跳过文件 ({summary.skipped_file_count}):[/bold cyan]")
        for s in summary.skipped_files:
            console.print(f"  {s['path']}  [dim]({s['reason']})[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# 纯文本回退输出
# ---------------------------------------------------------------------------

def _print_summary_plain(summary, *, verbose: bool, output_path: str) -> None:
    """纯文本格式输出（rich 不可用时的回退）。"""
    print(f"分析完成 — {summary.created_at}")
    print()
    print("── Scanner ──")
    print(f"  遍历文件: {summary.total_files_scanned}")
    print(f"  Python 文件: {summary.python_file_count}")
    print(f"  跳过: {summary.skipped_file_count}")
    print()
    print("── Parser ──")
    print(f"  导入总数: {summary.total_imports}  (内部: {summary.internal_imports}, 外部: {summary.external_imports}, 未知: {summary.unknown_imports})")
    print(f"  类: {summary.total_classes}, 函数: {summary.total_functions}")
    print(f"  含 main guard: {len(summary.files_with_main_guard)}")
    print()
    print("── Graph ──")
    print(f"  模块: {summary.module_count}, 内部依赖边: {summary.edge_count}")
    print()
    print("── Analyzer ──")
    dag_label = "是" if summary.is_dag else "否（存在循环依赖）"
    print(f"  DAG: {dag_label}")
    print(f"  循环依赖: {len(summary.circular_deps)}")
    print(f"  拓扑深度: {summary.depth}")
    print(f"  入口候选: {len(summary.entry_candidates)}")
    print(f"  结构核心候选: {len(summary.structural_core_candidates)}")
    print()
    if summary.structural_core_candidates:
        print("  结构核心模块候选 (Top 5):")
        for i, c in enumerate(summary.structural_core_candidates[:5], 1):
            role = summary.module_categories.get(c["module"], "-")
            print(f"    {i}. {c['module']}  (得分: {c['score']:.3f}, 被依赖: {c['in_degree']}, 角色: {role})")
        print()
    if summary.entry_candidates:
        print("  入口候选模块:")
        for e in summary.entry_candidates:
            print(f"    {e['module']}  (得分: {e['score']:.2f}, 信号: {', '.join(e['signals'])})")
        print()
    if summary.circular_deps:
        print("  ⚠ 循环依赖:")
        for cycle in summary.circular_deps:
            print(f"    {' → '.join(cycle)}")
        print()
    if verbose:
        print("── 模块角色 ──")
        for module, role in sorted(summary.module_categories.items()):
            print(f"  {module}: {role}")
        print()
        print("── 拓扑分层 ──")
        for i, layer in enumerate(summary.layers):
            print(f"  Layer {i}: {', '.join(layer)}")
        print()
    print(f"分析结果已保存至: {output_path}")


def cmd_structure(args):
    """生成项目结构说明 STRUCTURE.md。"""
    from reposcope.storage import load_repo_summary
    from reposcope.agent import generate_structure_md, save_structure_md

    repo_path = os.path.abspath(args.path)
    summary_file = args.summary_file or os.path.join(
        repo_path, ".reposcope", "repo_summary.json"
    )
    if not os.path.isfile(summary_file):
        print(f"错误: 未找到分析结果文件: {summary_file}")
        print(f"请先运行: reposcope analyze {repo_path}")
        sys.exit(1)

    summary = load_repo_summary(summary_file)

    if args.output:
        save_structure_md(summary, args.output)
        print(f"STRUCTURE.md 已保存至: {args.output}")
    else:
        print(generate_structure_md(summary))


def cmd_graph(args):
    """生成 Mermaid 依赖图。"""
    from reposcope.storage import load_repo_summary
    from reposcope.agent import generate_mermaid, save_mermaid_file

    repo_path = os.path.abspath(args.path)
    summary_file = args.summary_file or os.path.join(
        repo_path, ".reposcope", "repo_summary.json"
    )
    if not os.path.isfile(summary_file):
        print(f"错误: 未找到分析结果文件: {summary_file}")
        print(f"请先运行: reposcope analyze {repo_path}")
        sys.exit(1)

    summary = load_repo_summary(summary_file)
    title = args.title or f"依赖图 — {os.path.basename(repo_path)}"

    if args.output:
        output = save_mermaid_file(
            args.output, summary, direction=args.direction, title=title,
        )
        print(f"Mermaid 依赖图已保存至: {output}")
    else:
        mermaid = generate_mermaid(
            summary, direction=args.direction, title=title,
        )
        print(mermaid)


def _clean_answer(text: str) -> str:
    """清理 Agent 回答中的 markdown 格式符号。"""
    import re
    # 去掉 ```python ... ``` 代码块标记
    text = re.sub(r'```python\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    # 去掉 **bold** 标记
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # 去掉行内 `code` 反引号
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 压缩连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def cmd_chat(args):
    """交互式多轮对话。"""
    from reposcope.session import RepoScopeSession

    repo_path = os.path.abspath(args.path)

    # 检查分析结果
    json_path = os.path.join(repo_path, ".reposcope", "repo_summary.json")
    if not os.path.isfile(json_path):
        print(f"错误: 未找到分析结果: {json_path}")
        print(f"请先运行: reposcope analyze \"{repo_path}\"")
        sys.exit(1)

    # 检查 API Key
    from reposcope.agent.llm_client import get_api_key
    if not get_api_key():
        print("错误: 未找到 API Key。")
        print("请检查以下环境变量:")
        print("  REPOSCOPE_API_KEY — 直接设置 Key")
        print("  REPOSCOPE_BASE_URL — API 地址")
        print("  REPOSCOPE_MODEL — 模型名")
        print("  REPOSCOPE_LLM_PROVIDER — 厂商类型 (openai/anthropic)")
        sys.exit(1)

    # 美化启动横幅
    repo_name = os.path.basename(repo_path.rstrip(os.sep))
    print()
    print(f"  RepoScope Chat — {repo_name}")
    print(f"  仓库: {repo_path}")
    print(f"  输入问题开始对话，输入 exit / quit / q 退出")
    print(f"  --verbose 可显示工具调用过程")
    print()

    try:
        session = RepoScopeSession(repo_path, verbose=args.verbose, max_turns=args.max_turns)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"会话初始化失败: {e}")
        print("请检查 LLM 配置: REPOSCOPE_API_KEY / REPOSCOPE_BASE_URL / REPOSCOPE_MODEL")
        sys.exit(1)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("再见！")
            break

        try:
            if args.verbose:
                # verbose: 走 Session 主链路，显示工具调用过程
                print()
                for event in session.ask_stream(user_input):
                    etype = event["type"]
                    if etype == "tool_start":
                        args_str = ", ".join(
                            f"{k}={repr(v)[:50]}" for k, v in event.get("args", {}).items()
                        )
                        print(f"  [tool] {event['name']}({args_str})")
                    elif etype == "tool_result":
                        content = event.get("content", "")
                        preview = content[:200].replace("\n", " ")
                        if len(content) > 200:
                            preview += "..."
                        print(f"  [result] {preview}")
                    elif etype == "synthesize":
                        print(f"  [synthesize] 正在生成回答...")
                    elif etype == "answer":
                        print(f"\nAgent: {_clean_answer(event['content'])}")
                    elif etype == "done":
                        pass  # already printed answer
            else:
                # 默认模式：直接获取回答，不显示工具调用
                print()
                answer = session.ask(user_input)
                answer = _clean_answer(answer)
                print(f"Agent: {answer}")
                print()
        except Exception as e:
            print(f"\n错误: {e}")
            print("请检查 LLM 配置或网络连接。")


def cmd_ask(args):
    """基于分析结果回答架构与代码问题。Agent 自主选择工具。"""
    from reposcope.storage import load_repo_summary

    repo_path = os.path.abspath(args.path)

    # 定位 JSON
    summary_file = args.summary_file or os.path.join(
        repo_path, ".reposcope", "repo_summary.json"
    )
    if not os.path.isfile(summary_file):
        print(f"错误: 未找到分析结果文件: {summary_file}")
        print(f"请先运行: reposcope analyze {repo_path}")
        sys.exit(1)

    summary = load_repo_summary(summary_file)
    from reposcope.agent.llm_client import get_api_key
    has_api_key = bool(get_api_key())

    # ---- 快速路径：确定性结构问题直接走 QueryEngine（0 LLM 调用） ----
    from reposcope.agent import QueryEngine
    engine = QueryEngine(summary)
    fast_result = engine.ask(args.question)
    if fast_result.matched_pattern != "fallback":
        _print_fast_path_result(fast_result, summary, args)
        return

    # 快速路径未命中 → 自动判断问题类型并构建索引（-c/-e 变为可选优化）
    code_index = None
    need_index = args.code or args.embed or _needs_code_index(args.question)
    if need_index:
        use_emb = args.embed
        if args.verbose and not (args.code or args.embed):
            print(f"(检测到代码/流程问题，自动构建{'向量' if use_emb else 'TF-IDF'}索引)")
        code_index = _build_code_index(summary, use_embedding=use_emb, verbose=args.verbose)
        if code_index is None:
            print("(代码索引构建失败，回退到结构查询)")

    # Agent 模式：有 API Key 时自动规划 + 调工具
    if has_api_key and not args.deterministic:
        from reposcope.agent.langgraph_agent import RepoScopeAgent
        agent = RepoScopeAgent(summary, code_index=code_index, verbose=args.verbose)
        print(f"\n[Agent] 正在分析问题...\n")
        try:
            result = agent.run(args.question)
            print(result["answer"])
            if args.verbose:
                trace = result.get("trace", [])
                if trace:
                    print(f"\n── 工具调用轨迹 ({result['rounds']} 轮) ──")
                    for t in trace:
                        print(f"  {t}")
        except Exception as e:
            print(f"Agent 错误: {e}")
            _fallback_ask(summary, args, code_index)
        return

    # 确定性模式
    _fallback_ask(summary, args, code_index)


def _build_code_index(summary, *, use_embedding: bool = False, verbose: bool = False):
    """构建代码索引（带缓存：文件列表不变则复用）。"""
    import hashlib
    import pickle
    import os as _os

    from reposcope.agent import chunk_files
    from reposcope.rag.chunker import find_config_files

    all_files = list(summary.python_files)
    config_files = find_config_files(summary.repo_path)
    all_files.extend(config_files)

    # 缓存 key = 文件列表的 hash
    files_hash = hashlib.md5(
        "".join(sorted(all_files)).encode()
    ).hexdigest()[:12]
    cache_dir = _os.path.join(summary.repo_path, ".reposcope")
    cache_path = _os.path.join(cache_dir, f"code_index_hybrid_{files_hash}.pkl")

    # 尝试从缓存加载
    if _os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                index = pickle.load(f)
            if verbose:
                print(f"(从缓存加载代码索引: {cache_path})")
            return index
        except Exception:
            pass  # 缓存损坏，重新构建

    label = "向量语义" if use_embedding else "混合检索 (TF-IDF + 语义)"
    print(f"\n[索引构建 - {label}] 正在索引文件...")
    try:
        chunk_results = chunk_files(all_files)

        if use_embedding:
            from reposcope.rag.index_embedding import EmbeddingIndex
            index = EmbeddingIndex(chunk_results)
        else:
            from reposcope.rag.index_hybrid import HybridCodeIndex
            index = HybridCodeIndex(chunk_results)

        # 保存缓存
        _os.makedirs(cache_dir, exist_ok=True)
        # 清理旧缓存
        for old in _os.listdir(cache_dir):
            if old.startswith("code_index_hybrid_") and old.endswith(".pkl"):
                _os.remove(_os.path.join(cache_dir, old))
        with open(cache_path, "wb") as f:
            pickle.dump(index, f)

        if verbose:
            print(f"(索引完成: {chunk_results.total_files} 文件 → "
                  f"{chunk_results.total_chunks} 个代码片段)")
        return index
    except Exception as e:
        print(f"索引构建失败: {e}")
        return None


def _print_fast_path_result(fast_result, summary, args) -> None:
    """为快速路径的确定性结果添加一句自然语言总结。"""
    # 给每种查询类型生成一个简短总结句
    summaries = {
        "_answer_entry_points": lambda: (
            f"共检测到 {len(summary.entry_candidates)} 个候选入口模块，"
            f"主要入口是 {summary.entry_candidates[0]['module']}（得分 {summary.entry_candidates[0]['score']:.2f}）："
        ),
        "_answer_core_modules": lambda: (
            f"共 {len(summary.structural_core_candidates)} 个结构核心模块候选，"
            f"核心是 {summary.structural_core_candidates[0]['module']}（得分 {summary.structural_core_candidates[0]['score']:.3f}）："
        ),
        "_answer_circular_deps": lambda: "",
        "_answer_layers": lambda: f"项目拓扑结构共 {summary.depth} 层：",
        "_answer_categories": lambda: f"模块角色分类（共 {summary.module_count} 个模块）：",
        "_answer_summary": lambda: "",
    }

    prefix = ""
    for pattern, gen in summaries.items():
        if pattern in fast_result.matched_pattern:
            prefix = gen()
            break

    if prefix:
        print(prefix)
        print()
    print(fast_result.answer)
    if args.verbose:
        print(f"\n(快速路径: {fast_result.matched_pattern}, 0 LLM 调用)")


def _needs_code_index(question: str) -> bool:
    """判断问题是否需要代码索引（代码搜索或流程追踪）。"""
    code_kw = [
        "实现", "代码", "函数", "定义", "怎么写", "怎么实现",
        "where", "implement", "function", "code", "method", "class",
        "在哪", "在哪里", "哪里", "位置", "定位",
        "loss", "train", "forward", "backward", "model", "dataset",
        "data", "config", "优化", "聚合", "加载", "预处理",
        "show", "查看", "显示", "readme",
    ]
    flow_kw = ["流程", "怎么走", "从", "到", "→", "flow", "path", "trace", "pipeline"]
    q = question.lower()
    return any(kw in q for kw in code_kw) or any(kw in q for kw in flow_kw)


def _is_flow_question(question: str) -> bool:
    """判断问题是否为流程追踪问题。"""
    flow_kw = ["流程", "怎么走", "→", "flow", "path", "trace", "pipeline",
               "从", "到", "怎么串", "调用链"]
    q = question.lower()
    return any(kw in q for kw in flow_kw)


def _fallback_ask(summary, args, code_index) -> None:
    """确定性回退：QueryEngine + 代码搜索（如有索引）。"""
    from reposcope.agent import QueryEngine
    engine = QueryEngine(summary)
    result = engine.ask(args.question)
    answer = result.answer
    if args.verbose:
        print(f"(匹配模式: {result.matched_pattern})")

    # 未命中结构查询 → 尝试代码搜索或流程追踪
    if result.matched_pattern == "fallback":
        if code_index:
            if _is_flow_question(args.question):
                from reposcope.rag.flow_tracer import trace_flow
                flow_result = trace_flow(args.question, code_index, summary)
                answer = flow_result.explanation
            else:
                from reposcope.rag.retriever import retrieve
                context = retrieve(args.question, code_index, top_k=5)
                if context.chunks:
                    lines = ["[代码检索结果]"]
                    for i, chunk in enumerate(context.chunks[:5], 1):
                        score = context.search_results[i-1].score if i <= len(context.search_results) else 0
                        lines.append(
                            f"  {i}. [{chunk.type}] {chunk.name} "
                            f"({chunk.file}:{chunk.line_start}) score={score:.3f}"
                        )
                    answer = "\n".join(lines)
                    answer += "\n\n提示: 设置 REPOSCOPE_API_KEY 后可使用 Agent 模式获得代码解释。"
                else:
                    answer = f"未找到与 '{args.question}' 相关的代码片段。"
        else:
            if _needs_code_index(args.question):
                answer += "\n\n(这个问题看起来是代码/流程问题，正在自动构建代码索引...)"
                idx = _build_code_index(summary, use_embedding=False, verbose=args.verbose)
                if idx:
                    if _is_flow_question(args.question):
                        from reposcope.rag.flow_tracer import trace_flow
                        flow_result = trace_flow(args.question, idx, summary)
                        answer = flow_result.explanation
                    else:
                        from reposcope.rag.retriever import retrieve
                        context = retrieve(args.question, idx, top_k=5)
                        if context.chunks:
                            lines = ["[代码检索结果]"]
                            for i, chunk in enumerate(context.chunks[:5], 1):
                                score = context.search_results[i-1].score if i <= len(context.search_results) else 0
                                lines.append(
                                    f"  {i}. [{chunk.type}] {chunk.name} "
                                    f"({chunk.file}:{chunk.line_start}) score={score:.3f}"
                                )
                            answer = "\n".join(lines)
                            answer += "\n\n提示: 设置 REPOSCOPE_API_KEY 后可使用 Agent 模式获得代码解释。"

    print(answer)


def main():
    parser = argparse.ArgumentParser(
        prog="reposcope",
        description="RepoScope Agent — 面向 Python 仓库的结构理解 Agent",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # scan
    scan_parser = subparsers.add_parser("scan", help="扫描仓库 Python 文件")
    scan_parser.add_argument("path", help="仓库路径")
    scan_parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    scan_parser.add_argument("--max-size-kb", type=int, default=500, help="最大文件大小 (KB)")
    scan_parser.set_defaults(func=cmd_scan)

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="完整仓库结构分析，生成 repo_summary.json")
    analyze_parser.add_argument("path", help="仓库路径")
    analyze_parser.add_argument("-o", "--output", help="JSON 输出路径 (默认: <repo>/.reposcope/repo_summary.json)")
    analyze_parser.add_argument("-v", "--verbose", action="store_true", help="详细输出（含文件列表和角色分类）")
    analyze_parser.set_defaults(func=cmd_analyze)

    # structure
    structure_parser = subparsers.add_parser("structure", help="生成项目结构说明 STRUCTURE.md")
    structure_parser.add_argument("path", help="仓库路径")
    structure_parser.add_argument("-f", "--summary-file", help="repo_summary.json 路径")
    structure_parser.add_argument("-o", "--output", help="输出路径 (默认: 打印到控制台)")
    structure_parser.set_defaults(func=cmd_structure)

    # graph
    graph_parser = subparsers.add_parser("graph", help="生成 Mermaid 依赖图")
    graph_parser.add_argument("path", help="仓库路径")
    graph_parser.add_argument("-f", "--summary-file", help="repo_summary.json 路径 (默认: <repo>/.reposcope/repo_summary.json)")
    graph_parser.add_argument("-o", "--output", help="输出 .mmd 文件路径 (默认: 打印到控制台)")
    graph_parser.add_argument("-d", "--direction", choices=["TD", "LR"], default="TD", help="布局方向: TD=上→下, LR=左→右 (默认: TD)")
    graph_parser.add_argument("-t", "--title", help="图表标题 (默认: 依赖图 — <仓库名>)")
    graph_parser.set_defaults(func=cmd_graph)

    # chat
    chat_parser = subparsers.add_parser("chat", help="交互式多轮对话（支持上下文记忆）")
    chat_parser.add_argument("path", help="仓库路径")
    chat_parser.add_argument("--max-turns", type=int, default=10, help="MemoryTool 最多保留的对话轮数 (默认: 10)")
    chat_parser.add_argument("-v", "--verbose", action="store_true", help="显示工具调用轨迹")
    chat_parser.set_defaults(func=cmd_chat)

    # ask
    ask_parser = subparsers.add_parser("ask", help="基于分析结果的结构化问答")
    ask_parser.add_argument("path", help="仓库路径")
    ask_parser.add_argument("question", help="架构问题（如：入口在哪、核心模块有哪些、有没有循环依赖）")
    ask_parser.add_argument("-f", "--summary-file", help="repo_summary.json 路径 (默认: <repo>/.reposcope/repo_summary.json)")
    ask_parser.add_argument("-d", "--deterministic", action="store_true", help="强制使用确定性模式（不调用 LLM）")
    ask_parser.add_argument("-c", "--code", action="store_true", help="启用代码检索模式（索引函数/类/方法）")
    ask_parser.add_argument("-e", "--embed", action="store_true", help="使用向量语义索引（sentence-transformers，需安装）")
    ask_parser.add_argument("-m", "--mode", choices=["auto", "react", "plan", "reflect"], default="auto",
                            help="推理模式: auto=自动选择, react=边想边做, plan=先计划再执行, reflect=自检修正")
    ask_parser.add_argument("-v", "--verbose", action="store_true", help="显示匹配的查询模式")
    ask_parser.set_defaults(func=cmd_ask)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
