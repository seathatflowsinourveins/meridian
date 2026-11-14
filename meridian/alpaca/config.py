"""
The execution client's configuration. It names no credential and holds no key: the keys come
only from systemd credentials (`credentials.py`).

The subclass pattern (adapter fields as keyword arguments, common fields through `**kwargs`)
is NautilusTrader 2.0.0rc9's (`docs/developer_guide/python_adapters.md`, "Define adapter
configuration").
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from nautilus_trader.config import ExecutionClientConfig
from nautilus_trader.model import AccountId, InstrumentId, Money

from .commission import PAPER_US_EQUITY_COMMISSION
from .constants import ACCOUNT_ISSUER, VENUE

_COMMON_FIELDS = frozenset({"instrument_provider", "routing"})


class AlpacaPaperExecClientConfig(ExecutionClientConfig):
    """The engine account, the lane's order namespace and universe, and fee evidence.

    `commission_per_fill` is decimal text in USD and `commission_source` the official page it
    was read from. No Alpaca fill carries a fee, so without both the client refuses to connect
    rather than invent one (the earlier line's rule; see docs/adr/data/m3-alpaca.md).
    """

    def __init__(
        self,
        *,
        account_id: str,
        house_prefix: str,
        universe: list[str],
        commission_per_fill: str | None = None,
        commission_source: str | None = None,
        request_timeout_secs: float = 10.0,
        order_budget_rows_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        unknown = sorted(set(kwargs) - _COMMON_FIELDS)
        if unknown:
            raise TypeError(f"{type(self).__name__}() got unexpected keyword arguments {unknown}")
        account = AccountId(account_id)
        if account.value.split("-", 1)[0] != ACCOUNT_ISSUER:
            raise ValueError(f"account_id must be issued as {ACCOUNT_ISSUER}-<tag>")
        ids = [InstrumentId.from_str(value) for value in universe]
        if not ids or any(iid.venue != VENUE for iid in ids) or len(set(ids)) != len(ids):
            raise ValueError("universe must list distinct ALPACA instruments")
        if not 0 < float(request_timeout_secs) <= 60:
            raise ValueError("request_timeout_secs must be in (0, 60]")
        self.account_id = account.value
        self.house_prefix = str(house_prefix)
        self.universe = [str(iid) for iid in ids]
        self.commission_per_fill = commission_per_fill
        self.commission_source = commission_source
        self.request_timeout_secs = float(request_timeout_secs)
        self.order_budget_rows_path = order_budget_rows_path

    @classmethod
    def for_paper_equities(
        cls, *, account_id: str, house_prefix: str, universe: list[str], **kwargs: Any
    ) -> AlpacaPaperExecClientConfig:
        """Use this paper lane's sourced charge, which models no cost of real trading."""
        fee = PAPER_US_EQUITY_COMMISSION
        return cls(
            account_id=account_id,
            house_prefix=house_prefix,
            universe=universe,
            commission_per_fill=fee.decimal_text,
            commission_source="; ".join(
                f"{source.url} (read {source.date_read.isoformat()})" for source in fee.sources
            ),
            **kwargs,
        )

    def commission(self) -> Money | None:
        """The evidenced per-fill fee, or None when the evidence is missing or malformed."""
        value, source = self.commission_per_fill, self.commission_source
        if not isinstance(value, str) or not isinstance(source, str) or "https://" not in source:
            return None
        try:
            amount = Decimal(value)
        except InvalidOperation:
            return None
        if not amount.is_finite() or amount < 0 or amount != round(amount, 2):
            return None
        return Money.from_str(f"{amount:f} USD")

    def instrument_ids(self) -> list[InstrumentId]:
        return [InstrumentId.from_str(value) for value in self.universe]
