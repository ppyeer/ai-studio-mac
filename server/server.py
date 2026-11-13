"""AI Studio 独立服务：网页 + /api/tools/ai-studio 接口，渲染交给本机 ComfyUI。

    python server/server.py            # 默认 0.0.0.0:8001，见 .env.example
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_studio  # noqa: E402
from ai_studio import AiStudio  # noqa: E402
from prompt_translate import translate as translate_prompt_zh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = Path(os.environ.get("AI_STUDIO_DATA") or ROOT / "data").expanduser()
JOBS_PATH = DATA_DIR / "ai-studio-jobs.json"
HOST = os.environ.get("AI_STUDIO_HOST") or "0.0.0.0"
PORT = int(os.environ.get("AI_STUDIO_PORT") or 8001)
MAX_BODY = 85 * 1024 * 1024  # 最多 4 张参考图，每张 15 MB，base64 后约 80 MB
COMFY_AUTOSTART = (os.environ.get("AI_STUDIO_COMFY_AUTOSTART") or "1") != "0"
STATIC_FILES = {"index.html", "ai-studio.js", "ai-studio.css", "ai-finals.html", "favicon.svg"}

_comfy_lock = threading.Lock()
_comfy_started = {"at": 0.0}


def ensure_comfy() -> None:
    """ComfyUI 没在跑时自己拉起来（一般由 systemd 托管，这里只是兜底）。"""
    if not COMFY_AUTOSTART or ai_studio._comfy_up():
        return
    with _comfy_lock:
        if time.time() - _comfy_started["at"] < 180 or ai_studio._comfy_up():
            return
        comfy = ai_studio.COMFY_DIR
        python = Path(os.environ.get("COMFYUI_PYTHON") or comfy / ".venv" / "bin" / "python")
        if not python.is_file() or not (comfy / "main.py").is_file():
            raise ai_studio.AiStudioError(f"ComfyUI 没有运行，也找不到 {comfy}/main.py，请先运行 scripts/install.sh")
        port = urlparse(ai_studio.COMFY_URL).port or 8188
        log = ai_studio.COMFY_LOG_PATH
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as handle:
            handle.write(f"\n===== AI Studio 启动 ComfyUI {time.strftime('%F %T')} =====\n".encode())
            handle.flush()
            subprocess.Popen([str(python), "main.py", "--listen", "127.0.0.1", "--port", str(port),
                              *shlex.split(os.environ.get("COMFYUI_ARGS") or "")], cwd=str(comfy),
                             stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        _comfy_started["at"] = time.time()


_studio: AiStudio | None = None
_studio_lock = threading.Lock()


def studio() -> AiStudio:
    global _studio
    with _studio_lock:
        if _studio is None:
            _studio = AiStudio(JOBS_PATH, ensure_comfy=ensure_comfy)
        return _studio


def comfy_log_tail(lines: int = 400) -> str:
    try:
        with ai_studio.COMFY_LOG_PATH.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 256 * 1024))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return f"（还没有 ComfyUI 日志：{ai_studio.COMFY_LOG_PATH}）"
    return "\n".join(text.splitlines()[-lines:])


class Handler(BaseHTTPRequestHandler):
    server_version = "AIStudio/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("AI_STUDIO_ACCESS_LOG") == "1":
            super().log_message(fmt, *args)

    # ---------- 工具 ----------
    def parts(self) -> list[str]:
        return [part for part in unquote(urlparse(self.path).path).split("/") if part]

    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_problem(self, message: str, status: int = 400) -> None:
        self.send_json({"error": message}, status)

    def read_json(self, limit: int) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > limit:
            self.close_connection = True
            raise OverflowError
        raw = self.rfile.read(length) if length else b""
        data = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        return data if isinstance(data, dict) else {}

    def same_origin(self) -> bool:
        origin = self.headers.get("Origin", "")
        return not (self.headers.get("Sec-Fetch-Site") == "cross-site" or (origin and urlparse(origin).netloc != self.headers.get("Host")))

    def handle_errors(self, action) -> None:
        try:
            action()
        except OverflowError:
            self.send_problem("请求过大：图片请控制在 15 MB 以内", 413)
        except json.JSONDecodeError:
            self.send_problem("Invalid JSON", 400)
        except ValueError as exc:  # AiStudioError / PromptTranslateError 都是 ValueError
            self.send_problem(str(exc), 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            self.send_problem(f"Server error: {exc}", 500)

    # ---------- 静态文件 ----------
    def send_file(self, file_path: Path, cache: str = "no-cache") -> None:
        # 视频要支持 Range，浏览器才能拖动进度条。
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        file_size = file_path.stat().st_size
        start, end = 0, max(0, file_size - 1)
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", str(self.headers.get("Range") or "").strip())
        partial = bool(match and (match.group(1) or match.group(2)))
        if partial:
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), file_size - 1) if match.group(2) else file_size - 1
            else:
                start = max(0, file_size - int(match.group(2)))
            if start >= file_size or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = end - start + 1 if file_size else 0
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(file_path.name)}")
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if self.command == "HEAD":
            return
        with file_path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def serve_static(self, path: str) -> None:
        relative = path.lstrip("/")
        if path in {"", "/"}:
            self.send_response(302)
            self.send_header("Location", "/ai-studio")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        # /ai-studio/<系列>/<分组> 这类前端路由都回到同一个页面
        name = relative if relative in STATIC_FILES else "index.html"
        self.send_file(WEB_DIR / name)

    # ---------- 路由 ----------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        def action():
            path = urlparse(self.path).path
            parts = self.parts()
            if path == "/api/tools/ai-studio":
                service = studio()
                return self.send_json({"config": service.config(), **service.state()})
            if path == "/api/tools/ai-studio/comfy-log":
                body = comfy_log_tail().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if parts[:4] == ["api", "tools", "ai-studio", "media"]:
                if len(parts) != 6:
                    return self.send_problem("文件不存在", 404)
                try:
                    target = studio().media(parts[4], parts[5])
                except ValueError:
                    return self.send_problem("文件不存在", 404)
                return self.send_file(target, "private, max-age=300")
            if path.startswith("/api/"):
                return self.send_problem("Not found", 404)
            return self.serve_static(path)
        self.handle_errors(action)

    def do_POST(self):
        def action():
            parts = self.parts()
            if parts[:3] != ["api", "tools", "ai-studio"]:
                return self.send_problem("Not found", 404)
            if not self.same_origin():
                return self.send_problem("不接受跨站 AI Studio 操作", 403)
            payload = self.read_json(MAX_BODY)
            service = studio()
            if parts == ["api", "tools", "ai-studio", "lint"]:
                return self.send_json(service.lint(payload))
            if parts == ["api", "tools", "ai-studio", "jobs"]:
                job = service.create(payload)
                return self.send_json({"job": job, "state": service.state()})
            if parts == ["api", "tools", "ai-studio", "series"]:
                series = service.create_series(payload)
                return self.send_json({"series": series, "state": service.state()})
            if parts == ["api", "tools", "ai-studio", "translate"]:
                return self.send_json(translate_prompt_zh(payload.get("text", "")))
            if len(parts) == 8 and parts[3] == "series" and parts[5] == "episodes" and parts[7] == "compose":
                job = service.compose_episode(parts[4], parts[6])
                return self.send_json({"job": job, "state": service.state()})
            if len(parts) == 8 and parts[3] == "series" and parts[5] == "episodes" and parts[7] == "voice":
                result = service.voice_episode(parts[4], parts[6], payload)
                return self.send_json({**result, "state": service.state()})
            if len(parts) == 6 and parts[3] == "jobs" and parts[5] in {"cancel", "rerun"}:
                if parts[5] == "cancel":
                    job = service.cancel(parts[4])
                else:
                    job = service.rerun(parts[4], new_seed=bool(payload.get("new_seed", True)),
                                        fast=payload["fast"] if isinstance(payload.get("fast"), bool) else None)
                return self.send_json({"job": job, "state": service.state()})
            return self.send_problem("未知 AI Studio 接口", 404)
        self.handle_errors(action)

    def do_PATCH(self):
        def action():
            parts = self.parts()
            if len(parts) != 5 or parts[:3] != ["api", "tools", "ai-studio"] or parts[3] not in {"jobs", "series"}:
                return self.send_problem("Not found", 404)
            if not self.same_origin():
                return self.send_problem("不接受跨站 AI Studio 操作", 403)
            service = studio()
            if parts[3] == "jobs":
                job = service.update(parts[4], self.read_json(10_000))
                return self.send_json({"job": job, "state": service.state()})
            series = service.update_series(parts[4], self.read_json(4_000_000))
            return self.send_json({"series": series, "state": service.state()})
        self.handle_errors(action)

    def do_DELETE(self):
        def action():
            parts = self.parts()
            if len(parts) != 5 or parts[:3] != ["api", "tools", "ai-studio"] or parts[3] not in {"jobs", "series", "voices"}:
                return self.send_problem("Not found", 404)
            if not self.same_origin():
                return self.send_problem("不接受跨站 AI Studio 操作", 403)
            service = studio()
            {"jobs": service.delete, "series": service.delete_series, "voices": service.delete_voice}[parts[3]](parts[4])
            return self.send_json({"ok": True, "state": service.state()})
        self.handle_errors(action)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    studio()  # 重启后马上接着跟踪没跑完的任务
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"AI Studio: http://{HOST}:{PORT}/ai-studio  ComfyUI: {ai_studio.COMFY_URL}  素材库: {ai_studio.LIBRARY_DIR}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
