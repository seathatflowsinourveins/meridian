#!/usr/bin/env python3
"""Grading aid for task R4 (ADR 0009). Usage: python3 -I grade_aid.py CHECKOUT

Loads CHECKOUT/meridian/boundary.py and asks its gateway_trading_mode() about small settings
files written to a temporary folder. It reads no real Gateway file, connects to nothing and
runs no lane module. Prints one JSON object: what each fixture returns, or "refused".

The target defect of R4: at the task base a tradingMode that [Logon] only inherits from a
[DEFAULT] section is returned as [Logon]'s own; after the fix it is refused.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

KEY = "trading" + "Mode"
PAPER = "p"
OTHER = chr(108)  # any value that is not the paper value


def load(checkout: Path):
    spec = importlib.util.spec_from_file_location("boundary_under_test", checkout / "meridian" / "boundary.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


FIXTURES = {
    "logon_own_paper": f"[Logon]\n{KEY}={PAPER}\n",
    "inherited_from_default": f"[DEFAULT]\n{KEY}={PAPER}\n[Logon]\nother=1\n",
    "default_only_no_logon": f"[DEFAULT]\n{KEY}={PAPER}\n",
    "logon_own_other_default_paper": f"[DEFAULT]\n{KEY}={PAPER}\n[Logon]\n{KEY}={OTHER}\n",
    "logon_missing_key": "[Logon]\nother=1\n",
    "key_other_case": f"[Logon]\n{KEY.upper()}={PAPER}\n",
    "value_upper": f"[Logon]\n{KEY}={PAPER.upper()}\n",
    "value_padded": f"[Logon]\n{KEY} =  {PAPER}  \n",
    "value_with_inline_text": f"[Logon]\n{KEY}={PAPER} ;x\n",
    "colon_delimiter": f"[Logon]\n{KEY}: {PAPER}\n",
    "duplicate_key": f"[Logon]\n{KEY}={PAPER}\n{KEY}={PAPER}\n",
    "duplicate_section": f"[Logon]\n{KEY}={PAPER}\n[Logon]\nother=1\n",
    "section_other_case": f"[logon]\n{KEY}={PAPER}\n",
    "continuation_line": f"[Logon]\n{KEY}={PAPER}\n  x\n",
    "empty_file": "",
}


def main() -> int:
    checkout = Path(sys.argv[1]).resolve()
    mod = load(checkout)
    out: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in FIXTURES.items():
            f = Path(tmp) / f"{name}.ini"
            f.write_text(text, encoding="utf-8")
            try:
                value = mod.gateway_trading_mode(f)
                try:
                    mod.require_paper_login(f)
                    passes = True
                except mod.BoundaryError:
                    passes = False
                out[name] = {"value": value, "passes_check_1": passes}
            except mod.BoundaryError:
                out[name] = "refused"
        missing = Path(tmp) / "absent.ini"
        try:
            mod.gateway_trading_mode(missing)
            out["missing_file"] = "returned"
        except mod.BoundaryError:
            out["missing_file"] = "refused"
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
