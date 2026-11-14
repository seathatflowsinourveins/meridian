"""A simulated venue that mirrors the Alpaca paper lane as far as the engine can express it.

Upstream pattern (NautilusTrader v2.0.0rc9): `examples/backtest/model_configs_example.py:50-92`
(a cash venue with a fill model, a fee model and `StaticLatencyModel` in one
`BacktestVenueConfig`) and `docs/concepts/backtesting/fill-models.md:72-99`. The fee and
latency models are the engine's own; the fill model is a Python subclass of the engine's
`FillModel` (`fills.py`) for Alpaca paper's partial fills. The mirror:
`docs/adr/data/m5-native-sim.md`.

Alpaca's paper page (https://docs.alpaca.markets/us/docs/paper-trading, read 2026-11-14) says
paper fills match the NBBO when marketable and that paper does not account for slippage due
to latency or queue position. The slippage and latency here are therefore a stress beyond
the paper lane, with placeholder values, never calibrated ones (AGENTS.md: no tuned value).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nautilus_trader.backtest import BacktestVenueConfig
from nautilus_trader.execution import FixedFeeModel, StaticLatencyModel
from nautilus_trader.model import AccountType, BookType, Currency, Money, OmsType, OtoTriggerMode
from nautilus_trader.risk import RiskEngineConfig

from meridian.alpaca.commission import PAPER_US_EQUITY_COMMISSION

from .fills import ALPACA_PAPER_PARTIAL_RATE, PaperFillModel

PLACEHOLDER = "placeholder, uncalibrated: shows each model in the loop, not a tuned value"


def paper_commission() -> Money:
    """The repository's paper commission (zero USD per order), as the engine's Money."""
    c = PAPER_US_EQUITY_COMMISSION
    return Money.from_str(f"{c.decimal_text} {c.currency}")


@dataclass(frozen=True, kw_only=True, slots=True)
class VenueModels:
    """The venue's model inputs. Named fields, placeholder values; results go to runs/."""

    name: str
    provenance: str = PLACEHOLDER
    insert_latency_ns: int = 0
    cancel_latency_ns: int = 0
    prob_fill_on_limit: float = 1.0
    prob_slippage: float = 0.0
    random_seed: int = 0  # fixed: the fill model's draws repeat run to run
    partial_fill_rate: float = ALPACA_PAPER_PARTIAL_RATE  # Alpaca's stated rate, not tuned
    commission: Money = field(default_factory=paper_commission)
    max_order_submit_rate: str = "100/00:00:01"  # the engine's own default throttle
    cash_usd: int = 10_000_000
    order_budget: bool = True  # the lane's account pacer in front of each submit (`budget`)


# Several parameter sets for one command. Placeholders that make each model visible.
SETS = (
    VenueModels(name="frictionless"),
    VenueModels(
        name="latency-and-slippage",
        insert_latency_ns=100_000_000,
        cancel_latency_ns=100_000_000,
        prob_slippage=0.5,
        random_seed=7,
    ),
    VenueModels(name="with-fee", commission=Money.from_str("1.00 USD")),
)


def venue_config(models: VenueModels, venue: str) -> BacktestVenueConfig:
    return BacktestVenueConfig(
        name=venue,
        oms_type=OmsType.NETTING,  # one net position per symbol, as Alpaca's account
        account_type=AccountType.CASH,  # long only, no borrowing
        starting_balances=[f"{models.cash_usd} USD"],
        base_currency=Currency.from_str("USD"),
        book_type=BookType.L1_MBP,  # top of book from quotes, the lane's data
        allow_cash_borrowing=False,
        # Alpaca activates a bracket's exits once the entry "is completely filled" (orders
        # page, "Bracket Orders"); rc9's default PARTIAL releases them on the first part.
        oto_trigger_mode=OtoTriggerMode.FULL,
        # A new model per run: the engine keeps a Python model's state across runs.
        fill_model=PaperFillModel(
            prob_fill_on_limit=models.prob_fill_on_limit,
            prob_slippage=models.prob_slippage,
            partial_rate=models.partial_fill_rate,
            random_seed=models.random_seed,
        ),
        # charge_commission_once: one charge per order, however many partial fills.
        fee_model=FixedFeeModel(models.commission, charge_commission_once=True),
        latency_model=StaticLatencyModel(
            insert_latency_nanos=models.insert_latency_ns,
            cancel_latency_nanos=models.cancel_latency_ns,
        ),
    )


def risk_config(models: VenueModels) -> RiskEngineConfig:
    """The engine's risk engine, not bypassed, with its submit throttle."""
    return RiskEngineConfig(bypass=False, max_order_submit_rate=models.max_order_submit_rate)
