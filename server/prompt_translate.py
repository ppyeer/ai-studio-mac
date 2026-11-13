"""AI Studio 提示词的中文对照：用本机 Ollama 翻译，只供阅读，不改提交的提示词。

译文按原文哈希缓存在本机，同一段再看时直接返回。引号里的中文（台词、诗句，可能故意用了同音字）
翻译前换成占位符，翻译后原样放回。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

OLLAMA_URL = os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434"
OLLAMA_BIN = os.environ.get("OLLAMA_BIN") or shutil.which("ollama") or "/usr/local/bin/ollama"
MODEL = os.environ.get("AI_STUDIO_TRANSLATE_MODEL") or "qwen3:8b"
CACHE_PATH = Path(os.environ.get("AI_STUDIO_DATA") or Path(__file__).resolve().parent.parent / "data") / "prompt-zh-cache.json"
CACHE_MAX = 800
TEXT_MAX = 6000
SYSTEM_PROMPT = (
    "把用户给出的英文视频 / 图片生成提示词翻译成简体中文，供人阅读对照。"
    "<Picture 1>、[Shot 1]、⟦1⟧ 这类标记和时间码原样保留，人名、地名按中文习惯译出。只输出译文，不要解释。"
)
QUOTED_CJK = re.compile(r"[“\"「『][^”\"」』]*[\u4e00-\u9fff][^”\"」』]*[”\"」』]")


class PromptTranslateError(ValueError):
    pass


_lock = threading.Lock()
_cache: dict[str, str] | None = None


def _load_cache() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache(cache: dict[str, str]) -> None:
    if len(cache) > CACHE_MAX:
        for key in list(cache)[: len(cache) - CACHE_MAX]:
            cache.pop(key, None)
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = CACHE_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        temp.replace(CACHE_PATH)
    except OSError:
        pass


def _ollama_up() -> bool:
    try:
        with urlopen(f"{OLLAMA_URL}/api/version", timeout=1.5):
            return True
    except (URLError, OSError, TimeoutError):
        return False


def _ensure_ollama() -> None:
    if _ollama_up():
        return
    if not Path(OLLAMA_BIN).exists():
        raise PromptTranslateError("没有找到 Ollama，无法在本机翻译")
    log = (CACHE_PATH.parent / "ollama-serve.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([OLLAMA_BIN, "serve"], stdin=subprocess.DEVNULL, stdout=log.open("a"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    for _ in range(40):
        time.sleep(0.5)
        if _ollama_up():
            return
    raise PromptTranslateError("Ollama 没有启动起来")


def translate(text: str) -> dict:
    text = str(text or "").strip()
    if not text:
        return {"zh": "", "cached": True}
    if len(text) > TEXT_MAX:
        raise PromptTranslateError(f"这段太长（超过 {TEXT_MAX} 字符），没法翻译")
    if not re.search(r"[A-Za-z]{3}", text):
        return {"zh": text, "cached": True}
    key = hashlib.sha1(text.encode("utf-8")).hexdigest()
    with _lock:
        hit = _load_cache().get(key)
    if hit is not None:
        return {"zh": hit, "cached": True}
    _ensure_ollama()
    quotes: list[str] = []

    def keep(match: re.Match) -> str:
        quotes.append(match.group(0))
        return f"⟦{len(quotes)}⟧"

    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.2, "num_ctx": 8192},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": QUOTED_CJK.sub(keep, text)}],
    }
    request = Request(f"{OLLAMA_URL}/api/chat", json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=600) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        raise PromptTranslateError(f"本机翻译失败：{exc}") from exc
    if payload.get("error"):
        raise PromptTranslateError(f"本机翻译失败：{payload['error']}")
    output = re.sub(r"<think>.*?</think>", "", str(payload.get("message", {}).get("content") or ""), flags=re.S).strip()
    output = re.sub(r"⟦(\d+)⟧", lambda m: quotes[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(quotes) else m.group(0), output)
    if not output:
        raise PromptTranslateError("本机模型没有返回译文")
    with _lock:
        cache = _load_cache()
        cache[key] = output
        _save_cache(cache)
    return {"zh": output, "cached": False}
