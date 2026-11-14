"""Synthetic New York dates and quotes only; no network or account-derived data."""

import asyncio
from datetime import date, datetime

import pytest
from alpaca_fakes import AAPL
from nautilus_trader.core import unix_nanos_to_iso8601
from test_alpaca_data import QUOTE, Socket, rig, settle, subscribed
from test_alpaca_data import data as data  # pytest fixture

from meridian.alpaca.reports import timestamp_ns
from meridian.alpaca_sessions import NEW_YORK, SIP_DELAY_NS, session_at, session_ns


@pytest.mark.parametrize(
    "when,name,feed",
    [
        ("2026-11-13T19:59:59-05:00", "after_hours", "delayed_sip"),
        ("2026-11-13T20:00:00-05:00", None, None),
        ("2026-11-14T03:59:59-05:00", None, None),
        ("2026-11-15T19:59:59-05:00", None, None),
        ("2026-11-15T20:00:00-05:00", "overnight", "overnight"),
        ("2026-11-16T03:59:59-05:00", "overnight", "overnight"),
        ("2026-11-16T04:00:00-05:00", "pre_market", "delayed_sip"),
        ("2026-11-16T09:29:59-05:00", "pre_market", "delayed_sip"),
        ("2026-11-16T09:30:00-05:00", "regular", "iex"),
        ("2026-11-16T15:59:59-05:00", "regular", "iex"),
        ("2026-11-16T16:00:00-05:00", "after_hours", "delayed_sip"),
        ("2026-11-16T20:00:00-05:00", "overnight", "overnight"),
        # DST changes on Sunday while the window is closed; Sunday opening moves in UTC.
        ("2026-03-09T00:00:00Z", "overnight", "overnight"),
        ("2026-03-08T23:59:59Z", None, None),
        ("2026-11-02T00:59:59Z", None, None),
        ("2026-11-02T01:00:00Z", "overnight", "overnight"),
        ("2026-11-01T01:30:00-04:00", None, None),
        ("2026-11-01T01:30:00-05:00", None, None),
    ],
)
def test_sessions_and_dst(when, name, feed):
    current = session_at(datetime.fromisoformat(when))
    assert (None if current is None else current.name) == name
    assert (None if current is None else current.feed) == feed
    if current:
        assert current.start.tzinfo == NEW_YORK


def test_calendar_holiday_and_early_close():
    assert session_at(datetime.fromisoformat("2026-11-25T20:00:00-05:00"), {}) is None
    half_day = {
        date(2026, 11, 27): {
            "open": "09:30",
            "close": "13:00",
            "session_open": "0400",
            "session_close": "1700",
        }
    }
    for when, name in [
        ("2026-11-26T20:00:00-05:00", "overnight"),
        ("2026-11-27T03:59:59-05:00", "overnight"),
        ("2026-11-27T12:59:59-05:00", "regular"),
        ("2026-11-27T13:00:00-05:00", "after_hours"),
        ("2026-11-27T17:00:00-05:00", None),
    ]:
        current = session_at(datetime.fromisoformat(when), half_day)
        assert (None if current is None else current.name) == name
    with pytest.raises(ValueError, match="timezone aware"):
        session_at(datetime(2026, 11, 16, 9, 30))


SESSION_TIMES = [
    ("2026-11-16T02:00:00-05:00", "overnight"),
    ("2026-11-16T08:00:00-05:00", "delayed_sip"),
    ("2026-11-16T12:00:00-05:00", "iex"),
    ("2026-11-16T18:00:00-05:00", "delayed_sip"),
]


@pytest.mark.parametrize("when,feed", SESSION_TIMES)
def test_session_feed_pinned_and_quote_age_honest(data, monkeypatch, when, feed):
    async def check():
        r = rig(data, monkeypatch)
        r.clock.ns = timestamp_ns(when, "synthetic")
        r.client.session_now = lambda: session_ns(r.clock.ns)
        r.socket.protocol.uri.path = data.FEED_PATHS[feed]
        await subscribed(r)
        assert r.client.feed == feed
        assert r.calls[0][0].endswith(data.FEED_PATHS[feed])
        assert r.client.quote_age_ns(AAPL) is None
        delay = SIP_DELAY_NS if feed == "delayed_sip" else 0
        event = r.clock.ns - delay - 10
        frame = QUOTE.replace("2026-11-02T14:30:00.123456789Z", unix_nanos_to_iso8601(event))
        r.socket.frames.put_nowait(frame)
        await settle()
        assert r.ticks[0].ts_event == event
        assert r.client.quote_age_ns(AAPL) == delay + 10
        r.clock.ns += 100
        assert r.client.quote_age_ns(AAPL) == delay + 110
        # Even an incorrectly current timestamp cannot conceal a feed's declared delay.
        r.socket.frames.put_nowait(
            frame.replace(unix_nanos_to_iso8601(event), unix_nanos_to_iso8601(r.clock.ns))
        )
        await settle()
        assert r.client.quote_age_ns(AAPL) == delay
        await r.client._disconnect()

    asyncio.run(check())


@pytest.mark.parametrize("when,feed", SESSION_TIMES)
def test_wrong_feed_path_refuses_before_auth(data, monkeypatch, when, feed):
    async def check():
        r = rig(data, monkeypatch)
        r.clock.ns = timestamp_ns(when, "synthetic")
        r.client.session_now = lambda: session_ns(r.clock.ns)
        r.socket.protocol.uri.path = "/v1beta1/boats"
        with pytest.raises(RuntimeError, match="connection failed"):
            await r.client._connect()
        assert r.socket.closed and not r.socket.sent

    asyncio.run(check())


def test_feed_rollover_drops_old_quote_and_resubscribes(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        r.clock.ns = timestamp_ns("2026-11-16T19:59:59-05:00", "synthetic")
        r.client.session_now = lambda: session_ns(r.clock.ns)
        sockets = []

        async def connect(url, **kwargs):
            socket = Socket()
            socket.protocol.uri.path = "/" + url.split("/", 3)[3]
            sockets.append(socket)
            return socket

        monkeypatch.setattr(data.websockets, "connect", connect)
        await subscribed(r)
        old = sockets[0]
        stamp = unix_nanos_to_iso8601(r.clock.ns - SIP_DELAY_NS)
        old.frames.put_nowait(QUOTE.replace("2026-11-02T14:30:00.123456789Z", stamp))
        await settle()
        assert r.client.quote_age_ns(AAPL) == SIP_DELAY_NS
        r.clock.ns += 1_000_000_000
        assert r.client.quote_age_ns(AAPL) is None
        # Wake the existing receive; this old frame must never enter the engine.
        old.frames.put_nowait(QUOTE)
        for _ in range(20):
            await asyncio.sleep(0)
        assert old.closed and len(sockets) == 2
        assert r.client.feed == "overnight" and r.client.quote_age_ns(AAPL) is None
        assert sockets[-1].sent == ["auth", "subscribe"]
        stamp = unix_nanos_to_iso8601(r.clock.ns)
        sockets[-1].frames.put_nowait(QUOTE.replace("2026-11-02T14:30:00.123456789Z", stamp))
        await settle()
        assert len(r.ticks) == 2 and r.client.quote_age_ns(AAPL) == 0
        await r.client._disconnect()

    asyncio.run(check())


def test_closed_window_opens_no_stream(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        r.clock.ns = timestamp_ns("2026-11-13T20:00:00-05:00", "synthetic")
        r.client.session_now = lambda: session_ns(r.clock.ns)
        await subscribed(r)
        assert not r.calls and r.client.quote_age_ns(AAPL) is None
        await r.client._disconnect()

    asyncio.run(check())


def test_subscription_racing_session_change_has_one_new_socket(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        r.clock.ns = timestamp_ns("2026-11-16T19:59:59-05:00", "synthetic")
        r.client.session_now = lambda: session_ns(r.clock.ns)
        sockets = []

        async def connect(url, **kwargs):
            socket = Socket()
            socket.protocol.uri.path = "/" + url.split("/", 3)[3]
            close = socket.close

            async def closed():
                await close()
                socket.frames.put_nowait(ConnectionError("synthetic closed socket"))

            socket.close = closed
            sockets.append(socket)
            return socket

        monkeypatch.setattr(data.websockets, "connect", connect)
        await subscribed(r)
        r.clock.ns += 1_000_000_000
        from types import SimpleNamespace

        await asyncio.gather(
            r.client._subscribe_quotes(SimpleNamespace(instrument_ids=[AAPL])),
            r.client._switch_session(),
        )
        for _ in range(20):
            await asyncio.sleep(0)
        assert len(sockets) == 2 and sockets[0].closed
        assert r.client.feed == "overnight" and r.client.failure_reason is None
        assert r.client._acknowledged == {"AAPL"}
        await r.client._disconnect()

    asyncio.run(check())


def test_transport_timeout_latches_failure(data, monkeypatch):
    async def check():
        r = rig(data, monkeypatch)
        await subscribed(r)
        r.socket.frames.put_nowait(TimeoutError("synthetic transport timeout"))
        await settle()
        assert r.client.failure_reason and r.client.quote_age_ns(AAPL) is None
        await r.client._disconnect()

    asyncio.run(check())
