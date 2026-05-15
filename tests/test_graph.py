"""测试 graph 模块。"""

import os

import networkx as nx

from reposcope.parser.ast_extractor import ASTExtractor
from reposcope.parser.import_classifier import classify_imports
from reposcope.graph.import_graph import (
    ImportGraph,
    build_import_graph,
    get_dependencies,
    get_entry_points,
    get_importers,
    get_leaf_modules,
    get_module_summary,
    get_root_modules,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample_project")


# ---------------------------------------------------------------------------
# 测试辅助：构建 sample_project 的依赖图
# ---------------------------------------------------------------------------

ALL_FILES = [
    os.path.join(FIXTURE_DIR, "main.py"),
    os.path.join(FIXTURE_DIR, "config.py"),
    os.path.join(FIXTURE_DIR, "models", "__init__.py"),
    os.path.join(FIXTURE_DIR, "models", "user.py"),
    os.path.join(FIXTURE_DIR, "utils", "__init__.py"),
    os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
]


def _build_sample_graph() -> ImportGraph:
    extractor = ASTExtractor()
    ast_results = extractor.extract_all(ALL_FILES)
    classification = classify_imports(ast_results, FIXTURE_DIR)
    return build_import_graph(ast_results, classification, FIXTURE_DIR)


# ---------------------------------------------------------------------------
# build_import_graph 测试
# ---------------------------------------------------------------------------


class TestBuildImportGraph:
    """测试图的构建。"""

    @classmethod
    def setup_class(cls):
        cls.graph = _build_sample_graph()

    def test_is_digraph(self):
        assert isinstance(self.graph.graph, nx.DiGraph)

    def test_node_count(self):
        assert self.graph.node_count() == 6

    def test_edge_count(self):
        assert self.graph.edge_count() == 6

    def test_all_expected_nodes(self):
        for m in ["main", "config", "models", "models.user", "utils", "utils.helpers"]:
            assert self.graph.has_module(m), f"图中应包含节点: {m}"

    def test_edge_main_to_config(self):
        assert self.graph.graph.has_edge("main", "config")
        edge = self.graph.graph.edges["main", "config"]
        assert edge["imported_name"] in ("DEBUG", "APP_NAME")
        assert edge["line"] > 0

    def test_edge_main_to_utils_helpers(self):
        assert self.graph.graph.has_edge("main", "utils.helpers")
        edge = self.graph.graph.edges["main", "utils.helpers"]
        assert edge["imported_name"] == "format_greeting"

    def test_edge_main_to_models_user(self):
        assert self.graph.graph.has_edge("main", "models.user")
        edge = self.graph.graph.edges["main", "models.user"]
        assert edge["imported_name"] == "User"

    def test_edge_helpers_to_models_user(self):
        assert self.graph.graph.has_edge("utils.helpers", "models.user")
        edge = self.graph.graph.edges["utils.helpers", "models.user"]
        assert edge["imported_name"] == "User"

    def test_edge_models_init_to_user(self):
        """相对导入 from .user import User 产生的边。"""
        assert self.graph.graph.has_edge("models", "models.user")

    def test_edge_utils_init_to_helpers(self):
        """相对导入 from .helpers import format_greeting 产生的边。"""
        assert self.graph.graph.has_edge("utils", "utils.helpers")

    def test_no_external_edges(self):
        """确保外部 import 没有成为边（如 dataclasses）。"""
        for u, v in self.graph.graph.edges:
            assert v != "dataclasses"

    def test_node_attributes_present(self):
        for node in self.graph.graph.nodes:
            attrs = self.graph.graph.nodes[node]
            assert "file_path" in attrs
            assert "classes" in attrs
            assert "functions" in attrs
            assert "has_main_guard" in attrs

    def test_main_has_main_guard(self):
        assert self.graph.graph.nodes["main"]["has_main_guard"] is True

    def test_config_no_main_guard(self):
        assert self.graph.graph.nodes["config"]["has_main_guard"] is False

    def test_models_user_has_class(self):
        assert "User" in self.graph.graph.nodes["models.user"]["classes"]

    def test_main_has_function(self):
        assert "main" in self.graph.graph.nodes["main"]["functions"]

    def test_helpers_has_function(self):
        assert "format_greeting" in self.graph.graph.nodes["utils.helpers"]["functions"]

    def test_config_is_empty_module(self):
        node = self.graph.graph.nodes["config"]
        assert node["classes"] == []
        assert node["functions"] == []
        assert node["has_main_guard"] is False

    def test_get_file_roundtrip(self):
        """模块路径 → 文件路径 映射。"""
        f = self.graph.get_file("models.user")
        assert f is not None
        assert f.endswith(os.path.join("models", "user.py"))

    def test_get_module_roundtrip(self):
        m = self.graph.get_module(ALL_FILES[0])
        assert m == "main"

    def test_get_file_unknown(self):
        assert self.graph.get_file("nonexistent") is None

    def test_get_module_unknown(self):
        assert self.graph.get_module("/nonexistent/file.py") is None


# ---------------------------------------------------------------------------
# 查询辅助函数测试
# ---------------------------------------------------------------------------


class TestQueryHelpers:
    """测试图查询辅助函数。"""

    @classmethod
    def setup_class(cls):
        cls.graph = _build_sample_graph()

    # -- get_entry_points --

    def test_entry_points_contains_main(self):
        entries = get_entry_points(self.graph)
        assert "main" in entries

    def test_entry_points_excludes_config(self):
        entries = get_entry_points(self.graph)
        assert "config" not in entries

    # -- get_dependencies --

    def test_dependencies_main(self):
        deps = get_dependencies(self.graph, "main")
        assert sorted(deps) == ["config", "models.user", "utils.helpers"]

    def test_dependencies_config(self):
        deps = get_dependencies(self.graph, "config")
        assert deps == []

    def test_dependencies_unknown_module(self):
        deps = get_dependencies(self.graph, "nonexistent")
        assert deps == []

    # -- get_importers --

    def test_importers_models_user(self):
        importers = get_importers(self.graph, "models.user")
        assert sorted(importers) == ["main", "models", "utils.helpers"]

    def test_importers_main(self):
        importers = get_importers(self.graph, "main")
        assert importers == []

    def test_importers_unknown_module(self):
        importers = get_importers(self.graph, "nonexistent")
        assert importers == []

    # -- get_leaf_modules --

    def test_leaf_modules(self):
        leaves = get_leaf_modules(self.graph)
        assert sorted(leaves) == ["config", "models.user"]

    # -- get_root_modules --

    def test_root_modules(self):
        roots = get_root_modules(self.graph)
        assert sorted(roots) == ["main", "models", "utils"]

    # -- get_module_summary --

    def test_summary_main(self):
        s = get_module_summary(self.graph, "main")
        assert s is not None
        assert s["module"] == "main"
        assert "main" in s["functions"]
        assert s["has_main_guard"] is True
        assert len(s["dependencies"]) == 3
        assert s["imported_by"] == []

    def test_summary_models_user(self):
        s = get_module_summary(self.graph, "models.user")
        assert s is not None
        assert "User" in s["classes"]
        assert len(s["dependencies"]) == 0
        assert len(s["imported_by"]) == 3

    def test_summary_unknown_module(self):
        assert get_module_summary(self.graph, "nonexistent") is None


# ---------------------------------------------------------------------------
# 边界情况测试
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """测试边界情况。"""

    def test_empty_project(self):
        """空项目（无 Python 文件）应生成空图。"""
        g = build_import_graph([], [], FIXTURE_DIR)
        assert g.node_count() == 0
        assert g.edge_count() == 0
        assert get_entry_points(g) == []
        assert get_leaf_modules(g) == []
        assert get_root_modules(g) == []

    def test_no_internal_imports(self):
        """纯外部导入的项目。"""
        extractor = ASTExtractor()
        config_file = os.path.join(FIXTURE_DIR, "config.py")
        ast_results = extractor.extract_all([config_file])
        classification = classify_imports(ast_results, FIXTURE_DIR)
        g = build_import_graph(ast_results, classification, FIXTURE_DIR)
        assert g.node_count() == 1
        assert g.edge_count() == 0
        assert g.has_module("config")

    def test_graph_is_dag(self):
        """sample_project 的依赖图应为 DAG（无循环导入）。"""
        g = _build_sample_graph()
        assert nx.is_directed_acyclic_graph(g.graph)
