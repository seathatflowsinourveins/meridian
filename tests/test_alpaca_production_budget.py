"""Production wiring with synthetic owner rows, venue, keys, stream and clock only."""

import asyncio
import json
import subprocess
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
from alpaca_fakes import Clock, FakeStream, FakeVenue, api_error, exec_config
from nautilus_trader.model import TraderId

from meridian.alpaca import factories
from meridian.alpaca.budget import ActionKind
from meridian.alpaca.credentials import PaperKeys
from meridian.alpaca.pacing import load_controls
from meridian.alpaca.wire import AccountGateway
from meridian.order_budget.controls import NAMES
from meridian.order_budget.pacer import AccountPacer
from meridian.order_budget.rows import control_rows

ROOT = Path(__file__).resolve().parents[1]


def owner_rows(tmp_path):
    # Test-only promotion to exercise deployment validation, never production authority.
    rows = control_rows()
    for row in rows:
        row["scope"] = "REVIEWED"
    path = tmp_path / "synthetic-owner-rows.json"
    path.write_text(json.dumps(rows))
    return path, rows


@pytest.mark.parametrize("paper_defaults", [0, 1, len(NAMES)])
def test_rows_load_with_scope_counts(tmp_path, paper_defaults):
    path, rows = owner_rows(tmp_path)
    for row in rows[:paper_defaults]:
        row["scope"] = "PAPER_DEFAULT"
    original = json.dumps(rows)
    path.write_text(original)
    loaded = load_controls(str(path))
    assert loaded.paper_default_rows == paper_defaults
    assert loaded.reviewed_rows == len(NAMES) - paper_defaults
    assert not loaded.controls.fixture
    assert set(loaded.controls.values) == NAMES
    assert path.read_text() == original
    pacer = pacer_for(path, Clock())
    assert pacer.controls == loaded.controls and pacer.bucket.tokens == 0


@pytest.mark.parametrize(
    ("name", "field", "value"),
    [
        ("reserve_per_open_position", "scope", "FIXTURE_ONLY"),
        ("reserve_per_open_position", "scope", "synthetic-private-value"),
        ("cancel_timeout_s", "value", "synthetic-private-value"),
        ("cancel_timeout_s", "source", None),
        ("request_budget", "value", 201),  # exceeds the cited venue limit
    ],
)
def test_paper_default_rows_revalidate_without_disclosure(
    tmp_path, capsys, caplog, name, field, value
):
    path, rows = owner_rows(tmp_path)
    for row in rows:
        row["scope"] = "PAPER_DEFAULT"
    rows[-1]["scope"] = "REVIEWED"
    path.write_text(json.dumps(rows))
    # Establish accepted paper defaults, then invalidate one row on the next load.
    assert load_controls(str(path)).paper_default_rows == len(NAMES) - 1
    row = next(row for row in rows if row["name"] == name)
    row[field] = value
    row["unit"] = "synthetic-private-value"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError) as caught:
        load_controls(str(path))
    assert str(caught.value) == "order budget rows invalid"
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    output = capsys.readouterr()
    rendered = (
        "".join(traceback.format_exception(caught.value)) + output.out + output.err + caplog.text
    )
    assert "synthetic-private-value" not in rendered and str(path) not in rendered


@pytest.mark.parametrize(("name", "value"), [("window_s", "6"), ("broker_limit", 201)])
def test_rows_refuse_wrong_venue_limit_without_disclosure(tmp_path, capsys, caplog, name, value):
    path, rows = owner_rows(tmp_path)
    row = next(row for row in rows if row["name"] == name)
    row["value"] = value
    row["source"] = "synthetic-private-value"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError) as caught:
        load_controls(str(path))
    assert str(caught.value) == "order budget rows invalid"
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    output = capsys.readouterr()
    rendered = (
        "".join(traceback.format_exception(caught.value)) + output.out + output.err + caplog.text
    )
    assert "synthetic-private-value" not in rendered and str(path) not in rendered


def configured(path, **kwargs):
    return exec_config(order_budget_rows_path=str(path) if path is not None else None, **kwargs)


def pacer_for(path, clock):
    factory = factories.production_wiring(configured(path)).pacer
    assert factory is not None
    pacer = factory(clock)
    assert isinstance(pacer, AccountPacer)
    return pacer


def client_for(monkeypatch, path, **kwargs):
    clock, venue = Clock(), FakeVenue()
    monkeypatch.setattr(factories, "load_paper_keys", lambda: PaperKeys("synthetic", "synthetic"))
    monkeypatch.setattr(factories, "PaperTradingClient", lambda *a, **kw: venue)
    monkeypatch.setattr(factories, "paper_stream", lambda keys: FakeStream())
    client = factories.build_client(
        name="ALPACA",
        config=configured(path, **kwargs),
        cache=SimpleNamespace(positions_open=lambda **kw: [], orders_open=lambda **kw: []),
        clock=SimpleNamespace(timestamp_ns=clock),
        trader_id=TraderId("M3-TEST"),
    )
    monkeypatch.setattr(client, "_handle_instrument", lambda instrument: None)
    monkeypatch.setattr(client, "generate_account_state", lambda *args: None)
    monkeypatch.setattr(client, "create_task", lambda coro, name: asyncio.create_task(coro))
    return client, venue, clock


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


async def connect(client, venue, clock):
    before = len(venue.calls)
    task = asyncio.create_task(client._connect())
    await asyncio.sleep(0)
    if task.done():
        await task  # surface a startup failure, not a timeout
    assert client.gateway is not None
    pacer = client.gateway.pacer
    assert isinstance(pacer, AccountPacer)
    interval = pacer.bucket.interval_ns
    assert pacer.bucket.tokens == 0 and len(venue.calls) == before
    clock.ns += interval - 1
    pacer.drain()
    await asyncio.sleep(0)
    assert len(venue.calls) == before
    clock.ns += 1
    pacer.drain()
    await until(lambda: len(venue.calls) == before + 1 and bool(pacer.queue))
    clock.ns += interval
    pacer.drain()
    await asyncio.wait_for(task, 2)
    await until(lambda: client.stream_live)
    assert len(venue.calls) == before + 2
    return pacer


@pytest.mark.parametrize(
    "case",
    [
        "unset",
        "absent",
        "unreadable",
        "fixture",
        "missing",
        "malformed",
        "shape",
        "bad_name",
        "bad_value",
        "bad_metadata",
    ],
)
def test_invalid_owner_rows_refuse_connect_without_disclosing_values(
    tmp_path,
    monkeypatch,
    capsys,
    caplog,
    case,
):
    path, rows = owner_rows(tmp_path)
    reason = "order budget rows invalid"
    if case == "unset":
        path = None
        reason = "order budget rows file unavailable"
    elif case == "absent":
        path.unlink()
        reason = "order budget rows file unavailable"
    elif case == "unreadable":

        def unreadable(*args, **kwargs):
            raise PermissionError("synthetic-private-value")

        monkeypatch.setattr(Path, "read_text", unreadable)
        reason = "order budget rows file unavailable"
    elif case == "fixture":
        path.write_text(json.dumps(control_rows()))
    elif case == "missing":
        path.write_text(json.dumps(rows[:-1]))
    elif case == "malformed":
        path.write_text("synthetic-private-value")
    elif case == "shape":
        path.write_text(json.dumps(["synthetic-private-value"]))
    else:
        if case == "bad_name":
            rows[0]["name"] = ["synthetic-private-value"]
        elif case == "bad_value":
            rows[0]["value"] = "synthetic-private-value"
        else:
            rows[0]["scope"] = "synthetic-private-value"
        path.write_text(json.dumps(rows))
    client, venue, _ = client_for(monkeypatch, path)
    with pytest.raises(ValueError) as caught:
        asyncio.run(client._connect())
    assert str(caught.value) == reason
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    output = capsys.readouterr()
    rendered = (
        "".join(traceback.format_exception(caught.value)) + output.out + output.err + caplog.text
    )
    assert "synthetic-private-value" not in rendered
    assert venue.calls == [] and client.gateway is None


def test_reviewed_rows_connect_empty_again_on_reconnect(tmp_path, monkeypatch):
    path, _ = owner_rows(tmp_path)
    client, venue, clock = client_for(monkeypatch, path)

    async def scenario():
        first = await connect(client, venue, clock)
        await client._disconnect()
        second = await connect(client, venue, clock)
        assert second is not first
        await client._disconnect()

    asyncio.run(scenario())


def test_reviewed_rows_still_require_commission_evidence(tmp_path, monkeypatch):
    path, _ = owner_rows(tmp_path)
    client, venue, _ = client_for(monkeypatch, path, commission_per_fill=None)
    with pytest.raises(ValueError, match="sourced commission evidence required"):
        asyncio.run(client._connect())
    assert venue.calls == []


def test_a_minute_of_requests_is_paced_and_within_budget(tmp_path, monkeypatch):
    path, _ = owner_rows(tmp_path)
    client, venue, clock = client_for(monkeypatch, path)

    async def scenario():
        pacer = await connect(client, venue, clock)
        assert client.gateway is not None
        start = clock()
        count = pacer.controls["request_budget"] + pacer.bucket.burst
        sent = []
        tasks = [
            asyncio.create_task(
                client.gateway.call(
                    ActionKind.QUERY,
                    "get",
                    "/positions",
                    on_wire=lambda: sent.append(clock()),
                )
            )
            for _ in range(count)
        ]
        await asyncio.sleep(0)
        interval = pacer.bucket.interval_ns
        steps = pacer.controls.ns("window_s") // interval
        for i in range(1, steps + 1):
            clock.ns = start + i * interval
            pacer.drain()
            await until(lambda expected=2 + i: len(venue.calls) == expected)
        assert len(sent) == steps > 0
        assert len(sent) <= pacer.controls["request_budget"]
        assert sent == [start + i * interval for i in range(1, steps + 1)]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client._disconnect()

    asyncio.run(scenario())


def test_a_429_pauses_the_production_gateway(tmp_path):
    path, _ = owner_rows(tmp_path)
    clock, venue = Clock(), FakeVenue()
    pacer = pacer_for(path, clock)
    gw = AccountGateway(venue, pacer, lambda: (0, 0))

    async def scenario():
        venue.fail("get", "/positions", api_error(429))
        task = asyncio.create_task(gw.call(ActionKind.QUERY, "get", "/positions"))
        await asyncio.sleep(0)
        clock.ns += pacer.bucket.interval_ns
        pacer.drain()
        with pytest.raises(type(api_error(429))):
            await asyncio.wait_for(task, 2)
        assert pacer.paused_until == clock() + pacer.controls.ns("backoff_base_s")
        venue.failures.clear()
        task = asyncio.create_task(gw.call(ActionKind.QUERY, "get", "/positions"))
        await asyncio.sleep(0)
        clock.ns = pacer.paused_until - 1
        pacer.drain()
        await asyncio.sleep(0)
        assert len(venue.calls) == 1
        clock.ns += 1
        pacer.drain()
        await asyncio.wait_for(task, 2)
        assert len(venue.calls) == 2
        await gw.close()

    asyncio.run(scenario())


def test_a_production_pacer_refusal_is_not_sent(tmp_path):
    path, _ = owner_rows(tmp_path)
    pacer = pacer_for(path, Clock())
    venue = FakeVenue()
    gw = AccountGateway(venue, pacer, lambda: (pacer.bucket.burst, 0))
    sent = []

    async def scenario():
        with pytest.raises(ValueError, match="^entry-reserve-exceeds-burst$"):
            await gw.call(ActionKind.SUBMIT, "post", "/orders", {}, on_wire=lambda: sent.append(1))
        await gw.close()

    asyncio.run(scenario())
    assert sent == [] and venue.calls == [] and pacer.wire_requests == 0


def test_owner_template_has_all_names_and_no_values_and_private_copy_is_ignored():
    rows = json.loads((ROOT / "deploy/alpaca-order-budget.template.json").read_text())
    assert len(rows) == len(NAMES) and {row["name"] for row in rows} == NAMES
    fields = {"value", "source", "unit", "last_change", "calibration", "scope"}
    assert all(set(row) == fields | {"name"} for row in rows)
    assert all(row[field] is None for row in rows for field in fields)
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "local/alpaca-order-budget.json",
            "local/alpaca-order-budget.json.bak",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and len(result.stdout.splitlines()) == 2
