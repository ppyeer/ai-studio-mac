#!/usr/bin/env bash
# 下载全部模型：视频 + 图片 + 配音 + 人声分离。参数原样传给 download_models.py（例如 --only video）。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
if [ $# -eq 0 ]; then
  exec "$PY" "$ROOT/scripts/download_models.py" --voice
fi
exec "$PY" "$ROOT/scripts/download_models.py" "$@"
