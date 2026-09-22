"""Find USB serial adapters and map saved USB serial numbers back to device paths.

Device paths like /dev/ttyUSB2 change between reboots; USB serial numbers
(for example the FTDI ``ftDZZ3P9`` on the M2 controller) do not. The config
stores serial numbers and this module turns them back into paths.
"""
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

from serial.tools import list_ports


@dataclass(frozen=True)
class PortInfo:
    device: str
    serial_number: Optional[str]
    manufacturer: Optional[str]
    product: Optional[str]

    @property
    def label(self) -> str:
        """Text shown in the GUI picker: path, serial number, product."""
        return "  ".join(part for part in (self.device, self.serial_number, self.product) if part)


def list_usb_ports(comports: Optional[Callable[[], Iterable]] = None) -> List[PortInfo]:
    """Return USB serial ports sorted by device path.

    Entries without a USB vendor id (Bluetooth, debug consoles) are dropped.
    ``comports`` is injectable for tests; it defaults to pyserial's scanner.
    """
    scan = comports or list_ports.comports
    ports = [
        PortInfo(p.device, p.serial_number, p.manufacturer, p.product)
        for p in scan()
        if getattr(p, "vid", None) is not None
    ]
    return sorted(ports, key=lambda p: p.device)


def resolve_serial(serial_number: Optional[str], ports: Optional[List[PortInfo]] = None) -> Optional[str]:
    """Return today's device path for a USB serial number, or None if absent."""
    if not serial_number:
        return None
    if ports is None:
        ports = list_usb_ports()
    for port in ports:
        if port.serial_number == serial_number:
            return port.device
    return None
