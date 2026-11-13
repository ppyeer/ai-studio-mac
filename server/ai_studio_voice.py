"""AI Studio 配音：用 IndexTTS-2.5 按参考音色把每个镜头的配音文字读成 wav。

由 ai_studio.py 用 index-tts 自己的 venv 调用：python ai_studio_voice.py spec.json
spec = {model_dir, items: [{id, text, ref, out}]}；模型只加载一次，逐条生成，每条结束打印一行 JSON：
{"id", "ok", "duration", "error"}。text 里可带 <字|PIN4> 读音标注。
另有 python ai_studio_voice.py --check：从 stdin 读 {"texts": [...]}，打印每段里没标注的多音字和 pypinyin 按上下文猜的读音。
"""
import json
import re
import sys
import wave
from pathlib import Path

MARK = re.compile(r"<([^<>|]+)\|([^<>]+)>")
# 朗读里真正容易读错的多音字；pypinyin 的异读表太全（"泥""留"都算），只报这些
POLYPHONES = set("似那爪还长行更为处正解了纶参冠系重朝少好中间见将相乐数难散教看着得便降传调薄落曲弹藏尽应骑横发华胜空斗转"
                 "识吐号和恶量度省塞卷差闷漂累兴缝折露血载择宿佛扇闻凉论分供奔背壳模强据剥恐几禁哪若泊盛舍属率涨种处没要会觉")


def marked(text):
    """标注里 j/q/x 后的 u 改成 v（que4 → QVE4），和 IndexTTS 训练时的拼音写法一致，否则会读错。"""
    def fix(match):
        return "<" + match.group(1) + "|" + re.sub(r"^([JQX])U", r"\1V", match.group(2).upper()) + ">"
    return MARK.sub(fix, text)


def check(texts):
    from pypinyin import Style, pinyin

    result = []
    for text in texts:
        plain = MARK.sub(lambda match: "\0" * len(match.group(1)), text)
        guesses = pinyin(plain, style=Style.TONE3, heteronym=False, neutral_tone_with_five=True, errors=lambda chars: [[""] for _ in chars])
        found = []
        for char, guess in zip(plain, guesses):
            if char == "\0" or char not in POLYPHONES or not guess or not guess[0]:
                continue
            options = pinyin(char, style=Style.TONE3, heteronym=True, neutral_tone_with_five=True)[0]
            if len(options) > 1 and not any(item["char"] == char and item["guess"] == guess[0] for item in found):
                found.append({"char": char, "guess": guess[0], "options": options[:6]})
        result.append(found)
    return result


def recite(tts, item):
    """诗句吟诵：一句一句分开读（句内二二三的停顿靠顿号），句与句之间按 pause 秒补静音再接起来。"""
    frames, params = [], None
    for index, part in enumerate(item["parts"]):
        piece = f"{item['out']}.part{index}.wav"
        tts.infer(spk_audio_prompt=item["ref"], text=marked(part["text"]), lang="ZH", output_path=piece,
                  duration_factor=float(item.get("speed") or 1.0))
        with wave.open(piece) as handle:
            params = params or handle.getparams()
            frames.append(handle.readframes(handle.getnframes()))
        Path(piece).unlink()
        if index < len(item["parts"]) - 1:
            frames.append(b"\0" * (int(params.framerate * float(part.get("pause") or 0)) * params.sampwidth * params.nchannels))
    with wave.open(item["out"], "wb") as handle:
        handle.setparams(params)
        handle.writeframes(b"".join(frames))


def main():
    if sys.argv[1:] == ["--check"]:
        print(json.dumps(check(json.load(sys.stdin).get("texts") or []), ensure_ascii=False))
        return
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    from indextts.infer_v2_5 import IndexTTS2

    model_dir = spec["model_dir"]
    tts = IndexTTS2(cfg_path=str(Path(model_dir) / "config.yaml"), model_dir=model_dir)
    for item in spec["items"]:
        try:
            Path(item["out"]).parent.mkdir(parents=True, exist_ok=True)
            if item.get("parts"):
                recite(tts, item)
            else:
                tts.infer(spk_audio_prompt=item["ref"], text=marked(item["text"]), lang="ZH", output_path=item["out"],
                          duration_factor=float(item.get("speed") or 1.0))
            with wave.open(item["out"]) as handle:
                duration = handle.getnframes() / handle.getframerate()
            print(json.dumps({"id": item["id"], "ok": True, "duration": round(duration, 3)}), flush=True)
        except Exception as exc:  # 一条失败不影响后面几条
            print(json.dumps({"id": item["id"], "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
