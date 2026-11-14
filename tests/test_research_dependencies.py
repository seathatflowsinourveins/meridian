"""Synthetic, offline calls adapted from the upstream APIs cited in UPSTREAM.md.

Research installs by default; missing packages fail these tests, rather than skip.
Imports happen after the network guard. No provider client or SDK facade starts.
"""

import socket
from datetime import date
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def refuse(*args, **kwargs):
        raise AssertionError("research smoke tests must not connect to a service")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    # Edgar's import-time cache migration must only touch this test's directory.
    monkeypatch.setenv("EDGAR_LOCAL_DATA_DIR", str(tmp_path / "edgar"))
    monkeypatch.setenv("FINANCEDATABASE_CACHE_DIR", str(tmp_path / "finance"))


def test_polars_computes_a_replay_feature():
    import polars as pl

    result = (
        pl.DataFrame({"close": [100.0, 110.0, 99.0]})
        .lazy()
        .select(pl.col("close").pct_change().alias("return"))
        .collect()
    )
    assert result["return"].to_list() == [None, pytest.approx(0.1), pytest.approx(-0.1)]


def test_openbb_standardizes_offline_equity_reference_data():
    # openbb is a metapackage; its core models work without building the SDK,
    # loading user settings, or querying a data provider.
    from openbb_core.provider.standard_models.equity_info import (
        EquityInfoData,
        EquityInfoQueryParams,
    )

    query = EquityInfoQueryParams(symbol="example")
    row = EquityInfoData.model_validate(
        {"symbol": query.symbol, "sector": "Technology", "latest_filing_date": "2024-07-01"}
    )
    assert row.symbol == "EXAMPLE"
    assert row.sector == "Technology"
    assert row.latest_filing_date == date(2024, 7, 1)


def test_edgartools_filters_filings_available_at_a_cutoff():
    import pyarrow as pa
    from edgar import Filings

    filings = Filings(
        pa.table(
            {
                "form": ["10-K", "10-K", "10-Q"],
                "filing_date": [date(2024, 2, 1), date(2024, 3, 1), date(2024, 2, 1)],
                "company": ["Synthetic issuer"] * 3,
                "cik": [1] * 3,
            }
        )
    )
    available = filings.filter(form="10-K", filing_date=":2024-02-15")
    assert available.data.num_rows == 1
    assert available.data["filing_date"].to_pylist() == [date(2024, 2, 1)]


def test_financedatabase_selects_a_sector_universe(monkeypatch, tmp_path: Path):
    import financedatabase as fd
    import polars as pl
    from financedatabase import database_controller

    pl.DataFrame(
        {
            "symbol": ["EXAMPLE_A", "EXAMPLE_B", "EXAMPLE_C"],
            "sector": ["Technology", "Energy", "Technology"],
            "country": ["United States", "United States", "Canada"],
            "delisted": [False, False, False],
        }
    ).write_parquet(tmp_path / "equities.parquet")
    monkeypatch.setattr(database_controller, "COMPRESSION_PATH", tmp_path)
    equities = fd.Equities(use_local_location=True)
    selected = equities.select(country="United States", sector="Technology", as_pandas=False)
    assert isinstance(selected, pl.DataFrame)
    assert selected["symbol"].to_list() == ["EXAMPLE_A"]


def test_vectorbt_sweeps_indicator_windows():
    import pandas as pd
    import vectorbt as vbt

    # IndicatorFactory generates the result class at runtime.
    result: Any = vbt.MA.run(pd.Series([1.0, 2.0, 3.0, 4.0]), window=[2, 3])
    assert result.ma.iloc[-1].tolist() == [3.5, 3.0]


def test_skfolio_combinatorial_splits_purge_adjacent_labels():
    import numpy as np
    from skfolio.model_selection import CombinatorialPurgedCV

    cv = CombinatorialPurgedCV(n_folds=3, n_test_folds=2, purged_size=1)
    splits = list(cv.split(np.arange(24).reshape(12, 2)))
    assert len(splits) == 3
    assert [train.tolist() for train, _ in splits] == [[9, 10, 11], [5, 6], [0, 1, 2]]
    for train, tests in splits:
        test = np.concatenate(tests)
        assert len(test) == 8
        assert all(abs(int(a) - int(b)) > 1 for a in train for b in test)


def test_ml4t_deflates_sharpe_for_multiple_trials():
    import numpy as np
    from ml4t.diagnostic.evaluation.stats import deflated_sharpe_ratio

    rng = np.random.default_rng(42)
    trials = [rng.normal(mean, 0.01, 252) for mean in (0.0, 0.0001, 0.0002)]
    result = deflated_sharpe_ratio(trials)
    assert result.n_trials == 3
    assert 0 <= result.probability <= 1
    assert result.expected_max_sharpe > 0
    assert result.deflated_sharpe < result.sharpe_ratio


def test_pandera_rejects_invalid_replay_prices():
    import pandas as pd
    import pandera.pandas as pa

    schema = pa.DataFrameSchema({"close": pa.Column(float, pa.Check.gt(0))})
    valid = pd.DataFrame({"close": [100.0, 101.0]})
    pd.testing.assert_frame_equal(schema.validate(valid), valid)
    with pytest.raises(pa.errors.SchemaError):
        schema.validate(pd.DataFrame({"close": [0.0]}))


def test_exchange_calendars_knows_the_xnys_half_day():
    import exchange_calendars as xcals
    import pandas as pd

    calendar = xcals.get_calendar("XNYS", start="2024-01-01", end="2024-12-31")
    assert calendar.session_close("2024-11-29") == pd.Timestamp("2024-11-29T18:00:00Z")
    assert not calendar.is_session("2024-11-28")
