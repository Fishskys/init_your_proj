"""通用工具：配置加载（项目根 init_your_proj.toml，两层合并）、git 操作、终端着色。"""
from __future__ import annotations

import os
import re
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

CONFIG_NAME = "init_your_proj.toml"
PACKAGE_DIR = Path(__file__).resolve().parent          # .../init_your_proj/scripts
# 工具仓库根：优先 IYP_HOME 环境变量（入口脚本设置），否则用包位置推导。
# templates 与 init_your_proj.toml 都在这里；与用户项目目录无关。
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


def find_project_root(start: Path | None = None) -> Path:
    """向上查找包含 .git 或 init_your_proj.toml 的目录。"""
    cur = (start or Path.cwd()).resolve()
    for p in (cur, *cur.parents):
        if (p / CONFIG_NAME).exists() or (p / ".git").exists():
            return p
    return cur


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    git = shutil.which("git") or "git"
    return subprocess.run(
        [git, *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def is_git_repo(root: Path) -> bool:
    r = run_git(["rev-parse", "--is-inside-work-tree"], cwd=root, check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


def tracked_files(root: Path) -> list[Path]:
    """git ls-files 的结果（已天然与 gitignore 联动）。"""
    r = run_git(["ls-files", "-z"], cwd=root, check=False)
    if r.returncode != 0:
        return []
    out = []
    for raw in r.stdout.split("\0"):
        if not raw:
            continue
        p = (root / raw).resolve()
        if p.is_file():
            out.append(p)
    return out



# ---------------- 配置（初始默认由 defaults 生成；用户增量 = 项目根可选 init_your_proj.toml） ----------------

CONFIG_TEMPLATE = '''# init_your_proj 用户增量配置（放在用户项目根目录，可选；不写则全部走默认）
# 完整默认值由工具内置（含动态本机值），这里只写要覆盖/追加的部分。
# 完整说明见 init_your_proj 工具目录 README.md

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
# 默认占位符，{name} 会被替换为关键词组名
placeholder = "<REDACTED:{name}>"
# 额外跳过的文件名（锁文件等默认已跳过）
skip_files = []
'''


def config_path(root: Path) -> Path:
    """用户增量配置 = 用户项目根目录下的 init_your_proj.toml（可选）。"""
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
            "placeholder": "<REDACTED:{name}>",
            "skip_files": [],
        },
    }


def _merge_layer(base: dict, user: dict) -> dict:
    """把一层 toml 的增量设置合并进配置（就地修改 base 并返回）。

    合并规则：
      - keywords.groups = 现有组（剔除 disable 名单）+ extra
      - whitelist_files / whitelist_lines / ip_whitelist / skip_files = 追加去重
      - placeholder 等标量 = 有写则覆盖
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
    if "placeholder" in ck:
        base["check"]["placeholder"] = ck["placeholder"]
    return base


def _read_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def json_list(items: list[str]) -> str:
    inner = ", ".join('"' + i + '"' for i in items)
    return "[" + inner + "]"


def toml_repr(s: str) -> str:
    """TOML 基本字符串（double-quoted，正确转义反斜杠与引号）。"""
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + out + '"'


def load_config(root: Path) -> dict:
    """配置合并链：内置默认 → 工具根 init_your_proj.toml（首次使用自动生成，本机值）
    → 用户项目根 init_your_proj.toml（用户增量，可选）。

    合并语义：
      - 工具根 toml 是「全量落盘版」：若其 keywords.groups 非空，则**替换**内置组列表
        （用户可在此增删组）；check 白名单等追加。
      - 用户根 toml 是「增量」：disable/extra/白名单追加、placeholder 覆盖。
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
    if "placeholder" in ck:
        cfg["check"]["placeholder"] = ck["placeholder"]


def tool_config_path() -> Path:
    """本工具项目根的配置文件 = <工具仓库>/init_your_proj.toml（本机检测值落盘）。"""
    return PROJECT_ROOT / CONFIG_NAME


def ensure_tool_config() -> tuple[Path, bool]:
    """用户 clone 本工具后第一次使用时，在工具项目根生成本机配置文件（已有则不动）。

    返回 (路径, 是否新建)。
    """
    path = tool_config_path()
    if path.exists():
        return path, False
    # 本机落盘版：全量展开内置默认（含动态本机值），用户可直接改
    from .defaults import all_default_keywords, DEFAULT_IP_WHITELIST
    lines = [
        "# init_your_proj 本工具配置（首次使用时自动生成，含本机动态值）",
        "# 与用户项目根的增量配置合并生效；本文件已被本仓库 .gitignore 排除。",
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
        'placeholder = "<REDACTED:{name}>"',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, True


def write_user_config_template(root: Path) -> Path:
    """在用户项目根生成增量配置模板；已存在则不动（用户编辑过的内容不覆盖）。"""
    path = config_path(root)
    if not path.exists():
        path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return path
