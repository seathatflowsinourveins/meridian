"""A stand-in for the opening of an IB Gateway API session, for tests only."""

from __future__ import annotations

import contextlib
import socket
import struct
import threading
import time

NOTICE = ("4", "2", "-1", "2104", "Market data farm connection is OK")


def _frame(*fields: str) -> bytes:
    payload = ("\0".join(fields) + "\0").encode("utf-8")
    return struct.pack(">I", len(payload)) + payload


def _read_exact(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ConnectionError("client went away")
        data += chunk
    return data


def _read_frame(conn: socket.socket) -> bytes:
    (size,) = struct.unpack(">I", _read_exact(conn, 4))
    return _read_exact(conn, size)


class FakeGateway:
    """Serves the version handshake and, after START_API, a managed-accounts message.

    ``accounts`` is the comma-separated list to report; None reports nothing. The keyword
    switches each misbehave in one way, so that one guard in the probe can be tested.
    """

    def __init__(
        self,
        accounts: str | None,
        *,
        later_accounts: str | None = None,  # what sessions after the first report instead
        notice_before_answer: bool = False,  # a 5-field frame ahead of the handshake answer
        version_text: str | None = None,  # answer the handshake with this instead of a version
        bytewise: bool = False,  # send every byte in its own segment
        chatter_seconds: float = 0.0,  # after START_API, send other frames for this long
        malformed_accounts: bool = False,  # a managed-accounts frame with no account field
        oversize_frame: bool = False,  # answer the handshake with an absurd length header
        error_code: str | None = None,  # after START_API, send this error and hang up
    ) -> None:
        self.accounts = accounts
        self.later_accounts = later_accounts
        self.notice_before_answer = notice_before_answer
        self.version_text = version_text
        self.bytewise = bytewise
        self.chatter_seconds = chatter_seconds
        self.malformed_accounts = malformed_accounts
        self.oversize_frame = oversize_frame
        self.error_code = error_code

        self.handshakes: list[str] = []
        self.start_api: list[bytes] = []
        self.after_start_api = b""  # anything the first client sent after START_API
        self.client_gone = threading.Event()  # set when the first session has ended
        self.sessions = 0

        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(0.05)
        self.port: int = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> FakeGateway:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._server.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            index = self.sessions
            self.sessions += 1
            try:
                with conn, contextlib.suppress(OSError):
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self._session(conn, index)
            finally:
                self.client_gone.set()

    def _send(self, conn: socket.socket, data: bytes) -> None:
        if not self.bytewise:
            conn.sendall(data)
            return
        for i in range(len(data)):
            conn.sendall(data[i : i + 1])

    def _hold(self, conn: socket.socket, keep: bool) -> None:
        """Keep the connection open, as a real Gateway does, until the client leaves."""
        conn.settimeout(0.05)
        while not self._stop.is_set():
            try:
                data = conn.recv(4096)
            except TimeoutError:
                continue
            if not data:
                return
            if keep:
                self.after_start_api += data

    def _session(self, conn: socket.socket, index: int) -> None:
        if _read_exact(conn, 4) != b"API\0":
            return
        versions = _read_frame(conn).decode("ascii")  # "v100..176"
        self.handshakes.append(versions)
        if self.oversize_frame:
            self._send(conn, struct.pack(">I", (1 << 20) + 1))
            self._hold(conn, keep=False)
            return
        if self.notice_before_answer:
            self._send(conn, _frame(*NOTICE))
        client_max = int(versions.rsplit("..", 1)[1])
        self._send(conn, _frame(self.version_text or str(client_max), "20261112 12:00:00 EST"))

        self.start_api.append(_read_frame(conn))
        self._send(conn, _frame(*NOTICE))
        self._send(conn, _frame("9", "1", "1"))
        if self.error_code is not None:
            self._send(conn, _frame("4", "2", "-1", self.error_code, "refused"))
            return
        if self.chatter_seconds:
            end = time.monotonic() + self.chatter_seconds
            while time.monotonic() < end and not self._stop.is_set():
                self._send(conn, _frame("9", "1", "1"))
                time.sleep(0.05)
        elif self.malformed_accounts:
            self._send(conn, _frame("15", "1"))
        else:
            later = index > 0 and self.later_accounts is not None
            accounts = self.later_accounts if later else self.accounts
            if accounts is not None:
                self._send(conn, _frame("15", "1", accounts))
        self._hold(conn, keep=index == 0)
