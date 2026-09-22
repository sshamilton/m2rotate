import json

from m2config import CONFIG_PATH, DEFAULTS, load_config, save_config


def test_defaults():
    assert DEFAULTS == {"az_serial": None, "el_serial": None, "baud": 9600, "tcp_port": 4534}
    assert CONFIG_PATH.name == "config.json"
    assert CONFIG_PATH.parent.name == "m2rotate"


def test_load_missing_file_returns_defaults(tmp_path):
    assert load_config(tmp_path / "nope.json") == DEFAULTS


def test_load_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    assert load_config(path) == DEFAULTS


def test_save_then_load_round_trips_and_creates_parent(tmp_path):
    path = tmp_path / "deep" / "dir" / "config.json"
    cfg = {"az_serial": "ftDZZ3P9", "el_serial": "A5020LVA", "baud": 19200, "tcp_port": 4535}
    save_config(cfg, path)
    assert load_config(path) == cfg


def test_load_ignores_unknown_keys_and_fills_missing(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"az_serial": "ftDZZ3P9", "bogus": 1}))
    assert load_config(path) == {"az_serial": "ftDZZ3P9", "el_serial": None, "baud": 9600, "tcp_port": 4534}


def test_save_only_writes_known_keys(tmp_path):
    path = tmp_path / "config.json"
    save_config({"az_serial": "x", "bogus": 1}, path)
    assert json.loads(path.read_text()) == {"az_serial": "x", "el_serial": None, "baud": 9600, "tcp_port": 4534}
