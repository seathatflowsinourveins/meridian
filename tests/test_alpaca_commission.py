"""The sourced paper fee can build a config without weakening missing-fee refusal."""

from datetime import date
from urllib.parse import urlsplit

import pytest

from meridian.alpaca.config import AlpacaPaperExecClientConfig


def paper_config() -> AlpacaPaperExecClientConfig:
    return AlpacaPaperExecClientConfig.for_paper_equities(
        account_id="ALPACA-test", house_prefix="test", universe=["AAPL.ALPACA"]
    )


def test_paper_equity_config_yields_zero_usd_commission():
    config = paper_config()
    commission = config.commission()
    assert commission is not None
    assert str(commission) == "0.00 USD"


def test_paper_equity_sources_are_dated_official_https_citations():
    from meridian.alpaca.commission import PAPER_US_EQUITY_COMMISSION

    fee = PAPER_US_EQUITY_COMMISSION
    assert fee.currency == "USD"
    assert len(fee.sources) == 2
    configured_source = paper_config().commission_source
    assert configured_source is not None
    for source in fee.sources:
        url = urlsplit(source.url)
        assert url.scheme == "https"
        assert url.hostname in {"alpaca.markets", "docs.alpaca.markets"}
        assert isinstance(source.date_read, date)
        assert source.date_read <= date.today()
        assert source.quote
        assert source.url in configured_source
        assert source.date_read.isoformat() in configured_source


@pytest.mark.parametrize("value", [None, "", "invalid", "NaN", "Infinity", "-0.01", "0.001"])
def test_paper_equity_config_still_refuses_missing_or_malformed_value(value):
    config = paper_config()
    config.commission_per_fill = value
    assert config.commission() is None


@pytest.mark.parametrize("source", [None, "", "not a citation"])
def test_paper_equity_config_still_refuses_missing_or_malformed_source(source):
    config = paper_config()
    config.commission_source = source
    assert config.commission() is None
