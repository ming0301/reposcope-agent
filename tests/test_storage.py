"""测试 storage 模块。"""

import json
import os

import networkx as nx

from reposcope.storage.repo_summary import (
    RepoSummary,
    build_repo_summary_full,
    load_repo_summary,
    reconstruct_graph,
    save_repo_summary,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample_project")


# ---------------------------------------------------------------------------
# build_repo_summary_full 测试
# ---------------------------------------------------------------------------


class TestBuildRepoSummaryFull:
    """测试完整管线构建 RepoSummary。"""

    @classmethod
    def setup_class(cls):
        cls.summary = build_repo_summary_full(FIXTURE_DIR)

    def test_returns_repo_summary(self):
        assert isinstance(self.summary, RepoSummary)

    def test_repo_path(self):
        assert self.summary.repo_path == os.path.abspath(FIXTURE_DIR)

    def test_created_at_is_iso(self):
        assert "T" in self.summary.created_at

    # -- Scanner 部分 --

    def test_scanner_section(self):
        assert self.summary.total_files_scanned > 0
        assert self.summary.python_file_count >= 7
        assert self.summary.skipped_file_count > 0

    def test_python_files_absolute(self):
        for f in self.summary.python_files:
            assert os.path.isabs(f)

    def test_skipped_files_have_reason(self):
        for s in self.summary.skipped_files:
            assert "path" in s
            assert "reason" in s

    # -- Parser 部分 --

    def test_parser_section(self):
        assert self.summary.total_imports > 0
        assert self.summary.internal_imports > 0
        assert self.summary.external_imports > 0
        # internal + external + unknown == total
        assert (
            self.summary.internal_imports
            + self.summary.external_imports
            + self.summary.unknown_imports
            == self.summary.total_imports
        )

    def test_total_classes(self):
        assert self.summary.total_classes >= 1  # User class in models/user.py

    def test_total_functions(self):
        assert self.summary.total_functions >= 2  # main(), format_greeting()

    def test_files_with_main_guard(self):
        mg_files = [os.path.basename(f) for f in self.summary.files_with_main_guard]
        assert "main.py" in mg_files

    # -- Graph 部分 --

    def test_graph_section(self):
        assert self.summary.module_count >= 6
        assert self.summary.edge_count >= 6

    def test_graph_data_has_nodes_and_links(self):
        assert "nodes" in self.summary.graph_data
        assert "links" in self.summary.graph_data
        assert len(self.summary.graph_data["nodes"]) == self.summary.module_count
        assert len(self.summary.graph_data["links"]) == self.summary.edge_count

    # -- Analyzer 部分 --

    def test_analyzer_section(self):
        assert self.summary.is_dag is True
        assert self.summary.circular_deps == []
        assert self.summary.depth >= 2
        assert len(self.summary.layers) == self.summary.depth

    def test_module_categories(self):
        assert len(self.summary.module_categories) == self.summary.module_count

    def test_entry_candidates(self):
        assert len(self.summary.entry_candidates) >= 1
        main_candidate = next(
            (e for e in self.summary.entry_candidates if e["module"] == "main"), None
        )
        assert main_candidate is not None
        assert main_candidate["score"] > 0.5

    def test_structural_core_candidates_naming(self):
        """验证字段名使用 structural_core_candidates。"""
        assert hasattr(self.summary, "structural_core_candidates")
        cores = self.summary.structural_core_candidates
        assert len(cores) >= 1
        # models.user 应排在前面（被依赖最多）
        assert cores[0]["module"] == "models.user"
        assert cores[0]["in_degree"] >= 3

    def test_structural_core_fields(self):
        cores = self.summary.structural_core_candidates
        for c in cores:
            assert "module" in c
            assert "file" in c
            assert "score" in c
            assert "in_degree" in c
            assert "out_degree" in c
            assert "betweenness" in c
            assert "pagerank" in c
            assert 0.0 <= c["score"] <= 1.0
            assert 0.0 <= c["betweenness"] <= 1.0
            assert 0.0 <= c["pagerank"] <= 1.0


# ---------------------------------------------------------------------------
# save / load round-trip 测试
# ---------------------------------------------------------------------------


class TestSaveLoad:
    """测试保存和加载的完整往返。"""

    @classmethod
    def setup_class(cls):
        cls.summary = build_repo_summary_full(FIXTURE_DIR)

    def test_save_creates_file(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        assert os.path.isfile(filepath)

    def test_saved_json_is_valid(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "repo_path" in data
        assert "scanner" in data
        assert "parser" in data
        assert "graph" in data
        assert "analyzer" in data

    def test_saved_json_has_structural_core(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "structural_core_candidates" in data["analyzer"]

    def test_roundtrip_repo_path(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        assert loaded.repo_path == self.summary.repo_path

    def test_roundtrip_scanner(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        assert loaded.python_file_count == self.summary.python_file_count
        assert loaded.total_files_scanned == self.summary.total_files_scanned
        assert loaded.skipped_file_count == self.summary.skipped_file_count

    def test_roundtrip_parser(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        assert loaded.total_imports == self.summary.total_imports
        assert loaded.internal_imports == self.summary.internal_imports
        assert loaded.total_classes == self.summary.total_classes
        assert loaded.total_functions == self.summary.total_functions

    def test_roundtrip_graph(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        assert loaded.module_count == self.summary.module_count
        assert loaded.edge_count == self.summary.edge_count
        assert len(loaded.graph_data["nodes"]) == self.summary.module_count
        assert len(loaded.graph_data["links"]) == self.summary.edge_count

    def test_roundtrip_analyzer(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        assert loaded.is_dag == self.summary.is_dag
        assert loaded.depth == self.summary.depth
        assert loaded.layers == self.summary.layers
        assert loaded.module_categories == self.summary.module_categories

    def test_roundtrip_structural_core(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        assert len(loaded.structural_core_candidates) == len(
            self.summary.structural_core_candidates
        )
        assert loaded.structural_core_candidates[0]["module"] == "models.user"

    def test_roundtrip_entry_candidates(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        assert len(loaded.entry_candidates) == len(self.summary.entry_candidates)

    def test_reconstruct_graph(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        g = reconstruct_graph(loaded)
        assert isinstance(g, nx.DiGraph)
        assert g.number_of_nodes() == self.summary.module_count
        assert g.number_of_edges() == self.summary.edge_count

    def test_reconstructed_graph_has_node_attrs(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        g = reconstruct_graph(loaded)
        node = g.nodes["main"]
        assert "file_path" in node
        assert "has_main_guard" in node
        assert node["has_main_guard"] is True

    def test_reconstructed_graph_has_edge_attrs(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        loaded = load_repo_summary(filepath)
        g = reconstruct_graph(loaded)
        assert g.has_edge("main", "models.user")
        edge = g.edges["main", "models.user"]
        assert "imported_name" in edge
        assert "line" in edge

    def test_json_indent_pretty_print(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        assert len(lines) > 10  # 缩进良好，不止一行

    def test_save_creates_parent_dirs(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "sub", "nested", "repo_summary.json")
        save_repo_summary(self.summary, filepath)
        assert os.path.isfile(filepath)


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """测试边界情况。"""

    def test_full_pipeline_on_empty_dir(self, tmp_path):
        """空目录应有空的 RepoSummary。"""
        import tempfile
        with tempfile.TemporaryDirectory() as empty_dir:
            summary = build_repo_summary_full(empty_dir)
            assert isinstance(summary, RepoSummary)
            assert summary.total_files_scanned == 0
            assert summary.python_file_count == 0
            assert summary.module_count == 0
            assert summary.edge_count == 0
            assert summary.structural_core_candidates == []
            assert summary.entry_candidates == []

    def test_save_load_empty_summary(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "empty.json")
        summary = build_repo_summary_full(FIXTURE_DIR)
        save_repo_summary(summary, filepath)
        loaded = load_repo_summary(filepath)
        assert isinstance(loaded, RepoSummary)

    def test_json_all_sections_present(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "sections.json")
        summary = build_repo_summary_full(FIXTURE_DIR)
        save_repo_summary(summary, filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in ["repo_path", "created_at", "scanner", "parser", "graph", "analyzer"]:
            assert key in data, f"JSON 中缺少顶层键: {key}"
