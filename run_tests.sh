#!/bin/sh
# iyp 全量测试（零依赖，用标准库 unittest）
# 用法：./run_tests.sh          全部
#       ./run_tests.sh -v       详细
#       ./run_tests.sh tests.test_checker  只跑某模块
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
if [ $# -eq 0 ]; then
    exec python3 -m unittest discover -s tests -t .
fi
case "$1" in
    -v|--verbose)
        shift
        exec python3 -m unittest discover -s tests -t . -v "$@"
        ;;
    *)
        exec python3 -m unittest "$@"
        ;;
esac
