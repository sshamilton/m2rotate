import pytest

from m2rotor import BIN_QUERY, ProtocolError, format_ap_command, parse_bin_reply


def test_bin_query_bytes():
    assert BIN_QUERY == b"Bin;"


def test_parse_reply_with_two_char_prefix_and_terminator():
    assert parse_bin_reply(b"AZ142.3;") == 142.3


def test_parse_reply_with_small_value():
    assert parse_bin_reply(b"EL37.0;") == 37.0


def test_parse_reply_ignores_trailing_bytes_after_terminator():
    assert parse_bin_reply(b"AZ142.3;junk") == 142.3


def test_parse_reply_accepts_integer_value():
    assert parse_bin_reply(b"AZ142;") == 142.0


def test_parse_reply_too_short_raises():
    with pytest.raises(ProtocolError):
        parse_bin_reply(b"")
    with pytest.raises(ProtocolError):
        parse_bin_reply(b"A;")


def test_parse_reply_garbage_raises():
    with pytest.raises(ProtocolError):
        parse_bin_reply(b"??????;")


def test_parse_reply_terminator_before_number_raises():
    with pytest.raises(ProtocolError):
        parse_bin_reply(b"AZ;142.3")


def test_format_ap_command_one_decimal():
    assert format_ap_command(142.3) == b"APn142.3\r;"


def test_format_ap_command_rounds_to_one_decimal():
    assert format_ap_command(142.36) == b"APn142.4\r;"


def test_format_ap_command_zero():
    assert format_ap_command(0.0) == b"APn0.0\r;"


from m2rotor import query_position, read_position
from tests.fakes import FakeSerial


def test_read_position_sends_bin_and_parses_reply():
    port = FakeSerial(position=142.3)
    assert read_position(port) == 142.3
    assert port.writes == [b"Bin;"]


def test_read_position_malformed_raises():
    port = FakeSerial(reply=b"??")
    with pytest.raises(ProtocolError):
        read_position(port)


def test_query_position_opens_reads_and_closes(monkeypatch):
    opened = {}
    fake = FakeSerial(position=37.0)

    def fake_serial(device, baud, timeout):
        opened.update(device=device, baud=baud, timeout=timeout)
        return fake

    import m2rotor
    monkeypatch.setattr(m2rotor.serial, "Serial", fake_serial)
    assert query_position("/dev/ttyUSB9", baud=19200, timeout=0.5) == 37.0
    assert opened == {"device": "/dev/ttyUSB9", "baud": 19200, "timeout": 0.5}
    assert fake.is_open is False
