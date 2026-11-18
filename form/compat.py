"""Which versions of the programs Form Studio drives it is built for, and saying so when that is why something failed.

Every adapter talks to another program through its command line and its files: CLI flags, preset formats, a Python
API (Blender, FreeCAD). Those change between releases. When a run fails *and* the installed version is outside the
range below *and* the failure looks like such a change (an option the program no longer knows, a preset or file
format it cannot read, an API attribute that is gone), the error names the range and what to do:

    Form Studio works with OrcaSlicer 2.0–2.5; you have 2.6.0. Update Form Studio, or install OrcaSlicer 2.5.

Nothing else is ever blamed on the version: a failure inside the range, a failure of another kind, or a version
that could not be read keeps the program's own message. `status()` only describes; it never blocks a run.

A range is (first, last) by major.minor: "2.5" covers every 2.5.x. "first" is the oldest release whose command line
and files the adapter's code follows; "last" is the newest one it was run with (docs/VERIFICATION.md lists those
runs). Bambu Studio numbers its releases 02.09.01.70; leading zeros are ignored.
"""
from __future__ import annotations

import re

# kind -> (label, first, last, download page)
RANGES: dict[str, tuple] = {
    "bambu": ("Bambu Studio", "1.8", "2.9", "https://bambulab.com/en/download/studio"),
    "orca": ("OrcaSlicer", "2.0", "2.5", "https://github.com/SoftFever/OrcaSlicer/releases"),
    "elegoo": ("ElegooSlicer", "1.5", "1.5", "https://github.com/ELEGOO-3D/ElegooSlicer/releases"),
    "snapmaker": ("Snapmaker Orca", "2.4", "2.4", "https://github.com/Snapmaker/OrcaSlicer/releases"),
    "prusa": ("PrusaSlicer", "2.6", "2.9", "https://www.prusa3d.com/page/prusaslicer_424/"),
    "superslicer": ("SuperSlicer", "2.5", "2.5", "https://github.com/supermerill/SuperSlicer/releases"),
    "qidi": ("QIDISlicer", "1.0", "1.2", "https://github.com/QIDITECH/QIDISlicer/releases"),
    "blender": ("Blender", "4.2", "5.2", "https://www.blender.org/download/"),
    "freecad": ("FreeCAD", "0.21", "1.1", "https://www.freecad.org/downloads.php"),
    "openscad": ("OpenSCAD", "2021.1", "2026.10", "https://openscad.org/downloads.html"),
}

# What a changed command line, file format or API looks like in each program's own words. Matched case-insensitively
# against the error and the end of the log. A slicer's numbered refusals (exit codes) are written out by the adapters
# first (form/adapters/orca.py EXIT_REASONS), so their sentences are what is matched here.
SIGNATURES: dict[str, list[str]] = {
    "slicer": [r"unknown option", r"unrecogni[sz]ed (?:option|argument|command)", r"invalid option", r"no such option",
               r"is not a valid option", r"unknown parameter", r"invalid parameters to the slicer",
               r"unsupported cli instruction", r"input preset file is invalid", r"preset cache is format version",
               r"unknown (?:config(?:uration)?|setting) key", r"unknown configuration (?:option|value)",
               r"failed to (?:parse|load) (?:the )?(?:config|preset|profile)", r"profile format", r"version of the file .* newer"],
    "blender": [r"has no attribute", r"attributeerror", r"unexpected keyword argument", r"keyerror: .bpy_",
                r"bpy_struct.* not found", r"unknown argument", r"unrecogni[sz]ed (?:option|argument)", r"no module named"],
    "freecad": [r"has no attribute", r"attributeerror", r"no module named", r"unexpected keyword argument",
                r"unknown option", r"unrecogni[sz]ed option"],
    "openscad": [r"unknown option", r"unrecogni[sz]ed (?:option|argument)", r"invalid (?:option|argument)",
                 r"export-format", r"unknown export format", r"unrecognised export format"],
}
FAMILY = {"blender": "blender", "freecad": "freecad", "openscad": "openscad"}      # everything else is a slicer


def parse(version) -> tuple | None:
    """(major, minor, rest...) from "2.5.1", "02.09.01.70", "OpenSCAD version 2021.01", "Blender 5.2.3 LTS"; None if
    there is no number in it ("unknown", "unavailable", "")."""
    m = re.search(r"(\d+)(?:\.(\d+))?((?:\.\d+)*)", str(version or ""))
    if not m:
        return None
    rest = tuple(int(x) for x in m.group(3).split(".")[1:]) if m.group(3) else ()
    return (int(m.group(1)), int(m.group(2) or 0)) + rest


def _short(v: tuple) -> tuple:
    return v[:2]


def _text(v: tuple) -> str:
    return ".".join(str(x) for x in v)


def range_text(kind: str) -> str:
    label, lo, hi, _ = RANGES[kind]
    return f"{label} {lo}" if lo == hi else f"{label} {lo}–{hi}"


def status(kind: str, version) -> dict:
    """{"supported": True | False | None (version unknown), "range": "OrcaSlicer 2.0–2.5", "version", "newer"}."""
    if kind not in RANGES:
        return {"supported": None, "range": "", "version": version or ""}
    v = parse(version)
    out = {"range": range_text(kind), "version": str(version or ""), "first": RANGES[kind][1], "last": RANGES[kind][2]}
    if v is None:
        return out | {"supported": None}
    lo, hi = parse(RANGES[kind][1]), parse(RANGES[kind][2])
    inside = _short(lo) <= _short(v) <= _short(hi)
    return out | {"supported": inside, "newer": None if inside else _short(v) > _short(hi)}


def looks_like_version_change(kind: str, text: str) -> bool:
    pats = SIGNATURES[FAMILY.get(kind, "slicer")]
    low = (text or "").lower()
    return any(re.search(p, low) for p in pats)


def explain(kind: str, version, text: str) -> str | None:
    """The sentence to show instead of (before) the program's own error, or None when the version is not the cause."""
    s = status(kind, version)
    if s.get("supported") is not False or not looks_like_version_change(kind, text):
        return None
    label, lo, hi, url = RANGES[kind]
    have = _text(parse(version))
    if s["newer"]:
        todo = f"Update Form Studio, or install {label} {hi} ({url})."
    else:
        todo = f"Update {label} to {hi} ({url})."
    return f"Form Studio works with {range_text(kind)}; you have {have}. {todo}"


def wrap_message(kind: str, version, message: str, log: str = "") -> tuple[str, str] | None:
    """(new message, hint) when the version explains the failure; the program's own words go into the hint."""
    why = explain(kind, version, f"{message}\n{log[-4000:] if log else ''}")
    if not why:
        return None
    return why, f"What {RANGES[kind][0]} said: {message}"
