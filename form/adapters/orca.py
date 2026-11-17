"""Slicer adapter for OrcaSlicer (SoftFever/OrcaSlicer), a fork of Bambu Studio.

The CLI flags, the JSON preset layout under the config folder and the 3MF slice_info are the
Bambu Studio ones (see _bbl.py; flags from src/libslic3r/PrintConfig.cpp CLIActionsConfigDef,
output name "plate_<n>.gcode" from src/OrcaSlicer.cpp). What differs is the G-code: with a
Bambu Lab printer OrcaSlicer writes Bambu's "; CHANGE_LAYER" / "; FEATURE:" markers and the
"; model printing time: …; total estimated time: …" header; with any other printer it writes
";LAYER_CHANGE" / ";Z:" / ";TYPE:" and puts "; estimated printing time (normal mode) = …" and
"; total filament used [g] = …" after the last layer (src/libslic3r/GCode.cpp,
src/libslic3r/GCode/GCodeProcessor.cpp). Both are read here.

Presets. Up to OrcaSlicer 2.4 the system presets are JSON files under <config>/system/<vendor>/.
From 2.5 each vendor is one packed cache, <vendor>.opc, in <config>/system and in the program's
own profiles folder; orca_cache.py reads those. A preset is looked for as JSON first (user presets
still are JSON), then in <config>/system/*.opc, then in the shipped profiles, so presets pinned in
studio.toml work on an install that was never opened. The current selection is "presets".machine
in OrcaSlicer.conf plus that printer's entry in "orca_presets" (process, filament), as
PresetBundle::load_selections reads it.

Verified by slicing with OrcaSlicer 2.5.1 on macOS (Bambu Lab A1 mini presets from BBL.opc).

Settings, all optional, in studio.toml:
    [slicer.orca]
    app = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
    config_dir = "~/Library/Application Support/OrcaSlicer"
    machine = "auto"      # "auto" follows the selection in OrcaSlicer
    process = "auto"
    filament = "auto"
"""
from __future__ import annotations

import os
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


def profile_dirs(app: Path) -> list[Path]:
    """Where the program keeps the vendor presets it ships (resources/profiles), for each layout."""
    app = Path(app)
    try:
        real = app.resolve()
    except OSError:
        real = app
    out = []
    for exe in dict.fromkeys((app, real)):
        here = exe.parent
        out += [here.parent / "Resources" / "profiles",                 # macOS bundle: Contents/MacOS/OrcaSlicer
                here / "resources" / "profiles",                        # Windows, Linux tarball
                here.parent / "resources" / "profiles",                 # Linux: bin/orca-slicer beside resources/
                here.parent / "share" / "OrcaSlicer" / "profiles"]      # Linux packages
    found = []
    for d in out:
        try:                            # one folder under two spellings (case, symlink) counts once
            if d.is_dir() and not any(os.path.samefile(d, f) for f in found):
                found.append(d)
        except OSError:
            continue
    return found


def cache_dirs(app: Path, config_dir: Path) -> list[Path]:
    """Folders with packed vendor presets: the person's installed vendors first, then the shipped ones."""
    return [d for d in [Path(config_dir) / "system", *profile_dirs(app)] if d.is_dir()]


def selection(conf: dict) -> dict:
    """The presets chosen in OrcaSlicer. The printer is under "presets"; its process and filament
    are in that printer's "orca_presets" entry (older versions kept them under "presets" too)."""
    presets = conf.get("presets") if isinstance(conf.get("presets"), dict) else {}
    machine = presets.get("machine") or ""
    mine = {}
    for entry in conf.get("orca_presets") or []:
        if isinstance(entry, dict) and entry.get("machine") == machine:
            mine = entry
            break
    filaments = presets.get("filaments") if isinstance(presets.get("filaments"), list) else []
    return {"machine": machine,
            "process": mine.get("process") or presets.get("process") or "",
            "filament": mine.get("filament") or (filaments[0] if filaments else "") or ""}


FAMILY = _bbl.Family(kind="orca", label=LABEL, conf_name="OrcaSlicer.conf", version_re=r"OrcaSlicer-([\d.]+)",
                     table="orca", deep_search=True, parse_header=parse_gcode_header,
                     cache_dirs=cache_dirs, selection=selection)


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
