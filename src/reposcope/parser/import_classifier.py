"""
Import 分类器 — 区分内部 import、外部 import、unknown import。

支持普通 import、from import、相对 import。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .ast_extractor import ASTItem, FileASTResult

# Python 3.9 标准库模块名全集
_STDLIB_MODULES: set[str] = {
    "__future__", "__main__", "_thread", "abc", "aifc", "argparse", "array",
    "ast", "asynchat", "asyncio", "asyncore", "atexit", "audioop", "base64",
    "bdb", "binascii", "binhex", "bisect", "builtins", "bz2", "calendar",
    "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs", "codeop",
    "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "cProfile", "crypt",
    "csv", "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal",
    "difflib", "dis", "distutils", "doctest", "email", "encodings", "enum",
    "errno", "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
    "formatter", "fractions", "ftplib", "functools", "gc", "getopt",
    "getpass", "gettext", "glob", "graphlib", "grp", "gzip", "hashlib",
    "heapq", "hmac", "html", "http", "idlelib", "imaplib", "imghdr",
    "imp", "importlib", "inspect", "io", "ipaddress", "itertools", "json",
    "keyword", "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox",
    "mailcap", "marshal", "math", "mimetypes", "mmap", "modulefinder",
    "msilib", "msvcrt", "multiprocessing", "netrc", "nis", "nntplib",
    "numbers", "operator", "optparse", "os", "ossaudiodev", "parser", "pathlib",
    "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "posixpath", "pprint", "profile", "pstats", "pty",
    "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random", "re",
    "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched",
    "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal",
    "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "sqlite3",
    "ssl", "stat", "statistics", "string", "stringprep", "struct", "subprocess",
    "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
    "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "trace", "traceback",
    "tracemalloc", "tty", "turtle", "turtledemo", "types", "typing",
    "unicodedata", "unittest", "urllib", "uu", "uuid", "venv", "warnings",
    "wave", "weakref", "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib",
    "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    # 常用第三方工具通常被误判为 stdlib，不在此列表中
}


@dataclass
class ClassifiedImport:
    """分类后的 import 条目。"""

    file: str
    line: int
    name: str
    module: str
    level: int
    resolved_module: str   # 解析后的完整模块路径
    category: str          # "internal" | "external" | "unknown"


@dataclass
class ClassificationResult:
    """单个文件的 import 分类结果。"""

    file: str
    imports: list[ClassifiedImport]


def _module_path(filepath: str, root: str) -> str:
    """将文件路径转为相对 root 的模块路径。

    /abs/root/utils/helpers.py → utils.helpers
    /abs/root/models/__init__.py → models
    /abs/root/config.py → config
    """
    rel = os.path.relpath(filepath, root)
    if rel.endswith("__init__.py"):
        rel = os.path.dirname(rel)
    else:
        rel = os.path.splitext(rel)[0]
    return rel.replace(os.sep, ".").replace("/", ".").lstrip(".")


def _package_of(module_path: str) -> str:
    """返回模块路径的父包名。

    models.user → models
    models → ''（顶层模块没有父包）
    config → ''
    """
    parts = module_path.rsplit(".", 1)
    return parts[0] if len(parts) > 1 else ""


def _get_package(filepath: str, root: str) -> str:
    """返回文件相对导入解析时使用的包上下文。

    __init__.py 文件的包上下文是它自身代表的包；
    普通文件的包上下文是其父包。
    """
    rel = os.path.relpath(filepath, root)
    is_init = os.path.basename(filepath) == "__init__.py"
    if is_init:
        rel_dir = os.path.dirname(rel)
        if rel_dir in ("", "."):
            return ""
        return rel_dir.replace(os.sep, ".").replace("/", ".")
    module_path = _module_path(filepath, root)
    return _package_of(module_path)


def _resolve_relative(package: str, level: int, module: str) -> str:
    """将相对导入解析为绝对模块路径。

    package: 当前文件所在的包（如 'models'）
    level: 相对导入点数（1 = 当前包，2 = 父包，...）
    module: from 语句中 . 后的模块名
    """
    if level == 0:
        return module
    parts = package.split(".") if package else []
    keep = len(parts) - (level - 1)
    if keep < 0:
        # 相对导入超出已知项目层级
        return ""
    base = ".".join(parts[:keep]) if keep > 0 else ""
    if module:
        return f"{base}.{module}" if base else module
    return base


def _top_level(module: str) -> str:
    """返回模块的顶级包名。"""
    return module.split(".")[0] if module else ""


def classify_imports(
    ast_results: list[FileASTResult],
    root_path: str,
) -> list[ClassificationResult]:
    """对 AST 提取结果中的所有 import 进行分类。

    Args:
        ast_results: ASTExtractor.extract_all() 的返回结果
        root_path: 项目根目录（用于计算内部模块路径）

    Returns:
        分类后的 import 列表（按文件组织）
    """
    # 构建内部模块路径集合
    internal_modules: set[str] = set()
    for result in ast_results:
        internal_modules.add(_module_path(result.file, root_path))

    output: list[ClassificationResult] = []

    for result in ast_results:
        package = _get_package(result.file, root_path)
        classified: list[ClassifiedImport] = []

        for imp in result.imports:
            resolved = _resolve_relative(package, imp.level or 0, imp.module or "")
            category = _classify(resolved, internal_modules)
            classified.append(ClassifiedImport(
                file=imp.file,
                line=imp.line,
                name=imp.name,
                module=imp.module or "",
                level=imp.level or 0,
                resolved_module=resolved,
                category=category,
            ))

        output.append(ClassificationResult(file=result.file, imports=classified))

    return output


def _classify(resolved_module: str, internal_modules: set[str]) -> str:
    """判断单个 import 的分类。"""
    if not resolved_module:
        return "unknown"
    # 精确匹配或前缀匹配（子模块也算内部）
    if resolved_module in internal_modules:
        return "internal"
    # 检查是否为内部模块的子模块
    for im in internal_modules:
        if resolved_module.startswith(im + "."):
            return "internal"
    # 检查顶级包是否为标准库
    top = _top_level(resolved_module)
    if top in _STDLIB_MODULES:
        return "external"
    # 其余视为外部第三方包
    return "external"
