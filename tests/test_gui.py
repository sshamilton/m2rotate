import tempfile
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import m2rotor
from m2gui import App, start_allowed
from m2ports import PortInfo

AZ = PortInfo("/dev/ttyUSB0", "ftDZZ3P9", "FTDI", "FT232R USB UART")
EL = PortInfo("/dev/ttyUSB1", "A5020LVA", "FTDI", "FT232R USB UART")


def test_start_allowed_with_two_different_ports():
    assert start_allowed(AZ, EL) is True


def test_start_blocked_when_a_port_is_missing():
    assert start_allowed(None, EL) is False
    assert start_allowed(AZ, None) is False
    assert start_allowed(None, None) is False


def test_start_blocked_when_same_device_picked_twice():
    assert start_allowed(AZ, AZ) is False
    assert start_allowed(AZ, PortInfo("/dev/ttyUSB0", None, None, "manual")) is False


@pytest.fixture
def app():
    config_path = Path(tempfile.mkdtemp()) / "config.json"
    instance = App(config_path=config_path)
    try:
        yield instance
    finally:
        instance.destroy()


def test_find_index_prefers_serial_number_over_stale_device_path(app):
    app._ports = [
        PortInfo("/dev/ttyUSB0", "SERIAL_B", None, None),
        PortInfo("/dev/ttyUSB1", "SERIAL_A", None, None),
    ]
    assert app._find_index("SERIAL_A", "/dev/ttyUSB0") == 1
    assert app._find_index(None, "/dev/ttyUSB0") == 0


def test_abnormal_stop_resets_the_gui(app):
    class StandInBridge:
        running = False

        def stop(self):
            pass

    bridge = StandInBridge()
    app._bridge = bridge
    app.start_button.configure(text="Stop")
    app._apply_event("status", m2rotor.STATUS_STOPPED)
    assert app._bridge is None
    assert app.start_button.cget("text") == "Start"

    bridge.running = True
    app._bridge = bridge
    app.start_button.configure(text="Stop")
    app._apply_event("status", m2rotor.STATUS_STOPPED)
    assert app._bridge is bridge
