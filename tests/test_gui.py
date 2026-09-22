import pytest

pytest.importorskip("tkinter")

from m2gui import start_allowed
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
