"""测试 RepoScopeSession。"""

import os


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample_project")


class TestRepoScopeSession:
    """测试 Session API（不依赖 LLM 的部分）。"""

    @classmethod
    def setup_class(cls):
        """确保 repo_summary.json 存在。"""
        json_path = os.path.join(FIXTURE_DIR, ".reposcope", "repo_summary.json")
        if not os.path.isfile(json_path):
            from reposcope.storage.repo_summary import build_repo_summary_full, save_repo_summary
            summary = build_repo_summary_full(FIXTURE_DIR)
            save_repo_summary(summary, json_path)

    def test_session_init_structure(self):
        """验证 Session 创建后内部组件完整。"""
        os.environ["REPOSCOPE_API_KEY"] = "test-dummy"
        try:
            from reposcope.session import RepoScopeSession
            session = RepoScopeSession(FIXTURE_DIR)
            # 组件都存在
            assert session._summary is not None
            assert session._code_index is not None
            assert session._agent is not None
            assert session._memory is not None
            assert session.memory.is_empty()
        finally:
            del os.environ["REPOSCOPE_API_KEY"]

    def test_session_summary(self):
        from reposcope.session import RepoScopeSession
        os.environ["REPOSCOPE_API_KEY"] = "test-dummy"
        try:
            session = RepoScopeSession(FIXTURE_DIR)
            s = session.summary()
            assert s["python_files"] >= 7
            assert s["modules"] >= 6
            assert s["is_dag"] is True
            assert len(s["entry_points"]) >= 1
        finally:
            del os.environ["REPOSCOPE_API_KEY"]

    def test_session_repo_path(self):
        from reposcope.session import RepoScopeSession
        os.environ["REPOSCOPE_API_KEY"] = "test-dummy"
        try:
            session = RepoScopeSession(FIXTURE_DIR)
            assert session.repo_path == os.path.abspath(FIXTURE_DIR)
        finally:
            del os.environ["REPOSCOPE_API_KEY"]

    def test_session_prints_summary(self, capsys):
        from reposcope.session import RepoScopeSession
        os.environ["REPOSCOPE_API_KEY"] = "test-dummy"
        try:
            session = RepoScopeSession(FIXTURE_DIR)
            session.print_summary()
            captured = capsys.readouterr()
            assert "Python" in captured.out or "模块" in captured.out
        finally:
            del os.environ["REPOSCOPE_API_KEY"]
