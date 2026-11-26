"""Adapter for Blender, run headless: illustrative renders of an exported STL.

A render is an illustration of the geometry under made-up studio light, with a
made-up filament material. It is not a photo of a print and is not evidence of
anything about the part. Every render carries LABEL.

Blender is optional. Without it, `resolve()` says exactly what is missing.

The scene itself is built by `blender_scene.py`, which runs inside Blender's
own Python. This module only finds Blender, writes a job file (every number the
scene needs, already computed here so it can be tested without Blender), runs
it with a time limit and reads the result.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

LABEL = "Rendered in Blender — an illustration, not a photo of a print"
SCENE_VERSION = 3
SCENE_SCRIPT = Path(__file__).with_name("blender_scene.py")
DOWNLOAD_URL = "https://www.blender.org/download/"
SIZE = (1600, 1200)
LENS_MM = 70.0                 # 36 mm sensor width: about 29° horizontal field of view, a product-shot lens
SENSOR_MM = 36.0
# the app's viewport "iso" camera: azimuth, elevation in degrees (Viewport.qml `views.iso`)
APP_ISO = (-34.0, 28.4)

PRESETS = {
    "studio": {"label": "Studio", "note": "Soft box over a light seamless backdrop"},
    "desk": {"label": "Desk", "note": "Warm light on a wooden desk"},
    "dark": {"label": "Dark", "note": "Graphite backdrop and a rim light"},
}
FINISHES = {
    "matte": {"label": "Matte PLA", "roughness": 0.58, "specular": 0.45, "coat": 0.0, "metallic": 0.0, "sheen": 0.0,
              "subsurface": 0.0},
    "petg": {"label": "PETG gloss", "roughness": 0.16, "specular": 0.55, "coat": 0.35, "metallic": 0.0, "sheen": 0.0,
             "subsurface": 0.08},
    "silk": {"label": "Silk PLA", "roughness": 0.3, "specular": 0.6, "coat": 0.15, "metallic": 0.55, "sheen": 0.25,
             "subsurface": 0.0},
    # product finishes, for designs that declare material zones (Recipe.appearance) or a whole part in one of them
    "gloss": {"label": "Gloss paint", "roughness": 0.32, "specular": 0.5, "coat": 1.0, "coat_roughness": 0.03,
              "metallic": 0.0, "sheen": 0.0, "subsurface": 0.0},
    "carbon": {"label": "Carbon twill, clear coat", "roughness": 0.35, "specular": 0.5, "coat": 1.0,
               "coat_roughness": 0.02, "metallic": 0.0, "sheen": 0.0, "subsurface": 0.0, "tile_mm": 24.0},
    "smoke": {"label": "Smoked polycarbonate", "roughness": 0.02, "specular": 0.5, "coat": 0.0, "metallic": 0.0,
              "sheen": 0.0, "subsurface": 0.0},
    "rubber": {"label": "Rubber", "roughness": 0.85, "specular": 0.25, "coat": 0.0, "metallic": 0.0, "sheen": 0.3,
               "subsurface": 0.0},
    "metal": {"label": "Brushed metal", "roughness": 0.28, "specular": 0.5, "coat": 0.0, "metallic": 1.0, "sheen": 0.0,
              "subsurface": 0.0},
}
# photo cameras by name: (azimuth, elevation) in the convention of render() and the app's viewport (azimuth from +X
# toward +Y: "front" looks from -Y). A product that faces +X shows its face in "right"; three_quarter is between.
PHOTO_VIEWS = {"iso": None, "front": (-90.0, 6.0), "back": (90.0, 6.0), "left": (180.0, 6.0), "right": (0.0, 6.0),
               "top": (-90.0, 80.0), "three_quarter": (-38.0, 16.0), "three_quarter_back": (-142.0, 20.0)}


def photo_view(view=None, azimuth=None, elevation=None) -> tuple[float, float]:
    """(az, el) for the Blender camera (its azimuth convention: 0 looks from -Y) from a view name or an explicit
    azimuth/elevation in the render() convention. None everywhere: the app's iso camera."""
    if azimuth is not None or elevation is not None:
        base = PHOTO_VIEWS.get(view or "three_quarter") or (-38.0, 16.0)
        az = float(azimuth) if azimuth is not None else base[0]
        el = float(elevation) if elevation is not None else base[1]
    else:
        if view not in (None, "") and view not in PHOTO_VIEWS:
            raise ValueError(f"Unknown view “{view}”. Views: {', '.join(PHOTO_VIEWS)}.")
        pv = PHOTO_VIEWS.get(view or "iso")
        if pv is None:
            return APP_ISO
        az, el = pv
    if not -89.0 <= el <= 89.0:
        raise ValueError("elevation must be between -89 and 89 degrees")
    return ((az + 90.0 + 180.0) % 360.0 - 180.0, el)
SWATCHES = [
    {"name": "White", "hex": "#eeece6"}, {"name": "Light grey", "hex": "#b9bcbd"}, {"name": "Charcoal", "hex": "#3a3d40"},
    {"name": "Black", "hex": "#1a1b1d"}, {"name": "Sage", "hex": "#9fb7a0"}, {"name": "Blue", "hex": "#3d6fb6"},
    {"name": "Red", "hex": "#c0392b"}, {"name": "Orange", "hex": "#e67e22"}, {"name": "Yellow", "hex": "#f1c40f"},
    {"name": "Sand", "hex": "#d8c7a5"},
]
DEFAULT_COLOR = "#eeece6"


class BlenderMissing(Exception):
    """Blender is not installed or not configured; the message says how to get it."""


class BlenderFailed(Exception):
    def __init__(self, message, hint="", log=""):
        super().__init__(message)
        self.hint, self.log = hint, log


# ---- finding Blender ---------------------------------------------------------

def candidates(cfg: dict | None = None) -> list[str]:
    """Where Blender is looked for, first match wins: [blender].app, the platform's usual places, PATH."""
    out = []
    conf = ((cfg or {}).get("blender") or {}).get("app") or ""
    if conf:
        out.append(os.path.expanduser(conf))
    if sys.platform == "darwin":
        out += ["/Applications/Blender.app/Contents/MacOS/Blender",
                os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender")]
    elif sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if base:
                out += sorted(glob.glob(os.path.join(base, "Blender Foundation", "Blender*", "blender.exe")), reverse=True)
    else:
        out += ["/snap/bin/blender", "/usr/bin/blender", "/usr/local/bin/blender"]
    w = shutil.which("blender")
    if w:
        out.append(w)
    return out


_version_cache: dict = {}


def version(app: str) -> str:
    """'5.2.3' (or '' if Blender does not answer)."""
    if app in _version_cache:
        return _version_cache[app]
    try:
        r = subprocess.run([app, "--version"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace")
        m = re.search(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", r.stdout + r.stderr)
        v = m.group(1) if m else ""
    except (OSError, subprocess.SubprocessError):
        v = ""
    if v:
        _version_cache[app] = v
    return v


def resolve(cfg: dict | None = None) -> dict:
    """{"available", "app", "version", "reason"} for running Blender. Never raises. With its "Use in Form Studio"
    switch off (form/use.py) it is not available, whatever is installed, and Blender is not even asked its version."""
    try:
        from .. import use
        if not use.on("blender", cfg):
            return {"available": False, "app": "", "version": "", "off": True, "reason": use.off_reason("blender")}
    except ImportError:
        pass
    return probe(cfg)


def probe(cfg: dict | None = None) -> dict:
    """Is Blender installed here? The same answer as resolve(), without the switch (Settings shows both)."""
    conf = ((cfg or {}).get("blender") or {}).get("app") or ""
    for c in candidates(cfg):
        if c and Path(c).is_file():
            v = version(c)
            if not v:
                return {"available": False, "app": c, "version": "",
                        "reason": f"{c} did not answer `--version`. Reinstall Blender from {DOWNLOAD_URL}"}
            major = int(v.split(".")[0])
            if major < 4:
                return {"available": False, "app": c, "version": v,
                        "reason": f"Blender {v} is too old; Form Studio needs Blender 4.2 or newer ({DOWNLOAD_URL})."}
            return {"available": True, "app": c, "version": v, "reason": ""}
    where = f"[blender].app = {conf} does not exist. " if conf else ""
    return {"available": False, "app": "", "version": "",
            "reason": where + f"Blender is not installed. Get it free from {DOWNLOAD_URL}, "
                              "or set [blender].app in studio.toml to its executable."}


def print_toolbox(app: str, timeout: float = 90) -> dict:
    """Is Blender's 3D-Print Toolbox installed? It was a bundled add-on (object_print3d_utils) up to Blender 4.1
    and is an extension from extensions.blender.org (print3d_toolbox) since 4.2, so most installs do not have it.
    Reads Blender's add-on list with the user's preferences; changes nothing."""
    expr = "import addon_utils; print('FORM_MODS ' + ','.join(m.__name__ for m in addon_utils.modules()))"
    try:
        r = subprocess.run([app, "-b", "-noaudio", "--python-expr", expr], capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return {"available": False, "module": None, "reason": f"Blender did not answer: {e}"}
    line = next((l for l in r.stdout.splitlines() if l.startswith("FORM_MODS ")), None)
    if line is None:
        return {"available": False, "module": None, "reason": "Blender did not list its add-ons."}
    mods = [m for m in line[10:].split(",") if m]
    hit = next((m for m in mods if "print3d" in m.lower()), None)
    if hit:
        return {"available": True, "module": hit,
                "reason": f"3D-Print Toolbox is installed ({hit}), but Form Studio does not run it yet: Form Studio's own mesh "
                          "checks cover manifold, thickness and overhang."}
    return {"available": False, "module": None,
            "reason": "The 3D-Print Toolbox is not installed (since Blender 4.2 it is an extension, not bundled), "
                      "so Form Studio adds no Blender print checks. Form Studio's own mesh checks still run."}


# ---- numbers the scene needs -------------------------------------------------

def hex_to_linear(hexstr: str) -> list[float]:
    """'#rrggbb' (sRGB) → linear RGB, which is what Blender's colour sockets take."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", hexstr.strip())
    if not m:
        raise ValueError(f"“{hexstr}” is not a colour like #3d6fb6.")
    out = []
    for i in (0, 2, 4):
        c = int(m.group(1)[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def view_dir(az_deg: float, el_deg: float) -> list[float]:
    """Unit vector from the target toward the camera, Z up, same convention as the app's viewport."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    return [math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)]


def frame_camera(lo, hi, az_deg=APP_ISO[0], el_deg=APP_ISO[1], lens_mm=LENS_MM, sensor_mm=SENSOR_MM,
                 aspect=SIZE[0] / SIZE[1], fill=0.72) -> dict:
    """Place a perspective camera so the whole box fits in `fill` of the frame, looking from (az, el).

    lo/hi: the box corners. Returns location, target, distance, horizontal fov (degrees), and the
    largest fraction of the half-width/half-height any corner reaches (≤ fill by construction).
    """
    c = [(a + b) / 2 for a, b in zip(lo, hi)]
    d = view_dir(az_deg, el_deg)
    fwd = [-x for x in d]
    right = _norm(_cross(fwd, [0, 0, 1]))
    up = _cross(right, fwd)
    tan_h = sensor_mm / 2 / lens_mm
    tan_v = tan_h / aspect
    corners = [[(lo, hi)[i >> k & 1][k] - c[k] for k in range(3)] for i in range(8)]
    dist = 0.0
    for p in corners:
        along = _dot(p, d)                 # toward the camera
        need = max(abs(_dot(p, right)) / (tan_h * fill), abs(_dot(p, up)) / (tan_v * fill))
        dist = max(dist, along + need)
    dist = max(dist, 1e-6)
    reach = 0.0
    for p in corners:
        depth = dist - _dot(p, d)
        reach = max(reach, abs(_dot(p, right)) / depth / tan_h, abs(_dot(p, up)) / depth / tan_v)
    return {"location": [c[k] + d[k] * dist for k in range(3)], "target": c, "distance": dist,
            "hfov_deg": math.degrees(2 * math.atan(tan_h)), "reach": reach, "right": right, "up": up}


def stl_bounds(stl: Path) -> tuple[list[float], list[float]]:
    """Axis-aligned bounds of a binary or ASCII STL, without Blender."""
    data = Path(stl).read_bytes()
    lo, hi = [math.inf] * 3, [-math.inf] * 3

    def add(x, y, z):
        for i, v in enumerate((x, y, z)):
            lo[i] = min(lo[i], v)
            hi[i] = max(hi[i], v)
    import struct
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + n * 50 == len(data):
            for i in range(n):
                vals = struct.unpack_from("<12f", data, 84 + i * 50)
                for j in (3, 6, 9):
                    add(*vals[j:j + 3])
            return lo, hi
    for m in re.finditer(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data):
        add(*(float(x) for x in m.groups()))
    if lo[0] == math.inf:
        raise ValueError(f"{Path(stl).name} has no triangles.")
    return lo, hi


def build_job(stl: Path, out_png: Path, preset: str = "studio", finish: str = "matte", color: str = DEFAULT_COLOR,
              layer_mm: float | None = None, fast: bool = False, samples: int = 128,
              size=SIZE, view=APP_ISO, zones: list | None = None) -> dict:
    """Everything the scene script needs, in scene units (metres; the STL is in millimetres).
    zones: [{stl, finish (or None: the asked finish), color (or None)}] renders each zone with its own material
    (a design's appearance()); they replace stl."""
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset “{preset}”. Presets: {', '.join(PRESETS)}.")
    if finish not in FINISHES:
        raise ValueError(f"Unknown material “{finish}”. Materials: {', '.join(FINISHES)}.")
    parts = None
    if zones:
        parts, los, his = [], [], []
        for z in zones:
            fz = z.get("finish") or finish
            if fz not in FINISHES:
                raise ValueError(f"Unknown material “{fz}”. Materials: {', '.join(FINISHES)}.")
            cz = z.get("color") or color
            parts.append({"stl": str(z["stl"]), "finish": dict(FINISHES[fz], id=fz), "color": hex_to_linear(cz),
                          "color_hex": cz})
            a, b = stl_bounds(Path(z["stl"]))
            los.append(a)
            his.append(b)
        lo = [min(x[i] for x in los) for i in range(3)]
        hi = [max(x[i] for x in his) for i in range(3)]
    else:
        lo, hi = stl_bounds(stl)
    span = [b - a for a, b in zip(lo, hi)]
    # the part stands on the floor at the origin; frame it in its placed position (millimetres)
    plo, phi = [-span[0] / 2, -span[1] / 2, 0.0], [span[0] / 2, span[1] / 2, span[2]]
    cam = frame_camera(plo, phi, *view, aspect=size[0] / size[1])
    s = 0.001
    return {
        "scene_version": SCENE_VERSION, "stl": str(stl), "out": str(out_png),
        "preset": preset, "finish": dict(FINISHES[finish], id=finish), "color_hex": color, "color": hex_to_linear(color),
        "offset_mm": [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]], "span_m": [x * s for x in span],
        "size_m": max(span) * s, "layer_mm": layer_mm if layer_mm and 0.04 <= layer_mm <= 1.0 else None,
        "camera": {"location": [x * s for x in cam["location"]], "target": [x * s for x in cam["target"]],
                   "lens_mm": LENS_MM, "sensor_mm": SENSOR_MM, "distance_m": cam["distance"] * s},
        "view": {"az": view[0], "el": view[1]},
        "engine": "eevee" if fast else "cycles", "samples": 32 if fast else int(samples),
        "resolution": list(size), **({"parts": parts} if parts else {}),
    }


# ---- running it ----------------------------------------------------------------

def tail(text: str, lines: int = 25) -> str:
    keep = [l for l in text.splitlines() if l.strip()]
    return "\n".join(keep[-lines:])


def run_job(app: str, job: dict, job_path: Path, timeout: float = 180, progress=None) -> dict:
    """Run Blender headless on a job file. Kills it after `timeout` seconds. Returns the scene's report.

    progress(fraction, text) is called as Blender reports render samples.
    """
    job_path.write_text(json.dumps(job, indent=1), encoding="utf-8")
    cmd = [app, "-b", "--factory-startup", "-noaudio", "--python-exit-code", "3",
           "--python", str(SCENE_SCRIPT), "--", str(job_path)]
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise BlenderFailed(f"Could not start Blender: {e}", f"Check [blender].app, or reinstall from {DOWNLOAD_URL}")
    log: list[str] = []
    killed = {"v": False}

    def watchdog():
        if proc.poll() is None:
            killed["v"] = True
            proc.kill()
    timer = threading.Timer(timeout, watchdog)
    timer.daemon = True
    timer.start()
    sample = re.compile(r"Sample (\d+)/(\d+)")
    try:
        for line in proc.stdout:
            log.append(line.rstrip("\n"))
            if len(log) > 4000:
                del log[:2000]
            m = sample.search(line)
            if m and progress:
                a, b = int(m.group(1)), int(m.group(2))
                progress(min(1.0, a / max(1, b)), f"Sample {a}/{b}")
            elif progress and line.startswith("FORM_STEP "):
                progress(None, line[10:].strip())
        proc.wait()
    finally:
        timer.cancel()
        proc.stdout.close()
    text = "\n".join(log)
    if killed["v"]:
        raise BlenderFailed(f"Blender did not finish within {timeout:.0f} s and was stopped.",
                            "Try the fast (EEVEE) mode, or raise [blender].timeout_s in studio.toml.", tail(text))
    report = None
    for line in reversed(log):
        if line.startswith("FORM_RESULT "):
            try:
                report = json.loads(line[len("FORM_RESULT "):])
            except ValueError:
                pass
            break
    if proc.returncode != 0 or not report or not Path(job["out"]).is_file():
        err = (report or {}).get("error") or f"Blender exited with code {proc.returncode}."
        from .. import compat                       # a Blender outside the supported range that lost an API: say so
        why = compat.wrap_message("blender", version(app), f"Blender could not render: {err}", tail(text, 60))
        if why:
            raise BlenderFailed(why[0], why[1], tail(text))
        raise BlenderFailed(f"Blender could not render: {err}", "The end of Blender's log is attached.", tail(text))
    report["seconds"] = round(time.time() - t0, 2)
    return report
