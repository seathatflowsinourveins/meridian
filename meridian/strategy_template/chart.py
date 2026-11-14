"""One self-contained chart page for a template simulation, drawn by TradingView Lightweight Charts.

Written by `sim.py --chart` next to the engine's report under `runs/`. The page embeds the
verbatim standalone build under `upstream/lightweight-charts/v5.2.1/` (README "Build
Variants": it defines `window.LightweightCharts`) and the run's data as JSON, so it opens from
the file system with no network. Per symbol: one-second candles of the bids the run used, a
marker at each fill from the engine's fills report, and the trailing stop's trigger level while
the emulated stop was held, which the template already records (`SymbolBook.triggers`). The
calls follow the library's own examples at v5.2.1 (`website/tutorials/how_to/series-markers.js`,
`price-line.js`): `addSeries`, `createSeriesMarkers`, `createPriceLine`. Synthetic data only.
"""

from __future__ import annotations

import html
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.model import InstrumentId, QuoteTick

from .strategy import SymbolBook

LIBRARY = Path(__file__).resolve().parents[2] / (
    "upstream/lightweight-charts/v5.2.1/lightweight-charts.standalone.production.js"
)
LIBRARY_TAG = b'<script id="lightweight-charts">'
NS = 1_000_000_000
UP, DOWN, TRAIL = "#26a69a", "#ef5350", "#f68410"  # the upstream examples' colours


def bars(bids: list[tuple[int, Decimal]]) -> list[dict[str, Any]]:
    """One candle per second of bids: the library's time is in whole seconds."""
    out: list[dict[str, Any]] = []
    for ts, bid in bids:
        second, value = ts // NS, float(bid)
        if out and out[-1]["time"] == second:
            bar = out[-1]
            bar["high"], bar["low"] = max(bar["high"], value), min(bar["low"], value)
            bar["close"] = value
        else:
            out.append({"time": second, "open": value, "high": value, "low": value, "close": value})
    return out


def trail(
    book: SymbolBook, bids: list[tuple[int, Decimal]], ends: Iterable[int]
) -> list[list[dict[str, Any]]]:
    """The trigger level at each quote while the emulated stop was held, one list per holding.

    A holding starts at the first recorded trigger and ends (exclusive) at the next release of
    the stop or sell fill. The last sample in each second is kept for the step line.
    """
    stops = sorted(set(ends))
    segments: list[list[dict[str, Any]]] = []
    changes = [(ts, Decimal(level)) for ts, level in book.triggers]
    i, level, end = 0, None, None
    for ts, _bid in bids:
        if end is not None and ts >= end:
            level, end = None, None
        if i < len(changes) and changes[i][0] <= ts:
            if level is None:
                segments.append([])
                end = next((s for s in stops if s > ts), None)
            while i < len(changes) and changes[i][0] <= ts:
                level = changes[i][1]
                i += 1
        if level is None:
            continue
        point = {"time": ts // NS, "value": float(level), "ts": ts, "level": format(level, "f")}
        segment = segments[-1]
        if segment and segment[-1]["time"] == point["time"]:
            segment[-1] = point
        else:
            segment.append(point)
    return segments


def marker(fill: Mapping[str, Any]) -> dict[str, Any]:
    entry = fill["side"] == "BUY"  # the template is long only: a buy enters, a sell exits
    return {
        "time": fill["ts"] // NS,
        "position": "atPriceMiddle",
        "price": float(fill["px"]),
        "shape": "arrowUp" if entry else "arrowDown",
        "color": UP if entry else DOWN,
        "text": f"{'entry' if entry else 'exit'} {fill['side']} {fill['qty']} @ {fill['px']}",
        **fill,
    }


def chart_data(
    ticks: Iterable[QuoteTick], books: Mapping[InstrumentId, SymbolBook], fills: Any
) -> list[dict[str, Any]]:
    """`fills` is the engine's own `generate_fills_report()` DataFrame."""
    bids: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
    for q in sorted(ticks, key=lambda q: q.ts_event):
        bids[str(q.instrument_id)].append((q.ts_event, q.bid_price.as_decimal()))
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fills.to_dict("records"):
        by_symbol[row["instrument_id"]].append(
            {
                "ts": int(row["ts_event"].value),
                "side": row["order_side"],
                "qty": row["last_qty"],
                "px": row["last_px"],
            }
        )
    out = []
    for iid, book in books.items():
        symbol = str(iid)
        symbol_fills = sorted(by_symbol[symbol], key=lambda f: f["ts"])
        sells = [f["ts"] for f in symbol_fills if f["side"] == "SELL"]
        segments = trail(book, bids[symbol], [*book.releases, *sells])
        held = book.phase.value == "holding" and segments and segments[-1]
        out.append(
            {
                "symbol": symbol,
                "summary": book.report(),
                "bars": bars(bids[symbol]),
                "markers": [marker(f) for f in symbol_fills],
                "trail": segments,
                "open_trail": segments[-1][-1]["value"] if held else None,
            }
        )
    return out


def statistics_rows(statistics: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    rows = []
    for currency, values in sorted(statistics.get("pnls", {}).items()):
        rows += [(f"PnL ({currency})", k, v) for k, v in sorted(values.items())]
    for group in ("returns", "general"):
        rows += [(group, k, v) for k, v in sorted(statistics.get(group, {}).items())]
    rows += [("totals", k, statistics[k]) for k in ("total_positions", "total_orders")]
    return [(g, k, "undefined" if v is None else json.dumps(v)) for g, k, v in rows]


SCRIPT = """
(() => {
  const run = JSON.parse(document.getElementById('run-data').textContent);
  const LC = window.LightweightCharts;
  const pick = (o, keys) => Object.fromEntries(keys.map(k => [k, o[k]]));
  for (const s of run.symbols) {
    const box = document.createElement('section');
    const title = document.createElement('h2');
    const r = s.summary;
    title.textContent = `${s.symbol}: ${r.phase}, entries ${r.entries}, exits ${r.exits}`;
    const el = document.createElement('div');
    el.className = 'chart';
    box.append(title, el);
    document.getElementById('charts').append(box);
    const chart = LC.createChart(el, {
      autoSize: true,
      timeScale: { timeVisible: true, secondsVisible: true },
    });
    const candles = chart.addSeries(LC.CandlestickSeries, {
      upColor: '__UP__', downColor: '__DOWN__', borderVisible: false,
      wickUpColor: '__UP__', wickDownColor: '__DOWN__', title: 'bid',
    });
    candles.setData(s.bars.map(b => pick(b, ['time', 'open', 'high', 'low', 'close'])));
    LC.createSeriesMarkers(candles, s.markers.map(
      m => pick(m, ['time', 'position', 'price', 'shape', 'color', 'text'])));
    for (const segment of s.trail) {
      const line = chart.addSeries(LC.LineSeries, {
        color: '__TRAIL__', lineWidth: 2, lineType: LC.LineType.WithSteps,
        lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
      });
      line.setData(segment.map(p => pick(p, ['time', 'value'])));
    }
    if (s.open_trail !== null) {
      candles.createPriceLine({
        price: s.open_trail, color: '__TRAIL__', lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: 'trail (open)',
      });
    }
    chart.timeScale().fitContent();
  }
  document.body.dataset.drawn = String(run.symbols.length);
})();
"""
for _token, _colour in (("__UP__", UP), ("__DOWN__", DOWN), ("__TRAIL__", TRAIL)):
    SCRIPT = SCRIPT.replace(_token, _colour)

STYLE = """
body { font: 14px system-ui, sans-serif; margin: 16px; color: #131722; background: #fff; }
.chart { height: 320px; margin-bottom: 24px; }
table { border-collapse: collapse; margin-bottom: 24px; }
td, th { border: 1px solid #d1d4dc; padding: 2px 8px; text-align: left; }
.key span { display: inline-block; width: 12px; height: 12px; margin: 0 4px 0 12px; }
"""


def page(symbols: list[dict[str, Any]], statistics: Mapping[str, Any]) -> bytes:
    library = LIBRARY.read_bytes()
    assert b"</script" not in library.lower()
    data = json.dumps({"symbols": symbols}, sort_keys=True, allow_nan=False)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    table = "".join(
        f"<tr><td>{html.escape(g)}</td><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>"
        for g, k, v in statistics_rows(statistics)
    )
    head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Template simulation chart</title>
<style>{STYLE}</style>
</head>
<body>
<h1>Strategy template: synthetic, uncalibrated simulation</h1>
<p>Synthetic quotes and fixture parameters: not observed prices, not a tuned strategy, not
evidence of any edge. Candles: bids per second. Markers: the engine's fills.</p>
<p class="key"><span style="background:{UP}"></span>entry (buy)
<span style="background:{DOWN}"></span>exit (sell)
<span style="background:{TRAIL}"></span>trailing stop trigger while held</p>
<h2>Engine statistics (undefined = the engine returned a non-finite value)</h2>
<table><tr><th>group</th><th>statistic</th><th>value</th></tr>{table}</table>
<div id="charts"></div>
<footer>Charts: TradingView Lightweight Charts&trade; 5.2.1, Copyright (c) 2025-2026
TradingView, Inc., Apache License 2.0, embedded unmodified from
upstream/lightweight-charts/v5.2.1/ (its LICENSE and NOTICE are there).</footer>
<script id="run-data" type="application/json">{data}</script>
"""
    tail = f"</script>\n<script>{SCRIPT}</script>\n</body>\n</html>\n"
    return head.encode() + LIBRARY_TAG + library + tail.encode()


def write_chart(
    folder: Path,
    ticks: Iterable[QuoteTick],
    books: Mapping[InstrumentId, SymbolBook],
    fills: Any,
    statistics: Mapping[str, Any],
) -> Path:
    out = folder / "chart.html"
    out.write_bytes(page(chart_data(ticks, books, fills), statistics))
    return out
