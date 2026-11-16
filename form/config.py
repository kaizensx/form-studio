"""Studio configuration.

Where the config file is looked for, first match wins:
  1. $FORM_CONFIG
  2. studio.toml in a source checkout (next to the `form` package)
  3. ~/.config/form-studio/studio.toml

Relative paths in the file resolve against the file's own folder. Without any
file, projects live in $FORM_DATA or ~/FORM.
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_CONFIG = Path("~/.config/form-studio/studio.toml").expanduser()

if sys.platform == "darwin":
    _BAMBU_APP = "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
    _BAMBU_CONF = "~/Library/Application Support/BambuStudio"
elif sys.platform.startswith("linux"):
    _BAMBU_APP = "bambu-studio"
    _BAMBU_CONF = "~/.config/BambuStudio"
else:
    _BAMBU_APP = r"C:\Program Files\Bambu Studio\bambu-studio.exe"
    _BAMBU_CONF = "~/AppData/Roaming/BambuStudio"

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 4173},
    "data": {"dir": "~/FORM"},
    "printer": {"name": "Bambu Lab A1 mini", "envelope_mm": [180, 180, 180], "plate_margin_mm": 2.0},
    "slicer": {
        "kind": "bambu",
        "app": _BAMBU_APP,
        "config_dir": _BAMBU_CONF,
        "machine": "auto", "process": "auto", "filament": "auto",
        "timeout_s": 600,
    },
    # Apps that `open_in` may hand files to. Values are application names (macOS)
    # or commands (Linux/Windows). Empty means the system default for the file type.
    "apps": {"slicer": "BambuStudio", "cad": "", "viewer": ""},
    # Other CAD tools (optional). Empty = look in the usual places. OpenSCAD builds `language="openscad"` designs;
    # FreeCADCmd, when found, re-imports each exported STEP as an extra check.
    "cad": {"openscad": "", "freecad": "", "timeout_s": 120},
    # Chat in the bench runs Claude Code headless on your account, with FORM's tools (and web lookups if web = true).
    "chat": {"enabled": True, "cli": "claude", "model": "opus", "web": True, "budget_usd_per_message": 3.0},
    # Open the bench in your browser when an agent starts working (MCP server).
    "bench": {"auto_open": True},
    # Optional in-app model consultation through a local `claude` CLI. Off by
    # default: when FORM is used over MCP, the calling agent is the intelligence.
    "models": {
        "cli": "",
        "default": "opus",
        "specialist": "",
        "specialist_budget_usd": 0.5,
        "timeout_s": 120,
    },
}


def _find_config() -> Path | None:
    if os.environ.get("FORM_CONFIG"):
        return Path(os.environ["FORM_CONFIG"]).expanduser()
    for cand in (ROOT / "studio.toml", USER_CONFIG):
        if cand.exists():
            return cand
    return None


def load() -> dict:
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    path = _find_config()
    base = Path.home()
    if path and path.exists():
        with open(path, "rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            if section in cfg and isinstance(values, dict):
                cfg[section].update(values)
        base = path.parent
    cfg["_path"] = str(path) if path else "(defaults; no studio.toml found)"
    d = Path(os.environ.get("FORM_DATA", cfg["data"]["dir"])).expanduser()
    cfg["data"]["dir"] = str(d if d.is_absolute() else (base / d).resolve())
    return cfg
