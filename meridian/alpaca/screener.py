"""Read-only alpaca-py 0.45.0 ScreenerClient; endpoint evidence in UPSTREAM.md.

Start from the SDK's get_market_movers/get_most_actives request/model pattern.
Raw responses preserve JSON numbers before SDK float coercion; offline callers may
also supply the SDK's Movers/MostActives models. No order client or automatic loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic_ns, time_ns
from typing import Any

from alpaca.data.enums import MarketType, MostActivesBy
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.requests import MarketMoversRequest, MostActivesRequest

from .credentials import PaperKeys, load_paper_keys
from .screener_models import ScreenerRead, parse_screeners

DATA_URL = "https://data.alpaca.markets"
PATHS = ("/v1beta1/screener/stocks/movers", "/v1beta1/screener/stocks/most-actives")
# Basic data API: about-market-data-api, read 2026-11-13. Separate from trading.
DATA_REQUESTS_PER_MINUTE = 200
REQUEST_INTERVAL_NS = 60_000_000_000 // DATA_REQUESTS_PER_MINUTE


class DataReadBudget:
    """Share one per data credential among all REST readers in this process.

    No burst: >=300ms between attempts gives at most 200 in any half-open minute.
    A pair of screener reads needs >=600ms per cycle; callers schedule, never sleep
    here. Failed attempts count. Separate processes/readers must share admission
    externally; constructing another budget does not create another venue quota.
    """

    def __init__(self, now: Callable[[], int] = monotonic_ns):
        self._now = now
        self._next = 0
        self._lock = Lock()

    def admit(self) -> None:
        with self._lock:
            now = self._now()
            if now < self._next:
                raise ValueError("data read not due")
            self._next = now + REQUEST_INTERVAL_NS


class ReadOnlyScreener(ScreenerClient):
    """Pinned GET paths, no redirects/proxies/retries; each wire attempt is paced."""

    def __init__(self, keys: PaperKeys, budget: DataReadBudget):
        super().__init__(keys.key_id, keys.secret_key, raw_data=True, url_override=DATA_URL)
        self._retry = 0
        self._session.trust_env = False
        self._budget = budget

    def _one_request(self, method: str, url: str, opts: dict, retry: int) -> Any:
        if method != "GET" or url not in {DATA_URL + path for path in PATHS}:
            raise ValueError("unsupported screener endpoint")
        self._budget.admit()
        try:
            return super()._one_request(
                method, url, {**opts, "allow_redirects": False, "timeout": (10, 10)}, 0
            )
        except Exception:
            # Never carry request headers or venue bodies into an exception/report.
            raise RuntimeError("screener read failed; no automatic retry") from None


@dataclass(frozen=True)
class Received:
    body: Any
    read_at_ns: int


class ScreenerReader:
    """Two explicitly scheduled SDK reads; no background runner and no stale cache."""

    def __init__(self, sdk: Any, now: Callable[[], int] = time_ns):
        self._sdk, self._now = sdk, now

    def movers(self, top: int = 10) -> Received:
        if type(top) is not int or not 1 <= top <= 50:
            raise ValueError("movers top must be 1..50")
        body = self._sdk.get_market_movers(
            MarketMoversRequest(top=top, market_type=MarketType.STOCKS)
        )
        return Received(body, self._now())

    def actives(self, top: int = 10) -> Received:
        if type(top) is not int or not 1 <= top <= 100:
            raise ValueError("actives top must be 1..100")
        body = self._sdk.get_most_actives(MostActivesRequest(top=top, by=MostActivesBy.VOLUME))
        return Received(body, self._now())

    @staticmethod
    def combine(movers: Received, actives: Received) -> ScreenerRead:
        return parse_screeners(
            movers.body,
            actives.body,
            movers_read_at_ns=movers.read_at_ns,
            actives_read_at_ns=actives.read_at_ns,
        )


def build_screener(
    budget: DataReadBudget,
    *,
    keys: Callable[[], PaperKeys] = load_paper_keys,
    sdk: Callable[[PaperKeys, DataReadBudget], Any] = ReadOnlyScreener,
) -> ScreenerReader:
    return ScreenerReader(sdk(keys(), budget))
