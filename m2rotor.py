"""Core bridge between the hamlib rotctld protocol (as spoken by gpredict)
and an M2 RC2800 rotor controller with separate azimuth and elevation ports.

No printing and no debugger hooks here: everything the outside world needs
to know is delivered through an ``on_event`` callback.
"""
import re

BIN_QUERY = b"Bin;"
_NUMBER_RE = re.compile(rb"[-+]?\d+(?:\.\d+)?")


class ProtocolError(ValueError):
    """The controller answered with something we cannot parse."""


def parse_bin_reply(reply: bytes) -> float:
    """Parse the controller's reply to ``Bin;``.

    The M2 answers with a two character prefix, the position, and a ``;``
    terminator. Skipping the first two bytes mirrors the slicing in the
    original script. Anything after the first ``;`` is ignored.
    """
    if len(reply) < 3:
        raise ProtocolError(f"reply too short: {reply!r}")
    body = reply[2:].split(b";")[0]
    match = _NUMBER_RE.search(body)
    if match is None:
        raise ProtocolError(f"no number in reply: {reply!r}")
    return float(match.group(0))


def format_ap_command(value: float) -> bytes:
    """Build the ``APn`` go-to command. The controller wants one decimal."""
    return f"APn{value:.1f}\r;".encode("ascii")
