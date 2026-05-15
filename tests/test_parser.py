"""测试 parser 模块。"""

import os
import pytest

from reposcope.parser.ast_extractor import ASTExtractor, ASTItem, FileASTResult
from reposcope.parser.import_classifier import (
    ClassificationResult,
    ClassifiedImport,
    classify_imports,
    _module_path,
    _package_of,
    _get_package,
    _resolve_relative,
    _top_level,
    _classify,
    _STDLIB_MODULES,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample_project")


# ---------------------------------------------------------------------------
# ASTExtractor 测试
# ---------------------------------------------------------------------------

class TestASTExtractor:
    """测试 ast_extractor.py"""

    @classmethod
    def setup_class(cls):
        cls.extractor = ASTExtractor()

    # -- main.py --

    def test_main_py_imports(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "main.py")
        )
        import_names = [(i.name, i.module, i.level) for i in result.imports]
        assert ("DEBUG", "config", 0) in import_names
        assert ("APP_NAME", "config", 0) in import_names
        assert ("format_greeting", "utils.helpers", 0) in import_names
        assert ("User", "models.user", 0) in import_names
        assert len(result.imports) == 4

    def test_main_py_functions(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "main.py")
        )
        func_names = [f.name for f in result.functions]
        assert "main" in func_names
        assert len(result.functions) == 1

    def test_main_py_main_guard(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "main.py")
        )
        assert result.main_guard is not None
        assert result.main_guard.type == "main_guard"
        assert result.main_guard.name == "__main__"

    def test_main_py_no_classes(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "main.py")
        )
        assert len(result.classes) == 0

    # -- config.py --

    def test_config_py_empty_structure(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "config.py")
        )
        assert len(result.imports) == 0
        assert len(result.classes) == 0
        assert len(result.functions) == 0
        assert result.main_guard is None

    # -- models/user.py --

    def test_user_py_classes(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "models", "user.py")
        )
        class_names = [c.name for c in result.classes]
        assert "User" in class_names
        assert len(result.classes) == 1

    def test_user_py_imports(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "models", "user.py")
        )
        assert len(result.imports) == 1
        imp = result.imports[0]
        assert imp.name == "dataclass"
        assert imp.module == "dataclasses"
        assert imp.level == 0

    def test_user_py_functions(self):
        """顶层函数检测 — 类方法不会被提取为顶层 function。"""
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "models", "user.py")
        )
        assert len(result.functions) == 0

    # -- utils/helpers.py --

    def test_helpers_py_functions(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "utils", "helpers.py")
        )
        func_names = [f.name for f in result.functions]
        assert "format_greeting" in func_names
        assert len(result.functions) == 1

    def test_helpers_py_imports(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "utils", "helpers.py")
        )
        assert len(result.imports) == 1
        imp = result.imports[0]
        assert imp.name == "User"
        assert imp.module == "models.user"
        assert imp.level == 0

    # -- models/__init__.py (相对导入) --

    def test_models_init_relative_import(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "models", "__init__.py")
        )
        assert len(result.imports) == 1
        imp = result.imports[0]
        assert imp.name == "User"
        assert imp.module == "user"
        assert imp.level == 1

    # -- utils/__init__.py (相对导入) --

    def test_utils_init_relative_import(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "utils", "__init__.py")
        )
        assert len(result.imports) == 1
        imp = result.imports[0]
        assert imp.name == "format_greeting"
        assert imp.module == "helpers"
        assert imp.level == 1

    # -- 通用 --

    def test_file_field_present(self):
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "main.py")
        )
        for imp in result.imports:
            assert os.path.isabs(imp.file)
            assert imp.line > 0

    def test_extract_all(self):
        files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "config.py"),
        ]
        results = self.extractor.extract_all(files)
        assert len(results) == 2
        assert results[0].file == files[0]
        assert results[1].file == files[1]

    def test_syntax_error_returns_empty(self):
        """语法错误的文件应返回空结果，不抛出异常。"""
        result = self.extractor.extract(
            os.path.join(FIXTURE_DIR, "binary.dat")
        )
        assert result.file.endswith("binary.dat")
        assert len(result.imports) == 0
        assert len(result.classes) == 0
        assert len(result.functions) == 0
        assert result.main_guard is None

    def test_plain_import_style(self, tmp_path):
        """`import X` 和 `import X as Y` 风格的导入应正确提取。"""
        filepath = os.path.join(str(tmp_path), "test_plain_import.py")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("import os\nimport sys as system\nimport json, re\n")
        result = self.extractor.extract(filepath)
        assert len(result.imports) == 4  # os, system, json, re
        names = [(i.name, i.module, i.level) for i in result.imports]
        assert ("os", "os", 0) in names
        assert ("system", "sys", 0) in names
        assert ("json", "json", 0) in names
        assert ("re", "re", 0) in names


# ---------------------------------------------------------------------------
# Import 分类器测试
# ---------------------------------------------------------------------------

class TestImportClassifier:
    """测试 import_classifier.py"""

    @classmethod
    def setup_class(cls):
        cls.extractor = ASTExtractor()
        cls.root = FIXTURE_DIR
        cls.all_files = [
            os.path.join(FIXTURE_DIR, "main.py"),
            os.path.join(FIXTURE_DIR, "config.py"),
            os.path.join(FIXTURE_DIR, "models", "__init__.py"),
            os.path.join(FIXTURE_DIR, "models", "user.py"),
            os.path.join(FIXTURE_DIR, "utils", "__init__.py"),
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"),
        ]
        cls.ast_results = cls.extractor.extract_all(cls.all_files)
        cls.classification = classify_imports(cls.ast_results, cls.root)

    def _imports_for(self, filename: str) -> list[ClassifiedImport]:
        target = os.path.join(FIXTURE_DIR, filename)
        for cr in self.classification:
            if cr.file == target:
                return cr.imports
        return []

    def test_main_py_internal_imports(self):
        imports = self._imports_for("main.py")
        for imp in imports:
            assert imp.category == "internal", (
                f"main.py 导入 {imp.resolved_module} 应为 internal"
            )

    def test_user_py_external_import(self):
        imports = self._imports_for(os.path.join("models", "user.py"))
        assert len(imports) == 1
        assert imports[0].resolved_module == "dataclasses"
        assert imports[0].category == "external"

    def test_helpers_py_internal_import(self):
        imports = self._imports_for(os.path.join("utils", "helpers.py"))
        assert len(imports) == 1
        assert imports[0].resolved_module == "models.user"
        assert imports[0].category == "internal"

    def test_relative_import_resolved_internal(self):
        """models/__init__.py 的 from .user import User 解析为 models.user（内部）。"""
        imports = self._imports_for(os.path.join("models", "__init__.py"))
        assert len(imports) == 1
        assert imports[0].module == "user"
        assert imports[0].level == 1
        assert imports[0].resolved_module == "models.user"
        assert imports[0].category == "internal"

    def test_utils_init_relative_import(self):
        imports = self._imports_for(os.path.join("utils", "__init__.py"))
        assert len(imports) == 1
        assert imports[0].resolved_module == "utils.helpers"
        assert imports[0].category == "internal"

    def test_config_py_no_imports(self):
        imports = self._imports_for("config.py")
        assert len(imports) == 0

    def test_classified_import_has_all_fields(self):
        imports = self._imports_for("main.py")
        for imp in imports:
            assert os.path.isabs(imp.file)
            assert imp.line > 0
            assert imp.name
            assert isinstance(imp.module, str)
            assert isinstance(imp.level, int)
            assert imp.resolved_module
            assert imp.category in ("internal", "external", "unknown")

    def test_all_imports_categorized(self):
        for cr in self.classification:
            for imp in cr.imports:
                assert imp.category in ("internal", "external", "unknown"), (
                    f"{imp.file}:{imp.line} {imp.name} 未正确分类"
                )

    def test_classification_result_structure(self):
        for cr in self.classification:
            assert isinstance(cr, ClassificationResult)
            assert os.path.isabs(cr.file)
            assert isinstance(cr.imports, list)


# ---------------------------------------------------------------------------
# 辅助函数单元测试
# ---------------------------------------------------------------------------

class TestModulePath:
    """测试模块路径计算。"""

    def test_regular_file(self):
        p = _module_path(
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"), FIXTURE_DIR
        )
        assert p == "utils.helpers"

    def test_init_file(self):
        p = _module_path(
            os.path.join(FIXTURE_DIR, "models", "__init__.py"), FIXTURE_DIR
        )
        assert p == "models"

    def test_root_file(self):
        p = _module_path(
            os.path.join(FIXTURE_DIR, "config.py"), FIXTURE_DIR
        )
        assert p == "config"


class TestPackageOf:
    """测试 _package_of 和 _get_package。"""

    def test_nested_module(self):
        assert _package_of("models.user") == "models"

    def test_top_level_module(self):
        assert _package_of("config") == ""

    def test_no_parent_package(self):
        assert _package_of("models") == ""

    # -- _get_package --

    def test_get_package_init_file(self):
        p = _get_package(
            os.path.join(FIXTURE_DIR, "models", "__init__.py"), FIXTURE_DIR
        )
        assert p == "models"

    def test_get_package_regular_file(self):
        p = _get_package(
            os.path.join(FIXTURE_DIR, "utils", "helpers.py"), FIXTURE_DIR
        )
        assert p == "utils"

    def test_get_package_root_file(self):
        p = _get_package(
            os.path.join(FIXTURE_DIR, "config.py"), FIXTURE_DIR
        )
        assert p == ""

    def test_get_package_root_init(self):
        p = _get_package(
            os.path.join(FIXTURE_DIR, "__init__.py"), FIXTURE_DIR
        )
        assert p == ""


class TestResolveRelative:
    """测试相对导入解析。"""

    def test_absolute_import(self):
        assert _resolve_relative("", 0, "os") == "os"

    def test_current_package_level1(self):
        assert _resolve_relative("models", 1, "user") == "models.user"

    def test_parent_package_level2(self):
        assert _resolve_relative("utils.helpers", 2, "other") == "utils.other"

    def test_empty_module_level1(self):
        """from . import X"""
        assert _resolve_relative("models", 1, "") == "models"

    def test_beyond_root(self):
        """相对导入层级超过已知包层级。"""
        # 当包为空字符串（根级 __init__.py）且 level=2 时，超出项目根
        assert _resolve_relative("", 2, "other") == ""


class TestTopLevel:
    """测试 _top_level"""

    def test_top_level_simple(self):
        assert _top_level("os") == "os"

    def test_top_level_nested(self):
        assert _top_level("os.path") == "os"

    def test_top_level_empty(self):
        assert _top_level("") == ""


class TestSTDLIB:
    """验证常用标准库在列表中。"""

    def test_common_stdlib_present(self):
        for m in ["os", "sys", "ast", "json", "collections", "dataclasses",
                   "typing", "re", "math", "pathlib", "subprocess"]:
            assert m in _STDLIB_MODULES, f"{m} 应在 _STDLIB_MODULES 中"

    def test_project_modules_not_in_stdlib(self):
        """确保项目内的模块名不在标准库列表中。"""
        for m in ["config", "main", "models", "utils"]:
            assert m not in _STDLIB_MODULES, f"{m} 不应在 _STDLIB_MODULES 中"


class TestClassify:
    """测试 _classify 函数。"""

    def test_exact_internal_match(self):
        assert _classify("config", {"config", "models"}) == "internal"

    def test_submodule_internal(self):
        assert _classify("models.user", {"models"}) == "internal"

    def test_stdlib_external(self):
        assert _classify("os", set()) == "external"

    def test_third_party_external(self):
        assert _classify("numpy", set()) == "external"

    def test_unknown_empty(self):
        assert _classify("", set()) == "unknown"
