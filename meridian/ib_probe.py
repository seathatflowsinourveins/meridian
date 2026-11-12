"""
Ask a running IB Gateway which accounts its session manages. Own design.

NautilusTrader's Interactive Brokers adapter (2.0.0rc9) never looks at the account list
the Gateway sends: it takes the configured account id on trust. This module reads that
list itself, before any engine is built, so ``meridian.boundary`` can check it.

It speaks only the opening of the TWS API socket protocol: the version handshake, then
START_API, after which the Gateway sends the managed-accounts message unprompted. It
sends nothing else. It cannot place, change or cancel an order.

Wire format (IBKR TWS API, see UPSTREAM.md): after the literal ``API\\0`` every message
is a 4-byte big-endian length followed by NUL-terminated text fields. Advertising at most
version 176 keeps the Gateway on that text framing.
"""

from __future__ import annotations

import socket
import struct
import time

_MIN_VERSION = 100
_MAX_VERSION = 176
_START_API = "71"
_ERROR = "4"
_MANAGED_ACCOUNTS = "15"
_MAX_FRAME = 1 << 20


class ProbeError(RuntimeError):
    """The Gateway could not be asked, or did not answer as expected."""


def _recv_exact(sock: socket.socket, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError("the Gateway did not answer in time")
        sock.settimeout(remaining)
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ProbeError("the Gateway closed the connection")
        data += chunk
    return bytes(data)


def _recv_fields(sock: socket.socket, deadline: float) -> list[str]:
    (size,) = struct.unpack(">I", _recv_exact(sock, 4, deadline))
    if size == 0 or size > _MAX_FRAME:
        raise ProbeError("the Gateway sent a frame of an unexpected size")
    payload = _recv_exact(sock, size, deadline).decode("utf-8", errors="replace")
    return payload.removesuffix("\0").split("\0")


def _frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


def _handshake(sock: socket.socket, deadline: float) -> None:
    sock.sendall(b"API\0" + _frame(f"v{_MIN_VERSION}..{_MAX_VERSION}".encode("ascii")))
    # The answer is the frame with exactly two fields: server version, connection time.
    # IBKR's own client skips anything that arrives before it; so does this, within reason.
    for _ in range(8):
        fields = _recv_fields(sock, deadline)
        if len(fields) == 2 and fields[0].isascii() and fields[0].isdigit():
            if not _MIN_VERSION <= int(fields[0]) <= _MAX_VERSION:
                raise ProbeError(
                    "the Gateway answered with a protocol version that was not offered"
                )
            return
    raise ProbeError("the Gateway did not answer the version handshake")


def _codes(errors: list[str]) -> str:
    codes = [c for c in errors if c.isascii() and c.isdigit()]
    return f" (Gateway error codes: {', '.join(codes)})" if codes else ""


def managed_accounts(host: str, port: int, client_id: int, timeout: float = 10.0) -> list[str]:
    """The account ids the Gateway's session manages, as the Gateway reports them.

    ``timeout`` bounds the whole call, not each read.
    """
    deadline = time.monotonic() + timeout
    errors: list[str] = []
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            _handshake(sock, deadline)
            start_api = "\0".join([_START_API, "2", str(client_id), ""]) + "\0"
            sock.sendall(_frame(start_api.encode("ascii")))
            while True:  # bounded by the deadline inside _recv_exact
                fields = _recv_fields(sock, deadline)
                if fields[0] == _ERROR and len(fields) >= 4:
                    errors.append(fields[3])
                elif fields[0] == _MANAGED_ACCOUNTS:
                    if len(fields) < 3:
                        raise ProbeError("the managed-accounts message was malformed")
                    return [a for a in fields[2].split(",") if a]
    except ProbeError as e:
        raise ProbeError(f"{e}{_codes(errors)}") from None
    except TimeoutError as e:
        raise ProbeError(f"the Gateway did not answer in time{_codes(errors)}") from e
    except OSError as e:
        raise ProbeError(f"cannot ask the Gateway at {host}:{port}: {e}{_codes(errors)}") from e
