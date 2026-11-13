"""Word-timestamped Mandarin STT of one take with faster-whisper on the CPU (the GPU keeps rendering).

Two passes: plain, and with the expected lines as the initial prompt (a prompt alone can drop whole stretches).
Every character also gets its toneless pinyin, so a homophone is not scored as a miss.
transcribe() -> {"plain": [[start, end, word], ...], "prompt": [...], "py": {char: pinyin} or None without pypinyin}
"""
from faster_whisper import WhisperModel


def pinyin(chars):
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return None
    return {c: (lazy_pinyin(c) or [c])[0] for c in chars}


def transcribe(path, lines, model="large-v3-turbo"):
    m = WhisperModel(model, device="cpu", compute_type="int8")

    def run(**kw):
        segs, _ = m.transcribe(str(path), language="zh", word_timestamps=True, vad_filter=True, **kw)
        return [[w.start, w.end, w.word] for s in segs for w in (s.words or [])]

    res = {"plain": run()}
    prompt = "，".join(lines)[:400]
    res["prompt"] = run(initial_prompt=prompt, condition_on_previous_text=False) if prompt else res["plain"]
    res["py"] = pinyin({c for t in lines for c in t} | {c for k in ("plain", "prompt") for x in res[k] for c in x[2]})
    return res
