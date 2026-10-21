"""checker.py：关键词构建、扫描、白名单、脱敏、二进制探测、四种 scope。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import (FAKE_AWS, FAKE_AWS2, FAKE_DB_URL, commit_all, grp,
                           init_repo, make_cfg, ip)

from scripts import checker


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestBuildPatterns(unittest.TestCase):
    def test_patterns_compiled(self):
        cfg = make_cfg([grp("t", r"AKIA[0-9A-Z]{16}", "high")])
        pats = checker.build_patterns(cfg)
        self.assertEqual(len(pats), 1)
        self.assertIn("_re", pats[0])
        self.assertTrue(pats[0]["_re"].search(f"{FAKE_AWS}"))

    def test_group_without_pattern_skipped(self):
        cfg = make_cfg([{"name": "x", "description": "no pattern"}])
        self.assertEqual(checker.build_patterns(cfg), [])

    def test_defaults_have_no_dup_names(self):
        from scripts.defaults import all_default_keywords
        names = [g["name"] for g in all_default_keywords()]
        self.assertEqual(len(names), len(set(names)), f"重复组名: {names}")


class TestScanBasics(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _scan(self, cfg):
        files = checker._collect_dir_files(self.root)
        return checker.scan(self.root, cfg, files)

    def test_hit_and_line_number(self):
        _write(self.root, "a.txt", f"hello\n{FAKE_AWS}\nbye\n")
        cfg = make_cfg([grp("aws", r"AKIA[0-9A-Z]{16}", "high")])
        hits = self._scan(cfg)
        self.assertEqual(len(hits), 1)
        h = hits[0]
        self.assertEqual(h.rel, "a.txt")
        self.assertEqual(h.lineno, 2)
        self.assertEqual(h.severity, "high")
        self.assertEqual(h.match_text, f"{FAKE_AWS}")
        # 上下文各 1 行
        self.assertEqual([c[0] for c in h.context], [1, 3])

    def test_one_hit_per_line_first_group_wins(self):
        _write(self.root, "a.txt", f"{FAKE_AWS}\n")
        cfg = make_cfg([grp("g1", r"AKIA[0-9A-Z]{16}", "high"),
                        grp("g2", r"AKIA", "medium")])
        hits = self._scan(cfg)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].group, "g1")

    def test_whitelist_strings_skip_line(self):
        _write(self.root, "a.txt", f"{FAKE_AWS}\n")
        cfg = make_cfg([grp("aws", r"AKIA[0-9A-Z]{16}")],
                       whitelist_strings=["AKIA"])
        self.assertEqual(self._scan(cfg), [])

    def test_whitelist_files_skip(self):
        _write(self.root, "logs/a.log", f"{FAKE_AWS}\n")
        cfg = make_cfg([grp("aws", r"AKIA[0-9A-Z]{16}")],
                       whitelist_files=["logs/"])
        self.assertEqual(self._scan(cfg), [])

    def test_skip_files_by_name(self):
        _write(self.root, "package-lock.json", '{"k":"' + FAKE_AWS + '"}\n')
        cfg = make_cfg([grp("aws", r"AKIA[0-9A-Z]{16}")])
        self.assertEqual(self._scan(cfg), [])

    def test_ip_whitelist_cidr(self):
        _write(self.root, "a.txt", f"host={ip(192, 168, 0, 20)} port=1\n")
        cfg = make_cfg([grp("ip", r"(?:\d{1,3}\.){3}\d{1,3}")],
                       ip_whitelist=[f"{ip(192, 168, 0, 0)}/24"])
        self.assertEqual(self._scan(cfg), [])
        # 换成不在白名单的公网 IP → 命中
        _write(self.root, "b.txt", f"host={ip(93, 184, 216, 34)}\n")
        hits = self._scan(cfg)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].match_text, ip(93, 184, 216, 34))

    def test_masked_example_filtered(self):
        _write(self.root, "a.txt",
               'url = "postgresql://user:***@db/x"\n'
               'url2 = "postgresql://user:<password>@db/x"\n')
        cfg = make_cfg([grp("db", r"(?i)\b(?:postgres(?:ql)?)://[^\s'\"<>]+:[^\s'\"<>]+@", "high")])
        self.assertEqual(self._scan(cfg), [])

    def test_real_password_reported(self):
        _write(self.root, "a.txt", 'url = "' + FAKE_DB_URL + '"\n')
        cfg = make_cfg([grp("db", r"(?i)\b(?:postgres(?:ql)?)://[^\s'\"<>]+:[^\s'\"<>]+@", "high")])
        hits = self._scan(cfg)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, "high")

    def test_multiple_lines_multiple_hits(self):
        _write(self.root, "a.txt", f"{FAKE_AWS}\nok\n{FAKE_AWS2}\n")
        cfg = make_cfg([grp("aws", r"AKIA[0-9A-Z]{16}")])
        hits = self._scan(cfg)
        self.assertEqual([h.lineno for h in hits], [1, 3])


class TestBinaryDetection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_text_file_not_binary(self):
        p = _write(self.root, "t.txt", "普通中文文本，包含破折号——和一些内容。\n")
        self.assertFalse(checker.is_probably_binary(p))

    def test_nul_bytes_binary(self):
        p = self.root / "b.bin"
        p.write_bytes(b"AKIA\x00\x00\x00binary")
        self.assertTrue(checker.is_probably_binary(p))

    def test_empty_file_not_binary(self):
        p = self.root / "e.txt"
        p.write_text("", encoding="utf-8")
        self.assertFalse(checker.is_probably_binary(p))

    def test_binary_not_reported_in_scan(self):
        (self.root / "b.bin").write_bytes(b"\x00" * 100 + FAKE_AWS.encode())
        cfg = make_cfg([grp("aws", r"AKIA[0-9A-Z]{16}")])
        files = checker._collect_dir_files(self.root)
        self.assertEqual(checker.scan(self.root, cfg, files), [])

    def test_skip_dirs_pruned(self):
        _write(self.root, "node_modules/x/a.txt", f"{FAKE_AWS}\n")
        _write(self.root, "src/a.txt", "ok\n")
        files = [f.relative_to(self.root).as_posix()
                 for f in checker._collect_dir_files(self.root)]
        self.assertTrue(all("node_modules" not in f for f in files))
        self.assertIn("src/a.txt", files)


class TestMask(unittest.TestCase):
    def test_long(self):
        self.assertEqual(checker._mask(f"{FAKE_AWS}"), "AK***OP")

    def test_short(self):
        self.assertEqual(checker._mask("abc"), "***")
        self.assertEqual(checker._mask("abcdef"), "***")

    def test_seven_chars(self):
        self.assertEqual(checker._mask("abcdefg"), "ab***fg")


class TestCollectDirFiles(unittest.TestCase):
    def test_single_file_root(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "one.txt"
            p.write_text("x", encoding="utf-8")
            self.assertEqual(checker._collect_dir_files(p), [p])


class TestCmdCheckScopes(unittest.TestCase):
    """端到端：四种 scope 的退出码与行为。"""

    def _quiet(self, args):
        """调用 cmd_check 并吞掉其正常输出，只返回退出码。"""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            return checker.cmd_check(args)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        init_repo(self.root)
        from scripts.common import ensure_tool_config
        ensure_tool_config()

    def tearDown(self):
        self._tmp.cleanup()

    def test_dir_scope_finds_secret(self):
        _write(self.root, "a.txt", 'token = "' + FAKE_AWS + '"\n')
        self.assertEqual(self._quiet([str(self.root)]), 1)

    def test_dir_scope_clean(self):
        _write(self.root, "a.txt", "nothing here\n")
        self.assertEqual(self._quiet([str(self.root)]), 0)

    def test_stage_scope_only_staged(self):
        _write(self.root, "committed.txt", "clean\n")
        commit_all(self.root, "base")
        # 未暂存的敏感文件 → --stage 不应看到
        _write(self.root, "unstaged.txt", 'x = "' + FAKE_AWS + '"\n')
        self.assertEqual(self._quiet(["--stage", str(self.root)]), 0)
        # 暂存后 → 应阻断
        import tests.helpers as H
        H.git(self.root, "add", "unstaged.txt")
        self.assertEqual(self._quiet(["--stage", str(self.root)]), 1)

    def test_tracked_scope(self):
        _write(self.root, "a.txt", 'x = "' + FAKE_AWS + '"\n')
        commit_all(self.root, "leak")
        self.assertEqual(self._quiet(["--tracked", str(self.root)]), 1)

    def test_git_scope_history(self):
        _write(self.root, "a.txt", 'x = "' + FAKE_AWS + '"\n')
        commit_all(self.root, "leak")
        # 删除后当前工作区干净，但历史仍有
        _write(self.root, "a.txt", "clean\n")
        commit_all(self.root, "cleanup")
        self.assertEqual(self._quiet(["--tracked", str(self.root)]), 0)
        self.assertEqual(self._quiet(["--git", str(self.root)]), 1)

    def test_git_scope_reports_real_lineno(self):
        _write(self.root, "a.txt", "line1\nline2\nx = '" + FAKE_AWS + "'\n")
        commit_all(self.root, "leak")
        cfg = __import__("scripts.common", fromlist=["load_config"]).load_config(self.root)
        hits = checker._scan_git_history(self.root, cfg)
        self.assertTrue(hits)
        self.assertEqual(hits[0].lineno, 3)               # @@ hunk 解析出的真实行号

    def test_strict_blocks_low(self):
        _write(self.root, "a.txt", "MARKER_LOW_CONTENT\n")
        from scripts.common import ensure_tool_config, load_config
        # 在用户项目根写一个 low 组（配置跟随扫描根）
        (self.root / "init_your_proj.toml").write_text(
            '[[keywords.groups]]\nname = "tmp_low"\npattern = "MARKER_LOW_CONTENT"\n'
            'description = "low"\nseverity = "low"\n', encoding="utf-8")
        self.assertEqual(self._quiet([str(self.root)]), 0)          # low 仅 warn
        self.assertEqual(self._quiet(["--strict", str(self.root)]), 1)

    def test_nonexistent_path_dies(self):
        with self.assertRaises(SystemExit) as cm:
            self._quiet([str(self.root / "no-such-dir")])
        self.assertEqual(cm.exception.code, 1)

    def test_single_file_path_uses_parent(self):
        _write(self.root, "a.txt", 'x = "' + FAKE_AWS + '"\n')
        self.assertEqual(self._quiet([str(self.root / "a.txt")]), 1)


if __name__ == "__main__":
    unittest.main()
