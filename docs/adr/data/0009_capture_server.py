"""Loopback capture for one dsh always-on probe (ADR 0009 measurement).

Records every HTTP request it receives (method, path, non-secret headers, raw body) and
answers 401, so no model ever runs. It sees only what the harness would have sent to the
provider. Credential-bearing headers are never written, only their names.

usage: python3 -I capture_server.py PORT OUTDIR
"""
import http.server
import json
import pathlib
import socketserver
import sys

PORT = int(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
SECRET_HEADERS = {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization"}
COUNT = [0]


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _body(self):
        if (self.headers.get("transfer-encoding") or "").lower() == "chunked":
            parts = []
            while True:
                size = int(self.rfile.readline().strip().split(b";")[0] or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                parts.append(self.rfile.read(size))
                self.rfile.readline()
            return b"".join(parts)
        length = int(self.headers.get("content-length") or 0)
        return self.rfile.read(length) if length else b""

    def _handle(self):
        body = self._body()
        COUNT[0] += 1
        n = COUNT[0]
        record = {
            "n": n,
            "method": self.command,
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items() if k.lower() not in SECRET_HEADERS},
            "secret_header_names": sorted(k.lower() for k in self.headers.keys() if k.lower() in SECRET_HEADERS),
            "body_bytes": len(body),
        }
        (OUT / f"req-{n:02d}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
        (OUT / f"req-{n:02d}.body").write_bytes(body)
        payload = json.dumps({"type": "error", "error": {"type": "authentication_error", "message": "loopback capture, no model"}}).encode()
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    do_POST = _handle
    do_GET = _handle
    do_PUT = _handle

    def log_message(self, *args):
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as server:
    server.serve_forever()
