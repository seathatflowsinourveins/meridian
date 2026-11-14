# M5 evaluation harness: pinned APIs and the synthetic demonstration

Read and exercised 2026-11-14. No dependency added or updated. `uv sync --locked`
installed skfolio 1.12.7 and ml4t-diagnostic 0.2.0, verified with
`importlib.metadata.version`. The source and docstrings in the installed wheel were
read first; version-tagged public source and documentation were checked as follows.

## Sources actually read

- [skfolio 1.12.7 combinatorial splitter source and API docstrings](https://github.com/skfolio/skfolio/blob/v1.12.7/src/skfolio/model_selection/_combinatorial.py),
  installed as `skfolio/model_selection/_combinatorial.py`: `CombinatorialPurgedCV`,
  `split`, `get_path_ids` and `recombined_paths`.
  [Published API documentation](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)
  is unversioned; the installed pin governs this integration.
- [ml4t-diagnostic 0.2.0 statistical-test guide](https://github.com/ml4t/diagnostic/blob/v0.2.0/docs/user-guide/statistical-tests.md):
  aligned observations, retaining all candidates and supported statistics-based DSR;
  paired train/test performance matrices for PBO.
- Installed `ml4t/diagnostic/evaluation/stats/` modules, matching these tagged APIs:
  [deflated_sharpe_ratio.py](https://github.com/ml4t/diagnostic/blob/v0.2.0/src/ml4t/diagnostic/evaluation/stats/deflated_sharpe_ratio.py),
  [moments.py](https://github.com/ml4t/diagnostic/blob/v0.2.0/src/ml4t/diagnostic/evaluation/stats/moments.py),
  [backtest_overfitting.py](https://github.com/ml4t/diagnostic/blob/v0.2.0/src/ml4t/diagnostic/evaluation/stats/backtest_overfitting.py).
- NautilusTrader 2.0.0rc9 installed `backtest/__init__.pyi`: `BacktestResult.returns_series`
  is `dict[int, float]`. The existing native simulation's source and its
  [feature manifest](m5-native-sim.md) describe the node/catalog integration.

## API decisions

The splitter takes a chronological `(observations, candidates)` array and yields
training indices plus a list of held-out-fold index arrays. There are at least three
folds and at least two test folds, with fewer test folds than total folds. Purge removes
observations on both sides of test boundaries; embargo removes additional observations
after a test fold. Its `split` rejects purge plus embargo at least `floor(T / folds) - 1`.
The harness uses four folds, two test folds, one observation of purge and one of embargo
as visible demonstration defaults. CLI flags change these resampling inputs, not risk
settings. Train/test indices and each candidate's scores are recorded for every split.

`compute_return_statistics` supplies native-frequency sample Sharpe, skewness, Pearson
kurtosis, lag-one autocorrelation and sample count. DSR's statistics API takes **excess**
kurtosis, so the adapter subtracts three. It also receives raw `n_trials = len(SETS)` and
the sample variance (`ddof=1`) of Sharpe across **all** sets. The raw-returns DSR API picks
only the best candidate; using that independently on each column would silently use one
trial. We instead call `deflated_sharpe_ratio_from_statistics` for each column with the
same full K and variance, preserving the upstream 95% threshold. No effective-trial
correlation discount is used. Report both the corrected probability and the numerical
`deflated_sharpe` (observed minus expected maximum); they are distinct upstream fields.
All displayed research Sharpes are unannualized; engine statistics retain their own labels.

`compute_pbo` takes matching `(CV combinations, candidates)` performance matrices, not
raw returns or a trial count alone. We pass Sharpe on each purged training subset and
its concatenated held-out folds. Upstream selects the training maximum, ranks its held-out
score, and reports the fraction strictly below the median rank. This is one diagnostic
across the candidate set, not a separate PBO for each candidate. Upstream resolves ties
by array order: this adapter instead marks PBO unavailable with a reason when scores tie.
Malformed, unaligned, nonfinite, short or zero-variance series fail; no imputation,
observation deletion, candidate deletion or fold deletion can inflate significance.

## Simulation and output

`uv run python -m research.evaluate [--sessions 24 --folds 4 --test-folds 2 --purge 1 --embargo 1]`
uses `meridian.sim.runner.write_catalog` and `run_set` with the unchanged three `venue.SETS`.
A fresh BacktestNode runs each set once with its existing fixed fill-model seed. The
runner now exposes the engine's return dictionary directly, with no PnL reconstruction.
The original one-session simulation produced exactly one daily return in an offline probe:
it cannot support CV or DSR. The new optional `spacing_days` catalog argument places copies
of the existing scenarios seven calendar days apart, on the same weekday. Its default zero
preserves the original simultaneous-copy simulation. Each copy has distinct instrument IDs;
the bracket still occurs once at the beginning. The default evaluator's 24 copies yielded
162 calendar-day engine returns, including the engine's zero returns on inactive days.
No generated research noise is substituted for the engine's return values.

`runs/M5-evaluation-<uuid>/record.json` contains the source notice, library versions,
model inputs/seeds, engine statistics and returns for every set, CV configuration, exact
split indices, training/held-out scores, per-set held-out Sharpe distribution and quantiles,
per-set DSR fields and overall PBO. The catalog is in the same ignored folder. The terminal
shows a comparison table, PBO, sample/trial/split counts and full engine statistics. A
simulation scenario failure or invalid diagnostic input produces a nonzero exit and a
record explaining the failure. Output has no NaN/Infinity JSON literals.

## Scope of the evidence

These are repeated synthetic behavior scenarios, **not independent market samples**.
The default demonstration can return high corrected probabilities simply because the same
positive-return scenario repeats; it is not evidence of skill. Inactive-day zeros are
retained because the engine emitted them. No extra observations are invented by the evaluator.
Open positions and the engine's cash-account statistics have the limitations described in
[m5-native-sim.md](m5-native-sim.md). Changing costs can change the rank even without improving
cash PnL; no candidate is described as profitable. This command starts no lane.

Candidates are fixed before splitting; there is no estimator to refit. The distribution
is held-out **split scores**, not reconstructed independent backtest paths. CPCV can train
on dates later than a held-out block; it is not walk-forward validation. Purge sizes are
observation counts, not inferred holding horizons, and do not erase state already present
in a full-run return series. Evaluating a learned or tuned strategy would require a separate
fit/replay inside each fold and purge horizons justified by its labels and state. Any future
search must retain its complete trial history; today's K describes only the fixed simulation
sets in this one synthetic exercise, never earlier unrecorded experiments.

## Tests and gates

`tests/test_evaluation.py` uses seed 42, 1,024 observations and 64 noise trials: none passes
95% DSR (maximum probability about 0.153). A constructed 0.003 mean increment in the first
noise column makes it rank first, pass, win each training split and give PBO zero. That
number is solely a statistical test fixture, not a trading parameter. The best candidate's
statistics-based DSR is checked against upstream's raw-matrix API. Pure ranking reversal
has known PBO one; identical training/test rankings have PBO zero. Other tests verify purge
and embargo distances, held-out scores against direct mean/sample-standard-deviation,
rejected malformed data, ambiguous ties and unchanged engine return values.

The real module command runs twice with socket syscalls blocked using the native simulation's
existing seccomp bootstrap. Full records match despite distinct output directories; all
artifacts stay under `runs/`. Three captured native node results prove one run per set.
The upstream gate now scans `research/` as well as `meridian/` and `deploy/`, and its planted
unmapped-file case covers all three roots without removing any existing cases. The dependency
boundary forbids `research` imports from every `meridian/` module, including literal dynamic
imports. Ruff already scans all Python; pyright explicitly includes the new package.
