#!/usr/bin/env python3
"""下载 AI Studio 用到的模型，断点续传、分段并行，已下好的文件按大小核对后跳过。

    python3 scripts/download_models.py                # 视频 + 图片模型（约 52 GB）
    python3 scripts/download_models.py --voice        # 另加配音 IndexTTS-2.5（ModelScope，约 6 GB）和人声分离模型
    python3 scripts/download_models.py --only voice   # 只下配音
国内网络：export HF_ENDPOINT=https://hf-mirror.com
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), os.path.expandvars(value.strip().strip('"').strip("'")))


load_env()
HF = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
MS = "https://www.modelscope.cn"
COMFY_MODELS = Path(os.environ.get("COMFYUI_DIR") or ROOT / "ComfyUI").expanduser() / "models"
VOICE_DIR = Path(os.environ.get("INDEXTTS_MODEL_DIR") or ROOT / "models" / "IndexTTS-2.5").expanduser()
SEPARATOR_DIR = Path(os.environ.get("AI_STUDIO_SEPARATOR_MODELS") or ROOT / "models" / "separator").expanduser()
SEPARATOR = Path(os.environ.get("AI_STUDIO_SEPARATOR") or ROOT / ".venvs" / "tools" / "bin" / "audio-separator").expanduser()
TOKEN = os.environ.get("HF_TOKEN") or ""
PIECES = 8

# (仓库, 仓库里的路径, ComfyUI models 下的目录)
H3_VIDEO = [
    ("Abiray/MiniMax-H3-Pruned-GGUF", "MiniMax-H3-FL2VA-Pruned-Q5_K_M.gguf", "diffusion_models"),
    ("Plaguekind/H3-Lora", "H3-PK-Parasyte-Turbo.safetensors", "loras"),
    ("realrebelai/MiniMax-H3_GGUFs", "qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf", "text_encoders"),
    ("Comfy-Org/MiniMax-H3", "vae/minimax_h3_video_vae_fp16.safetensors", "vae"),
    ("Comfy-Org/MiniMax-H3", "vae/minimax_h3_audio_vae_fp32.safetensors", "vae"),
]
H3_IMAGE = [
    ("Abiray/MiniMax-H3-Image-GGUF", "MiniMax-H3-Image-Pruned-Q5_K_M.gguf", "diffusion_models"),
    ("Comfy-Org/MiniMax-H3-Image", "vae/minimax_h3_image_vae_fp16.safetensors", "vae"),
]
# IndexTTS-2.5 的辅助模型：(ModelScope 仓库, 仓库里的路径, hf_cache 下的路径)
VOICE_AUX = [
    ("AI-ModelScope/w2v-bert-2.0", "config.json", "w2v-bert-2.0/config.json"),
    ("AI-ModelScope/w2v-bert-2.0", "preprocessor_config.json", "w2v-bert-2.0/preprocessor_config.json"),
    ("AI-ModelScope/w2v-bert-2.0", "model.safetensors", "w2v-bert-2.0/model.safetensors"),
    ("iic/speech_campplus_sv_zh-cn_16k-common", "campplus_cn_common.bin", "campplus_cn_common.bin"),
    ("nv-community/bigvgan_v2_22khz_80band_256x", "config.json", "bigvgan/config.json"),
    ("nv-community/bigvgan_v2_22khz_80band_256x", "bigvgan_generator.pt", "bigvgan/bigvgan_generator.pt"),
]
SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"


def headers(link):
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN and link.startswith(HF) else {}


def remote_size(link):
    request = urllib.request.Request(link, method="HEAD", headers=headers(link))
    with urllib.request.urlopen(request, timeout=60) as response:
        size = response.headers.get("Content-Length") or response.headers.get("X-Linked-Size")
    return int(size) if size else 0


def fetch_range(link, start, end, part):
    need = end - start + 1
    for attempt in range(60):
        have = part.stat().st_size if part.exists() else 0
        if have > need:
            with part.open("r+b") as handle:
                handle.truncate(need)
            have = need
        if have == need:
            return
        try:
            request = urllib.request.Request(link, headers={**headers(link), "Range": f"bytes={start + have}-{end}"})
            with urllib.request.urlopen(request, timeout=60) as response, part.open("ab") as handle:
                if response.status != 206:
                    raise RuntimeError(f"服务器不支持分段下载（{response.status}）")
                while chunk := response.read(1 << 20):
                    handle.write(chunk)
        except (OSError, RuntimeError) as exc:
            print(f"  重试 {part.name}：{type(exc).__name__}", flush=True)
            time.sleep(min(30, 2 + attempt))
    raise RuntimeError(f"{part.name} 多次重试仍未下完")


def fetch(link, path: Path, size: int = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    size = size or remote_size(link)
    if path.exists() and (path.stat().st_size == size or not size):
        print(f"已有 {path.name}", flush=True)
        return
    if path.exists():
        path.unlink()
    print(f"下载 {path.name}（{size / 1e9:.2f} GB）", flush=True)
    if not size:
        urllib.request.urlretrieve(link, path)
        return
    pieces = PIECES if size > 50_000_000 else 1
    step = -(-size // pieces)
    ranges = [(index * step, min(size, (index + 1) * step) - 1) for index in range(pieces)]
    parts = [path.with_name(f"{path.name}.part{index}") for index in range(pieces)]
    with ThreadPoolExecutor(pieces) as pool:
        list(pool.map(lambda index: fetch_range(link, *ranges[index], parts[index]), range(pieces)))
    temporary = path.with_name(path.name + ".joining")
    with temporary.open("wb") as handle:
        for part in parts:
            with part.open("rb") as source:
                while chunk := source.read(1 << 24):
                    handle.write(chunk)
    temporary.replace(path)
    for part in parts:
        part.unlink()
    print(f"完成 {path.name}", flush=True)


def ms_listing(repo):
    with urllib.request.urlopen(f"{MS}/api/v1/models/{repo}/repo/files?Recursive=true", timeout=60) as response:
        listing = json.load(response)
    return {item["Path"]: item["Size"] for item in listing["Data"]["Files"] if item["Type"] == "blob"}


def download_h3(items):
    for repo, remote, folder in items:
        fetch(f"{HF}/{repo}/resolve/main/{remote}", COMFY_MODELS / folder / Path(remote).name)


def download_voice():
    files = ms_listing("IndexTeam/IndexTTS-2.5")
    for remote, size in files.items():
        fetch(f"{MS}/models/IndexTeam/IndexTTS-2.5/resolve/master/{remote}", VOICE_DIR / remote, size)
    sizes = {}
    for repo, remote, local in VOICE_AUX:
        sizes.setdefault(repo, ms_listing(repo))
        fetch(f"{MS}/models/{repo}/resolve/master/{remote}", VOICE_DIR / "hf_cache" / local, sizes[repo][remote])
    if SEPARATOR.is_file():
        SEPARATOR_DIR.mkdir(parents=True, exist_ok=True)
        if not (SEPARATOR_DIR / SEPARATOR_MODEL).is_file():
            print("下载人声分离模型", SEPARATOR_MODEL, flush=True)
            subprocess.run([str(SEPARATOR), "--download_model_only", "--model_filename", SEPARATOR_MODEL,
                            "--model_file_dir", str(SEPARATOR_DIR)], check=True)
    else:
        print("没装人声分离工具（scripts/install.sh 不带 --no-tools 会装），跳过分离模型", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", action="store_true", help="另外下载配音和人声分离模型")
    parser.add_argument("--only", choices=["video", "image", "voice"], help="只下其中一类")
    args = parser.parse_args()
    groups = [args.only] if args.only else ["video", "image"] + (["voice"] if args.voice else [])
    for group in groups:
        print(f"\n== {group} ==", flush=True)
        if group == "video":
            download_h3(H3_VIDEO)
        elif group == "image":
            download_h3(H3_IMAGE)
        else:
            download_voice()
    print("\n全部完成", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("已中断；再次运行会从断点继续")
