"""
Venue identity and the one trading host. Paper only, hard-coded, with no switch.

alpaca-py 0.45.0 (`alpaca/common/enums.py`, `BaseURL.TRADING_PAPER` and
`BaseURL.TRADING_STREAM_PAPER`) names these two URLs. The adapter hands them to the SDK as
`url_override`. The runtime host guards in `wire.py` are the boundary. The source scans in
`tests/test_alpaca_paper.py` and `tests/test_paper_only.py` are tripwires for recognizable
hosts and switches; computed values and indirect calls can escape them.
"""

from nautilus_trader.model import Venue

VENUE = Venue("ALPACA")

# The only trading endpoints this package knows. Both are the paper ones.
PAPER_HOST = "paper-api.alpaca.markets"
PAPER_TRADING_URL = "https://paper-api.alpaca.markets"
PAPER_TRADE_STREAM_URL = "wss://paper-api.alpaca.markets/stream"

# Engine account ids for this venue are issued as "ALPACA-<tag>".
ACCOUNT_ISSUER = "ALPACA"

NOT_SUPPORTED = "not supported by the Alpaca paper lane (M3: plain DAY LIMIT orders only)"
