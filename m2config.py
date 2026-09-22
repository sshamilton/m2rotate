"""Load and save the settings shared by the GUI and the headless entry point."""
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "m2rotate" / "config.json"
DEFAULTS = {"az_serial": None, "el_serial": None, "baud": 9600, "tcp_port": 4534}


def load_config(path=CONFIG_PATH) -> dict:
    """Return the saved settings merged over DEFAULTS. Missing or corrupt file gives DEFAULTS."""
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return cfg
    if isinstance(data, dict):
        cfg.update({key: data[key] for key in DEFAULTS if key in data})
    return cfg


def save_config(cfg: dict, path=CONFIG_PATH) -> None:
    """Write the known keys of cfg as JSON, creating the parent directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    known = {key: cfg.get(key, DEFAULTS[key]) for key in DEFAULTS}
    path.write_text(json.dumps(known, indent=2) + "\n")
