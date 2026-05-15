"""测试 analyzer 模块。"""

import os

from reposcope.parser.ast_extractor import ASTExtractor
from reposcope.parser.import_classifier import classify_imports
from reposcope.graph.import_graph import ImportGraph, build_import_graph
from reposcope.analyzer.entry_detector import (
    EntryCandidate,
    CoreModuleCandidate,
    detect_entries,
    rank_core_modules,
)
from reposcope.analyzer.architecture import (
    ArchitectureProfile,
    categorize_modules,
    compute_layers,
    detect_circular_deps,
    profile_architecture,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample_project")

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


def _build_ast_results() -> list:
    return ASTExtractor().extract_all(ALL_FILES)


# ---------------------------------------------------------------------------
# detect_entries 测试
# ---------------------------------------------------------------------------


class TestDetectEntries:
    """测试入口检测。"""

    @classmethod
    def setup_class(cls):
        cls.graph = _build_sample_graph()
        cls.ast_results = _build_ast_results()
        cls.entries = detect_entries(cls.graph, cls.ast_results)

    def test_returns_list_of_entry_candidates(self):
        assert isinstance(self.entries, list)
        for e in self.entries:
            assert isinstance(e, EntryCandidate)

    def test_main_is_top_entry(self):
        assert len(self.entries) > 0
        assert self.entries[0].module == "main"

    def test_main_score_is_high(self):
        main = next(e for e in self.entries if e.module == "main")
        assert main.score > 0.5

    def test_main_has_main_guard_signal(self):
        main = next(e for e in self.entries if e.module == "main")
        assert "main_guard" in main.signals
        assert "root_module" in main.signals
        assert "has_main_in_name" in main.signals

    def test_config_not_in_entries(self):
        modules = [e.module for e in self.entries]
        assert "config" not in modules

    def test_models_user_not_in_entries(self):
        modules = [e.module for e in self.entries]
        assert "models.user" not in modules

    def test_scores_are_descending(self):
        scores = [e.score for e in self.entries]
        assert scores == sorted(scores, reverse=True)

    def test_each_entry_has_file(self):
        for e in self.entries:
            assert os.path.isabs(e.file)
            assert e.file != ""

    def test_signals_are_valid(self):
        valid = {"main_guard", "root_module", "high_out_degree",
                  "has_main_in_name", "leaf_with_functions"}
        for e in self.entries:
            for s in e.signals:
                assert s in valid, f"未知信号: {s}"

    def test_empty_graph_returns_empty(self):
        empty_graph = build_import_graph([], [], FIXTURE_DIR)
        result = detect_entries(empty_graph, [])
        assert result == []


# ---------------------------------------------------------------------------
# rank_core_modules 测试
# ---------------------------------------------------------------------------


class TestRankCoreModules:
    """测试核心模块排序。"""

    @classmethod
    def setup_class(cls):
        cls.graph = _build_sample_graph()
        cls.ranking = rank_core_modules(cls.graph)

    def test_returns_list_of_candidates(self):
        assert isinstance(self.ranking, list)
        for c in self.ranking:
            assert isinstance(c, CoreModuleCandidate)

    def test_all_modules_ranked(self):
        assert len(self.ranking) == 6

    def test_models_user_is_top_core(self):
        assert self.ranking[0].module == "models.user"

    def test_models_user_has_highest_in_degree(self):
        top = self.ranking[0]
        for c in self.ranking[1:]:
            assert top.in_degree >= c.in_degree

    def test_utils_helpers_ranks_high(self):
        modules = [c.module for c in self.ranking[:3]]
        assert "utils.helpers" in modules

    def test_scores_between_0_and_1(self):
        for c in self.ranking:
            assert 0.0 <= c.score <= 1.0

    def test_scores_are_descending(self):
        scores = [c.score for c in self.ranking]
        assert scores == sorted(scores, reverse=True)

    def test_fields_not_empty(self):
        for c in self.ranking:
            assert c.module
            assert os.path.isabs(c.file)
            assert c.in_degree >= 0
            assert c.out_degree >= 0
            assert c.betweenness >= 0.0
            assert c.pagerank >= 0.0

    def test_main_has_low_score(self):
        main = next(c for c in self.ranking if c.module == "main")
        assert main.in_degree == 0

    def test_empty_graph_returns_empty(self):
        empty_graph = build_import_graph([], [], FIXTURE_DIR)
        result = rank_core_modules(empty_graph)
        assert result == []


# ---------------------------------------------------------------------------
# profile_architecture 测试
# ---------------------------------------------------------------------------


class TestArchitectureProfile:
    """测试架构画像。"""

    @classmethod
    def setup_class(cls):
        cls.graph = _build_sample_graph()
        cls.ast_results = _build_ast_results()
        cls.profile = profile_architecture(cls.graph, cls.ast_results)

    def test_returns_architecture_profile(self):
        assert isinstance(self.profile, ArchitectureProfile)

    def test_module_and_edge_count(self):
        assert self.profile.module_count == 6
        assert self.profile.edge_count == 6

    def test_is_dag(self):
        assert self.profile.is_dag is True

    def test_no_circular_deps(self):
        assert self.profile.circular_deps == []

    def test_depth(self):
        assert self.profile.depth == 3

    def test_layers_structure(self):
        layers = self.profile.layers
        assert len(layers) == 3
        # 第 0 层：无入边的模块
        assert sorted(layers[0]) == ["main", "models", "utils"]
        # 第 1 层
        assert sorted(layers[1]) == ["config", "utils.helpers"]
        # 第 2 层
        assert layers[2] == ["models.user"]

    def test_categories_all_modules(self):
        assert len(self.profile.categories) == 6
        for m in ["main", "config", "models", "models.user", "utils", "utils.helpers"]:
            assert m in self.profile.categories, f"缺少: {m}"

    def test_category_main_is_entry(self):
        assert self.profile.categories["main"] == "entry"

    def test_category_config_is_config(self):
        assert self.profile.categories["config"] == "config"

    def test_category_models_is_package_init(self):
        assert self.profile.categories["models"] == "package_init"

    def test_category_utils_is_package_init(self):
        assert self.profile.categories["utils"] == "package_init"

    def test_category_models_user_is_model(self):
        assert self.profile.categories["models.user"] == "model"

    def test_category_utils_helpers_is_utility(self):
        assert self.profile.categories["utils.helpers"] == "utility"

    def test_entry_points(self):
        assert self.profile.entry_points == ["main"]

    def test_root_modules(self):
        assert sorted(self.profile.root_modules) == ["main", "models", "utils"]

    def test_leaf_modules(self):
        assert sorted(self.profile.leaf_modules) == ["config", "models.user"]


# ---------------------------------------------------------------------------
# 子函数单元测试
# ---------------------------------------------------------------------------


class TestCircularDeps:
    """测试循环依赖检测。"""

    def test_no_cycles_in_sample(self):
        graph = _build_sample_graph()
        cycles = detect_circular_deps(graph)
        assert cycles == []

    def test_empty_graph(self):
        empty_graph = build_import_graph([], [], FIXTURE_DIR)
        assert detect_circular_deps(empty_graph) == []


class TestComputeLayers:
    """测试拓扑分层。"""

    def test_layer_count(self):
        graph = _build_sample_graph()
        layers = compute_layers(graph)
        assert len(layers) == 3

    def test_first_layer_no_incoming(self):
        graph = _build_sample_graph()
        layers = compute_layers(graph)
        for node in layers[0]:
            assert graph.graph.in_degree(node) == 0

    def test_all_nodes_present(self):
        graph = _build_sample_graph()
        layers = compute_layers(graph)
        all_nodes = set()
        for layer in layers:
            all_nodes.update(layer)
        assert all_nodes == set(graph.graph.nodes)

    def test_layer_order_respected(self):
        """验证每一层的节点只依赖更外层（编号更小）的节点。"""
        graph = _build_sample_graph()
        layers = compute_layers(graph)
        layer_index: dict[str, int] = {}
        for i, layer in enumerate(layers):
            for node in layer:
                layer_index[node] = i
        for u, v in graph.graph.edges:
            assert layer_index[u] < layer_index[v], (
                f"边 {u}→{v} 违反拓扑序: layer[{u}]={layer_index[u]}, layer[{v}]={layer_index[v]}"
            )

    def test_empty_graph(self):
        empty_graph = build_import_graph([], [], FIXTURE_DIR)
        assert compute_layers(empty_graph) == []


class TestCategorizeModules:
    """测试模块角色分类。"""

    @classmethod
    def setup_class(cls):
        cls.graph = _build_sample_graph()
        cls.ast_results = _build_ast_results()
        ast_by_module = {}
        for r in cls.ast_results:
            m = cls.graph.get_module(r.file)
            if m is not None:
                ast_by_module[m] = r
        cls.categories = categorize_modules(cls.graph, ast_by_module)

    def test_all_modules_categorized(self):
        for m in ["main", "config", "models", "models.user", "utils", "utils.helpers"]:
            assert m in self.categories

    def test_valid_categories(self):
        valid = {"entry", "config", "model", "utility", "package_init",
                 "orchestrator", "leaf", "module"}
        for cat in self.categories.values():
            assert cat in valid, f"未知分类: {cat}"

    def test_empty_graph(self):
        empty_graph = build_import_graph([], [], FIXTURE_DIR)
        assert categorize_modules(empty_graph, {}) == {}


# ---------------------------------------------------------------------------
# 边界情况：有循环依赖的图
# ---------------------------------------------------------------------------


class TestCyclicGraph:
    """测试循环依赖图的处理。"""

    @classmethod
    def setup_class(cls):
        import networkx as nx
        from reposcope.graph.import_graph import ImportGraph

        # 手工构造一个带环的 ImportGraph
        g = nx.DiGraph()
        g.add_node("a", file_path="/fake/a.py", classes=[], functions=[], has_main_guard=False)
        g.add_node("b", file_path="/fake/b.py", classes=[], functions=[], has_main_guard=False)
        g.add_node("c", file_path="/fake/c.py", classes=[], functions=[], has_main_guard=False)
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "a")  # 形成环 a→b→c→a

        cls.graph = ImportGraph(
            graph=g,
            root_path="/fake",
            _module_to_file={},
            _file_to_module={},
        )

    def test_detect_cycle(self):
        cycles = detect_circular_deps(self.graph)
        assert len(cycles) > 0

    def test_profile_not_dag(self):
        from reposcope.analyzer.architecture import profile_architecture
        profile = profile_architecture(self.graph, [])
        assert profile.is_dag is False

    def test_layers_handles_cycle(self):
        layers = compute_layers(self.graph)
        all_nodes = set()
        for layer in layers:
            all_nodes.update(layer)
        assert all_nodes == {"a", "b", "c"}
