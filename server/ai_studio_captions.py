"""AI Studio 成片字幕图：片头诗名、竖排隶书诗句、旁白字幕、时间线、片尾整首诗。

由 ai_studio.py 用带 Pillow 的 Python 调用：
    python ai_studio_captions.py spec.json
每张图都是与成片同尺寸的透明 PNG，由 ffmpeg overlay 叠加；诗句逐字渐显时改出一段只含诗句区域的透明 mov。
"""

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import ai_studio_fonts

SONG_BOLD, SONG_REGULAR = True, False
INK = (250, 244, 228, 255)
GOLD = (226, 196, 132, 255)
WHITE = (255, 255, 255, 255)
DIM = (226, 214, 190, 150)
SEAL = (178, 44, 36, 235)
VERMILION = (214, 72, 46, 255)
PUNCT = "，。；？！、：,.;?!:“”‘’《》"


def song(size, bold=SONG_REGULAR):
    return ai_studio_fonts.song(size, bold)


def lishu(size):
    return ai_studio_fonts.lishu(size)


def text_width(draw, text, face):
    left, _, right, _ = draw.textbbox((0, 0), text, font=face)
    return right - left


def shadowed(size, paint, blur=6, strength=1.6):
    """先画文字层，再做柔和投影，亮背景上也看得清。"""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    paint(ImageDraw.Draw(layer))
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda value: min(255, int(value * strength))))
    result = Image.new("RGBA", size, (0, 0, 0, 0))
    result.alpha_composite(shadow, (2, 3))
    result.alpha_composite(layer)
    return result


def soft_patch(size, box, alpha=110, blur=60):
    """文字背后一块边缘很虚的暗影，不是硬底条。"""
    patch = Image.new("L", size, 0)
    ImageDraw.Draw(patch).rounded_rectangle(box, radius=40, fill=alpha)
    patch = patch.filter(ImageFilter.GaussianBlur(blur))
    result = Image.new("RGBA", size, (0, 0, 0, 0))
    result.putalpha(patch)
    return result


def clauses(text):
    """按标点断成小句，去掉标点（竖排不放标点）。"""
    parts, current = [], ""
    for char in str(text or "").replace("\n", ""):
        if char in PUNCT:
            if current.strip():
                parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def columns(text, limit):
    """小句合并成竖列：一列不超过 limit 字，同列两小句之间留半格。"""
    result, current = [], []
    for part in clauses(text):
        length = sum(len(item) for item in current) + len(current) * 0.5 + len(part)
        if current and length > limit:
            result.append(current)
            current = []
        current.append(part)
    if current:
        result.append(current)
    return result


def column_height(column, cell):
    return sum(len(part) for part in column) * cell * 1.06 + (len(column) - 1) * cell * 0.5


def draw_column(draw, column, x, y, cell, face, fill):
    for index, part in enumerate(column):
        for char in part:
            left, top, right, bottom = draw.textbbox((0, 0), char, font=face)
            draw.text((x - (right - left) / 2 - left, y + (cell - (bottom - top)) / 2 - top), char, font=face, fill=fill)
            y += cell * 1.06
        if index < len(column) - 1:
            y += cell * 0.5


def sentences(text):
    """旁白散文：一句（到句号/问号/叹号/分号）一行。"""
    rows, current = [], ""
    for char in str(text or "").replace("\n", ""):
        current += char
        if char in "。；？！":
            rows.append(current)
            current = ""
    if current.strip():
        rows.append(current)
    return [row.strip() for row in rows if row.strip()]


def fit(draw, rows, max_width, size, face_of, minimum=24):
    while size > minimum and max(text_width(draw, row, face_of(size)) for row in rows) > max_width:
        size -= 2
    return size


def header(width, height, item):
    """顶部居中：隶书诗名 + 宋体「作者 · 地点 · 时间」。"""
    scale = width / 1080
    title = item.get("title") or ""
    if title and not item.get("raw"):
        title = f"《{title}》"
    line = item.get("line") or ""
    top = int(height * float(item.get("y") or (0.062 if height > width else 0.05)))
    # tone=ink：写在浅色绢本地图上，用墨色字、朱砂小字，不垫暗影
    ink = item.get("tone") == "ink"
    title_fill, line_fill, rule_fill = ((66, 46, 32, 255), (150, 40, 28, 255), (150, 40, 28, 150)) if ink else (WHITE, WHITE, (255, 255, 255, 150))

    def paint(draw, parts=("title", "line")):
        size = fit(draw, [title], width * 0.86, int(84 * scale), lishu)
        face = lishu(size)
        if "title" in parts:
            draw.text(((width - text_width(draw, title, face)) / 2, top), title, font=face, fill=title_fill)
        if not line or "line" not in parts:
            return
        weight = SONG_REGULAR if ink else SONG_BOLD
        rows = [line]
        if text_width(draw, line, song(int(32 * scale), weight)) > width * 0.86 and " · " in line:
            pieces = line.split(" · ")
            half = (len(pieces) + 1) // 2
            rows = [" · ".join(pieces[:half]), " · ".join(pieces[half:])]
        small_size = fit(draw, rows, width * 0.86, int(34 * scale), lambda value: song(value, weight))
        small = song(small_size, weight)
        y = top + size + int(30 * scale)
        for index, row in enumerate(rows):
            draw.text(((width - text_width(draw, row, small)) / 2, y + index * int(small_size * 1.45)), row, font=small, fill=line_fill)
        y += len(rows) * int(small_size * 1.45) + int(14 * scale)
        rule = int(120 * scale)
        draw.line([(width / 2 - rule, y), (width / 2 + rule, y)], fill=rule_fill, width=max(1, int(2 * scale)))

    if ink:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        paint(ImageDraw.Draw(canvas))
        return canvas
    # 和诗句一样一层贴字的投影；小字的投影收得更紧，免得糊进笔画
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(shadowed((width, height), lambda draw: paint(draw, ("title",)), blur=7, strength=1.8))
    canvas.alpha_composite(shadowed((width, height), lambda draw: paint(draw, ("line",)), blur=4, strength=1.8))
    return canvas


def verse(width, height, item):
    """诗句：隶书竖排，从右往左，靠画面右侧上部，像题在画上的款。"""
    scale = width / 1080
    cols = columns(item.get("text"), 8)
    cell = int(92 * scale)
    gap = cell * 1.5
    top = height * (0.215 if height > width else 0.16)
    while cell > 36 and (max(column_height(column, cell) for column in cols) > height * 0.56 or len(cols) * cell * 1.5 > width * 0.6):
        cell -= 2
        gap = cell * 1.5
    right = width - int(80 * scale) - cell / 2
    block_w = (len(cols) - 1) * gap + cell
    block_h = max(column_height(column, cell) for column in cols)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    face = lishu(cell)
    if item.get("animate"):
        return verse_clip(width, height, item, canvas, cols, cell, gap, top, right, face)

    def paint(draw):
        for index, column in enumerate(cols):
            draw_column(draw, column, right - index * gap, top, cell, face, INK)

    canvas.alpha_composite(shadowed((width, height), paint, blur=7, strength=1.8))
    return canvas


def verse_clip(width, height, item, patch, cols, cell, gap, top, right, face):
    """诗句逐字渐显：只渲染诗句所在的一块区域，输出带透明通道的 mov，返回它在画面里的位置。
    item.animate = {duration, out, ffmpeg, times?}；times 是每个字出现的秒数，缺省按朗读时段均分，小句之间停半拍。"""
    spec = item["animate"]
    duration, fps = float(spec["duration"]), 24
    scale = width / 1080
    pad = int(40 * scale)
    block_w = (len(cols) - 1) * gap + cell
    block_h = max(column_height(column, cell) for column in cols)
    x0 = max(0, int(right + cell / 2 - block_w - pad - 30 * scale))
    y0 = max(0, int(top - pad - 30 * scale))
    x1 = min(width, int(right + cell / 2 + pad + 30 * scale))
    y1 = min(height, int(top + block_h + pad + 30 * scale))
    x0, y0 = x0 - x0 % 2, y0 - y0 % 2
    x1, y1 = x1 - (x1 - x0) % 2, y1 - (y1 - y0) % 2
    box_w, box_h = x1 - x0, y1 - y0
    glyphs, steps = [], 0.0
    for index, column in enumerate(cols):
        x, y = right - index * gap, top
        for number, part in enumerate(column):
            for char in part:
                glyph = shadowed((width, height), lambda draw, c=char, gx=x, gy=y: draw_column(draw, [c], gx, gy, cell, face, INK),
                                 blur=7, strength=1.8).crop((x0, y0, x1, y1))
                bbox = glyph.getbbox()
                if bbox:
                    glyphs.append((glyph.crop(bbox), bbox[:2], steps))
                steps += 1
                y += cell * 1.06
            if number < len(column) - 1:
                y += cell * 0.5
            steps += 0.6
        steps += 0.4
    times = spec.get("times") or []
    # 有配音时 reveal = 配音时长，最后一个字随最后一个音出来
    reveal = min(float(spec.get("reveal") or duration - 1.6), duration - 0.6)
    reveal = max(0.5, reveal)
    total = max(1.0, steps)
    fade, tail = 0.45, 0.45
    starts = [float(times[i]) if i < len(times) else reveal * at / total for i, (_, _, at) in enumerate(glyphs)]
    command = [spec.get("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{box_w}x{box_h}",
               "-r", str(fps), "-i", "-", "-c:v", "qtrle", spec["out"]]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    frames = max(1, round(duration * fps))
    try:
        for index in range(frames):
            t = index / fps
            out_alpha = max(0.0, min(1.0, (duration - t) / tail))
            frame = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
            for (glyph, offset, _), start in zip(glyphs, starts):
                alpha = max(0.0, min(1.0, (t - start) / fade)) * out_alpha
                if alpha > 0:
                    frame.alpha_composite(fade_layer(glyph, alpha), offset)
            process.stdin.write(frame.tobytes())
    finally:
        process.stdin.close()
    if process.wait():
        raise RuntimeError("诗句动画编码失败")
    return {"video": spec["out"], "x": x0, "y": y0}


def fade_layer(image, alpha):
    if alpha >= 1:
        return image
    layer = image.copy()
    layer.putalpha(image.getchannel("A").point(lambda value: int(value * alpha)))
    return layer


def fill(draw, text, face, limit):
    """整段连着写：一行写满再换行；句末标点不放到行首。"""
    lines, current = [], ""
    for char in text:
        if current and char not in PUNCT and text_width(draw, current + char, face) > limit:
            lines.append(current)
            current = ""
        current += char
    if current:
        lines.append(current)
    return lines


def prose(width, height, item):
    """旁白：宋体横排，画面下方，最多两行。"""
    scale = width / 1080
    rows = sentences(item.get("text"))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    probe = ImageDraw.Draw(canvas)
    # 最多两行：一句一行放得下就照旧；否则整段连写、写满一行再换行，两行还放不下才缩小字号
    size, limit = int(46 * scale), width * 0.86
    if len(rows) > 2 or any(text_width(probe, row, song(size, SONG_BOLD)) > limit for row in rows):
        text = "".join(rows)
        while True:
            rows = fill(probe, text, song(size, SONG_BOLD), limit)
            if len(rows) <= 2 or size <= int(24 * scale):
                break
            size -= 2
    gap = int(size * 0.6)
    block = len(rows) * size + (len(rows) - 1) * gap
    bottom = height - int((250 if height > width else 100) * scale)
    top = bottom - block
    def paint(draw):
        face = song(size, SONG_BOLD)
        for index, row in enumerate(rows):
            draw.text(((width - text_width(draw, row, face)) / 2, top + index * (size + gap)), row, font=face, fill=INK)

    # 不垫底色，和顶部标题一样靠两层投影托住
    canvas.alpha_composite(shadowed((width, height), paint, blur=12, strength=1.4))
    canvas.alpha_composite(shadowed((width, height), paint, blur=3, strength=2.6))
    return canvas


def timeline(width, height, item):
    """序章时间线：五个阶段一字排开，当前阶段朱砂点亮；上方一行隶书小标题。"""
    scale = width / 1080
    stages = item.get("stages") or []
    active = set(item.get("active") or [])
    y = height * float(item.get("y") or 0.665)
    left, right = width * 0.1, width * 0.9
    step = (right - left) / max(1, len(stages) - 1)
    # tone=ink：写在浅色绢本地图下方，墨色字、朱砂点，排得更紧凑
    ink = item.get("tone") == "ink"
    text_fill, dim, gold, caption_gap = ((66, 46, 32, 255), (120, 100, 78, 200), (150, 40, 28, 255), 140) if ink else (INK, DIM, GOLD, 165)

    def paint(draw):
        caption = item.get("caption") or ""
        if caption:
            face = lishu(fit(draw, [caption], width * 0.84, int(58 * scale), lishu))
            draw.text(((width - text_width(draw, caption, face)) / 2, y - caption_gap * scale), caption, font=face, fill=text_fill)
        draw.line([(left, y), (right, y)], fill=dim, width=max(1, int(3 * scale)))
        for index, stage in enumerate(stages):
            x = left + index * step
            lit = index in active
            radius = (15 if lit else 9) * scale
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=VERMILION if lit else dim)
            year = song(int(28 * scale), SONG_BOLD)
            draw.text((x - text_width(draw, stage["year"], year) / 2, y - 56 * scale), stage["year"], font=year, fill=gold if lit else dim)
            name = lishu(int((36 if lit else 30) * scale))
            draw.text((x - text_width(draw, stage["name"], name) / 2, y + 24 * scale), stage["name"], font=name, fill=text_fill if lit else dim)

    if ink:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        paint(ImageDraw.Draw(canvas))
        return canvas
    canvas = soft_patch((width, height), [left - 70 * scale, y - 190 * scale, right + 70 * scale, y + 110 * scale], alpha=120, blur=50)
    canvas.alpha_composite(shadowed((width, height), paint, blur=5))
    return canvas


def poem(width, height, item):
    """片尾整首诗：隶书竖排居中，右起诗题，左收作者与时地，钤一方小印。"""
    scale = width / 1080
    title = item.get("title") or ""
    line = item.get("line") or ""
    cols = columns(item.get("poem"), 9)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cell = int(66 * scale)
    while cell > 26:
        gap = cell * 1.55
        total_w = (len(cols) + 1) * gap + cell * 1.9
        tallest = max([column_height(column, cell) for column in cols] + [len(title) * cell * 1.3 * 1.06])
        if total_w <= width * 0.88 and tallest <= height * 0.6:
            break
        cell -= 2
    gap = cell * 1.55
    title_cell = int(cell * 1.3)
    small_cell = max(20, int(cell * 0.56))
    title_parts = [part for part in title.replace("·", " ").split() if part]
    total_w = title_cell + gap * 0.4 + (len(cols)) * gap + small_cell * 1.6
    right = (width + total_w) / 2 - title_cell / 2
    poem_h = max(column_height(column, cell) for column in cols)
    top = (height - poem_h) / 2 - height * 0.02

    def paint(draw):
        draw_column(draw, title_parts, right, top - cell * 0.4, title_cell, lishu(title_cell), INK)
        x = right - title_cell / 2 - gap * 0.4 - cell / 2
        face = lishu(cell)
        for column in cols:
            draw_column(draw, column, x, top, cell, face, INK)
            x -= gap
        info = [part for part in line.split(" · ") if part]
        draw_column(draw, info, x + gap - cell / 2 - small_cell * 1.0, top + poem_h * 0.35, small_cell, song(small_cell), GOLD)

    canvas.alpha_composite(shadowed((width, height), paint))
    seal = int(54 * scale)
    draw = ImageDraw.Draw(canvas)
    sx = (width - total_w) / 2 - seal * 0.2
    sy = top + poem_h * 0.35 + len(line.replace(" · ", "")) * small_cell * 1.06 + small_cell * 1.5
    sy = min(sy, height - seal * 3)
    draw.rectangle([sx, sy, sx + seal, sy + seal], fill=SEAL)
    mark = lishu(int(seal * 0.66))
    char = item.get("seal") or "坡"
    left, top_, right_, bottom = draw.textbbox((0, 0), char, font=mark)
    draw.text((sx + (seal - (right_ - left)) / 2 - left, sy + (seal - (bottom - top_)) / 2 - top_), char, font=mark, fill=(250, 236, 220, 255))
    return canvas


def guard(width, height, item):
    """把底图的标题带（和底部年份带）原样盖回去：视频模型有时会把旁白写进地图标题。"""
    source = Image.open(item["source"]).convert("RGBA")
    ratio = max(width / source.width, height / source.height)
    source = source.resize((round(source.width * ratio), round(source.height * ratio)), Image.LANCZOS)
    left, top = (source.width - width) // 2, (source.height - height) // 2
    source = source.crop((left, top, left + width, top + height))
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for start, end in item.get("bands") or []:
        draw.rectangle([0, int(height * start), width, int(height * end)], fill=255)
    source.putalpha(mask.filter(ImageFilter.GaussianBlur(height * 0.012)))
    return source


RENDER = {"header": header, "verse": verse, "subtitle": prose, "prose": prose, "timeline": timeline, "poem": poem, "guard": guard}


def main(spec_path):
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    width, height = int(spec["width"]), int(spec["height"])
    outputs = {}
    for item in spec["items"]:
        result = RENDER[item["kind"]](width, height, item)
        if isinstance(result, dict):
            outputs[item["path"]] = [{"path": result["video"], "at": 0, "x": result["x"], "y": result["y"], "video": True}]
        else:
            result.save(item["path"])
            outputs[item["path"]] = [{"path": item["path"], "at": 0}]
    # 标准输出给合成端：每个条目实际生成了哪些图
    print(json.dumps(outputs, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
