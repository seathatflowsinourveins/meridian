"""Run `python -m research.evaluate`: synthetic simulation and upstream diagnostics.

Sources and rationale: docs/adr/data/m5-evaluation.md. Nothing connects to a service.
"""

import argparse
import json
from dataclasses import asdict
from importlib.metadata import version
from typing import Any
from uuid import uuid4

import numpy as np
from skfolio.model_selection import CombinatorialPurgedCV

from meridian import boundary
from meridian.sim import runner
from meridian.sim.venue import SETS
from research.metrics import CVConfig, evaluate_returns

NOTICE = (
    "SYNTHETIC DATA; placeholder parameter sets; repeated weekly scenarios. "
    "Diagnostics demonstrate wiring, not evidence of profitability or permission for a paper run."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=24, help="synthetic weekly scenario copies")
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--test-folds", type=int, default=2)
    parser.add_argument("--purge", type=int, default=1, help="observations on each test boundary")
    parser.add_argument(
        "--embargo", type=int, default=1, help="extra observations after test folds"
    )
    args = parser.parse_args(argv)
    if args.sessions < 4:
        parser.error("--sessions must be at least 4; one session has only one daily return")
    config = CVConfig(args.folds, args.test_folds, args.purge, args.embargo)
    # Validate configuration before creating the simulation catalog.
    try:
        list(
            CombinatorialPurgedCV(**asdict(config)).split(
                np.zeros(((args.sessions - 1) * 7 + 1, len(SETS)))
            )
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(NOTICE, flush=True)
    folder = boundary.REPO_ROOT / "runs" / f"M5-evaluation-{uuid4().hex}"
    folder.mkdir(parents=True)
    store = runner.write_catalog(folder, copies=args.sessions, spacing_days=7)
    runs = [runner.run_set(models, store, copies=args.sessions) for models in SETS]
    record: dict[str, Any] = {
        "schema": "meridian.evaluation-record/1",
        "notice": NOTICE,
        "data_source": "engine BacktestResult.returns_series; calendar-day returns including zeros",
        "sessions": args.sessions,
        "spacing_days": 7,
        "versions": {
            name: version(name) for name in ("nautilus_trader", "skfolio", "ml4t-diagnostic")
        },
        "simulation": runs,
    }
    failed = any(data["problems"] for data in runs)
    try:
        result = evaluate_returns({data["set"]: data["returns_series"] for data in runs}, config)
        record["evaluation"] = result
    except ValueError as exc:
        record["evaluation_error"] = str(exc)
        failed = True
        result = None
    if result:
        print(
            "set                     rank    Sharpe  OOS median [min, max]"
            "       Deflated  DSR prob  DSR >=95%"
        )
        for data in result["sets"]:
            q, dsr = data["oos_quantiles"], data["dsr"]
            print(
                f"{data['set']:<24} {data['rank']:>3} {data['sharpe']:>9.4f} "
                f"{q['median']:>8.4f} [{q['min']:.4f}, {q['max']:.4f}] "
                f"{dsr['deflated_sharpe']:>9.4f} "
                f"{dsr['probability']:>9.4f} {str(dsr['is_significant']):>10}"
            )
        pbo = result["pbo"]
        print(f"PBO across {len(SETS)} sets: {pbo.get('pbo', pbo.get('reason'))}")
        print(
            f"Trials: {result['n_trials']}; observations: {result['n_observations']}; "
            f"CPCV splits: {len(result['splits'])}; Sharpe is unannualized."
        )
    for data in runs:
        print(
            f"Engine statistics ({data['set']}): " + json.dumps(data["statistics"], sort_keys=True)
        )
        if data["problems"]:
            print("Simulation problems: " + "; ".join(data["problems"]))
    if "evaluation_error" in record:
        print(f"Evaluation unavailable: {record['evaluation_error']}")
    (folder / "record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print("FAIL" if failed else "PASS (synthetic harness only)")
    print(f"Evaluation record: {folder.relative_to(boundary.REPO_ROOT)}/record.json")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
