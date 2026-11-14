# M4 screener universe

`alpaca/screener.py` follows installed alpaca-py 0.45.0's `ScreenerClient` requests;
`screener_models.py` parses raw JSON or SDK-shaped models without transport imports.
Sources below were read 2026-11-13; no service or account was contacted.

| Endpoint / source | Documented semantics |
|---|---|
| [Movers](https://docs.alpaca.markets/us/reference/movers-1) | GET `/v1beta1/screener/stocks/movers`; `top` 1–50 per direction, default 10. Real-time SIP, split-adjusted, exchange-tradable symbols; change compares previous and latest closing prices. `gainers`, `losers`, `market_type`, `last_updated`; each row has `symbol`, `price`, `change`, `percent_change`. Resets at market open; before then shows the previous market day's movers. |
| [Most-actives](https://docs.alpaca.markets/us/reference/mostactives-1) | GET `/v1beta1/screener/stocks/most-actives`; `top` 1–100, default 10; `by` volume (default) or trades. Real-time SIP. `most_actives` rows contain `symbol`, cumulative trading-day `volume` and `trade_count`; `last_updated` is computation time. The exact reset time and outside-hours update behavior are unspecified. |
| [Plans](https://docs.alpaca.markets/us/docs/about-market-data-api), [FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) | Paper accounts default to free Basic, 200 historical data requests/minute, IEX real-time equity coverage; regular users' REST data host is `data.alpaca.markets`. |

Neither endpoint page explicitly promises free Basic screener entitlement. Alpaca's
[discovery-tool guide](https://docs.alpaca.markets/us/docs/trading-api-mcp) lists both screeners
and says a free paper account suffices to start, but is not an endpoint entitlement table.
Thus free access to these SIP-derived lists is **unconfirmed**, not a reason to buy a plan;
a refused read fails without fallback. That guide was read only, with nothing installed.
The endpoint docs do not establish overnight screening under 24/5, nor current pre/after-hours
rankings. Those reads are retained as observations but authorize no entries. Calendar-aware
`alpaca_sessions.py` must identify the same regular session for computation, receipt and decision.

Selection is own design: intersect movers with volume-ranked actives, descending venue percent
change then symbol for ties; retain the original rank after filtering. Both directions may be
candidates, not entry signals. Require the lane's allowlist and already-read asset rows explicitly
marked active, tradable US equities ([Asset fields](https://alpaca.markets/sdks/python/api_reference/trading/models.html#asset)). Missing activity is unknown, not zero; daily cumulative
volume is a liquidity proxy, not executable depth. No advisory source is used.

Copy `deploy/alpaca-universe.template.json` to an owner-held local file and fill every null;
`UniverseParams.from_file` refuses missing/unknown/invalid fields. `min_price` is dollars,
`min_volume` shares traded that day, `max_symbols` the count cap, `max_age_ns` the maximum age
of both computations and receipts, and `provenance` identifies their source. Null placeholders
are the only deployment defaults; simulation numbers are synthetic and uncalibrated. A future
lane must respect its quote subscription cap too. No lane integration or entry rules here.

The caller schedules movers and actives separately, at least 300ms between wire attempts:
600ms minimum per pair, at most 200 attempts in any half-open minute. This is a ceiling derived
from Basic, not a recommended refresh cadence. Share `DataReadBudget` across all data REST
readers; other processes require shared admission too. Trading's order budget is separate.
Failures count, retries are disabled, early attempts refuse, redirects and environment proxies
are disabled. Every result records local completion time; venue computation time cannot backdate it.
`UniverseTimeline` replaces lists, including empty ones; a receipt at T serves only decisions >T.
The template simulation consumes these universes from synthetic responses (up to 100 symbols);
leaving a list prevents subsequent entries while existing positions retain protective exits.
