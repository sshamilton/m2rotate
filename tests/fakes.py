"""A stand-in for serial.Serial that behaves like one M2 controller port."""
import serial


class FakeSerial:
    """Answers ``Bin;`` with ``AZ<position>;`` and records every write.

    ``reply`` overrides the answer verbatim (for malformed-reply tests).
    ``fail`` makes every write raise SerialException (for error tests).
    Both can be flipped at any time while a bridge is using the port.
    """

    def __init__(self, position=0.0, reply=None, fail=False):
        self.position = position
        self.reply = reply
        self.fail = fail
        self.writes = []
        self.is_open = True
        self.flushes = 0

    def reset_input_buffer(self):
        self.flushes += 1

    def write(self, data):
        if self.fail:
            raise serial.SerialException("fake port failure")
        self.writes.append(bytes(data))
        return len(data)

    def read_until(self, expected=b";", size=None):
        if self.reply is not None:
            return self.reply
        return f"AZ{self.position:.1f};".encode("ascii")

    def close(self):
        self.is_open = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
