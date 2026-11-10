"""
Zero-dependency server (Python standard library only) with the same endpoints as server/app.py.
Handy when you do not want to install FastAPI yet:

    python -m server.dev_server            # http://127.0.0.1:8000
    python -m server.dev_server --port 9000
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .api import ApiError, Settings, audio_file_for, bank_stats, health, start_exam, submit_exam

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
MAX_BODY = 1_000_000


def make_handler(settings):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ApiError(413, "body too large")
            if n == 0:
                return {}
            try:
                return json.loads(self.rfile.read(n))
            except ValueError:
                raise ApiError(400, "body is not valid JSON")

        def _dispatch(self, fn):
            try:
                self._send(200, fn())
            except ApiError as e:
                self._send(e.status, {"detail": e.message})
            except Exception as e:  # never leak a traceback to the client
                self._send(500, {"detail": f"internal error: {type(e).__name__}"})

        def _send_audio(self, parts):
            """GET /api/exam/<id>/audio/<part_id>: streams the part's mp3 with HTTP Range support (so the browser can seek)."""
            try:
                target, ctype = audio_file_for(parts[2], parts[4], settings)
            except ApiError as e:
                return self._send(e.status, {"detail": e.message})
            size = target.stat().st_size
            start, end, status = 0, size - 1, 200
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                try:
                    a, b = rng[6:].split(",")[0].split("-")
                    start = int(a) if a else max(0, size - int(b))
                    end = min(int(b), size - 1) if (a and b) else size - 1
                    if start > end or start >= size:
                        raise ValueError
                    status = 206
                except ValueError:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "private, max-age=3600")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with open(target, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def do_GET(self):
            path = self.path.split("?")[0]
            gparts = path.strip("/").split("/")
            if len(gparts) == 5 and gparts[:2] == ["api", "exam"] and gparts[3] == "audio":
                self._send_audio(gparts)
            elif path in ("/", "/index.html"):
                self._send(200, FRONTEND.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/health":
                self._dispatch(lambda: health(settings))
            elif path == "/api/bank/stats":
                self._dispatch(lambda: bank_stats(settings))
            else:
                self._send(404, {"detail": "not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            parts = path.strip("/").split("/")
            if path == "/api/exam/start":
                self._dispatch(lambda: start_exam(self._json_body(), settings))
            elif len(parts) == 4 and parts[:2] == ["api", "exam"] and parts[3] == "submit":
                self._dispatch(lambda: submit_exam(parts[2], self._json_body(), settings))
            else:
                self._send(404, {"detail": "not found"})

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(port=8000, settings=None, host="127.0.0.1"):
    settings = settings or Settings.from_env()
    return ThreadingHTTPServer((host, port), make_handler(settings))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    srv = serve(args.port)
    print(f"Lingo Easy dev server on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
