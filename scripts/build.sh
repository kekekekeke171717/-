#!/usr/bin/env bash
# 本地一键自检：装依赖 → 生成数据 → 跑测试 → 跑一遍 demo。
# 用法： bash scripts/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
echo "==> 1/4 安装依赖"
"$PY" -m pip install -q -r requirements.txt

echo "==> 2/4 生成样例数据与流程图"
"$PY" scripts/gen_data.py
"$PY" scripts/gen_diagrams.py

echo "==> 3/4 单元测试"
PYTHONPATH=src "$PY" -m pytest tests -q

echo "==> 4/4 跑一遍 demo（产物在 out/）"
PYTHONPATH=src "$PY" -m clinic_triage demo
PYTHONPATH=src "$PY" examples/demo.py > /dev/null

echo
echo "构建完成："
ls -1 out/
echo
echo "提示：out/ 目录已在 .gitignore 中，不会被提交。"
