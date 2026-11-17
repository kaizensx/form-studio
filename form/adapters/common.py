"""Pieces every slicer adapter shares: the two exceptions, finding the program, reading G-code.

A slice is a simulation by the slicer. It is not a print.
"""
from __future__ import annotations

import glob
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


class SlicerBlocked(Exception):
    """The slicer cannot run here; message says exactly why."""


class SlicerFailed(Exception):
    def __init__(self, message, hint="", log=""):
        super().__init__(message)
        self.hint, self.log = hint, log


def platform() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("win"):
        return "win"
    return "linux"


def expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def find_app(candidates: list[str]) -> str | None:
    """First candidate that exists: an absolute path, a glob (AppImages), or a command on PATH."""
    for c in candidates:
        c = expand(c)
        if any(ch in c for ch in "*?["):
            hits = sorted(glob.glob(c))
            if hits:
                return hits[-1]
            continue
        hit = shutil.which(c)
        if hit:
            return hit
        if os.path.isabs(c) and Path(c).exists():
            return c
    return None


def first_dir(candidates: list[str]) -> str:
    """First config folder that exists, else the first candidate (where the program would create it)."""
    for c in candidates:
        if Path(expand(c)).is_dir():
            return expand(c)
    return expand(candidates[0])


def shipped_dirs(app, share: str, sub: str = "profiles") -> list[Path]:
    """Folders named `sub` among the resources a slicer ships, for every way it is installed.

    app is the program FORM starts: the executable, a link to it, or the AppRun of an unpacked
    AppImage. share is the folder name the program uses under share/ ("OrcaSlicer")."""
    app = Path(app)
    try:
        real = app.resolve()
    except OSError:
        real = app
    out = []
    for exe in dict.fromkeys((app, real)):
        here = exe.parent
        out += [here.parent / "Resources" / sub,                # macOS bundle: Contents/MacOS/<Program>
                here / "resources" / sub,                       # Windows; Linux tarball; AppImage with resources beside AppRun
                here.parent / "resources" / sub,                # Linux: bin/<program> beside resources/
                here.parent / "share" / share / sub,            # Linux packages
                here / "usr" / "bin" / "resources" / sub,       # unpacked AppImage (PrusaSlicer family): AppRun, usr/bin/resources
                here / "usr" / "resources" / sub,
                here / "usr" / "share" / share / sub,
                here / "bin" / "resources" / sub]
    found = []
    for d in out:
        try:                            # one folder under two spellings (case, symlink) counts once
            if d.is_dir() and not any(os.path.samefile(d, f) for f in found):
                found.append(d)
        except OSError:
            continue
    return found


def windows_file_version(path) -> str:
    """The version text in a Windows program's file properties ("" when it has none, or elsewhere).

    Only the text fields. The numeric field is not the program's version in every build: OrcaSlicer 2.5.1's
    orca-slicer.exe has no text and the number 2.0.0.0."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("version")
        api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
        api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        api.GetFileVersionInfoW.restype = wintypes.BOOL
        api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wintypes.UINT)]
        api.VerQueryValueW.restype = wintypes.BOOL
        size = api.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not api.GetFileVersionInfoW(str(path), 0, size, buf):
            return ""
        at, n = ctypes.c_void_p(), wintypes.UINT()
        if api.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(at), ctypes.byref(n)) and n.value >= 4:
            lang, page = struct.unpack("HH", ctypes.string_at(at.value, 4))
            for key in ("ProductVersion", "FileVersion"):
                where = f"\\StringFileInfo\\{lang:04x}{page:04x}\\{key}"
                if api.VerQueryValueW(buf, where, ctypes.byref(at), ctypes.byref(n)) and n.value:
                    text = ctypes.wstring_at(at.value, n.value).strip("\0 ")
                    if re.search(r"\d", text):
                        return text
    except (OSError, AttributeError, ValueError, struct.error):
        pass
    return ""


def version_in(text: str, pattern: str) -> str:
    m = re.search(pattern, text or "")
    return m.group(1) if m else ""


def program_version(app: str, pattern: str, libraries: tuple = ()) -> str:
    """The version of a slicer: what `--help` prints, matched by `pattern`.

    On Windows the programs with a window (orca-slicer.exe, bambu-studio.exe, QIDISlicer.exe) print nothing
    to a pipe, so there the version comes from the file properties of the program, or of the library beside
    it that holds the program (`libraries`, e.g. "OrcaSlicer.dll"): bambu-studio.exe states it there,
    orca-slicer.exe does not. "unknown" when neither says (a slice then takes it from its G-code, see
    gcode_version); "unavailable" when the program could not be started at all."""
    try:
        with tempfile.TemporaryDirectory() as scratch:     # the CLI drops result.json into its cwd
            r = subprocess.run([app, "--help"], capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL, cwd=scratch, errors="replace")
        found = version_in(r.stdout + r.stderr, pattern)
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    if not found and os.name == "nt":
        for f in (Path(app), *(Path(app).parent / lib for lib in libraries)):
            found = version_in(windows_file_version(f), r"(\d+(?:\.\d+)+)") if f.exists() else ""
            if found:
                break
    return found or "unknown"


def gcode_version(path: Path, program: str) -> str:
    """The version the slicer wrote at the top of its G-code: "; generated by OrcaSlicer 2.5.1 on …",
    "; BambuStudio 02.09.01.70". "" when the first lines do not name `program`."""
    pat = re.compile(r"^;\s*(?:generated by\s+)?" + re.escape(program).replace(r"\ ", r"\s*") + r"[ _-]+v?(\d+(?:\.\d+)+)")
    try:
        with open(path, errors="ignore", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 60:
                    break
                m = pat.match(line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def private(text: str) -> str:
    """Logs are shipped with projects; never let them carry the user's home path."""
    return text.replace(str(Path.home()), "~")


def dur(text: str) -> float:
    """'1d 2h 3m 4s' (get_time_dhms in Bambu Studio, OrcaSlicer and PrusaSlicer) to seconds."""
    total = 0.0
    for num, unit in re.findall(r"(\d+)\s*([dhms])", text):
        total += int(num) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total


# Statistics comment lines. Where each one is written (sources are cited in tests/fixtures/slicers/SOURCES.txt):
#   Bambu Studio / OrcaSlicer with a Bambu Lab printer: in the header block.
#   OrcaSlicer with any other printer, PrusaSlicer, SuperSlicer, QIDISlicer: after the last layer.
STAT_PATTERNS = {
    "layers": [r"^; total layer number: (\d+)", r"^; total layers count = (\d+)"],
    "max_z_mm": [r"^; max_z_height: ([\d.]+)"],
    "filament_mm": [r"^; total filament length \[mm\] : ([\d.]+)", r"^; filament used \[mm\] = ([\d.]+)"],
    "filament_g": [r"^; total filament weight \[g\] : ([\d.]+)", r"^; total filament used \[g\] = ([\d.]+)",
                   r"^; filament used \[g\] = ([\d.]+)"],
    "model_time": [r"^; model printing time: ([^;]+);"],
    "total_time": [r"^; model printing time: [^;]*; total estimated time: (.+)$",r"^; estimated printing time \(normal mode\) = (.+)$"],
}


def gcode_stats(path: Path, head_lines: int = 400, tail_bytes: int = 2_000_000) -> dict:
    """Read the slicer's own statistics comments from the start and the end of a G-code file."""
    lines = []
    with open(path, "rb") as f:
        for i, raw in enumerate(f):
            if i >= head_lines:
                break
            lines.append(raw.decode("utf-8", "ignore"))
        size = os.fstat(f.fileno()).st_size
        f.seek(max(0, size - tail_bytes))
        tail = f.read().decode("utf-8", "ignore").splitlines()
    lines += tail[1:] if size > tail_bytes else []
    comments = [ln.rstrip("\r\n") for ln in lines if ln.startswith(";")]
    out: dict = {}
    for k, pats in STAT_PATTERNS.items():          # patterns in order of preference (totals before per-extruder)
        for pat in pats:
            m = next((m for m in (re.search(pat, ln) for ln in comments) if m), None)
            if m:
                out[k] = m.group(1).strip()
                break
    if "layers" in out:
        out["layers"] = int(out["layers"])
    for k in ("max_z_mm", "filament_mm", "filament_g"):
        if k in out:
            out[k] = float(out[k])
    if "total_time" in out and "time_s" not in out:
        out["time_s"] = dur(out["total_time"])
    return out


def generator(path: Path) -> str:
    """The '; generated by …' line, if the file has one in its first lines."""
    with open(path, errors="ignore", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i > 40:
                break
            m = re.match(r"^;\s*generated by (.+?)(?: on .*)?$", line.strip())
            if m:
                return m.group(1)
    return ""


# Layer and feature markers. Bambu Studio (and OrcaSlicer with a Bambu Lab printer) write
# "; CHANGE_LAYER", "; Z_HEIGHT: z", "; FEATURE: type". PrusaSlicer and OrcaSlicer with other
# printers write ";LAYER_CHANGE", ";Z:z", ";TYPE:type".
STYLES = {
    "bambu": ("; CHANGE_LAYER", "; Z_HEIGHT:", "; FEATURE:"),
    "prusa": (";LAYER_CHANGE", ";Z:", ";TYPE:"),
}


def parse_layers(path: Path, style: str = "bambu", type_map: dict | None = None) -> list[dict]:
    """Extrusion paths per layer, by slicer feature type, for inspection.

    style "auto" commits to whichever layer marker appears first.
    type_map renames feature types (PrusaSlicer's names to the ones FORM's viewer colours)."""
    layers, cur, x, y, z, feat, path_pts = [], None, 0.0, 0.0, 0.0, "", None
    relative_e, last_e = True, 0.0
    before_r = None                                 # last M73 R seen before the first layer
    if style == "auto":
        style = None
    lay, zh, ft = STYLES[style] if style else ("", "", "")
    tmap = type_map or {}

    def close():
        nonlocal path_pts
        if path_pts and len(path_pts["p"]) >= 4 and cur is not None:
            cur["paths"].append(path_pts)
        path_pts = None

    with open(path, errors="ignore", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line[0] == ";":
                if style is None:
                    for name, marks in STYLES.items():
                        if line.startswith(marks[0]):
                            style = name
                            lay, zh, ft = marks
                            break
                    else:
                        continue
                if line.startswith(lay):
                    close()
                    cur = {"z": z, "paths": []}
                    layers.append(cur)
                elif line.startswith(zh) and cur is not None:
                    try:
                        cur["z"] = float(line[len(zh):])
                    except ValueError:
                        pass
                elif line.startswith(ft):
                    close()
                    feat = line[len(ft):].strip()
                    feat = tmap.get(feat, feat)
                continue
            code = line.split(";", 1)[0].split()
            if not code:
                continue
            g = code[0]
            if g == "M83":
                relative_e = True
            elif g == "M82":
                relative_e = False
            elif g == "G92":
                for w in code[1:]:
                    if w[0] == "E":
                        last_e = float(w[1:])
            elif g == "M73":
                # print simulation (form/toolpath.py): the slicer's own "R minutes remain" markers, with where in
                # the layer they sit: [paths finished, points in the open path, minutes]. One seen before the
                # first layer is kept at the very start of it.
                r = next((w[1:] for w in code[1:] if w[0] == "R"), None)
                if r is not None and r.isdigit():
                    if cur is None:
                        before_r = int(r)
                    else:
                        if before_r is not None and "marks" not in cur:
                            cur["marks"] = [[0, 0, before_r]]
                        before_r = None
                        cur.setdefault("marks", []).append([len(cur["paths"]), len(path_pts["p"]) // 2 if path_pts else 0, int(r)])
            elif g in ("G0", "G1", "G2", "G3"):
                nx, ny, e, i, j = x, y, None, 0.0, 0.0
                try:
                    for w in code[1:]:
                        c, val = w[0], w[1:]
                        if c == "X": nx = float(val)
                        elif c == "Y": ny = float(val)
                        elif c == "Z": z = float(val)
                        elif c == "E": e = float(val)
                        elif c == "I": i = float(val)
                        elif c == "J": j = float(val)
                except ValueError:
                    continue
                de = 0.0
                if e is not None:
                    de = e if relative_e else e - last_e
                    if not relative_e:
                        last_e = e
                moved = (nx != x or ny != y)
                if de > 0 and moved and cur is not None:
                    if path_pts is None:
                        path_pts = {"t": feat, "p": [round(x, 3), round(y, 3)]}
                    if g in ("G2", "G3"):
                        cx, cy = x + i, y + j
                        a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
                        if g == "G2" and a1 >= a0: a1 -= 2 * math.pi
                        if g == "G3" and a1 <= a0: a1 += 2 * math.pi
                        rad = math.hypot(x - cx, y - cy)
                        steps = max(2, int(abs(a1 - a0) * rad / 0.6))
                        for s in range(1, steps):
                            a = a0 + (a1 - a0) * s / steps
                            path_pts["p"] += [round(cx + rad * math.cos(a), 3), round(cy + rad * math.sin(a), 3)]
                    path_pts["p"] += [round(nx, 3), round(ny, 3)]
                else:
                    close()
                x, y = nx, ny
    close()
    return [l for l in layers if l["paths"]]
