"""
Paper-only boundary for the IBKR lane. Own design (no upstream ships it).

The lane may start only when the IB Gateway it is about to use reports exactly one
account and that account is on the allowlist in ``risk/boundary.contract.json``.
Everything else refuses to start: a missing or malformed contract, a mode other than
"paper", a host other than 127.0.0.1, a port other than the Gateway paper port, no
account, more than one account, or an account that is not listed.

The allowlist holds SHA-256 hashes, which keeps the account id out of plain sight. It is
not a secret: an account id is short, so anyone holding the contract can recover it by
hashing every possible id. Treat the contract as if it held the id. No message raised
here contains an account id.

    uv run python -m meridian.boundary hash    # prompts for an account id, prints its hash
"""

from __future__ import annotations

import getpass
import hashlib
import json
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
# IB Gateway's default socket port for a paper login. The contract cannot widen this set.
PAPER_PORTS = frozenset({4002})
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9]+")


class BoundaryError(RuntimeError):
    """The lane must not start."""


@dataclass(frozen=True)
class IbkrBoundary:
    host: str
    port: int
    paper_accounts_sha256: frozenset[str]


def account_hash(account_id: str) -> str:
    """SHA-256 of the account id exactly as the Gateway reports it, without whitespace."""
    return hashlib.sha256(account_id.strip().encode("utf-8")).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def load_contract(path: Path | None = None) -> IbkrBoundary:
    """Read and validate the boundary contract. Raises BoundaryError on any doubt."""
    path = CONTRACT_PATH if path is None else path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except FileNotFoundError as e:
        raise BoundaryError(f"boundary contract not found: {path}") from e
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


def allowed_account(reported: Iterable[str], boundary: IbkrBoundary) -> str:
    """Return the one account the lane may use, or raise BoundaryError."""
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
    if account_hash(account) not in boundary.paper_accounts_sha256:
        raise BoundaryError("the account the Gateway reports is not on the paper allowlist")
    return account


def _main(argv: list[str]) -> int:
    if argv != ["hash"]:
        print("usage: python -m meridian.boundary hash", file=sys.stderr)
        return 2
    account_id = getpass.getpass("Paper account id (not echoed): ")
    if not account_id.strip():
        print("no account id given", file=sys.stderr)
        return 2
    print(account_hash(account_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
