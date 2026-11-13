"""字幕、片尾诗文、行迹地图共用的字体。

宋体：AI_STUDIO_FONT_SONG / AI_STUDIO_FONT_SONG_BOLD 指定，否则用仓库 assets/fonts 里的思源宋体（scripts/install.sh 下载），
再退到系统里的 Noto Serif CJK 或 macOS 宋体。隶书：AI_STUDIO_FONT_LISHU 指定，否则用 macOS 的隶变，都没有就用粗宋体代替。
"""
import os
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
MAC_SONG = Path("/System/Library/Fonts/Supplemental/Songti.ttc")


def _pick(env, candidates):
    if os.environ.get(env):
        return (os.environ[env], 0)
    for path, index in candidates:
        if Path(path).is_file():
            return (str(path), index)
    raise SystemExit(f"找不到中文字体：请运行 scripts/install.sh 下载，或用 {env} 指定字体文件")


def _cjk(weight):
    # Noto Serif CJK 的 ttc 里第 3 个（index 2）是简体中文
    return [(f"/usr/share/fonts/google-noto-serif-cjk-fonts/NotoSerifCJK-{weight}.ttc", 2),
            (f"/usr/share/fonts/opentype/noto/NotoSerifCJK-{weight}.ttc", 2),
            (f"/usr/share/fonts/noto-cjk/NotoSerifCJK-{weight}.ttc", 2)]


SONG_REGULAR = _pick("AI_STUDIO_FONT_SONG", [(FONT_DIR / "NotoSerifSC-Regular.otf", 0), *_cjk("Regular"), (MAC_SONG, 4)])
SONG_BOLD = _pick("AI_STUDIO_FONT_SONG_BOLD", [(FONT_DIR / "NotoSerifSC-Bold.otf", 0), *_cjk("Bold"), (MAC_SONG, 1)])
# macOS 的「隶变」是系统按需下载的字体：优先用装到用户字体目录的完整版
LISHU = os.environ.get("AI_STUDIO_FONT_LISHU") or next((str(path) for path in [
    Path.home() / "Library/Fonts/Libian.ttc",
    *sorted(Path("/System/Library/AssetsV2").glob("com_apple_MobileAsset_Font*/*/AssetData/Libian.ttc")),
] if path.is_file() and path.stat().st_size > 1_000_000), "")


def song(size, bold=False):
    path, index = SONG_BOLD if bold else SONG_REGULAR
    return ImageFont.truetype(path, size, index=index)


def lishu(size):
    return ImageFont.truetype(LISHU, size) if LISHU and Path(LISHU).is_file() else song(size, bold=True)
