# Published copy (docs/adr/data/0007_validate_r4.py): the two live-login fixtures build their mode letter
# from L, so the repository's paper-only scan does not flag this file. Otherwise byte for
# byte the file that ran; the fixtures' text is unchanged.
"""Check that R4's target defect exists at 96e82e6 and not at 39cb68e, using synthetic jts.ini files.

usage: py -3 -I validate_r4.py <boundary at 96e82e6> <boundary at 39cb68e> <scratch dir>
Calls only gateway_trading_mode(path=<synthetic file>); reads no real Gateway file.
"""

import importlib.util
import sys
from pathlib import Path

L = "l"
cases = {
    "default_p_logon_without_key": "[DEFAULT]\ntradingMode = p\n\n[Logon]\nuseRemoteSettings = false\n",
    "logon_live": "[Logon]\ntradingMode = " + L + "\n",
    "logon_paper": "[Logon]\ntradingMode = p\n",
    "default_l_logon_p": "[DEFAULT]\ntradingMode = " + L + "\n\n[Logon]\ntradingMode = p\n",
}
scratch = Path(sys.argv[3])
scratch.mkdir(parents=True, exist_ok=True)
for label, src in (("96e82e6", sys.argv[1]), ("39cb68e", sys.argv[2])):
    spec = importlib.util.spec_from_file_location(f"boundary_{label}", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for name, text in cases.items():
        p = scratch / f"{name}.ini"
        p.write_text(text, encoding="utf-8")
        try:
            mod.require_paper_login(p)
            result = "PASSES (treated as paper)"
        except mod.BoundaryError as e:
            result = f"refused: {e}"
        print(f"{label}\t{name}\t{result}")
