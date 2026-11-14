"""Start a language server with the git worktree root as its workspace (own design; ADR 0016).

DeepSeek Harness's stdio LSP provider (@deepseek-ai/dsh-lsp-stdio 0.2.2-rc.1) starts the server
in the session's current directory and sends that directory as `rootUri` and the one workspace
folder. After the agent enters a subdirectory, pyright would then take the subdirectory as its
project root and resolve none of the repository's imports. This shim, which setup.sh dsh
installs as ~/.dsh/lsp/dsh-lsp-root.py, starts the server and rewrites only the client's
`initialize` request so that its root is the worktree root. Every other byte passes unchanged,
and the server's output goes straight to the client.

Usage: python3 -I dsh-lsp-root.py ROOT COMMAND [ARG...]
"""

import contextlib
import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO


def read_message(stream: BinaryIO) -> tuple[bytes, bytes] | None:
    """One framed message as (header block, body), or None at the end of the stream."""
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        byte = stream.read(1)
        if not byte:
            return None
        header += byte
    length = next(
        int(line.split(b":", 1)[1])
        for line in header.split(b"\r\n")
        if line.lower().startswith(b"content-length:")
    )
    return header, stream.read(length)


def with_root(body: bytes, root: Path) -> bytes:
    """The body with an initialize request's root fields set to `root`; anything else as is."""
    try:
        message = json.loads(body)
    except ValueError:
        return body
    if not isinstance(message, dict) or message.get("method") != "initialize":
        return body
    params = message.setdefault("params", {})
    params["rootUri"] = root.as_uri()
    params["rootPath"] = str(root)
    params["workspaceFolders"] = [{"uri": root.as_uri(), "name": root.name}]
    return json.dumps(message, separators=(",", ":")).encode()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    root = Path(argv[0]).resolve()
    server = subprocess.Popen(argv[1:], stdin=subprocess.PIPE)
    signal.signal(signal.SIGTERM, lambda *_: server.terminate())
    assert server.stdin is not None
    try:
        while (message := read_message(sys.stdin.buffer)) is not None:
            header, body = message
            new = with_root(body, root)
            if new is not body:
                header = b"Content-Length: %d\r\n\r\n" % len(new)
            server.stdin.write(header + new)
            server.stdin.flush()
    except BrokenPipeError:
        pass
    finally:
        with contextlib.suppress(BrokenPipeError):
            server.stdin.close()
    return server.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
