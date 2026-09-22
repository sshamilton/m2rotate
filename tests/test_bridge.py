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
