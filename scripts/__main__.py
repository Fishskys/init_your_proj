"""init_your_proj: 多工程可复用 git 基础设施。

子命令:
  init    由快照模板生成本项目的 AGENTS.md
  ignore  交互式问答生成个性化 .gitignore（已有则去重追加）
  check   可配置关键词扫描（只扫 git 跟踪文件，交互/统一处理命中）
  config  打印当前合并后的有效配置
"""
import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
