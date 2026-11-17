"""Slicer adapter for the Bambu Studio CLI: resolve the configured presets, slice, read results.

A slice is a simulation by the slicer. It says the model can be toolpathed with
these presets and estimates time and material. It is not a print.

The CLI, preset layout and 3MF reading are shared with OrcaSlicer in _bbl.py.
Settings: [slicer].app, [slicer].config_dir, [slicer].machine/process/filament.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from . import _bbl
from .common import SlicerBlocked, SlicerFailed, dur as _dur, parse_layers as _parse_layers  # noqa: F401
from .common import private as _private  # noqa: F401
from .common import expand as _expand, find_app as _find, platform as _platform, shipped_dirs as _shipped_dirs

LABEL = "Bambu Studio"
URL = "https://bambulab.com/en/download/studio"


def parse_gcode_header(path: Path) -> dict:
    out, n = {}, 0
    pats = {
        "layers": r"^; total layer number: (\d+)", "max_z_mm": r"^; max_z_height: ([\d.]+)",
        "filament_mm": r"^; total filament length \[mm\] : ([\d.]+)",
        "filament_g": r"^; total filament weight \[g\] : ([\d.]+)",
        "model_time": r"^; model printing time: ([^;]+);", "total_time": r"total estimated time: (.+)$",
    }
    with open(path, errors="ignore", encoding="utf-8") as f:
        for line in f:
            n += 1
            if n > 400:
                break
            for k, pat in pats.items():
                m = re.search(pat, line)
                if m and k not in out:
                    out[k] = m.group(1).strip()
    for k in ("layers",):
        if k in out:
            out[k] = int(out[k])
    for k in ("max_z_mm", "filament_mm", "filament_g"):
        if k in out:
            out[k] = float(out[k])
    if "total_time" in out and "time_s" not in out:
        out["time_s"] = _dur(out["total_time"])
    return out


def profile_dirs(app: Path) -> list[Path]:
    """The vendor presets inside the program (resources/profiles/<vendor>/<kind>/*.json). Bambu Studio copies
    them to <config_dir>/system when it is first opened; until then they are the only ones there are."""
    return _shipped_dirs(app, "BambuStudio")


FAMILY = _bbl.Family(kind="bambu", label=LABEL, conf_name="BambuStudio.conf", version_re=r"BambuStudio-([\d.]+)", program="BambuStudio",
                     parse_header=parse_gcode_header, shipped=profile_dirs)

# Where else the program is, when [slicer].app was left at its default and nothing is there.
APPS = {
    "darwin": ["~/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"],
    "win": [r"%ProgramFiles%\Bambu Studio\bambu-studio.exe", r"%LOCALAPPDATA%\Programs\Bambu Studio\bambu-studio.exe",
            "bambu-studio.exe"],
    "linux": ["BambuStudio", "/opt/BambuStudio/AppRun", "~/Applications/Bambu*Studio*.AppImage"],
}


def _conf(config_dir: Path) -> dict:
    return _bbl.read_conf(config_dir, FAMILY.conf_name)


def flatten(config_dir: Path, kind: str, name: str, _depth=0) -> dict:
    """Resolve the inheritance chain into one self-contained preset."""
    return _bbl.flatten(FAMILY, config_dir, kind, name, _depth)


def _app(cfg: dict) -> Path:
    from ..config import DEFAULTS
    s = cfg["slicer"]
    app = Path(shutil.which(s["app"]) or _expand(s["app"]))
    if not app.exists() and s["app"] == DEFAULTS["slicer"]["app"]:
        other = _find(APPS[_platform()])
        if other:
            return Path(other)
    return app


def find_app(cfg: dict) -> str | None:
    """The configured program, if it exists (for auto-detection)."""
    app = _app(cfg)
    return str(app) if app.exists() else None


def install_hint() -> dict:
    cmds, note = [], f"Download from {URL}"
    if sys.platform == "darwin" and shutil.which("brew"):
        cmds = ["brew install --cask bambu-studio"]
    elif shutil.which("flatpak"):
        cmds = ["flatpak install -y flathub com.bambulab.BambuStudio"]
        note = "Then set [slicer].app to the AppImage or a wrapper script; flatpak apps need `flatpak run`."
    return {"url": URL, "cmds": cmds, "note": note, "size": "about 200 MB"}


def resolve(cfg: dict) -> dict:
    """Which presets a slice would use right now, with content hashes."""
    s = cfg["slicer"]
    return _bbl.resolve(FAMILY, s, _app(cfg), Path(s["config_dir"]).expanduser(),
                        {k: s[k] for k in ("machine", "process", "filament")})


_version_cache = FAMILY.version_cache


def version(app: str) -> str:
    return _bbl.version(FAMILY, app)


def public(resolved: dict) -> dict:
    return _bbl.public(FAMILY, resolved)


def slice_stl(resolved: dict, stl: Path, out_dir: Path, timeout: float = 600) -> dict:
    return _bbl.slice_stl(FAMILY, resolved, stl, out_dir, timeout)


def _read_3mf(path: Path, out_dir: Path) -> dict:
    return _bbl.read_3mf(path, out_dir)


def parse_layers(path: Path) -> list[dict]:
    """Extrusion paths per layer, by slicer feature type, for inspection."""
    return _parse_layers(path, "bambu")
