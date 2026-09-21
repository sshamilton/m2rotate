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
