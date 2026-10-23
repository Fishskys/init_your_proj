"""iyp: 多工程可复用 git 基础设施。

子命令:
  init   初始化项目（复制 AGENTS.md/README.md 模板 + 交互生成 .gitignore + git init + 可选增量配置）
  check  敏感信息检查（默认递归扫描目录；--stage/--git/--tracked 可选范围）
"""
import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
