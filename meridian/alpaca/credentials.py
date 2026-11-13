"""
The paper keys reach the lane only as systemd credentials, never through the environment, a
config file, the command line or the repository.

systemd.exec(5) of systemd 259 (the distro's version): `LoadCredentialEncrypted=ID:PATH`
decrypts the file at start and places it, readable only by the unit's user, in the directory
named by `$CREDENTIALS_DIRECTORY`. The unit is `deploy/systemd/meridian-alpaca-paper.service`;
the files the owner fills are described in `docs/m3-alpaca.md`. No agent reads them.

Error messages name a credential, never its content.
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

KEY_ID = "alpaca-paper-key-id"
SECRET_KEY = "alpaca-paper-secret-key"
CREDENTIAL_NAMES = (KEY_ID, SECRET_KEY)

# Alpaca's key ids and secrets are short ASCII tokens; anything long is the wrong file.
_MAX_BYTES = 256


class PaperKeysUnavailable(RuntimeError):
    """The paper keys are not where the unit puts them; the lane refuses to start."""


@dataclass(frozen=True, slots=True)
class PaperKeys:
    key_id: str = field(repr=False)
    secret_key: str = field(repr=False)

    def __repr__(self) -> str:
        return "PaperKeys(<withheld>)"

    __str__ = __repr__


def load_paper_keys(environ: Mapping[str, str] = os.environ) -> PaperKeys:
    """Read both credentials from `$CREDENTIALS_DIRECTORY`, or refuse by name."""
    directory = environ.get("CREDENTIALS_DIRECTORY")
    if not directory:
        raise PaperKeysUnavailable(
            "no $CREDENTIALS_DIRECTORY: the paper keys are loaded only by the systemd unit "
            "deploy/systemd/meridian-alpaca-paper.service (see docs/m3-alpaca.md)"
        )
    base = Path(directory)
    return PaperKeys(_read(base, KEY_ID), _read(base, SECRET_KEY))


def _read(base: Path, name: str) -> str:
    path = base / name
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise PaperKeysUnavailable(f"credential {name} is missing") from None
    except OSError as exc:
        raise PaperKeysUnavailable(
            f"credential {name} cannot be read ({type(exc).__name__})"
        ) from None
    if len(data) > _MAX_BYTES:
        raise PaperKeysUnavailable(f"credential {name} is longer than {_MAX_BYTES} bytes")
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if not data or not data.isascii() or not all(0x21 <= byte <= 0x7E for byte in data):
        raise PaperKeysUnavailable(f"credential {name} is empty or not one printable token")
    return data.decode("ascii")


def main() -> int:
    """`python -m meridian.alpaca.credentials`: check the unit's credentials, offline.

    What the prepared unit runs until the lane's own entry point exists. It opens no socket and
    prints no value: only whether both credentials are present and well formed.
    """
    try:
        load_paper_keys()
    except PaperKeysUnavailable as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print("both Alpaca paper credentials are present and well formed (values not shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
