"""
Builds the execution client from node configuration, after the upstream template
(`examples/live/_template/factories.py` at NautilusTrader v2.0.0rc9): `create` returns a fresh
client and opens nothing. The SDK, the stream and the keys are built at connect.

M2's pacer reads the owner's control rows at connect and starts with no burst.
"""

from __future__ import annotations

from typing import Any, cast

from nautilus_trader.live.clients import ExecutionClientFactory
from nautilus_trader.model import AccountId, AccountType, OmsType

from .config import AlpacaPaperExecClientConfig
from .constants import VENUE
from .credentials import PaperKeys, load_paper_keys
from .execution import AlpacaPaperExecutionClient, Wiring
from .pacing import build_pacer
from .wire import PaperTradingClient, PaperTradingStream


def paper_stream(keys: PaperKeys) -> PaperTradingStream:
    """alpaca-py's trade-update stream, raw messages, pinned to the paper host."""
    return PaperTradingStream(keys.key_id, keys.secret_key)


def production_wiring(config: AlpacaPaperExecClientConfig) -> Wiring:
    timeout = config.request_timeout_secs
    return Wiring(
        keys=load_paper_keys,
        sdk=lambda keys: PaperTradingClient(keys.key_id, keys.secret_key, timeout_secs=timeout),
        stream=paper_stream,
        pacer=lambda now_ns: build_pacer(config.order_budget_rows_path, now_ns),
    )


def build_client(
    *,
    name: str,
    config: Any,
    cache: Any,
    clock: Any,
    trader_id: Any,
    wiring: Wiring | None = None,
    client_type: type[AlpacaPaperExecutionClient] = AlpacaPaperExecutionClient,
) -> AlpacaPaperExecutionClient:
    config = cast("AlpacaPaperExecClientConfig", config)
    if not isinstance(config, AlpacaPaperExecClientConfig):
        raise TypeError("expected AlpacaPaperExecClientConfig")
    return client_type(
        name=name,
        config=config,
        cache=cache,
        clock=clock,
        trader_id=trader_id,
        venue=VENUE,
        account_id=AccountId(config.account_id),
        account_type=AccountType.MARGIN,
        oms_type=OmsType.NETTING,
        wiring=wiring or production_wiring(config),
        house_prefix=config.house_prefix,
        universe=config.instrument_ids(),
        commission=config.commission(),
    )


class AlpacaPaperExecClientFactory(ExecutionClientFactory):
    """Registered under the client name ALPACA."""

    @staticmethod
    def create(*, name, config, cache, clock, trader_id) -> AlpacaPaperExecutionClient:
        return build_client(name=name, config=config, cache=cache, clock=clock, trader_id=trader_id)
