"""Offline SDK-shaped screener data only; no credentials or services are accessed."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from alpaca.data.models.screener import MostActives, Movers
from alpaca.data.requests import MarketMoversRequest
from nautilus_trader.model import InstrumentId

from meridian.alpaca.credentials import PaperKeys
from meridian.alpaca.screener import (
    DATA_URL,
    PATHS,
    REQUEST_INTERVAL_NS,
    DataReadBudget,
    ReadOnlyScreener,
    ScreenerReader,
    build_screener,
    parse_screeners,
)
from meridian.alpaca.universe import UniverseParams, UniverseTimeline, select_universe
from meridian.alpaca_sessions import session_ns
from meridian.strategy_template import sim

NOW = sim.START_NS
WHEN = datetime.fromtimestamp(NOW // 1_000_000_000, UTC)
PARAMS = UniverseParams(
    provenance="synthetic, uncalibrated",
    min_price=Decimal(1),
    min_volume=100,
    max_symbols=3,
    max_age_ns=60_000_000_000,
)
CALENDAR = {
    date(2026, 11, 13): {
        "session_open": "0400",
        "open": "09:30",
        "close": "16:00",
        "session_close": "2000",
    }
}


def bodies(names=("AAA", "BBB"), *, when=WHEN):
    movers = {
        "gainers": [{"symbol": s, "price": 10, "change": 1, "percent_change": 10} for s in names],
        "losers": [],
        "market_type": "stocks",
        "last_updated": when,
    }
    actives = {
        "most_actives": [{"symbol": s, "volume": 1000, "trade_count": 10} for s in names],
        "last_updated": when,
    }
    return movers, actives


def read(names=("AAA", "BBB"), *, now=NOW):
    movers, actives = bodies(names, when=datetime.fromtimestamp(now / 1e9, UTC))
    return parse_screeners(
        Movers(**movers), MostActives(**actives), movers_read_at_ns=now, actives_read_at_ns=now
    )


def universe(reading=None, *, params=PARAMS, allowed=None, assets=None, calendar=CALENDAR):
    reading = reading or read()
    names = [c.symbol for c in reading.candidates]
    return select_universe(
        reading,
        params,
        allowed_symbols=frozenset(names if allowed is None else allowed),
        assets=assets
        if assets is not None
        else {
            s: {"symbol": s, "class": "us_equity", "status": "active", "tradable": True}
            for s in names
        },
        calendar=calendar,
    )


def test_ranking_is_venue_percent_then_symbol_and_both_times_are_kept():
    movers, actives = bodies(("BBB", "AAA", "CCC"))
    movers["gainers"][2]["percent_change"] = 20
    reading = parse_screeners(movers, actives, movers_read_at_ns=NOW, actives_read_at_ns=NOW + 1)
    assert [(c.symbol, c.rank) for c in reading.candidates] == [("CCC", 1), ("AAA", 2), ("BBB", 3)]
    assert reading.read_at_ns == NOW + 1
    assert reading.movers_updated_ns == NOW
    assert reading.candidates[0].volume == 1000


def test_strict_receipt_order_and_replacement_including_empty_lists():
    first = universe(read(("AAA", "BBB")))
    second = universe(read(("BBB",), now=NOW + 10))
    empty = universe(read((), now=NOW + 20))
    timeline = UniverseTimeline((first, second, empty))
    assert timeline.at(NOW - 1) == timeline.at(NOW) == ()
    assert [c.symbol for c in timeline.at(NOW + 10)] == ["AAA", "BBB"]
    assert [c.symbol for c in timeline.at(NOW + 11)] == ["BBB"]
    assert timeline.at(NOW + 21) == ()
    with pytest.raises(ValueError, match="strictly increasing"):
        UniverseTimeline((second, first))


def test_price_volume_allowlist_and_cap_are_all_required():
    reading = read(("AAA", "BBB", "CCC"))
    assert [c.symbol for c in universe(reading, allowed={"BBB"}).at(NOW + 1)] == ["BBB"]
    assert universe(reading, params=replace(PARAMS, min_price=Decimal(11))).at(NOW + 1) == ()
    assert universe(reading, params=replace(PARAMS, min_volume=1001)).at(NOW + 1) == ()
    assert len(universe(reading, params=replace(PARAMS, max_symbols=1)).at(NOW + 1)) == 1
    movers, actives = bodies()
    actives["most_actives"] = []
    unknown = parse_screeners(movers, actives, movers_read_at_ns=NOW, actives_read_at_ns=NOW)
    assert unknown.candidates[0].volume is None
    assert universe(unknown, params=replace(PARAMS, min_volume=0)).at(NOW + 1) == ()


@pytest.mark.parametrize(
    "change",
    [
        {"tradable": False},
        {"tradable": "true"},
        {"status": "inactive"},
        {"class": "crypto"},
        {"symbol": "BBB"},
    ],
)
def test_asset_permission_is_explicit(change):
    asset = {"symbol": "AAA", "class": "us_equity", "status": "active", "tradable": True}
    assert universe(read(("AAA",)), assets={"AAA": asset | change}).at(NOW + 1) == ()
    assert universe(read(("AAA",)), assets={}).at(NOW + 1) == ()


@pytest.mark.parametrize("hour,session", [(2, "overnight"), (8, "pre_market"), (18, "after_hours")])
def test_245_nonregular_reads_are_unknown_and_cannot_admit(hour, session):
    from meridian.alpaca_sessions import NEW_YORK

    when = datetime(2026, 11, 13, hour, tzinfo=NEW_YORK)
    now = int(when.timestamp()) * 1_000_000_000
    current = session_ns(now, CALENDAR)
    assert current is not None and current.name == session
    snapshot = universe(read(now=now))
    assert snapshot.read.candidates  # the response is retained, not labelled current
    assert snapshot.at(now + 1) == ()
    assert snapshot.at(NOW + 1) == ()


def test_stale_future_and_wrong_session_inputs_do_not_authorize_entries():
    assert universe().at(NOW + PARAMS.max_age_ns + 1) == ()
    assert universe(calendar={}).at(NOW + 1) == ()
    old = replace(read(), movers_updated_ns=NOW - PARAMS.max_age_ns)
    assert universe(old).at(NOW + 1) == ()
    movers, actives = bodies(when=WHEN.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone"):
        parse_screeners(movers, actives, movers_read_at_ns=NOW, actives_read_at_ns=NOW)
    with pytest.raises(ValueError, match="computation time"):
        parse_screeners(*bodies(), movers_read_at_ns=NOW - 1, actives_read_at_ns=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("price", 0),
        ("price", "NaN"),
        ("price", True),
        ("change", -1),
        ("percent_change", float("inf")),
        ("symbol", "AAA/BBB"),
        ("price", None),
    ],
)
def test_malformed_mover_rows_refuse_even_if_not_in_allowlist(field, value):
    movers, actives = bodies()
    movers["gainers"][0][field] = value
    with pytest.raises(ValueError):
        parse_screeners(movers, actives, movers_read_at_ns=NOW, actives_read_at_ns=NOW)


@pytest.mark.parametrize(
    "field,value", [("volume", -1), ("trade_count", 1.5), ("volume", False), ("trade_count", "NaN")]
)
def test_malformed_activity_rows_refuse(field, value):
    movers, actives = bodies()
    actives["most_actives"][0][field] = value
    with pytest.raises(ValueError):
        parse_screeners(movers, actives, movers_read_at_ns=NOW, actives_read_at_ns=NOW)


def test_envelope_limits_duplicates_and_nonstocks_refuse():
    for mutate in (
        lambda m, a: m.update(gainers=None),
        lambda m, a: m.update(market_type="crypto"),
        lambda m, a: m["gainers"].append(m["gainers"][0]),
        lambda m, a: m.update(losers=[m["gainers"][0]]),
        lambda m, a: a.update(most_actives=[{}]),
        lambda m, a: m.update(gainers=[{}] * 51),
        lambda m, a: a.update(most_actives=[{}] * 101),
    ):
        movers, actives = bodies()
        mutate(movers, actives)
        with pytest.raises(ValueError):
            parse_screeners(movers, actives, movers_read_at_ns=NOW, actives_read_at_ns=NOW)


def test_owner_file_has_no_fallback_and_rejects_placeholder(tmp_path):
    import json
    from pathlib import Path

    with pytest.raises(ValueError):
        UniverseParams.from_file(Path("deploy/alpaca-universe.template.json"))
    config = tmp_path / "synthetic.json"
    config.write_text(
        json.dumps(
            {
                "provenance": "synthetic, uncalibrated",
                "min_price": "1",
                "min_volume": 1,
                "max_symbols": 1,
                "max_age_ns": 1,
            }
        )
    )
    assert UniverseParams.from_file(config).min_price == 1
    config.write_text('{"min_price": "1"}')
    with pytest.raises(ValueError):
        UniverseParams.from_file(config)


def test_reader_uses_sdk_requests_and_completion_times():
    called = []

    def movers(request):
        called.append(("movers", request.top, request.market_type))
        return Movers(**bodies()[0])

    def actives(request):
        called.append(("actives", request.top, request.by))
        return MostActives(**bodies()[1])

    times = iter((NOW + 1, NOW + 2))
    reader = ScreenerReader(
        SimpleNamespace(get_market_movers=movers, get_most_actives=actives), now=lambda: next(times)
    )
    result = reader.combine(reader.movers(50), reader.actives(100))
    assert result.read_at_ns == NOW + 2
    assert called == [("movers", 50, "stocks"), ("actives", 100, "volume")]
    for method, top in (
        (reader.movers, 51),
        (reader.actives, 101),
        (reader.movers, 0),
        (reader.actives, True),
    ):
        with pytest.raises(ValueError):
            method(top)
    assert len(called) == 2


def test_factory_uses_existing_loader_injection_and_construction_has_no_io():
    budget = DataReadBudget()
    reader = build_screener(budget, keys=lambda: PaperKeys("synthetic-id", "synthetic-secret"))
    assert reader._sdk._base_url == DATA_URL
    assert reader._sdk._retry == 0 and reader._sdk._session.trust_env is False


def test_wire_paces_failed_reads_and_refuses_all_other_hosts_paths_methods(monkeypatch):
    now = [0]
    budget = DataReadBudget(lambda: now[0])
    client = ReadOnlyScreener(PaperKeys("synthetic-id", "synthetic-secret"), budget)
    calls = []

    def request(method, url, **opts):
        calls.append((method, url, opts))
        raise RuntimeError("synthetic private response must not escape")

    monkeypatch.setattr(client._session, "request", request)
    for method, url in (
        ("POST", DATA_URL + PATHS[0]),
        ("GET", DATA_URL + "/orders"),
        ("GET", "https://example.invalid" + PATHS[0]),
    ):
        with pytest.raises(ValueError, match="endpoint"):
            client._one_request(method, url, {}, 0)
    with pytest.raises(RuntimeError, match="^screener read failed; no automatic retry$"):
        client.get_market_movers(MarketMoversRequest())
    assert len(calls) == 1
    assert calls[0][2]["allow_redirects"] is False
    assert calls[0][2]["timeout"] == (10, 10)
    with pytest.raises(ValueError, match="not due"):
        client._one_request("GET", DATA_URL + PATHS[1], {}, 0)
    now[0] += REQUEST_INTERVAL_NS
    with pytest.raises(RuntimeError):
        client._one_request("GET", DATA_URL + PATHS[1], {}, 0)
    assert len(calls) == 2


def test_successful_sdk_reads_use_only_the_two_pinned_gets(monkeypatch):
    now = [NOW]
    budget = DataReadBudget(lambda: now[0])
    sdk = ReadOnlyScreener(PaperKeys("synthetic-id", "synthetic-secret"), budget)
    responses = iter(bodies())
    sent = []

    def request(method, url, **opts):
        sent.append((method, url, opts["params"]))
        body = next(responses)
        body["last_updated"] = WHEN.isoformat()
        now[0] += 1  # receipt is after the request
        return SimpleNamespace(text="synthetic", json=lambda: body, raise_for_status=lambda: None)

    monkeypatch.setattr(sdk._session, "request", request)
    reader = ScreenerReader(sdk, now=lambda: now[0])
    movers = reader.movers()
    now[0] += REQUEST_INTERVAL_NS
    actives = reader.actives()
    reading = reader.combine(movers, actives)
    assert reading.movers_read_at_ns == NOW + 1
    assert reading.actives_read_at_ns == NOW + REQUEST_INTERVAL_NS + 2
    assert sent == [
        ("GET", DATA_URL + PATHS[0], {"top": 10}),
        ("GET", DATA_URL + PATHS[1], {"top": 10, "by": "volume"}),
    ]
    assert [c.symbol for c in reading.candidates] == ["AAA", "BBB"]


def test_pair_schedule_and_shared_other_data_reads_stay_inside_200_per_minute():
    now = [0]
    budget = DataReadBudget(lambda: now[0])
    sent = []
    # Alternating endpoints; a third caller competes for this same admission.
    for tick in range(1201):
        now[0] = tick * 100_000_000
        callers = ("movers", "actives", "other-data")
        offset = (tick // 3) % 3
        for caller in callers[offset:] + callers[:offset]:
            try:
                budget.admit()
            except ValueError:
                continue
            sent.append((now[0], caller))
    assert all(sum(t <= x < t + 60_000_000_000 for x, _ in sent) <= 200 for t, _ in sent)
    assert {caller for _, caller in sent} == {"movers", "actives", "other-data"}
    assert REQUEST_INTERVAL_NS * 2 == 600_000_000


def test_template_entries_only_after_membership_and_removal_does_not_block_exits():
    ids = [InstrumentId.from_str("REENTRY.SIM"), InstrumentId.from_str("GAP.SIM")]
    full = sim.synthetic_universe(ids).snapshots[0]
    # All quotes are provided; GAP never joins. REENTRY joins after its early breakout,
    # then leaves while holding. Its protective exit must still happen, without re-entry.
    joined = replace(
        full,
        read=replace(
            full.read, movers_read_at_ns=NOW + 3_000_000_000, actives_read_at_ns=NOW + 3_000_000_000
        ),
        candidates=tuple(c for c in full.candidates if c.symbol == "REENTRY"),
    )
    left = replace(
        full,
        read=replace(
            full.read, movers_read_at_ns=NOW + 6_000_000_000, actives_read_at_ns=NOW + 6_000_000_000
        ),
        candidates=(),
    )
    timeline = UniverseTimeline((joined, left))
    books = {}
    sim.run(
        scenarios={s: sim.SCENARIOS[s] for s in ("REENTRY", "GAP")},
        universe=timeline,
        inspect=lambda engine, strategy: books.update(strategy.books),
    )
    assert books[ids[1]].entries == []
    assert len(books[ids[0]].entries) == 1
    assert books[ids[0]].exits
    for iid, book in books.items():
        for entry_ns in book.entries:
            assert iid.symbol.value in {c.symbol for c in timeline.at(entry_ns)}
            assert entry_ns > joined.read.read_at_ns
