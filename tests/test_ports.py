from types import SimpleNamespace

import m2ports
from m2ports import PortInfo, list_usb_ports, resolve_serial


def fake_comport(device, vid=0x0403, serial_number=None, manufacturer=None, product=None):
    return SimpleNamespace(
        device=device, vid=vid, serial_number=serial_number,
        manufacturer=manufacturer, product=product,
    )


FTDI_AZ = fake_comport("/dev/ttyUSB0", serial_number="ftDZZ3P9", manufacturer="FTDI", product="FT232R USB UART")
FTDI_EL = fake_comport("/dev/ttyUSB1", serial_number="A5020LVA", manufacturer="FTDI", product="FT232R USB UART")
BLUETOOTH = fake_comport("/dev/cu.Bluetooth-Incoming-Port", vid=None)


def test_list_usb_ports_filters_out_non_usb_and_sorts_by_device():
    ports = list_usb_ports(comports=lambda: [BLUETOOTH, FTDI_EL, FTDI_AZ])
    assert [p.device for p in ports] == ["/dev/ttyUSB0", "/dev/ttyUSB1"]
    assert ports[0] == PortInfo("/dev/ttyUSB0", "ftDZZ3P9", "FTDI", "FT232R USB UART")


def test_label_shows_device_serial_and_product():
    port = PortInfo("/dev/ttyUSB0", "ftDZZ3P9", "FTDI", "FT232R USB UART")
    assert port.label == "/dev/ttyUSB0  ftDZZ3P9  FT232R USB UART"


def test_label_skips_missing_fields():
    assert PortInfo("/dev/ttys003", None, None, None).label == "/dev/ttys003"


def test_resolve_serial_hit():
    ports = list_usb_ports(comports=lambda: [FTDI_AZ, FTDI_EL])
    assert resolve_serial("A5020LVA", ports=ports) == "/dev/ttyUSB1"


def test_resolve_serial_miss_and_none():
    ports = list_usb_ports(comports=lambda: [FTDI_AZ])
    assert resolve_serial("nope", ports=ports) is None
    assert resolve_serial(None, ports=ports) is None


def test_resolve_serial_scans_when_no_ports_given(monkeypatch):
    monkeypatch.setattr(m2ports, "list_usb_ports", lambda: [PortInfo("/dev/ttyUSB7", "ftDZZ3P9", None, None)])
    assert resolve_serial("ftDZZ3P9") == "/dev/ttyUSB7"
