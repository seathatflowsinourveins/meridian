# M5: the engine's simulation features at the pin, layer by layer, and where each is used

Evidence for `meridian/sim/` (2026-11-14). Engine NautilusTrader 2.0.0rc9, tag `v2.0.0rc9`,
commit `da6b57aefdd62b44f675e434ffcfefca7f4025dd`. Every source path below is at that commit
(`https://github.com/nautechsystems/nautilus_trader/blob/da6b57ae.../<path>`), read from a
sparse clone of the tag; "stub" means the installed wheel's `nautilus_trader/<module>/__init__.pyi`,
the Python surface this repository uses. Nothing was answered from memory: each "in rc9" was
read in the source or stub, and each "used" is exercised by the test named.

States: **used**; **available, not used** (in rc9 and reachable from Python, not used here, with
the reason); **not in rc9**. No row needed "only on the development branch": every feature
looked for is either in the tag or absent from it.

Run it: `uv run python -m meridian.sim [--calendar ROWS.json]`. Tests: `tests/test_sim.py`
and, for the four rules closed on 2026-11-14 (partial fills, DAY expiry, calendar rows, the
order budget), `tests/test_sim_gaps.py` (all offline).

## The path

```
synthetic quote paths (template scenarios + one bracket path)      meridian/strategy_template/sim.py
  + InstrumentStatus from alpaca_sessions windows, + calendar rows   meridian/sim/catalog.py
    (rows written offline from exchange-calendars)                 research/xnys_calendar_rows.py
  -> ParquetDataCatalog (write_instruments/quote_ticks/statuses)   catalog.write
  -> BacktestDataConfig x2 -> BacktestRunConfig -> BacktestNode    meridian/sim/runner.py
       venue: cash, NETTING, L1, PaperFillModel(seed, 10% partial), FixedFeeModel(repo
              commission), StaticLatencyModel, OTO FULL, statuses meridian/sim/venue.py, fills.py
       risk:  RiskEngineConfig(bypass=False, max_order_submit_rate)
       strategies: GatedBreakout (template, OrderEmulator trailing stops), BracketProbe;
              PaperVenue: session rule, DAY expiry, M2 pacer      meridian/sim/strategies.py, budget.py
  -> BacktestResult + node reports + create_tearsheet -> runs/M5-sim-*/<set>/
  one node per parameter set (venue.SETS), disposed in turn
```

## Manifest

| Layer | What rc9 ships | Source at the tag | Upstream example | Here (module; test) or why not | State |
|---|---|---|---|---|---|
| High-level API | `BacktestNode(configs)`, `build`, `run -> list[BacktestResult]`, `add_strategy(run_id, instance)`, `add_strategy_from_config`, `add_actor`, `add_exec_algorithm`, `get_engine_cache`, `generate_*_report`, `dispose` | `crates/backtest/src/node.rs:55`; stub `backtest:165-199`; `docs/concepts/backtesting/apis-and-runs.md:125-187` | `docs/getting_started/backtest_high_level.py:205-261` | `runner.run_set`; every test in `test_sim.py` | used |
| Run, venue, data configs | `BacktestRunConfig` (venues, data, engine, chunk_size, start/end, `dispose_on_completion`), `BacktestVenueConfig` (35 fields), `BacktestDataConfig` (catalog, data_type, instrument_ids, time bounds, filter) | `crates/backtest/src/config.rs:449,814,1082`; stub `backtest:45-90,242-381` | `examples/backtest/model_configs_example.py:83-140` | `runner.run_config`, `venue.venue_config` | used |
| Importable strategy configs | `ImportableStrategyConfig` with `add_strategy_from_config` / `add_strategies_from_configs` | stub `backtest:189`, `trading` | `backtest_high_level.py:235-236` (comment), `add_builtin_strategy` at :242 | the template takes `TemplateParams` and a Python instance (`node.add_strategy`, stub `backtest:188`); an importable config would need a `StrategyConfig` subclass carrying every template field | available, not used |
| Parquet data catalog | `ParquetDataCatalog`: `write_instruments`, `write_quote_ticks`, `write_trade_ticks`, `write_bars`, `write_instrument_statuses`, `write_instrument_closes`, `query_*`; one instrument per write | stub `persistence:146-527`; `crates/persistence` | `backtest_high_level.py:121-176` | `catalog.write`; all engine tests read it through `BacktestDataConfig` | used |
| Streaming or chunked runs | node: `chunk_size` in `[1, 1_000_000]`; engine: `run(streaming=True)`, `clear_data`, `end` | `apis-and-runs.md:103-123,184-185`; `crates/backtest/src/engine.rs:673-690` | none in `examples/backtest/` | the synthetic data is ~400 quotes; one-shot load | available, not used |
| Several runs with different parameters | one run config per node (`validate_configs`: "Only one run config per BacktestNode"), so a fresh node per config; or `BacktestEngine.reset()` and `clear_strategies()` reusing loaded data | `crates/backtest/src/node.rs:427-433`; `apis-and-runs.md:268-334` | `apis-and-runs.md:287-306` (fresh nodes) | `runner.main` loops `venue.SETS`, one node each; `test_every_set_runs_the_template_and_the_bracket` | used (fresh nodes) |
| Fill models | `DefaultFillModel`, `BestPriceFillModel`, `OneTickSlippageFillModel`, `ProbabilisticFillModel`, `TwoTierFillModel`, `ThreeTierFillModel`, `LimitOrderPartialFillModel`, `SizeAwareFillModel`, `CompetitionAwareFillModel`, `VolumeSensitiveFillModel`, `MarketHoursFillModel`; Python `FillModel` subclass; `change_fill_model` | `crates/execution/src/models/fill.rs:290-1353`; stub `execution`; `docs/concepts/backtesting/fill-models.md:39-161` | `model_configs_example.py:50-54`; `fill-models.md:84-99` | `fills.PaperFillModel`, a Python `FillModel` subclass (`crates/execution/src/python/fill.rs:37-160`; fill-models.md "Custom fill models"): seeded touch and slip draws, so the engine's one-tick L1 slip stays (fill-models.md:177-189; `test_slippage_moves_the_fill_price`), and Alpaca paper's partial fills from its liquidity hook, asked on each LIMIT fill attempt (`matching_engine/mod.rs`, `determine_limit_fill_model_price_and_volume`); `test_partial_fills_happen_at_alpacas_rate_with_a_fixed_seed`. Not `LimitOrderPartialFillModel` (a fixed 5 units, fill.rs:841-920) nor `ProbabilisticFillModel` (ignores the slip draw for its own book, fill.rs:590-597) | used (Python subclass) |
| Latency models | `StaticLatencyModel(base, insert, update, cancel)`; Python `LatencyModel` subclass | `crates/execution/src/models/latency.rs:31,217`; `docs/concepts/backtesting/execution-flow.md:97-112` | `model_configs_example.py:75-80` | `venue.venue_config`; `test_latency_moves_the_fill_time` | used |
| Fee models | `FixedFeeModel(Money, charge_commission_once)`, `MakerTakerFeeModel`, `PerContractFeeModel`, `ProbabilityPriceFeeModel`, option fee models; Python `FeeModel` subclass | `crates/execution/src/models/fee.rs:32-569`; `apis-and-runs.md:180-182` | `model_configs_example.py:56-73` | `FixedFeeModel(paper_commission())`: the repository's zero from `meridian/alpaca/commission.py`, a fixed charge per order; `test_the_fee_model_changes_pnl_by_the_fee` | used |
| Book types, execution on quotes, trades, bars | `L1_MBP` (quotes and bars update the book), `L2_MBP`, `L3_MBO`; `trade_execution`, `bar_execution`, `bar_adaptive_high_low_ordering` | `docs/concepts/backtesting/data-and-venues.md:51-93`; `trade-execution.md`; `bar-execution.md:31-45` | `examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py`, `fx_ema_cross_audusd_bars_from_ticks.py` | L1 from quotes, the lanes' data; trades and bars: none in the synthetic data | used (L1 quotes); trades, bars available, not used |
| Queue position, liquidity consumption | `queue_position` (with `trade_execution`), `liquidity_consumption`, `order_priority_reset_policy` | `trade-execution.md:116-247`; `fill-prices-and-matching.md:137-205` | `trade-execution.md:141-170` (sandbox config) | both need recorded trades or depth; Alpaca paper fills ignore NBBO size and queue (paper page, below) | available, not used |
| Account types | `CASH`, `MARGIN`, `BETTING`; margin models; `allow_cash_borrowing`, `frozen_account` | `accounts-and-margin.md:38-122` | `model_configs_example.py:83-92` (cash) | `CASH`, `NETTING`, no borrowing, USD base | used |
| Reject and expiry | the venue rejects while the market is not open (`MarketStatus`); GTD orders expire (`expire_gtd_orders`); `reject_stop_orders`, `support_gtd_orders`, `use_reduce_only`; no DAY expiry in the simulated venue | `crates/execution/src/matching_engine/mod.rs:3351-3361,4714,7261` | none | rejection: `test_outside_every_session_the_venue_rejects_from_its_status_data`. DAY expiry, own: `strategies.PaperVenue` sets a time alert at the trade date's last session end for each accepted DAY order and cancels it if it rests; `test_a_resting_day_order_is_cancelled_at_the_days_end_and_gtc_is_not` | used (reject); DAY expiry own (not in rc9's venue) |
| Time in force, extended hours | `GTC IOC FOK GTD DAY AT_THE_OPEN AT_THE_CLOSE`; no extended-hours flag or per-session order-type rule | stub `model:8377-8393` | none | own: `strategies.refusal` (Alpaca: outside regular hours only LIMIT with DAY or GTC); `test_market_refused_outside_regular_hours_where_a_limit_is_accepted` | not in rc9 (own rule) |
| Instrument status and halts | `InstrumentStatus` data and `MarketStatusAction` (`TRADING`, `HALT`, `PAUSE`, `CLOSE`...) drive the matching engine's `MarketStatus`; strategies get `on_instrument_status` | `matching_engine/mod.rs:2632-2662`; stub `model:2408,8119` | `docs/tutorials/backtest_book_imbalance_betfair.md` | `catalog.status_events`, through the catalog; `test_session_statuses_follow_alpaca_sessions`, the Saturday test | used |
| Sessions or calendars | none: no exchange calendar or session type in the engine | searched stubs and `crates/backtest`, `crates/execution` | none | own: `meridian.alpaca_sessions` windows turned into statuses; with `--calendar`, Alpaca-shaped calendar rows move the edges and close a date without a row. `research/xnys_calendar_rows.py` writes the rows from `exchange-calendars` (research group, pinned) offline; no `meridian/` module imports it. `test_the_venue_rejects_on_the_holiday_and_after_the_early_close` | not in rc9 (own) |
| Order emulator, trailing stops, trigger types | `OrderEmulator` holds `TRAILING_STOP_*`, `STOP_*`, `LIMIT`, `*_IF_TOUCHED`, releases as LIMIT or MARKET; `TriggerType` (`BID_ASK`, `LAST_PRICE`, `MARK_PRICE`...) | `docs/concepts/orders/emulated.md:5-146`; `crates/execution/src/order_emulator/`, `trailing.rs:45-217` | `python/tests/strategies/acceptance.py:515-700` (`EMACrossTrailingStop`) | the template's `TRAILING_STOP_LIMIT`, `BID_ASK`; `test_the_trailing_stop_triggers_at_the_emulated_level` | used |
| Contingent orders | `OrderFactory.bracket` (OTO entry, OUO exits), OCO, OUO, `submit_order_list`, `oto_trigger_mode`, `support_contingent_orders`, `manage_contingent_orders` | `docs/concepts/orders/advanced.md:49-342`; stub `common:1571-1617`, `trading:572` | `examples/live/interactive_brokers/notebooks/bracket_order_example.py:68-115` | `strategies.BracketProbe` (LIMIT entry, LIMIT take-profit, STOP_MARKET stop, at the venue); the run's `problems` requires entry and take-profit filled, stop cancelled. `oto_trigger_mode=FULL`: with partial fills, rc9's default `PARTIAL` released the exits for the whole quantity after the first part and the cash account rejected them; Alpaca activates them once the entry "is completely filled" (orders page, "Bracket Orders"). Not in the lanes: their wire refuses contingent orders | used (sim only) |
| Execution algorithms | native `TwapAlgorithm` (`add_native_exec_algorithm`), Python `ExecutionAlgorithm` | `docs/concepts/execution/algorithms.md:10-60`; stub `backtest` `add_native_exec_algorithm` | `docs/getting_started/backtest_low_level.py` (TWAP) | the lanes send one order at a time of a few shares; slicing has no use yet | available, not used |
| Market exit, close all | `Strategy.market_exit`, `close_position`, `close_all_positions`, `cancel_all_orders` | `crates/trading/src/strategy/mod.rs:1222,1767`; stub `trading` | `docs/getting_started/quickstart.py`, `docs/tutorials/ema_cross.py` | the lanes do not close on stop (the owner inspects what is left); `market_exit` sends MARKET orders, refused by Alpaca outside regular hours | available, not used |
| Risk engine checks and throttles | precision, positive price, quantity bounds, notional limits, cash balance, reduce-only, GTD, submit and modify rate limits (default 100 a second), trading state `ACTIVE/REDUCING/HALTED` | `docs/concepts/execution/index.md:186-317`; `crates/risk/src/engine/mod.rs:205-320`, `config.rs:46-66` | `examples/backtest/crypto_ema_cross_with_binance_provider.py` (`RiskEngineConfig`) | `venue.risk_config` (not bypassed, `max_order_submit_rate`); `test_the_throttle_denies_above_its_rate`. `max_notional_per_order`: a size limit is the owner's. In front of it, as in the lane, M2's account pacer (own, `budget.py`) | used (checks, throttle) |
| Loaders and wranglers | `QuoteTickDataWrangler`, `TradeTickDataWrangler`, `BarDataWrangler`, book wranglers (Arrow record batches); `TestDataProvider` CSV loaders | stub `persistence:33,109-131,595,853`; `python/nautilus_trader/testkit/providers.py:111-131,470-556` | `docs/tutorials/backtest_fx_bars.py` | the generator builds `QuoteTick` directly; `TestDataProvider` downloads from GitHub outside a source checkout (providers.py:127) and has no US equity | available, not used |
| Bundled sample data for US equities | `test_data/large/itch_AAPL.XNAS_2019-01-30_deltas.metadata.json` (L3 deltas, 23.7 MB, fetched from `emi.nasdaq.com`, "Public market data from NASDAQ exchange"); `test_data/nautilus/arrow/depths.parquet` (one synthetic AAPL.XNAS row); no US-equity quotes, trades or bars | `test_data/large/`, `test_data/nautilus/README.md` | none | not usable offline: the ITCH file is a download and L3 depth; the depth row is a fixture | not in rc9 (usable form) |
| Synthetic generators | none for market data (fixtures and providers only) | stubs `testkit`, `persistence` | none | own: `meridian/strategy_template/sim.py` paths | not in rc9 (own) |
| Simulation modules | `SimulationModule` (Python subclass), `FXRolloverInterestModule`, `CfdSwapModule` | `docs/concepts/backtesting/simulation-modules.md`; stub `backtest:383-412,527-564` | none | no rollover or swap for cash equities; a module adjusts balances and cannot reject orders | available, not used |
| Actors | `Actor`/`DataActor`, `add_actor`, `add_actor_from_config`, built-in `DataTester` | `docs/concepts/actors.md`; stub `backtest:184-187`, `testkit:17` | `docs/concepts/actors.md:15-50` | nothing needs a non-trading component yet | available, not used |
| Several venues | several `BacktestVenueConfig` in one run, each with its models | `apis-and-runs.md:127-131` | `model_configs_example.py:82-140` (four venues) | one venue: the lane under test | available, not used |
| Analysis | `BacktestResult` (`stats_pnls`, `stats_returns`, `stats_general`, `returns_series`), node `generate_orders/fills/positions/account_report`, `create_tearsheet(result, node=, run_config_id=)` | `crates/analysis/src/statistics/`; stub `backtest:201-240`; `python/nautilus_trader/analysis/tearsheet.py:805-815` | `docs/getting_started/backtest_low_level.py` (tearsheet) | `runner.write_report`; `test_command_without_sockets_writes_engine_reports`. Reuses `meridian/strategy_template/report.py` (main, #52) for its dependency check and finite-value JSON; its `write_report` takes a `BacktestEngine`, so the node's run-id reports are written here. In a cash account `PnL (total)` is the change in USD balance, so shares still held at the end count as spent cash | used |
| Sandbox execution client | `SandboxExecutionClientConfig`: live data, the same simulated exchange; shares `book_type`, `fill_model`, `fee_model`, `latency_model`, `margin_model`, account type, OMS, `bar_execution`, `trade_execution`, `queue_position`, `liquidity_consumption`, `reject_stop_orders`, `support_contingent_orders`, `use_reduce_only`, `price_protection_points`, `order_priority_reset_policy`; lacks `modules`, routing, `allow_cash_borrowing`, liquidation | `crates/adapters/sandbox/src/config.rs:47-157` | `examples/live/sandbox/exec_tester.py:74-102` | the next task (attended): `venue.VenueModels` maps field for field onto it; status data come from the live feed there, so the session rule must sit in the strategy (as `refusal` does here) | available, not used |

## The Alpaca paper mirror

Read 2026-11-14: https://docs.alpaca.markets/us/docs/paper-trading ("Paper vs Live",
"Fill assumptions"), https://docs.alpaca.markets/us/docs/orders-at-alpaca ("Submitting an
Extended Hours Eligible Order", "Time in Force", "Bracket Orders") and
https://docs.alpaca.markets/us/docs/245-trading-for-trading-api (sessions, DAY orders, holidays).

| Alpaca paper | Here | Mirror or gap |
|---|---|---|
| Cash account in USD, long only in the lanes | `CASH`, `NETTING`, `allow_cash_borrowing=False` | mirror |
| Commission zero (`meridian/alpaca/commission.py`) | `FixedFeeModel(paper_commission())` | mirror; regulatory fees: neither |
| Fills only when marketable, at the NBBO | L1 book from quotes, `prob_fill_on_limit=1.0` | mirror |
| Quantity not checked against NBBO size | `liquidity_consumption=False` (default) | mirror |
| Partial fills of random size 10% of the time; a marketable remainder re-evaluated (paper page) | `fills.PaperFillModel`: a seeded draw on each LIMIT fill attempt, 1 to leaves - 1 shares | mirror (own subclass on rc9's hook) |
| No slippage due to latency, no queue position, no market impact | `prob_slippage` and latency placeholders | deliberate stress beyond paper |
| Outside regular hours: only LIMIT, DAY or GTC, extended-hours eligible | own `strategies.refusal` | mirror (own rule) |
| No trading outside 24/5 sessions; the NYSE holiday calendar, early closes (24/5 FAQ) | `InstrumentStatus` CLOSE from `alpaca_sessions` and calendar rows; venue rejects | mirror (rows from `exchange-calendars`; the half day's after-hours end, 17:00, is the script's assumption, below) |
| DAY orders cancelled after the close; extended-hours DAY at 8:00 PM ET (orders page, 24/5 FAQ) | `PaperVenue` cancels each resting DAY order at its trade date's last session end | mirror (own rule) |
| Request rate 200 a minute (`UPSTREAM.md`); the lane's own budget | M2's pacer, built by the lane's `build_pacer` from placeholder `PAPER_DEFAULT` rows, before each venue submit; then the engine's throttle | mirror (submits only: cancels, reads and emulator releases are not paced here) |

## Own code, and why

- `catalog.status_events`: rc9 has no calendar; it has status data the venue obeys.
- `strategies.refusal`: rc9 checks no order type against a session.
- `strategies.BracketProbe`: a strategy that sends one bracket (the factory is upstream's).
- `runner`: the wiring, the one-node-per-set loop and the report folder.
- `fills.PaperFillModel`: rc9 has no seeded random partial fill; it has the Python hook.
- `strategies.PaperVenue`: DAY expiry (rc9's venue expires only GTD) and the pacer hand-off;
  while the pacer holds an order the template sees it as its unresolved order.
- `budget`: placeholder rows in the lane's shape (`deploy/alpaca-order-budget.template.json`);
  the values are `meridian/order_budget/rows.py`'s fixture values, never reviewed ones.
- `research/xnys_calendar_rows.py`: XNYS sessions from `exchange-calendars`, plus Alpaca's
  04:00 and 20:00 extended edges. `exchange-calendars` has no after-hours end for a half day;
  the script takes the close plus four hours (17:00), the half-day row of
  `tests/test_alpaca_sessions.py`, to compare with Alpaca's calendar rows when a lane reads them.

## Socket check

`ParquetDataCatalog` starts the engine's tokio runtime, whose signal driver opens one
`AF_UNIX` socketpair on first use (tokio 1.54.1 `src/signal/unix.rs:68`; found by returning
`EPERM` for `socketpair` under seccomp: "failed to create UnixStream"). The suite's filter
(`tests/test_alpaca_sim.py`) traps both `socket` and `socketpair`, so the command test traps
`socket` from the start, creates that runtime, then adds the suite's filter unchanged. No
`socket` call happens at any point, and no `socket` or `socketpair` after the runtime starts.
