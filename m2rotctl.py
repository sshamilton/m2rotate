#!/usr/bin/env python3
"""Headless entry point: run the M2 rotor bridge for gpredict without a window.

Uses the ports saved by m2gui.py (~/.config/m2rotate/config.json) unless
overridden on the command line:

    python3 m2rotctl.py --az /dev/ttyUSB0 --el /dev/ttyUSB1 --port 4534
"""
import argparse
import sys
import time

import m2config
import m2ports
from m2rotor import RotorBridge


def print_event(kind, payload):
    stamp = time.strftime("%H:%M:%S")
    if kind == "log":
        print(stamp, payload, flush=True)
    elif kind == "status":
        print(stamp, f"Status: {payload}", flush=True)


def resolve_devices(cfg, args):
    """Command-line device paths win; otherwise resolve the saved USB serial numbers."""
    az = args.az or m2ports.resolve_serial(cfg.get("az_serial"))
    el = args.el or m2ports.resolve_serial(cfg.get("el_serial"))
    return az, el


def main(argv=None):
    parser = argparse.ArgumentParser(description="M2 rotor bridge for gpredict (headless)")
    parser.add_argument("--az", help="azimuth serial device, e.g. /dev/ttyUSB0")
    parser.add_argument("--el", help="elevation serial device, e.g. /dev/ttyUSB1")
    parser.add_argument("--baud", type=int, help="serial baud rate (default from config, 9600)")
    parser.add_argument("--port", type=int, help="TCP port gpredict connects to (default from config, 4534)")
    args = parser.parse_args(argv)

    cfg = m2config.load_config()
    az, el = resolve_devices(cfg, args)
    if az is None or el is None:
        print("Could not find both rotor ports. Pass --az and --el, or pick them in m2gui.py first.",
              file=sys.stderr)
        return 2

    bridge = RotorBridge(az, el, baud=args.baud or cfg["baud"],
                         tcp_port=args.port or cfg["tcp_port"], on_event=print_event)
    try:
        bridge.start()
    except Exception as exc:
        print(f"Failed to start: {exc}", file=sys.stderr)
        return 1
    print(f"Azimuth {az}, elevation {el}. Ctrl-C to stop.", flush=True)
    interrupted = False
    try:
        while bridge.running:
            time.sleep(1)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        bridge.stop()
    if not interrupted:
        print("Bridge stopped unexpectedly.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
