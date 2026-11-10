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

from .api import ApiError, Settings, bank_stats, health, start_exam, submit_exam

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

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
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
