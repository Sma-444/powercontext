"""本地 Web 界面：只用标准库 ``http.server``，不引入前端构建链。

这样评审 ``pip install -r requirements.txt`` 之后就能 ``python -m duban serve``，
不需要 node、不需要打包、也不需要连外网。

请求都是 JSON，处理函数在同一个 asyncio 事件循环里跑（HTTP 线程通过
``run_coroutine_threadsafe`` 投递协程），因此 seekdb 与 PowerContext 的异步接口
不需要任何改造。
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from duban.config import Settings
from duban.service import Duban, open_runtime


class Api:
    """把 HTTP 动作翻译成 ``Duban`` 的调用。"""

    def __init__(self, duban: Duban, loop: asyncio.AbstractEventLoop) -> None:
        self.duban = duban
        self.loop = loop

    def call(self, coroutine, timeout: float = 90.0):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=timeout)


def build_handler(api: Api, web_root: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "duban/0.1"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - 标准库签名
            if self.path.startswith("/api/"):
                return
            print(f"[web] {self.address_string()} {fmt % args}")

        # ------------------------------------------------------------------ GET

        def do_GET(self) -> None:  # noqa: N802 - 标准库命名
            parsed = urlparse(self.path)
            params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            try:
                if parsed.path in ("/", "/index.html"):
                    return self._index(params)
                if parsed.path.startswith("/static/"):
                    relative = parsed.path[len("/static/") :]
                    target = (web_root / relative).resolve()
                    if web_root.resolve() not in target.parents:
                        return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                    return self._file(target)
                if parsed.path == "/api/health":
                    return self._json({"ok": True, "user": api.duban.settings.user})
                if parsed.path == "/api/state":
                    return self._json(api.call(api.duban.state()))
                if parsed.path == "/api/page":
                    return self._json(
                        api.call(
                            api.duban.page(params.get("doc_id", ""), int(params.get("page") or 0))
                        )
                    )
                if parsed.path == "/api/resolve":
                    return self._json(
                        api.call(api.duban.resolve(params.get("doc_id", ""), params.get("anchor", "")))
                    )
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as error:  # noqa: BLE001 - 统一转成 JSON 错误
                return self._json({"error": f"{type(error).__name__}: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        # ----------------------------------------------------------------- POST

        def do_POST(self) -> None:  # noqa: N802 - 标准库命名
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            try:
                if parsed.path == "/api/ask":
                    question = str(payload.get("question") or "").strip()
                    if not question:
                        return self._json({"error": "question 不能为空"}, HTTPStatus.BAD_REQUEST)
                    result = api.call(api.duban.ask(question))
                    return self._json(result.as_dict())
                if parsed.path == "/api/mark":
                    term = str(payload.get("term") or "").strip()
                    if not term:
                        return self._json({"error": "term 不能为空"}, HTTPStatus.BAD_REQUEST)
                    api.call(api.duban.mark_weak(term, str(payload.get("note") or ""), str(payload.get("source") or "")))
                    return self._json(api.call(api.duban.state()))
                if parsed.path == "/api/unmark":
                    api.call(api.duban.unmark_weak(str(payload.get("term") or "")))
                    return self._json(api.call(api.duban.state()))
                if parsed.path == "/api/profile":
                    changes = {key: value for key, value in payload.items() if key in {"depth", "language", "note"}}
                    api.call(api.duban.set_profile(**changes))
                    return self._json(api.call(api.duban.state()))
                if parsed.path == "/api/progress":
                    api.call(
                        api.duban.touch(
                            str(payload.get("doc_id") or ""),
                            page=int(payload.get("page") or 0),
                            anchor=str(payload.get("anchor") or ""),
                            ratio=float(payload.get("ratio") or 0.0),
                        )
                    )
                    return self._json({"ok": True})
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as error:  # noqa: BLE001
                return self._json({"error": f"{type(error).__name__}: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        # -------------------------------------------------------------- helpers

        def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path) -> None:
            if not path.is_file():
                return self._json({"error": f"missing {path.name}"}, HTTPStatus.NOT_FOUND)
            body = path.read_bytes()
            mime, _ = mimetypes.guess_type(path.name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _index(self, params: dict[str, str]) -> None:
            """首页。``?preload=1&q=...`` 会把状态与答案直接内联进 HTML。

            这样截图/分享链接打开时首屏就有内容，不必等前端再发一轮请求；
            也让评审在弱网下打开就先看到结果。
            """

            template = (web_root / "index.html").read_text(encoding="utf-8")
            if params.get("preload") != "1":
                body = template.encode("utf-8")
            else:
                preload: dict[str, object] = {"state": api.call(api.duban.state())}
                question = params.get("q") or ""
                if question:
                    preload["answer"] = api.call(api.duban.ask(question, remember=False)).as_dict()
                payload = json.dumps(preload, ensure_ascii=False).replace("</", "<\\/")
                script = f'<script>window.__PRELOAD__ = {payload};</script>\n'
                body = template.replace('<script src="/static/app.js"></script>', script + '<script src="/static/app.js"></script>').encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


async def serve(settings: Settings, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    async with open_runtime(settings) as duban:
        await duban.init()
        api = Api(duban, asyncio.get_running_loop())
        httpd = ThreadingHTTPServer((host, port), build_handler(api, settings.web))
        httpd.daemon_threads = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        print(f"读伴已启动：http://{host}:{port}")
        print(f"数据库：{settings.database}")
        print(f"作用域：{settings.scope}")
        print("Ctrl+C 结束。")
        try:
            while True:
                await asyncio.sleep(1.0)
        finally:
            httpd.shutdown()
            httpd.server_close()
