"""Capture-only HTTP endpoint for the always-on probe (ADR 0011 measurement; reused unchanged for ADR 0012, second round).

Binds 127.0.0.1:<port>, records every request (method, path, headers with credential
headers redacted, raw body) under <outdir>, and answers 400 with an Anthropic-style
error body. There is no model behind it; it exists so dsh assembles and sends its first
Messages request without any API key or network access.

Usage: python3 -I capture_server.py <port> <outdir>
"""
import http.server
import json
import os
import sys
import threading

PORT = int(sys.argv[1])
OUT = sys.argv[2]
REDACT = {"x-api-key", "authorization", "cookie", "proxy-authorization"}
LOCK = threading.Lock()
COUNT = [0]


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read_body(self):
        length = self.headers.get("Content-Length")
        if length is not None:
            return self.rfile.read(int(length))
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            body = b""
            while True:
                line = self.rfile.readline().strip()
                size = int(line.split(b";")[0] or b"0", 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass
                    return body
                body += self.rfile.read(size)
                self.rfile.read(2)
        return b""

    def _handle(self):
        body = self._read_body()
        with LOCK:
            COUNT[0] += 1
            n = COUNT[0]
        headers = {k: ("<redacted>" if k.lower() in REDACT else v) for k, v in self.headers.items()}
        meta = {"n": n, "method": self.command, "path": self.path, "headers": headers,
                "body_bytes": len(body)}
        with open(os.path.join(OUT, f"req-{n:02d}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
        with open(os.path.join(OUT, f"req-{n:02d}.body"), "wb") as f:
            f.write(body)
        resp = json.dumps({"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "capture-only endpoint: request recorded, no model behind it"}}).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(resp)

    do_POST = do_GET = do_PUT = do_DELETE = do_HEAD = _handle

    def log_message(self, fmt, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
with open(os.path.join(OUT, "ready"), "w", encoding="utf-8") as f:
    f.write(str(os.getpid()))
server.serve_forever()
