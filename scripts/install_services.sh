#!/usr/bin/env bash
# 把 ComfyUI 和 AI Studio 装成当前用户的 launchd 服务：登录后自动运行、崩溃自动重启。
#   bash scripts/install_services.sh            # 安装并启动
#   bash scripts/install_services.sh --remove   # 停止并卸载
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS=(com.aistudio.comfyui com.aistudio.server)

for label in "${LABELS[@]}"; do
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
done
if [ "${1:-}" = --remove ]; then
  for label in "${LABELS[@]}"; do rm -f "$AGENTS/$label.plist"; done
  echo "已卸载"
  exit 0
fi

mkdir -p "$AGENTS" "$ROOT/data"
for label in "${LABELS[@]}"; do
  sed "s#@ROOT@#$ROOT#g" "$ROOT/scripts/launchd/$label.plist" > "$AGENTS/$label.plist"
  plutil -lint "$AGENTS/$label.plist" >/dev/null
  launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"
done

[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
sleep 3
launchctl print "$DOMAIN/com.aistudio.server" | grep -E "state =|pid =" || true
echo
echo "AI Studio：http://127.0.0.1:${AI_STUDIO_PORT:-8001}/ai-studio"
echo "重启服务：launchctl kickstart -k $DOMAIN/com.aistudio.server   （ComfyUI 换成 com.aistudio.comfyui）"
echo "日志：tail -f $ROOT/data/server.log    tail -f ${COMFYUI_DIR:-$ROOT/ComfyUI}/user/ai-studio-comfyui.log"
