#!/bin/zsh
# 启动 AI Studio 网页服务（launchd 和手动运行共用）。
ROOT=${0:A:h:h}
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONUNBUFFERED=1
cd "$ROOT" || exit 1
exec ./.venv/bin/python server/server.py
