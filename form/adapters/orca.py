"""Slicer adapter for OrcaSlicer (SoftFever/OrcaSlicer), a fork of Bambu Studio.

The CLI flags, the JSON preset layout under the config folder and the 3MF slice_info are the
Bambu Studio ones (see _bbl.py; flags from src/libslic3r/PrintConfig.cpp CLIActionsConfigDef,
output name "plate_<n>.gcode" from src/OrcaSlicer.cpp). What differs is the G-code: with a
Bambu Lab printer OrcaSlicer writes Bambu's "; CHANGE_LAYER" / "; FEATURE:" markers and the
"; model printing time: …; total estimated time: …" header; with any other printer it writes
";LAYER_CHANGE" / ";Z:" / ";TYPE:" and puts "; estimated printing time (normal mode) = …" and
"; total filament used [g] = …" after the last layer (src/libslic3r/GCode.cpp,
src/libslic3r/GCode/GCodeProcessor.cpp). Both are read here.

Not run against a real OrcaSlicer on the machine this was written on; tested with fixtures.

Settings, all optional, in studio.toml:
    [slicer.orca]
    app = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
    config_dir = "~/Library/Application Support/OrcaSlicer"
    machine = "auto"      # "auto" follows the selection in OrcaSlicer
    process = "auto"
    filament = "auto"
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import _bbl
from .common import SlicerBlocked, SlicerFailed, first_dir, find_app as _find, gcode_stats, platform  # noqa: F401
from .common import parse_layers as _parse_layers

LABEL = "OrcaSlicer"
URL = "https://github.com/SoftFever/OrcaSlicer/releases"
FLATPAK_IDS = ("com.orcaslicer.OrcaSlicer", "io.github.softfever.OrcaSlicer")   # current id, and the one before v2.3.2

APPS = {
    "darwin": ["/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer",
               "~/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"],
    "win": [r"%ProgramFiles%\OrcaSlicer\orca-slicer.exe", r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
            r"%LOCALAPPDATA%\Programs\OrcaSlicer\orca-slicer.exe", "orca-slicer.exe"],
    "linux": ["orca-slicer", "OrcaSlicer", "~/Applications/OrcaSlicer*.AppImage", "~/.local/bin/OrcaSlicer*.AppImage",
              "/opt/OrcaSlicer/AppRun"]
             + [f"{root}/exports/bin/{fid}" for fid in FLATPAK_IDS
                for root in ("/var/lib/flatpak", "~/.local/share/flatpak")],
}
CONFIG_DIRS = {
    "darwin": ["~/Library/Application Support/OrcaSlicer"],
    "win": [r"%APPDATA%\OrcaSlicer"],
    "linux": ["~/.config/OrcaSlicer"] + [f"~/.var/app/{fid}/config/OrcaSlicer" for fid in FLATPAK_IDS],
}


def parse_gcode_header(path: Path) -> dict:
    return gcode_stats(path)


FAMILY = _bbl.Family(kind="orca", label=LABEL, conf_name="OrcaSlicer.conf", version_re=r"OrcaSlicer-([\d.]+)",
                     table="orca", deep_search=True, parse_header=parse_gcode_header)


def _settings(cfg: dict) -> dict:
    s = cfg["slicer"]
    sub = s.get("orca") if isinstance(s.get("orca"), dict) else {}
    explicit = s.get("kind") == "orca"          # top-level preset names apply when Orca is chosen by name
    out = {}
    for k in ("machine", "process", "filament"):
        out[k] = sub.get(k) or (s.get(k, "auto") if explicit else "auto")
    out["app"] = sub.get("app") or ""
    out["config_dir"] = sub.get("config_dir") or ""
    return out


def find_app(cfg: dict) -> str | None:
    st = _settings(cfg)
    if st["app"]:
        return _find([st["app"]])
    return _find(APPS[platform()])


def config_dir(cfg: dict) -> Path:
    st = _settings(cfg)
    return Path(first_dir([st["config_dir"]] if st["config_dir"] else CONFIG_DIRS[platform()]))


def install_hint() -> dict:
    cmds, note = [], f"Download from {URL}"
    if platform() == "darwin" and shutil.which("brew"):
        cmds = ["brew install --cask orcaslicer"]
    elif platform() == "linux" and shutil.which("flatpak"):
        cmds = [f"flatpak install -y flathub {FLATPAK_IDS[0]}"]
    return {"url": URL, "cmds": cmds, "note": note, "size": ""}


def resolve(cfg: dict) -> dict:
    st = _settings(cfg)
    app = find_app(cfg)
    shown = Path(app or st["app"] or APPS[platform()][0]).expanduser()
    out = _bbl.resolve(FAMILY, cfg["slicer"], shown, config_dir(cfg), st)
    if not app:
        out["reason"] = (f"OrcaSlicer was not found (looked for {APPS[platform()][0]}). "
                         "Install it or set [slicer.orca].app in studio.toml.")
    return out


def version(app: str) -> str:
    return _bbl.version(FAMILY, app)


def public(resolved: dict) -> dict:
    return _bbl.public(FAMILY, resolved)


def slice_stl(resolved: dict, stl: Path, out_dir: Path, timeout: float = 600) -> dict:
    return _bbl.slice_stl(FAMILY, resolved, stl, out_dir, timeout)


def parse_layers(path: Path) -> list[dict]:
    """Either marker style, whichever the file uses."""
    return _parse_layers(path, "auto")
