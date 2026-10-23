"""check 子命令：零交互、零修改的敏感信息扫描。

- 扫描范围四选一：--dir（默认，递归扫目录文本文件）/ --stage（暂存文件）/
  --git（全部历史提交）/ --tracked（全部被跟踪文件）；
- 关键词组来自三层配置合并（内置默认 → 工具根本机 toml → 用户项目根增量 toml）；
- 命中输出 文件:行号 + 规则名 + 风险等级 + 命中值（默认脱敏，--raw 展示原文）；
- 默认 high/medium 阻断（非零退出码），low 仅警告；--strict 时 low 也阻断；
- 不改文件、不移除 git 跟踪、不写入白名单。
"""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import (
    BOLD, CYAN, DIM, GREEN, RED, YELLOW, c, die,
    is_git_repo, load_config, run_git, warn,
)
from .defaults import DEFAULT_SKIP_FILES

SEV_COLOR = {"high": RED, "medium": YELLOW, "low": DIM}


@dataclass
class Hit:
    file: Path
    rel: str
    lineno: int
    line: str
    group: str
    severity: str
    description: str
    match_text: str
    context: list[tuple[int, str]] = field(default_factory=list)


def build_patterns(cfg: dict) -> list[dict]:
    """只以配置文件为准：keywords.groups 数组就是全部检测组。"""
    out = []
    for k in cfg.get("keywords", {}).get("groups", []):
        if "pattern" not in k:
            continue
        out.append({
            "name": k.get("name", "custom"),
            "pattern": k["pattern"],
            "description": k.get("description", "自定义关键词"),
            "severity": k.get("severity", "medium"),
        })
    for k in out:
        k["_re"] = re.compile(k["pattern"])
    return out


def is_probably_binary(path: Path) -> bool:
    """探测二进制文件：前 8KB 含空字节、或按 UTF-8 解码后控制字符过多。

    注意多字节字符可能被 8192 字节边界切断——解码用 errors='ignore'，
    只要有空字节或大量控制字符才算二进制，避免把长中文/长破折号文本误杀。
    """
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
    except OSError:
        return True
    if not chunk:
        return False
    if b"\x00" in chunk:
        return True
    # 解码容错：截断边界上的残缺字节忽略即可，不影响二进制判定
    try:
        text = chunk.decode("utf-8", errors="ignore")
    except Exception:
        return True
    if not text:
        # 8KB 全是非 UTF-8 字节（如 UTF-16/Latin-1 高位字节占满）→ 按二进制处理
        return True
    # 控制字符（除常见空白）比例过高视为二进制
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r\f")
    return controls / len(text) > 0.05


def _wl_file_match(rel: str, w: str) -> bool:
    """白名单文件匹配：支持 fnmatch 通配、精确路径、以及目录前缀（"logs/" 匹配其下所有文件）。"""
    if fnmatch.fnmatch(rel, w) or rel == w:
        return True
    d = w.rstrip("/")
    return bool(d) and rel.startswith(d + "/")


def scan(root: Path, cfg: dict, files: list[Path]) -> list[Hit]:
    patterns = build_patterns(cfg)
    if not patterns:
        warn("无可用关键词组：iyp.toml 的 [[keywords.groups]] 为空或解析失败")
        return []
    skip_names = set(DEFAULT_SKIP_FILES) | set(cfg.get("check", {}).get("skip_files", []))
    wl_files = [f for f in cfg.get("check", {}).get("whitelist_files", []) if f]
    wl_strings = [w for w in cfg.get("check", {}).get("whitelist_strings", []) if w]
    # IP 白名单：load_config 已合并默认（127.0.0.1/DNS/探测本机 IP）+ 用户增量
    from .common import ip_in_whitelist
    ip_whitelist = set(cfg.get("check", {}).get("ip_whitelist", []))
    # 脱敏示例过滤：命中内容里密码段是 *** / <...> / xxx 占位形态的视为示例，不算命中
    masked_re = re.compile(r":[\s\"']*(\*\*\*+|<{1,2}[^>\s]{1,30}>{1,2}|x{4,}|\.{3,})@", )

    hits: list[Hit] = []
    for f in files:
        rel = f.relative_to(root).as_posix()
        if any(_wl_file_match(rel, w) for w in wl_files):
            continue
        if f.name in skip_names:
            continue
        if is_probably_binary(f):
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if any(w in line for w in wl_strings):
                continue
            for k in patterns:
                m = k["_re"].search(line)
                if m:
                    if ip_in_whitelist(m.group(0), ip_whitelist):
                        continue  # 白名单 IP（127.0.0.1、常见 DNS、用户追加）
                    if masked_re.search(m.group(0)):
                        continue  # 脱敏示例（user:***@db / <password>@ 等）
                    ctx = []
                    for j in (i - 1, i + 1):
                        if 1 <= j <= len(lines):
                            ctx.append((j, lines[j - 1]))
                    hits.append(Hit(f, rel, i, line, k["name"], k["severity"],
                                    k["description"], m.group(0), ctx))
                    break  # 每行只报一次（第一个命中的组）
    return hits


def cmd_check(args: list[str]) -> int:
    """目录扫描模式：零交互、零修改，命中脱敏输出。

    阻断级别由 --strict 控制：默认 high/medium 阻断；--strict 时所有层级（含 low）都阻断。

    扫描范围（互斥，默认 --dir）：
      --dir     扫描指定目录（或 cwd）下所有文本文件（递归，跳过 .git 与常见垃圾目录）
      --stage   只查本次暂存文件（pre-commit 场景）
      --git     扫描全部历史提交内容（找已入库的泄漏）
      --tracked 扫描全部被 git 跟踪的文件（全库体检）
    """
    pos = [a for a in args if not a.startswith("--")]
    root = Path(pos[0]).expanduser().resolve() if pos else Path.cwd().resolve()
    if not root.exists():
        die(f"路径不存在: {root}")
    if root.is_file():
        root = root.parent  # 单文件路径：配置与扫描根取其父目录

    strict = "--strict" in args
    if "--stage" in args:
        scope = "stage"
    elif "--git" in args:
        scope = "git"
    elif "--tracked" in args:
        scope = "tracked"
    else:
        scope = "dir"

    if scope != "dir" and not is_git_repo(root):
        die(f"不是 git 仓库: {root}（先运行 iyp init 或 git init；目录扫描无需 git）")

    # 配置合并链：内置默认 → 工具根本机配置（首次使用自动生成）→ 用户项目根增量（可选）
    from .common import ensure_tool_config
    tpath, tcreated = ensure_tool_config()
    if tcreated:
        print(c(f"首次使用：已生成本机配置 {tpath}", GREEN))
    cfg = load_config(root)
    patterns = build_patterns(cfg)
    if not patterns:
        print("iyp check: 无检测规则，跳过。")
        return 0

    # 按扫描范围取文件集
    rel_label: str
    hits: list[Hit]
    if scope == "dir":
        staged = _collect_dir_files(root)
        rel_label = f"目录 {root}（全部文本文件）"
        hits = scan(root, cfg, staged)
    elif scope == "git":
        # 历史提交：git log -p 输出按 commit 分块，逐块解析新增行（+ 开头）
        hits = _scan_git_history(root, cfg)
        rel_label = "全部历史提交"
    else:
        if scope == "stage":
            r = run_git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACM"],
                        cwd=root, check=False)
            rel_label = "本次暂存文件"
        else:
            r = run_git(["ls-files", "-z"], cwd=root, check=False)
            rel_label = "全部被跟踪文件（全库体检）"
        if r.returncode != 0:
            die("git 命令执行失败")
        staged = [(root / raw).resolve() for raw in r.stdout.split("\0") if raw]
        staged = sorted({p for p in staged if p.is_file()})
        hits = scan(root, cfg, staged)

    if strict:
        blocking = [h for h in hits if h.severity in ("high", "medium", "low")]
    else:
        blocking = [h for h in hits if h.severity in ("high", "medium")]

    if not hits:
        print(f"iyp check: 通过，{rel_label}未发现敏感信息。")
        return 0

    n_high = sum(1 for h in hits if h.severity == "high")
    n_med = sum(1 for h in hits if h.severity == "medium")
    n_low = sum(1 for h in hits if h.severity == "low")
    raw = "--raw" in args
    print(c(f"iyp check（{rel_label}）: 发现 {len(hits)} 处命中"
            f"（high {n_high} / medium {n_med} / low {n_low}）",
            BOLD if not blocking else RED))
    for h in hits:
        mark = "BLOCK" if h.severity in ("high", "medium") or (strict and h.severity == "low") else "warn "
        print(c(f"  [{mark}] {h.rel}:{h.lineno}  {h.group} ({h.severity})  {h.description}",
                SEV_COLOR.get(h.severity, DIM)))
        print(c(f"         行内容: {h.line.strip()[:80]}", DIM))
        if raw:
            print(c(f"         命中值: {h.match_text}", DIM))
        else:
            print(c(f"         命中值: {_mask(h.match_text)}（已脱敏，--raw 可看原文）", DIM))

    if blocking:
        levels = "high/medium/low" if strict else "high/medium"
        tip = ("处置建议：删除该行，或替换为环境变量/占位符；\n"
               "确属误报（文档示例/测试数据）请把该行加入 iyp.toml 的\n"
               "check.whitelist_strings（子串匹配）后重新提交。")
        if scope == "git":
            tip = ("注意：--git 扫描的是历史提交，泄漏已入库。修复需两步：\n"
                   "1. 修改/删除当前文件中的敏感内容并提交；\n"
                   "2. 用 git filter-repo / BFG 重写历史清除残留（force push 需团队协调）。\n" + tip)
        print(c(f"\n阻断原因：{rel_label}包含敏感信息（{levels}）。\n" + tip, RED))
        return 1
    print(c("无阻断级问题，允许提交。", GREEN))
    return 0


def _scan_git_history(root: Path, cfg: dict) -> list[Hit]:
    """扫描全部历史提交中新增的内容行（git log -p，只看 + 行）。

    以 (文件, 行内容) 去重，避免同一泄漏在多次提交中重复报告。
    """
    r = run_git(["log", "-p", "-U0", "--no-color"], cwd=root, check=False)
    if r.returncode != 0:
        die("git log -p 失败")
    cur_file = None
    seen: set[tuple[str, str]] = set()
    hits: list[Hit] = []
    patterns = build_patterns(cfg)
    if not patterns:
        return []

    # 白名单（与 scan 相同语义）
    wl_strings = [w for w in cfg.get("check", {}).get("whitelist_strings", []) if w]
    from .common import ip_in_whitelist
    ip_whitelist = set(cfg.get("check", {}).get("ip_whitelist", []))
    from .defaults import DEFAULT_SKIP_FILES
    skip_names = set(DEFAULT_SKIP_FILES) | set(cfg.get("check", {}).get("skip_files", []))
    wl_files = [f for f in cfg.get("check", {}).get("whitelist_files", []) if f]
    import re as _re
    masked_re = _re.compile(r":[\s\"']*(\*\*\*+|<{1,2}[^>\s]{1,30}>{1,2}|x{4,}|\.{3,})@")

    import re as _re2
    hunk_re = _re2.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")
    new_lineno = 0
    for raw in r.stdout.split("\n"):
        if raw.startswith("@@"):
            m = hunk_re.match(raw)
            # hunk 头的 +c 已是首行行号；下面每遇一条新文件行再 +1，故此处减 1
            new_lineno = (int(m.group(1)) - 1) if m else 0
            continue
        if raw.startswith("+++ b/"):
            cur_file = raw[6:] or None
            continue
        if raw.startswith("-"):
            continue
        if not raw.startswith("+"):
            # 上下文行也消耗行号
            if cur_file is not None:
                new_lineno += 1
            continue
        line = raw[1:]
        new_lineno += 1
        if cur_file is None:
            continue
        if Path(cur_file).name in skip_names:
            continue
        if any(_wl_file_match(cur_file, w) for w in wl_files):
            continue
        key = (cur_file, line.strip())
        if key in seen or any(w in line for w in wl_strings):
            continue
        seen.add(key)
        for k in patterns:
            m = k["_re"].search(line)
            if m:
                if ip_in_whitelist(m.group(0), ip_whitelist):
                    continue
                if masked_re.search(m.group(0)):
                    continue
                hits.append(Hit(root / cur_file, cur_file, new_lineno, line, k["name"],
                                k["severity"], k["description"], m.group(0)))
                break
    hits.sort(key=lambda h: (h.rel, h.lineno))
    return hits


def _collect_dir_files(root: Path) -> list[Path]:
    """递归收集目录下所有文本文件（跳过 .git、node_modules 等常见垃圾目录与二进制）。"""
    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                 ".idea", ".vscode", "dist", "build", "target", ".mypy_cache",
                 ".pytest_cache", ".ruff_cache", ".tox", ".eggs", "vendor"}
    if root.is_file():
        return [root]
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if not is_probably_binary(p):
                out.append(p)
    return sorted(set(out))


def _mask(text: str) -> str:
    """脱敏：保留首尾 2 字符，中间用 *** 替代；过短则全 ***。"""
    t = text.strip()
    if len(t) <= 6:
        return "***"
    return t[:2] + "***" + t[-2:]
