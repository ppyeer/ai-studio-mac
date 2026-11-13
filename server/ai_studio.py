"""AI Studio：用本机 ComfyUI（MiniMax H3）直接出片、出图。

视频提示词按 h3-local-studio 的六段式（或自由描述）写好后提交到 ComfyUI；图片走 MiniMax H3-Image
（文生图 / 参考图编辑，6 步）。成品按「类别 / 画幅」整理到素材库（AI_STUDIO_LIBRARY），视频另生成
缩略图、联系表和单条质检结论，图片另生成缩略图和网页预览图。
"""
from __future__ import annotations

import base64
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import sys

# 所有外部路径都可以用环境变量覆盖（见仓库根目录 .env.example）；默认按仓库目录结构摆放
APP_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name) or default).expanduser()


COMFY_URL = os.environ.get("AI_STUDIO_COMFY_URL") or "http://127.0.0.1:8188"
COMFY_DIR = _env_path("COMFYUI_DIR", APP_ROOT / "ComfyUI")
COMFY_LOG_PATH = _env_path("COMFYUI_LOG", COMFY_DIR / "user" / "ai-studio-comfyui.log")
LIBRARY_DIR = _env_path("AI_STUDIO_LIBRARY", APP_ROOT / "data" / "library")
STUDIO_REPO = Path(__file__).resolve().parent
TAKE_GATE_PYTHON = _env_path("AI_STUDIO_TOOLS_PYTHON", APP_ROOT / ".venvs" / "tools" / "bin" / "python")
YUNET_MODEL = _env_path("AI_STUDIO_YUNET", APP_ROOT / "models" / "face_detection_yunet_2023mar.onnx")
# 字幕和片尾诗文用 Pillow 画成透明 PNG 再叠加（不依赖 ffmpeg 的 drawtext）
CAPTION_PYTHON = os.environ.get("AI_STUDIO_CAPTION_PYTHON") or sys.executable
CAPTION_SCRIPT = Path(__file__).with_name("ai_studio_captions.py")
# 行迹地图按经纬度程序绘制（生图模型画不准地理位置）；Natural Earth 海岸线 / 河流 / 湖泊数据
MAP_SCRIPT = Path(__file__).with_name("ai_studio_map.py")
MAP_DATA_DIR = _env_path("AI_STUDIO_MAP_DATA", APP_ROOT / "assets" / "mapdata")
MAX_ROUTE = 40
# 配音单独生成：IndexTTS-2.5（自己的 venv）按参考音色读每镜的配音文字；合成时原片人声分离掉，只留环境声和配乐再叠新配音
VOICE_REPO = _env_path("INDEXTTS_DIR", APP_ROOT / "vendor" / "index-tts")
VOICE_PYTHON = VOICE_REPO / ".venv" / "bin" / "python"
VOICE_MODEL_DIR = _env_path("INDEXTTS_MODEL_DIR", APP_ROOT / "models" / "IndexTTS-2.5")
VOICE_SCRIPT = Path(__file__).with_name("ai_studio_voice.py")
SEPARATOR = _env_path("AI_STUDIO_SEPARATOR", APP_ROOT / ".venvs" / "tools" / "bin" / "audio-separator")
SEPARATOR_MODEL_DIR = _env_path("AI_STUDIO_SEPARATOR_MODELS", APP_ROOT / "models" / "separator")
SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
VOICE_DIR = LIBRARY_DIR / ".voice"
VOICE_ACTIVE = {"queued", "running"}
PINYIN_RE = re.compile(r"^[a-zv]{1,6}[1-5]$")
VOICE_MARK_RE = re.compile(r"(<[^<>|]+\|[^<>]+>)")

MODELS = {
    "unet": "MiniMax-H3-FL2VA-Pruned-Q5_K_M.gguf",
    "lora": "H3-PK-Parasyte-Turbo.safetensors",
    "clip": "qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf",
    "video_vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
}
IMAGE_MODELS = {
    "unet": "MiniMax-H3-Image-Pruned-Q5_K_M.gguf",
    "clip": MODELS["clip"],
    "vae": "minimax_h3_image_vae_fp16.safetensors",
}
MODEL_FOLDERS = ("diffusion_models", "unet", "loras", "text_encoders", "clip", "vae")
SECTIONS = ("subject_definitions", "summary", "retention_analysis", "detailed_description",
            "overall_soundscape", "non_diegetic_music")
SECTION_LABELS = {
    "subject_definitions": "开场人物与道具",
    "summary": "动作梗概",
    "retention_analysis": "保持与镜头",
    "detailed_description": "按秒节拍",
    "overall_soundscape": "声音",
    "non_diegetic_music": "配乐",
}
IDENTITY_RETENTION = (
    "identity_preserved - keep faces/hairstyles/costumes/makeup; pose, expression, camera angle and framing may change. "
    "Natural real-time speed, no slow motion. No people other than those described appear."
)
IMAGE_NO_TEXT = "No text, logos or watermarks anywhere in the image."
CATEGORIES = [
    {
        "id": "free", "kind": "video", "label": "自由创作", "style": "free", "format": "portrait", "mode": "t2v",
        "hint": "一段英文描述：画面风格、场景、按秒分镜、机位、声音、台词。中文只放在引号台词里。",
        "prompt": (
            "Vertical smartphone-style portrait video, soft natural light, natural skin texture, fine grain, "
            "no lettering anywhere in frame.\n\nScene overview: \n\nStoryboard:\n[0s-5s] \n\n"
            "Camera: Static Shot.\n\nAudio: \n\nMusic: none\n\n"
            "No text, subtitles, lettering, signage, logos or watermarks of any kind."
        ),
    },
    {
        "id": "wuxia", "kind": "video", "label": "唯美武侠 MV", "style": "structured", "format": "portrait", "mode": "i2v",
        "hint": "每镜三件事：一个明确动作 + 一个运镜 + 一次表情变化。露脸时人柔动、镜头动。",
        "sections": {
            "subject_definitions": "A young swordswoman in flowing white hanfu ... Nobody else is in the frame.",
            "retention_analysis": IDENTITY_RETENTION + " Backlit golden rim light, soft fill on the face. No glow, no energy orbs, no magic.",
            "detailed_description": "0-2 s: ... The camera slowly arcs left around her and stops at a three-quarter view. 2-4 s: ...",
            "overall_soundscape": "wind through bamboo, rustling silk, a soft footstep on stone. No clear speech.",
            "non_diegetic_music": "none.",
        },
    },
    {
        # 苏东坡 · 一生行迹、徐霞客 · 游记行迹 用的镜头写法：一镜朗读一两句原文，画外旁白，人物不开口
        "id": "trail", "kind": "video", "label": "诗文行迹", "style": "structured", "format": "portrait", "mode": "i2v",
        "hint": "一镜朗读一两句诗文原文（7–12 秒）：原文只放在旁白的引号里，画中人物不开口；首镜用片头图作首帧，0–3 秒停在地图上再切实景，之后用上一镜尾帧接着拍。",
        "sections": {
            "subject_definitions": ("<Picture 1> is the first frame: the last frame of the previous shot, showing ... (the poet or traveller: "
                                    "age, face, beard, costume, headwear, props) in ... (place, season, time of day, light). The shot "
                                    "carries on directly from that frame with the same person, costume, place and light."),
            "summary": "One continuous shot of ...",
            "retention_analysis": ("Clean live-action footage from edge to edge in a cinematic Chinese historical film look of the stated "
                                   "dynasty: restrained ink-wash palette of misty blue-grey, pale jade and warm amber, natural light only, "
                                   "gentle film grain, historically accurate clothing and architecture. " + IDENTITY_RETENTION +
                                   " No subtitles, captions or writing appear anywhere in the frame."),
            "detailed_description": ("[Shot 1] (0–7 s) The same place as in <Picture 1>. The camera slowly ... and stops. 0-4 s: ... "
                                     "4-7 s: ... From about 0.5 s, an off-screen mature male narrator recites in Mandarin Chinese, in "
                                     "voice-over, slow, warm and resonant, with a natural breath between the phrases: “……” The only voice "
                                     "is the narrator; nobody on screen speaks: their lips stay closed and they never look into the camera "
                                     "lens. One continuous shot, no cuts."),
            "overall_soundscape": "... The only voice is the off-screen narrator reciting the quoted lines; no other speech.",
            "non_diegetic_music": ("the same slow, gentle solo guqin melody with a soft xiao bamboo flute that runs through the whole "
                                   "series, kept low beneath the recitation."),
        },
    },
    {
        "id": "photo", "kind": "image", "label": "写实摄影", "format": "portrait_34", "mode": "t2i",
        "hint": "一段完整的英文画面描述：主体、动作、环境、光线、镜头焦段、质感。描述越完整越好，最长约 4000 词元。",
        "prompt": (
            "A photorealistic photograph of ... \n\n"
            "Subject: ... \nSetting: ... \n"
            "Lighting: soft natural window light from the left, gentle shadows. \n"
            "Camera: full-frame camera, 50 mm lens at f/2, eye level, shallow depth of field. \n"
            "Texture: true-to-life skin and material detail, subtle film grain, natural colour. \n"
            + IMAGE_NO_TEXT
        ),
    },
    {
        "id": "poster", "kind": "image", "label": "海报文字", "format": "portrait_34", "mode": "t2i",
        "hint": "排版、配色、字体都写清楚；要出现在画面上的字放在英文引号里，中文字也可以，只放在引号里。",
        "prompt": (
            "A finished poster design for ... \n\n"
            "Layout: a large hero image of ... in the upper two thirds, generous margins, clean grid. \n"
            "Typography: the headline reads \"...\" in bold condensed capitals at the top; "
            "below it a smaller line reads \"...\"; at the bottom a date line reads \"...\". \n"
            "Style: ... \nPalette: ... \n"
            "All lettering is crisp, correctly spelled and exactly as quoted; no other text appears."
        ),
    },
    {
        "id": "illustration", "kind": "image", "label": "插画概念", "format": "landscape_43", "mode": "t2i",
        "hint": "写明媒介和画风（水彩、油画、厚涂、像素……），再按前景 / 中景 / 背景描述画面。",
        "prompt": (
            "A detailed concept illustration of ... \n\n"
            "Medium and style: ... \n"
            "Foreground: ... \nMidground: ... \nBackground: ... \n"
            "Lighting and mood: ... \n" + IMAGE_NO_TEXT
        ),
    },
    {
        "id": "keyframe", "kind": "image", "label": "视频首帧", "format": "portrait", "mode": "t2i",
        "hint": "给视频准备首帧：画幅和视频保持一致，人物和道具要在画面里交代清楚。出图后点「用作首帧」直接带到视频。",
        "prompt": (
            "A single cinematic live-action film still, used as the first frame of a video. \n\n"
            "Subject: ... \nSetting: ... \n"
            "Camera: eye level, 35 mm lens, subject placed on the left third. \n"
            "Lighting: ... \n"
            "Realistic live-action footage look, natural skin texture, no motion blur. No text, subtitles, logos or watermarks."
        ),
    },
    {
        "id": "trail_card", "kind": "image", "label": "行迹片头图", "format": "portrait", "mode": "t2i",
        "hint": "诗文行迹每集的片头图：古地图上朱砂线按顺序连起走过的地方，停在本集一站；图上只写标题、本站地名、年号年份三处，字放在英文引号里。出图后核对图上的字。",
        "prompt": (
            "A vertical 9:16 title card for a documentary film: an antique Chinese map of ... (dynasty) China painted on aged, softly "
            "creased ochre silk in restrained ink-wash style. Mountains are drawn as blue-green brush strokes, the Yellow River and the "
            "Yangtze as fine flowing ink lines, the sea to the east and south as pale wave patterns, with a faint brocade mounting border "
            "around the map. Small ink dots mark the places he travelled, and a thin vermilion ink line links them in order: ... (each "
            "place with its position on the map, e.g. \"Hangzhou beside West Lake on the south-east coast\"). The line ends at a glowing "
            "vermilion dot at ..., surrounded by a soft warm halo.\n\n"
            "At the top centre, a title in elegant black regular-script calligraphy reads \"……\". Next to the glowing dot, a small label "
            "in black calligraphy reads \"……\". At the bottom centre, a line in black regular-script calligraphy reads \"……\".\n\n"
            "Soft warm light from the upper left, delicate silk and paper texture, high detail, calm and elegant composition with generous "
            "empty space. All lettering is crisp, correctly written and exactly as quoted; no other text, seals, logos or watermarks appear."
        ),
    },
]
IDENTITY_RETENTION_ZH = (
    "保持人物身份不变：面孔、发型、服装、妆容保持一致；姿势、表情、镜头角度和构图可以变化。"
    "自然的真实速度，没有慢动作。除描述的人物外不出现其他人。"
)
IMAGE_NO_TEXT_ZH = "画面中任何地方都不出现文字、标志或水印。"
# 中文模式直接把中文交给 H3：文本编码器是 Qwen3-VL，能读懂中文。
CATEGORY_ZH = {
    "free": {
        "hint": "一段中文描述：画面风格、场景、按秒分镜、机位、声音、台词。台词放在引号里。",
        "prompt": (
            "竖屏手机风格视频，柔和自然光，真实皮肤质感，细腻颗粒，画面中不出现任何文字。\n\n场景概述：\n\n分镜：\n[0s-5s] \n\n"
            "镜头：固定机位。\n\n声音：\n\n配乐：无\n\n"
            "画面中不出现任何文字、字幕、招牌、标志或水印。"
        ),
    },
    "wuxia": {
        "sections": {
            "subject_definitions": "一位身穿飘逸白色汉服的年轻女剑客……画面中没有其他人。",
            "retention_analysis": IDENTITY_RETENTION_ZH + "逆光金色轮廓光，面部有柔和补光。没有光晕、能量球或法术特效。",
            "detailed_description": "0-2 s: ……镜头缓缓向左环绕她，停在四分之三侧面。2-4 s: ……",
            "overall_soundscape": "风吹竹林声、丝绸摩擦声、石板上轻柔的脚步声。没有清晰的说话声。",
            "non_diegetic_music": "无。",
        },
    },
    "trail": {
        "sections": {
            "subject_definitions": "<Picture 1> 是第一帧：上一镜的最后一帧，画面里是……（诗人或旅人：年龄、面容、胡须、服装、头饰、道具），在……（地点、季节、时辰、光线）。镜头直接从这一帧接着拍，人物、服装、地点和光线保持不变。",
            "summary": "一个连续镜头：……",
            "retention_analysis": "画面从边到边都是干净的真人实拍，标明朝代的电影感中国古装片质感：克制的水墨色调，雾蓝灰、淡玉青和暖琥珀，只用自然光，细腻胶片颗粒，服装和建筑符合史实。" + IDENTITY_RETENTION_ZH + "画面任何地方都不出现字幕、说明文字或书写的字。",
            "detailed_description": "[Shot 1] (0–7 s) 与 <Picture 1> 同一地点。镜头缓缓……然后停住。0-4 s: …… 4-7 s: …… 约 0.5 秒起，画外一位成熟男声用普通话以旁白朗诵，缓慢、温暖、浑厚，句间自然换气：“……” 唯一的声音是旁白；画面里没有人说话：人物双唇紧闭，从不看向镜头。一个连续镜头，没有剪切。",
            "overall_soundscape": "……唯一的人声是画外旁白朗诵引号里的句子，没有其他说话声。",
            "non_diegetic_music": "贯穿全系列的同一段舒缓古琴独奏，伴着轻柔的箫声，压低在朗诵之下。",
        },
    },
    "trail_card": {
        "prompt": (
            "一张竖版 9:16 纪录片片头图：一幅画在泛黄、带柔和折痕的赭色绢本上的……（朝代）中国古地图，克制的水墨风格。山用青绿笔触画出，"
            "黄河与长江是流畅的细墨线，东面和南面的海是淡淡的波纹，四周有一圈淡淡的锦缎装裱边。小墨点标出他走过的地方，"
            "一条细细的朱砂线按顺序把它们连起来：……（每个地方写清在地图上的方位）。朱砂线停在……一个发光的朱砂点上，周围有柔和的暖色光晕。\n\n"
            "顶部居中，一行优雅的黑色楷书标题写着“……”。发光的点旁边，一个黑色书法小标签写着“……”。底部居中，一行黑色楷书写着“……”。\n\n"
            "左上方柔和的暖光，细腻的绢纸质感，细节丰富，构图沉静典雅、留白充足。所有文字清晰、书写正确，与引号中完全一致；不出现其他文字、印章、标志或水印。"
        ),
    },
    "photo": {
        "hint": "一段完整的画面描述：主体、动作、环境、光线、镜头焦段、质感。描述越完整越好。",
        "prompt": (
            "一张写实摄影照片：……\n\n主体：……\n场景：……\n"
            "光线：左侧柔和的自然窗光，阴影柔和。\n"
            "镜头：全画幅相机，50mm 镜头，光圈 f/2，平视，浅景深。\n"
            "质感：真实的皮肤和材质细节，轻微胶片颗粒，自然色彩。\n" + IMAGE_NO_TEXT_ZH
        ),
    },
    "poster": {
        "prompt": (
            "一张完成的海报设计：……\n\n"
            "版式：上方三分之二是……的大幅主视觉，留白充足，网格干净。\n"
            "文字：顶部大标题写着“……”，粗体窄体；下方一行小字写着“……”；底部日期行写着“……”。\n"
            "风格：……\n配色：……\n"
            "所有文字清晰、准确，与引号中完全一致；不出现其他文字。"
        ),
    },
    "illustration": {
        "prompt": (
            "一幅细致的概念插画：……\n\n媒介与画风：……\n"
            "前景：……\n中景：……\n背景：……\n光线与氛围：……\n" + IMAGE_NO_TEXT_ZH
        ),
    },
    "keyframe": {
        "prompt": (
            "一张电影感的真人实拍剧照，用作视频的第一帧。\n\n主体：……\n场景：……\n"
            "镜头：平视，35mm 镜头，主体位于画面左侧三分之一。\n光线：……\n"
            "真实的实拍质感，自然的皮肤纹理，没有运动模糊。不出现文字、字幕、标志或水印。"
        ),
    },
}
for _item in CATEGORIES:
    for _key, _value in CATEGORY_ZH.get(_item["id"], {}).items():
        _item[f"{_key}_zh"] = _value
ZH_PROMPT_WARN = "中文模式：引号外的中文会直接交给 H3。它能读懂中文，但偶尔会把中文当字幕画进画面，建议先用预览清晰度确认"
CATEGORY_IDS = {item["id"] for item in CATEGORIES}
CATEGORY_KIND = {item["id"]: item["kind"] for item in CATEGORIES}
FORMATS = {
    "portrait": {"label": "竖屏 9:16", "kinds": ["video", "image"], "sizes": {"preview": (352, 608), "standard": (480, 864), "hd": (768, 1344), "fhd": (1088, 1920)},
                 "image_sizes": {"4mp": (1536, 2720), "9mp": (2304, 4096), "16mp": (3072, 5472)}},
    "landscape": {"label": "横屏 16:9", "kinds": ["video", "image"], "sizes": {"preview": (608, 352), "standard": (864, 480), "hd": (1344, 768), "fhd": (1920, 1088)},
                  "image_sizes": {"4mp": (2720, 1536), "9mp": (4096, 2304), "16mp": (5472, 3072)}},
    "square": {"label": "方形 1:1", "kinds": ["video", "image"], "sizes": {"preview": (448, 448), "standard": (640, 640), "hd": (1024, 1024), "fhd": (1440, 1440)},
               "image_sizes": {"4mp": (2048, 2048), "9mp": (3072, 3072), "16mp": (4096, 4096)}},
    "portrait_34": {"label": "竖幅 3:4", "kinds": ["image"], "image_sizes": {"4mp": (1728, 2304), "9mp": (2592, 3456), "16mp": (3552, 4736)}},
    "landscape_43": {"label": "横幅 4:3", "kinds": ["image"], "image_sizes": {"4mp": (2304, 1728), "9mp": (3456, 2592), "16mp": (4736, 3552)}},
}
IMAGE_QUALITIES = {
    "4mp": {"label": "标准 · 4MP", "note": "文生图约 3.5 分钟，参考图编辑约 8 分钟"},
    "9mp": {"label": "精细 · 9MP", "note": "预计约为标准的 3 倍，确认构图后再用"},
    "16mp": {"label": "原生 · 16MP", "note": "模型原生 4K，预计 30 分钟以上，耗时和内存最高"},
}
IMAGE_MODES = {"t2i": "文生图", "edit": "参考图编辑"}
MAX_REFS = 4
QUALITIES = {
    "preview": {"label": "预览 · 0.2MP", "note": "5 秒约 7 分钟"},
    "standard": {"label": "标准 · 0.4MP", "note": "5 秒约 13 分钟"},
    "hd": {"label": "高清 · 768p", "note": "耗时和内存都明显更高，先用预览确认"},
    "fhd": {"label": "高清 · 1080p", "note": "像素约为 768p 的 2 倍，耗时和内存最高"},
}
MODES = {"t2v": "文生视频", "i2v": "首帧生视频", "flf": "首尾帧"}
# ComfyUI 核心的 EasyCache：特征变化小的步直接复用上一步的输出差。8 步蒸馏下能跳的步不多，先当实验开关
STEP_CACHE = {"reuse_threshold": 0.2, "start_percent": 0.15, "end_percent": 0.95}
ACTIVE = {"queued", "submitted", "running", "finishing"}
STATUS_LABELS = {"queued": "等待提交", "submitted": "排队中", "running": "生成中", "finishing": "整理中",
                 "done": "已完成", "failed": "失败", "cancelled": "已取消"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_SERIES = 60
MAX_GROUPS = 40
MAX_EPISODES = 200
MAX_SHOTS = 16
# intro 序章（排在正片前）、bridge 承上启下（排在全诗片尾后）
SHOT_ROLES = {"", "intro", "bridge"}
# 配音记录里承上解说（分集的 recap）占用的镜头号
RECAP = -1
COMPOSE_END_SECONDS = 7
MEDIA_KINDS = ("video", "thumb", "sheet", "first", "last", "image", "preview", "source", "tail", "srt", "voice_track", "music_track") + tuple(f"ref{i}" for i in range(1, MAX_REFS + 1))
STEP_RE = re.compile(r"(\d+)/(\d+) \[")


class AiStudioError(ValueError):
    pass


def video_frames(seconds: float) -> int:
    """24 fps，向上取到模型接受的 17n+5 帧。"""
    n = max(5, round(seconds * 24))
    return n + (5 - n % 17) % 17


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _comfy(path: str, payload: dict | None = None, timeout: float = 10):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(f"{COMFY_URL}{path}", data=data, method="POST" if data is not None else "GET",
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw.strip() else {}


def _comfy_up() -> bool:
    try:
        _comfy("/system_stats", timeout=1.5)
        return True
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def _missing_models(models: dict) -> list[str]:
    return [name for name in dict.fromkeys(models.values()) if not any(
        (COMFY_DIR / "models" / folder / name).is_file() for folder in MODEL_FOLDERS)]


def _log_size() -> int:
    try:
        return COMFY_LOG_PATH.stat().st_size
    except OSError:
        return 0


def _load_prompt_lint():
    path = STUDIO_REPO / "tools" / "prompt_lint.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("h3_prompt_lint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compose_prompt(style: str, sections: dict, free_text: str) -> str:
    if style == "free":
        return str(free_text or "").strip()
    return "\n".join(f"{key}: {str(sections.get(key) or '').strip()}" for key in SECTIONS).strip()


def build_graph(job: dict, first_name: str = "", last_name: str = "", soundtrack_name: str = "") -> dict:
    """MacMax 默认的 Parasyte 8 步路径（API 格式），只保留文生 / 首帧 / 首尾帧需要的节点。"""
    conditioning = {"clip": ["13", 0], "vae": ["11", 0], "prompt": job["prompt"],
                    "width": job["width"], "height": job["height"], "length": job["frames"]}
    graph = {
        "140": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": MODELS["unet"]}},
        "141": {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["140", 0], "lora_name": MODELS["lora"], "strength_model": 1.5}},
        "143": {"class_type": "H3AdaLNLoRAFix", "inputs": {"model": ["141", 0], "mode": "strip"}},
        "119": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["143", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "13": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": MODELS["clip"], "type": "minimax"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": MODELS["video_vae"]}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": MODELS["audio_vae"]}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": conditioning},
        "16": {"class_type": "BasicGuider", "inputs": {"model": ["119", 0], "conditioning": ["104", 0]}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["119", 0], "scheduler": "beta57", "steps": 8, "denoise": 1.0}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "er_sde"}},
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": job["seed"]}},
        "14": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["15", 0], "guider": ["16", 0], "sampler": ["17", 0], "sigmas": ["9", 0], "latent_image": ["104", 1]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["11", 0]}},
        "23": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["24", 0]}},
        "91": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "audio": ["23", 0], "fps": 24.0}},
        "92": {"class_type": "SaveVideo",
               "inputs": {"video": ["91", 0], "filename_prefix": f"ai-studio/{job['id']}", "format": "auto", "codec": "auto"}},
    }
    if first_name:
        graph["121"] = {"class_type": "LoadImage", "inputs": {"image": first_name}}
        conditioning["first_frame"] = ["121", 0]
    if last_name:
        graph["122"] = {"class_type": "LoadImage", "inputs": {"image": last_name}}
        conditioning["last_frame"] = ["122", 0]
    if soundtrack_name:
        # 对口型：整条配音从第 0 帧锚进音频潜变量，画面跟着这条声轨生成
        graph["123"] = {"class_type": "LoadAudio", "inputs": {"audio": soundtrack_name}}
        graph["124"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": ["104", 0], "latent": ["104", 1], "audio_vae": ["24", 0],
                                                                      "audio": ["123", 0], "frame_idx": 0}}
        graph["16"]["inputs"]["conditioning"] = ["124", 0]
    if job.get("fast"):
        graph["145"] = {"class_type": "EasyCache", "inputs": {"model": ["119", 0], **STEP_CACHE, "verbose": True}}
        graph["16"]["inputs"]["model"] = ["145", 0]
    return graph


def build_image_graph(job: dict, ref_names: list[str]) -> dict:
    """MiniMax H3-Image：6 步、cfg 1、无负面提示词（这些值由蒸馏 checkpoint 固定）。"""
    conditioning = {"clip": ["2", 0], "vae": ["3", 0], "prompt": job["prompt"],
                    "width": job["width"], "height": job["height"]}
    graph = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": IMAGE_MODELS["unet"]}},
        "2": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": IMAGE_MODELS["clip"], "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": IMAGE_MODELS["vae"]}},
        "4": {"class_type": "MiniMaxH3ImageConditioning", "inputs": conditioning},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["4", 1],
                         "seed": job["seed"], "steps": 6, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": f"ai-studio/{job['id']}"}},
    }
    for index, name in enumerate(ref_names, start=1):
        graph[f"2{index}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        conditioning[f"images.image_{index}"] = [f"2{index}", 0]
    return graph


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError, ImportError):
        return None


def _nearest_image_format(size: tuple[int, int] | None) -> str:
    if not size or not size[1]:
        return "square"
    ratio = size[0] / size[1]
    candidates = [key for key, item in FORMATS.items() if "image" in item["kinds"]]
    return min(candidates, key=lambda key: abs(math.log(ratio * FORMATS[key]["image_sizes"]["4mp"][1] / FORMATS[key]["image_sizes"]["4mp"][0])))


def _shot_index(payload: dict) -> int:
    try:
        return max(0, min(MAX_SHOTS - 1, int(payload.get("shot") or 0)))
    except (TypeError, ValueError):
        return 0


def _safe_title(text: str) -> str:
    title = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(text or "").strip())[:40].strip("._")
    return title or "未命名"


def _decode_image(data_url: str) -> tuple[bytes, str]:
    match = re.fullmatch(r"data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\s]+)", str(data_url or ""), re.S)
    if not match:
        raise AiStudioError("图片格式只支持 PNG、JPEG 或 WebP")
    content = base64.b64decode(match.group(2))
    if len(content) > MAX_IMAGE_BYTES:
        raise AiStudioError("图片不能超过 15 MB")
    signatures = {"png": b"\x89PNG", "jpeg": b"\xff\xd8", "jpg": b"\xff\xd8", "webp": b"RIFF"}
    kind = match.group(1)
    if not content.startswith(signatures[kind]):
        raise AiStudioError("图片内容与格式不符")
    return content, "jpg" if kind == "jpeg" else kind


class AiStudio:
    def __init__(self, jobs_path: Path, ensure_comfy=None, ffmpeg: str | None = None):
        self.jobs_path = jobs_path
        self.ensure_comfy = ensure_comfy
        # launchd / systemd 下 PATH 很短，which 找不到时按 Homebrew、系统目录再找一遍
        self.ffmpeg = ffmpeg or os.environ.get("FFMPEG") or shutil.which("ffmpeg") or next(
            (path for path in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg") if Path(path).is_file()), "ffmpeg")
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.voice_wake = threading.Event()
        self.stem_lock = threading.Lock()
        self.voices: list[dict] = []
        self.jobs, self.series = self._load()
        for job in self.jobs:
            if (job.get("final") or job.get("mode") == "map") and job.get("status") == "finishing":
                job.update(status="failed", error="合成中途服务重启，请重新合成", progress=None)
        for voice in self.voices:
            if voice.get("status") == "running":
                voice["status"] = "queued"
        self.lint_module = None
        self.worker = threading.Thread(target=self._loop, name="ai-studio", daemon=True)
        self.worker.start()
        self.voice_worker = threading.Thread(target=self._voice_loop, name="ai-studio-voice", daemon=True)
        self.voice_worker.start()

    # ---------- 持久化 ----------
    def _load(self) -> tuple[list[dict], list[dict]]:
        try:
            data = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], []
        if not isinstance(data, dict):
            return [], []
        jobs = [job for job in data.get("jobs", []) if isinstance(job, dict)]
        series = [item for item in data.get("series", []) if isinstance(item, dict) and item.get("id")]
        self.voices = [item for item in data.get("voices", []) if isinstance(item, dict) and item.get("id")]
        return jobs, series

    def _save(self) -> None:
        self.jobs_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.jobs_path.parent,
                                         prefix=f".{self.jobs_path.name}.", suffix=".tmp", delete=False) as handle:
            handle.write(json.dumps({"series": self.series, "jobs": self.jobs, "voices": self.voices}, ensure_ascii=False, indent=1) + "\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.jobs_path)

    def _job(self, job_id: str) -> dict:
        for job in self.jobs:
            if job.get("id") == job_id:
                return job
        raise AiStudioError("任务不存在")

    # ---------- 系列 ----------
    def _series(self, series_id: str) -> dict:
        for item in self.series:
            if item.get("id") == series_id:
                return item
        raise AiStudioError("系列不存在")

    def _placement(self, payload: dict) -> tuple[str, str, str]:
        """payload 里的 series / group / episode 校验后返回；空串表示未归入系列 / 未分组 / 不属于分集。"""
        series_id = str(payload.get("series") or "")
        if not series_id:
            return "", "", ""
        with self.lock:
            series = self._series(series_id)
            group_id = str(payload.get("group") or "")
            if group_id and not any(group.get("id") == group_id for group in series.get("groups") or []):
                raise AiStudioError("分组不存在")
            episode_id = str(payload.get("episode") or "")
            if episode_id and not any(item.get("id") == episode_id for item in series.get("episodes") or []):
                episode_id = ""
        return series_id, group_id, episode_id

    @staticmethod
    def _shot_fields(raw: dict) -> dict:
        sections = raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
        try:
            seconds = min(12.0, max(4.5, float(raw.get("seconds") or 12)))
        except (TypeError, ValueError):
            seconds = 12.0
        return {
            "mode": raw.get("mode") if raw.get("mode") in MODES else "i2v",
            "lines": str(raw.get("lines") or "").strip()[:300],
            "format": raw.get("format") if raw.get("format") in FORMATS and "video" in FORMATS[raw["format"]]["kinds"] else "portrait",
            "quality": raw.get("quality") if raw.get("quality") in QUALITIES else "preview",
            "seconds": seconds,
            "sections": {key: str(sections.get(key) or "").strip()[:6000] for key in SECTIONS},
            "role": raw.get("role") if raw.get("role") in SHOT_ROLES else "",
            "image_prompt": str(raw.get("image_prompt") or "").strip()[:20000],
            "last_from": raw.get("last_from") if raw.get("last_from") in {"card", "next_card"} else "",
            "stages": [int(item) for item in raw.get("stages") or [] if isinstance(item, int) and 0 <= item < 20][:10],
            "caption_title": str(raw.get("caption_title") or "").strip()[:60],
            "caption_line": str(raw.get("caption_line") or "").strip()[:80],
            "route_to": raw.get("route_to") if isinstance(raw.get("route_to"), int) and 0 <= raw["route_to"] < MAX_ROUTE else 0,
            "voice": str(raw.get("voice") or "").strip()[:400],
        }

    @staticmethod
    def _route_fields(raw) -> list[dict]:
        stops = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                lon, lat = float(item.get("lon")), float(item.get("lat"))
            except (TypeError, ValueError):
                continue
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                stops.append({"name": str(item.get("name") or "").strip()[:8], "lon": round(lon, 4), "lat": round(lat, 4),
                              "anchor": item.get("anchor") if item.get("anchor") in {"e", "w", "n", "s"} else ""})
        return stops[:MAX_ROUTE]

    @staticmethod
    def _episode_fields(raw: dict, group_ids: set[str], existing_ids: set[str]) -> dict:
        def text(value, limit: int) -> str:
            return str(value or "").strip()[:limit]

        image = raw.get("image") if isinstance(raw.get("image"), dict) else {}
        shots = [item for item in raw.get("shots") or [] if isinstance(item, dict)]
        if not shots and isinstance(raw.get("video"), dict):
            shots = [{**raw["video"], "mode": "i2v", "lines": raw.get("recite")}]
        if len(shots) > MAX_SHOTS:
            raise AiStudioError(f"一个分集最多 {MAX_SHOTS} 个镜头")
        episode_id = str(raw.get("id") or "")
        return {
            "id": episode_id if episode_id in existing_ids else uuid.uuid4().hex[:8],
            "group": str(raw.get("group") or "") if str(raw.get("group") or "") in group_ids else "",
            "title": text(raw.get("title"), 60) or "未命名分集",
            "poem_title": text(raw.get("poem_title"), 60), "author": text(raw.get("author"), 30),
            "place": text(raw.get("place"), 40), "date": text(raw.get("date"), 80), "post": text(raw.get("post"), 80),
            "age": text(raw.get("age"), 20),
            "poem": text(raw.get("poem"), 2000), "note": text(raw.get("note"), 1000),
            # 承上解说：片头前一小段旁白，交代上一集之后发生了什么（用系列解说音色配音，不用出视频）
            "recap": text(raw.get("recap"), 200),
            "route": AiStudio._route_fields(raw.get("route")),
            # 本集朗读参考：配音照这一条原片的声音和语气读（任务 id），空则用系列的旁白音色
            "narrator": re.sub(r"[^\w-]", "", str(raw.get("narrator") or ""))[:40],
            # 整集背景音乐取自哪一镜原片的伴奏（任务 id），空则用朗读参考那一镜，再没有就用第一镜
            "music": re.sub(r"[^\w-]", "", str(raw.get("music") or ""))[:40],
            "image": {
                "format": image.get("format") if image.get("format") in FORMATS and "image" in FORMATS[image["format"]]["kinds"] else "portrait",
                "quality": image.get("quality") if image.get("quality") in IMAGE_QUALITIES else "4mp",
                "prompt": text(image.get("prompt"), 20000),
            },
            "shots": [AiStudio._shot_fields(item) for item in shots],
        }

    @staticmethod
    def _series_fields(payload: dict, existing: dict | None = None) -> dict:
        existing = existing or {}
        name = str(payload.get("name", existing.get("name", "")) or "").strip()[:30]
        if not name:
            raise AiStudioError("请填写系列名称")
        old_groups = {group["id"]: group for group in existing.get("groups") or []}
        groups, names = [], set()
        for raw in (payload.get("groups") if "groups" in payload else existing.get("groups")) or []:
            if not isinstance(raw, dict):
                continue
            group_name = str(raw.get("name") or "").strip()[:30]
            if not group_name or group_name in names:
                continue
            names.add(group_name)
            group_id = str(raw.get("id") or "")
            groups.append({"id": group_id if group_id in old_groups else uuid.uuid4().hex[:8], "name": group_name,
                           "note": str(raw.get("note") or "").strip()[:600]})
        if len(groups) > MAX_GROUPS:
            raise AiStudioError(f"一个系列最多 {MAX_GROUPS} 个分组")
        group_ids = {group["id"] for group in groups}
        existing_episodes = {item.get("id") for item in existing.get("episodes") or []}
        raw_episodes = payload.get("episodes") if "episodes" in payload else existing.get("episodes")
        episodes = [AiStudio._episode_fields(raw, group_ids, existing_episodes) for raw in raw_episodes or [] if isinstance(raw, dict)]
        if len(episodes) > MAX_EPISODES:
            raise AiStudioError(f"一个系列最多 {MAX_EPISODES} 个分集")
        return {
            "name": name,
            # 成片库里按类别把系列归到一起；空 = 「其他」
            "category": str(payload.get("category", existing.get("category", "")) or "").strip()[:20],
            "description": str(payload.get("description", existing.get("description", "")) or "").strip()[:1000],
            "style": str(payload.get("style", existing.get("style", "")) or "").strip()[:3000],
            "route": AiStudio._route_fields(payload.get("route", existing.get("route"))),
            # 配音：旁白音色取自哪一条视频的原声（任务 id，空 = 每镜用自己原片的声音）；读音表每行「词语 拼音…」
            "narrator": re.sub(r"[^\w-]", "", str(payload.get("narrator", existing.get("narrator", "")) or ""))[:40],
            "pron": str(payload.get("pron", existing.get("pron", "")) or "").strip()[:4000],
            # 片尾整首诗旁钤的小印，一个字；空则用「坡」
            "seal": str(payload.get("seal", existing.get("seal", "")) or "").strip()[:1],
            "groups": groups,
            "episodes": episodes,
        }

    def create_series(self, payload: dict) -> dict:
        fields = self._series_fields(payload)
        with self.lock:
            if len(self.series) >= MAX_SERIES:
                raise AiStudioError(f"最多 {MAX_SERIES} 个系列")
            if any(item.get("name") == fields["name"] for item in self.series):
                raise AiStudioError("已经有同名系列")
            series = {"id": uuid.uuid4().hex[:8], **fields, "created_at": _now()}
            self.series.append(series)
            self._save()
            return series

    def update_series(self, series_id: str, payload: dict) -> dict:
        with self.lock:
            series = self._series(series_id)
            fields = self._series_fields(payload, series)
            if any(item.get("name") == fields["name"] and item is not series for item in self.series):
                raise AiStudioError("已经有同名系列")
            series.update(fields)
            kept = {group["id"] for group in fields["groups"]}
            kept_episodes = {item["id"] for item in fields["episodes"]}
            for job in self.jobs:
                if job.get("series") == series_id and job.get("group") and job["group"] not in kept:
                    job["group"] = ""
                if job.get("series") == series_id and job.get("episode") and job["episode"] not in kept_episodes:
                    job["episode"] = ""
            self._save()
            return series

    def delete_series(self, series_id: str) -> None:
        """只删系列本身：其中的作品回到「未归入系列」，文件不动。"""
        with self.lock:
            series = self._series(series_id)
            self.series.remove(series)
            for job in self.jobs:
                if job.get("series") == series_id:
                    job["series"], job["group"], job["episode"] = "", "", ""
            self._save()

    # ---------- 对外接口 ----------
    def config(self) -> dict:
        return {
            "categories": CATEGORIES,
            "formats": FORMATS,
            "qualities": QUALITIES,
            "modes": MODES,
            "image_qualities": IMAGE_QUALITIES,
            "image_modes": IMAGE_MODES,
            "max_refs": MAX_REFS,
            "sections": [{"key": key, "label": SECTION_LABELS[key]} for key in SECTIONS],
            "status_labels": STATUS_LABELS,
            "library_dir": str(LIBRARY_DIR),
            "models": MODELS,
            "image_models": IMAGE_MODELS,
        }

    def state(self) -> dict:
        with self.lock:
            jobs = [self._public(job) for job in reversed(self.jobs)]
            series = json.loads(json.dumps(self.series))
            voices = [{key: value for key, value in item.items() if key not in {"file", "spoken"}} for item in self.voices]
        return {"jobs": jobs, "series": series, "voices": voices, "voice_available": self._voice_ready() == "",
                "voice_missing": self._voice_ready(), "comfy_running": _comfy_up(), "missing_models": _missing_models(MODELS),
                "missing_image_models": _missing_models(IMAGE_MODELS),
                "qc_available": TAKE_GATE_PYTHON.is_file(), "lint_available": (STUDIO_REPO / "tools" / "prompt_lint.py").is_file()}

    def _public(self, job: dict) -> dict:
        result = {key: value for key, value in job.items() if key not in {"files"}}
        files = job.get("files") or {}
        result["kind"] = job.get("kind") or "video"
        result["series"], result["group"], result["episode"] = job.get("series") or "", job.get("group") or "", job.get("episode") or ""
        result["shot"], result["final"] = int(job.get("shot") or 0), bool(job.get("final"))
        result["has"] = {kind: bool(files.get(kind)) and Path(files[kind]).is_file() for kind in MEDIA_KINDS}
        result["video_path"] = files.get("video", "")
        result["image_path"] = files.get("image", "")
        result["status_label"] = STATUS_LABELS.get(job.get("status"), job.get("status", ""))
        if job.get("status") in ACTIVE and job.get("started_at_ts"):
            result["elapsed"] = round(time.time() - job["started_at_ts"])
        return result

    def lint(self, payload: dict) -> dict:
        if payload.get("kind") == "image":
            return self._lint_image(payload)
        chinese = payload.get("lang") == "zh"
        style = "free" if payload.get("style") == "free" else "structured"
        if style == "free":
            text = str(payload.get("free_text") or "")
            blanked = re.sub(r"“[^”]*”|\"[^\"]*\"|「[^」]*」", "", text)
            cjk = sorted(set(re.findall(r"[\u3400-\u9fff]+", blanked)))
            short = (len(text) <= 30) if chinese else (len(text) <= 80)
            warns = ["描述太短：写清场景、动作、机位和声音，画面才会动起来"] if short else []
            if chinese:
                return {"errors": [], "warns": ([ZH_PROMPT_WARN] if cjk else []) + warns}
            errors = [f"引号外出现中文：{'、'.join(cjk[:6])}。H3 会把它当字幕烧进画面，请改写成英文，中文只放在引号台词里"] if cjk else []
            return {"errors": errors, "warns": warns}
        if self.lint_module is None:
            self.lint_module = _load_prompt_lint()
        if self.lint_module is None:
            return {"errors": [], "warns": ["找不到 prompt_lint.py，跳过检查"]}
        text = compose_prompt(style, payload.get("sections") or {}, "")
        secs = float(payload.get("seconds") or 5)
        errors, warns = self.lint_module.lint(text, secs)
        if chinese:
            chinese_errors = [item for item in errors if "Chinese outside a spoken line" in item]
            errors = [item for item in errors if item not in chinese_errors]
            if chinese_errors:
                warns = [ZH_PROMPT_WARN, *warns]
        return {"errors": errors, "warns": warns}

    @staticmethod
    def _lint_image(payload: dict) -> dict:
        text = str(payload.get("free_text") or "")
        errors, warns = [], []
        if "..." in text or "…" in text.replace("“…”", ""):
            errors.append("模板里还有「...」没有填写")
        blanked = re.sub(r"“[^”]*”|\"[^\"]*\"|「[^」]*」|‘[^’]*’", "", text)
        cjk = sorted(set(re.findall(r"[\u3400-\u9fff]+", blanked)))
        if cjk and payload.get("lang") != "zh":
            warns.append(f"引号外出现中文：{'、'.join(cjk[:6])}。H3-Image 读完整英文描述效果最好，要画进图里的中文字请放进引号")
        if len(text) < (80 if payload.get("lang") == "zh" else 200):
            warns.append("描述偏短：H3-Image 适合完整、具体的长描述（主体、环境、光线、镜头、质感）")
        refs = [item for item in payload.get("ref_images") or [] if item]
        if payload.get("mode") == "edit" and refs and "<Picture 1>" not in text:
            warns.append("编辑模式建议在提示词里用 <Picture 1>、<Picture 2> 指代参考图")
        return {"errors": errors, "warns": warns}

    def create(self, payload: dict) -> dict:
        series_id, group_id, episode_id = self._placement(payload)
        if payload.get("kind") == "image" or CATEGORY_KIND.get(payload.get("category")) == "image":
            if episode_id and _shot_index(payload) == 0 and MAP_DATA_DIR.is_dir():
                drawn = self._draw_card(payload, series_id, group_id, episode_id)
                if drawn:
                    return drawn
            return self._create_image(payload, series_id, group_id, episode_id)
        category = payload.get("category") if CATEGORY_KIND.get(payload.get("category")) == "video" else "free"
        if payload.get("format") not in FORMATS or "video" not in FORMATS[payload["format"]]["kinds"]:
            payload = {**payload, "format": "portrait"}
        fmt = payload.get("format") if payload.get("format") in FORMATS else "portrait"
        quality = payload.get("quality") if payload.get("quality") in QUALITIES else "preview"
        mode = payload.get("mode") if payload.get("mode") in MODES else "t2v"
        style = "free" if payload.get("style") == "free" else "structured"
        sections = {key: str((payload.get("sections") or {}).get(key) or "") for key in SECTIONS}
        prompt = compose_prompt(style, sections, payload.get("free_text") or "")
        if len(prompt) < 20:
            raise AiStudioError("提示词太短")
        if len(prompt) > 12000:
            raise AiStudioError("提示词太长")
        try:
            seconds = float(payload.get("seconds") or 5)
        except (TypeError, ValueError):
            raise AiStudioError("时长无效") from None
        if not 1 <= seconds <= 12:
            raise AiStudioError("时长需在 1–12 秒之间")
        seed_text = str(payload.get("seed") or "").strip()
        seed = int(seed_text) if seed_text.isdigit() else random.randint(1, 2**31 - 1)
        if mode != "t2v" and not payload.get("first_image"):
            raise AiStudioError("首帧生视频需要上传首帧图片")
        if mode == "flf" and not payload.get("last_image"):
            raise AiStudioError("首尾帧模式需要上传尾帧图片")
        lint = self.lint({**payload, "style": style})
        if lint["errors"] and not payload.get("force"):
            raise AiStudioError("提示词检查未通过：" + "；".join(lint["errors"][:3]))
        width, height = FORMATS[fmt]["sizes"][quality]
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        job = {
            "id": job_id, "kind": "video", "title": str(payload.get("title") or "").strip()[:60] or "未命名镜头",
            "series": series_id, "group": group_id, "episode": episode_id, "shot": _shot_index(payload) if episode_id else 0,
            "category": category, "format": fmt, "quality": quality, "mode": mode, "style": style,
            "sections": sections if style == "structured" else {}, "free_text": prompt if style == "free" else "",
            "prompt": prompt, "seconds": seconds, "frames": video_frames(seconds), "seed": seed,
            "width": width, "height": height, "status": "queued", "created_at": _now(),
            "lint": lint, "files": {}, "progress": None, "error": "", "lang": "zh" if payload.get("lang") == "zh" else "en",
            "fast": bool(payload.get("fast")),
        }
        inputs = LIBRARY_DIR / ".inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        for kind in ("first", "last"):
            if (kind == "first" and mode != "t2v") or (kind == "last" and mode == "flf"):
                content, suffix = _decode_image(payload.get(f"{kind}_image"))
                target = inputs / f"{job_id}_{kind}.{suffix}"
                target.write_bytes(content)
                job["files"][kind] = str(target)
        return self._enqueue(job)

    def _create_image(self, payload: dict, series_id: str = "", group_id: str = "", episode_id: str = "") -> dict:
        missing = _missing_models(IMAGE_MODELS)
        if missing:
            raise AiStudioError("图片模型还没准备好：缺少 " + "、".join(missing))
        category = payload.get("category") if CATEGORY_KIND.get(payload.get("category")) == "image" else "photo"
        quality = payload.get("quality") if payload.get("quality") in IMAGE_QUALITIES else "4mp"
        mode = payload.get("mode") if payload.get("mode") in IMAGE_MODES else "t2i"
        prompt = str(payload.get("free_text") or "").strip()
        if len(prompt) < 20:
            raise AiStudioError("提示词太短")
        if len(prompt) > 20000:
            raise AiStudioError("提示词太长")
        refs = [item for item in payload.get("ref_images") or [] if item][:MAX_REFS] if mode == "edit" else []
        if mode == "edit" and not refs:
            raise AiStudioError("参考图编辑需要至少上传一张图片")
        lint = self._lint_image({**payload, "mode": mode})
        if lint["errors"] and not payload.get("force"):
            raise AiStudioError("提示词检查未通过：" + "；".join(lint["errors"][:3]))
        seed_text = str(payload.get("seed") or "").strip()
        seed = int(seed_text) if seed_text.isdigit() else random.randint(1, 2**31 - 1)
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        files = {}
        inputs = LIBRARY_DIR / ".inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        for index, data_url in enumerate(refs, start=1):
            content, suffix = _decode_image(data_url)
            target = inputs / f"{job_id}_ref{index}.{suffix}"
            target.write_bytes(content)
            files[f"ref{index}"] = str(target)
        fmt = payload.get("format")
        if fmt == "auto" and files:
            fmt = _nearest_image_format(_image_size(Path(files["ref1"])))
        if fmt not in FORMATS or "image" not in FORMATS[fmt]["kinds"]:
            fmt = next(item["format"] for item in CATEGORIES if item["id"] == category)
        width, height = FORMATS[fmt]["image_sizes"][quality]
        job = {
            "id": job_id, "kind": "image", "title": str(payload.get("title") or "").strip()[:60] or "未命名图片",
            "series": series_id, "group": group_id, "episode": episode_id, "shot": _shot_index(payload) if episode_id else 0,
            "category": category, "format": fmt, "quality": quality, "mode": mode, "style": "free",
            "sections": {}, "free_text": prompt, "prompt": prompt, "seed": seed, "width": width, "height": height,
            "status": "queued", "created_at": _now(), "lint": lint, "files": files, "progress": None, "error": "",
            "lang": "zh" if payload.get("lang") == "zh" else "en",
        }
        return self._enqueue(job)

    def _draw_card(self, payload: dict, series_id: str, group_id: str, episode_id: str) -> dict | None:
        """有经纬度路线的分集，片头图直接用程序画的行迹地图（和成片开场那一帧一样），不再让模型出图。"""
        with self.lock:
            series = next((item for item in self.series if item.get("id") == series_id), None)
            episode = next((item for item in (series or {}).get("episodes") or [] if item.get("id") == episode_id), None)
            if not episode or not episode.get("route"):
                return None
            route, date, name = list(episode["route"]), episode.get("date") or "", series.get("name") or ""
            job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
            job = {
                "id": job_id, "kind": "image", "title": str(payload.get("title") or "").strip()[:60] or f"{episode['title']} · 片头图",
                "series": series_id, "group": group_id, "episode": episode_id, "shot": 0, "category": "keyframe", "format": "portrait",
                "quality": "4mp", "mode": "map", "style": "free", "sections": {}, "free_text": "", "prompt": "行迹地图：" + " → ".join(
                    stop["name"] for stop in route), "seed": 0, "width": 1080, "height": 1920, "status": "finishing", "created_at": _now(),
                "started_at_ts": time.time(), "lint": {"errors": [], "warns": []}, "files": {}, "progress": None, "error": "", "lang": "zh",
            }
            self.jobs.append(job)
            self._save()
        threading.Thread(target=self._render_card, args=(job, route, date, name), daemon=True).start()
        return self._public(job)

    def _render_card(self, job: dict, route: list[dict], date: str, name: str) -> None:
        work = LIBRARY_DIR / ".compose" / job["id"]
        try:
            work.mkdir(parents=True, exist_ok=True)
            still = work / "card.png"
            here = len(route) - 1
            spec = {"width": job["width"], "height": job["height"], "fps": 24, "ffmpeg": self.ffmpeg, "title": name, "data_dir": str(MAP_DATA_DIR),
                    "clips": [{"still": str(still), "still_at": 1.0,
                               "segments": [{"route": route, "from": here, "to": here, "date_from": date, "duration": 1.0}]}]}
            (work / "map.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run([CAPTION_PYTHON, str(MAP_SCRIPT), str(work / "map.json")], capture_output=True, text=True, timeout=300)
            if result.returncode or not still.is_file():
                return self._finish(job, error="画行迹地图失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1])
            self._organize_image(job, still)
        except (OSError, subprocess.SubprocessError) as exc:
            self._finish(job, error=f"画行迹地图失败：{exc}")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _enqueue(self, job: dict) -> dict:
        with self.lock:
            self.jobs.append(job)
            self._save()
        self.wake.set()
        return self._public(job)

    def rerun(self, job_id: str, new_seed: bool = True, fast: bool | None = None) -> dict:
        with self.lock:
            source = self._job(job_id)
        if source.get("final"):
            return self.compose_episode(source.get("series") or "", source.get("episode") or "")
        payload = {key: source.get(key) for key in ("kind", "title", "series", "group", "episode", "shot", "category", "format", "quality", "mode", "style", "sections", "free_text", "seconds", "lang", "fast")}
        if payload.get("series") and not any(item.get("id") == payload["series"] for item in self.series):
            payload["series"], payload["group"] = "", ""
        payload["seed"] = "" if new_seed else str(source.get("seed"))
        payload["force"] = True
        if fast is not None:
            payload["fast"] = fast
        files = source.get("files") or {}

        def data_url(path: str) -> str:
            suffix = Path(path).suffix.lstrip(".").replace("jpg", "jpeg")
            return f"data:image/{suffix};base64," + base64.b64encode(Path(path).read_bytes()).decode()

        for kind in ("first", "last"):
            if files.get(kind) and Path(files[kind]).is_file():
                payload[f"{kind}_image"] = data_url(files[kind])
        payload["ref_images"] = [data_url(files[f"ref{i}"]) for i in range(1, MAX_REFS + 1)
                                 if files.get(f"ref{i}") and Path(files[f"ref{i}"]).is_file()]
        return self.create(payload)

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self._job(job_id)
            status, prompt_id = job.get("status"), job.get("comfy_prompt_id")
            if status not in ACTIVE:
                return self._public(job)
            job.update(status="cancelled", finished_at=_now(), progress=None)
            self._save()
        if prompt_id:
            try:
                if status == "running":
                    _comfy("/interrupt", {})
                else:
                    _comfy("/queue", {"delete": [prompt_id]})
            except (HTTPError, URLError, TimeoutError, OSError, ValueError):
                pass
        return self._public(job)

    def delete(self, job_id: str, remove_files: bool = True) -> None:
        with self.lock:
            job = self._job(job_id)
            if job.get("status") in ACTIVE:
                raise AiStudioError("任务还在进行，先取消再删除")
            self.jobs.remove(job)
            self._save()
        if remove_files:
            for path in (job.get("files") or {}).values():
                target = Path(path).resolve()
                if LIBRARY_DIR.resolve() in target.parents and target.is_file():
                    target.unlink()

    def update(self, job_id: str, payload: dict) -> dict:
        placement = self._placement(payload) if "series" in payload else None
        with self.lock:
            job = self._job(job_id)
            if placement is not None:
                episode = job.get("episode", "") if placement[0] == job.get("series") else ""
                job["series"], job["group"], job["episode"] = placement[0], placement[1], placement[2] or episode
            if "title" in payload:
                job["title"] = str(payload.get("title") or "").strip()[:60] or job["title"]
            if payload.get("rating") in {"", "keep", "reject"}:
                job["rating"] = payload["rating"]
            if "shot" in payload and job.get("episode"):
                job["shot"] = _shot_index(payload)
            self._save()
            return self._public(job)

    def media(self, job_id: str, kind: str) -> Path:
        if kind == "tail":
            self._ensure_tail(job_id)
        if kind == "voice":
            with self.lock:
                path = next((item.get("file") for item in self.voices if item.get("id") == job_id), "")
            target = Path(path or "/nonexistent").resolve()
            if VOICE_DIR.resolve() not in target.parents or not target.is_file():
                raise AiStudioError("文件不存在")
            return target
        with self.lock:
            path = (self._job(job_id).get("files") or {}).get(kind)
        if kind not in MEDIA_KINDS or not path:
            raise AiStudioError("文件不存在")
        target = Path(path).resolve()
        if LIBRARY_DIR.resolve() not in target.parents or not target.is_file():
            raise AiStudioError("文件不存在")
        return target

    def _ensure_tail(self, job_id: str) -> None:
        """视频的最后一帧，作为下一个镜头的首帧。"""
        with self.lock:
            job = self._job(job_id)
            files = job.get("files") or {}
            if files.get("tail") and Path(files["tail"]).is_file():
                return
            video = files.get("video")
        if not video or not Path(video).is_file():
            raise AiStudioError("这条还没有视频，取不到最后一帧")
        thumbs = LIBRARY_DIR / ".thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)
        target = thumbs / f"{job_id}_tail.png"
        subprocess.run([self.ffmpeg, "-v", "error", "-y", "-sseof", "-0.08", "-i", video, "-frames:v", "1", "-update", "1", str(target)],
                       capture_output=True, timeout=60)
        if not target.is_file():
            raise AiStudioError("提取最后一帧失败")
        with self.lock:
            job["files"] = {**(job.get("files") or {}), "tail": str(target)}
            self._save()

    # ---------- 配音 ----------
    @staticmethod
    def _voice_ready() -> str:
        if not VOICE_PYTHON.is_file():
            return "配音环境（index-tts）还没装好"
        needed = ["gpt.pth", "s2mel.pth", "codec.pth", "hf_cache/w2v-bert-2.0/model.safetensors", "hf_cache/campplus_cn_common.bin",
                  "hf_cache/bigvgan/bigvgan_generator.pt"]
        missing = [name for name in needed if not (VOICE_MODEL_DIR / name).is_file()]
        return f"配音模型还在下载：缺 {', '.join(Path(name).name for name in missing)}" if missing else ""

    @staticmethod
    def _pron_table(text: str) -> list[tuple[str, list[str]]]:
        """读音表：每行「词语 拼音 拼音…」，拼音带数字声调，ü 写作 v，"-" 表示这个字不标。"""
        table = []
        for line in str(text or "").splitlines():
            parts = line.replace("：", " ").replace(":", " ").split()
            if len(parts) < 2 or len(parts) - 1 != len(parts[0]):
                continue
            # j/q/x 后的 u 实为 ü，IndexTTS 训练用的写法是 jv/qv/xv（que4 写成 qve4 才认得）
            pins = [re.sub(r"^([jqx])u", r"\1v", item.lower().replace("ü", "v")) for item in parts[1:]]
            if all(item == "-" or PINYIN_RE.match(item) for item in pins):
                table.append((parts[0], [item.upper() if item != "-" else "" for item in pins]))
        return sorted(table, key=lambda entry: -len(entry[0]))

    @staticmethod
    def _annotate(text: str, table: list[tuple[str, list[str]]]) -> str:
        """按读音表给配音文字加 <字|PIN4> 标注；文字里已手写的标注原样保留。"""
        result = []
        for part in VOICE_MARK_RE.split(text):
            if VOICE_MARK_RE.fullmatch(part):
                result.append(part)
                continue
            marks = [""] * len(part)
            for word, pins in table:
                start = part.find(word)
                while start >= 0:
                    if not any(marks[start:start + len(word)]):
                        for offset, pin in enumerate(pins):
                            marks[start + offset] = pin or "-"
                    start = part.find(word, start + 1)
            result.append("".join(f"<{char}|{mark}>" if mark and mark != "-" else char for char, mark in zip(part, marks)))
        return "".join(result)

    @staticmethod
    def _recite_parts(spoken: str) -> list[dict]:
        """诗句按吟诵节奏切开：七言 二二三、五言 二三、四言 二二、六言 二二二，组间用顿号让它略停；
        一句（五字以上的分句，或到句号为止的几个短句）单独读，句后停 pause 秒。"""
        groups = {7: [2, 2, 3], 5: [2, 3], 4: [2, 2], 6: [2, 2, 2]}
        parts, line, clause = [], "", []
        for unit in re.findall(r"<[^<>|]+\|[^<>]+>|.", spoken):
            if unit not in "，,。；;！!？?、":
                if unit.strip():
                    clause.append(unit)
                continue
            text, start = [], 0
            for size in groups.get(len(clause), [len(clause)]):
                text.append("".join(clause[start:start + size]))
                start += size
            line += "、".join(text) + ("。" if unit in "。；;！!？?" else "，")
            if unit in "。；;！!？?" or len(clause) >= 5:
                parts.append({"text": line, "pause": 0.55 if unit in "。；;！!？?" else 0.3})
                line = ""
            clause = []
        if clause or line:
            parts.append({"text": line + "".join(clause) + ("。" if clause else ""), "pause": 0})
        return [part for part in parts if part["text"].strip("，。")]

    @staticmethod
    def _voice_text(shot: dict) -> str:
        return str(shot.get("voice") or shot.get("lines") or "").strip()

    @staticmethod
    def _episode_voice_text(episode: dict, index: int) -> str:
        """配音文字；镜头号 RECAP 是片头前的承上解说。"""
        if index == RECAP:
            return str(episode.get("recap") or "").strip()
        shots = episode.get("shots") or []
        return AiStudio._voice_text(shots[index]) if 0 <= index < len(shots) else ""

    def _polyphones(self, texts: list[str]) -> list[list[dict]]:
        if not VOICE_PYTHON.is_file():
            return [[] for _ in texts]
        try:
            result = subprocess.run([str(VOICE_PYTHON), str(VOICE_SCRIPT), "--check"], input=json.dumps({"texts": texts}, ensure_ascii=False),
                                    capture_output=True, text=True, timeout=60)
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return [[] for _ in texts]

    def _shot_take(self, series_id: str, episode: dict, index: int) -> dict | None:
        """这一镜用哪一条：优先「留用」，否则最新完成的那条。"""
        done = [job for job in self.jobs if job.get("series") == series_id and job.get("episode") == episode["id"]
                and not job.get("final") and (job.get("kind") or "video") == "video" and int(job.get("shot") or 0) == index
                and job.get("status") == "done" and job.get("rating") != "reject"
                and Path((job.get("files") or {}).get("video") or "").is_file()]
        kept = [job for job in done if job.get("rating") == "keep"]
        # 按当前配音对过口型的那条最优先：换别的条，嘴就又对不上配音了
        voice = self._current_voice(episode, index)
        synced = [job for job in done if voice and job.get("voice_sync") == voice["id"]]
        return (synced or kept or done or [None])[-1]

    def _current_voice(self, episode: dict, index: int) -> dict | None:
        """这一镜已生成、文字和当前配音文字一致的最新配音。"""
        text = self._episode_voice_text(episode, index)
        done = [item for item in self.voices if item.get("episode") == episode.get("id") and item.get("shot") == index
                and item.get("status") == "done" and item.get("text") == text and Path(item.get("file") or "").is_file()]
        return done[-1] if text and done else None

    @staticmethod
    def _sync_prompt(text: str, kind: str, lead: float) -> str:
        """对口型用的提示词：去掉画外旁白、闭嘴、引号台词这些句子，改成人物自己开口吟诵（不写出字句，H3 会自己念）。"""
        drop = re.compile(r"narrat|voice-?over|recit|speak|speech|lips|mouth|voice|“|”|\"", re.I)
        sentences = [item for item in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if item]
        kept = " ".join(item for item in sentences if not drop.search(item))
        if kind == "detailed_description":
            match = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?), an? ", kept)
            who = match.group(1) if match else "The main character"
            return (f"{kept} From about {lead:g} s {who} recites aloud in a low, slow, heartfelt voice, speaking with natural lip "
                    f"movements synchronized; his face stays clearly visible and apart from speaking he stays nearly still.").strip()
        if kind == "overall_soundscape":
            return f"{kept} His own low reciting voice is the only voice.".strip()
        return kept

    def _lipsync(self, series_id: str, episode: dict, index) -> dict:
        """按这一镜当前的配音重生成视频：配音前面补上字幕起点的静音、锚成整条声轨，H3 让人物的嘴跟着它动。"""
        shots = episode.get("shots") or []
        if not isinstance(index, int) or not 0 <= index < len(shots):
            raise AiStudioError("镜头不存在")
        with self.lock:
            voice = self._current_voice(episode, index)
            take = self._shot_take(series_id, episode, index)
            if not voice:
                raise AiStudioError("这一镜还没有生成好的配音")
            if not take:
                raise AiStudioError("这一镜还没有视频，先生成一条")
            if any(job.get("voice_sync") == voice["id"] and job.get("status") in ACTIVE for job in self.jobs):
                raise AiStudioError("这一镜正在按配音对口型")
        main = [i for i, shot in enumerate(shots) if not shot.get("role")]
        lead = 3.4 if main and index == main[0] else 0.4
        duration = float(voice.get("duration") or 0)
        seconds = lead + duration + 0.6
        if seconds > 15:
            raise AiStudioError(f"配音 {duration:.1f} 秒，加上开头留白超过 15 秒，模型一次放不下；把这一镜的配音文字拆短一些")
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        track = VOICE_DIR / "sync" / f"{job_id}.wav"
        track.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([self.ffmpeg, "-v", "error", "-y", "-i", voice["file"], "-filter_complex",
                                 f"anullsrc=r=48000:cl=stereo,atrim=0:{lead:.3f}[lead];"
                                 f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(voice.get('gain') or 0):.1f}dB[dub];"
                                 f"[lead][dub]concat=n=2:v=0:a=1,apad,atrim=0:{seconds:.3f}[out]",
                                 "-map", "[out]", "-c:a", "pcm_s16le", str(track)], capture_output=True, text=True, timeout=120)
        if result.returncode or not track.is_file():
            raise AiStudioError("准备对口型声轨失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1][:200])
        files = {kind: take["files"][kind] for kind in ("first", "last") if Path((take.get("files") or {}).get(kind) or "").is_file()}
        if (take.get("mode") or "t2v") != "t2v" and "first" not in files:
            raise AiStudioError("原来那条的首帧图找不到了，没法按原画面重做")
        files["soundtrack"] = str(track)
        if take.get("style") == "free":
            sections, free_text = {}, self._sync_prompt(take.get("prompt") or "", "detailed_description", lead)
            prompt = free_text
        else:
            sections = {key: self._sync_prompt(value, key, lead) if key in ("detailed_description", "overall_soundscape") else value
                        for key, value in (take.get("sections") or {}).items()}
            free_text, prompt = "", compose_prompt("structured", sections, "")
        job = {
            **{key: take.get(key) for key in ("series", "group", "episode", "shot", "category", "format", "quality", "mode", "width", "height", "lang", "fast")},
            "id": job_id, "kind": "video", "title": f"{(take.get('title') or '')[:52]} · 对口型", "style": take.get("style") or "structured",
            "sections": sections, "free_text": free_text, "prompt": prompt, "seconds": round(seconds, 2), "frames": video_frames(seconds),
            "seed": random.randint(1, 2**31 - 1), "status": "queued", "created_at": _now(), "lint": {"errors": [], "warns": []},
            "files": files, "progress": None, "error": "", "voice_sync": voice["id"], "voice_lead": lead,
        }
        return {"job": self._enqueue(job)}

    def voice_episode(self, series_id: str, episode_id: str, payload: dict) -> dict:
        """改某一镜的配音文字（text）、查多音字（check）、生成配音（generate；不给 shot 就整集）。"""
        with self.lock:
            series = self._series(series_id)
            episode = next((item for item in series.get("episodes") or [] if item.get("id") == episode_id), None)
            if not episode:
                raise AiStudioError("分集不存在")
            shots = episode.get("shots") or []
            index = payload.get("shot")
            if index is not None and (not isinstance(index, int) or not (0 <= index < len(shots) or index == RECAP)):
                raise AiStudioError("镜头不存在")
            if index == RECAP and not str(episode.get("recap") or "").strip():
                raise AiStudioError("这一集还没写承上解说")
            if "text" in payload and index is not None:
                if index == RECAP:
                    episode["recap"] = str(payload.get("text") or "").strip()[:200]
                else:
                    shots[index]["voice"] = str(payload.get("text") or "").strip()[:400]
                self._save()
            if "narrator" in payload:
                narrator = str(payload.get("narrator") or "")
                if narrator and not any(job.get("id") == narrator and job.get("episode") == episode_id for job in self.jobs):
                    raise AiStudioError("朗读参考必须是本集的一条视频")
                episode["narrator"] = narrator
                self._save()
            if "music" in payload:
                music = str(payload.get("music") or "")
                if music and not any(job.get("id") == music and job.get("episode") == episode_id for job in self.jobs):
                    raise AiStudioError("背景音乐必须取自本集的一条视频")
                episode["music"] = music
                self._save()
        if payload.get("lipsync"):
            return self._lipsync(series_id, episode, index)
        with self.lock:
            # 诗句照本集朗读参考（苏轼本人的声音）读；序章、承上、承上启下这些解说用系列的解说音色
            reciter = episode.get("narrator") or ""
            announcer = series.get("narrator") or reciter
            table = self._pron_table(series.get("pron") or "")
            indices = [index] if index is not None else ([RECAP] if episode.get("recap") else []) + [
                i for i, shot in enumerate(shots) if self._voice_text(shot)]
            texts = {i: self._episode_voice_text(episode, i) for i in indices}
            verses = {i for i in indices if i != RECAP and not shots[i].get("role")}
            voices = {i: reciter if i in verses else announcer for i in indices}
        if payload.get("check"):
            found = self._polyphones([self._annotate(texts[i], table) for i in indices])
            return {"polyphones": {str(i): items for i, items in zip(indices, found)}}
        if not payload.get("generate"):
            return {}
        missing = self._voice_ready()
        if missing:
            raise AiStudioError(missing)
        created = []
        for i in indices:
            if not texts[i]:
                raise AiStudioError(f"第 {i + 1} 镜没有配音文字")
            with self.lock:
                if any(item.get("episode") == episode_id and item.get("shot") == i and item.get("status") in VOICE_ACTIVE for item in self.voices):
                    continue
            take = self._shot_take(series_id, episode, i) if i != RECAP else None
            if not take and not voices[i]:
                voices[i] = series.get("narrator") or ""
            if not take and not voices[i]:
                raise AiStudioError("承上解说没有原片可取音色，先在系列里设解说音色" if i == RECAP
                                    else f"第 {i + 1} 镜还没有视频，取不到原声音色；可以先在系列里指定解说音色")
            spoken = self._annotate(texts[i], table)
            record = {"id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4], "series": series_id, "episode": episode_id,
                      "shot": i, "text": texts[i], "spoken": spoken, "take": (take or {}).get("id", ""), "narrator": voices[i],
                      "status": "queued", "error": "", "duration": 0, "gain": 0.0, "created_at": _now(),
                      "polyphones": self._polyphones([spoken])[0], "parts": self._recite_parts(spoken) if i in verses else []}
            with self.lock:
                self.voices.append(record)
                self._save()
            created.append(record["id"])
        self.voice_wake.set()
        return {"created": created}

    def delete_voice(self, voice_id: str) -> None:
        with self.lock:
            record = next((item for item in self.voices if item.get("id") == voice_id), None)
            if not record:
                raise AiStudioError("配音不存在")
            if record.get("status") == "running":
                raise AiStudioError("这条配音正在生成")
            self.voices.remove(record)
            self._save()
        target = Path(record.get("file") or "/nonexistent").resolve()
        if VOICE_DIR.resolve() in target.parents and target.is_file():
            target.unlink()

    def _stems(self, take_id: str) -> dict:
        """一条视频的原声分成人声 / 伴奏（环境声 + 配乐），按任务 id 缓存，同一条只分离一次。"""
        folder = VOICE_DIR / "stems"
        stems = {"vocals": folder / f"{take_id}_vocals.flac", "inst": folder / f"{take_id}_inst.flac"}
        if all(path.is_file() for path in stems.values()):
            return stems
        with self.lock:
            video = (self._job(take_id).get("files") or {}).get("video")
        if not video or not Path(video).is_file():
            raise RuntimeError("原视频不存在，无法分离人声")
        if not SEPARATOR.is_file():
            raise RuntimeError("没有找到人声分离工具 audio-separator")
        folder.mkdir(parents=True, exist_ok=True)
        with self.stem_lock, tempfile.TemporaryDirectory(dir=folder) as temporary:
            source = Path(temporary) / "source.wav"
            # 分离模型一次吃 8 秒，短于 8 秒的片段会报错：先补静音到 10 秒，分完再裁回原长
            length = self._probe_duration(video)[0]
            subprocess.run([self.ffmpeg, "-v", "error", "-y", "-i", video, "-vn", "-ac", "2", "-ar", "44100", "-af", "apad=whole_dur=10",
                            str(source)], capture_output=True, timeout=120)
            if not source.is_file():
                raise RuntimeError("这条视频没有声音")
            result = subprocess.run([str(SEPARATOR), str(source), "--model_filename", SEPARATOR_MODEL, "--output_dir", temporary,
                                     "--model_file_dir", str(SEPARATOR_MODEL_DIR)], capture_output=True, text=True, timeout=900,
                                    env=self._tool_env(NO_PROXY="*"))
            outputs = {path.name: path for path in Path(temporary).glob("*.flac")}
            vocals = next((path for name, path in outputs.items() if "(Vocals)" in name), None)
            inst = next((path for name, path in outputs.items() if "(Instrumental)" in name), None)
            if not vocals or not inst:
                raise RuntimeError("人声分离失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1][:200])
            for produced, key in ((vocals, "vocals"), (inst, "inst")):
                subprocess.run([self.ffmpeg, "-v", "error", "-y", "-i", str(produced), "-t", f"{length:.3f}", str(stems[key])],
                               capture_output=True, timeout=120)
                if not stems[key].is_file():
                    raise RuntimeError("人声分离结果保存失败")
        return stems

    def _music_source(self, take_ids: list) -> str:
        """没指定配乐来源时挑一镜：伴奏够长（≥9 秒）里最响的；有的镜头伴奏几乎只剩分离残留，循环起来断断续续。"""
        best, best_score = "", None
        for take_id in dict.fromkeys(item for item in take_ids if item):
            try:
                inst = self._stems(take_id)["inst"]
            except Exception:
                continue
            length, level = self._probe_duration(str(inst))[0], self._mean_volume(inst)
            if level is None or length < 3:
                continue
            score = (length >= 9, level)
            if best_score is None or score > best_score:
                best, best_score = take_id, score
        if not best:
            raise RuntimeError("这一集没有可用的配乐，先在某一镜点「用这镜配乐做整集背景音乐」")
        return best

    def _music_bed(self, take_id: str, total: float, out: Path) -> None:
        """一镜原片分离出的伴奏循环铺满 total 秒：接缝处交叉淡化，首尾淡入淡出，响度拉到统一的垫乐水平。"""
        inst = self._stems(take_id)["inst"]
        length = self._probe_duration(str(inst))[0]
        if length < 3:
            raise RuntimeError("这一镜的配乐太短，换一镜做背景音乐")
        fade = min(2.5, length / 4)
        copies = max(1, math.ceil((total - fade) / (length - fade)))
        command = [self.ffmpeg, "-v", "error", "-y"]
        for _ in range(copies):
            command += ["-i", str(inst)]
        graph, last = [], "0:a"
        for index in range(1, copies):
            graph.append(f"[{last}][{index}:a]acrossfade=d={fade:.2f}:c1=qsin:c2=qsin[x{index}]")
            last = f"x{index}"
        level = self._mean_volume(inst)
        gain = max(-12.0, min(12.0, -27.0 - level)) if level is not None else 0.0
        graph.append(f"[{last}]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{total:.3f},volume={gain:.1f}dB,"
                     f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0.0, total - 3):.2f}:d=3[bed]")
        result = subprocess.run(command + ["-filter_complex", ";".join(graph), "-map", "[bed]", "-c:a", "pcm_s16le", str(out)],
                                capture_output=True, text=True, timeout=300)
        if result.returncode or not out.is_file():
            raise RuntimeError("生成整集配乐失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1][:200])

    def _tool_env(self, **extra) -> dict:
        """systemd / launchd 下 PATH 很短；分离和配音工具内部要直接调 ffmpeg。"""
        folder = str(Path(self.ffmpeg).parent)
        return {**os.environ, "PATH": f"{folder}:{os.environ.get('PATH', '/usr/bin:/bin')}", **extra}

    def _mean_volume(self, path: Path) -> float | None:
        result = subprocess.run([self.ffmpeg, "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                                capture_output=True, text=True, timeout=120)
        match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
        return float(match.group(1)) if match else None

    def _voice_ref(self, take_id: str) -> Path:
        """参考音色：原片人声去掉开头静音，取 12 秒。"""
        target = VOICE_DIR / "refs" / f"{take_id}.wav"
        if target.is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        vocals = self._stems(take_id)["vocals"]
        subprocess.run([self.ffmpeg, "-v", "error", "-y", "-i", str(vocals), "-af",
                        "silenceremove=start_periods=1:start_threshold=-40dB,atrim=0:12", "-ac", "1", "-ar", "24000", str(target)],
                       capture_output=True, timeout=120)
        if not target.is_file():
            raise RuntimeError("提取参考音色失败")
        return target

    def _voice_loop(self) -> None:
        while True:
            try:
                self._voice_tick()
            except Exception as exc:  # 后台线程不能因为一次异常退出
                print(f"[ai-studio-voice] {exc!r}")
            self.voice_wake.wait(60)
            self.voice_wake.clear()

    def _voice_fail(self, record: dict, error: str) -> None:
        with self.lock:
            record.update(status="failed", error=error[:300], finished_at=_now())
            self._save()

    def _voice_tick(self) -> None:
        with self.lock:
            queued = [item for item in self.voices if item.get("status") == "queued"]
        if not queued:
            return
        missing = self._voice_ready()
        if missing:
            for record in queued:
                self._voice_fail(record, missing)
            return
        items, records = [], {}
        for record in queued:
            with self.lock:
                record.update(status="running", started_at=_now())
                self._save()
            try:
                ref = self._voice_ref(record.get("narrator") or record["take"])
                if record.get("take"):
                    self._stems(record["take"])
            except (OSError, RuntimeError, AiStudioError, subprocess.SubprocessError) as exc:
                self._voice_fail(record, f"准备音色失败：{exc}")
                continue
            out = VOICE_DIR / record["series"] / f"{record['id']}.wav"
            items.append({"id": record["id"], "text": record["spoken"], "parts": record.get("parts") or [], "ref": str(ref), "out": str(out)})
            records[record["id"]] = (record, out)
        if not items:
            return
        work = VOICE_DIR / ".work"
        work.mkdir(parents=True, exist_ok=True)
        spec = work / f"{items[0]['id']}.json"
        spec.write_text(json.dumps({"model_dir": str(VOICE_MODEL_DIR), "items": items}, ensure_ascii=False), encoding="utf-8")
        log = work / f"{items[0]['id']}.log"
        try:
            with log.open("w", encoding="utf-8") as errors:
                process = subprocess.Popen([str(VOICE_PYTHON), str(VOICE_SCRIPT), str(spec)], cwd=str(VOICE_REPO), stdout=subprocess.PIPE,
                                           stderr=errors, text=True, env=self._tool_env(HF_HUB_OFFLINE="1", PYTORCH_ENABLE_MPS_FALLBACK="1"))
                for line in process.stdout:
                    try:
                        result = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(result, dict) or result.get("id") not in records:
                        continue
                    record, out = records.pop(result["id"])
                    if not result.get("ok") or not out.is_file():
                        self._voice_fail(record, f"配音生成失败：{result.get('error') or '没有输出文件'}")
                        continue
                    # 新配音的响度对齐朗读参考（没有参考就对齐这一镜原片人声），整集一样响
                    gain = 0.0
                    level_from = record.get("narrator") or record.get("take")
                    if level_from:
                        before, after = self._mean_volume(self._stems(level_from)["vocals"]), self._mean_volume(out)
                        if before is not None and after is not None:
                            gain = round(max(-12.0, min(12.0, before - after)), 1)
                    with self.lock:
                        record.update(status="done", file=str(out), duration=result.get("duration") or 0, gain=gain, finished_at=_now())
                        self._save()
                process.wait()
        finally:
            spec.unlink(missing_ok=True)
        tail = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()][-1:] if log.is_file() else []
        for record, _ in records.values():
            self._voice_fail(record, "配音进程意外退出：" + (tail[0][:200] if tail else "未知错误"))

    # ---------- 分集合成 ----------
    def _shot_takes(self, series_id: str, episode: dict) -> list[dict]:
        """每个镜头选一条：优先「留用」，否则最新完成的那条。"""
        takes = []
        for index in range(len(episode.get("shots") or [])):
            take = self._shot_take(series_id, episode, index)
            if not take:
                raise AiStudioError(f"第 {index + 1} 镜还没有完成的视频")
            takes.append(take)
        return takes

    def compose_episode(self, series_id: str, episode_id: str) -> dict:
        with self.lock:
            series = self._series(series_id)
            episode = next((item for item in series.get("episodes") or [] if item.get("id") == episode_id), None)
            if not episode:
                raise AiStudioError("分集不存在")
            if any(job.get("final") and job.get("episode") == episode_id and job.get("status") in ACTIVE for job in self.jobs):
                raise AiStudioError("这一集正在合成")
            takes = self._shot_takes(series_id, episode)
            fmt = takes[0].get("format") or "portrait"
            width, height = {"portrait": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}.get(fmt, (1080, 1920))
            job = {
                "id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4], "kind": "video", "final": True,
                "title": f"{episode['title']} · 成片"[:60], "series": series_id, "group": episode.get("group") or "", "episode": episode_id,
                "shot": 0, "category": "free", "format": fmt, "quality": "final", "mode": "compose", "style": "free", "sections": {},
                "free_text": "", "prompt": "合成：" + " + ".join(f"第 {i + 1} 镜 {take['id']}" for i, take in enumerate(takes)),
                "seconds": 0, "seed": 0, "width": width, "height": height, "status": "finishing", "created_at": _now(),
                "started_at_ts": time.time(), "lint": {"errors": [], "warns": []}, "files": {}, "progress": None, "error": "",
            }
            self.jobs.append(job)
            self._save()
        stages = []
        for group in series.get("groups") or []:
            name = re.sub(r"^[①-⑳]\s*", "", group.get("name") or "").split("（")[0].replace(" · ", "").strip()
            year = re.search(r"\d{4}", group.get("name") or "")
            stages.append({"year": year.group(0) if year else "", "name": name[:6]})
        guard = ""
        for index, shot in enumerate(episode.get("shots") or []):
            if shot.get("role") == "intro" and shot.get("image_prompt"):
                cards = [item for item in self.jobs if item.get("episode") == episode_id and item.get("kind") == "image"
                         and int(item.get("shot") or 0) == index and item.get("status") == "done" and item.get("rating") != "reject"]
                card = next((item for item in reversed(cards) if item.get("rating") == "keep"), cards[-1] if cards else None)
                files = (card or {}).get("files") or {}
                guard = next((files[key] for key in ("source", "image", "preview") if files.get(key) and Path(files[key]).is_file()), "")
                break
        atlas = None
        if episode.get("route") and MAP_DATA_DIR.is_dir():
            episodes = series.get("episodes") or []
            position = next(index for index, item in enumerate(episodes) if item.get("id") == episode_id)
            following = episodes[position + 1] if position + 1 < len(episodes) else None
            previous = episodes[position - 1] if position else None
            atlas = {"title": series.get("name") or "", "life": series.get("route") or [],
                     "previous_date": (previous or {}).get("date") or "",
                     "next": {"route": following["route"], "date": following.get("date") or ""} if following and following.get("route") else None}
        # 已生成、且文字和这一镜当前配音文字一致的配音，合成时替换原片人声
        dubs = {}
        with self.lock:
            for index in [RECAP, *range(len(episode.get("shots") or []))]:
                voice = self._current_voice(episode, index)
                if voice:
                    dubs[index] = {"file": voice["file"], "duration": float(voice.get("duration") or 0), "gain": float(voice.get("gain") or 0)}
        threading.Thread(target=self._compose, args=(job, {**episode, "seal": series.get("seal") or ""}, [dict(take) for take in takes],
                                                     stages, guard, atlas, dubs),
                         daemon=True).start()
        return self._public(job)

    def _probe_duration(self, path: str) -> tuple[float, bool]:
        ffprobe = str(Path(self.ffmpeg).with_name("ffprobe"))
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
                                capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout or "{}")
        duration = float((data.get("format") or {}).get("duration") or 0)
        return duration, any(item.get("codec_type") == "audio" for item in data.get("streams") or [])

    def _map_hold(self, video: str) -> float:
        """片头地图停留多久：和首帧比，画面开始大变（地图化开成实景）的时刻，限制在 2–3.5 秒。"""
        size = (24, 42)
        result = subprocess.run([self.ffmpeg, "-v", "error", "-t", "5", "-i", video, "-vf", f"fps=8,scale={size[0]}:{size[1]},format=gray",
                                 "-f", "rawvideo", "-"], capture_output=True, timeout=60)
        pixels = size[0] * size[1]
        frames = [result.stdout[index:index + pixels] for index in range(0, len(result.stdout) - pixels + 1, pixels)]
        for index, frame in enumerate(frames[1:], start=1):
            if sum(abs(a - b) for a, b in zip(frame, frames[0])) / pixels > 30:
                return min(3.5, max(2.0, index / 8))
        return 2.0

    def _map_clips(self, work: Path, size: tuple[int, int], atlas: dict, episode: dict, intro: list[dict], first_main: dict,
                   bridges: list[dict], still: Path, recap: list[dict] | None = None) -> dict:
        """用经纬度画行迹动画：序章整段、正片首镜开头的地图、承上启下。返回 片段 id → mp4 路径。"""
        route, date = episode["route"], episode.get("date") or ""
        here = len(route) - 1
        clips = []
        life, reached = atlas.get("life") or [], 0
        for index, clip in enumerate(intro):
            target = int(clip["shot"].get("route_to") or 0)
            if life and target and index < len(intro) - 1:
                segment = {"route": life, "from": reached, "to": min(target, len(life) - 1), "date_from": ""}
                reached = segment["to"]
            else:
                segment = {"route": route, "from": here, "to": here, "date_from": "", "date_to": date, "date_at": 0.6,
                           "fade": {"route": life, "progress": reached, "window": [0.1, 0.55]} if life and reached else None}
            clips.append({"id": id(clip), "out": str(work / f"map_intro{index}.mp4"), "segments": [{**segment, "duration": clip["duration"]}]})
        for clip in recap or []:
            # 承上：从上一站走到本站，日期从上一集换到本集，停在本集开场的地图上
            clips.append({"id": id(clip), "out": str(work / "map_recap.mp4"), "segments": [{
                "route": route, "from": max(0, here - 1), "to": here, "move": [0.15, 0.7], "date_from": atlas.get("previous_date") or date,
                "date_to": date, "date_at": 0.5, "duration": clip["duration"]}]})
        first_main["map_hold"] = self._map_hold(first_main["video"]) * first_main.get("stretch", 1.0)
        clips.append({"id": id(first_main), "out": str(work / "map_open.mp4"),
                      "segments": [{"route": route, "from": here, "to": here, "date_from": date, "duration": first_main["map_hold"] + 0.6}]})
        following = atlas.get("next")
        if following and bridges:
            clip = bridges[0]
            clips.append({"id": id(clip), "out": str(work / "map_bridge.mp4"), "segments": [{
                "route": following["route"], "from": min(here, len(following["route"]) - 1), "to": len(following["route"]) - 1,
                "move": [0.3, 0.85], "date_from": date, "date_to": following["date"], "background": str(still), "reveal": [0.6, 1.8],
                "duration": clip["duration"]}]})
        spec = {"width": size[0], "height": size[1], "fps": 24, "ffmpeg": self.ffmpeg, "life": life,
                "title": atlas.get("title") or "", "data_dir": str(MAP_DATA_DIR), "clips": clips}
        (work / "map.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([CAPTION_PYTHON, str(MAP_SCRIPT), str(work / "map.json")], capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise RuntimeError("行迹地图生成失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1])
        return {item["id"]: item["out"] for item in clips}

    def _compose(self, job: dict, episode: dict, takes: list[dict], stages: list[dict] | None = None, guard: str = "",
                 atlas: dict | None = None, dubs: dict | None = None) -> None:
        """片段顺序：序章 → 正片各镜 → 全诗片尾（定格虚化）→ 承上启下（落在下一集片头图上）。
        分集带经纬度路线时，序章、首镜开头的地图和承上启下的画面都换成程序画的行迹动画，声音仍用原片。"""
        work = LIBRARY_DIR / ".compose" / job["id"]
        try:
            work.mkdir(parents=True, exist_ok=True)
            width, height = job["width"], job["height"]
            shots = episode.get("shots") or []
            clips = []
            for index, take in enumerate(takes):
                shot = shots[index] if index < len(shots) else {}
                duration, has_audio = self._probe_duration(take["files"]["video"])
                clips.append({"video": take["files"]["video"], "duration": duration, "audio": has_audio, "shot": shot,
                              "role": shot.get("role") or "", "take": take["id"], "dub": (dubs or {}).get(index)})
            intro = [clip for clip in clips if clip["role"] == "intro"]
            main = [clip for clip in clips if clip["role"] == ""]
            bridges = [clip for clip in clips if clip["role"] == "bridge"]
            if not main:
                raise RuntimeError("没有正片镜头")
            # 承上解说：正片前一段，画面是本集开场的地图（没有路线就定格首镜第一帧），只有解说声
            recap = []
            if (dubs or {}).get(RECAP):
                dub = dubs[RECAP]
                recap = [{"recap": True, "video": main[0]["video"], "duration": round(dub["duration"] + 1.4, 3), "audio": False,
                          "shot": {"lines": episode.get("recap") or ""}, "role": "recap", "take": main[0]["take"], "dub": dub}]
            # 吟诵配音比镜头长：画面放慢（最多 1.6 倍）让它读完，不压快语速
            for clip in main:
                if not clip.get("dub"):
                    continue
                if clip is main[0]:
                    # 首镜开头 3.4 秒是地图化开，放慢后这段也跟着变长，诗句照样等地图化开再出
                    need = (clip["dub"]["duration"] + 0.6) / max(1.0, clip["duration"] - 3.4)
                    if need > 1:
                        clip["stretch"] = min(1.6, need)
                else:
                    need = (0.4 + clip["dub"]["duration"] + 0.6) / clip["duration"]
                    if need > 1:
                        clip["stretch"] = min(1.6, need)
                if clip.get("stretch"):
                    clip["duration"] *= clip["stretch"]
            open_lead = 3.4 * main[0].get("stretch", 1.0)
            for clip in bridges:
                if clip.get("dub") and clip["dub"]["duration"] + 1.4 > clip["duration"]:
                    clip["stretch"] = min(1.6, (clip["dub"]["duration"] + 1.4) / clip["duration"])
                    clip["duration"] *= clip["stretch"]
            end = COMPOSE_END_SECONDS
            card = {"card": True, "duration": float(end), "role": "card"}
            segments = intro + recap + main + [card] + bridges
            cursor = 0.0
            for segment in segments:
                segment["start"] = cursor
                cursor += segment["duration"]
            total = cursor
            main_start, main_end = main[0]["start"], card["start"]

            title = episode.get("poem_title") or episode.get("title")
            header_line = " · ".join(item for item in (episode.get("author"), episode.get("place"), episode.get("date"), episode.get("age")) if item)
            items, windows, subtitles = [], [], []

            def add(item, begin, finish):
                item["path"] = str(work / f"o{len(items)}.png")
                items.append(item)
                windows.append((begin, finish))

            def speech(clip, lead, kind):
                """字幕时段：有新配音就跟着配音走（诗句逐字出完正好读完），否则按原片的经验时段。"""
                begin, end = clip["start"] + lead, clip["start"] + clip["duration"] - 0.15
                entry = {"text": clip["shot"]["lines"], "begin": begin, "end": end, "kind": kind}
                if clip.get("dub"):
                    clip["lead"] = lead
                    # 配音比镜头剩下的时间长一点时稍微加快（最多 1.3 倍），保证读完
                    dub = clip["dub"]
                    dub["tempo"] = min(1.3, max(1.0, dub["duration"] / max(0.5, clip["duration"] - lead - 0.25)))
                    spoken = dub["duration"] / dub["tempo"]
                    entry["end"] = min(end, begin + spoken + (1.6 if kind == "verse" else 0.6))
                    entry["reveal"] = spoken
                sentences = re.findall(r"[^。！？]+[。！？]?", entry["text"]) if kind == "prose" else []
                chunks = []
                for sentence in sentences:
                    if chunks and len(chunks[-1]) + len(sentence) <= 34:
                        chunks[-1] += sentence
                    else:
                        chunks.append(sentence)
                if len(chunks) < 2:
                    subtitles.append(entry)
                    return
                # 解说长：按句分成几屏，按字数分配时长，每屏最多两行
                span = entry.get("reveal") or (entry["end"] - begin)
                total, cursor = sum(len(chunk) for chunk in chunks), begin
                for position, chunk in enumerate(chunks):
                    finish = entry["end"] if position == len(chunks) - 1 else cursor + span * len(chunk) / total
                    subtitles.append({"text": chunk, "begin": cursor, "end": finish, "kind": kind})
                    cursor = finish

            still = work / "end.png"
            subprocess.run([self.ffmpeg, "-v", "error", "-y", "-sseof", "-0.08", "-i", main[-1]["video"], "-frames:v", "1", "-update", "1", "-vf",
                            f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}", str(still)],
                           capture_output=True, timeout=60)
            if not still.is_file():
                raise RuntimeError("生成片尾背景失败")
            maps = self._map_clips(work, (width, height), atlas, episode, intro, main[0], bridges, still, recap) if atlas else {}
            if intro and guard and not maps:
                last_intro = intro[-1]
                plain = [clip for clip in intro if clip["shot"].get("mode") != "flf"]
                add({"kind": "guard", "source": guard, "bands": [[0, 0.115]]}, 0, last_intro["start"] + last_intro["duration"] * 0.4)
                if plain:
                    add({"kind": "guard", "source": guard, "bands": [[0.915, 1]]}, 0, plain[-1]["start"] + plain[-1]["duration"])
            for clip in intro:
                shot = clip["shot"]
                if stages:
                    # 行迹地图下方留给时间线；序章最后一镜后半段地图下沿要出第一站的时间，时间线提前收
                    finish = clip["start"] + clip["duration"] * (0.5 if maps and clip is intro[-1] else 1) - 0.1
                    add({"kind": "timeline", "stages": stages, "active": shot.get("stages") or [], "caption": shot.get("caption_title") or "",
                         "y": 0.765 if maps else 0.665, "tone": "ink" if maps else ""}, clip["start"] + 0.3, finish)
                if shot.get("lines"):
                    speech(clip, 0.4, "prose")
            for clip in recap:
                speech(clip, 0.5, "prose")
            add({"kind": "header", "title": title, "line": header_line}, main_start + 3.0 * main[0].get("stretch", 1.0), main_end)
            for index, clip in enumerate(main):
                if clip["shot"].get("lines"):
                    speech(clip, open_lead if index == 0 else 0.4, "verse")
            add({"kind": "poem", "title": title, "line": header_line, "poem": episode.get("poem") or "", "seal": episode.get("seal") or ""},
                main_end + 0.7, main_end + end - 0.7)
            for clip in bridges:
                shot = clip["shot"]
                if shot.get("caption_title"):
                    on_map = id(clip) in maps
                    add({"kind": "header", "raw": True, "y": 0.715 if on_map else 0.135, "tone": "ink" if on_map else "",
                         "title": shot["caption_title"], "line": shot.get("caption_line") or ""},
                        clip["start"] + (1.8 if on_map else 0.5), clip["start"] + clip["duration"] - 1.2)
                if shot.get("lines"):
                    speech(clip, 0.4, "prose")
            for item in subtitles:
                entry = {"kind": item["kind"], "text": item["text"]}
                if item["kind"] == "verse":
                    # 诗句逐字渐显：字幕脚本另出一段透明 mov
                    entry["animate"] = {"duration": round(item["end"] - item["begin"], 3), "ffmpeg": self.ffmpeg,
                                        "out": str(work / f"verse{len(items)}.mov")}
                    if item.get("reveal"):
                        entry["animate"]["reveal"] = round(item["reveal"], 3)
                add(entry, item["begin"], item["end"])
            (work / "spec.json").write_text(json.dumps({"width": width, "height": height, "items": items}, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run([CAPTION_PYTHON, str(CAPTION_SCRIPT), str(work / "spec.json")], capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError("字幕图生成失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1])
            outputs = json.loads(result.stdout.strip().splitlines()[-1])
            # 叠加层：整张透明图渐显渐隐；诗句是自带逐字渐显的透明 mov，按位置贴上
            layers = []
            for item, (begin, finish) in zip(items, windows):
                for part in outputs.get(item["path"]) or [{"path": item["path"]}]:
                    layers.append({"path": part["path"], "begin": begin, "finish": finish, "video": part.get("video", False),
                                   "x": part.get("x", 0), "y": part.get("y", 0), "fade": 0.0 if item["kind"] == "guard" else 0.5})

            command, graph, late = [self.ffmpeg, "-v", "error", "-y"], [], []
            fit = f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height},setsar=1,fps=24,format=yuv420p"
            for index, segment in enumerate(segments):
                duration = segment["duration"]
                if segment.get("card"):
                    # 定格在最后一帧：0.7 秒虚化压暗 → 整首诗 → 0.7 秒还原清晰，接承上启下（它从同一帧起）
                    command += ["-loop", "1", "-t", str(end), "-i", str(still)]
                    ramp = f"clip(min(T/0.7,({end}-T)/0.7),0,1)"
                    graph.append(f"[{index}:v]setsar=1,fps=24,format=yuv420p,split[s{index}][b{index}]")
                    graph.append(f"[b{index}]gblur=sigma=24,eq=brightness=-0.3:saturation=0.6[g{index}]")
                    graph.append(f"[s{index}][g{index}]blend=all_expr='A*(1-{ramp})+B*{ramp}',format=yuv420p[v{index}]")
                    graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{end}[a{index}]")
                    continue
                command += ["-i", segment["video"]]
                drawn = maps.get(id(segment))
                if drawn:
                    # 地图动画作为额外输入排在所有字幕图之后
                    late.append(drawn)
                    extra = len(segments) + len(layers) + len(late) - 1
                if drawn and segment is main[0]:
                    # 首镜开头盖一段程序画的地图，到原片地图化开处淡出
                    slow = f"setpts={segment['stretch']:.4f}*PTS," if segment.get("stretch") else ""
                    graph.append(f"[{index}:v]{slow}{fit},trim=duration={duration:.3f}[r{index}]")
                    graph.append(f"[{extra}:v]setsar=1,fps=24,format=yuva420p,fade=t=out:st={segment['map_hold']:.2f}:d=0.6:alpha=1[m{index}]")
                    graph.append(f"[r{index}][m{index}]overlay=0:0:eof_action=pass,format=yuv420p[v{index}]")
                elif drawn:
                    graph.append(f"[{extra}:v]{fit},tpad=stop_mode=clone:stop_duration=2,trim=duration={duration:.3f},setpts=PTS-STARTPTS[v{index}]")
                elif segment.get("recap"):
                    graph.append(f"[{index}:v]{fit},trim=end_frame=1,tpad=stop_mode=clone:stop_duration={duration:.3f},"
                                 f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v{index}]")
                elif segment.get("stretch"):
                    graph.append(f"[{index}:v]setpts={segment['stretch']:.4f}*PTS,{fit},trim=duration={duration:.3f}[v{index}]")
                else:
                    graph.append(f"[{index}:v]{fit}[v{index}]")
                # 配音轨：新配音按字幕起点放；没配音的镜头用原片分离出的人声。配乐不跟镜头走，整集另铺一条
                dub = segment.get("dub")
                pad = f"apad,atrim=0:{duration:.3f}"
                if dub:
                    lead = segment.get("lead", 3.4 if segment is main[0] else 0.4)
                    late.append(dub["file"])
                    voice = len(segments) + len(layers) + len(late) - 1
                    tempo = f"atempo={dub['tempo']:.3f}," if dub.get("tempo", 1.0) > 1.001 else ""
                    # 前面接一段真静音再读；adelay 的延迟经过 concat 会丢，配音会提前到镜头开头
                    graph.append(f"[{voice}:a]aresample=48000,aformat=channel_layouts=stereo,{tempo}volume={dub['gain']:.1f}dB[dub{index}]")
                    graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{lead:.3f}[lead{index}]")
                    graph.append(f"[lead{index}][dub{index}]concat=n=2:v=0:a=1,{pad}[a{index}]")
                elif segment["audio"]:
                    late.append(str(self._stems(segment["take"])["vocals"]))
                    voice = len(segments) + len(layers) + len(late) - 1
                    graph.append(f"[{voice}:a]aresample=48000,aformat=channel_layouts=stereo,{pad}[a{index}]")
                else:
                    graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{duration:.3f}[a{index}]")
            graph.append("".join(f"[v{i}][a{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=1[base][voices]")
            # 整集一条连续配乐：取一镜原片分离出的伴奏，循环交叉淡化铺满全片；有人声时自动压低一点
            music = work / "music.wav"
            self._music_bed(episode.get("music") or self._music_source([episode.get("narrator")] + [clip["take"] for clip in main]), total, music)
            late.append(str(music))
            bed = len(segments) + len(layers) + len(late) - 1
            graph.append("[voices]asplit=3[vmix][vkey][vtrack]")
            graph.append(f"[{bed}:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[mbed][mtrack]")
            graph.append("[mbed][vkey]sidechaincompress=threshold=0.03:ratio=3:attack=40:release=600[mduck]")
            graph.append("[mduck][vmix]amix=inputs=2:duration=first:normalize=0[aout]")
            last = "base"
            for index, layer in enumerate(layers):
                begin, length = layer["begin"], max(0.1, layer["finish"] - layer["begin"])
                chain = ["format=rgba"]
                if layer["video"]:
                    command += ["-i", layer["path"]]
                else:
                    command += ["-loop", "1", "-framerate", "24", "-t", f"{length:.3f}", "-i", layer["path"]]
                    if layer["fade"]:
                        fade_out = min(0.4, length / 3)
                        chain += [f"fade=t=in:st=0:d={min(layer['fade'], length / 2):.2f}:alpha=1",
                                  f"fade=t=out:st={length - fade_out:.2f}:d={fade_out:.2f}:alpha=1"]
                chain.append(f"setpts=PTS-STARTPTS+{begin:.3f}/TB")
                graph.append(f"[{len(segments) + index}:v]{','.join(chain)}[l{index}]")
                label = f"o{index}"
                graph.append(f"[{last}][l{index}]overlay={layer['x']}:{layer['y']}:eof_action=pass:repeatlast=0[{label}]")
                last = label
            for path in late:
                command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"] if not path else ["-i", path]
            target = self._library_folder(job) / f"{job['id'][:8]}_{_safe_title(job['title'])}_{job['id'][-4:]}.mp4"
            draft = work / "draft.mp4"
            command += ["-filter_complex", ";".join(graph), "-map", f"[{last}]", "-map", "[aout]",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", str(draft),
                        "-map", "[vtrack]", "-c:a", "pcm_s16le", str(work / "voice.wav"),
                        "-map", "[mtrack]", "-c:a", "pcm_s16le", str(work / "music.out.wav")]
            result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
            if result.returncode or not draft.is_file():
                raise RuntimeError("ffmpeg 合成失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1][:300])
            srt = target.with_suffix(".srt")
            stamp = lambda value: f"{int(value // 3600):02d}:{int(value % 3600 // 60):02d}:{int(value % 60):02d},{int(round(value % 1 * 1000)) % 1000:03d}"
            srt.write_text("".join(f"{index}\n{stamp(item['begin'])} --> {stamp(item['end'])}\n{item['text']}\n\n"
                                   for index, item in enumerate(sorted(subtitles, key=lambda entry: entry["begin"]), start=1)), encoding="utf-8")
            # 画面里已烧录字幕；再封一条可开关的软字幕轨，播放器和剪辑软件都能读
            result = subprocess.run([self.ffmpeg, "-v", "error", "-y", "-i", str(draft), "-i", str(srt), "-map", "0", "-map", "1",
                                     "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=chi",
                                     "-movflags", "+faststart", str(target)], capture_output=True, text=True, timeout=300)
            if result.returncode or not target.is_file():
                shutil.move(str(draft), str(target))
            thumb = LIBRARY_DIR / ".thumbs" / f"{job['id']}.jpg"
            subprocess.run([self.ffmpeg, "-v", "error", "-y", "-ss", str(main_start + min(5.0, (main_end - main_start) / 2)), "-i", str(target),
                            "-frames:v", "1", "-vf", "scale='min(480,iw)':-2", str(thumb)], capture_output=True, timeout=60)
            files = {"video": str(target), "srt": str(srt)}
            # 配音轨和配乐轨另存，和成片等长，可直接拖进剪辑软件重新混
            for kind, name, label in (("voice_track", "voice.wav", "配音轨"), ("music_track", "music.out.wav", "配乐轨")):
                if (work / name).is_file():
                    track = target.with_name(f"{target.stem}_{label}.wav")
                    shutil.move(str(work / name), track)
                    files[kind] = str(track)
            if thumb.is_file():
                files["thumb"] = str(thumb)
            with self.lock:
                job["files"] = files
                job["seconds"] = round(total, 2)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as exc:
            return self._finish(job, error=f"合成失败：{exc}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self._finish(job)

    # ---------- 后台：提交、跟踪、整理 ----------
    def _loop(self) -> None:
        while True:
            try:
                self._tick()
            except Exception as exc:  # 后台线程不能因为一次异常退出
                print(f"[ai-studio] {exc!r}")
            with self.lock:
                busy = any(job.get("status") in ACTIVE for job in self.jobs)
            self.wake.wait(3 if busy else 60)
            self.wake.clear()

    def _tick(self) -> None:
        with self.lock:
            active = [job for job in self.jobs if job.get("status") in ACTIVE]
        if not active:
            return
        if not _comfy_up():
            if any(job["status"] == "queued" for job in active) and self.ensure_comfy:
                try:
                    self.ensure_comfy()
                except Exception as exc:
                    self._fail_queued(f"无法启动 ComfyUI：{exc}")
            for job in active:
                if job["status"] in {"submitted", "running"} and time.time() - job.get("seen_ts", time.time()) > 600:
                    self._finish(job, error="ComfyUI 已停止，任务中断")
            return
        queue = _comfy("/queue")
        running_ids = {item[1] for item in queue.get("queue_running") or [] if len(item) > 1}
        pending_ids = {item[1] for item in queue.get("queue_pending") or [] if len(item) > 1}
        for job in active:
            if job["status"] == "queued":
                self._submit(job)
                continue
            if job["status"] == "finishing":
                continue
            prompt_id = job.get("comfy_prompt_id")
            history = _comfy(f"/history/{prompt_id}").get(prompt_id)
            if history:
                self._collect(job, history)
                continue
            with self.lock:
                job["seen_ts"] = time.time()
                if prompt_id in running_ids:
                    if job["status"] != "running":
                        job.update(status="running", started_at=_now(), started_at_ts=time.time())
                    job["progress"] = self._progress(job.get("log_offset", 0))
                elif prompt_id in pending_ids:
                    job["status"] = "submitted"
                elif time.time() - job.get("submitted_ts", time.time()) > 30:
                    self._finish(job, error="ComfyUI 队列里找不到这个任务")
                self._save()

    def _fail_queued(self, message: str) -> None:
        with self.lock:
            for job in self.jobs:
                if job.get("status") == "queued":
                    job.update(status="failed", error=message, finished_at=_now())
            self._save()

    def _submit(self, job: dict) -> None:
        names = {}
        for kind in ("first", "last", "soundtrack") + tuple(f"ref{i}" for i in range(1, MAX_REFS + 1)):
            source = (job.get("files") or {}).get(kind)
            if source:
                name = f"aistudio_{job['id']}_{kind}{Path(source).suffix}"
                (COMFY_DIR / "input").mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, COMFY_DIR / "input" / name)
                names[kind] = name
        if job.get("kind") == "image":
            graph = build_image_graph(job, [names[f"ref{i}"] for i in range(1, MAX_REFS + 1) if f"ref{i}" in names])
        else:
            graph = build_graph(job, names.get("first", ""), names.get("last", ""), names.get("soundtrack", ""))
        log_offset = _log_size()
        try:
            result = _comfy("/prompt", {"prompt": graph, "client_id": "ai-studio"}, timeout=30)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(detail)
                detail = parsed.get("error", {}).get("message", "") + " " + json.dumps(parsed.get("node_errors") or {}, ensure_ascii=False)[:600]
            except ValueError:
                pass
            return self._finish(job, error=f"ComfyUI 拒绝了任务：{detail.strip()[:800]}")
        with self.lock:
            job.update(status="submitted", comfy_prompt_id=result.get("prompt_id"), submitted_at=_now(),
                       submitted_ts=time.time(), seen_ts=time.time(), log_offset=log_offset)
            self._save()

    def _progress(self, offset: int) -> dict | None:
        try:
            with COMFY_LOG_PATH.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                if offset > size:
                    offset = 0
                handle.seek(max(offset, size - 6000))
                text = handle.read().decode("utf-8", "replace").replace("\r", "\n")
        except OSError:
            return None
        matches = STEP_RE.findall(text)
        if not matches:
            return None
        step, total = matches[-1]
        return {"step": int(step), "total": int(total)}

    def _collect(self, job: dict, history: dict) -> None:
        status = history.get("status") or {}
        if status.get("status_str") == "error" or not status.get("completed", True):
            message = ""
            for name, info in status.get("messages") or []:
                if name == "execution_error":
                    message = f"{info.get('node_type', '')}: {info.get('exception_message', '')}".strip()
                elif name == "execution_interrupted" and not message:
                    message = "已中断"
            if job.get("status") == "cancelled":
                return
            return self._finish(job, error=message or "生成失败")
        image_job = job.get("kind") == "image"
        output = None
        for item in (history.get("outputs") or {}).get("8" if image_job else "92", {}).get("images") or []:
            candidate = COMFY_DIR / "output" / item.get("subfolder", "") / item.get("filename", "")
            if candidate.is_file():
                output = candidate
        if output is None:
            return self._finish(job, error="生成结束但没找到图片文件" if image_job else "生成结束但没找到视频文件")
        with self.lock:
            job["status"] = "finishing"
            self._save()
        organize = self._organize_image if image_job else self._organize
        threading.Thread(target=organize, args=(job, output), daemon=True).start()

    def _library_folder(self, job: dict) -> Path:
        """系列作品放到 系列/<系列名>/<分组名>/，其余按 类别/画幅。"""
        fmt = FORMATS[job["format"]]["label"].replace(" ", "_").replace(":", "x")
        with self.lock:
            series = next((item for item in self.series if item.get("id") == job.get("series")), None)
        if series:
            group = next((item for item in series.get("groups") or [] if item.get("id") == job.get("group")), None)
            folder = LIBRARY_DIR / "系列" / _safe_title(series["name"]) / (_safe_title(group["name"]) if group else "未分组")
        else:
            category = next(item["label"] for item in CATEGORIES if item["id"] == job["category"])
            folder = LIBRARY_DIR / category / fmt
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _organize_image(self, job: dict, output: Path) -> None:
        try:
            folder = self._library_folder(job)
            target = folder / f"{job['id'][:8]}_{_safe_title(job['title'])}_s{job['seed']}_{job['id'][-4:]}{output.suffix}"
            shutil.copy2(output, target)
            prompt_file = folder / f"{target.stem}.prompt.txt"
            prompt_file.write_text(job["prompt"] + "\n", encoding="utf-8")
            files = {"image": str(target), "prompt_txt": str(prompt_file)}
            thumbs = LIBRARY_DIR / ".thumbs"
            thumbs.mkdir(parents=True, exist_ok=True)
            # thumb / preview 限制长边；source 把短边限制在 2048（H3-Image 参考图编码的上限），供「用作参考图」回传。
            long_edge = "scale='if(gt(iw,ih),min({0},iw),-2)':'if(gt(iw,ih),-2,min({0},ih))'"
            short_edge = "scale='if(gt(iw,ih),-2,min(2048,iw))':'if(gt(iw,ih),min(2048,ih),-2)'"
            for kind, scale, quality in (("thumb", long_edge.format(480), "4"), ("preview", long_edge.format(1600), "3"),
                                         ("source", short_edge, "2")):
                derived = thumbs / f"{job['id']}_{kind}.jpg"
                subprocess.run([self.ffmpeg, "-v", "error", "-y", "-i", str(target), "-frames:v", "1", "-q:v", quality,
                                "-vf", scale, str(derived)], capture_output=True, timeout=120)
                if derived.is_file():
                    files[kind] = str(derived)
        except OSError as exc:
            return self._finish(job, error=f"整理图片失败：{exc}")
        with self.lock:
            job["files"] = {**(job.get("files") or {}), **files}
        self._finish(job)

    def _organize(self, job: dict, output: Path) -> None:
        folder = self._library_folder(job)
        target = folder / f"{job['id'][:8]}_{_safe_title(job['title'])}_s{job['seed']}_{job['id'][-4:]}.mp4"
        shutil.copy2(output, target)
        prompt_file = folder / f"{target.stem}.prompt.txt"
        prompt_file.write_text(job["prompt"] + "\n", encoding="utf-8")
        files = {"video": str(target), "prompt_txt": str(prompt_file)}
        thumbs = LIBRARY_DIR / ".thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)
        thumb = thumbs / f"{job['id']}.jpg"
        subprocess.run([self.ffmpeg, "-v", "error", "-y", "-ss", str(min(1.0, job["seconds"] / 2)), "-i", str(target),
                        "-frames:v", "1", "-vf", "scale='min(480,iw)':-2", str(thumb)], capture_output=True, timeout=60)
        if thumb.is_file():
            files["thumb"] = str(thumb)
        sheet_prefix = thumbs / f"{job['id']}_sheet"
        script = STUDIO_REPO / "tools" / "contact_sheet.sh"
        if script.is_file():
            subprocess.run(["/bin/bash", str(script), str(target), str(sheet_prefix)], capture_output=True, timeout=120,
                           env={**os.environ, "FFMPEG": self.ffmpeg})
            sheet = Path(f"{sheet_prefix}_1.jpg")
            if sheet.is_file():
                files["sheet"] = str(sheet)
        qc = self._quality_check(target, job)
        if Path(f"{target}.qa.json").is_file():
            files["qa"] = f"{target}.qa.json"
        with self.lock:
            job["files"] = {**(job.get("files") or {}), **files}
            job["qc"] = qc
        self._finish(job)

    def _quality_check(self, video: Path, job: dict) -> dict | None:
        script = STUDIO_REPO / "tools" / "take_gate.py"
        if not (TAKE_GATE_PYTHON.is_file() and script.is_file()):
            return None
        command = [str(TAKE_GATE_PYTHON), str(script), str(video), "--ffmpeg", self.ffmpeg]
        if YUNET_MODEL.is_file():
            command += ["--yunet", str(YUNET_MODEL)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=600, cwd=str(STUDIO_REPO))
        except (OSError, subprocess.SubprocessError) as exc:
            return {"verdict": "ERROR", "lines": [str(exc)]}
        lines = [line for line in result.stdout.splitlines() if line.strip() and not line.startswith("objc[")]
        if not lines:
            lines = ["ERROR"] + [line for line in result.stderr.splitlines() if line.strip() and not line.startswith("objc[")][-3:]
        verdict = lines[0].split()[0] if lines else "ERROR"
        return {"verdict": verdict, "lines": lines[:8]}

    def _finish(self, job: dict, error: str = "") -> None:
        with self.lock:
            if job.get("status") == "cancelled":
                return
            job.update(status="failed" if error else "done", error=error, finished_at=_now(), progress=None)
            if job.get("started_at_ts"):
                job["render_secs"] = round(time.time() - job["started_at_ts"])
            self._save()
