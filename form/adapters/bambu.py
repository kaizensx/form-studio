"""Slicer adapter for the Bambu Studio CLI: resolve the configured presets, slice, read results.

A slice is a simulation by the slicer. It says the model can be toolpathed with
these presets and estimates time and material. It is not a print.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree


class SlicerBlocked(Exception):
    """The slicer cannot run here; message says exactly why."""


class SlicerFailed(Exception):
    def __init__(self, message, hint="", log=""):
        super().__init__(message)
        self.hint, self.log = hint, log


def _conf(config_dir: Path) -> dict:
    p = config_dir / "BambuStudio.conf"
    if not p.exists():
        return {}
    text = p.read_text(errors="ignore")
    try:
        return json.loads(text[: text.rfind("}") + 1])
    except ValueError:
        return {}


def _search_dirs(config_dir: Path, kind: str) -> list[Path]:
    dirs = [d / kind for d in sorted((config_dir / "user").glob("*")) if (d / kind).is_dir()]
    dirs += [d / kind for d in sorted((config_dir / "system").glob("*")) if (d / kind).is_dir()]
    return dirs


def _find(config_dir: Path, kind: str, name: str) -> Path:
    for d in _search_dirs(config_dir, kind):
        for cand in (d / f"{name}.json", d / "base" / f"{name}.json"):
            if cand.exists():
                return cand
    raise SlicerBlocked(f"{kind.capitalize()} preset “{name}” was not found under {config_dir}. "
                        f"Open Bambu Studio once with this preset selected, or set [slicer].{kind} in studio.toml.")


def flatten(config_dir: Path, kind: str, name: str, _depth=0) -> dict:
    """Resolve the inheritance chain into one self-contained preset."""
    if _depth > 12:
        raise SlicerBlocked(f"Preset “{name}” has a circular inheritance chain.")
    d = json.loads(_find(config_dir, kind, name).read_text())
    parent = d.get("inherits")
    if parent:
        base = flatten(config_dir, kind, parent, _depth + 1)
        base.update(d)
        d = base
    d.pop("inherits", None)
    return d


def resolve(cfg: dict) -> dict:
    """Which presets a slice would use right now, with content hashes."""
    s = cfg["slicer"]
    app = Path(shutil.which(s["app"]) or s["app"]).expanduser()
    config_dir = Path(s["config_dir"]).expanduser()
    out = {"app": str(app), "available": False, "presets": {}, "reason": ""}
    if not app.exists():
        out["reason"] = f"Bambu Studio was not found at {app}. Install it or set [slicer].app in studio.toml."
        return out
    selected = _conf(config_dir).get("presets", {})
    names = {
        "machine": s["machine"] if s["machine"] != "auto" else selected.get("machine", ""),
        "process": s["process"] if s["process"] != "auto" else selected.get("process", ""),
        "filament": s["filament"] if s["filament"] != "auto" else (selected.get("filaments") or [""])[0],
    }
    out["source"] = {k: ("studio.toml" if s[k] != "auto" else "Bambu Studio current selection") for k in names}
    try:
        for kind, name in names.items():
            if not name:
                raise SlicerBlocked(f"No {kind} preset is selected in Bambu Studio and none is set in studio.toml.")
            flat = flatten(config_dir, kind, name)
            flat["name"] = name
            flat["from"] = "system"
            idkey = {"machine": "printer_settings_id", "process": "print_settings_id", "filament": "filament_settings_id"}[kind]
            flat[idkey] = [name] if kind == "filament" else name
            blob = json.dumps(flat, sort_keys=True).encode()
            out["presets"][kind] = {"name": name, "sha": hashlib.sha256(blob).hexdigest()[:16], "data": flat}
        m, p = out["presets"]["machine"]["data"], out["presets"]["process"]["data"]
        compat = p.get("compatible_printers") or []
        if compat and names["machine"] not in compat:
            raise SlicerBlocked(f"Process “{names['process']}” is not compatible with “{names['machine']}”.")
        out["nozzle_mm"] = float((m.get("nozzle_diameter") or ["0.4"])[0])
        out["layer_height_mm"] = float(p.get("layer_height", 0.2))
        area = m.get("printable_area") or []
        if area:
            xs = [float(a.split("x")[0]) for a in area]
            ys = [float(a.split("x")[1]) for a in area]
            out["envelope_mm"] = [max(xs) - min(xs), max(ys) - min(ys), float(m.get("printable_height", 180))]
        out["summary"] = {
            "walls": p.get("wall_loops"), "infill": p.get("sparse_infill_density"),
            "supports": p.get("enable_support"), "plate": p.get("curr_bed_type") or m.get("curr_bed_type"),
            "filament_type": (out["presets"]["filament"]["data"].get("filament_type") or ["?"])[0],
            "density": float((out["presets"]["filament"]["data"].get("filament_density") or ["1.24"])[0]),
        }
        out["available"] = True
    except SlicerBlocked as e:
        out["reason"] = str(e)
    except (ValueError, OSError) as e:
        out["reason"] = f"Could not read Bambu Studio presets: {e}"
    return out


_version_cache: dict = {}


def version(app: str) -> str:
    if app not in _version_cache:
        try:
            with tempfile.TemporaryDirectory() as scratch:     # the CLI drops result.json into its cwd
                r = subprocess.run([app, "--help"], capture_output=True, text=True, timeout=30,
                                   stdin=subprocess.DEVNULL, cwd=scratch)
            m = re.search(r"BambuStudio-([\d.]+)", r.stdout + r.stderr)
            _version_cache[app] = m.group(1) if m else "unknown"
        except (OSError, subprocess.SubprocessError):
            _version_cache[app] = "unavailable"
    return _version_cache[app]


def public(resolved: dict) -> dict:
    out = {k: v for k, v in resolved.items() if k != "presets"}
    out["presets"] = {k: {"name": v["name"], "sha": v["sha"]} for k, v in resolved.get("presets", {}).items()}
    if resolved.get("available"):
        out["version"] = version(resolved["app"])
    return out


def _private(text: str) -> str:
    """Logs are shipped with projects; never let them carry the user's home path."""
    return text.replace(str(Path.home()), "~")


def slice_stl(resolved: dict, stl: Path, out_dir: Path, timeout: float = 600) -> dict:
    if not resolved.get("available"):
        raise SlicerBlocked(resolved.get("reason") or "Slicer unavailable.")
    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    files = {}
    for kind, p in resolved["presets"].items():
        files[kind] = out_dir / f"preset_{kind}.json"
        files[kind].write_text(json.dumps(p["data"], indent=1))
    local = out_dir / "model.stl"
    shutil.copyfile(stl, local)
    cmd = [resolved["app"], "--debug", "3",
           "--load-settings", f"{files['machine']};{files['process']}",
           "--load-filaments", str(files["filament"]),
           "--arrange", "1", "--slice", "0",
           "--export-3mf", "plate.3mf", "--outputdir", str(out_dir), str(local)]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=out_dir, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SlicerFailed(f"Bambu Studio did not finish within {timeout:g} s.",
                           "Raise [slicer].timeout_s in studio.toml, or simplify the model.")
    except OSError as e:
        raise SlicerBlocked(f"Bambu Studio could not be started: {e}")
    log = _private(r.stdout + "\n" + r.stderr)
    (out_dir / "slicer.log").write_text(log[-200_000:])
    result = {}
    if (out_dir / "result.json").exists():
        try:
            result = json.loads((out_dir / "result.json").read_text())
        except ValueError:
            pass
    gcode = out_dir / "plate_1.gcode"
    threemf = out_dir / "plate.3mf"
    if r.returncode != 0 or not gcode.exists():
        errors = [ln.split("] ", 2)[-1] for ln in log.splitlines() if "[error]" in ln]
        msg = result.get("error_string") or (errors[-1] if errors else f"exit code {r.returncode}")
        raise SlicerFailed(f"Bambu Studio refused to slice: {msg}",
                           "The full log is kept beside the failed slice. Check that the presets match the printer.",
                           "\n".join(errors[-8:]))
    info = parse_gcode_header(gcode)
    if threemf.exists():
        info.update(_read_3mf(threemf, out_dir))
    info.update({
        "seconds": round(time.time() - t0, 2), "slicer_version": version(resolved["app"]),
        "gcode": gcode.name, "threemf": threemf.name if threemf.exists() else None,
        "gcode_sha256": hashlib.sha256(gcode.read_bytes()).hexdigest(),
        "presets": {k: {"name": v["name"], "sha": v["sha"]} for k, v in resolved["presets"].items()},
        "warnings": sorted({ln.split("] ", 2)[-1][:200] for ln in log.splitlines()
                            if "[warning]" in ln and "cli mode" not in ln})[:12],
    })
    return info


def _read_3mf(path: Path, out_dir: Path) -> dict:
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "Metadata/slice_info.config" in names:
                root = ElementTree.fromstring(z.read("Metadata/slice_info.config"))
                for meta in root.iter("metadata"):
                    k, v = meta.get("key"), meta.get("value")
                    if k == "prediction":
                        out["time_s"] = float(v)
                    elif k == "weight":
                        out["filament_g"] = float(v)
                    elif k == "support_used":
                        out["support_used"] = v == "true"
                for w in root.iter("warning"):
                    out.setdefault("plate_warnings", []).append(w.get("msg"))
            for cand in ("Metadata/plate_1.png", "Metadata/top_1.png"):
                if cand in names:
                    (out_dir / Path(cand).name).write_bytes(z.read(cand))
                    out.setdefault("images", []).append(Path(cand).name)
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError):
        out["threemf_unreadable"] = True
    return out


def parse_gcode_header(path: Path) -> dict:
    out, n = {}, 0
    pats = {
        "layers": r"^; total layer number: (\d+)", "max_z_mm": r"^; max_z_height: ([\d.]+)",
        "filament_mm": r"^; total filament length \[mm\] : ([\d.]+)",
        "filament_g": r"^; total filament weight \[g\] : ([\d.]+)",
        "model_time": r"^; model printing time: ([^;]+);", "total_time": r"total estimated time: (.+)$",
    }
    with open(path, errors="ignore") as f:
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


def _dur(text: str) -> float:
    total = 0.0
    for num, unit in re.findall(r"(\d+)\s*([dhms])", text):
        total += int(num) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total


def parse_layers(path: Path) -> list[dict]:
    """Extrusion paths per layer, by slicer feature type, for inspection."""
    layers, cur, x, y, z, feat, path_pts = [], None, 0.0, 0.0, 0.0, "", None
    relative_e, last_e = True, 0.0

    def close():
        nonlocal path_pts
        if path_pts and len(path_pts["p"]) >= 4 and cur is not None:
            cur["paths"].append(path_pts)
        path_pts = None

    with open(path, errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line[0] == ";":
                if line.startswith("; CHANGE_LAYER"):
                    close()
                    cur = {"z": z, "paths": []}
                    layers.append(cur)
                elif line.startswith("; Z_HEIGHT:") and cur is not None:
                    cur["z"] = float(line.split(":")[1])
                elif line.startswith("; FEATURE:"):
                    close()
                    feat = line.split(":", 1)[1].strip()
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
