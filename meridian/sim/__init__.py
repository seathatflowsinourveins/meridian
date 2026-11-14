"""The end-to-end simulation on the pinned engine's own simulation features.

`uv run python -m meridian.sim [--copies N]`: synthetic quotes and session statuses written to
the engine's `ParquetDataCatalog`, replayed by its `BacktestNode` into a simulated venue with
its fill, fee and latency models and its risk engine, the strategy template on several
symbols plus one bracket, one node per parameter set, and the engine's own statistics, reports
and tearsheet. What the engine ships at the pin and where each piece is used:
`docs/adr/data/m5-native-sim.md`. No adapter, lane, network or broker data.
"""
