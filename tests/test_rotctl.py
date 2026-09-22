from types import SimpleNamespace

import m2rotctl


def args(az=None, el=None):
    return SimpleNamespace(az=az, el=el, baud=None, port=None)


def test_resolve_devices_uses_saved_serials(monkeypatch):
    table = {"ftDZZ3P9": "/dev/ttyUSB0", "A5020LVA": "/dev/ttyUSB1"}
    monkeypatch.setattr(m2rotctl.m2ports, "resolve_serial", lambda s: table.get(s))
    cfg = {"az_serial": "ftDZZ3P9", "el_serial": "A5020LVA"}
    assert m2rotctl.resolve_devices(cfg, args()) == ("/dev/ttyUSB0", "/dev/ttyUSB1")


def test_resolve_devices_command_line_wins(monkeypatch):
    monkeypatch.setattr(m2rotctl.m2ports, "resolve_serial", lambda s: "/dev/ttyUSB0")
    cfg = {"az_serial": "ftDZZ3P9", "el_serial": "A5020LVA"}
    assert m2rotctl.resolve_devices(cfg, args(az="/dev/ttyS9")) == ("/dev/ttyS9", "/dev/ttyUSB0")


def test_resolve_devices_missing_gives_none(monkeypatch):
    monkeypatch.setattr(m2rotctl.m2ports, "resolve_serial", lambda s: None)
    assert m2rotctl.resolve_devices({"az_serial": None, "el_serial": None}, args()) == (None, None)


def test_main_exits_2_when_ports_unresolved(monkeypatch, capsys):
    monkeypatch.setattr(m2rotctl.m2config, "load_config", lambda: {"az_serial": None, "el_serial": None, "baud": 9600, "tcp_port": 4534})
    monkeypatch.setattr(m2rotctl.m2ports, "resolve_serial", lambda s: None)
    assert m2rotctl.main([]) == 2
    assert "Could not find both rotor ports" in capsys.readouterr().err


def test_main_exits_1_when_bridge_stops_unexpectedly(monkeypatch, capsys):
    monkeypatch.setattr(m2rotctl.m2config, "load_config", lambda: {"az_serial": None, "el_serial": None, "baud": 9600, "tcp_port": 4534})
    monkeypatch.setattr(m2rotctl.m2ports, "resolve_serial", lambda s: "/dev/fake")
    monkeypatch.setattr(m2rotctl.time, "sleep", lambda seconds: None)

    calls = {"stopped": False}

    class FakeBridge:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        @property
        def running(self):
            return False

        def stop(self):
            calls["stopped"] = True

    monkeypatch.setattr(m2rotctl, "RotorBridge", FakeBridge)
    assert m2rotctl.main([]) == 1
    assert calls["stopped"] is True
    assert "Bridge stopped unexpectedly" in capsys.readouterr().err
