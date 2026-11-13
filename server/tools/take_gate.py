#!/usr/bin/env python3
"""Automatic checks of one rendered take, all on this machine.

  take_gate.py take.mp4 [--profile visual|dialogue] [--lines "台词1" "台词2"]
               [--yunet face_detection_yunet_2023mar.onnx] [--whisper large-v3-turbo] [-o verdict.json]

ffmpeg (always)          cuts the model made inside the take, frozen picture
OpenCV (optional)        ZOOM suspect from the frame-scale track; with --yunet also LENS (frontal head while speaking)
faster-whisper (dialogue profile, optional)
                         every expected line heard (two passes, pypinyin homophone tolerance), speech nobody wrote
Missing optional parts are skipped with a note in the verdict. Exit 0 = PASS, 1 = FAIL, 2 = the take could not be read.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa import judge  # noqa: E402

SCENE = 0.3                         # ffmpeg scene-change score counted as a cut
FREEZE = "freezedetect=n=-60dB:d=1"


def ffmpeg_measure(ffmpeg, take):
    """(duration, cut times, [(freeze start, freeze duration)]) from one decoding pass."""
    vf = f"{FREEZE},select='gt(scene,{SCENE})',showinfo"
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(take), "-map", "0:v:0", "-vf", vf, "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"ffmpeg exit {r.returncode}")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    cuts = [float(t) for t in re.findall(r"Parsed_showinfo.*?\bpts_time:\s*([0-9.]+)", r.stderr)]
    freezes, start = [], None
    for key, val in re.findall(r"freeze_(start|duration): ([0-9.]+)", r.stderr):
        if key == "start":
            start = float(val)
        elif start is not None:
            freezes.append((start, float(val)))
            start = None
    if start is not None:   # still frozen at the end of the take
        freezes.append((start, max(0.0, dur - start)))
    return dur, cuts, freezes


def summary(v, out):
    cuts = "、".join(f"{c} s" for c in v["cuts"]) or "无"
    word = "通过" if v["result"] == "PASS" else "不通过"
    print(f"{v['result']} {word} · {v['profile']} · {v['dur']} s · 模型切镜：{cuts}")
    for line in v["lines"]:
        print(f"  台词「{line['text']}」召回 {line['recall']}")
    for m in v["fails"]:
        print("  失败", m)
    for m in v["warns"]:
        print("  提醒", m)
    for m in v["notes"]:
        print("  跳过", m)
    if v["fails"] and v["retryable"]:
        print("  换一个 seed 重渲通常能修好")
    print("  明细", out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take", help="rendered mp4")
    ap.add_argument("--profile", choices=("visual", "dialogue"), default="visual",
                    help="visual: cuts, freeze, zoom; dialogue: also the spoken lines (default: visual)")
    ap.add_argument("--lines", nargs="*", default=[],
                    help="expected spoken lines; dialogue profile without lines flags any speech")
    ap.add_argument("--yunet", help="OpenCV YuNet face model file, enables the LENS check")
    ap.add_argument("--whisper", default="large-v3-turbo", help="faster-whisper model name or folder")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg binary (default: ffmpeg on PATH)")
    ap.add_argument("-o", "--output", help="verdict JSON (default: <take>.qa.json)")
    a = ap.parse_args(argv)

    try:
        dur, cuts, freezes = ffmpeg_measure(a.ffmpeg, a.take)
    except (OSError, RuntimeError) as e:
        print(f"take_gate: 读不了 {a.take}：{e}", file=sys.stderr)
        return 2
    notes, vis, stt = [], None, None
    try:
        from qa import vis as qa_vis
        vis = qa_vis.measure(a.take, cuts, a.yunet)
        if not a.yunet:
            notes.append("没给 --yunet：LENS（说话时正对镜头）检查跳过")
    except ImportError:
        notes.append("没装 opencv-python：ZOOM / LENS 检查跳过")
    except Exception as e:   # e.g. an OpenCV without FaceDetectorYN, or a bad model file
        notes.append(f"画面测量失败，ZOOM / LENS 检查跳过：{e}")
    if a.profile == "dialogue":
        try:
            from qa import stt as qa_stt
            stt = qa_stt.transcribe(a.take, a.lines, a.whisper)
            if stt["py"] is None:
                notes.append("没装 pypinyin：台词逐字比对，同音字会算成错字")
        except ImportError:
            notes.append("没装 faster-whisper：台词检查跳过")
        except Exception as e:   # e.g. the whisper model could not be downloaded
            notes.append(f"语音识别失败，台词检查跳过：{e}")
    elif a.lines:
        notes.append("--lines 只在 --profile dialogue 下检查")

    v = judge.verdict(a.profile, vis["dur"] if vis else dur, cuts, freezes, vis, stt, a.lines)
    v["take"], v["notes"] = a.take, notes
    out = a.output or a.take + ".qa.json"
    Path(out).write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    summary(v, out)
    return 0 if v["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
