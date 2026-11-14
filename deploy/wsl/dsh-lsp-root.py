"""Start a language server with the git worktree root as its workspace (own design; ADR 0016).

DeepSeek Harness's stdio LSP provider (@deepseek-ai/dsh-lsp-stdio 0.2.2-rc.1) starts the server
in the session's current directory and sends that directory as `rootUri` and the one workspace
folder. After the agent enters a subdirectory, pyright would then take the subdirectory as its
project root and resolve none of the repository's imports. This shim, which setup.sh dsh
installs as ~/.dsh/lsp/dsh-lsp-root.py, starts the server and rewrites only the client's
`initialize` request so that its root is the worktree root. Every other byte passes unchanged,
and the server's output goes straight to the client.

Lifecycle: the shim's exit status is the server's (128 + N when signal N ended it), and the shim
exits as soon as the server does, even while the client keeps its input open (the provider waits
for that exit to finish shutdown or to notice a failed transport). The client's end of input, or
a header block with no Content-Length, closes the server's input and waits for its status.
SIGTERM terminates the server, then exits with its status.

Usage: python3 -I dsh-lsp-root.py ROOT COMMAND [ARG...]
"""

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO


class RawReader:
    """Reads file descriptor `fd` with os.read: no buffered object whose lock a blocked daemon
    thread could still hold when the interpreter exits."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.pending = b""

    def read(self, size: int) -> bytes:
        while len(self.pending) < size:
            chunk = os.read(self.fd, 65536)
            if not chunk:
                break
            self.pending += chunk
        data, self.pending = self.pending[:size], self.pending[size:]
        return data

    def read_header(self) -> bytes:
        while b"\r\n\r\n" not in self.pending:
            chunk = os.read(self.fd, 65536)
            if not chunk:
                return b""
            self.pending += chunk
        end = self.pending.index(b"\r\n\r\n") + 4
        header, self.pending = self.pending[:end], self.pending[end:]
        return header


def content_length(header: bytes) -> int | None:
    for line in header.split(b"\r\n"):
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def read_message(reader: RawReader) -> tuple[bytes, bytes] | None:
    """One framed message as (header block, body); None at the end of input or on a header block
    without a usable Content-Length."""
    header = reader.read_header()
    if not header:
        return None
    length = content_length(header)
    if length is None:
        return None
    return header, reader.read(length)


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


def forward(reader: RawReader, sink: IO[bytes], root: Path) -> None:
    """Copy the client's messages to the server until the client's input ends."""
    try:
        while (message := read_message(reader)) is not None:
            header, body = message
            new = with_root(body, root)
            if new is not body:
                header = b"Content-Length: %d\r\n\r\n" % len(new)
            sink.write(header + new)
            sink.flush()
    except BrokenPipeError, ValueError, OSError:
        pass  # the server's input closed: it is exiting, and main() waits for it
    finally:
        with contextlib.suppress(BrokenPipeError, ValueError, OSError):
            sink.close()


def exit_status(returncode: int) -> int:
    return 128 - returncode if returncode < 0 else returncode


def main(argv: list[str], fd: int = 0, exit_now: Callable[[int], object] = os._exit) -> int:
    if len(argv) < 2:
        print("usage: python3 -I dsh-lsp-root.py ROOT COMMAND [ARG...]", file=sys.stderr)
        return 2
    root = Path(argv[0]).resolve()
    started: list[subprocess.Popen[bytes]] = []
    # Installed before the server starts, so a SIGTERM at any moment reaches it.
    signal.signal(signal.SIGTERM, lambda *_: [process.terminate() for process in started])
    server = subprocess.Popen(argv[1:], stdin=subprocess.PIPE)
    started.append(server)
    assert server.stdin is not None
    threading.Thread(target=forward, args=(RawReader(fd), server.stdin, root), daemon=True).start()
    status = exit_status(server.wait())
    # The forwarding thread may still be blocked on the client's input: leave without joining it.
    sys.stderr.flush()
    exit_now(status)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
