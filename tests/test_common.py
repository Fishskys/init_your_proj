"""common.py：三层配置合并、IP 白名单、TOML 序列化、工具配置生成。"""
from __future__ import annotations

import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests.helpers import grp, make_cfg, ip

from scripts import common


class TestIpInWhitelist(unittest.TestCase):
    def test_exact_match(self):
        wl = {ip(10, 0, 0, 1), ip(192, 168, 1, 1)}
        self.assertTrue(common.ip_in_whitelist(ip(10, 0, 0, 1), wl))
        self.assertFalse(common.ip_in_whitelist(ip(10, 0, 0, 2), wl))

    def test_ip_with_port(self):
        wl = {ip(10, 0, 0, 1)}
        self.assertTrue(common.ip_in_whitelist(f"{ip(10, 0, 0, 1)}:8080", wl))
        self.assertTrue(common.ip_in_whitelist(f"{ip(10, 0, 0, 1)}:8080:*", wl))

    def test_cidr_match(self):
        wl = {f"{ip(192, 168, 0, 0)}/24"}
        self.assertTrue(common.ip_in_whitelist(ip(192, 168, 0, 20), wl))
        self.assertTrue(common.ip_in_whitelist(ip(192, 168, 0, 255), wl))
        self.assertFalse(common.ip_in_whitelist(ip(192, 168, 1, 1), wl))

    def test_cidr_ip_with_port(self):
        wl = {f"{ip(192, 168, 0, 0)}/24"}
        self.assertTrue(common.ip_in_whitelist(f"{ip(192, 168, 0, 20)}:8077", wl))

    def test_non_ip_strings(self):
        # db_url 整段 URL 不是 IP，不应误判
        self.assertFalse(common.ip_in_whitelist("postgresql://user:***@db", {ip(10, 0, 0, 1)}))
        self.assertFalse(common.ip_in_whitelist("not-an-ip", set()))

    def test_invalid_cidr_ignored(self):
        self.assertFalse(common.ip_in_whitelist(ip(10, 0, 0, 1), {"bad/99"}))


class TestTomlSerialization(unittest.TestCase):
    def test_toml_repr_escapes(self):
        s = r"C:\Users\x\a" + '"q"'
        out = common.toml_repr(s)
        # 能被 tomllib 正确回读
        val = tomllib.loads("k = " + out)["k"]
        self.assertEqual(val, s)

    def test_json_list(self):
        self.assertEqual(common.json_list([]), "[]")
        self.assertEqual(common.json_list(["a", "b"]), '["a", "b"]')


class TestMergeLayer(unittest.TestCase):
    def _base(self, groups):
        return make_cfg(groups, ip_whitelist=[ip(127, 0, 0, 1)])

    def test_disable_group(self):
        base = self._base([grp("a", "A"), grp("b", "B")])
        common._merge_layer(base, {"keywords": {"disable": ["a"]}})
        names = [g["name"] for g in base["keywords"]["groups"]]
        self.assertEqual(names, ["b"])

    def test_extra_group_appended(self):
        base = self._base([grp("a", "A")])
        common._merge_layer(base, {"keywords": {"extra": [grp("x", "X")]}})
        self.assertEqual([g["name"] for g in base["keywords"]["groups"]], ["a", "x"])

    def test_user_groups_override_by_name(self):
        base = self._base([grp("a", "OLD", severity="low")])
        common._merge_layer(base, {"keywords": {"groups": [grp("a", "NEW", severity="high")]}})
        groups = base["keywords"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["pattern"], "NEW")
        self.assertEqual(groups[0]["severity"], "high")

    def test_whitelist_append_dedup(self):
        base = self._base([grp("a", "A")])
        base["check"]["whitelist_strings"] = ["keep"]
        common._merge_layer(base, {"check": {
            "whitelist_strings": ["keep", "new"],
            "ip_whitelist": [ip(10, 1, 1, 1), ip(127, 0, 0, 1)],
            "whitelist_files": ["logs/"],
            "skip_files": ["x.lock"],
        }})
        self.assertEqual(base["check"]["whitelist_strings"], ["keep", "new"])
        # 127.0.0.1 已存在 → 去重
        self.assertEqual(base["check"]["ip_whitelist"], [ip(127, 0, 0, 1), ip(10, 1, 1, 1)])
        self.assertEqual(base["check"]["whitelist_files"], ["logs/"])
        self.assertIn("x.lock", base["check"]["skip_files"])

    def test_empty_user_layer_noop(self):
        base = self._base([grp("a", "A")])
        before = [g["name"] for g in base["keywords"]["groups"]]
        common._merge_layer(base, {})
        self.assertEqual([g["name"] for g in base["keywords"]["groups"]], before)


class TestLoadConfigThreeLayers(unittest.TestCase):
    """端到端三层合并：内置默认 → 工具根 toml → 用户项目根 toml。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.userproj = self.tmp / "userproj"
        self.userproj.mkdir()
        self._old_env = os.environ.get("IYP_HOME")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("IYP_HOME", None)
        else:
            os.environ["IYP_HOME"] = self._old_env
        self._tmp.cleanup()

    def test_user_increment_over_default(self):
        # 只写用户层：disable 一个内置组 + 追加字符串白名单
        (self.userproj / "init_your_proj.toml").write_text(
            '[keywords]\ndisable = ["github_pat"]\n\n'
            '[check]\nwhitelist_strings = ["MY_TOKEN_PLACEHOLDER"]\n',
            encoding="utf-8",
        )
        cfg = common.load_config(self.userproj)
        names = [g["name"] for g in cfg["keywords"]["groups"]]
        self.assertNotIn("github_pat", names)
        self.assertIn("ipv4", names)                      # 其余默认组仍在
        self.assertIn("MY_TOKEN_PLACEHOLDER", cfg["check"]["whitelist_strings"])
        # 默认 IP 白名单仍在
        self.assertIn(ip(127, 0, 0, 1), cfg["check"]["ip_whitelist"])

    def test_broken_toml_reports_clear_error(self):
        """坏 TOML 不应裸 traceback，而应给出清晰错误并以 exit 1 结束。"""
        (self.userproj / "init_your_proj.toml").write_text("这不是 toml [[[", encoding="utf-8")
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stderr(err):
            common.load_config(self.userproj)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("TOML", err.getvalue())


class TestEnsureToolConfig(unittest.TestCase):
    def test_generates_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("IYP_HOME")
            os.environ["IYP_HOME"] = d
            try:
                path, created = common.ensure_tool_config()
                self.assertTrue(created)
                self.assertTrue(path.exists())
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(data["keywords"]["groups"])
                self.assertIn(ip(127, 0, 0, 1), data["check"]["ip_whitelist"])
                # 第二次调用不再新建
                _, created2 = common.ensure_tool_config()
                self.assertFalse(created2)
            finally:
                if old is None:
                    os.environ.pop("IYP_HOME", None)
                else:
                    os.environ["IYP_HOME"] = old

    def test_tool_config_template_has_no_placeholder(self):
        # placeholder 已从配置项移除
        self.assertNotIn("placeholder", common.CONFIG_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
