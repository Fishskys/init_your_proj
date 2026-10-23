"""通用工具：三层配置合并（内置默认 → 工具根 toml → 用户项目根 toml）、IP CIDR 白名单、git/终端。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"

CONFIG_NAME = "iyp.toml"
PACKAGE_DIR = Path(__file__).resolve().parent          # .../iyp（Python 包目录）
# 工具仓库根：优先 IYP_HOME 环境变量（入口脚本设置），否则用包位置推导。
# templates 与 iyp.toml 都在这里；与用户项目目录无关。
PROJECT_ROOT = Path(os.environ.get("IYP_HOME", "")) if os.environ.get("IYP_HOME") else PACKAGE_DIR.parent
if not PROJECT_ROOT.exists():
    PROJECT_ROOT = PACKAGE_DIR.parent


def color_enabled() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text: str, *codes: str) -> str:
    if not color_enabled():
        return text
    return "".join(codes) + text + RESET


def warn(msg: str) -> None:
    print(c(f"[warn] {msg}", YELLOW))


def die(msg: str, code: int = 1) -> None:
    print(c(f"[error] {msg}", RED), file=sys.stderr)
    sys.exit(code)


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    git = shutil.which("git") or "git"
    return subprocess.run(
        [git, *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def is_git_repo(root: Path) -> bool:
    r = run_git(["rev-parse", "--is-inside-work-tree"], cwd=root, check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


# ---------------- 配置（初始默认由 defaults 生成；用户增量 = 项目根可选 iyp.toml） ----------------

CONFIG_TEMPLATE = '''# iyp 用户增量配置（放在用户项目根目录，可选；不写则全部走默认）
# 完整默认值由工具内置（含动态本机值），这里只写要覆盖/追加的部分。
# 完整说明见 iyp 工具目录 README.md

[keywords]
# 停用内置关键词组（写组名）
disable = []
# 追加自定义组
extra = [
    # { name = "my_internal_host", pattern = 'internal\\.example\\.com', description = "内部域名", severity = "medium" },
]

[check]
# 文件级白名单：整文件跳过（相对路径，支持 fnmatch 通配）
whitelist_files = []
# 字符串白名单：命中的行包含任一字符串即不再报告（子串匹配，比整行匹配更耐用）
whitelist_strings = []
# IP 白名单追加：在默认（127.0.0.1、常见公共 DNS、探测到的本机 IP）之外，再加你的网关/服务器 IP
ip_whitelist = []
# 额外跳过的文件名（锁文件等默认已跳过）
skip_files = []
'''

def config_path(root: Path) -> Path:
    """用户增量配置 = 用户项目根目录下的 iyp.toml（可选）。"""
    return root / CONFIG_NAME


def ip_in_whitelist(hit: str, ip_whitelist: set[str]) -> bool:
    """命中的 IP 是否在白名单内：支持精确匹配与 CIDR 网段（如 192.168.0.0/24）。"""
    import ipaddress
    hit = hit.strip()
    if hit in ip_whitelist:
        return True
    # 命中串可能是 ip:port 或 ip:port:*(MCP host 格式)，剥离端口部分
    ip_part = hit.split(":")[0]
    if ip_part in ip_whitelist:
        return True
    try:
        ip = ipaddress.ip_address(ip_part)
    except ValueError:
        return False
    for w in ip_whitelist:
        try:
            if "/" in w and ip in ipaddress.ip_network(w, strict=False):
                return True
        except ValueError:
            continue
    return False


def build_base_config() -> dict:
    from .defaults import all_default_keywords, DEFAULT_IP_WHITELIST
    return {
        "keywords": {"groups": all_default_keywords(), "disable": []},
        "check": {
            "whitelist_files": [],
            "whitelist_strings": [],
            "ip_whitelist": list(DEFAULT_IP_WHITELIST),
            "skip_files": [],
        },
    }


def _merge_layer(base: dict, user: dict) -> dict:
    """把一层 toml 的增量设置合并进配置（就地修改 base 并返回）。

    合并规则：
      - keywords.groups = 现有组（剔除 disable 名单）+ extra
      - whitelist_files / whitelist_strings / ip_whitelist / skip_files = 追加去重
    """
    uk = user.get("keywords", {})
    disabled = set(uk.get("disable", []))
    groups = [g for g in base["keywords"]["groups"] if g.get("name") not in disabled]
    groups += list(uk.get("extra", []))
    # 用户 toml 直接写 [[keywords.groups]] 的组也追加（按 name 去重，同名覆盖内置定义）
    user_groups = {g["name"]: g for g in uk.get("groups", []) if isinstance(g, dict) and g.get("name")}
    if user_groups:
        groups = [g for g in groups if g.get("name") not in user_groups]
        groups += list(user_groups.values())
    base["keywords"]["groups"] = groups

    ck = user.get("check", {})
    for key in ("whitelist_files", "whitelist_strings", "ip_whitelist", "skip_files"):
        extra_vals = ck.get(key, [])
        if extra_vals:
            base["check"][key] = list(dict.fromkeys(base["check"][key] + list(extra_vals)))
    return base


def _read_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        die(f"配置文件 TOML 语法错误: {path}\n  {e}")
    except OSError as e:
        die(f"配置文件读取失败: {path}\n  {e}")


def json_list(items: list[str]) -> str:
    inner = ", ".join('"' + i + '"' for i in items)
    return "[" + inner + "]"


def toml_repr(s: str) -> str:
    """TOML 基本字符串（double-quoted，正确转义反斜杠与引号）。"""
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + out + '"'


def load_config(root: Path) -> dict:
    """配置合并链：内置默认 → 工具根 iyp.toml（首次使用自动生成，本机值）
    → 用户项目根 iyp.toml（用户增量，可选）。

    合并语义：
      - 工具根 toml 是「全量落盘版」：若其 keywords.groups 非空，则**替换**内置组列表
        （用户可在此增删组）；check 白名单等追加。
      - 用户根 toml 是「增量」：disable/extra/白名单追加。
    """
    cfg = build_base_config()

    # 第一层：工具根的本机配置文件（全量落盘版，替换语义）
    tool_cfg = tool_config_path()
    if tool_cfg.exists():
        data = _read_toml(tool_cfg)
        tk = data.get("keywords", {})
        if tk.get("groups"):
            cfg["keywords"]["groups"] = list(tk["groups"])
        _merge_check(cfg, data)
        # 工具层的 disable 同样生效
        disabled = set(tk.get("disable", []))
        if disabled:
            cfg["keywords"]["groups"] = [g for g in cfg["keywords"]["groups"]
                                         if g.get("name") not in disabled]

    # 第二层：用户项目根的增量配置（增量语义）
    user_cfg = config_path(root)
    if user_cfg.exists():
        data = _read_toml(user_cfg)
        _merge_layer(cfg, data)

    return cfg


def _merge_check(cfg: dict, data: dict) -> None:
    """把一层 toml 的 [check] 增量合并进 cfg（白名单追加去重，标量覆盖）。"""
    ck = data.get("check", {})
    for key in ("whitelist_files", "whitelist_strings", "ip_whitelist", "skip_files"):
        extra_vals = ck.get(key, [])
        if extra_vals:
            cfg["check"][key] = list(dict.fromkeys(cfg["check"][key] + list(extra_vals)))


def _tool_root() -> Path:
    """工具仓库根：优先 IYP_HOME（运行时可改），否则回退到包目录的父目录。"""
    env = os.environ.get("IYP_HOME", "")
    return Path(env) if env else PACKAGE_DIR.parent


def _user_config_dir() -> Path:
    """本机配置目录（XDG 规范；Windows 用 %APPDATA%）。

    - Linux/macOS：$XDG_CONFIG_HOME 或 ~/.config
    - Windows：%APPDATA%
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "iyp"
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "iyp"
    return Path.home() / ".config" / "iyp"


def templates_dir() -> Path:
    """模板目录解析。

    - 优先 IYP_HOME/templates（源码模式或测试隔离目录里放了一份时）；
    - 否则用包内自带的 iyp/templates（安装后即 package data）。
    """
    env = os.environ.get("IYP_HOME", "")
    if env:
        cand = Path(env) / "templates"
        if cand.is_dir():
            return cand
    return PACKAGE_DIR / "templates"


def tool_config_path() -> Path:
    """本机配置文件的落点。

    优先级（保证"用户改过的白名单不丢"）：
      1. IYP_HOME 显式指定（源码模式 / 测试隔离）→ <IYP_HOME>/iyp.toml
      2. 已有的 XDG 用户配置 → <config_dir>/iyp.toml
      3. 源码模式下仓库根已有旧配置（向后兼容，不丢老白名单）→ <repo>/iyp.toml
      4. 默认走 XDG 用户配置目录（安装态；不写 site-packages）
    """
    env = os.environ.get("IYP_HOME", "")
    if env:
        return Path(env) / CONFIG_NAME
    xdg = _user_config_dir() / CONFIG_NAME
    if xdg.exists():
        return xdg
    legacy = PACKAGE_DIR.parent / CONFIG_NAME
    if legacy.exists() and (PACKAGE_DIR.parent / "pyproject.toml").exists():
        # 源码仓库根（有 pyproject.toml）且已有旧配置 → 继续沿用，避免白名单丢失
        return legacy
    return xdg


def ensure_tool_config() -> tuple[Path, bool]:
    """首次使用时生成本机配置文件（已有则不动）。落点见 tool_config_path()。

    返回 (路径, 是否新建)。
    """
    path = tool_config_path()
    if path.exists():
        return path, False
    # 本机落盘版：全量展开内置默认（含动态本机值），用户可直接改
    from .defaults import all_default_keywords, DEFAULT_IP_WHITELIST
    lines = [
        "# iyp 本机配置（首次使用时自动生成，含本机动态值）",
        "# 与用户项目根的增量配置合并生效；本机配置不随仓库分发（已被 .gitignore 排除）。",
        "",
        "[[keywords.groups]]",
    ]
    for k in all_default_keywords():
        lines += [
            f'name = "{k["name"]}"',
            f'pattern = {toml_repr(k["pattern"])}',
            f'description = {toml_repr(k["description"])}',
            f'severity = "{k["severity"]}"',
            "",
            "[[keywords.groups]]",
        ]
    while lines and lines[-1].startswith("[["):
        lines.pop()
    lines += [
        "",
        "[check]",
        f"ip_whitelist = {json_list(DEFAULT_IP_WHITELIST)}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, True


def write_user_config_template(root: Path) -> Path:
    """在用户项目根生成增量配置模板；已存在则不动（用户编辑过的内容不覆盖）。"""
    path = config_path(root)
    if not path.exists():
        path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return path
