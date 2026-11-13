"""Local capture stub for one dsh run: record each provider request body, answer 401.

Usage: python3 -I capture_server.py PORT OUT_DIR LIFETIME_SECONDS

Listens on 127.0.0.1 only. Every POST body is written to OUT_DIR/req-<n>.json together with
the method, path and the names (never the values) of the request headers. The answer is an
Anthropic-style 401 error, so no model output is produced and nothing leaves the machine.
The process exits by itself after LIFETIME_SECONDS.
"""
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
LIFETIME = float(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
COUNT = [0]
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _record(self, body):
        with LOCK:
            COUNT[0] += 1
            n = COUNT[0]
        meta = {"method": self.command, "path": self.path, "header_names": sorted(self.headers.keys())}
        (OUT / f"req-{n:02d}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        (OUT / f"req-{n:02d}.body").write_bytes(body)

    def _answer(self, code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        self._record(body)
        self._answer(401, {"type": "error", "error": {"type": "authentication_error", "message": "local capture stub: no model"}})

    def do_GET(self):
        self._record(b"")
        self._answer(404, {"type": "error", "error": {"type": "not_found_error", "message": "local capture stub"}})

    def log_message(self, fmt, *args):
        sys.stderr.write("capture: " + (fmt % args) + "\n")


server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Timer(LIFETIME, server.shutdown).start()
server.serve_forever()
