"""The Bambu Studio family: Bambu Studio and OrcaSlicer share a CLI, a preset layout and a 3MF format.

Both keep presets as JSON files under <config_dir>/system/<vendor>/<kind>/ (and .../<kind>/base/)
and <config_dir>/user/<id>/<kind>/, chain them with "inherits", remember the current selection in
<App>.conf (JSON, followed by a checksum comment), and slice with

    <app> --load-settings "machine.json;process.json" --load-filaments filament.json
          --arrange 1 --slice 0 --export-3mf plate.3mf --outputdir DIR model.stl

writing DIR/plate_1.gcode and DIR/plate.3mf (with Metadata/slice_info.config).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .common import SlicerBlocked, SlicerFailed, private


@dataclass
class Family:
    kind: str                       # "bambu", "orca"
    label: str                      # "Bambu Studio"
    conf_name: str                  # "BambuStudio.conf"
    version_re: str                 # r"BambuStudio-([\d.]+)"
    table: str = ""                 # studio.toml table holding app/config_dir/presets ("" = [slicer] itself)
    deep_search: bool = False       # also look in nested folders / by "name" field (OrcaSlicer's libraries)
    parse_header: object = None     # G-code statistics reader
    version_cache: dict = field(default_factory=dict)

    def where(self, kind: str) -> str:
        return f"[slicer.{self.table}].{kind}" if self.table else f"[slicer].{kind}"


def read_conf(config_dir: Path, conf_name: str) -> dict:
    p = config_dir / conf_name
    if not p.exists():
        return {}
    text = p.read_text(errors="ignore")
    try:
        return json.loads(text[: text.rfind("}") + 1])
    except ValueError:
        return {}


def search_dirs(config_dir: Path, kind: str) -> list[Path]:
    dirs = [d / kind for d in sorted((config_dir / "user").glob("*")) if (d / kind).is_dir()]
    dirs += [d / kind for d in sorted((config_dir / "system").glob("*")) if (d / kind).is_dir()]
    return dirs


def find(fam: Family, config_dir: Path, kind: str, name: str) -> Path:
    dirs = search_dirs(config_dir, kind)
    for d in dirs:
        for cand in (d / f"{name}.json", d / "base" / f"{name}.json"):
            if cand.exists():
                return cand
    if fam.deep_search:
        for d in dirs:
            for cand in sorted(d.rglob(f"{name}.json")):
                return cand
        for d in dirs:
            for cand in sorted(d.rglob("*.json")):
                try:
                    if json.loads(cand.read_text(encoding="utf-8")).get("name") == name:
                        return cand
                except (ValueError, OSError, AttributeError):
                    continue
    raise SlicerBlocked(f"{kind.capitalize()} preset “{name}” was not found under {config_dir}. "
                        f"Open {fam.label} once with this preset selected, or set {fam.where(kind)} in studio.toml.")


def flatten(fam: Family, config_dir: Path, kind: str, name: str, _depth=0) -> dict:
    """Resolve the inheritance chain into one self-contained preset."""
    if _depth > 12:
        raise SlicerBlocked(f"Preset “{name}” has a circular inheritance chain.")
    d = json.loads(find(fam, config_dir, kind, name).read_text(encoding="utf-8"))
    parent = d.get("inherits")
    if parent:
        base = flatten(fam, config_dir, kind, parent, _depth + 1)
        base.update(d)
        d = base
    d.pop("inherits", None)
    return d


def resolve(fam: Family, s: dict, app: Path, config_dir: Path, wanted: dict) -> dict:
    """Which presets a slice would use right now, with content hashes.

    s is [slicer] (for the timeout); wanted maps machine/process/filament to a name or "auto"."""
    out = {"app": str(app), "available": False, "presets": {}, "reason": "", "label": fam.label,
           "config_dir": str(config_dir)}
    if not app.exists():
        out["reason"] = f"{fam.label} was not found at {app}. Install it or set {fam.where('app')} in studio.toml."
        return out
    selected = read_conf(config_dir, fam.conf_name).get("presets", {})
    names = {
        "machine": wanted["machine"] if wanted["machine"] != "auto" else selected.get("machine", ""),
        "process": wanted["process"] if wanted["process"] != "auto" else selected.get("process", ""),
        "filament": wanted["filament"] if wanted["filament"] != "auto" else (selected.get("filaments") or [""])[0],
    }
    out["source"] = {k: ("studio.toml" if wanted[k] != "auto" else f"{fam.label} current selection") for k in names}
    try:
        for kind, name in names.items():
            if not name:
                raise SlicerBlocked(f"No {kind} preset is selected in {fam.label} and none is set in studio.toml.")
            flat = flatten(fam, config_dir, kind, name)
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
        out["reason"] = f"Could not read {fam.label} presets: {e}"
    return out


def version(fam: Family, app: str) -> str:
    if app not in fam.version_cache:
        try:
            with tempfile.TemporaryDirectory() as scratch:     # the CLI drops result.json into its cwd
                r = subprocess.run([app, "--help"], capture_output=True, text=True, timeout=30,
                                   stdin=subprocess.DEVNULL, cwd=scratch)
            m = re.search(fam.version_re, r.stdout + r.stderr)
            fam.version_cache[app] = m.group(1) if m else "unknown"
        except (OSError, subprocess.SubprocessError):
            fam.version_cache[app] = "unavailable"
    return fam.version_cache[app]


def public(fam: Family, resolved: dict) -> dict:
    out = {k: v for k, v in resolved.items() if k != "presets"}
    out["presets"] = {k: {"name": v["name"], "sha": v["sha"]} for k, v in resolved.get("presets", {}).items()}
    if resolved.get("available"):
        out["version"] = version(fam, resolved["app"])
    return out


def slice_stl(fam: Family, resolved: dict, stl: Path, out_dir: Path, timeout: float = 600) -> dict:
    if not resolved.get("available"):
        raise SlicerBlocked(resolved.get("reason") or "Slicer unavailable.")
    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    files = {}
    for kind, p in resolved["presets"].items():
        files[kind] = out_dir / f"preset_{kind}.json"
        files[kind].write_text(json.dumps(p["data"], indent=1), encoding="utf-8")
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
        raise SlicerFailed(f"{fam.label} did not finish within {timeout:g} s.",
                           "Raise [slicer].timeout_s in studio.toml, or simplify the model.")
    except OSError as e:
        raise SlicerBlocked(f"{fam.label} could not be started: {e}")
    log = private(r.stdout + "\n" + r.stderr)
    (out_dir / "slicer.log").write_text(log[-200_000:], encoding="utf-8")
    result = {}
    if (out_dir / "result.json").exists():
        try:
            result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
        except ValueError:
            pass
    gcode = out_dir / "plate_1.gcode"
    threemf = out_dir / "plate.3mf"
    if r.returncode != 0 or not gcode.exists():
        errors = [ln.split("] ", 2)[-1] for ln in log.splitlines() if "[error]" in ln]
        msg = result.get("error_string") or (errors[-1] if errors else f"exit code {r.returncode}")
        raise SlicerFailed(f"{fam.label} refused to slice: {msg}",
                           "The full log is kept beside the failed slice. Check that the presets match the printer.",
                           "\n".join(errors[-8:]))
    info = fam.parse_header(gcode)
    if threemf.exists():
        info.update(read_3mf(threemf, out_dir))
    info.update({
        "seconds": round(time.time() - t0, 2), "slicer_version": version(fam, resolved["app"]),
        "gcode": gcode.name, "threemf": threemf.name if threemf.exists() else None,
        "gcode_sha256": hashlib.sha256(gcode.read_bytes()).hexdigest(),
        "presets": {k: {"name": v["name"], "sha": v["sha"]} for k, v in resolved["presets"].items()},
        "warnings": sorted({ln.split("] ", 2)[-1][:200] for ln in log.splitlines()
                            if "[warning]" in ln and "cli mode" not in ln})[:12],
    })
    return info


def read_3mf(path: Path, out_dir: Path) -> dict:
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
