#!/usr/bin/env python3
"""Tkinter window for the M2 rotor bridge.

Pick the azimuth and elevation serial ports from a list of USB adapters,
Test each one, Start the bridge gpredict connects to, and watch the status,
log and live antenna position. Ports are remembered by USB serial number in
~/.config/m2rotate/config.json.

For testing without hardware, extra devices (for example ptys from
tools/fake_m2.py) can be offered in the pickers:

    python3 m2gui.py --az /dev/ttys003 --el /dev/ttys004
"""
import argparse
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import m2config
import m2ports
import m2rotor
from m2ports import PortInfo

LOG_MAX_LINES = 500
RED = "#b00020"
HINT = ("Hint: both controller ports answer Bin; identically. Test each, then nudge the "
        "antenna in gpredict or on the controller and see which reading changes to tell AZ from EL.")
STATUS_TEXT = {
    m2rotor.STATUS_STOPPED: "Stopped",
    m2rotor.STATUS_CONNECTED: "Client connected",
    m2rotor.STATUS_SERIAL_ERROR: "Serial error",
}


def start_allowed(az, el):
    """Start is allowed only when both ports are chosen and are different devices."""
    return az is not None and el is not None and az.device != el.device


class App(tk.Tk):
    def __init__(self, extra_ports=(), config_path=m2config.CONFIG_PATH):
        super().__init__()
        self.title("M2 Rotor Bridge")
        self.minsize(520, 420)
        self._config_path = config_path
        self._cfg = m2config.load_config(config_path)
        self._extra_ports = list(extra_ports)
        self._ports = []
        self._bridge = None
        self._events = queue.Queue()
        self._build_widgets()
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)

    # ---- widgets -------------------------------------------------------

    def _build_picker(self, parent, row, text, which):
        """Build one Azimuth/Elevation picker row: label, combobox, Test button, result label."""
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=2)
        combo = ttk.Combobox(parent, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._update_start_state())
        test = ttk.Button(parent, text="Test", width=5, command=lambda: self.test_port(which))
        test.grid(row=row, column=2)
        result = ttk.Label(parent, text="", width=22)
        result.grid(row=row, column=3, sticky="w", padx=4)
        setattr(self, f"{which}_combo", combo)
        setattr(self, f"{which}_test", test)
        setattr(self, f"{which}_result", result)

    def _build_widgets(self):
        top = ttk.Frame(self, padding=(8, 8, 8, 2))
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        self._build_picker(top, 0, "Azimuth port", "az")
        self._build_picker(top, 1, "Elevation port", "el")

        settings = ttk.Frame(top)
        settings.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 2))
        ttk.Label(settings, text="Baud").pack(side="left")
        self.baud_entry = ttk.Entry(settings, width=7)
        self.baud_entry.insert(0, str(self._cfg["baud"]))
        self.baud_entry.pack(side="left", padx=(4, 12))
        ttk.Label(settings, text="gpredict port").pack(side="left")
        self.port_entry = ttk.Entry(settings, width=7)
        self.port_entry.insert(0, str(self._cfg["tcp_port"]))
        self.port_entry.pack(side="left", padx=4)
        self.refresh_button = ttk.Button(settings, text="Refresh", command=self.refresh_ports)
        self.refresh_button.pack(side="right")

        ttk.Label(top, text=HINT, wraplength=500, foreground="#555").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(2, 6))

        readout = ttk.Frame(self, padding=8)
        readout.pack(fill="x")
        readout.columnconfigure(0, weight=1)
        readout.columnconfigure(1, weight=1)
        ttk.Label(readout, text="Azimuth").grid(row=0, column=0)
        ttk.Label(readout, text="Elevation").grid(row=0, column=1)
        big = ("Helvetica", 36)
        self.az_value = ttk.Label(readout, text="---.-°", font=big)
        self.az_value.grid(row=1, column=0)
        self.el_value = ttk.Label(readout, text="--.-°", font=big)
        self.el_value.grid(row=1, column=1)

        status_row = ttk.Frame(self, padding=(8, 2, 8, 6))
        status_row.pack(fill="x")
        self.status_label = ttk.Label(status_row, text="Status: Stopped")
        self.status_label.pack(side="left")
        self.start_button = ttk.Button(status_row, text="Start", width=8, command=self.toggle_bridge)
        self.start_button.pack(side="right")

        self.log = ScrolledText(self, height=10, state="disabled", wrap="none",
                                font=("Menlo", 11) if self.tk.call("tk", "windowingsystem") == "aqua" else ("Monospace", 10))
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ---- ports ---------------------------------------------------------

    def refresh_ports(self):
        """Rescan USB ports, keep or restore each picker's selection, update Start."""
        previous = (self._selected(self.az_combo), self._selected(self.el_combo))
        self._ports = m2ports.list_usb_ports() + self._extra_ports
        labels = [p.label for p in self._ports]
        pickers = (
            (self.az_combo, self.az_result, "az_serial", previous[0]),
            (self.el_combo, self.el_result, "el_serial", previous[1]),
        )
        for combo, result, key, current in pickers:
            combo["values"] = labels
            wanted_serial = current.serial_number if current else self._cfg.get(key)
            wanted_device = current.device if current else None
            index = self._find_index(wanted_serial, wanted_device)
            if index is not None:
                combo.current(index)
                self._set_label(result, "")
            else:
                combo.set("")
                if wanted_serial:
                    self._set_label(result, f"not found ({wanted_serial})", RED)
        self._log(f"Found {len(self._ports)} serial port(s)")
        self._update_start_state()

    def _find_index(self, serial_number, device):
        for index, port in enumerate(self._ports):
            if serial_number and port.serial_number == serial_number:
                return index
            if device and port.device == device:
                return index
        return None

    def _selected(self, combo):
        index = combo.current()
        return self._ports[index] if 0 <= index < len(self._ports) else None

    def test_port(self, which):
        """Send Bin; on the chosen port in a worker thread and show the reply."""
        combo, result = (self.az_combo, self.az_result) if which == "az" else (self.el_combo, self.el_result)
        port = self._selected(combo)
        if port is None:
            return
        self._set_label(result, "testing...")
        baud = self._int_entry(self.baud_entry, m2config.DEFAULTS["baud"])

        def worker():
            try:
                value = m2rotor.query_position(port.device, baud)
                self._events.put(("test", (which, f"{which.upper()} reads {value:.1f}", None)))
            except Exception as exc:
                self._events.put(("log", f"Test {port.device}: {exc}"))
                self._events.put(("test", (which, "no response", RED)))

        threading.Thread(target=worker, name=f"test-{which}", daemon=True).start()

    # ---- bridge --------------------------------------------------------

    def toggle_bridge(self):
        if self._bridge is not None:
            self._stop_bridge()
            return
        az, el = self._selected(self.az_combo), self._selected(self.el_combo)
        if not start_allowed(az, el):
            return
        baud = self._int_entry(self.baud_entry, m2config.DEFAULTS["baud"])
        tcp_port = self._int_entry(self.port_entry, m2config.DEFAULTS["tcp_port"])
        bridge = m2rotor.RotorBridge(
            az.device, el.device, baud=baud, tcp_port=tcp_port,
            on_event=lambda kind, payload: self._events.put((kind, payload)),
        )
        try:
            bridge.start()
        except Exception as exc:
            self._set_status(f"Failed to start: {exc}", RED)
            self._log(f"Failed to start: {exc}")
            return
        self._bridge = bridge
        self._capture_settings()
        self._save_config()
        self.start_button.configure(text="Stop")
        self._update_start_state()

    def _stop_bridge(self):
        bridge, self._bridge = self._bridge, None
        if bridge is not None:
            bridge.stop()
        self.start_button.configure(text="Start")
        self._update_start_state()

    def _update_start_state(self):
        running = self._bridge is not None
        allowed = start_allowed(self._selected(self.az_combo), self._selected(self.el_combo))
        self.start_button.configure(state="normal" if (running or allowed) else "disabled")
        for button in (self.az_test, self.el_test, self.refresh_button):
            button.configure(state="disabled" if running else "normal")
        for combo in (self.az_combo, self.el_combo):
            combo.configure(state="disabled" if running else "readonly")
        for entry in (self.baud_entry, self.port_entry):
            entry.configure(state="disabled" if running else "normal")

    # ---- events from the bridge thread ---------------------------------

    def _drain_events(self):
        try:
            while True:
                kind, payload = self._events.get_nowait()
                self._apply_event(kind, payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _apply_event(self, kind, payload):
        if kind == "log":
            self._log(payload)
        elif kind == "position":
            az, el = payload
            self.az_value.configure(text=f"{az:.1f}°")
            self.el_value.configure(text=f"{el:.1f}°")
        elif kind == "status":
            if payload == m2rotor.STATUS_LISTENING:
                text = f"Listening on {self._int_entry(self.port_entry, m2config.DEFAULTS['tcp_port'])}"
            else:
                text = STATUS_TEXT.get(payload, payload)
            self._set_status(text, RED if payload == m2rotor.STATUS_SERIAL_ERROR else None)
        elif kind == "test":
            which, text, color = payload
            self._set_label(self.az_result if which == "az" else self.el_result, text, color)
        # "error" events are already logged by the bridge; nothing extra to show.

    # ---- small helpers -------------------------------------------------

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')} {text}\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_MAX_LINES:
            self.log.delete("1.0", f"{lines - LOG_MAX_LINES + 1}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text, color=None):
        self.status_label.configure(text=f"Status: {text}", foreground=color or "")

    @staticmethod
    def _set_label(label, text, color=None):
        label.configure(text=text, foreground=color or "")

    @staticmethod
    def _int_entry(entry, default):
        try:
            return int(entry.get().strip())
        except ValueError:
            return default

    def _capture_settings(self):
        """Copy the current picks into the config dict. Manual ports have no serial and are not saved."""
        az, el = self._selected(self.az_combo), self._selected(self.el_combo)
        if az is not None and az.serial_number:
            self._cfg["az_serial"] = az.serial_number
        if el is not None and el.serial_number:
            self._cfg["el_serial"] = el.serial_number
        self._cfg["baud"] = self._int_entry(self.baud_entry, m2config.DEFAULTS["baud"])
        self._cfg["tcp_port"] = self._int_entry(self.port_entry, m2config.DEFAULTS["tcp_port"])

    def _save_config(self):
        try:
            m2config.save_config(self._cfg, self._config_path)
        except OSError as exc:
            self._log(f"Could not save settings: {exc}")

    def _on_close(self):
        self._stop_bridge()
        self._capture_settings()
        self._save_config()
        self.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="M2 rotor bridge GUI")
    parser.add_argument("--az", help="extra azimuth device to offer in the picker (e.g. a pty for testing)")
    parser.add_argument("--el", help="extra elevation device to offer in the picker")
    args = parser.parse_args(argv)
    extra = [PortInfo(device, None, None, "manual") for device in (args.az, args.el) if device]
    App(extra_ports=extra).mainloop()


if __name__ == "__main__":
    main()
