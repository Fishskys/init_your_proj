"""init 子命令：项目路径（用户指定或 cwd）-> 模板 -> .gitignore -> git init -> 配置。

1. 项目路径由用户指定（iyp init . / iyp init /path/to/proj），不填则为当前目录；
2. 把 templates/ 下模板复制到项目根：AGENTS_template.md→AGENTS.md、README_template.md→README.md；
3. 交互式问答生成个性化 .gitignore（固定四段 + 语言段 + 可选 AI agent 目录）；
4. 未 git 初始化则 git init；
5. 确保本机配置 init_your_proj.toml 存在（首次自动生成到 XDG 配置目录）；
   询问是否在用户项目根创建增量配置 init_your_proj.toml（默认 n，选 y 自动加入 .gitignore）。
"""
from __future__ import annotations

from pathlib import Path

from .common import (
    CYAN, DIM, GREEN, c, die,
)
from .gitignore_gen import cmd_ignore_flow


def resolve_template(name: str) -> Path:
    from .common import templates_dir
    p = templates_dir() / name
    if not p.exists():
        die(f"模板不存在: {p}")
    return p


def _copy_template(tpl: Path, target: Path, label: str) -> None:
    if target.exists():
        ans = input(c(f"{target} 已存在，覆盖？[y/n]（默认: n）: ")).strip().lower()
        if ans == "y":
            target.write_bytes(tpl.read_bytes())
            print(c(f"已覆盖复制 {tpl} -> {target}", GREEN))
        else:
            print(f"跳过 {label}。")
    else:
        target.write_bytes(tpl.read_bytes())
        print(c(f"已复制 {tpl} -> {target}", GREEN))


def cmd_init(args: list[str]) -> int:
    # 0) 项目路径：用户指定（iyp init . / iyp init /path/to/proj）；不填则为当前目录
    args = [a for a in args if not a.startswith("--")]
    root = Path(args[0]).expanduser().resolve() if args else Path.cwd().resolve()
    print(c(f"项目路径: {root}", GREEN))

    # 1) 复制模板 -> AGENTS.md / README.md
    _copy_template(resolve_template("AGENTS_template.md"), root / "AGENTS.md", "AGENTS.md")
    _copy_template(resolve_template("README_template.md"), root / "README.md", "README.md")

    # 2) 交互式生成 .gitignore（默认把 init_your_proj/ 加进去）
    ret = cmd_ignore_flow(root)

    # 3) git 检测：未初始化则执行 git init
    from .common import is_git_repo
    if not is_git_repo(root):
        from .common import run_git
        r = run_git(["init"], cwd=root, check=False)
        if r.returncode == 0:
            print(c(f"已在该目录执行 git init（此前未初始化）", GREEN))
        else:
            from .common import warn
            warn(f"git init 失败: {r.stderr.strip()}")
    else:
        print("项目已初始化 git，跳过 git init。")

    # 4) 配置：a) 本工具项目根自动生成本机配置（首次使用，静默）
    #         b) 询问是否在用户项目根生成增量配置文件（默认 n）；选 y 则加入 .gitignore
    from .common import ensure_tool_config, write_user_config_template, warn
    tpath, tcreated = ensure_tool_config()
    if tcreated:
        print(c(f"首次使用：已生成本机配置 {tpath}", GREEN))

    ans = input(c("是否需要在用户项目根目录创建配置文件 init_your_proj.toml？[y/n]（默认: n）: ")).strip().lower()
    if ans == "y":
        ucfg = write_user_config_template(root)
        print(c(f"已生成用户增量配置模板: {ucfg}（check 会与工具本机配置合并）", GREEN))
        gi = root / ".gitignore"
        if gi.exists():
            gitext = gi.read_text(encoding="utf-8")
            if "init_your_proj.toml" not in gitext:
                if not gitext.endswith("\n"):
                    gitext += "\n"
                gitext += "\n# init_your_proj 增量配置\ninit_your_proj.toml\n"
                gi.write_text(gitext, encoding="utf-8")
                print(c("已把 init_your_proj.toml 加入 .gitignore", GREEN))
        else:
            warn("项目根无 .gitignore，请自行把 init_your_proj.toml 加入忽略列表")
    else:
        print(c("提示：之后可随时在用户项目根创建 init_your_proj.toml 增量配置（模板见工具 README）", DIM))
    return ret
