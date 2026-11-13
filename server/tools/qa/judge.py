"""Verdict for one take from its measurements.

FAIL reasons are the ones a new seed usually fixes: no clean piece of 2 s or more, a frozen picture, a missing or
garbled line. LENS and ZOOM are only suspects (a frontal head is not proof of looking into the lens; a body moving
toward the camera reads as a push): check them on the contact sheet before you reject the take.
"""
import difflib
import math
import re

NORM = re.compile(r"[\s\*…，。？！、,.?!:：；;“”\"'（）()—\-～~]")


def norm(s):
    return NORM.sub("", s)


def match(words, want, py):
    """(recall of the line `want` in the word list, [start, end] of the matched stretch or None)."""
    ch = [(c, w[0], w[1]) for w in words for c in norm(w[2])]
    sm = difflib.SequenceMatcher(None, [py.get(c, c) for c in want], [py.get(c, c) for c, _, _ in ch], autojunk=False)
    blocks = [m for m in sm.get_matching_blocks() if m.size]
    solid = [m for m in blocks if m.size >= 2] or blocks
    span = [ch[solid[0].b][1], ch[solid[-1].b + solid[-1].size - 1][2]] if solid else None
    return sum(m.size for m in blocks) / len(want), span


def verdict(profile, dur, cuts, freezes, vis=None, stt=None, lines=()):
    fails, warns, retry = [], [], False
    v = {"profile": profile, "dur": round(dur, 2)}

    # cuts the model made inside the take: report the clean pieces, the edit cuts around them
    b = [0.0] + sorted(c for c in cuts if 0.05 < c < dur - 0.05) + [dur]
    pieces = [[round(b[i], 2), round(b[i + 1], 2)] for i in range(len(b) - 1)]
    v["cuts"], v["pieces"] = [round(c, 2) for c in b[1:-1]], pieces
    frag = [p for p in pieces if p[1] - p[0] < 1.0]
    if frag:
        warns.append(f"CUT 模型内部硬切留下 <1 s 碎片 {frag}，剪辑要避开")
    if max(p[1] - p[0] for p in pieces) < 2.0:
        fails.append("CUT 没有 ≥2 s 的完整镜头")
        retry = True

    long_fz = [f for f in freezes if f[1] >= 1.0]
    if long_fz:
        fails.append(f"FREEZE 画面冻结 {[(round(a, 1), round(d, 1)) for a, d in long_fz]}")
        retry = True

    v["lines"], v["lens"], v["zoom"] = [], [], []
    if profile == "dialogue" and stt is None:
        warns.append("LINE 台词没有检查（缺 faster-whisper 或识别失败，见 notes）")
    if profile == "dialogue" and stt is not None:
        py = stt.get("py") or {}
        for t in lines:
            w = norm(t)
            if not w:
                continue
            rec, span = max((match(stt[k], w, py) for k in ("plain", "prompt")), key=lambda r: r[0])
            v["lines"].append({"text": t, "recall": round(rec, 2), "span": span})
            if rec < 0.6:
                fails.append(f"LINE「{t}」没说出来或说错（召回 {rec:.2f}）")
                retry = True
            elif rec < 0.85:
                warns.append(f"LINE「{t}」不完整（召回 {rec:.2f}）")
            if span and any(span[0] + 0.1 < c < span[1] - 0.1 for c in v["cuts"]):
                warns.append(f"CUT 台词「{t}」中间被模型切了一刀")
        heard = sum(len(norm(x[2])) for x in stt["plain"])
        want = sum(len(norm(t)) for t in lines)
        v["heard"] = "".join(x[2] for x in stt["plain"])
        if want and heard > want * 1.5 + 4:
            warns.append(f"EXTRA 多出台词外的人声（听到 {heard} 字，台词 {want} 字）：{v['heard']}")
        if not want and heard >= 4:
            warns.append(f"EXTRA 本应无台词，听到：{v['heard']}")
        # LENS suspect: a frontal head while a line is spoken
        for line in v["lines"]:
            if not line["span"] or not vis:
                continue
            fs = [f for f in vis["faces"] if line["span"][0] <= f[0] <= line["span"][1]
                  and f[1] >= 0.12 and f[2] is not None and abs(f[2]) < 1.5]
            if len(fs) >= 3 and sorted(abs(f[2]) for f in fs)[len(fs) // 2] < 0.12:
                v["lens"].append({"text": line["text"], "span": line["span"],
                                  "yaw": round(sorted(abs(f[2]) for f in fs)[len(fs) // 2], 3)})
        if v["lens"]:
            warns.append("LENS 说话时接近正脸，需看画面确认是否直视镜头：" + "；".join(f"「{x['text']}」" for x in v["lens"]))

    # ZOOM suspect: the frame scale keeps one direction for 2+ s
    if vis:
        sec = {}
        for t, s in vis["scale"]:
            if s is None or abs(math.log(s)) > 0.08:
                continue
            sec.setdefault(int(t), []).append(math.log(s))
        v["zoom"] = [[k, round((math.exp(sum(x)) - 1) * 100, 2)] for k, x in sorted(sec.items())
                     if len(x) >= vis["fps"] * 0.6]
        sus = [(a, b2) for (a, za), (b2, zb) in zip(v["zoom"], v["zoom"][1:])
               if b2 == a + 1 and abs(za) > 1 and abs(zb) > 1 and (za > 0) == (zb > 0)]
        if sus:
            warns.append(f"ZOOM 画面持续推拉 {sus}（单位：秒；也可能是人物走向镜头），需看联系表复核")

    v.update(result="FAIL" if fails else "PASS", fails=fails, warns=warns, retryable=bool(fails) and retry)
    return v
