"""CLI 入口与参数分发。子命令：init / check。"""
from __future__ import annotations

import argparse

from . import __version__

HELP_TEXT = f"""\
iyp {__version__} — 多工程可复用 git 基础设施

指令总览：

  iyp init [path]
      项目初始化：复制 templates/ 下模板为项目根 AGENTS.md / README.md，
      交互式生成个性化 .gitignore，未 git init 则自动 git init，
      并生成用户增量配置 init_your_proj.toml（询问，默认 n）。
      path  项目根目录（默认当前目录；也可 /path/to/proj）

  iyp check [path] [--dir | --stage | --git | --tracked] [--strict] [--raw]
      敏感信息检查：零交互、零修改，命中内容输出（文件:行号 + 规则名 + 风险等级）。
      默认命中值脱敏（首尾2字符+***），--raw 可看完整原文。
      默认 high/medium 阻断（非零退出码）；--strict 时 low 也阻断。
      path   项目根目录（默认当前目录；也可 /path/to/proj）
      --dir       （默认）递归扫描目录下所有文本文件（无需 git 仓库）
      --stage     只查本次暂存文件（pre-commit 场景）
      --git       扫描全部历史提交（排查已入库的泄漏，命中提示需重写历史）
      --tracked   扫描全部被 git 跟踪的文件（当前工作区状态，全库体检）
      --strict    严格模式：low 级命中也阻断
      --raw       命中值完整展示，不脱敏

常用场景：

  # 提交前卡点（.git/hooks/pre-commit 中）：
  iyp check --stage "$PWD" || exit 1

  # 排查历史提交中已入库的泄漏：
  iyp check --git /path/to/proj

  # 全库体检（当前工作区全部被跟踪文件）：
  iyp check --tracked /path/to/proj

配置：三层合并（内置默认 → 工具根 init_your_proj.toml → 用户项目根 init_your_proj.toml 增量）。
详见工具目录 README.md。
"""


def _print_help() -> int:
    print(HELP_TEXT, end="")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("help", "-h", "--help") and len(argv) == 1:
        return _print_help()

    parser = argparse.ArgumentParser(
        prog="iyp",
        description="多工程可复用 git 基础设施：项目初始化 / 提交前敏感信息检查（iyp help 查看指令总览）",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser(
        "init",
        help="复制 templates/ 下模板为项目根 AGENTS.md / README.md，并交互式生成 .gitignore",
    )
    p_init.add_argument("path", nargs="?", default=None,
                        help="项目根目录（默认当前目录；也可 /path/to/proj）")

    p_chk = sub.add_parser(
        "check",
        help="敏感信息检查：零交互零修改，命中脱敏输出；默认 high/medium 阻断，--strict 时 low 也阻断",
    )
    p_chk.add_argument("path", nargs="?", default=None,
                       help="项目根目录（默认当前目录；也可 /path/to/proj）")
    scope = p_chk.add_mutually_exclusive_group()
    scope.add_argument("--dir", action="store_true", default=True,
                       help="（默认）递归扫描目录下所有文本文件（无需 git）")
    scope.add_argument("--stage", action="store_true",
                       help="只查本次暂存文件（pre-commit 场景）")
    scope.add_argument("--git", action="store_true",
                       help="扫描全部历史提交（找已入库的泄漏，命中提示需重写历史）")
    scope.add_argument("--tracked", action="store_true",
                       help="扫描全部被 git 跟踪的文件（当前工作区状态，全库体检）")
    p_chk.add_argument("--strict", action="store_true",
                       help="严格模式：low 级命中也阻断（默认只阻断 high/medium）")
    p_chk.add_argument("--raw", action="store_true",
                       help="命中值完整展示（不脱敏；默认脱敏为 首尾2字符+***）")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        from .agents_init import cmd_init
        return cmd_init([args.path] if args.path else [])
    if args.cmd == "check":
        from .checker import cmd_check
        extra = []
        if args.stage:
            extra.append("--stage")
        elif args.git:
            extra.append("--git")
        elif args.tracked:
            extra.append("--tracked")
        if args.strict:
            extra.append("--strict")
        if args.raw:
            extra.append("--raw")
        return cmd_check(([args.path] if args.path else []) + extra)
    return 2


def entry() -> None:
    """console_scripts 入口：pip/uv tool/pipx 安装后生成的 iyp 命令调用此函数。"""
    import sys
    sys.exit(main(sys.argv[1:]))
