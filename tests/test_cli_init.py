"""cli.py / agents_init.py / 入口：参数解析、退出码、init 全流程（含配置自动入 gitignore）。"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.helpers import git, init_repo

from iyp import agents_init, cli


class TestCliParsing(unittest.TestCase):
    def test_help_exit_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["help"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("iyp init", out)
        self.assertIn("iyp check", out)
        self.assertIn("--dir", out)
        self.assertIn("--raw", out)

    def test_version_exits(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()):
                cli.main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_no_subcommand_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                cli.main([])
        self.assertEqual(cm.exception.code, 2)

    def test_mutually_exclusive_scope(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                cli.main(["check", "--git", "--tracked"])
        self.assertEqual(cm.exception.code, 2)

    def test_check_dispatch_stage(self):
        with mock.patch("iyp.checker.cmd_check", return_value=0) as m:
            rc = cli.main(["check", "--stage", "--strict", "--raw", "/tmp/x"])
        self.assertEqual(rc, 0)
        args = m.call_args[0][0]
        self.assertIn("--stage", args)
        self.assertIn("--strict", args)
        self.assertIn("--raw", args)
        self.assertEqual(args[0], "/tmp/x")

    def test_check_dispatch_default_dir(self):
        with mock.patch("iyp.checker.cmd_check", return_value=0) as m:
            cli.main(["check"])
        args = m.call_args[0][0]
        self.assertFalse(any(a in args for a in ("--stage", "--git", "--tracked")))


class TestInitFlow(unittest.TestCase):
    """init 全流程（交互用 mock 喂答案）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        self.root.mkdir(parents=True)
        self._old = os.environ.get("IYP_HOME")
        # 隔离工具根：模板从真实仓库取，工具配置写到临时目录
        self._toolhome = Path(self._tmp.name) / "toolhome"
        (self._toolhome / "templates").mkdir(parents=True)
        import shutil
        real = Path(__file__).resolve().parents[1] / "src" / "iyp" / "templates"
        for f in real.iterdir():
            shutil.copy(f, self._toolhome / "templates" / f.name)
        os.environ["IYP_HOME"] = str(self._toolhome)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("IYP_HOME", None)
        else:
            os.environ["IYP_HOME"] = self._old
        self._tmp.cleanup()

    def _run_init(self, answers, existing_gitignore=None):
        if existing_gitignore is not None:
            (self.root / ".gitignore").write_text(existing_gitignore, encoding="utf-8")
        it = iter(answers)
        with mock.patch("builtins.input", lambda *a, **k: next(it)), \
             redirect_stdout(io.StringIO()):
            rc = agents_init.cmd_init([str(self.root)])
        return rc

    def test_full_init_creates_templates_and_gitignore(self):
        # 语言=1(python)，AI目录=n，追加确认=y，创建配置=y
        rc = self._run_init(["1", "n", "y"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "AGENTS.md").exists())
        self.assertTrue((self.root / "README.md").exists())
        self.assertTrue((self.root / ".gitignore").exists())
        gi = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", gi)
        self.assertIn("# --- Python ---", gi)
        # 无过时 iyp 段
        self.assertNotIn("iyp 工具自身", gi)

    def test_config_file_auto_gitignored(self):
        rc = self._run_init(["1", "n", "y"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "iyp.toml").exists())
        gi = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("iyp.toml", gi)
        # 真正被 git 忽略
        init_repo(self.root)
        r = git(self.root, "check-ignore", "iyp.toml", check=False)
        self.assertEqual(r.returncode, 0, "iyp.toml 应被 git 忽略")

    def test_config_file_declined(self):
        rc = self._run_init(["1", "n", "n"])
        self.assertEqual(rc, 0)
        self.assertFalse((self.root / "iyp.toml").exists())

    def test_existing_gitignore_appends_grouped(self):
        rc = self._run_init(["1", "n", "y", "n"],
                            existing_gitignore="# mine\nnode_modules/\n")
        self.assertEqual(rc, 0)
        gi = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(gi.startswith("# mine\nnode_modules/\n"))
        self.assertIn("# --- Python ---", gi)
        self.assertIn("# --- 日志文件 ---", gi)

    def test_git_init_performed(self):
        self._run_init(["", "n", "n"])   # 不选语言、不建配置
        r = git(self.root, "rev-parse", "--is-inside-work-tree", check=False)
        self.assertEqual(r.returncode, 0)


class TestEntryPoints(unittest.TestCase):
    def test_root_iyp_runs_version(self):
        import subprocess
        repo = Path(__file__).resolve().parents[1]
        r = subprocess.run([sys.executable, str(repo / "iyp"), "--version"],
                           capture_output=True, text=True)
        from iyp import __version__
        self.assertEqual(r.returncode, 0)
        self.assertIn(__version__, r.stdout)

    def test_pkg_iyp_runs_version(self):
        import subprocess
        repo = Path(__file__).resolve().parents[1]
        r = subprocess.run([sys.executable, str(repo / "src" / "iyp" / "iyp"), "--version"],
                           capture_output=True, text=True)
        from iyp import __version__
        self.assertEqual(r.returncode, 0)
        self.assertIn(__version__, r.stdout)


if __name__ == "__main__":
    unittest.main()
