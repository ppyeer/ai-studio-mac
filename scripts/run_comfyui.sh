#!/bin/zsh
# 启动 ComfyUI（launchd 和手动运行共用）。输出追加到日志文件：AI Studio 从这份日志读采样进度。
ROOT=${0:A:h:h}
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
COMFYUI_DIR=${COMFYUI_DIR:-$ROOT/ComfyUI}
COMFYUI_LOG=${COMFYUI_LOG:-$COMFYUI_DIR/user/ai-studio-comfyui.log}
PORT=${${AI_STUDIO_COMFY_URL:-http://127.0.0.1:8188}##*:}
PORT=${PORT%%/*}
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p "${COMFYUI_LOG:h}"
cd "$COMFYUI_DIR" || exit 1
print "\n===== 启动 ComfyUI $(date '+%F %T') =====" >> "$COMFYUI_LOG"
exec ./.venv/bin/python main.py --listen 127.0.0.1 --port "$PORT" ${=COMFYUI_ARGS} >> "$COMFYUI_LOG" 2>&1
