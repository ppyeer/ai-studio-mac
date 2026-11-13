#!/usr/bin/env bash
# AI Studio + ComfyUI 一键安装（macOS，Apple Silicon M 系列，PyTorch MPS）。
#
#   bash scripts/install.sh              # 全部安装
#   bash scripts/install.sh --no-voice   # 不装配音（IndexTTS）
#   bash scripts/install.sh --no-tools   # 不装人声分离和质检
#
# 模型另用 scripts/download_models.sh 下载（约 52 GB + 可选配音模型约 6 GB）。
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a

COMFYUI_DIR=${COMFYUI_DIR:-$ROOT/ComfyUI}
INDEXTTS_DIR=${INDEXTTS_DIR:-$ROOT/vendor/index-tts}
PYTHON_VERSION=${PYTHON_VERSION:-3.12}

COMFYUI_REF=v0.45.2
GGUF_REF=6ea2651
PLAGUEKIND_REF=aaec055
APPLESILICON_REF=cfb04c3
INDEXTTS_REF=d9e41aa

WITH_VOICE=1 WITH_TOOLS=1
for arg in "$@"; do
  case $arg in
    --no-voice) WITH_VOICE=0 ;;
    --no-tools) WITH_TOOLS=0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[注意] %s\033[0m\n' "$*"; }

clone_at() {  # clone_at <url> <dir> <ref>
  if [ ! -d "$2/.git" ]; then
    git clone "$1" "$2"
  fi
  git -C "$2" fetch --tags --quiet origin || true
  git -C "$2" checkout --quiet "$3"
}

# ---------- 1. 系统检查与依赖 ----------
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "这个安装包只支持 Apple Silicon 的 Mac" >&2; exit 1; }
sysctl -n machdep.cpu.brand_string
echo "内存：$(( $(sysctl -n hw.memsize) / 1073741824 )) GB"

if ! xcode-select -p >/dev/null 2>&1; then
  step "安装 Xcode 命令行工具（编译 Metal 加速内核需要；装完后请重新运行本脚本）"
  xcode-select --install || true
  exit 1
fi

if ! command -v brew >/dev/null; then
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$candidate" ] && eval "$("$candidate" shellenv)" && break
  done
fi
command -v brew >/dev/null || { echo "请先安装 Homebrew：https://brew.sh" >&2; exit 1; }

step "安装 git、ffmpeg、uv（Homebrew）"
brew install git git-lfs ffmpeg uv
uv python install "$PYTHON_VERSION"

# ---------- 2. ComfyUI ----------
step "安装 ComfyUI $COMFYUI_REF 到 $COMFYUI_DIR"
clone_at https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR" "$COMFYUI_REF"
[ -x "$COMFYUI_DIR/.venv/bin/python" ] || uv venv --python "$PYTHON_VERSION" "$COMFYUI_DIR/.venv"
CPY="$COMFYUI_DIR/.venv/bin/python"
uv pip install --python "$CPY" torch torchvision torchaudio
uv pip install --python "$CPY" -r "$COMFYUI_DIR/requirements.txt"

step "安装 ComfyUI 自定义节点"
clone_at https://github.com/city96/ComfyUI-GGUF.git "$COMFYUI_DIR/custom_nodes/ComfyUI-GGUF" "$GGUF_REF"
uv pip install --python "$CPY" -r "$COMFYUI_DIR/custom_nodes/ComfyUI-GGUF/requirements.txt"
clone_at https://github.com/PlagueKind/ComfyUI-PlagueKind-Nodes.git "$COMFYUI_DIR/custom_nodes/ComfyUI-PlagueKind-Nodes" "$PLAGUEKIND_REF"
# Apple Silicon 加速：Metal flash-attention、int8 矩阵乘等（ASFP8_INT8_EXT=1 时首次启动会编译内核）
clone_at https://github.com/pawel-mazurkiewicz/ComfyUI-AppleSilicon-FP8.git "$COMFYUI_DIR/custom_nodes/ComfyUI-AppleSilicon-FP8" "$APPLESILICON_REF"
uv pip install --python "$CPY" -r "$COMFYUI_DIR/custom_nodes/ComfyUI-AppleSilicon-FP8/requirements.txt"
rm -rf "$COMFYUI_DIR/custom_nodes/comfyui-obvpm"
cp -R "$ROOT/comfyui-nodes/comfyui-obvpm" "$COMFYUI_DIR/custom_nodes/"
cp "$ROOT/comfyui-nodes/minimax_h3_image_gguf_fix.py" "$COMFYUI_DIR/custom_nodes/"
mkdir -p "$COMFYUI_DIR"/models/{diffusion_models,text_encoders,vae,loras} "$COMFYUI_DIR/user"

# ---------- 3. AI Studio 服务 ----------
step "安装 AI Studio 服务环境"
[ -x "$ROOT/.venv/bin/python" ] || uv venv --python "$PYTHON_VERSION" "$ROOT/.venv"
uv pip install --python "$ROOT/.venv/bin/python" -r "$ROOT/server/requirements.txt"

# ---------- 4. 人声分离 + 质检 ----------
if [ "$WITH_TOOLS" = 1 ]; then
  step "安装人声分离（audio-separator）和单条质检（take_gate）"
  [ -x "$ROOT/.venvs/tools/bin/python" ] || uv venv --python "$PYTHON_VERSION" "$ROOT/.venvs/tools"
  TPY="$ROOT/.venvs/tools/bin/python"
  uv pip install --python "$TPY" torch torchaudio "audio-separator[cpu]" opencv-python-headless numpy faster-whisper
  mkdir -p "$ROOT/models"
  [ -s "$ROOT/models/face_detection_yunet_2023mar.onnx" ] || curl -fL --retry 3 -o "$ROOT/models/face_detection_yunet_2023mar.onnx" \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx || \
    warn "YuNet 人脸模型下载失败，质检会跳过人脸检查"
fi

# ---------- 5. 配音 IndexTTS-2.5 ----------
if [ "$WITH_VOICE" = 1 ]; then
  step "安装配音（IndexTTS）到 $INDEXTTS_DIR"
  mkdir -p "$(dirname "$INDEXTTS_DIR")"
  GIT_LFS_SKIP_SMUDGE=1 clone_at https://github.com/index-tts/index-tts.git "$INDEXTTS_DIR" "$INDEXTTS_REF"
  (cd "$INDEXTTS_DIR" && uv sync --python "$PYTHON_VERSION" && uv pip install --python .venv/bin/python pypinyin)
fi

mkdir -p "$ROOT/data"
[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"

[ -n "$(ls ~/Library/Fonts/Libian.ttc /System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/Libian.ttc 2>/dev/null)" ] || \
  warn "没有找到「隶变」字体：片头诗名会用粗宋体代替。可在「字体册」里搜索「隶变」点下载。"

step "安装完成"
cat <<EOF
下一步：
  1. 下载模型：      bash scripts/download_models.sh        （国内可先 export HF_ENDPOINT=https://hf-mirror.com）
  2. 开机自动运行：  bash scripts/install_services.sh
     或者前台试跑：  bash scripts/run_comfyui.sh  和  bash scripts/run_server.sh（各开一个终端）
  3. 打开：          http://127.0.0.1:${AI_STUDIO_PORT:-8001}/ai-studio
  4. 导入示例系列：  .venv/bin/python scripts/import_examples.py
EOF
