# M2 Rotor Bridge GUI — Design

Date: 2026-09-21
Status: approved for planning

## Goal

Add a small Tkinter GUI to the existing hamlib-to-M2 rotor bridge so that the
azimuth and elevation serial ports can be chosen from a list, tested, and
remembered, and so the bridge's health and current antenna position are
visible without reading a terminal.

Out of scope: anything to do with the Icom IC-9700. gpredict drives the
radio itself. Manual rotor slewing (go-to, park) is also out of scope.

## Platform

Linux only, on the shack PC that runs gpredict. Python 3, Tkinter (ships
with Python on Linux), pyserial. No other dependencies.

Development happens on the Mac. Unit tests run on the Mac. Real hardware
testing happens on the shack PC.

## Architecture

Three modules plus a headless entry point.

### `m2rotor.py` — core

- `RotorBridge` class. Owns both serial ports and the TCP server gpredict
  connects to. Constructor takes az device path, el device path, baud, TCP
  host/port, and an `on_event` callback.
- `start()` opens both serial ports, binds and listens on TCP, and launches
  the serve loop on a background thread. Raises on serial or socket open
  failure; nothing is left half-open.
- `stop()` signals the thread, closes the client connection if any, closes
  the listening socket and both serial ports, and joins the thread.
- Serve loop protocol is unchanged from today's `m2rotctl.py`:
  - `p`: send `Bin;` to az then el, parse each 8-byte reply, respond
    `"<az>\n<el>\n"`. On a malformed reply, log a warning and send nothing.
  - `P <az> <el>`: clamp el below 0 to 0, respond `RPRT 0\n`, then write
    `APn<val>\r;` with one decimal place to each port. Skip the write when
    az and el both match the last commanded values.
  - `S`: log, close the client, and wait for the next connection.
  - Client disconnect (empty recv): same as `S`.
- Idle polling: when no client is connected, the loop uses a 1 s accept
  timeout and polls both ports with `Bin;` between accepts so the GUI
  readout stays live.
- Events delivered via `on_event(kind, payload)` from the bridge thread.
  Kinds: `log` (str), `position` ((az, el) floats), `status` (one of
  `stopped`, `listening`, `connected`, `serial_error`), `error` (str).
  The GUI is responsible for marshalling these onto the Tk thread.
- `query_position(device, baud=9600, timeout=1.0)`: standalone function.
  Opens the port, sends `Bin;`, parses the reply, closes the port, returns a
  float or raises. Used by the GUI Test buttons.
- `parse_bin_reply(bytes) -> float` and `format_ap_command(float) -> bytes`
  are module-level pure functions so they can be unit tested directly.
- No `pdb`, no `print`. All output goes through `on_event`.

### `m2ports.py` — discovery

- `list_usb_ports() -> list[PortInfo]` wrapping
  `serial.tools.list_ports.comports()`, filtered to entries with a USB VID
  so Bluetooth and console ports are excluded. `PortInfo` carries `device`,
  `serial_number`, `manufacturer`, `product`, and a `label` string of the
  form `"/dev/ttyUSB0  ftDZZ3P9  FT232R USB UART"`.
- `resolve_serial(serial_number) -> str | None`: returns today's device
  path for a saved USB serial number, or `None` if not plugged in.

### `m2gui.py` — window

- Tkinter, single window titled "M2 Rotor Bridge".
- Never imports pyserial directly; uses `m2ports` and `m2rotor` only.
- Config at `~/.config/m2rotate/config.json` with keys `az_serial`,
  `el_serial`, `baud`, `tcp_port`. Ports are stored by USB serial number,
  never by device path. Saved on Start and on window close. Loaded on
  launch and resolved to device paths.

### `m2rotctl.py` — headless entry point

Rewritten as a thin wrapper: load the same config file, resolve ports,
construct `RotorBridge` with a callback that prints log lines, run until
Ctrl-C. Keeps the existing gpredict setup working without a display.
Optional `--az`, `--el`, `--baud`, `--port` flags override the config.

`m2rotate.py` (old Windows DDE version) is left untouched.

## Window layout

```
┌ M2 Rotor Bridge ──────────────────────────────────────┐
│ Azimuth port    [ /dev/ttyUSB0  ftDZZ3P9  FT232R ▾ ] [Test] │
│ Elevation port  [ /dev/ttyUSB1  A5020LVA  FT232R ▾ ] [Test] │
│ Baud [9600]   gpredict port [4534]          [Refresh] │
│ Hint: both ports answer Bin; — nudge the antenna and  │
│ see which reading changes to tell AZ from EL.         │
│                                                       │
│      Azimuth              Elevation                   │
│      142.3°                 37.0°                     │
│                                                       │
│ Status: Client connected                [ Stop ]      │
├───────────────────────────────────────────────────────┤
│ 18:02:11 Listening on 127.0.0.1:4534                  │
│ 18:02:15 gpredict connected from 127.0.0.1            │
│ 18:02:15 Set AZ 142.3 EL 37.0                         │
└───────────────────────────────────────────────────────┘
```

Behavior:

- Port pickers are read-only comboboxes populated from `list_usb_ports()`.
  Refresh rescans. A saved port that is not currently present is shown as
  "not found (ftDZZ3P9)" in red and Start stays disabled.
- Test calls `query_position` on that picker's port and shows
  "AZ reads 142.3" / "EL reads 37.0" or "no response" beside the button.
  Test buttons are disabled while the bridge is running.
- Start is enabled only when both ports are chosen, both are present, and
  they differ. Start becomes Stop while running.
- Readout shows the latest `position` event as large numbers with one
  decimal. Status line shows Stopped / Listening on <port> / Client
  connected / Serial error (red).
- Log pane is a read-only scrolling text widget, timestamped, capped at
  the last 500 lines.
- Bridge events arrive on the bridge thread and are queued; the GUI drains
  the queue with `after(100, ...)`.
- Window close stops the bridge, saves config, then exits.

## Error handling

- Serial or socket open failure on Start: error shown in the status line
  and the log, bridge not started, ports not left open.
- Malformed `Bin;` reply: warning logged, no response sent for that poll.
- Serial write or read error while running: logged, status set to
  `serial_error`, TCP client kept connected so gpredict does not fall over.
  Next successful poll clears the status back to `connected`/`listening`.
- Controller unplugged mid-session follows the same path as above.
- No debugger hooks anywhere.

## Testing

Unit tests with pytest in `tests/`, runnable on the Mac with no hardware.
A fake serial object records writes and returns scripted replies.

- `parse_bin_reply`: valid replies, short replies, garbage, missing `;`.
- `format_ap_command`: one decimal place, negative el clamped upstream.
- `RotorBridge` over a real local TCP socket with fake serial ports:
  `p` returns both values; `P` writes both `APn` commands and replies
  `RPRT 0`; repeated identical `P` does not rewrite; `S` drops the client
  and a new client can connect; malformed reply sends nothing; serial
  exception emits `serial_error` and keeps the client; `stop()` closes
  everything and joins.
- `m2ports`: label formatting, USB filter, `resolve_serial` hit and miss,
  using a patched `comports()`.
- GUI enable/disable rule: Start disabled when ports missing or identical.

Manual test on the Mac: two `socat` pty pairs with a tiny script answering
`Bin;` with canned M2 replies, GUI pointed at the ptys, `nc` acting as
gpredict.

Shack PC checklist:

1. `pip install pyserial pytest`, `python3 -m pytest`.
2. Launch `m2gui.py`, plug in the controller, Refresh, confirm both FTDI
   serial numbers appear.
3. Test each port, nudge the antenna, confirm AZ and EL are assigned
   correctly, Start.
4. In gpredict, engage the rotor; confirm readout tracks and the antenna
   moves.
5. Close and relaunch; confirm the ports are remembered and resolve.
6. Run `m2rotctl.py` headless once to confirm the fallback still works.
