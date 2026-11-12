"""
Paper-only boundary for the IBKR lane. Own design (no upstream ships it).

The lane may start only when every check below holds. They run before the engine is loaded
and again after the run, and each one refuses on anything it does not recognise:

1. The IB Gateway's own settings file, ``~/Jts/jts.ini``, has ``tradingMode=p`` under
   ``[Logon]``. The Gateway writes it at login (seen on this machine: the file changed at the
   owner's Paper Trading login). No file, no key, a duplicate, or any other value refuses.
2. The Gateway installed under ``~/Jts/ibgateway`` is running and listens on exactly one TCP
   port, the paper port 4002 (read from ``/proc``). No Gateway, another port, or an extra
   port refuses.
3. The Gateway reports exactly one account, and its id has the paper form: a capital D,
   capital letters, then digits. That is a convention seen in this Gateway's paper login and
   in the examples of IBKR and NautilusTrader. It is not a documented guarantee: IBKR's API
   documentation says the API makes no difference between live and paper trading.
4. Only if the owner has created ``risk/boundary.contract.json``: the account is on its
   allowlist. The file is optional. When present it can only make the check stricter, and a
   file that is present but malformed refuses.

The lane connects to 127.0.0.1 on the paper port and nowhere else.

The allowlist holds SHA-256 hashes, which keeps the account id out of plain sight. It is
not a secret: an account id is short, so anyone holding the contract can recover it by
hashing every possible id. Treat the contract as if it held the id. No message raised
here contains an account id.

    uv run python -m meridian.boundary hash        # prompts for an account id, prints its hash
    uv run python -m meridian.boundary contract    # owner at a terminal: prints a contract
                                                   # for the account the Gateway reports
"""

from __future__ import annotations

import configparser
import getpass
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = REPO_ROOT / "risk" / "boundary.contract.json"
SCHEMA = "meridian.boundary/1"
# The Gateway runs inside this distro and listens on loopback only.
GATEWAY_HOST = "127.0.0.1"
# IB Gateway's default socket port for a paper login. Nothing widens this set.
PAPER_PORT = 4002
PAPER_PORTS = frozenset({PAPER_PORT})
# Where `deploy/wsl/setup.sh gateway` installs the Gateway, and the Gateway's settings file.
GATEWAY_DIR = Path.home() / "Jts" / "ibgateway"
JTS_INI = Path.home() / "Jts" / "jts.ini"
PAPER_TRADING_MODE = "p"
PROC = Path("/proc")
# Client id for the probe of the ``contract`` command; distinct from the lane's own clients.
CONTRACT_PROBE_CLIENT_ID = 1598
CONFIRM_WORD = "PAPER"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9]+")
# A capital D, then capital letters, then digits (check 3 in the module text).
_PAPER_FORM = re.compile(r"D[A-Z]*[0-9]+")
_TCP_LISTEN = "0A"


class BoundaryError(RuntimeError):
    """The lane must not start."""


@dataclass(frozen=True)
class IbkrBoundary:
    host: str
    port: int
    # None when the owner has no contract: checks 1 to 3 decide alone.
    paper_accounts_sha256: frozenset[str] | None


def account_hash(account_id: str) -> str:
    """SHA-256 of the account id exactly as the Gateway reports it, without whitespace."""
    return hashlib.sha256(account_id.strip().encode("utf-8")).hexdigest()


# --- check 4: the owner's optional contract ---------------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def load_contract(path: Path | None = None) -> IbkrBoundary:
    """The owner's contract if there is one, else no allowlist. Raises on any doubt."""
    path = CONTRACT_PATH if path is None else path
    if not os.path.lexists(path):
        return IbkrBoundary(host=GATEWAY_HOST, port=PAPER_PORT, paper_accounts_sha256=None)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, ValueError, RecursionError) as e:
        raise BoundaryError(f"boundary contract is unreadable: {path}") from e

    if not isinstance(raw, dict):
        raise BoundaryError("boundary contract is not a JSON object")
    if raw.get("schema") != SCHEMA:
        raise BoundaryError(f"boundary contract schema is not {SCHEMA!r}")
    if raw.get("mode") != "paper":
        raise BoundaryError('boundary contract mode is not "paper"')

    ibkr = raw.get("ibkr")
    if not isinstance(ibkr, dict):
        raise BoundaryError("boundary contract has no ibkr section")
    host = ibkr.get("gateway_host")
    port = ibkr.get("gateway_port")
    hashes = ibkr.get("paper_accounts_sha256")

    if not isinstance(host, str) or host != GATEWAY_HOST:
        raise BoundaryError(f"gateway_host is not {GATEWAY_HOST}")
    if type(port) is not int or port not in PAPER_PORTS:
        raise BoundaryError("gateway_port is not the IB Gateway paper port")
    if not isinstance(hashes, list) or not hashes:
        raise BoundaryError("paper_accounts_sha256 is missing or empty")
    for value in hashes:
        if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
            raise BoundaryError("paper_accounts_sha256 holds a value that is not a SHA-256 hash")

    return IbkrBoundary(host=host, port=port, paper_accounts_sha256=frozenset(hashes))


# --- check 1: the Gateway's own record of the login mode --------------------------------------


def gateway_trading_mode(path: Path | None = None) -> str:
    """The value of tradingMode under [Logon] in the Gateway's jts.ini. Raises if unclear.

    Only that one value is returned; the file can hold other things (such as a user name),
    and nothing else from it is kept or shown.
    """
    path = JTS_INI if path is None else path
    parser = configparser.ConfigParser(strict=True, interpolation=None)
    try:
        parser.read_string(path.read_text(encoding="utf-8"), source=str(path))
    except (OSError, UnicodeError, configparser.Error) as e:
        raise BoundaryError(f"cannot read the IB Gateway's settings file {path}") from e
    value = parser.get("Logon", "tradingMode", fallback=None)
    if value is None:
        raise BoundaryError("the IB Gateway's settings file has no tradingMode under [Logon]")
    return value


def require_paper_login(path: Path | None = None) -> None:
    if gateway_trading_mode(path) != PAPER_TRADING_MODE:
        raise BoundaryError(
            "the IB Gateway is not logged in to Paper Trading (jts.ini tradingMode is not p)"
        )


# --- check 2: the ports the Gateway listens on --------------------------------------------------


def _listening_ports_by_inode(proc: Path) -> dict[str, int]:
    """Socket inode -> port, for every listening TCP socket (IPv4 and, if present, IPv6)."""
    found: dict[str, int] = {}
    for name, required in (("tcp", True), ("tcp6", False)):
        table = proc / "net" / name
        try:
            lines = table.read_text(encoding="ascii").splitlines()
        except FileNotFoundError:
            if required:
                raise BoundaryError(f"cannot read {table}") from None
            continue
        except (OSError, UnicodeError) as e:
            raise BoundaryError(f"cannot read {table}") from e
        for line in lines[1:]:
            fields = line.split()
            try:
                local, state, inode = fields[1], fields[3], fields[9]
                port = int(local.rsplit(":", 1)[1], 16)
            except (IndexError, ValueError) as e:
                raise BoundaryError(f"unexpected line in {table}") from e
            if state == _TCP_LISTEN:
                found[inode] = port
    return found


def gateway_listen_ports(
    proc: Path | None = None, gateway_dir: Path | None = None
) -> frozenset[int]:
    """The TCP ports that processes of the installed IB Gateway listen on. Raises if none run."""
    proc = PROC if proc is None else proc
    gateway_dir = GATEWAY_DIR if gateway_dir is None else gateway_dir
    prefix = str(gateway_dir.resolve()) + os.sep
    listening = _listening_ports_by_inode(proc)
    try:
        entries = list(proc.iterdir())
    except OSError as e:
        raise BoundaryError(f"cannot list {proc}") from e
    gateway_running = False
    ports: set[int] = set()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            exe = os.readlink(entry / "exe")
        except OSError:
            continue  # the process has ended, or it belongs to another user
        if not exe.startswith(prefix):
            continue
        gateway_running = True
        try:
            fds = list((entry / "fd").iterdir())
        except OSError as e:
            raise BoundaryError("cannot read the IB Gateway's open sockets") from e
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue  # closed since the listing
            if target.startswith("socket:[") and target.endswith("]"):
                port = listening.get(target[len("socket:[") : -1])
                if port is not None:
                    ports.add(port)
    if not gateway_running:
        raise BoundaryError(f"the IB Gateway installed in {gateway_dir} is not running")
    return frozenset(ports)


def require_gateway_on_paper_port_only() -> None:
    ports = gateway_listen_ports()
    if ports != PAPER_PORTS:
        shown = ", ".join(str(p) for p in sorted(ports)) or "no port"
        raise BoundaryError(
            f"the IB Gateway listens on {shown}; the lane needs it to listen on the paper port only"
        )


def local_paper_checks(contract_path: Path | None = None) -> IbkrBoundary:
    """Checks 1, 2 and the optional contract. Reads local state only; no network."""
    bounds = load_contract(contract_path)
    require_paper_login()
    require_gateway_on_paper_port_only()
    return bounds


# --- check 3: the account the Gateway reports -----------------------------------------------


def single_paper_form_account(reported: Iterable[str]) -> str:
    """The one account the Gateway reports, if it has the paper form; else BoundaryError."""
    accounts = [a.strip() for a in reported if a and a.strip()]
    if not accounts:
        raise BoundaryError("the Gateway reported no account")
    if len(accounts) != 1:
        raise BoundaryError(
            f"the Gateway reported {len(accounts)} accounts; the lane needs exactly one"
        )
    account = accounts[0]
    # The engine's adapter treats a hyphen in the account specially. Letters and digits only.
    if not _ACCOUNT_ID.fullmatch(account):
        raise BoundaryError("the Gateway reported an account id of an unexpected form")
    if not _PAPER_FORM.fullmatch(account):
        raise BoundaryError("the Gateway reported an account id that is not of the paper form")
    return account


def allowed_account(reported: Iterable[str], boundary: IbkrBoundary) -> str:
    """Return the one account the lane may use, or raise BoundaryError."""
    account = single_paper_form_account(reported)
    allowlist = boundary.paper_accounts_sha256
    if allowlist is not None and account_hash(account) not in allowlist:
        raise BoundaryError("the account the Gateway reports is not on the paper allowlist")
    return account


# --- the owner's commands ------------------------------------------------------------------------


def contract_text(account_id: str) -> str:
    """The contract that allowlists exactly this account, as the owner would write it."""
    contract = {
        "schema": SCHEMA,
        "mode": "paper",
        "ibkr": {
            "gateway_host": GATEWAY_HOST,
            "gateway_port": PAPER_PORT,
            "paper_accounts_sha256": [account_hash(account_id)],
        },
    }
    return json.dumps(contract, indent=2) + "\n"


def _contract() -> int:
    """Print a contract for the account the Gateway reports, once the owner confirms it.

    The contract is optional. The owner's own shell writes the file
    (``> risk/boundary.contract.json``); this prints to stdout only. Prompts and the account
    id go to the terminal (stderr), never stdout. Without a person at a terminal it refuses,
    so a tool call cannot produce a contract.
    """
    if not _owner_at_terminal():
        print("REFUSED: the contract command needs the owner at a terminal", file=sys.stderr)
        return 2
    from meridian import ib_probe

    try:
        require_paper_login()
        require_gateway_on_paper_port_only()
        reported = ib_probe.managed_accounts(GATEWAY_HOST, PAPER_PORT, CONTRACT_PROBE_CLIENT_ID)
        account = single_paper_form_account(reported)
    except (BoundaryError, ib_probe.ProbeError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(
        f"The Gateway on {GATEWAY_HOST}:{PAPER_PORT} reports one account: {account}\n"
        "Check that the Gateway window says Paper Trading and that this is your paper "
        "account.\n"
        f"Type {CONFIRM_WORD} to print the contract for it: ",
        end="",
        file=sys.stderr,
        flush=True,
    )
    if _read_answer().strip() != CONFIRM_WORD:
        print("Not confirmed; nothing printed.", file=sys.stderr)
        return 2
    sys.stdout.write(contract_text(account))
    return 0


def _owner_at_terminal() -> bool:
    # stdout is redirected to the file, so the terminal is stdin and stderr.
    return sys.stdin.isatty() and sys.stderr.isatty()


def _read_answer() -> str:
    return sys.stdin.readline()


def _main(argv: list[str]) -> int:
    if argv == ["contract"]:
        return _contract()
    if argv != ["hash"]:
        print("usage: python -m meridian.boundary hash|contract", file=sys.stderr)
        return 2
    account_id = getpass.getpass("Paper account id (not echoed): ")
    if not account_id.strip():
        print("no account id given", file=sys.stderr)
        return 2
    print(account_hash(account_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
