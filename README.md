# m2rotate

Bridges gpredict's rotctld protocol to an M2 RC2800 rotor controller that
has separate azimuth and elevation serial ports. Runs on the Linux shack PC
next to gpredict. The Icom IC-9700 is driven by gpredict/hamlib directly and
is not part of this tool (see IC9700-Connection-Notes.txt).

## Install (Linux)

    sudo apt install python3-tk python3-venv
    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt

## Run the GUI

    python3 m2gui.py

1. Plug in the controller and click Refresh. Both FTDI adapters appear with
   their USB serial numbers.
2. Click Test on each picker. Both answer the same query, so nudge the
   antenna and see which reading changes to tell azimuth from elevation.
3. Click Start. In gpredict, set the rotator to `localhost` port `4534`
   (rotctld protocol) and engage it.

Your picks are saved by USB serial number in `~/.config/m2rotate/config.json`
and restored next launch, even if /dev/ttyUSB numbering changes.

## Run headless

    python3 m2rotctl.py                 # uses the saved ports
    python3 m2rotctl.py --az /dev/ttyUSB0 --el /dev/ttyUSB1 --port 4534

## Tests

    python3 -m pytest -q

Manual test without hardware: run `tools/fake_m2.py --start 142.3` and
`tools/fake_m2.py --start 37.0` in two terminals, then
`python3 m2gui.py --az <first pty> --el <second pty>` and talk to port 4534
with `nc` using `p`, `P 150 45`, `S`.

## Shack PC checklist

1. `python3 -m pytest -q` passes.
2. Launch `m2gui.py`, plug in the controller, Refresh, confirm both FTDI
   serial numbers appear (`ftDZZ3P9`, `A5020LVA`).
3. Test each port, nudge the antenna, confirm AZ and EL are assigned
   correctly, Start.
4. In gpredict, engage the rotor; confirm the readout tracks and the antenna
   moves.
5. Close and relaunch; confirm the ports are remembered and resolve.
6. Run `m2rotctl.py` headless once to confirm the fallback still works.

## Files

- `m2rotor.py` — protocol helpers and the `RotorBridge` core
- `m2ports.py` — USB serial port discovery
- `m2config.py` — settings file
- `m2gui.py` — Tkinter window
- `m2rotctl.py` — headless entry point
- `m2rotate.py` — old Windows/DDE version, kept for reference
