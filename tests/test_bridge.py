import socket
import time

import pytest
import serial

import m2rotor
from m2rotor import RotorBridge
from tests.fakes import FakeSerial


def wait_for(predicate, timeout=3.0, message="condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {message}")


class Harness:
    """A bridge wired to two FakeSerial ports, recording every event."""

    def __init__(self, az_position=142.3, el_position=37.0):
        self.az = FakeSerial(position=az_position)
        self.el = FakeSerial(position=el_position)
        self.events = []
        fakes = {"AZ": self.az, "EL": self.el}
        self.bridge = RotorBridge(
            "AZ", "EL", tcp_port=0,
            on_event=lambda kind, payload: self.events.append((kind, payload)),
            serial_factory=lambda device, baud, timeout: fakes[device],
        )

    def statuses(self):
        return [payload for kind, payload in self.events if kind == "status"]

    def logs(self):
        return [payload for kind, payload in self.events if kind == "log"]

    def connect(self):
        client = socket.create_connection(self.bridge.address, timeout=2.0)
        wait_for(lambda: m2rotor.STATUS_CONNECTED in self.statuses(), message="connected status")
        return client


@pytest.fixture
def harness():
    h = Harness()
    h.bridge.start()
    yield h
    h.bridge.stop()


def test_start_listens_and_stop_closes_everything(harness):
    host, port = harness.bridge.address
    assert host == "127.0.0.1" and port > 0
    assert harness.bridge.running
    wait_for(lambda: m2rotor.STATUS_LISTENING in harness.statuses(), message="listening status")
    assert any(f"Listening on 127.0.0.1:{port}" in line for line in harness.logs())

    harness.bridge.stop()
    assert not harness.bridge.running
    assert harness.az.is_open is False and harness.el.is_open is False
    assert harness.statuses()[-1] == m2rotor.STATUS_STOPPED
    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=0.5)


def test_start_failure_closes_ports_already_opened():
    az = FakeSerial()

    def factory(device, baud, timeout):
        if device == "EL":
            raise serial.SerialException("no such port")
        return az

    bridge = RotorBridge("AZ", "EL", tcp_port=0, serial_factory=factory)
    with pytest.raises(serial.SerialException):
        bridge.start()
    assert az.is_open is False
    assert not bridge.running
    assert bridge.address is None


def test_p_returns_both_positions_and_emits_position(harness):
    client = harness.connect()
    client.sendall(b"p\n")
    assert client.recv(1024) == b"142.3\n37.0\n"
    assert ("position", (142.3, 37.0)) in harness.events
    client.close()


def test_malformed_reply_sends_nothing_and_logs(harness):
    harness.el.reply = b"??"
    client = harness.connect()
    client.sendall(b"p\n")
    client.settimeout(0.5)
    with pytest.raises(socket.timeout):
        client.recv(1024)
    assert any("Malformed reply" in line for line in harness.logs())
    client.close()


def test_idle_poll_emits_position_without_a_client():
    h = Harness()
    h.bridge.IDLE_POLL_SECONDS = 0.1
    h.bridge.start()
    try:
        wait_for(lambda: ("position", (142.3, 37.0)) in h.events, message="idle position")
    finally:
        h.bridge.stop()


def test_command_split_across_recv_calls_is_still_framed_correctly(harness):
    client = harness.connect()
    client.sendall(b"p")
    time.sleep(0.05)
    client.sendall(b"\n")
    assert client.recv(1024) == b"142.3\n37.0\n"
    client.close()


def test_run_surfaces_unexpected_exception_and_stop_stays_safe():
    h = Harness()
    h.bridge.IDLE_POLL_SECONDS = 0.1

    def boom():
        raise RuntimeError("boom")

    h.bridge._poll_position = boom
    h.bridge.start()
    try:
        wait_for(lambda: any(kind == "error" for kind, _ in h.events), message="error event")
        wait_for(lambda: not h.bridge.running, message="thread exit")
        assert h.statuses()[-1] == m2rotor.STATUS_STOPPED
        assert ("error", "boom") in h.events
    finally:
        h.bridge.stop()  # must not raise even though the thread already died
    assert h.az.is_open is False and h.el.is_open is False


def ap_writes(port):
    return [w for w in port.writes if w.startswith(b"APn")]


def test_P_acks_and_writes_ap_commands_to_both_ports(harness):
    client = harness.connect()
    client.sendall(b"P 142.3 37.0\n")
    assert client.recv(1024) == b"RPRT 0\n"
    wait_for(lambda: ap_writes(harness.el), message="el APn write")
    assert ap_writes(harness.az) == [b"APn142.3\r;"]
    assert ap_writes(harness.el) == [b"APn37.0\r;"]
    assert any("Set AZ 142.3 EL 37.0" in line for line in harness.logs())
    client.close()


def test_P_clamps_negative_elevation_to_zero(harness):
    client = harness.connect()
    client.sendall(b"P 10 -5\n")
    assert client.recv(1024) == b"RPRT 0\n"
    wait_for(lambda: ap_writes(harness.el), message="el APn write")
    assert ap_writes(harness.el) == [b"APn0.0\r;"]
    client.close()


def test_repeated_identical_P_writes_once(harness):
    client = harness.connect()
    for _ in range(3):
        client.sendall(b"P 90 45\n")
        assert client.recv(1024) == b"RPRT 0\n"
    wait_for(lambda: ap_writes(harness.el), message="el APn write")
    time.sleep(0.1)
    assert len(ap_writes(harness.az)) == 1
    assert len(ap_writes(harness.el)) == 1
    client.close()


def test_bad_P_replies_error_and_keeps_client(harness):
    client = harness.connect()
    client.sendall(b"P 12\n")
    assert client.recv(1024) == b"RPRT -1\n"
    client.sendall(b"p\n")
    assert client.recv(1024) == b"142.3\n37.0\n"
    client.close()


def test_multiple_commands_in_one_packet(harness):
    client = harness.connect()
    client.sendall(b"P 1 2\np\n")
    client.settimeout(2.0)
    received = b""
    while b"37.0\n" not in received:
        received += client.recv(1024)
    assert received == b"RPRT 0\n142.3\n37.0\n"
    client.close()


def test_S_drops_client_and_accepts_the_next_one(harness):
    client = harness.connect()
    client.sendall(b"S\n")
    assert client.recv(1024) == b"RPRT 0\n"
    assert client.recv(1024) == b""  # server closed the connection
    client.close()
    wait_for(lambda: harness.statuses()[-1] == m2rotor.STATUS_LISTENING, message="back to listening")

    again = socket.create_connection(harness.bridge.address, timeout=2.0)
    again.sendall(b"p\n")
    assert again.recv(1024) == b"142.3\n37.0\n"
    again.close()


def test_client_disconnect_returns_to_listening(harness):
    client = harness.connect()
    client.close()
    wait_for(lambda: harness.statuses()[-1] == m2rotor.STATUS_LISTENING, message="back to listening")
    assert "client disconnected" in harness.logs()


def test_serial_error_keeps_client_and_recovers(harness):
    client = harness.connect()
    harness.az.fail = True
    client.sendall(b"P 100 50\n")
    assert client.recv(1024) == b"RPRT 0\n"
    wait_for(lambda: m2rotor.STATUS_SERIAL_ERROR in harness.statuses(), message="serial_error status")
    assert any("Serial error" in line for line in harness.logs())

    harness.az.fail = False
    client.sendall(b"p\n")
    assert client.recv(1024) == b"142.3\n37.0\n"  # same connection still works
    assert harness.statuses()[-1] == m2rotor.STATUS_CONNECTED
    assert "Serial recovered" in harness.logs()
    client.close()


def test_failed_write_is_retried_on_next_identical_P(harness):
    client = harness.connect()
    harness.az.fail = True
    client.sendall(b"P 100 50\n")
    assert client.recv(1024) == b"RPRT 0\n"
    wait_for(lambda: m2rotor.STATUS_SERIAL_ERROR in harness.statuses(), message="serial_error status")
    assert ap_writes(harness.el) == []  # el never written because az raised first

    harness.az.fail = False
    client.sendall(b"P 100 50\n")
    assert client.recv(1024) == b"RPRT 0\n"
    wait_for(lambda: ap_writes(harness.el), message="el APn write")
    assert ap_writes(harness.az) == [b"APn100.0\r;"]
    assert ap_writes(harness.el) == [b"APn50.0\r;"]
    assert harness.statuses()[-1] == m2rotor.STATUS_CONNECTED
    assert "Serial recovered" in harness.logs()
    client.close()
