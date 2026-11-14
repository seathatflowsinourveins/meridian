"""
The Alpaca paper lane's execution adapter (milestone M3). Own design, ported from the earlier
Sextant line and trimmed; see `docs/adr/data/m3-alpaca.md` and the register row in `UPSTREAM.md`.

Paper only: the one trading host is hard-coded in `constants.py`. Nothing in this package
places an order by itself. The engine does, in a run the owner starts and attends.
"""
