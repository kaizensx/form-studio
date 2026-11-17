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

Verified by slicing with OrcaSlicer 2.5.1 on macOS: a 20 mm cube for every 0.4 mm printer in the 71
vendor caches it ships (496 printers), each with the process and filament its window would select.
471 slice; the other 25 fail the same way when the CLI is handed OrcaSlicer's own JSON presets (values
its checks reject, a skirt that leaves the bed). The 8-tool Prusa CORE One INDX crashes the CLI about
one run in three, with those JSON presets too.

Three things the CLI leaves to its caller, found that way and handled in _bbl.py and below:
the build plate (bed_type), why it refused (EXIT_REASONS, and its log in 00000.log), and on macOS
a "reopen windows?" question after any earlier crash (cli_env).

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
from .common import SlicerBlocked, SlicerFailed, first_dir, find_app as _find, gcode_stats, platform, shipped_dirs  # noqa: F401
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
    return shipped_dirs(app, "OrcaSlicer")


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


# BedType in src/libslic3r/PrintConfig.hpp, by its number (0 is "Default Plate", not a plate).
BED_TYPES = ("", "Cool Plate", "Engineering Plate", "High Temp Plate", "Textured PEI Plate", "Textured Cool Plate",
             "Supertack Plate")
COOL_PLATE_MODELS = ("Bambu Lab X1 Carbon", "Bambu Lab X1", "Bambu Lab X1E")       # model ids BL-P001, BL-P002, C13


def bed_type(machine: dict, conf: dict, name: str) -> str:
    """The build plate OrcaSlicer's window slices with for this printer.

    The plate decides which of a filament's bed temperatures goes into the G-code
    (cool_plate_temp, hot_plate_temp, …). The window always sets it: the plate last chosen for the
    printer if the printer offers a choice (OrcaSlicer.conf "orca_presets"[].curr_bed_type), else
    the printer's default_bed_type, else Cool Plate for the X1 series and High Temp Plate for every
    other printer (Preset::get_default_bed_type, Sidebar::update_presets, tag v2.5.1). The CLI sets
    nothing and falls back to Cool Plate, which printed a Prusa CORE One's PLA bed at 35 °C where
    the window gives 60 °C. So FORM states the plate itself."""
    def by_number(text) -> str:
        try:
            n = int(str(text).strip())
        except ValueError:
            return ""
        return BED_TYPES[n] if 0 < n < len(BED_TYPES) else ""

    model = str(machine.get("printer_model") or "")
    default = str(machine.get("default_bed_type") or "").strip()
    if default:
        fallback = default if default in BED_TYPES else by_number(default) or "High Temp Plate"
    else:
        fallback = "Cool Plate" if model in COOL_PLATE_MODELS else "High Temp Plate"
    if model.startswith("Bambu Lab") or str(machine.get("support_multi_bed_types") or "0") == "1":
        for entry in conf.get("orca_presets") or []:
            if isinstance(entry, dict) and entry.get("machine") == name:
                return by_number(entry.get("curr_bed_type") or "") or fallback
    return fallback


# What the CLI's return codes mean, in its own words (src/libslic3r/Utils.hpp CLI_* and cli_errors in
# src/OrcaSlicer.cpp, tag v2.5.1). It writes result.json with the sentence on Linux only, so on
# macOS and Windows the code is all there is. Codes about 3MF input and slicing caches are left out:
# FORM hands it an STL.
EXIT_REASONS = {
    -1: "Failed setting up server environment.",
    -2: "Invalid parameters to the slicer.",
    -3: "The input files to the slicer are not found.",
    -5: "The input preset file is invalid and can not be parsed.",
    -6: "The input model file to the slicer can not be parsed.",
    -7: "Unsupported printer technology (not FDM).",
    -8: "Unsupported CLI instruction.",
    -13: "Failed exporting 3mf files.",
    -14: "Out of memory during slicing.",
    -17: "The selected printer is not compatible with the process preset.",
    -18: "Invalid parameter value(s) in the presets.",
    -20: "The selected printer's bed size is smaller than the bed size used in the print profile.",
    -21: "An error occurred when auto-arranging object(s).",
    -22: "An error occurred when auto-orienting object(s).",
    -25: "Failed exporting the G-code statistics.",
    -50: "The plate has nothing to slice: it is empty, or no object on it is both printable and fully inside the print volume.",
    -51: "There are some incorrect slicing parameters.",
    -52: "Some objects are located over the boundary of the heated bed.",
    -58: "Slicing time of a certain plate exceeds the limit.",
    -59: "Triangle count of single plate exceeds the limit.",
    -61: "Filaments are not compatible with the plate type.",
    -62: "The temperature difference of the filaments used is too large.",
    -63: "Object conflicts were detected when using print-by-object mode.",
    -64: "Object conflicts were detected.",
    -65: "Some slicing parameters cannot work with Spiral Vase mode.",
    -66: "Some filaments cannot be mapped to correct extruders for multi-extruder Printer.",
    -67: "Not support printing 2 or more TPU filaments.",
    -68: "Some filaments cannot be printed on the extruder mapped to.",
    -100: "Failed slicing the model.",
    -101: "G-code conflicts detected after slicing.",
    -102: "Found G-code in unprintable area after slicing.",
}

FAMILY = _bbl.Family(kind="orca", label=LABEL, conf_name="OrcaSlicer.conf", version_re=r"OrcaSlicer-([\d.]+)", program="OrcaSlicer",
                     table="orca", deep_search=True, parse_header=parse_gcode_header,
                     cache_dirs=cache_dirs, shipped=profile_dirs, selection=selection, exit_reasons=EXIT_REASONS, bed_type=bed_type)


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
