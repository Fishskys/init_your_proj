"""测试包的公共工具：仓库路径、临时项目、git 辅助。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """在 repo 内执行 git（不依赖用户全局 git 配置）。"""
    cmd = [
        "git",
        "-c", "user.name=test",
        "-c", "user.email=test@example.com",
        "-c", "init.defaultBranch=main",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True,
                          check=check, env=env)


def init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    return repo


def commit_all(repo: Path, message: str = "c") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def make_cfg(groups, *, ip_whitelist=None, whitelist_files=None,
             whitelist_strings=None, skip_files=None) -> dict:
    """构造一个最小可用的配置 dict（不依赖真实工具配置/本机环境）。"""
    return {
        "keywords": {"groups": list(groups), "disable": []},
        "check": {
            "whitelist_files": list(whitelist_files or []),
            "whitelist_strings": list(whitelist_strings or []),
            "ip_whitelist": list(ip_whitelist or []),
            "skip_files": list(skip_files or []),
        },
    }


def grp(name, pattern, severity="medium", description="d") -> dict:
    return {"name": name, "pattern": pattern,
            "description": description, "severity": severity}


# ---- 测试用假密钥：运行时拼接，源码中不成形，避免被 iyp check 误判为真实凭证 ----
FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"          # 20 字符 AWS Access Key ID 形态
FAKE_AWS2 = "AKIA" + "QRSTUVWXYZABCDEF"         # 另一个不同值
FAKE_GITHUB = "ghp_" + "0123456789abcdefghijABCDEFGHIJ012345"
FAKE_DB_URL = "postgresql://user:" + "realpw123" + "@db/x"
FAKE_OPENAI = "sk-" + "abcdefghij0123456789ABCDEFGHIJ"


def ip(*parts) -> str:
    """运行时拼 IP 字面量，避免测试源码被 ipv4 组当成真实 IP 命中。"""
    return ".".join(str(p) for p in parts)


def mac(*pairs) -> str:
    """运行时拼 MAC 字面量，避免测试源码被 mac_address 组命中。"""
    return ":".join(pairs)
