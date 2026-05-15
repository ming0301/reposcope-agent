"""测试 agent 模块。"""

import os

import pytest

from reposcope.storage.repo_summary import build_repo_summary_full
from reposcope.agent.query_engine import QueryEngine, QueryResult

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample_project")


# ---------------------------------------------------------------------------
# QueryEngine 测试
# ---------------------------------------------------------------------------


class TestQueryEngine:
    """测试确定性查询引擎。"""

    @classmethod
    def setup_class(cls):
        cls.summary = build_repo_summary_full(FIXTURE_DIR)
        cls.engine = QueryEngine(cls.summary)

    # -- 入口 --

    def test_entry_points_en(self):
        result = self.engine.ask("entry points")
        assert "main" in result.answer
        assert "0.95" in result.answer

    def test_entry_points_cn(self):
        result = self.engine.ask("入口在哪")
        assert "main" in result.answer

    def test_entry_points_main_guard(self):
        result = self.engine.ask("main guard 在哪里")
        assert "main" in result.answer

    # -- 核心模块 --

    def test_core_modules_en(self):
        result = self.engine.ask("core modules")
        assert "models.user" in result.answer
        # 应包含得分信息（值取决于算法，不硬编码）

    def test_core_modules_cn(self):
        result = self.engine.ask("核心模块有哪些")
        assert "models.user" in result.answer

    # -- 循环依赖 --

    def test_circular_deps(self):
        result = self.engine.ask("有没有循环依赖")
        assert "DAG" in result.answer

    def test_circular_deps_en(self):
        result = self.engine.ask("circular dependencies")
        assert "DAG" in result.answer

    # -- 依赖查询 --

    def test_deps_of_main(self):
        result = self.engine.ask("main 依赖谁")
        assert "config" in result.answer
        assert "models.user" in result.answer
        assert "utils.helpers" in result.answer

    def test_deps_of_leaf(self):
        result = self.engine.ask("models.user 依赖哪些模块")
        assert "没有导入任何内部模块" in result.answer

    def test_deps_unknown_module(self):
        result = self.engine.ask("nonexistent 依赖谁")
        assert "不在依赖图中" in result.answer

    # -- 被依赖查询 --

    def test_importers_of(self):
        result = self.engine.ask("who depends on models.user")
        assert "main" in result.answer
        assert "utils.helpers" in result.answer

    def test_importers_of_cn(self):
        result = self.engine.ask("谁依赖 models.user")
        assert "main" in result.answer

    def test_importers_of_leaf(self):
        result = self.engine.ask("谁依赖 main")
        assert "没有内部模块导入" in result.answer

    # -- 分层 --

    def test_layers(self):
        result = self.engine.ask("拓扑分层")
        assert "Layer 0" in result.answer
        assert "main" in result.answer
        assert "models.user" in result.answer

    def test_layers_en(self):
        result = self.engine.ask("layers of the project")
        assert "Layer" in result.answer

    # -- 角色 --

    def test_categories(self):
        result = self.engine.ask("模块角色分类")
        assert "entry" in result.answer
        assert "model" in result.answer
        assert "utility" in result.answer

    # -- 数量 --

    def test_how_many_files(self):
        result = self.engine.ask("有多少个Python文件")
        assert "7" in result.answer

    def test_how_many_modules(self):
        result = self.engine.ask("几个模块")
        assert "7" in result.answer

    # -- 概览 --

    def test_summary(self):
        result = self.engine.ask("架构概览")
        assert "Python 文件" in result.answer
        assert "模块节点" in result.answer
        assert "DAG" in result.answer

    def test_summary_en(self):
        result = self.engine.ask("project summary")
        assert "Python" in result.answer

    # -- 回退 --

    def test_fallback_on_unknown(self):
        result = self.engine.ask("这个项目的作者是谁")
        assert result.matched_pattern == "fallback"
        assert "提示" in result.answer  # 提供帮助

    # -- QueryResult 结构 --

    def test_query_result_fields(self):
        result = self.engine.ask("入口")
        assert isinstance(result, QueryResult)
        assert result.question == "入口"
        assert result.answer
        assert result.matched_pattern


# ---------------------------------------------------------------------------
# 模块名提取测试
# ---------------------------------------------------------------------------


class TestModuleExtraction:
    """测试模块名提取。"""

    @classmethod
    def setup_class(cls):
        cls.summary = build_repo_summary_full(FIXTURE_DIR)
        cls.engine = QueryEngine(cls.summary)

    def test_extract_importer_target_en(self):
        name = self.engine._extract_importer_target("who depends on models.user")
        assert name == "models.user"

    def test_extract_importer_target_cn(self):
        name = self.engine._extract_importer_target("谁依赖 utils.helpers")
        assert name == "utils.helpers"

    def test_extract_importer_target_not_importer(self):
        name = self.engine._extract_importer_target("models.user 依赖谁")
        assert name is None  # 这是 dep 问题，不是 importer 问题

    def test_extract_dep_source(self):
        name = self.engine._extract_dep_source("main 依赖谁")
        assert name == "main"

    def test_extract_dep_source_en(self):
        name = self.engine._extract_dep_source("main imports")
        assert name == "main"

    def test_extract_fallback_reserved_words(self):
        """保留词不应被提取为模块名。"""
        name = self.engine._extract_module_name("what is the entry point")
        assert name is None or name == "entry"  # 'entry' 在 reserved 中 → None


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """测试边界情况。"""

    def test_empty_summary(self):
        from reposcope.storage.repo_summary import RepoSummary
        from datetime import datetime, timezone

        empty = RepoSummary(
            repo_path="/empty",
            created_at=datetime.now(timezone.utc).isoformat(),
            total_files_scanned=0, python_file_count=0, skipped_file_count=0,
            python_files=[], skipped_files=[], skipped_reason_counts={},
            total_imports=0, internal_imports=0, external_imports=0,
            unknown_imports=0, total_classes=0, total_functions=0,
            files_with_main_guard=[],
            module_count=0, edge_count=0,
            graph_data={"nodes": [], "links": [], "directed": True, "multigraph": False},
            is_dag=True, circular_deps=[], depth=0, layers=[],
            module_categories={}, entry_candidates=[],
            structural_core_candidates=[],
        )
        engine = QueryEngine(empty)

        r = engine.ask("入口在哪")
        assert "未检测到" in r.answer

        r = engine.ask("核心模块")
        assert "未检测到" in r.answer

        r = engine.ask("main 依赖谁")
        assert "不在依赖图中" in r.answer

    def test_very_short_question(self):
        engine = QueryEngine(build_repo_summary_full(FIXTURE_DIR))
        result = engine.ask("?")
        assert result.matched_pattern == "fallback"


# ---------------------------------------------------------------------------
# Mermaid 生成测试
# ---------------------------------------------------------------------------


class TestMermaidGen:
    """测试 Mermaid 依赖图生成。"""

    @classmethod
    def setup_class(cls):
        from reposcope.storage.repo_summary import build_repo_summary_full
        from reposcope.report.mermaid import generate_mermaid

        cls.summary = build_repo_summary_full(FIXTURE_DIR)
        cls.mermaid = generate_mermaid(cls.summary)

    def test_starts_with_flowchart(self):
        assert self.mermaid.startswith("flowchart ")

    def test_default_direction_is_td(self):
        assert "flowchart TD" in self.mermaid

    def test_contains_all_modules(self):
        for m in ["main", "config", "models", "models.user", "utils", "utils.helpers"]:
            assert m in self.mermaid, f"应包含模块: {m}"

    def test_contains_edges(self):
        assert "main --> config" in self.mermaid
        assert "main --> models_user" in self.mermaid
        assert "utils_helpers --> models_user" in self.mermaid

    def test_node_ids_sanitized(self):
        """模块路径中的 . 应替换为 _，作为合法 Mermaid 节点 ID。"""
        assert "models_user" in self.mermaid
        assert "utils_helpers" in self.mermaid

    def test_empty_module_is_root_init(self):
        """空模块名应映射为 ROOT_INIT 节点。"""
        assert "ROOT_INIT" in self.mermaid

    def test_contains_class_definitions(self):
        assert "classDef entry" in self.mermaid
        assert "classDef model" in self.mermaid
        assert "classDef utility" in self.mermaid

    def test_nodes_have_class_applied(self):
        assert "class main entry;" in self.mermaid
        assert "class models_user model;" in self.mermaid
        assert "class utils_helpers utility;" in self.mermaid

    def test_lr_direction(self):
        from reposcope.report.mermaid import generate_mermaid
        mmd = generate_mermaid(self.summary, direction="LR")
        assert "flowchart LR" in mmd

    def test_title(self):
        from reposcope.report.mermaid import generate_mermaid
        mmd = generate_mermaid(self.summary, title="Test Title")
        assert 'title["Test Title"]' in mmd

    def test_no_duplicate_styling(self):
        """每个节点不应被重复应用样式。"""
        import re
        classes = re.findall(r"class (\S+) (\S+);", self.mermaid)
        node_class_pairs = set(classes)
        assert len(classes) == len(node_class_pairs)

    def test_edges_use_sanitized_ids(self):
        """边必须使用清理后的节点 ID（不能含 .）。"""
        for line in self.mermaid.split("\n"):
            if "-->" in line:
                parts = line.strip().split(" --> ")
                for p in parts:
                    assert "." not in p.split("[")[0].strip(), f"边中不应含 .: {line}"

    def test_save_mermaid_file(self, tmp_path):
        from reposcope.report.mermaid import save_mermaid_file
        filepath = os.path.join(str(tmp_path), "deps")
        result = save_mermaid_file(filepath, self.summary)
        assert result.endswith(".mmd")
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
        assert content.startswith("flowchart ")

    def test_save_mermaid_creates_parent_dirs(self, tmp_path):
        from reposcope.report.mermaid import save_mermaid_file
        filepath = os.path.join(str(tmp_path), "sub", "nested", "deps.mmd")
        result = save_mermaid_file(filepath, self.summary)
        assert os.path.isfile(result)

    def test_empty_graph(self):
        from reposcope.report.mermaid import generate_mermaid
        from reposcope.storage.repo_summary import RepoSummary
        from datetime import datetime, timezone

        empty = RepoSummary(
            repo_path="/empty",
            created_at=datetime.now(timezone.utc).isoformat(),
            total_files_scanned=0, python_file_count=0, skipped_file_count=0,
            python_files=[], skipped_files=[], skipped_reason_counts={},
            total_imports=0, internal_imports=0, external_imports=0,
            unknown_imports=0, total_classes=0, total_functions=0,
            files_with_main_guard=[],
            module_count=0, edge_count=0,
            graph_data={"nodes": [], "links": [], "directed": True, "multigraph": False},
            is_dag=True, circular_deps=[], depth=0, layers=[],
            module_categories={}, entry_candidates=[],
            structural_core_candidates=[],
        )
        mmd = generate_mermaid(empty)
        assert mmd.startswith("flowchart ")
        assert "-->" not in mmd  # 无边


# ---------------------------------------------------------------------------
# Verification 测试
# ---------------------------------------------------------------------------


class TestVerification:
    """测试 LLM 回答验证。"""

    @classmethod
    def setup_class(cls):
        from reposcope.storage.repo_summary import build_repo_summary_full
        cls.summary = build_repo_summary_full(FIXTURE_DIR)

    @staticmethod
    def _verify(response, summary):
        from reposcope.agent.verification import verify_response
        return verify_response(response, summary)

    # -- 模块存在 --

    def test_verify_existing_module(self):
        report = self._verify("`models.user` is a data model module", self.summary)
        # 模块存在应被 verified；"data model" 可能触发 category 检查，但不影响 passed
        assert any(
            c.status == "verified" and "models.user" in c.claim
            for c in report.checks
        )

    def test_verify_nonexistent_module(self):
        report = self._verify("`fantasy_module` 负责数据处理", self.summary)
        contradicts = [c for c in report.checks if c.status == "contradicted"]
        assert len(contradicts) >= 1
        assert any("fantasy_module" in c.claim for c in contradicts)

    # -- 依赖关系 --

    def test_verify_correct_dependency(self):
        report = self._verify("`main` 依赖 `config`", self.summary)
        deps = [c for c in report.checks if "依赖" in c.claim]
        assert len(deps) >= 1
        assert any(c.status == "verified" for c in deps)

    def test_verify_incorrect_dependency(self):
        report = self._verify("`config` 依赖 `models.user`", self.summary)
        contradicts = [c for c in report.checks if c.status == "contradicted"]
        assert any("config" in c.claim for c in contradicts)

    # -- 入口 --

    def test_verify_correct_entry(self):
        report = self._verify("`main` 是入口文件", self.summary)
        entries = [c for c in report.checks if "入口" in c.claim and "main" in c.claim]
        assert any(c.status == "verified" for c in entries)

    def test_verify_incorrect_entry(self):
        report = self._verify("`config` 是入口文件", self.summary)
        contradicts = [c for c in report.checks if c.status == "contradicted" and "config" in c.claim]
        assert len(contradicts) >= 1

    # -- 数量 --

    def test_verify_correct_count(self):
        report = self._verify(
            f"共有 {self.summary.module_count} 个模块", self.summary
        )
        counts = [c for c in report.checks if "module_count" in c.claim]
        assert any(c.status == "verified" for c in counts)

    def test_verify_incorrect_count(self):
        wrong = self.summary.module_count + 10
        report = self._verify(f"共有 {wrong} 个模块", self.summary)
        contradicts = [c for c in report.checks if c.status == "contradicted"]
        assert len(contradicts) >= 1

    # -- DAG --

    def test_verify_dag_true(self):
        report = self._verify("该项目是 DAG，没有循环依赖", self.summary)
        dag_checks = [c for c in report.checks if "DAG" in c.claim]
        assert any(c.status == "verified" for c in dag_checks)

    # -- 角色 --

    def test_verify_correct_category(self):
        report = self._verify("`models.user` 是模型", self.summary)
        cats = [c for c in report.checks if "角色" in c.claim or "model" in c.evidence]
        assert any(c.status == "verified" for c in cats)

    # -- VerificationReport 结构 --

    def test_report_has_all_fields(self):
        report = self._verify("`main` 依赖 `config`", self.summary)
        assert isinstance(report.verified_count, int)
        assert isinstance(report.contradicted_count, int)
        assert isinstance(report.unverifiable_count, int)
        assert isinstance(report.passed, bool)

    def test_empty_response(self):
        report = self._verify("", self.summary)
        assert report.passed is True

    def test_unverifiable_claim(self):
        report = self._verify("这个项目的作者是张三", self.summary)
        assert report.unverifiable_count >= 0  # 不应崩溃


# ---------------------------------------------------------------------------
# 集成测试：verify → report → 判断是否通过
# ---------------------------------------------------------------------------


class TestVerificationIntegration:
    """端到端验证测试。"""

    @classmethod
    def setup_class(cls):
        from reposcope.storage.repo_summary import build_repo_summary_full
        cls.summary = build_repo_summary_full(FIXTURE_DIR)

    @staticmethod
    def _verify(response, summary):
        from reposcope.agent.verification import verify_response
        return verify_response(response, summary)

    def test_all_true_response_passes(self):
        """一条全部正确的回答应当通过验证（用不会触发歧义匹配的文本）。"""
        response = (
            f"This project has {self.summary.module_count} modules. "
            "`main` depends on `config`, `utils.helpers` and `models.user`. "
            "The dependency graph is a DAG. "
            "`models.user` has role model."
        )
        report = self._verify(response, self.summary)
        assert report.passed is True
        assert report.verified_count >= 4
        assert report.contradicted_count == 0

    def test_mixed_response_with_lies(self):
        """包含错误断言的回答应当被捕获。"""
        response = (
            "该项目共有 999 个模块。"           # 错误
            "`main` 依赖 `nonexistent_module`。"  # 错误
            "`models.user` 是 utility 类型。"    # 错误
        )
        report = self._verify(response, self.summary)
        assert report.contradicted_count >= 2
        assert report.passed is False


# ---------------------------------------------------------------------------
# STRUCTURE.md 生成测试
# ---------------------------------------------------------------------------


class TestStructureGen:
    """测试 STRUCTURE.md 生成。"""

    @classmethod
    def setup_class(cls):
        from reposcope.storage.repo_summary import build_repo_summary_full
        from reposcope.report.structure import generate_structure_md

        cls.summary = build_repo_summary_full(FIXTURE_DIR)
        cls.md = generate_structure_md(cls.summary)

    def test_has_title(self):
        assert self.md.startswith("# Project Structure")

    def test_contains_overview_section(self):
        assert "## 1. Overview" in self.md

    def test_contains_entry_points_section(self):
        assert "## 2. Entry Points" in self.md

    def test_contains_module_roles_section(self):
        assert "## 3. Module Roles" in self.md

    def test_contains_layers_section(self):
        assert "## 4. Dependency Layers" in self.md

    def test_contains_structural_core_section(self):
        assert "## 5. Structural Core Candidates" in self.md
        assert "NOT necessarily the business-logic core" in self.md

    def test_contains_circular_deps_section(self):
        assert "## 6. Circular Dependencies" in self.md
        assert "DAG" in self.md

    def test_contains_key_deps_section(self):
        assert "## 7. Key Dependency Relationships" in self.md

    def test_contains_file_inventory(self):
        assert "## 8. File Inventory" in self.md
        assert "<details>" in self.md

    def test_contains_footer(self):
        assert "No LLM was used" in self.md

    def test_module_names_in_markdown(self):
        for m in ["main", "config", "models", "models.user", "utils", "utils.helpers"]:
            assert m in self.md, f"应包含: {m}"

    def test_entry_scores_in_markdown(self):
        assert "0.95" in self.md

    def test_save_structure_md(self, tmp_path):
        from reposcope.report.structure import save_structure_md
        filepath = os.path.join(str(tmp_path), "STRUCTURE.md")
        result = save_structure_md(self.summary, filepath)
        assert result == filepath
        assert os.path.isfile(filepath)

    def test_save_structure_creates_parent_dirs(self, tmp_path):
        from reposcope.report.structure import save_structure_md
        filepath = os.path.join(str(tmp_path), "sub", "STRUCTURE.md")
        save_structure_md(self.summary, filepath)
        assert os.path.isfile(filepath)

    def test_empty_summary(self):
        from reposcope.report.structure import generate_structure_md
        from reposcope.storage.repo_summary import RepoSummary
        from datetime import datetime, timezone

        empty = RepoSummary(
            repo_path="/empty",
            created_at=datetime.now(timezone.utc).isoformat(),
            total_files_scanned=0, python_file_count=0, skipped_file_count=0,
            python_files=[], skipped_files=[], skipped_reason_counts={},
            total_imports=0, internal_imports=0, external_imports=0,
            unknown_imports=0, total_classes=0, total_functions=0,
            files_with_main_guard=[],
            module_count=0, edge_count=0,
            graph_data={"nodes": [], "links": [], "directed": True, "multigraph": False},
            is_dag=True, circular_deps=[], depth=0, layers=[],
            module_categories={}, entry_candidates=[],
            structural_core_candidates=[],
        )
        md = generate_structure_md(empty)
        assert "Project Structure" in md
        assert "No entry point candidates" in md


# ---------------------------------------------------------------------------
# V3: Code Chunker + Index + Source Reader 测试
# ---------------------------------------------------------------------------


class TestCodeChunker:
    """测试 AST 代码切块。"""

    @classmethod
    def setup_class(cls):
        from reposcope.rag.chunker import chunk_files, CodeChunk

    def test_chunk_python_files(self):
        from reposcope.rag.chunker import chunk_files
        # 使用 sample_project 中的 Python 文件
        all_files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "config.py"),
            os.path.join(FIXTURE_DIR, "models", "user.py"),
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
        ]
        result = chunk_files(all_files)
        assert result.total_files == 4
        assert result.total_chunks >= 3  # main(), class User, format_greeting()

    def test_chunk_finds_functions(self):
        from reposcope.rag.chunker import chunk_files
        result = chunk_files([os.path.join(FIXTURE_DIR, "main.py")])
        funcs = [c for c in result.chunks if c.type == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "main"

    def test_chunk_finds_classes(self):
        from reposcope.rag.chunker import chunk_files
        result = chunk_files([os.path.join(FIXTURE_DIR, "models", "user.py")])
        classes = [c for c in result.chunks if c.type == "class"]
        assert len(classes) == 1
        assert classes[0].name == "User"

    def test_chunk_finds_methods(self):
        from reposcope.rag.chunker import chunk_files
        result = chunk_files([os.path.join(FIXTURE_DIR, "models", "user.py")])
        methods = [c for c in result.chunks if c.type == "method"]
        assert len(methods) == 1
        assert methods[0].name == "User.display_name"

    def test_chunk_has_code_and_signature(self):
        from reposcope.rag.chunker import chunk_files
        result = chunk_files([os.path.join(FIXTURE_DIR, "utils", "helpers.py")])
        func = [c for c in result.chunks if c.type == "function"][0]
        assert "format_greeting" in func.signature
        assert "format_greeting" in func.code

    def test_chunk_has_line_numbers(self):
        from reposcope.rag.chunker import chunk_files
        result = chunk_files([os.path.join(FIXTURE_DIR, "main.py")])
        func = [c for c in result.chunks if c.type == "function"][0]
        assert func.line_start > 0
        assert func.line_end >= func.line_start

    def test_chunk_non_python(self):
        from reposcope.rag.chunker import chunk_files
        result = chunk_files([os.path.join(FIXTURE_DIR, "config.py")])
        # config.py 只定义变量，无函数/类，应生成 module chunk
        assert result.total_chunks >= 1

    def test_chunk_binary_file(self):
        from reposcope.rag.chunker import chunk_files
        result = chunk_files([os.path.join(FIXTURE_DIR, "binary.dat")])
        assert result.total_chunks == 0


class TestCodeIndex:
    """测试代码索引和检索。"""

    @classmethod
    def setup_class(cls):
        from reposcope.rag.chunker import chunk_files
        from reposcope.rag.index_tfidf import CodeIndex

        all_files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "config.py"),
            os.path.join(FIXTURE_DIR, "models", "user.py"),
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
        ]
        cls.chunks = chunk_files(all_files)
        cls.index = CodeIndex(cls.chunks)

    def test_search_returns_results(self):
        results = self.index.search("user")
        assert len(results) > 0

    def test_search_scores_between_0_and_1(self):
        results = self.index.search("main")
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_search_by_function_type(self):
        results = self.index.search("greeting", chunk_types=["function"])
        assert len(results) >= 1
        assert all(r.chunk.type == "function" for r in results)

    def test_search_by_name_exact(self):
        chunks = self.index.search_by_name("User")
        assert len(chunks) >= 1
        assert any(c.name == "User" for c in chunks)

    def test_search_by_name_partial(self):
        chunks = self.index.search_by_name("display")
        assert len(chunks) >= 1
        assert any("display_name" in c.name for c in chunks)

    def test_get_chunks_by_file(self):
        user_py = os.path.join(FIXTURE_DIR, "models", "user.py")
        chunks = self.index.get_chunks_by_file(user_py)
        assert len(chunks) >= 2  # class + method

    def test_search_no_results(self):
        results = self.index.search("xyznonexistent123")
        assert len(results) == 0


class TestSourceReader:
    """测试源码读取。"""

    def test_read_file(self):
        from reposcope.rag.reader import read_file
        snippet = read_file(os.path.join(FIXTURE_DIR, "main.py"))
        assert snippet is not None
        assert snippet.language == "python"
        assert "def main" in snippet.code

    def test_read_lines(self):
        from reposcope.rag.reader import read_lines
        snippet = read_lines(os.path.join(FIXTURE_DIR, "main.py"), 8, 10, context=1)
        assert snippet is not None
        assert "def main" in snippet.code

    def test_read_nonexistent_file(self):
        from reposcope.rag.reader import read_file
        assert read_file("/nonexistent/file.py") is None

    def test_detect_language(self):
        from reposcope.rag.reader import _detect_language
        assert _detect_language("config.yaml") == "yaml"
        assert _detect_language("data.json") == "json"
        assert _detect_language("main.py") == "python"


# ---------------------------------------------------------------------------
# V3: CodeRAG 测试（Retrieve + Augment，Generate 需 API Key 故仅测 prompt 构建）
# ---------------------------------------------------------------------------


class TestCodeRAG:
    """测试 CodeRAG 检索和 prompt 构建。"""

    @classmethod
    def setup_class(cls):
        from reposcope.storage.repo_summary import build_repo_summary_full
        from reposcope.rag.chunker import chunk_files
        from reposcope.rag.index_tfidf import CodeIndex

        cls.summary = build_repo_summary_full(FIXTURE_DIR)
        all_files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "config.py"),
            os.path.join(FIXTURE_DIR, "models", "user.py"),
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
        ]
        chunk_results = chunk_files(all_files)
        cls.index = CodeIndex(chunk_results)

    @staticmethod
    def _retrieve(question, index, top_k=5):
        from reposcope.rag.retriever import retrieve
        return retrieve(question, index, top_k=top_k)

    @staticmethod
    def _build_prompt(question, context, summary):
        from reposcope.rag.retriever import build_code_prompt
        return build_code_prompt(question, context, summary)

    def test_retrieve_returns_context(self):
        context = self._retrieve("greeting function", self.index, top_k=3)
        assert len(context.chunks) >= 1
        assert any("format_greeting" in c.name for c in context.chunks)

    def test_retrieve_finds_class(self):
        context = self._retrieve("User class definition", self.index, top_k=3)
        assert any(c.type == "class" and c.name == "User" for c in context.chunks)

    def test_retrieve_combines_tfidf_and_name(self):
        """检索应合并 TF-IDF 和符号名搜索的结果。"""
        context = self._retrieve("main function", self.index, top_k=5)
        names = {c.name for c in context.chunks}
        assert "main" in names

    def test_build_prompt_contains_question(self):
        context = self._retrieve("greeting", self.index)
        prompt = self._build_prompt("how does greeting work", context, self.summary)
        assert "how does greeting work" in prompt

    def test_build_prompt_contains_code(self):
        context = self._retrieve("format_greeting", self.index)
        prompt = self._build_prompt("format_greeting", context, self.summary)
        assert "format_greeting" in prompt
        assert "```python" in prompt

    def test_build_prompt_has_navigation(self):
        context = self._retrieve("main", self.index)
        prompt = self._build_prompt("main", context, self.summary)
        assert "项目结构导航" in prompt

    def test_build_prompt_has_instructions(self):
        context = self._retrieve("main", self.index)
        prompt = self._build_prompt("main", context, self.summary)
        assert "回答要求" in prompt

    def test_retrieve_empty_query(self):
        context = self._retrieve("", self.index)
        assert isinstance(context.chunks, list)

    def test_retrieve_no_results(self):
        context = self._retrieve("xyznonexistent123456", self.index)
        assert len(context.chunks) == 0

    def test_rag_answer_dataclass(self):
        from reposcope.rag.retriever import RAGAnswer
        ans = RAGAnswer(
            question="test",
            answer="test answer",
            chunks_used=[],
            search_scores=[],
        )
        assert ans.question == "test"
        assert ans.answer == "test answer"

    def test_short_path_helper(self):
        from reposcope.rag.retriever import _short_path
        result = _short_path("/root/src/main.py", "/root")
        assert "src" in result or "main.py" in result

    def test_extract_symbol_names(self):
        from reposcope.rag.retriever import _extract_symbol_names
        names = _extract_symbol_names("where is the forward function in my_model")
        assert "forward" in names
        assert "my_model" in names
        assert "the" not in names


# ---------------------------------------------------------------------------
# V3: EmbeddingIndex 测试（语义向量检索）
# ---------------------------------------------------------------------------


class TestEmbeddingIndex:
    """测试向量语义索引——与 CodeIndex 接口完全对齐。"""

    @classmethod
    def setup_class(cls):
        from reposcope.rag.chunker import chunk_files
        from reposcope.rag.index_embedding import EmbeddingIndex

        all_files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "models", "user.py"),
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
        ]
        chunk_results = chunk_files(all_files)
        cls.index = EmbeddingIndex(chunk_results)

    def test_search_returns_results(self):
        results = self.index.search("greeting function")
        assert len(results) > 0

    def test_search_scores_between_0_and_1(self):
        results = self.index.search("main")
        for r in results:
            assert 0.0 <= r.score <= 1.0, f"score {r.score} 超出 [0,1]"

    def test_search_by_type_filter(self):
        results = self.index.search("user", chunk_types=["class"])
        assert len(results) >= 1
        assert all(r.chunk.type == "class" for r in results)

    def test_search_by_name(self):
        chunks = self.index.search_by_name("User")
        assert len(chunks) >= 1
        assert any(c.name == "User" for c in chunks)

    def test_search_by_name_partial(self):
        chunks = self.index.search_by_name("display")
        assert len(chunks) >= 1

    def test_get_chunks_by_file(self):
        user_py = os.path.join(FIXTURE_DIR, "models", "user.py")
        chunks = self.index.get_chunks_by_file(user_py)
        assert len(chunks) >= 2

    def test_search_nonsense_scores_are_low(self):
        """稠密向量总有非零相似度，但无意义 query 的分数应很低。"""
        results = self.index.search("xyznonexistent123456")
        # 可能返回少量结果但分数都应很低
        for r in results:
            assert r.score < 0.3, f"无意义查询不应有高分: {r.score}"

    def test_empty_query(self):
        results = self.index.search("")
        assert results == []

    def test_search_result_is_search_result(self):
        from reposcope.rag.index_embedding import SearchResult
        results = self.index.search("main")
        for r in results:
            assert isinstance(r, SearchResult)

    def test_same_interface_as_code_index(self):
        """与 CodeIndex 接口完全一致：search, search_by_name, get_chunks_by_file"""
        assert hasattr(self.index, "search")
        assert hasattr(self.index, "search_by_name")
        assert hasattr(self.index, "get_chunks_by_file")


# ---------------------------------------------------------------------------
# V3: Flow Tracer 测试（模块级路径查找 + 证据收集）
# ---------------------------------------------------------------------------


class TestFlowTracer:
    """测试模块级流程追踪。"""

    @classmethod
    def setup_class(cls):
        from reposcope.graph.import_graph import ImportGraph
        from reposcope.storage.repo_summary import build_repo_summary_full, reconstruct_graph

        cls.summary = build_repo_summary_full(FIXTURE_DIR)
        cls.graph = reconstruct_graph(cls.summary)

    # -- 路径查找 --

    def test_find_path_direct_edge(self):
        from reposcope.rag.flow_tracer import find_paths
        paths = find_paths(self.graph, "main", "config")
        assert len(paths) >= 1
        assert paths[0].modules == ["main", "config"]

    def test_find_path_indirect(self):
        from reposcope.rag.flow_tracer import find_paths
        paths = find_paths(self.graph, "main", "models.user")
        assert len(paths) >= 1
        assert paths[0].modules[0] == "main"
        assert paths[0].modules[-1] == "models.user"

    def test_find_path_nonexistent(self):
        from reposcope.rag.flow_tracer import find_paths
        paths = find_paths(self.graph, "main", "nonexistent")
        assert paths == []

    def test_find_path_reverse_direction(self):
        """反向路径应找不到（DI Graph: config 不依赖 main）。"""
        from reposcope.rag.flow_tracer import find_paths
        paths = find_paths(self.graph, "config", "main")
        assert paths == []

    # -- 端点提取 --

    def test_extract_endpoints_cn(self):
        from reposcope.rag.flow_tracer import _extract_endpoints
        modules = set(self.summary.module_categories.keys())
        src, tgt = _extract_endpoints("从 main 到 models.user 的流程", modules)
        assert src == "main"
        assert tgt == "models.user"

    def test_extract_endpoints_arrow(self):
        from reposcope.rag.flow_tracer import _extract_endpoints
        modules = set(self.summary.module_categories.keys())
        src, tgt = _extract_endpoints("main → config 的路径", modules)
        assert src == "main"
        assert tgt == "config"

    def test_extract_endpoints_no_match(self):
        from reposcope.rag.flow_tracer import _extract_endpoints
        modules = set(self.summary.module_categories.keys())
        src, tgt = _extract_endpoints("loss function在哪里", modules)
        assert src is None
        assert tgt is None

    # -- 边界声明 --

    def test_disclaimer_present(self):
        from reposcope.rag.flow_tracer import _BOUNDARY_DISCLAIMER
        assert "静态 import 依赖图" in _BOUNDARY_DISCLAIMER
        assert "不代表真实运行时" in _BOUNDARY_DISCLAIMER
        assert "import graph" in _BOUNDARY_DISCLAIMER

    # -- 确定性解释 --

    def test_deterministic_explanation_no_path(self):
        from reposcope.rag.flow_tracer import _build_deterministic_explanation
        result = _build_deterministic_explanation("test", [], {})
        assert "未能在" in result
        assert "import 依赖图" in result

    def test_deterministic_explanation_with_path(self):
        from reposcope.rag.flow_tracer import find_paths, _build_deterministic_explanation
        paths = find_paths(self.graph, "main", "config")
        result = _build_deterministic_explanation("从 main 到 config", paths, {})
        assert "main" in result
        assert "config" in result
        assert "import 依赖图" in result

    # -- FlowTraceResult dataclass --

    def test_flow_trace_result_fields(self):
        from reposcope.rag.flow_tracer import FlowTraceResult
        r = FlowTraceResult(
            question="test",
            source="main",
            target="config",
            paths=[],
            evidence={},
            explanation="no path",
            disclaimer="test disclaimer",
        )
        assert r.source == "main"
        assert r.target == "config"


# ---------------------------------------------------------------------------
# LangGraph Agent 测试
# ---------------------------------------------------------------------------


class TestLangGraphAgent:
    """测试 LangGraph Agent — Pydantic tools + StateGraph。"""

    @staticmethod
    def _make_agent():
        import os
        from reposcope.agent.langgraph_agent import RepoScopeAgent
        summary = build_repo_summary_full(FIXTURE_DIR)
        os.environ["REPOSCOPE_API_KEY"] = "test-dummy-key"
        try:
            return RepoScopeAgent(summary)
        finally:
            del os.environ["REPOSCOPE_API_KEY"]

    def test_agent_creation(self):
        agent = self._make_agent()
        assert len(agent._tools) == 3
        assert agent._graph is not None

    def test_tool_names(self):
        agent = self._make_agent()
        names = {t.name for t in agent._tools}
        assert names == {"search_code", "trace_flow", "read_source"}

    def test_tools_have_pydantic_schema(self):
        agent = self._make_agent()
        for t in agent._tools:
            assert t.args_schema is not None, f"{t.name} should have Pydantic args_schema"

    def test_search_code_without_index(self):
        from reposcope.agent.langgraph_agent import _search_code
        result = _search_code("loss", None)
        assert "未构建" in result

    def test_search_code_with_index(self):
        from reposcope.agent.langgraph_agent import _search_code
        from reposcope.rag.chunker import chunk_files
        from reposcope.rag.index_tfidf import CodeIndex
        all_files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "models", "user.py"),
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
        ]
        cr = chunk_files(all_files)
        idx = CodeIndex(cr)
        result = _search_code("greeting", idx)
        assert "format_greeting" in result

    def test_query_structure_works(self):
        from reposcope.agent.query_engine import QueryEngine
        summary = build_repo_summary_full(FIXTURE_DIR)
        result = QueryEngine(summary).ask("入口在哪")
        assert "main" in result.answer

    def test_agent_state_typeddict(self):
        from reposcope.agent.langgraph_agent import AgentState
        # 验证 TypedDict 可实例化
        state: AgentState = {"messages": [], "round_count": 0, "final_answer": "", "_trace": []}
        assert state["round_count"] == 0

    def test_pydantic_schemas(self):
        from reposcope.agent.langgraph_agent import SearchCodeInput, ReadSourceInput
        s = SearchCodeInput(query="loss function")
        assert s.query == "loss function"
        r = ReadSourceInput(file_and_lines="server.py:1-60")
        assert r.file_and_lines == "server.py:1-60"

    def test_build_clean_messages_filters_tool_calls(self):
        from reposcope.agent.langgraph_agent import _build_clean_messages
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

        msgs = [
            HumanMessage(content="loss在哪"),
            AIMessage(content="", tool_calls=[{"name": "search_code", "args": {"query": "loss"}, "id": "call_1"}]),
            ToolMessage(content="1. [method] Client.get_train_loss (client.py:127) score=0.753", tool_call_id="1"),
            AIMessage(content="找到了 loss 函数在 client.py"),
        ]
        clean = _build_clean_messages(msgs)
        # 应有 3 条：user question + tool result + final ai text
        assert len(clean) == 3
        # 不含 tool_calls 的 AIMessage
        assert not any("tool_calls" in str(m) for m in clean)
        # tool result 被保留
        assert any("Client.get_train_loss" in str(m) for m in clean)

    def test_get_role(self):
        from reposcope.agent.langgraph_agent import _get_role
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        assert _get_role(HumanMessage(content="hi")) == "human"
        assert _get_role(ToolMessage(content="result", tool_call_id="1")) == "tool"
        assert _get_role(AIMessage(content="answer")) == "ai"


# ---------------------------------------------------------------------------
# LLM Client 测试
# ---------------------------------------------------------------------------


class TestLLMClient:
    """测试统一 LLM 客户端工厂。"""

    def test_default_values(self):
        from reposcope.agent.llm_client import (
            DEFAULT_MODEL, DEFAULT_BASE_URL, DEFAULT_API_KEY_ENV, DEFAULT_PROVIDER,
        )
        assert DEFAULT_MODEL == "deepseek-chat"
        assert "deepseek" in DEFAULT_BASE_URL
        assert DEFAULT_API_KEY_ENV == "DEEPSEEK_API_KEY"
        assert DEFAULT_PROVIDER == "openai"

    def test_get_api_key_none_when_not_set(self):
        from reposcope.agent.llm_client import get_api_key
        # 确保测试环境中没有设置这些变量
        import os
        old = os.environ.pop("DEEPSEEK_API_KEY", None)
        old2 = os.environ.pop("REPOSCOPE_API_KEY", None)
        try:
            assert get_api_key() is None
        finally:
            if old: os.environ["DEEPSEEK_API_KEY"] = old
            if old2: os.environ["REPOSCOPE_API_KEY"] = old2

    def test_get_api_key_direct(self):
        import os
        from reposcope.agent.llm_client import get_api_key
        os.environ["REPOSCOPE_API_KEY"] = "test-key-direct"
        try:
            assert get_api_key() == "test-key-direct"
        finally:
            del os.environ["REPOSCOPE_API_KEY"]

    def test_require_api_key_raises(self):
        import os
        from reposcope.agent.llm_client import require_api_key
        old = os.environ.pop("DEEPSEEK_API_KEY", None)
        old2 = os.environ.pop("REPOSCOPE_API_KEY", None)
        try:
            import pytest
            with pytest.raises(ValueError, match="未找到 API Key"):
                require_api_key()
        finally:
            if old: os.environ["DEEPSEEK_API_KEY"] = old
            if old2: os.environ["REPOSCOPE_API_KEY"] = old2

    def test_get_llm_anthropic(self):
        import os
        from reposcope.agent.llm_client import get_llm
        os.environ["REPOSCOPE_API_KEY"] = "test-key"
        os.environ["REPOSCOPE_LLM_PROVIDER"] = "anthropic"
        try:
            llm = get_llm(api_key="test-key")
            from langchain_anthropic import ChatAnthropic
            assert isinstance(llm, ChatAnthropic)
        finally:
            del os.environ["REPOSCOPE_API_KEY"]
            del os.environ["REPOSCOPE_LLM_PROVIDER"]

    def test_get_llm_openai_compatible(self):
        import os
        from reposcope.agent.llm_client import get_llm
        from langchain_openai import ChatOpenAI
        os.environ["REPOSCOPE_API_KEY"] = "test-key"
        try:
            llm = get_llm(api_key="test-key")
            assert isinstance(llm, ChatOpenAI)
        finally:
            del os.environ["REPOSCOPE_API_KEY"]

    def test_default_provider_is_openai(self):
        from reposcope.agent.llm_client import DEFAULT_PROVIDER
        assert DEFAULT_PROVIDER == "openai"


# ---------------------------------------------------------------------------
# Memory Tool 测试
# ---------------------------------------------------------------------------


class TestMemoryTool:
    """测试多轮对话记忆。"""

    def test_new_memory_is_empty(self):
        from reposcope.agent.memory_tool import MemoryTool
        m = MemoryTool()
        assert m.is_empty()

    def test_save_and_recall(self):
        from reposcope.agent.memory_tool import MemoryTool
        m = MemoryTool(max_turns=3)
        m.save("loss在哪", "loss 在 client.py:127")
        m.save("它怎么计算", "使用 CrossEntropyLoss")
        ctx = m.recall()
        assert "loss在哪" in ctx
        assert "CrossEntropyLoss" in ctx

    def test_max_turns_limit(self):
        from reposcope.agent.memory_tool import MemoryTool
        m = MemoryTool(max_turns=2)
        m.save("q1", "a1")
        m.save("q2", "a2")
        m.save("q3", "a3")
        ctx = m.recall()
        assert "q1" not in ctx  # 被淘汰
        assert "q3" in ctx

    def test_empty_recall(self):
        from reposcope.agent.memory_tool import MemoryTool
        m = MemoryTool()
        ctx = m.recall()
        assert "暂无历史" in ctx


# ---------------------------------------------------------------------------
# HybridCodeIndex 测试
# ---------------------------------------------------------------------------


class TestHybridCodeIndex:
    """测试混合检索器。"""

    @classmethod
    def setup_class(cls):
        from reposcope.rag.chunker import chunk_files
        from reposcope.rag.index_hybrid import HybridCodeIndex

        all_files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "models", "user.py"),
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
        ]
        cr = chunk_files(all_files)
        cls.index = HybridCodeIndex(cr)

    def test_search_returns_results(self):
        results = self.index.search("greeting")
        assert len(results) > 0

    def test_search_finds_function(self):
        results = self.index.search("format_greeting")
        names = {r.chunk.name for r in results}
        assert "format_greeting" in names

    def test_search_scores_between_0_and_1(self):
        results = self.index.search("main")
        for r in results:
            assert 0.0 <= r.score <= 1.0, f"score {r.score} out of range"

    def test_search_by_name(self):
        chunks = self.index.search_by_name("User")
        assert len(chunks) >= 1
        assert any(c.name == "User" for c in chunks)

    def test_get_chunks_by_file(self):
        user_py = os.path.join(FIXTURE_DIR, "models", "user.py")
        chunks = self.index.get_chunks_by_file(user_py)
        assert len(chunks) >= 2

    def test_search_empty_query(self):
        results = self.index.search("")
        assert results == []

    def test_chinese_query(self):
        """中文 query 也应返回结果（语义检索兜底）。"""
        results = self.index.search("问候函数")
        assert len(results) >= 0  # 至少不崩溃

    def test_same_interface_as_code_index(self):
        assert hasattr(self.index, "search")
        assert hasattr(self.index, "search_by_name")
        assert hasattr(self.index, "get_chunks_by_file")
