#!/usr/bin/env python3
"""Pretend to be one M2 RC2800 controller port on a pseudo-terminal.

Run one per axis. Each prints the device path to point the GUI at:

    python3 tools/fake_m2.py --start 142.3     # azimuth
    python3 tools/fake_m2.py --start 37.0      # elevation

Answers ``Bin;`` with ``AZ<position>;`` and accepts ``APn<val>\r;`` go-to
commands, creeping toward the target on every query so the readout visibly
moves. The reply prefix is a guess at the real controller's format; the
parser only requires two prefix bytes, a number, and a ``;``.
"""
import argparse
import os
import re

NUMBER_RE = re.compile(rb"[-+]?\d+(?:\.\d+)?")
STEP = 0.5


def main():
    parser = argparse.ArgumentParser(description="Fake M2 rotor controller port on a pty")
    parser.add_argument("--start", type=float, default=0.0, help="initial position in degrees")
    args = parser.parse_args()

    master, slave = os.openpty()
    print(os.ttyname(slave), flush=True)

    position = target = args.start
    buffer = b""
    while True:
        try:
            buffer += os.read(master, 64)
        except OSError:
            break
        while b";" in buffer:
            command, buffer = buffer.split(b";", 1)
            command = command.strip()
            if command == b"Bin":
                if abs(target - position) <= STEP:
                    position = target
                elif target > position:
                    position += STEP
                else:
                    position -= STEP
                os.write(master, f"AZ{position:.1f};".encode("ascii"))
                print(f"Bin -> {position:.1f}", flush=True)
            elif command.startswith(b"APn"):
                match = NUMBER_RE.search(command[3:])
                if match:
                    target = float(match.group(0))
                    print(f"go to {target:.1f}", flush=True)
            else:
                print(f"ignored {command!r}", flush=True)


if __name__ == "__main__":
    main()
