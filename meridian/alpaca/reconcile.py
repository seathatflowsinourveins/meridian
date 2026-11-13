"""
Startup reconciliation: what the engine is shown, what is withheld, and what refuses the start.

Own design, ported from `sextant-paper@a991b73a:src/sextant/alpaca/execution.py` (the report
generators and `execution_engine_config`), trimmed to M3. Each rule answers one way the
earlier line's attended starts failed (docs/m3-alpaca.md, section 2):

- A failed start must say why. NautilusTrader keeps only "Failed to get mass status", so each
  stage records its requests, rows and first failure (class, HTTP status, our own reason; never
  a venue body, an id, a price or a quantity) in `StageTrace`.
- Terminal history in a symbol outside the lane's universe is withheld and counted, not
  refused; a working order there (any leg, at any depth) refuses the start by symbol. A row
  whose symbol cannot be read is not known to be outside: it refuses.
- A working order outside the lane's client-order-id namespace means another writer is active:
  the start refuses. Its ended orders are history and count for nothing.
- The order listing is read whole (newest first, paged by `until` past the 500-row cap); a
  failed, non-contiguous or stalled page is incomplete coverage, never "no more orders".
- A historical fill is explained by a listed order holding at least its cumulative quantity.
  A fill older than the oldest listed order is counted, not refused; any other unexplained
  fill refuses.

The engine itself refuses a holding no order explains (`generate_missing_orders` off).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from alpaca.common.exceptions import APIError
from nautilus_trader.live import LiveExecutionEngineConfig, SubmissionRecoveryPolicy
from nautilus_trader.model import InstrumentId

from .budget import ActionKind
from .reports import TERMINAL, decimal_text, timestamp_ns
from .wire import NOT_JSON

ORDER_PAGE_LIMIT = 500  # alpaca-py 0.45.0 GetOrdersRequest: limit at most 500
FILL_PAGE_SIZE = 100  # account activities: page_size at most 100
# The longest any engine setting may let an order check wait before it acts on what the venue
# shows, in seconds. NautilusTrader 2.0.0rc9 itself accepts a startup delay of up to a day and
# any positive cadence, deferral threshold, query delay or missing-order retry count.
MAX_CHECK_WAIT_SECS = 60

Call = Callable[..., Awaitable[Any]]

OUTSIDE_UNIVERSE = "working order outside the lane's universe"
ANOTHER_WRITER = "working order of another writer"
UNMAPPABLE_WORKING = "working order the lane cannot map"
UNMAPPABLE_FILLED = "ended order the lane cannot map holds fills"
UNREADABLE_SYMBOL = "Alpaca row requires its symbol"

# The only texts a trace keeps, exactly: each is ours and names no symbol, id, price, quantity
# or venue word (the earlier line's prefix rule let a venue status word through, sextant#688).
# A message's variable part, if any, follows a colon and is dropped.
_REASONS = frozenset(
    {
        "historical fill that no order report explains",
        "order pages are not contiguous",
        "order page made no progress",
        "order listing needs more pages than its budget",
        "fill activity pages exceed their budget",
        OUTSIDE_UNIVERSE,
        ANOTHER_WRITER,
        UNMAPPABLE_WORKING,
        UNMAPPABLE_FILLED,
        UNREADABLE_SYMBOL,
        NOT_JSON,
        "Alpaca order page is not a list",
        "Alpaca fill page is not a list",
        "Alpaca positions are not a list",
        "Alpaca order legs are not a list",
        "Alpaca row instrument is not loaded",
        "Alpaca row does not match the loaded instrument",
        "Alpaca order report requires a simple US-equity order",
        "Alpaca order report requires an order without legs",
        "Alpaca order report requires its venue and client order ids",
        "Alpaca order report requires a known type, side and time in force",
        "Alpaca order report has inconsistent share quantities",
        "Alpaca order status requires classification",
        "Alpaca trailing stop requires exactly one offset",
        "Alpaca position report requires a US equity",
        "Alpaca position report requires a known side",
        "Alpaca position report has an inconsistent share quantity",
        "Alpaca position report has an invalid average entry price",
        "venue quantity exceeds instrument size precision",
        "venue price exceeds instrument price precision",
    }
)
# decimal_text and timestamp_ns name only our own field names before these endings.
_FIELD_ENDINGS = (
    " requires decimal text from the venue",
    " requires valid decimal text",
    " requires a finite decimal",
    " requires an RFC 3339 timestamp",
    " is not a valid timestamp",
)
_REFUSALS = (OUTSIDE_UNIVERSE, ANOTHER_WRITER, UNMAPPABLE_WORKING, UNMAPPABLE_FILLED)


class IncompleteCoverage(RuntimeError):
    """Some rows could not be read or mapped exactly: never a partial list, never absence."""

    def __init__(self, reports: list, failures: list[tuple[object, BaseException]]):
        self.reports, self.failures = reports, failures
        named = "; ".join(str(error) for _, error in failures if str(error).startswith(_REFUSALS))
        super().__init__(
            "Alpaca reconciliation coverage incomplete" + (f": {named}" if named else "")
        )


def reason_of(error: BaseException) -> str | None:
    """The fixed part of one of our own messages, or None: never a value, never venue text."""
    if not isinstance(error, ValueError):
        return None
    text = str(error).split(":", 1)[0]
    if text in _REASONS or text.endswith(_FIELD_ENDINGS):
        return text
    return None


@dataclass
class StageTrace:
    """One report stage's counts and first failure; values are never recorded."""

    requests: dict[str, int] = field(default_factory=dict)
    rows: int = 0
    withheld_unloaded: int = 0
    withheld_unmapped: int = 0
    before_order_history: int = 0
    stopped_at_order_history: bool = False  # older FILL pages were not read (see below)
    cancelled: bool = False  # another stage failed first and the engine stopped this one
    failures: int = 0
    first: str | None = None
    status: int | None = None
    reason: str | None = None

    def count_request(self, method: str, path: str) -> None:
        name = f"{method.upper()} " + ("/orders/{id}" if path.startswith("/orders/") else path)
        self.requests[name] = self.requests.get(name, 0) + 1

    def fail(self, error: BaseException) -> None:
        failures = error.failures if isinstance(error, IncompleteCoverage) else []
        first = failures[0][1] if failures else error
        self.failures = len(failures) or 1
        self.first = type(first).__name__
        status = getattr(first, "status_code", None) if isinstance(first, APIError) else None
        self.status = status if isinstance(status, int) else None
        self.reason = reason_of(first)


@contextmanager
def traced(trace: dict[str, StageTrace], stage: str):
    """The engine runs the stages concurrently and cancels the rest when one fails; a
    cancelled stage is marked as such, so the trace names only the stage that failed."""
    entry = trace[stage] = StageTrace()
    try:
        yield entry
    except asyncio.CancelledError:
        entry.cancelled = True
        raise
    except BaseException as exc:
        entry.fail(exc)
        raise


def engine_config(universe: Sequence[InstrumentId], **kwargs: Any) -> LiveExecutionEngineConfig:
    """The execution engine settings this lane needs, refusing ones that would hide a gap.

    NautilusTrader 2.0.0rc9 (`crates/live/src/execution/manager.rs`, read 2026-11-12):
    `check_inflight_orders` turns an order still pending cancel after its retries into a local
    cancel, though the venue may not have acted; its open-order check reads the venue instead.
    `RetainUnresolved` keeps a submission whose outcome is unknown rather than rejecting it.

    The settings returned are checked whatever was passed: in-flight checks off, open-order
    checks on at a positive cadence. The node runs a periodic check only for an interval above
    zero (`crates/live/src/node/mod.rs`, its run loop), so with neither, nothing would read an
    order whose answer or update was lost. The in-flight interval passed only sets the cadence
    when none is given; passing 0 for it needs an explicit one.

    A check that runs too late, or never acts, is no check either. No setting may make one wait
    more than MAX_CHECK_WAIT_SECS: the delay the node adds before the first periodic check
    (`reconciliation_startup_delay_secs`, same run loop), the cadence, the recent local
    activity under which a check defers an order (`open_check_threshold_ms`, `manager.rs`,
    `reconcile_open_order_reports`), the delay between targeted order queries, and the misses
    before an order absent from the listing is queried (retries times the cadence). A check
    may send at least one targeted query per cycle, and no order is filtered out of the checks.
    """
    scope = [str(instrument_id) for instrument_id in universe]
    if not scope:
        raise ValueError("reconciliation requires the lane's universe")
    if kwargs.get("reconciliation_lookback_mins") is not None:
        raise ValueError("reconciliation lookback must stay unbounded")
    retain = SubmissionRecoveryPolicy.RETAIN_UNRESOLVED
    if kwargs.setdefault("submission_recovery_policy", retain) != retain:
        raise ValueError("submission recovery must retain unresolved orders")
    interval = LiveExecutionEngineConfig(**kwargs).inflight_check_interval_ms
    kwargs["inflight_check_interval_ms"] = 0
    if interval:
        kwargs.setdefault("open_check_interval_secs", interval / 1000)
    for name in ("generate_missing_orders", "filter_position_reports"):
        if kwargs.pop(name, False):
            raise ValueError(f"{name} would hide a holding no order explains")
    if kwargs.pop("filter_unclaimed_external_orders", True) is not True:
        raise ValueError("unclaimed external orders must stay filtered")
    config = LiveExecutionEngineConfig(
        reconciliation=True,
        generate_missing_orders=False,
        filter_position_reports=False,
        filter_unclaimed_external_orders=True,
        reconciliation_instrument_ids=scope,
        **kwargs,
    )
    cadence = config.open_check_interval_secs
    # rc9's constructor also refuses a set interval that is not positive and finite; the lane's
    # rule does not rest on that.
    if config.inflight_check_interval_ms != 0 or cadence is None or not cadence > 0:
        raise ValueError("open-order checks must replace in-flight checks")
    waits = {
        "reconciliation_startup_delay_secs": config.reconciliation_startup_delay_secs,
        "open_check_interval_secs": cadence,
        "open_check_threshold_ms": config.open_check_threshold_ms / 1000,
        "single_order_query_delay_ms": config.single_order_query_delay_ms / 1000,
        "open_check_missing_retries": config.open_check_missing_retries * cadence,
    }
    for name, seconds in waits.items():
        if not seconds <= MAX_CHECK_WAIT_SECS:
            raise ValueError(f"{name} would let an order check wait over {MAX_CHECK_WAIT_SECS} s")
    if config.max_single_order_queries_per_cycle < 1:
        raise ValueError("max_single_order_queries_per_cycle would stop every targeted query")
    if config.filtered_client_order_ids:
        raise ValueError("filtered_client_order_ids would leave an order unchecked")
    return config


def parts(row: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """The order and every leg below it, at any depth (alpaca-py `Order.legs` is recursive)."""
    pending = [row]
    while pending:
        part = pending.pop()
        yield part
        legs = part.get("legs") or []
        if not isinstance(legs, list):
            raise ValueError("Alpaca order legs are not a list")
        pending.extend(legs)


def is_working(row: Mapping[str, Any]) -> bool:
    """True if the order or any of its legs has not ended (a missing status counts as working)."""
    return any(part.get("status") not in TERMINAL for part in parts(row))


def row_symbol(row: Mapping[str, Any]) -> str:
    """An order or position row's symbol, or ValueError. A row without one in text is not
    known to be outside the universe, so it is never withheld as such: it refuses, and after
    startup it is a gap. (alpaca-py 0.45.0 types `Order.symbol` as optional: an `mleg` order
    omits it at the top level, so such an order in the history refuses too.)"""
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError(UNREADABLE_SYMBOL)
    return symbol


def withheld_unloaded(row: Mapping[str, Any], loaded: Callable[[str], bool]) -> bool:
    """True for ended history in a symbol outside the universe; refuses a working one, and a
    row whose symbol cannot be read (`row_symbol`)."""
    symbol = row_symbol(row)
    if loaded(symbol):
        return False
    if is_working(row):
        raise ValueError(f"{OUTSIDE_UNIVERSE}: {symbol}")
    return True


def check_one_writer(row: Mapping[str, Any], prefix: str) -> None:
    client_id = row.get("client_order_id")
    house = bool(prefix) and isinstance(client_id, str) and client_id.startswith(prefix)
    if not house and is_working(row):
        raise ValueError(f"{ANOTHER_WRITER}: {row.get('symbol')}")


def unmappable_history(row: Mapping[str, Any]) -> bool:
    """True for ended history in the universe that no simple order report can carry: a
    `replaced` order, or one with legs or another order class, with no fill in any part. It
    cannot change the holding, so it is counted and skipped. Working, or holding fills, it
    refuses: the engine could not be shown what it did."""
    simple = row.get("order_class") in ("simple", "", None) and not row.get("legs")
    if simple and row.get("status") != "replaced":
        return False
    if is_working(row):
        raise ValueError(f"{UNMAPPABLE_WORKING}: {row.get('symbol')}")
    for part in parts(row):
        filled = part.get("filled_qty")
        if not isinstance(filled, str) or decimal_text(filled, "filled quantity") != 0:
            raise ValueError(f"{UNMAPPABLE_FILLED}: {row.get('symbol')}")
    return True


def merge_listings(*listings: Iterable[Any]) -> list:
    """Merge by venue id; a row without a string id stays, to fail at its own boundary."""
    keyed: dict[str, Any] = {}
    loose: list = []
    for row in (row for listing in listings for row in listing):
        key = row.get("id") if isinstance(row, Mapping) else None
        if isinstance(key, str):
            keyed[key] = row
        else:
            loose.append(row)
    return [*keyed.values(), *loose]


def until_covering(instant_ns: int) -> str:
    """An RFC 3339 `until` one microsecond past `instant_ns`, at the venue's microsecond grain."""
    seconds, micros = divmod(instant_ns // 1_000 + 1, 1_000_000)
    moment = datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=micros)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def list_orders(call: Call, params: Mapping[str, Any], *, max_pages: int) -> list:
    """GET /v2/orders whole, newest first, paging by `until` (submission time).

    Each next page must again hold the rows at the previous page's oldest instant and must add
    rows. alpaca-py 0.45.0 documents `until` only as "submitted until this timestamp", so the
    next page asks for one microsecond past that instant (`until_covering`): the edge rows come
    back whether the venue reads `until` as inclusive or exclusive. The earlier line passed the
    instant itself, which under an exclusive reading refuses every listing longer than a page.
    """
    query: dict[str, Any] = dict(params, limit=ORDER_PAGE_LIMIT, direction="desc")
    rows: dict[str, Any] = {}
    unkeyed: list = []
    edge: set[str] = set()
    for _ in range(max_pages):
        try:
            page = await call(ActionKind.QUERY, "get", "/orders", query)
        except Exception as exc:
            raise IncompleteCoverage([], [(None, exc)]) from exc
        if not isinstance(page, list):
            raise IncompleteCoverage([], [(None, ValueError("Alpaca order page is not a list"))])
        stamped: dict[str, tuple[int, Any]] = {}
        for row in page:
            try:
                stamped[row["id"]] = (timestamp_ns(row["submitted_at"], "submitted_at"), row)
            except Exception:
                unkeyed.append(row)
        if not edge <= set(stamped):
            raise IncompleteCoverage([], [(None, ValueError("order pages are not contiguous"))])
        fresh = {key: row for key, (_, row) in stamped.items() if key not in rows}
        rows.update(fresh)
        if len(page) < ORDER_PAGE_LIMIT:
            return [*rows.values(), *unkeyed]
        if not fresh:
            raise IncompleteCoverage([], [(None, ValueError("order page made no progress"))])
        instant = min(ns for ns, _ in stamped.values())
        edge = {key for key, (ns, _) in stamped.items() if ns == instant}
        query = dict(query, until=until_covering(instant))
    raise IncompleteCoverage(
        [], [(None, ValueError("order listing needs more pages than its budget"))]
    )


async def list_fill_activities(
    call: Call,
    params: Mapping[str, Any],
    *,
    max_pages: int,
    horizon_ns: int | None = None,
    trace: StageTrace | None = None,
) -> list:
    """GET /v2/account/activities/FILL newest first, paged by the last row's id.

    With `horizon_ns`, the oldest listed order's submission, paging stops after the first page
    that reaches fills older than it. No such fill can belong to a listed order, and
    `explain_fills` counts each one and refuses none, so older pages cannot change the outcome:
    start 3's 8,422 such fills cost 85 paced requests in the earlier line.
    """
    query: dict[str, Any] = dict(params, page_size=FILL_PAGE_SIZE, direction="desc")
    rows: list = []
    for _ in range(max_pages):
        page = await call(ActionKind.QUERY, "get", "/account/activities/FILL", query)
        if not isinstance(page, list):
            raise IncompleteCoverage([], [(None, ValueError("Alpaca fill page is not a list"))])
        rows.extend(page)
        if len(page) < FILL_PAGE_SIZE:
            return rows
        last = _stamp_or_none(page[-1]) if horizon_ns is not None else None
        if last is not None and horizon_ns is not None and last < horizon_ns:
            if trace is not None:
                trace.stopped_at_order_history = True
            return rows
        query = dict(query, page_token=page[-1]["id"])
    raise IncompleteCoverage([], [(None, ValueError("fill activity pages exceed their budget"))])


def _stamp_or_none(fill: Any) -> int | None:
    try:
        return timestamp_ns(fill.get("transaction_time"), "transaction_time")
    except AttributeError, ValueError:
        return None  # a malformed row is refused by explain_fills, never skipped here


def oldest_submission(orders: Sequence[Any]) -> int | None:
    """The submission time of the oldest listed order or leg: the venue's history horizon."""
    stamps = [
        timestamp_ns(part.get("submitted_at"), "submitted_at")
        for row in orders
        if isinstance(row, Mapping)
        for part in parts(row)
        if isinstance(part.get("id"), str)
    ]
    return min(stamps, default=None)


def explain_fills(
    fills: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
    trace: StageTrace,
    loaded: Callable[[str], bool],
) -> None:
    """Refuse unless every historical fill is explained by a listed order, or predates them.

    A FILL activity carries no stream execution id and no fee (the earlier line's reading of
    the account activities reference, 2026-11-11), so no fill report is built from it: the
    engine infers each fill an order report shows.
    """
    listed: dict[str, Mapping[str, Any]] = {}
    for row in orders:
        if isinstance(row, Mapping):
            for part in parts(row):
                if isinstance(part.get("id"), str):
                    listed[part["id"]] = part
    oldest = oldest_submission(orders)
    failures: list[tuple[object, BaseException]] = []
    for fill in fills:
        try:
            order = listed.get(fill.get("order_id"))  # type: ignore[arg-type]
            if order is None:
                stamp = timestamp_ns(fill.get("transaction_time"), "transaction_time")
                # Older than every listed order: the venue no longer lists its order. With no
                # listed order at all there is no such horizon, so the fill is unexplained.
                if oldest is not None and stamp < oldest:
                    trace.before_order_history += 1
                    continue
                raise ValueError("historical fill that no order report explains")
            if decimal_text(order.get("filled_qty"), "filled quantity") < decimal_text(
                fill.get("cum_qty"), "cumulative fill quantity"
            ):
                raise ValueError("historical fill that no order report explains")
            withheld_unloaded(order, loaded)  # the same terminal-only rule outside the universe
        except Exception as exc:
            failures.append((None, exc))
    if failures:
        raise IncompleteCoverage([], failures)
