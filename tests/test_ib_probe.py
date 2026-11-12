import socket
import threading

import pytest
from fake_gateway import FakeGateway

from meridian import ib_probe


def ask(gateway: FakeGateway, timeout: float = 5.0) -> list[str]:
    return ib_probe.managed_accounts("127.0.0.1", gateway.port, client_id=7, timeout=timeout)


def test_reads_the_account_the_gateway_reports():
    with FakeGateway("DUFAKE0001") as gw:
        assert ask(gw) == ["DUFAKE0001"]


def test_reads_several_accounts_and_ignores_a_trailing_comma():
    with FakeGateway("DUFAKE0001,DUFAKE0002,") as gw:
        assert ask(gw) == ["DUFAKE0001", "DUFAKE0002"]


def test_sends_the_handshake_and_start_api_and_nothing_after():
    with FakeGateway("DUFAKE0001") as gw:
        ask(gw)
        assert gw.client_gone.wait(2)
        assert gw.handshakes == ["v100..176"]
        assert gw.start_api == [b"71\x002\x007\x00\x00"]
        assert gw.after_start_api == b""  # where an order message would have to go


def test_skips_a_notice_that_arrives_before_the_handshake_answer():
    with FakeGateway("DUFAKE0001", notice_before_answer=True) as gw:
        assert ask(gw) == ["DUFAKE0001"]


def test_reassembles_frames_that_arrive_a_byte_at_a_time():
    with FakeGateway("DUFAKE0001", bytewise=True) as gw:
        assert ask(gw) == ["DUFAKE0001"]


def test_the_timeout_bounds_the_whole_call_even_while_frames_keep_arriving():
    with (
        FakeGateway("DUFAKE0001", chatter_seconds=2.0) as gw,
        pytest.raises(ib_probe.ProbeError, match="in time"),
    ):
        ask(gw, timeout=0.5)


def test_fails_on_a_managed_accounts_message_without_an_account_field():
    with (
        FakeGateway("DUFAKE0001", malformed_accounts=True) as gw,
        pytest.raises(ib_probe.ProbeError, match="malformed"),
    ):
        ask(gw)


def test_fails_on_an_absurd_frame_length():
    with (
        FakeGateway("DUFAKE0001", oversize_frame=True) as gw,
        pytest.raises(ib_probe.ProbeError, match="unexpected size"),
    ):
        ask(gw, timeout=2)


@pytest.mark.parametrize("version_text", ["²", "4", "999"])
def test_fails_on_a_handshake_answer_that_is_not_an_offered_version(version_text):
    with (
        FakeGateway("DUFAKE0001", version_text=version_text) as gw,
        pytest.raises(ib_probe.ProbeError),
    ):
        ask(gw, timeout=0.5)


def test_reports_the_gateways_error_code_when_it_hangs_up():
    with (
        FakeGateway("DUFAKE0001", error_code="326") as gw,
        pytest.raises(ib_probe.ProbeError, match="326"),
    ):
        ask(gw)


def test_fails_when_no_account_message_arrives():
    with FakeGateway(None) as gw, pytest.raises(ib_probe.ProbeError):
        ask(gw, timeout=0.5)


def test_fails_when_nothing_listens():
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
    with pytest.raises(ib_probe.ProbeError):
        ib_probe.managed_accounts("127.0.0.1", port, client_id=7, timeout=0.5)


def test_fails_when_the_peer_is_not_a_gateway():
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        client_error: list[Exception] = []

        def call() -> None:
            try:
                ib_probe.managed_accounts("127.0.0.1", port, client_id=7, timeout=2)
            except ib_probe.ProbeError as e:
                client_error.append(e)

        thread = threading.Thread(target=call)
        thread.start()
        conn, _ = server.accept()
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        conn.close()
        thread.join(timeout=5)
    assert len(client_error) == 1
