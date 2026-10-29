#!/usr/bin/env bash
# 把看板发布到 GitHub Pages。
#
# out/dashboard.html 是自包含的单文件（样式和 JS 都内联），
# 所以「部署」这件事就是把它拷到发布目录再推送。
#
# 用法：
#   bash scripts/deploy.sh            # 生成产物到 docs-site/
#   DRY_RUN=1 bash scripts/deploy.sh  # 只构建不推送
#
# 依赖：已在 .github/workflows/pages.yml 里配好自动执行，本地跑一般是为了预览。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
OUT_DIR="${OUT_DIR:-out}"
SITE_DIR="${SITE_DIR:-docs-site}"

echo "==> 1/3 生成看板"
PYTHONPATH=src "$PY" -m clinic_triage demo --out "$OUT_DIR"

echo "==> 2/3 组装发布目录 $SITE_DIR"
rm -rf "$SITE_DIR"
mkdir -p "$SITE_DIR/images"
cp "$OUT_DIR/dashboard.html" "$SITE_DIR/index.html"
cp "$OUT_DIR/suggestions.csv" "$SITE_DIR/" 2>/dev/null || true
cp "$OUT_DIR/replay.json" "$SITE_DIR/" 2>/dev/null || true
cp docs/images/*.png "$SITE_DIR/images/"

# Pages 需要 .nojekyll，否则下划线开头的目录会被忽略
touch "$SITE_DIR/.nojekyll"

echo "==> 3/3 完成：$SITE_DIR"
ls -1 "$SITE_DIR"
echo
echo "这是 Pages 的产物目录（已在 .gitignore 里），不进版本库。"
echo "推送到 main 后由 .github/workflows/pages.yml 自动构建并发布；"
echo "本地跑这份脚本只是为了先看一眼效果 —— 直接浏览器打开 index.html 即可。"
