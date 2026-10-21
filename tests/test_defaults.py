"""defaults.py：默认关键词组、动态本机指纹、IP 白名单。"""
from __future__ import annotations

import unittest

from tests.helpers import ip, mac

from scripts import defaults


class TestDefaultKeywords(unittest.TestCase):
    def test_no_duplicate_names(self):
        names = [g["name"] for g in defaults.all_default_keywords()]
        self.assertEqual(len(names), len(set(names)))

    def test_all_groups_have_required_fields(self):
        for g in defaults.all_default_keywords():
            self.assertIn("name", g)
            self.assertIn("pattern", g)
            self.assertIn("severity", g)
            self.assertIn(g["severity"], ("high", "medium", "low"))

    def test_patterns_compile(self):
        import re
        for g in defaults.all_default_keywords():
            re.compile(g["pattern"])   # 不抛异常即可

    def test_ipv4_group_matches_public(self):
        # 公网 IP 也应命中（主人定的语义）
        import re
        ipv4 = next(g for g in defaults.all_default_keywords() if g["name"] == "ipv4")
        rx = re.compile(ipv4["pattern"])
        for addr in (ip(93, 184, 216, 34), ip(8, 8, 8, 8), ip(192, 168, 1, 5), ip(10, 0, 0, 1), ip(172, 16, 0, 1)):
            self.assertTrue(rx.search(addr), addr)

    def test_ipv4_not_match_inside_longer_number(self):
        import re
        ipv4 = next(g for g in defaults.all_default_keywords() if g["name"] == "ipv4")
        rx = re.compile(ipv4["pattern"])
        self.assertIsNone(rx.search(f"{ip(1, 2, 3, 4)}.5"))
        self.assertIsNone(rx.search(f"{ip(9, 9, 9, 9)}.9"))

    def test_mac_group(self):
        import re
        mac_grp = next(g for g in defaults.all_default_keywords() if g["name"] == "mac_address")
        rx = re.compile(mac_grp["pattern"])
        self.assertTrue(rx.search(mac("aa", "bb", "cc", "dd", "ee", "ff")))
        self.assertIsNone(rx.search("aa:bb:cc:dd:ee"))

    def test_high_severity_secret_groups_exist(self):
        names = {g["name"] for g in defaults.all_default_keywords() if g["severity"] == "high"}
        for expected in ("aws_access_key", "github_pat", "openai_key",
                         "private_key_block", "db_url"):
            self.assertIn(expected, names)


class TestDefaultIpWhitelist(unittest.TestCase):
    def test_loopback_and_dns(self):
        for addr in (ip(127, 0, 0, 1), ip(0, 0, 0, 0), ip(8, 8, 8, 8), ip(1, 1, 1, 1), ip(114, 114, 114, 114)):
            self.assertIn(addr, defaults.DEFAULT_IP_WHITELIST)

    def test_no_duplicates(self):
        self.assertEqual(len(defaults.DEFAULT_IP_WHITELIST),
                         len(set(defaults.DEFAULT_IP_WHITELIST)))


class TestHostKeywords(unittest.TestCase):
    def test_generates_local_identity(self):
        groups = defaults.build_host_keywords()
        self.assertTrue(groups)
        names = [g["name"] for g in groups]
        # 至少包含用户名/家目录/主机名三组之一（不同环境下可能缺项）
        self.assertTrue(any(n.startswith("my_") for n in names))
        for g in groups:
            self.assertEqual(g["severity"], "medium")

    def test_detected_values_are_literal(self):
        import re
        for g in defaults.build_host_keywords():
            # 生成的是 re.escape 后的字面值，应能匹配自身描述中的实测值
            m = re.search(r"实测值: (.+?)[）)]", g["description"])
            if m:
                self.assertTrue(re.search(g["pattern"], m.group(1)), g["name"])


class TestDetectLocalIps(unittest.TestCase):
    def test_returns_list_of_ips(self):
        ips = defaults.detect_local_ips()
        self.assertIsInstance(ips, list)
        import re
        for ip in ips:
            self.assertRegex(ip, r"^\d{1,3}(?:\.\d{1,3}){3}$")


class TestSkipFiles(unittest.TestCase):
    def test_lock_files_listed(self):
        for f in ("package-lock.json", "Cargo.lock", "poetry.lock"):
            self.assertIn(f, defaults.DEFAULT_SKIP_FILES)


if __name__ == "__main__":
    unittest.main()
