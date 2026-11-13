"""
Order submission's wire side: the payload, the endpoint allowlist, the paper-only SDK client,
and the account gateway's use of the order budget. Offline: the SDK is a fake account and the
budget is `alpaca_fakes.FakePacer`, which has the earlier pacer's interface.
"""

import asyncio
from types import SimpleNamespace

import pytest
import requests
from alpaca_fakes import Clock, FakePacer, FakeVenue, api_error
from nautilus_trader.model import (
    ClientOrderId,
    ContingencyType,
    InstrumentId,
    OrderSide,
    OrderType,
    Price,
    Quantity,
    TimeInForce,
    TriggerType,
)

from meridian.alpaca.budget import ActionKind
from meridian.alpaca.constants import PAPER_TRADING_URL
from meridian.alpaca.execution import _why
from meridian.alpaca.wire import (
    AccountGateway,
    PaperTradingClient,
    UnreadableAnswer,
    permitted,
    price_text,
    submit_payload,
)


def order(**overrides):
    values = {
        "order_type": OrderType.LIMIT,
        "time_in_force": TimeInForce.DAY,
        "expire_time": None,
        "is_post_only": False,
        "is_reduce_only": False,
        "is_quote_quantity": False,
        "display_qty": None,
        "contingency_type": ContingencyType.NO_CONTINGENCY,
        "order_list_id": None,
        "parent_order_id": None,
        "linked_order_ids": None,
        "exec_algorithm_id": None,
        "emulation_trigger": TriggerType.NO_TRIGGER,
        "client_order_id": ClientOrderId("M3-1"),
        "instrument_id": InstrumentId.from_str("AAPL.ALPACA"),
        "quantity": Quantity.from_str("1"),
        "side": OrderSide.BUY,
        "price": Price.from_str("187.25"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_a_day_limit_order_becomes_an_exact_decimal_text_payload():
    assert submit_payload(order(), "M3-") == {
        "client_order_id": "M3-1",
        "symbol": "AAPL",
        "qty": "1",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "187.25",
        "order_class": "simple",
        "extended_hours": False,
    }
    sell = submit_payload(order(side=OrderSide.SELL, price=Price.from_str("0.5123")), "M3-")
    assert sell["side"] == "sell" and sell["limit_price"] == "0.5123"


@pytest.mark.parametrize(
    "change",
    [
        {"order_type": OrderType.MARKET},
        {"order_type": OrderType.STOP_LIMIT},
        {"order_type": OrderType.TRAILING_STOP_MARKET},
        {"time_in_force": TimeInForce.GTC},
        {"time_in_force": TimeInForce.IOC},
        {"expire_time": 1},
        {"is_post_only": True},
        {"is_reduce_only": True},
        {"is_quote_quantity": True},
        {"display_qty": Quantity.from_str("1")},
        {"contingency_type": ContingencyType.OTO},
        {"parent_order_id": ClientOrderId("M3-0")},
        {"linked_order_ids": [ClientOrderId("M3-2")]},
        {"emulation_trigger": TriggerType.LAST_PRICE},
        {"client_order_id": ClientOrderId("OWNER-1")},
        {"quantity": Quantity.from_str("1.5")},
        {"price": Price.from_str("187.255")},
        {"price": Price.from_str("0.51234")},
    ],
)
def test_anything_but_a_plain_day_limit_order_is_refused_before_the_wire(change):
    with pytest.raises(ValueError):
        submit_payload(order(**change), "M3-")


def test_prices_must_already_sit_on_the_venue_tick():
    assert price_text(Price.from_str("1.00")) == "1.00"
    assert price_text(Price.from_str("0.9999")) == "0.9999"
    # The instrument's precision is 4; the text sent is canonical at the venue's tick.
    assert price_text(Price.from_str("187.2500")) == "187.25"
    assert price_text(Price.from_str("0.5000")) == "0.5000"
    with pytest.raises(ValueError):
        price_text(Price.from_str("1.0001"))


def test_a_refusal_reason_never_copies_a_venue_error_body():
    body = '{"code": 40410000, "message": "order 00000000-0000-4000-8000-000000000042 not found"}'
    assert _why(api_error(404, body)) == "APIError 404"
    assert _why(ValueError("wire admission refused")) == "wire admission refused"
    assert _why(KeyError("qty")) == "KeyError"


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("get", "/account", True),
        ("get", "/positions", True),
        ("get", "/orders", True),
        ("get", "/orders:by_client_order_id", True),
        ("get", "/account/activities/FILL", True),
        ("get", "/assets/AAPL", True),
        ("get", "/orders/00000000-0000-4000-8000-000000000001", True),
        ("delete", "/orders/00000000-0000-4000-8000-000000000001", True),
        ("post", "/orders", True),
        ("delete", "/orders", False),  # cancel every order
        ("delete", "/positions", False),  # close every position
        ("delete", "/positions/AAPL", False),
        ("patch", "/orders/00000000-0000-4000-8000-000000000001", False),  # replace
        ("delete", "/orders/not-a-uuid", False),
        ("get", "/assets/aapl", False),
        ("post", "/account/configurations", False),
        ("get", "/watchlists", False),
    ],
)
def test_the_gateway_calls_only_the_lanes_endpoints(method, path, allowed):
    assert permitted(method, path) is allowed


def test_the_sdk_client_is_on_the_paper_host_with_no_retries_and_a_timeout(monkeypatch):
    client = PaperTradingClient("synthetic-key-id", "synthetic-secret", timeout_secs=7.5)
    assert client._base_url == PAPER_TRADING_URL
    assert client._retry == 0
    seen = {}

    def request(method, url, **opts):
        seen.update(method=method, url=url, timeout=opts.get("timeout"))
        return SimpleNamespace(raise_for_status=lambda: None, text="", json=dict)

    monkeypatch.setattr(client._session, "request", request)
    client.get("/account")
    assert seen == {
        "method": "GET",
        "url": PAPER_TRADING_URL + "/v2/account",
        "timeout": (7.5, 7.5),
    }
    with pytest.raises(ValueError, match="paper endpoint"):
        client._one_request("GET", "https://example.invalid/v2/account", {}, 0)


@pytest.mark.parametrize("passed_down", [{}, {"allow_redirects": True}])
def test_the_sdk_client_follows_no_redirect_whatever_the_sdk_passes_down(monkeypatch, passed_down):
    """The request carries the keys in its headers. alpaca-py 0.45.0 passes
    allow_redirects=False; the client sets it itself, so a release that stops doing so (or
    passes True) still cannot send the keys after a redirect."""
    client = PaperTradingClient("synthetic-key-id", "synthetic-secret", timeout_secs=1)
    seen = []

    def request(method, url, **opts):
        seen.append(opts.get("allow_redirects"))
        return SimpleNamespace(raise_for_status=lambda: None, text="", json=dict)

    monkeypatch.setattr(client._session, "request", request)
    client._one_request("GET", PAPER_TRADING_URL + "/v2/account", dict(passed_down), 0)
    client.get("/account")  # through the SDK's own path
    assert seen == [False, False]


def test_a_429_from_the_venue_is_raised_once_not_resent_inside_the_sdk(monkeypatch):
    client = PaperTradingClient("synthetic-key-id", "synthetic-secret", timeout_secs=1)
    attempts = []

    def request(method, url, **opts):
        attempts.append(url)
        error = api_error(429)
        return SimpleNamespace(
            raise_for_status=lambda: (_ for _ in ()).throw(
                __import__("requests").HTTPError(response=SimpleNamespace(status_code=429))
            ),
            status_code=429,
            text=str(error),
        )

    monkeypatch.setattr(client._session, "request", request)
    with pytest.raises(Exception) as info:
        client.post("/orders", {"symbol": "AAPL"})
    assert len(attempts) == 1
    assert getattr(info.value, "status_code", None) == 429


def gateway(venue=None, *, limit=180):
    clock = Clock()
    pacer = FakePacer(clock, limit=limit)
    return AccountGateway(venue or FakeVenue(), pacer, lambda: (0, 0)), pacer, clock


def test_a_2xx_answer_whose_body_is_not_json_is_the_answers_failure(monkeypatch):
    """alpaca-py 0.45.0 decodes a 2xx body inside the request, so a body that is not JSON
    raises there, as requests' JSONDecodeError, where a failed request's error would arrive.
    The gateway hands it on as `UnreadableAnswer`: the venue answered, and the client counts
    that as the answer's failure (a gap), not the request's. None of the body is carried."""
    client = PaperTradingClient("synthetic-key-id", "synthetic-secret", timeout_secs=1)
    answer = requests.models.Response()
    answer.status_code, answer._content, answer.encoding = 200, b"<html>synthetic</html>", "utf-8"
    monkeypatch.setattr(client._session, "request", lambda method, url, **opts: answer)
    with pytest.raises(requests.exceptions.JSONDecodeError):
        client.get("/account")

    async def scenario():
        gw, _, _ = gateway(client)
        return await gw.call(ActionKind.QUERY, "get", "/account")

    with pytest.raises(UnreadableAnswer) as info:
        asyncio.run(scenario())
    assert str(info.value) == "Alpaca answer is not JSON" and "synthetic" not in repr(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_every_request_reads_included_passes_through_the_budget_with_its_kind():
    async def scenario():
        gw, pacer, _ = gateway()
        await gw.call(ActionKind.QUERY, "get", "/account")
        await gw.call(ActionKind.QUERY, "get", "/positions")
        await gw.call(
            ActionKind.SUBMIT,
            "post",
            "/orders",
            {
                "symbol": "AAPL",
                "client_order_id": "M3-9",
                "side": "buy",
                "qty": "1",
                "limit_price": "100.00",
            },
        )
        return gw, pacer

    gw, pacer = asyncio.run(scenario())
    assert pacer.kinds == [ActionKind.QUERY, ActionKind.QUERY, ActionKind.SUBMIT]
    assert pacer.wire_requests == len(gw.sdk.calls) == 3
    assert pacer.successes == 3


def test_the_on_wire_hook_runs_once_before_the_request_leaves():
    order_of_events = []

    class Recording(FakeVenue):
        def get(self, path, data=None, **kw):
            order_of_events.append("request")
            return super().get(path, data, **kw)

    async def scenario():
        gw, _, _ = gateway(Recording())
        await gw.call(
            ActionKind.QUERY, "get", "/account", on_wire=lambda: order_of_events.append("wire")
        )

    asyncio.run(scenario())
    assert order_of_events == ["wire", "request"]


def test_a_budget_refusal_is_not_sent_and_reaches_the_caller():
    async def scenario():
        gw, pacer, _ = gateway()
        pacer.refuse_kinds.add(ActionKind.SUBMIT)
        wired = []
        with pytest.raises(ValueError, match="synthetic pacer refusal"):
            await gw.call(ActionKind.SUBMIT, "post", "/orders", {}, on_wire=lambda: wired.append(1))
        return gw, wired

    gw, wired = asyncio.run(scenario())
    assert wired == [] and gw.sdk.calls == []


def test_a_refused_admission_is_not_sent():
    async def scenario():
        gw, _, _ = gateway()
        with pytest.raises(ValueError, match="admission refused"):
            await gw.call(ActionKind.QUERY, "get", "/account", admission=lambda: False)
        return gw

    assert asyncio.run(scenario()).sdk.calls == []


def test_a_submit_without_reserve_authority_is_refused_not_dropped():
    async def scenario():
        gw, pacer, _ = gateway()
        pacer.controls["reserve_per_open_position"] = None
        with pytest.raises(ValueError, match="reserve authority"):
            await gw.call(ActionKind.SUBMIT, "post", "/orders", {})
        return gw

    assert asyncio.run(scenario()).sdk.calls == []


def test_a_429_pauses_the_budget_and_the_error_reaches_the_caller():
    async def scenario():
        venue = FakeVenue()
        venue.fail("get", "/account", api_error(429))
        gw, pacer, _ = gateway(venue)
        with pytest.raises(Exception) as info:
            await gw.call(ActionKind.QUERY, "get", "/account")
        return pacer, info.value

    pacer, error = asyncio.run(scenario())
    assert pacer.rate_limited == 1 and pacer.paused_until > 0
    assert getattr(error, "status_code", None) == 429


def test_unsupported_endpoints_never_reach_the_budget():
    async def scenario():
        gw, pacer, _ = gateway()
        for method, path in (("delete", "/orders"), ("delete", "/positions")):
            with pytest.raises(ValueError, match="unsupported account endpoint"):
                await gw.call(ActionKind.CANCEL, method, path)
        return gw, pacer

    gw, pacer = asyncio.run(scenario())
    assert pacer.wire_requests == 0 and gw.sdk.calls == []


def test_the_budget_holds_180_order_actions_a_minute_and_cancels_go_first():
    """200 submits and 20 cancels queued at once: 180 reach the wire in the first minute,
    every cancel among them and ahead of the submits; the rest wait for the next window."""

    async def scenario():
        venue = FakeVenue()
        gw, pacer, clock = gateway(venue)
        # Hold the budget so that everything is queued before the first admission.
        pacer.paused_until = clock() + 1
        payload = {
            "symbol": "AAPL",
            "client_order_id": "M3-x",
            "side": "buy",
            "qty": "1",
            "limit_price": "100.00",
        }
        target = "/orders/00000000-0000-4000-8000-000000000001"
        venue.orders.append({"id": target.removeprefix("/orders/"), "status": "new"})
        tasks = [
            asyncio.ensure_future(gw.call(ActionKind.SUBMIT, "post", "/orders", dict(payload)))
            for _ in range(200)
        ] + [asyncio.ensure_future(gw.call(ActionKind.CANCEL, "delete", target)) for _ in range(20)]
        await asyncio.sleep(0.05)
        clock.ns += 2  # release the hold; still inside the first minute
        while pacer.wire_requests < 180:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        first_minute = list(pacer.kinds)
        clock.ns += 60 * 10**9  # the next window
        await asyncio.wait_for(asyncio.gather(*tasks), 10)
        return first_minute, pacer

    first_minute, pacer = asyncio.run(scenario())
    assert len(first_minute) == 180
    assert first_minute[:20] == [ActionKind.CANCEL] * 20
    assert set(first_minute[20:]) == {ActionKind.SUBMIT}
    assert pacer.wire_requests == 220


def test_a_cancelled_await_withdraws_its_queued_request():
    async def scenario():
        gw, pacer, clock = gateway(limit=1)
        await gw.call(ActionKind.QUERY, "get", "/account")  # uses the one admission
        waiting = asyncio.ensure_future(gw.call(ActionKind.QUERY, "get", "/positions"))
        await asyncio.sleep(0.02)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        clock.ns += 61 * 10**9
        pacer.drain()
        await asyncio.sleep(0.2)  # long enough for a request that was admitted to go out
        return gw, pacer

    gw, pacer = asyncio.run(scenario())
    assert gw.sdk.calls == [("get", "/account")]
    assert pacer.wire_requests == 1
