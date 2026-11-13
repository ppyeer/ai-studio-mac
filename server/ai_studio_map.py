"""AI Studio 路线地图动画：按真实经纬度在仿古绢本地图上画行迹，输出无声 mp4。

由 ai_studio.py 用带 Pillow / numpy 的 Python 调用：
    python ai_studio_map.py spec.json
spec = {width, height, fps, ffmpeg, title, data_dir,
        clips: [{out | still, segments: [{duration, route: [{name, lon, lat, anchor}], from, to, move: [起, 止],
                 date_from, date_to, date_at, fade: {route, progress, window}, background, reveal: [起, 止]}]}]}
progress 以「段」计：2.0 表示前两段路线已画完、停在第 3 个站点上。
海岸线、河流、湖泊来自 Natural Earth 1:50m（公有领域），放在 data_dir。
"""

import json
import math
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import ai_studio_fonts

# 地图范围：川西到东海、海南到燕山
LON0, LON1, LAT0, LAT1 = 101.0, 123.5, 17.8, 41.5
SILK = (214, 194, 152)
LAND = (228, 209, 166)
SEA = (183, 192, 170)
INK = (66, 46, 32)
RIVER = (74, 98, 104)
ROUTE_DARK = (138, 30, 22)
ROUTE = (196, 50, 34)
MOUNTAINS = [  # 经度, 纬度, 座数, 散布(度), 大小
    (101.0, 29.0, 7, 1.6, 1.1), (99.5, 26.5, 5, 1.2, 1.0), (107.6, 33.9, 7, 1.4, 1.0), (110.0, 31.6, 5, 1.1, 0.9),
    (113.4, 37.0, 5, 1.0, 0.9), (112.4, 39.2, 4, 1.0, 0.8), (117.4, 36.3, 2, 0.4, 0.7), (115.6, 31.2, 3, 0.6, 0.8),
    (117.6, 27.4, 5, 1.0, 0.9), (112.6, 25.4, 6, 1.4, 0.9), (108.8, 27.6, 4, 1.0, 0.8), (104.5, 24.5, 4, 1.2, 0.8),
    (102.0, 33.8, 4, 1.2, 0.9), (119.5, 29.0, 3, 0.7, 0.7), (109.7, 19.0, 1, 0.2, 0.6),
]
SEAS = [("东海", 122.4, 27.2), ("南海", 114.8, 19.4), ("黄海", 122.6, 34.6)]


def lishu(size):
    return ai_studio_fonts.lishu(size)


class Layout:
    def __init__(self, width, height):
        self.width, self.height = width, height
        scale = width / 1080
        self.scale = scale
        portrait = height > width
        margin = 60 * scale
        box_w = width - 2 * margin
        kx_per_ky = math.cos(math.radians((LAT0 + LAT1) / 2))
        avail_h = height * (0.62 if portrait else 0.8)
        ky = min(box_w / ((LON1 - LON0) * kx_per_ky), avail_h / (LAT1 - LAT0))
        self.kx, self.ky = ky * kx_per_ky, ky
        map_w, map_h = (LON1 - LON0) * self.kx, (LAT1 - LAT0) * self.ky
        self.left = (width - map_w) / 2
        self.top = 140 * scale if portrait else (height - map_h) / 2 + 30 * scale
        self.box = (self.left, self.top, self.left + map_w, self.top + map_h)
        self.title_y = 46 * scale if portrait else 20 * scale
        self.date_y = self.box[3] + 22 * scale

    def xy(self, lon, lat, factor=1):
        return ((self.left + (lon - LON0) * self.kx) * factor, (self.top + (LAT1 - lat) * self.ky) * factor)


def silk_texture(width, height, seed=7):
    rng = np.random.default_rng(seed)
    field = np.zeros((height, width), np.float32)
    for cell, amp in ((160, 9.0), (48, 5.0), (12, 3.0)):
        small = rng.normal(0, 1, (height // cell + 2, width // cell + 2)).astype(np.float32)
        img = Image.fromarray(((small - small.min()) / (np.ptp(small) + 1e-6) * 255).astype(np.uint8)).resize((width, height), Image.BICUBIC)
        field += (np.asarray(img, np.float32) / 255 - 0.5) * 2 * amp
    fibers = rng.normal(0, 1, (height, max(1, width // 40))).astype(np.float32)
    fiber_img = Image.fromarray(((fibers - fibers.min()) / (np.ptp(fibers) + 1e-6) * 255).astype(np.uint8)).resize((width, height), Image.BICUBIC)
    field += (np.asarray(fiber_img, np.float32) / 255 - 0.5) * 6
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dist = np.sqrt(((xx - width / 2) / (width / 2)) ** 2 + ((yy - height / 2) / (height / 2)) ** 2)
    vignette = 1 - 0.22 * np.clip(dist - 0.55, 0, 1) ** 1.4
    return field, vignette


def tint(color, field, vignette):
    arr = np.empty(field.shape + (3,), np.float32)
    for channel in range(3):
        arr[..., channel] = (color[channel] + field) * vignette
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def rings(geometry):
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [polygon[0] for polygon in geometry["coordinates"]]
    return []


def lines_of(geometry):
    if geometry["type"] == "LineString":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiLineString":
        return geometry["coordinates"]
    return []


def near(points, pad=3):
    return any(LON0 - pad < x < LON1 + pad and LAT0 - pad < y < LAT1 + pad for x, y, *_ in points)


def mountain(draw, x, y, size, rng):
    w, h = size * rng.uniform(0.9, 1.3), size * rng.uniform(0.8, 1.2)
    peak = (x + rng.uniform(-0.15, 0.15) * w, y - h)
    shape = [(x - w, y), (x - w * 0.45, y - h * 0.55), peak, (x + w * 0.4, y - h * 0.5), (x + w, y)]
    draw.polygon(shape, fill=(118, 148, 124, 150))
    draw.line([(x - w, y), (x - w * 0.45, y - h * 0.55), peak], fill=(70, 84, 66, 200), width=max(2, int(size / 9)))
    draw.line([peak, (x + w * 0.4, y - h * 0.5), (x + w, y)], fill=(70, 84, 66, 120), width=max(1, int(size / 14)))
    for k in range(2):
        sx = x - w * (0.55 - 0.25 * k)
        draw.line([(sx, y - h * 0.18), (sx + w * 0.22, y - h * (0.48 - 0.1 * k))], fill=(70, 84, 66, 110), width=max(1, int(size / 16)))


def base_map(layout, title, data_dir):
    width, height = layout.width, layout.height
    factor = 2
    big = (width * factor, height * factor)
    field, vignette = silk_texture(width, height)
    canvas = tint(SILK, field, vignette).convert("RGBA")
    map_img = Image.new("RGBA", big, SEA + (255,))
    draw = ImageDraw.Draw(map_img, "RGBA")
    data_dir = Path(data_dir)
    land = json.loads((data_dir / "ne_50m_land.geojson").read_text())
    land_mask = Image.new("L", big, 0)
    mask_draw = ImageDraw.Draw(land_mask)
    outlines = []
    for feature in land["features"]:
        for ring in rings(feature["geometry"]):
            if near(ring):
                points = [layout.xy(lon, lat, factor) for lon, lat, *_ in ring]
                mask_draw.polygon(points, fill=255)
                outlines.append(points)
    sea_tex = tint(SEA, field, vignette).resize(big, Image.BILINEAR).convert("RGBA")
    land_tex = tint(LAND, field, vignette).resize(big, Image.BILINEAR).convert("RGBA")
    map_img = Image.composite(land_tex, sea_tex, land_mask)
    draw = ImageDraw.Draw(map_img, "RGBA")
    # 海面水纹：近岸几道细浪线
    coast_glow = land_mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(18 * factor))
    wave = Image.new("RGBA", big, (88, 112, 112, 0))
    wave.putalpha(Image.eval(coast_glow, lambda v: int(v * 0.32)))
    sea_only = Image.eval(land_mask, lambda v: 255 - v)
    map_img.paste(wave, (0, 0), Image.fromarray(np.minimum(np.asarray(wave.getchannel("A")), np.asarray(sea_only))))
    draw = ImageDraw.Draw(map_img, "RGBA")
    rng = random.Random(11)
    for _ in range(140):
        lon, lat = rng.uniform(LON0, LON1), rng.uniform(LAT0, LAT1)
        x, y = layout.xy(lon, lat, factor)
        if land_mask.getpixel((int(min(big[0] - 1, max(0, x))), int(min(big[1] - 1, max(0, y))))) == 0:
            span = 14 * factor * layout.scale
            draw.arc([x - span, y - span * 0.45, x + span, y + span * 0.45], 200, 340, fill=(80, 104, 104, 90), width=max(1, int(1.6 * factor)))
    for points in outlines:
        draw.line(points + points[:1], fill=INK + (215,), width=int(2.4 * factor * layout.scale), joint="curve")
    lakes = json.loads((data_dir / "ne_50m_lakes.geojson").read_text())
    for feature in lakes["features"]:
        for ring in rings(feature["geometry"]):
            if near(ring, 0):
                draw.polygon([layout.xy(lon, lat, factor) for lon, lat, *_ in ring], fill=(150, 172, 166, 255), outline=RIVER + (200,))
    rivers = json.loads((data_dir / "ne_50m_rivers.geojson").read_text())
    for feature in rivers["features"]:
        rank = feature["properties"].get("scalerank") or 9
        if rank > 6:
            continue
        river_w = {1: 3.0, 2: 2.4, 3: 2.4, 4: 1.9}.get(rank, 1.4) * factor * layout.scale
        for line in lines_of(feature["geometry"]):
            if near(line, 0):
                draw.line([layout.xy(lon, lat, factor) for lon, lat, *_ in line], fill=RIVER + (200,), width=max(1, int(river_w)), joint="curve")
    for lon, lat, count, spread, size in MOUNTAINS:
        for _ in range(count):
            x, y = layout.xy(lon + rng.uniform(-spread, spread), lat + rng.uniform(-spread, spread) * 0.6, factor)
            if land_mask.getpixel((int(min(big[0] - 1, max(0, x))), int(min(big[1] - 1, max(0, y))))):
                mountain(draw, x, y, 22 * size * factor * layout.scale, rng)
    sea_face = lishu(int(34 * factor * layout.scale))
    for name, lon, lat in SEAS:
        x, y = layout.xy(lon, lat, factor)
        for index, char in enumerate(name):
            draw.text((x, y + index * 40 * factor * layout.scale), char, font=sea_face, fill=(70, 96, 100, 150), anchor="mm")
    map_img = map_img.reduce(factor)
    box = tuple(int(round(value)) for value in layout.box)
    canvas.paste(map_img.crop(box), box[:2])
    draw = ImageDraw.Draw(canvas, "RGBA")
    s = layout.scale
    draw.rectangle(box, outline=INK + (230,), width=max(2, int(3 * s)))
    draw.rectangle([box[0] - 10 * s, box[1] - 10 * s, box[2] + 10 * s, box[3] + 10 * s], outline=INK + (150,), width=max(1, int(1.5 * s)))
    face = lishu(int(64 * s))
    draw.text((layout.width / 2, layout.title_y), title, font=face, fill=INK + (255,), anchor="ma")
    return canvas.convert("RGB")


def leg_points(a, b, samples=48):
    (x0, y0), (x1, y1) = a, b
    length = math.hypot(x1 - x0, y1 - y0) or 1
    bend = min(0.16 * length, 70)
    cx, cy = (x0 + x1) / 2 - (y1 - y0) / length * bend, (y0 + y1) / 2 + (x1 - x0) / length * bend
    return [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1)
            for t in (i / samples for i in range(samples + 1))]


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def ease(value):
    value = clamp(value)
    return value * value * (3 - 2 * value)


class Painter:
    def __init__(self, spec):
        self.layout = Layout(spec["width"], spec["height"])
        self.base = base_map(self.layout, spec.get("title") or "", spec["data_dir"])
        self.cache = {}
        self.small = lishu(int(34 * self.layout.scale))
        self.large = lishu(int(48 * self.layout.scale))
        self.date_face = ai_studio_fonts.song(int(40 * self.layout.scale))
        self.backgrounds = {}

    def points(self, route, factor=1):
        return [self.layout.xy(stop["lon"], stop["lat"], factor) for stop in route]

    def legs_layer(self, route, count):
        """前 count 段完整路线（2 倍超采样后缩小），缓存复用。"""
        key = (tuple((stop["lon"], stop["lat"]) for stop in route), count)
        if key not in self.cache:
            factor = 2
            layer = Image.new("RGBA", (self.layout.width * factor, self.layout.height * factor), (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            pts = self.points(route, factor)
            for index in range(count):
                self.stroke(draw, leg_points(pts[index], pts[index + 1]), factor)
            self.cache[key] = layer.reduce(factor)
        return self.cache[key]

    def stroke(self, draw, line, factor):
        s = self.layout.scale * factor
        if len(line) < 2:
            return
        draw.line(line, fill=ROUTE_DARK + (235,), width=max(2, int(8 * s)), joint="curve")
        draw.line(line, fill=ROUTE + (255,), width=max(1, int(4.6 * s)), joint="curve")

    def route_frame(self, frame, route, progress, alpha=1.0):
        if len(route) < 2 or alpha <= 0:
            return
        full = int(math.floor(progress + 1e-6))
        full = min(full, len(route) - 1)
        layer = self.legs_layer(route, full)
        if alpha < 1:
            layer = layer.copy()
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
        frame.alpha_composite(layer)
        part = progress - full
        if part > 1e-3 and full < len(route) - 1:
            factor = 2
            pts = self.points(route, factor)
            line = leg_points(pts[full], pts[full + 1], 96)
            cut = line[:max(2, int(len(line) * part) + 1)]
            xs, ys = [p[0] for p in cut], [p[1] for p in cut]
            pad = 30 * factor
            x0, y0 = int(max(0, min(xs) - pad)), int(max(0, min(ys) - pad))
            x1, y1 = int(min(self.layout.width * factor, max(xs) + pad)), int(min(self.layout.height * factor, max(ys) + pad))
            x0, y0 = x0 - x0 % 2, y0 - y0 % 2
            x1, y1 = x1 + x1 % 2, y1 + y1 % 2
            patch = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
            draw = ImageDraw.Draw(patch)
            local = [(x - x0, y - y0) for x, y in cut]
            self.stroke(draw, local, factor)
            tip = local[-1]
            radius = 7 * self.layout.scale * factor
            draw.ellipse([tip[0] - radius, tip[1] - radius, tip[0] + radius, tip[1] + radius], fill=(240, 120, 70, 255))
            patch = patch.reduce(factor)
            if alpha < 1:
                patch.putalpha(patch.getchannel("A").point(lambda v: int(v * alpha)))
            frame.alpha_composite(patch, (x0 // factor, y0 // factor))

    def stations(self, route, progress):
        """每个地名的显现度和强调度（同名站点合并）。"""
        result = {}
        last = min(len(route) - 1, int(math.floor(progress + 1e-6)))
        part = progress - last
        for index, stop in enumerate(route):
            if index == 0:
                shown = 1.0
            else:
                shown = clamp((progress - (index - 1) - 0.75) / 0.25)
            if index == last:
                emphasis = 1 - ease((part - 0.75) / 0.25) if index < len(route) - 1 else 1.0
            elif index == last + 1:
                emphasis = ease((part - 0.75) / 0.25)
            else:
                emphasis = 0.0
            if shown <= 0 or not stop.get("name"):
                continue
            name = stop["name"]
            old = result.get(name)
            if old:
                result[name] = (old[0], max(old[1], shown), max(old[2], emphasis))
            else:
                result[name] = (stop, shown, emphasis)
        return result

    def labels(self, frame, marks, pulse):
        layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        s = self.layout.scale
        for name, (stop, shown, emphasis) in marks.items():
            x, y = self.layout.xy(stop["lon"], stop["lat"])
            if emphasis > 0.01:
                ring = (12 + 26 * pulse) * s
                draw.ellipse([x - ring, y - ring, x + ring, y + ring], outline=ROUTE + (int(170 * (1 - pulse) * emphasis * shown),), width=max(1, int(3 * s)))
            radius = (6 + 5 * emphasis) * s
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=ROUTE_DARK + (int(255 * shown),),
                         outline=(250, 236, 214, int(220 * shown)), width=max(1, int(2 * s)))
            anchor = stop.get("anchor") or "e"
            for face, alpha, color in ((self.small, shown * (1 - emphasis), INK), (self.large, shown * emphasis, ROUTE_DARK)):
                if alpha < 0.02:
                    continue
                gap = (16 if face is self.small else 20) * s
                position, mode = {"e": ((x + gap, y), "lm"), "w": ((x - gap, y), "rm"), "n": ((x, y - gap), "md"),
                                  "s": ((x, y + gap), "ma")}.get(anchor, ((x + gap, y), "lm"))
                draw.text(position, name, font=face, fill=color + (int(255 * alpha),), anchor=mode,
                          stroke_width=max(1, int(3 * s)), stroke_fill=(240, 226, 196, int(200 * alpha)))
        frame.alpha_composite(layer)

    def date(self, frame, text, alpha):
        if not text or alpha < 0.02:
            return
        layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((self.layout.width / 2, self.layout.date_y), text, font=self.date_face, fill=INK + (int(255 * alpha),), anchor="ma")
        frame.alpha_composite(layer)

    def background(self, path):
        if path not in self.backgrounds:
            image = Image.open(path).convert("RGB")
            w, h = self.layout.width, self.layout.height
            ratio = max(w / image.width, h / image.height)
            image = image.resize((math.ceil(image.width * ratio), math.ceil(image.height * ratio)), Image.LANCZOS)
            left, top = (image.width - w) // 2, (image.height - h) // 2
            self.backgrounds[path] = image.crop((left, top, left + w, top + h))
        return self.backgrounds[path]

    def frame(self, segment, t):
        duration = float(segment["duration"])
        route = segment.get("route") or []
        move = segment.get("move") or [0.15, 0.85]
        span = max(1e-3, (move[1] - move[0]) * duration)
        progress_mix = ease((t - move[0] * duration) / span)
        start, end = float(segment.get("from", 0)), float(segment.get("to", segment.get("from", 0)))
        progress = start + (end - start) * progress_mix
        cycles = max(1, round(duration / 1.8))
        pulse = math.sin(math.pi * cycles * t / duration) ** 2
        image = self.base.convert("RGBA")
        fade = segment.get("fade")
        fade_alpha = 0.0
        if fade:
            window = fade.get("window") or [0.1, 0.6]
            fade_alpha = 1 - ease((t / duration - window[0]) / max(1e-3, window[1] - window[0]))
            self.route_frame(image, fade["route"], float(fade["progress"]), fade_alpha)
        self.route_frame(image, route, progress)
        marks = self.stations(route, progress) if route else {}
        if fade and fade_alpha > 0:
            marks = {name: (stop, shown, emphasis * (1 - fade_alpha)) for name, (stop, shown, emphasis) in marks.items()}
            extra = self.stations(fade["route"], float(fade["progress"]))
            for name, (stop, shown, emphasis) in extra.items():
                own = marks.get(name)
                merged_shown = max(own[1] if own else 0, shown * fade_alpha)
                merged_emph = max(own[2] if own else 0, emphasis * fade_alpha)
                marks[name] = (stop, merged_shown, merged_emph)
        self.labels(image, marks, pulse)
        date_from, date_to = segment.get("date_from") or "", segment.get("date_to", segment.get("date_from")) or ""
        if date_from == date_to:
            self.date(image, date_from, 1.0)
        else:
            at = float(segment.get("date_at", move[1])) * duration
            mix = ease((t - at + 0.35) / 0.7)
            self.date(image, date_from, 1 - mix)
            self.date(image, date_to, mix)
        reveal = segment.get("reveal")
        if segment.get("background") and reveal:
            alpha = ease((t - reveal[0]) / max(1e-3, reveal[1] - reveal[0]))
            if alpha < 1:
                image = Image.blend(self.background(segment["background"]).convert("RGBA"), image, alpha)
        return image.convert("RGB")


def render(painter, spec, clip):
    if clip.get("still"):
        painter.frame(clip["segments"][0], float(clip.get("still_at") or 0)).save(clip["still"])
        return
    fps = int(spec.get("fps") or 24)
    width, height = spec["width"], spec["height"]
    command = [spec.get("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", clip["out"]]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for segment in clip["segments"]:
            frames = max(2, round(float(segment["duration"]) * fps))
            for index in range(frames):
                # 最后一帧精确落在段尾状态，前后两段（以及上下两集）首尾帧完全一致
                t = float(segment["duration"]) * index / (frames - 1)
                process.stdin.write(painter.frame(segment, t).tobytes())
    finally:
        process.stdin.close()
    if process.wait():
        sys.exit("ffmpeg 编码地图动画失败")


def fit_bounds(spec):
    """系列总路线（及本次各段路线）超出默认范围时向外扩，留 1.5° 边；全在默认范围内的系列画面不变。"""
    global LON0, LON1, LAT0, LAT1
    routes = [spec.get("life") or []]
    for clip in spec.get("clips") or [spec]:
        for segment in clip.get("segments") or []:
            routes += [segment.get("route") or [], (segment.get("fade") or {}).get("route") or []]
    stops = [stop for route in routes for stop in route]
    if stops:
        LON0 = min(LON0, min(stop["lon"] for stop in stops) - 1.5)
        LON1 = max(LON1, max(stop["lon"] for stop in stops) + 1.5)
        LAT0 = min(LAT0, min(stop["lat"] for stop in stops) - 1.5)
        LAT1 = max(LAT1, max(stop["lat"] for stop in stops) + 1.5)


def main(spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    fit_bounds(spec)
    painter = Painter(spec)
    for clip in spec.get("clips") or [spec]:
        render(painter, spec, clip)


if __name__ == "__main__":
    main(sys.argv[1])
