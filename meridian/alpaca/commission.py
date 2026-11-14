"""What Alpaca's paper simulation charges a US-equity fill: zero USD.

Only for this paper lane; this models no cost of real trading. The scoped zero
uses the two statements below under the owner's delegated decision. The paper
page does not mention commissions; the separate commission page supplies that
statement and qualifies it for business-partner arrangements.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class CommissionSource:
    url: str
    date_read: date
    quote: str


@dataclass(frozen=True)
class PaperEquityCommission:
    decimal_text: str
    currency: Literal["USD"]
    sources: tuple[CommissionSource, CommissionSource]


PAPER_US_EQUITY_COMMISSION = PaperEquityCommission(
    decimal_text="0.00",
    currency="USD",
    sources=(
        CommissionSource(
            url="https://docs.alpaca.markets/us/docs/paper-trading",
            date_read=date(2026, 11, 13),
            # Exact introductory clause and the relevant item of its exclusion list.
            quote="Specifically, paper trading does not account for:\n* Regulatory fees",
        ),
        CommissionSource(
            url="https://alpaca.markets/support/commission-clearing-fees",
            date_read=date(2026, 11, 13),
            quote="In general, we do not charge a commission for trades.",
        ),
    ),
)
