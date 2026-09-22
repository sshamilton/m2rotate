"""Core bridge between the hamlib rotctld protocol (as spoken by gpredict)
and an M2 RC2800 rotor controller with separate azimuth and elevation ports.

No printing and no debugger hooks here: everything the outside world needs
to know is delivered through an ``on_event`` callback.
"""
import re
import socket
import threading

import serial

BIN_QUERY = b"Bin;"
_NUMBER_RE = re.compile(rb"[-+]?\d+(?:\.\d+)?")

STATUS_STOPPED = "stopped"
STATUS_LISTENING = "listening"
STATUS_CONNECTED = "connected"
STATUS_SERIAL_ERROR = "serial_error"


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


def read_position(port) -> float:
    """Send ``Bin;`` on an already open port and return the parsed position."""
    port.reset_input_buffer()
    port.write(BIN_QUERY)
    reply = port.read_until(b";", 32)
    return parse_bin_reply(reply)


def query_position(device: str, baud: int = 9600, timeout: float = 1.0) -> float:
    """Open ``device``, ask where it is, close it. Used by the GUI Test buttons."""
    with serial.Serial(device, baud, timeout=timeout) as port:
        return read_position(port)


class RotorBridge:
    """Serves gpredict's rotctld protocol over TCP and drives the two M2 ports.

    Runs on its own thread after ``start()``. Reports through
    ``on_event(kind, payload)`` called from that thread, with kind one of
    ``"log"`` (str), ``"position"`` ((az, el) floats), ``"status"`` (one of
    the STATUS_* constants) or ``"error"`` (str). The GUI must marshal these
    onto the Tk thread itself.
    """

    IDLE_POLL_SECONDS = 1.0

    def __init__(self, az_device, el_device, baud=9600, host="127.0.0.1",
                 tcp_port=4534, on_event=None, serial_factory=serial.Serial):
        self.az_device = az_device
        self.el_device = el_device
        self.baud = baud
        self.host = host
        self.tcp_port = tcp_port
        self._on_event = on_event or (lambda kind, payload: None)
        self._serial_factory = serial_factory
        self._az = None
        self._el = None
        self._server = None
        self._client = None
        self._thread = None
        self._stop = threading.Event()
        self._last_target = None
        self._in_error = False

    # ---- lifecycle -----------------------------------------------------

    @property
    def address(self):
        """(host, port) actually bound, or None when not started."""
        return self._server.getsockname()[:2] if self._server is not None else None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Open both ports and the TCP listener, then start serving.

        Raises whatever the serial or socket open raised. Nothing is left
        half-open on failure.
        """
        if self.running:
            return
        self._close_all()
        try:
            self._az = self._serial_factory(self.az_device, self.baud, timeout=1.0)
            self._el = self._serial_factory(self.el_device, self.baud, timeout=1.0)
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((self.host, self.tcp_port))
            self._server.listen(1)
            self._server.settimeout(self.IDLE_POLL_SECONDS)
        except Exception:
            self._close_all()
            raise
        self._stop.clear()
        self._last_target = None
        self._in_error = False
        self._thread = threading.Thread(target=self._run, name="m2rotor", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop serving, drop any client, close the ports. Safe to call twice."""
        self._stop.set()
        client = self._client
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._close_all()
        self._emit("status", STATUS_STOPPED)

    def _close_all(self):
        for attr in ("_client", "_server", "_az", "_el"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _emit(self, kind, payload):
        try:
            self._on_event(kind, payload)
        except Exception:
            pass  # a misbehaving listener must not kill the bridge

    # ---- serving -------------------------------------------------------

    def _run(self):
        host, port = self.address
        self._emit("log", f"Listening on {host}:{port}")
        self._emit("status", STATUS_LISTENING)
        try:
            while not self._stop.is_set():
                try:
                    conn, addr = self._server.accept()
                except socket.timeout:
                    self._poll_position()  # keep the readout live with no client
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                self._emit("log", f"gpredict connected from {addr[0]}")
                self._emit("status", STATUS_CONNECTED)
                self._serve_client(conn)
                if not self._stop.is_set():
                    self._emit("status", STATUS_LISTENING)
        except Exception as exc:
            self._emit("log", f"Bridge stopped unexpectedly: {exc}")
            self._emit("error", str(exc))
            self._emit("status", STATUS_STOPPED)

    def _serve_client(self, conn):
        self._client = conn
        conn.settimeout(self.IDLE_POLL_SECONDS)
        buffer = b""
        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buffer += data
                keep_going = True
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.decode("ascii", "replace").strip()
                    if line and not self._handle_command(line, conn):
                        keep_going = False
                        break
                if not keep_going:
                    break
        finally:
            self._client = None
            try:
                conn.close()
            except OSError:
                pass
            self._emit("log", "client disconnected")

    def _send(self, conn, text):
        try:
            conn.sendall(text.encode("ascii"))
        except OSError:
            pass

    def _handle_command(self, line, conn):
        """Handle one rotctld command line. Return False to drop the client."""
        parts = line.split()
        cmd = parts[0][0]
        if cmd == "p":
            position = self._poll_position()
            if position is not None:
                az, el = position
                self._send(conn, f"{az:.1f}\n{el:.1f}\n")
            return True
        if cmd == "P":
            try:
                az, el = float(parts[1]), float(parts[2])
            except (IndexError, ValueError):
                self._emit("log", f"Bad set command {line!r}")
                self._send(conn, "RPRT -1\n")
                return True
            el = max(el, 0.0)  # never send a negative elevation to the rotor
            self._send(conn, "RPRT 0\n")  # set commands require an acknowledgement
            if (az, el) != self._last_target:
                self._emit("log", f"Set AZ {az:.1f} EL {el:.1f}")
                if self._write_target(az, el):
                    self._last_target = (az, el)
            return True
        if cmd in ("S", "q"):
            self._emit("log", "Shutdown command received")
            self._send(conn, "RPRT 0\n")
            return False
        self._emit("log", f"Ignored command {line!r}")
        return True

    # ---- controller I/O ------------------------------------------------

    def _write_target(self, az, el):
        try:
            self._az.write(format_ap_command(az))
            self._el.write(format_ap_command(el))
        except (serial.SerialException, OSError) as exc:
            self._serial_error(exc)
            return False
        self._clear_serial_error()
        return True

    def _poll_position(self):
        """Read both axes. Returns (az, el) or None after logging the problem."""
        try:
            az = read_position(self._az)
            el = read_position(self._el)
        except ProtocolError as exc:
            self._emit("log", f"Malformed reply: {exc}")
            return None
        except (serial.SerialException, OSError) as exc:
            self._serial_error(exc)
            return None
        self._clear_serial_error()
        self._emit("position", (az, el))
        return az, el

    def _serial_error(self, exc):
        self._emit("log", f"Serial error: {exc}")
        self._emit("error", str(exc))
        if not self._in_error:
            self._in_error = True
            self._emit("status", STATUS_SERIAL_ERROR)

    def _clear_serial_error(self):
        if self._in_error:
            self._in_error = False
            self._emit("log", "Serial recovered")
            self._emit("status", STATUS_CONNECTED if self._client is not None else STATUS_LISTENING)
