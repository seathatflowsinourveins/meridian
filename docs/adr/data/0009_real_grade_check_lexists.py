"""Grading check: does load_contract() treat a contract it cannot stat as absent? python3 -I this.py CHECKOUT"""
import importlib.util, os, sys, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("boundary_under_test", Path(sys.argv[1]) / "meridian" / "boundary.py")
mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp) / "risk"; d.mkdir(); f = d / "boundary.contract.json"; f.write_text("not json", encoding="utf-8")
    try:
        mod.load_contract(f); print("readable folder, malformed contract: accepted")
    except mod.BoundaryError: print("readable folder, malformed contract: refused")
    os.chmod(d, 0)
    try:
        b = mod.load_contract(f); print("folder without search permission: treated as no contract, allowlist =", b.paper_accounts_sha256)
    except mod.BoundaryError: print("folder without search permission: refused")
    finally: os.chmod(d, 0o700)
