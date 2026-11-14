"""Adapters to skfolio 1.12.7 and ml4t-diagnostic 0.2.0; no local inference formulas.

API sources, conventions and limitations: docs/adr/data/m5-evaluation.md.
"""

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from ml4t.diagnostic.evaluation.stats import (
    compute_pbo,
    compute_return_statistics,
    compute_sharpe,
    deflated_sharpe_ratio_from_statistics,
)
from numpy.typing import NDArray
from skfolio.model_selection import CombinatorialPurgedCV


@dataclass(frozen=True)
class CVConfig:
    """Demonstration settings in observations; not calibrated holding horizons."""

    n_folds: int = 4
    n_test_folds: int = 2
    purged_size: int = 1
    embargo_size: int = 1


def aligned_returns(
    series: dict[str, dict[int, float]],
) -> tuple[list[int], NDArray[np.float64]]:
    """Require every trial on exactly the same timestamps; never fill or drop rows."""
    if len(series) < 2:
        raise ValueError("evaluation requires at least two parameter sets")
    timestamps = sorted(next(iter(series.values())))
    if not timestamps or any(sorted(values) != timestamps for values in series.values()):
        raise ValueError("all trials must have identical, nonempty timestamp histories")
    matrix = np.array([[values[t] for values in series.values()] for t in timestamps])
    if not np.isfinite(matrix).all():
        raise ValueError("returns must be finite; no trial or observation may be discarded")
    return timestamps, matrix


def evaluate_returns(
    series: dict[str, dict[int, float]], config: CVConfig | None = None
) -> dict[str, Any]:
    """Score fixed, prespecified candidates on purged train and held-out observations.

    DSR uses all columns as trials (raw K, no correlation discount). PBO is one
    selection diagnostic across candidates, using Sharpe scores for every CV split.
    No fitting occurs here; test-fold scores are a resampling diagnostic, not a
    walk-forward claim or independent trials. Every split is retained for audit.
    """
    config = config or CVConfig()
    timestamps, matrix = aligned_returns(series)
    names = list(series)
    moments = [compute_return_statistics(column) for column in matrix.T]
    variance = float(np.var([m[0] for m in moments], ddof=1))
    if not np.isfinite(variance) or variance <= 0:
        raise ValueError("DSR needs positive cross-trial Sharpe variance")
    cv = CombinatorialPurgedCV(**asdict(config))
    splits = []
    in_sample, out_of_sample = [], []
    for train, tests in cv.split(matrix):
        test = np.sort(np.concatenate(tests))
        if len(train) < 2 or len(test) < 2:
            raise ValueError("purging leaves too few observations for Sharpe")
        train_scores = [compute_sharpe(column[train]) for column in matrix.T]
        test_scores = [compute_sharpe(column[test]) for column in matrix.T]
        in_sample.append(train_scores)
        out_of_sample.append(test_scores)
        selected = int(np.argmax(train_scores))
        splits.append(
            {
                "train": train.tolist(),
                "tests": [indices.tolist() for indices in tests],
                "train_sharpe": train_scores,
                "test_sharpe": test_scores,
                "selected_set": names[selected],
                "selected_test_sharpe": test_scores[selected],
            }
        )
    ins, oos = np.array(in_sample), np.array(out_of_sample)
    if not np.isfinite(ins).all() or not np.isfinite(oos).all():
        raise ValueError("CV produced a nonfinite Sharpe; no split may be discarded")
    # Upstream uses argmax/argsort, not average ranks. Refuse ambiguous tied rankings.
    tied = any(len(np.unique(row)) != len(names) for row in np.concatenate((ins, oos)))
    pbo = (
        {"status": "unavailable", "reason": "tied CV scores make upstream PBO ranks ambiguous"}
        if tied
        else {"status": "ok", **compute_pbo(ins, oos).to_dict()}
    )
    ranking = np.argsort(-np.array([m[0] for m in moments])).tolist()
    sets = []
    for i, (sharpe, skew, kurtosis, rho, count) in enumerate(moments):
        dsr = deflated_sharpe_ratio_from_statistics(
            observed_sharpe=sharpe,
            n_samples=count,
            n_trials=len(names),
            variance_trials=variance,
            skewness=skew,
            excess_kurtosis=kurtosis - 3.0,  # upstream moments use Pearson, DSR uses Fisher
            autocorrelation=rho,
            periods_per_year=365,  # engine returns include inactive calendar days
        )
        sets.append(
            {
                "set": names[i],
                "rank": ranking.index(i) + 1,
                "sharpe": sharpe,
                "dsr": {
                    "probability": dsr.probability,
                    "deflated_sharpe": dsr.deflated_sharpe,
                    "expected_max_sharpe": dsr.expected_max_sharpe,
                    "is_significant": bool(dsr.is_significant),
                    "confidence_level": dsr.confidence_level,
                    "n_trials": dsr.n_trials,
                    "n_samples": dsr.n_samples,
                    "variance_trials": dsr.variance_trials,
                    "skewness": dsr.skewness,
                    "excess_kurtosis": dsr.excess_kurtosis,
                    "autocorrelation": dsr.autocorrelation,
                },
                "oos_sharpe": oos[:, i].tolist(),
                "oos_quantiles": dict(
                    zip(
                        ("min", "q25", "median", "q75", "max"),
                        np.quantile(oos[:, i], [0, 0.25, 0.5, 0.75, 1]).tolist(),
                        strict=True,
                    )
                ),
            }
        )
    return {
        "timestamps_ns": timestamps,
        "n_observations": len(timestamps),
        "n_trials": len(names),
        "cv": asdict(config),
        "splits": splits,
        "pbo": pbo,
        "sets": sets,
    }
