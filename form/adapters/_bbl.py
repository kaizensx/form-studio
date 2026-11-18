"""The Bambu Studio family: Bambu Studio and OrcaSlicer share a CLI, a preset layout and a 3MF format.

Both keep presets as JSON files under <config_dir>/system/<vendor>/<kind>/ (and .../<kind>/base/)
and <config_dir>/user/<id>/<kind>/, chain them with "inherits", remember the current selection in
<App>.conf (JSON, followed by a checksum comment), and slice with

    <app> --load-settings "machine.json;process.json" --load-filaments filament.json
          --arrange 1 --slice 0 --export-3mf plate.3mf --outputdir DIR model.stl

writing DIR/plate_1.gcode and DIR/plate.3mf (with Metadata/slice_info.config).

OrcaSlicer 2.5+ packs its system presets into one <vendor>.opc per vendor instead of JSON files.
A family that sets cache_dirs gets those read (orca_cache.py) wherever a JSON file is missing;
Bambu Studio does not set it and is resolved from JSON files only, as before.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .common import SlicerBlocked, SlicerFailed, gcode_version, private, program_version


@dataclass
class Family:
    kind: str                       # "bambu", "orca"
    label: str                      # "Bambu Studio"
    conf_name: str                  # "BambuStudio.conf"
    version_re: str                 # r"BambuStudio-([\d.]+)"
    program: str = ""               # the name in its G-code header and of its library on Windows ("BambuStudio")
    table: str = ""                 # studio.toml table holding app/config_dir/presets ("" = [slicer] itself)
    deep_search: bool = False       # also look in nested folders / by "name" field (OrcaSlicer's libraries)
    parse_header: object = None     # G-code statistics reader
    shipped: object = None          # app -> the profiles folders inside the program (<vendor>/<kind>/*.json), for an install never opened
    cache_dirs: object = None       # (app, config_dir) -> folders holding packed <vendor>.opc presets (OrcaSlicer 2.5+)
    selection: object = None        # conf dict -> {"machine", "process", "filament"} chosen in the program
    exit_reasons: dict = field(default_factory=dict)    # CLI return code -> the program's own sentence for it
    bed_type: object = None         # (machine preset, conf dict, machine name) -> the plate the program's window would use
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


def search_dirs(config_dir: Path, kind: str, shipped=()) -> list[Path]:
    """Folders holding JSON presets of one kind: the person's own, the installed vendors, then the
    vendors inside the program (the same files; all there is before the program is first opened)."""
    dirs = [d / kind for d in sorted((config_dir / "user").glob("*")) if (d / kind).is_dir()]
    dirs += [d / kind for d in sorted((config_dir / "system").glob("*")) if (d / kind).is_dir()]
    for root in shipped:
        dirs += [d / kind for d in sorted(Path(root).glob("*")) if (d / kind).is_dir()]
    return dirs


def find(fam: Family, config_dir: Path, kind: str, name: str, shipped=()) -> Path:
    dirs = search_dirs(config_dir, kind, shipped)
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


@dataclass
class Packed:
    """Packed vendor presets (OrcaSlicer 2.5+ <vendor>.opc) to fall back on when there is no JSON file."""
    dirs: list                      # folders to search, in order
    vendor: Path | None = None      # the cache the printer came from: looked in first for the other presets
    json_roots: list = field(default_factory=list)      # shipped profiles folders with JSON presets (Family.shipped)


def load(fam: Family, config_dir: Path, kind: str, name: str, packed: Packed | None = None, within=None):
    """(preset, includes, cache): one preset as stated (its own keys and "inherits"), the presets it
    includes, and the vendor cache it came from (None for a JSON file).

    A JSON file wins. When there is none and the family packs its system presets into vendor
    caches, the preset is read from those. `within` is the cache of the preset that names this
    one as its parent: a parent is only ever taken from the same vendor or the filament library."""
    try:
        roots = packed.json_roots if packed else ()
        return json.loads(find(fam, config_dir, kind, name, roots).read_text(encoding="utf-8")), [], None
    except SlicerBlocked as missing:
        if packed is None or not packed.dirs:
            raise
        from . import orca_cache
        preset, path, problems = orca_cache.find(packed.dirs, kind, name, within=within, prefer=packed.vendor)
        if preset is None:
            if within:
                msg = (f"{kind.capitalize()} preset “{name}” was not found. It is a parent of a preset in "
                       f"{within}, and is neither in that file nor in the {orca_cache.LIBRARY} beside it.")
            else:
                where = ", ".join(str(c) for c in packed.dirs)
                msg = (f"{kind.capitalize()} preset “{name}” was not found: not as a JSON file under {config_dir}, "
                       f"and not in the packed vendor presets (*.opc) in {where}. "
                       f"Check the spelling of {fam.where(kind)} in studio.toml.")
            if problems:
                msg += " Could not read: " + " ".join(problems[:2])
            raise SlicerBlocked(msg) from missing
        if packed.vendor is None and path.stem != orca_cache.LIBRARY:
            packed.vendor = path
        d = preset.to_json()
        return d, d.pop("include", []), path


def flatten(fam: Family, config_dir: Path, kind: str, name: str, _depth=0, packed: Packed | None = None,
            within=None) -> dict:
    """Resolve the inheritance chain into one self-contained preset."""
    if _depth > 12:
        raise SlicerBlocked(f"Preset “{name}” has a circular inheritance chain.")
    d, includes, cache = load(fam, config_dir, kind, name, packed, within)
    parent = d.get("inherits")
    if parent or includes:
        base = flatten(fam, config_dir, kind, parent, _depth + 1, packed, cache) if parent else {}
        for inc in includes:            # OrcaSlicer layers these over the parent, under the preset's own keys
            layer = flatten(fam, config_dir, kind, inc, _depth + 1, packed, cache)
            for meta in ("type", "name", "from", "setting_id", "filament_id", "instantiation", "description"):
                layer.pop(meta, None)
            base.update(layer)
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
    conf = read_conf(config_dir, fam.conf_name)
    if fam.selection:
        chosen = fam.selection(conf)
    else:
        selected = conf.get("presets") or {}
        chosen = {"machine": selected.get("machine", ""), "process": selected.get("process", ""),
                  "filament": (selected.get("filaments") or [""])[0]}
    names = {k: wanted[k] if wanted[k] != "auto" else (chosen.get(k) or "") for k in ("machine", "process", "filament")}
    packed = None
    if fam.cache_dirs or fam.shipped:
        packed = Packed(list(fam.cache_dirs(app, config_dir)) if fam.cache_dirs else [],
                        json_roots=list(fam.shipped(app)) if fam.shipped else [])
    out["source"] = {k: ("studio.toml" if wanted[k] != "auto" else f"{fam.label} current selection") for k in names}
    try:
        for kind, name in names.items():
            if not name:
                raise SlicerBlocked(no_selection(fam, config_dir, kind, names, bool(conf)))
            flat = flatten(fam, config_dir, kind, name, packed=packed)
            if kind == "filament":
                # A per-filament list a vendor left empty ("default_filament_colour": "" in Cubicon's
                # presets) aborts the CLI: "ConfigOptionVector::set_at(): Assigning from an empty vector".
                # Left out, the program's own default applies, which is what its window does with it.
                flat = {k: v for k, v in flat.items() if v != []}
            if kind == "process" and fam.bed_type:
                machine = out["presets"]["machine"]["data"]
                if "curr_bed_type" not in flat and "curr_bed_type" not in machine:
                    flat["curr_bed_type"] = fam.bed_type(machine, conf, names["machine"])
            flat["name"] = name
            flat["from"] = "system"
            if kind == "machine":
                chain = machine_chain(fam, config_dir, name, packed)
                if len(chain) > 1 and is_user(fam, config_dir, "machine", name):
                    # a person's own printer: the CLI checks process compatibility against the system printer it
                    # inherits from. For a preset "from" "system" it takes the preset's own name as that printer;
                    # only "from": "User" makes it read "inherits" (BambuStudio.cpp run(): "new printer …, inherited
                    # from …, compatible 0" and exit -17 for a user printer passed as a system one)
                    flat["from"] = "User"
                    flat["inherits"] = next((n for n in chain[1:] if not n.startswith("fdm_")), chain[1])
            idkey = {"machine": "printer_settings_id", "process": "print_settings_id", "filament": "filament_settings_id"}[kind]
            flat[idkey] = [name] if kind == "filament" else name
            blob = json.dumps(flat, sort_keys=True).encode()
            out["presets"][kind] = {"name": name, "sha": hashlib.sha256(blob).hexdigest()[:16], "data": flat}
        plate_for_filament(out)
        m, p = out["presets"]["machine"]["data"], out["presets"]["process"]["data"]
        compat = p.get("compatible_printers") or []
        # a user printer is compatible with what its system printer is (the program checks the preset it inherits from)
        if compat and not set(machine_chain(fam, config_dir, names["machine"], packed)) & set(compat):
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


# the build plate -> the filament key holding its bed temperature; 0 there means the filament cannot be printed on it
PLATE_TEMP = {"Cool Plate": "cool_plate_temp", "Engineering Plate": "eng_plate_temp", "High Temp Plate": "hot_plate_temp",
              "Textured PEI Plate": "textured_plate_temp", "Textured Cool Plate": "textured_cool_plate_temp",
              "Supertack Plate": "supertack_plate_temp"}
PLATE_ORDER = ("Textured PEI Plate", "High Temp Plate", "Engineering Plate", "Cool Plate", "Textured Cool Plate", "Supertack Plate")


def plate_for_filament(out: dict) -> None:
    """When the build plate the slice would use (stated in the process or printer, else the CLI's Cool Plate) has
    no bed temperature for this filament, use the first plate that has one, and say so in out["plate_note"].

    The CLI refuses such a slice outright ("Filaments are not compatible with the plate type"); the slicer's window
    would make you pick another plate. Nothing changes for a filament the plate supports."""
    pr = out["presets"]
    m, p, f = pr["machine"]["data"], pr["process"]["data"], pr["filament"]["data"]
    plate = p.get("curr_bed_type") or m.get("curr_bed_type") or "Cool Plate"

    def temp(name):
        v = f.get(PLATE_TEMP.get(name, ""))
        v = v[0] if isinstance(v, list) and v else v
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if plate not in PLATE_TEMP or temp(plate) is None or temp(plate) > 0:
        return
    for other in PLATE_ORDER:
        t = temp(other)
        if t and t > 0:
            p = dict(p, curr_bed_type=other)
            blob = json.dumps(p, sort_keys=True).encode()
            pr["process"] = dict(pr["process"], data=p, sha=hashlib.sha256(blob).hexdigest()[:16])
            out["plate_note"] = f"{pr['filament']['name']} cannot be printed on the {plate}; the slice uses the {other}."
            return


def is_user(fam: Family, config_dir: Path, kind: str, name: str) -> bool:
    """Whether a preset is one of the person's own (a JSON file under <config>/user/)."""
    try:
        path = find(fam, config_dir, kind, name)
    except SlicerBlocked:
        return False
    try:
        path.resolve().relative_to((config_dir / "user").resolve())
        return True
    except ValueError:
        return False


def machine_chain(fam: Family, config_dir: Path, name: str, packed: Packed | None = None) -> list:
    """The printer preset and the presets it inherits from, nearest first."""
    out = []
    while name and len(out) < 12:
        out.append(name)
        try:
            d, _inc, _cache = load(fam, config_dir, "machine", name, packed)
        except SlicerBlocked:
            break
        name = d.get("inherits") or ""
    return out


def no_selection(fam: Family, config_dir: Path, kind: str, names: dict, has_conf: bool) -> str:
    """Why there is no preset of this kind to slice with, in words that match what is on disk."""
    fix = f"Choose one in {fam.label}, or set {fam.where(kind)} in studio.toml."
    if not has_conf:
        return (f"{fam.label} has no saved selection yet ({config_dir / fam.conf_name} is missing or unreadable), "
                f"so there is no {kind} preset to follow. Open {fam.label} once, or set {fam.where(kind)} in studio.toml.")
    if kind != "machine" and names.get("machine"):
        return (f"{fam.label} has the printer “{names['machine']}” selected but no {kind} preset saved for it "
                f"in {fam.conf_name}. {fix}")
    return f"No {kind} preset is selected in {fam.label} ({fam.conf_name}) and none is set in studio.toml. {fix}"


def version(fam: Family, app: str) -> str:
    if app not in fam.version_cache:
        fam.version_cache[app] = program_version(app, fam.version_re, (fam.program + ".dll",))
    return fam.version_cache[app]


def sliced_version(fam: Family, app: str, gcode: Path) -> str:
    """The program's version for a slice: as the program reports it, else as that G-code states it."""
    v = version(fam, app)
    if v in ("unknown", "unavailable"):
        said = gcode_version(gcode, fam.program)
        if said:
            v = fam.version_cache[app] = said
    return v


def public(fam: Family, resolved: dict) -> dict:
    out = {k: v for k, v in resolved.items() if k != "presets"}
    out["presets"] = {k: {"name": v["name"], "sha": v["sha"]} for k, v in resolved.get("presets", {}).items()}
    if resolved.get("available"):
        out["version"] = version(fam, resolved["app"])
    return out


@contextlib.contextmanager
def cli_env():
    """The environment the CLI runs in: the person's own, except on macOS, where it gets an empty
    throwaway home (CFFIXED_USER_HOME) for the length of the run.

    Why: the CLI starts AppKit to draw the plate thumbnail. After any earlier crash of the program
    (its CLI included) macOS then asks "…quit unexpectedly while reopening windows. Reopen?" in a
    modal window on the person's screen, and the slice sits behind it until the timeout; a slice
    killed there counts as one more crash. Seen with OrcaSlicer 2.5.1 on macOS 27. The crash history
    and saved window state are per home folder, so a fresh one never asks. Presets are passed as
    files and results are written to the output folder, so nothing is read from the real home."""
    if sys.platform != "darwin":
        yield None
        return
    home = tempfile.mkdtemp(prefix="form-slicer-home-")
    try:
        yield {**os.environ, "CFFIXED_USER_HOME": home}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def exit_code(returncode: int) -> int:
    """The CLI returns small negative numbers; the system hands them back wrapped (POSIX: 256 + n,
    Windows: 2**32 + n)."""
    if returncode > 0x7FFFFFFF:
        return returncode - (1 << 32)
    if 128 <= returncode <= 255:
        return returncode - 256
    return returncode


def own_logs(out_dir: Path) -> str:
    """OrcaSlicer 2.5 writes its log to numbered files in the working folder (00000.log), not to
    stdout. They are read into slicer.log and removed: they carry full paths."""
    text = []
    for p in sorted(out_dir.glob("*.log")):
        if p.name == "slicer.log":
            continue
        try:
            text.append(p.read_text(encoding="utf-8", errors="ignore"))
            p.unlink()
        except OSError:
            continue
    return "\n".join(text)


def refusal(fam: Family, returncode: int, said: str, errors: list, result: dict) -> str:
    """Why the CLI did not slice, in its own words where it gave any."""
    if result.get("error_string"):
        return result["error_string"]
    if errors:
        return errors[-1]
    lines = [ln.strip() for ln in said.splitlines() if ln.strip() and ln.strip() != "run found error, exit"]
    own = " ".join(lines[-6:])[:600] if len(lines) <= 12 else ""       # a few lines: its message. Many: usage text.
    if os.name == "posix" and returncode < 0:
        return f"it crashed (signal {-returncode})" + (f": {own}" if own else "")
    code = exit_code(returncode)
    reason = (fam.exit_reasons or {}).get(code, "")
    return " ".join(x for x in (reason, own, f"(exit code {code})") if x)


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
        with cli_env() as env:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=out_dir,
                               stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        (out_dir / "slicer.log").write_text(private(own_logs(out_dir))[-200_000:], encoding="utf-8")
        raise SlicerFailed(f"{fam.label} did not finish within {timeout:g} s.",
                           "Raise [slicer].timeout_s in studio.toml, or simplify the model.")
    except OSError as e:
        raise SlicerBlocked(f"{fam.label} could not be started: {e}")
    said = private(r.stdout + "\n" + r.stderr)
    own = private(own_logs(out_dir))
    log = said + ("\n" + own if own else "")
    (out_dir / "slicer.log").write_text(log[-200_000:], encoding="utf-8")
    result = {}
    if (out_dir / "result.json").exists():
        try:
            result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
        except ValueError:
            pass
    gcode = out_dir / "plate_1.gcode"
    threemf = out_dir / "plate.3mf"
    # Some builds (Snapmaker Orca on Windows with software OpenGL) write the whole G-code, say so, and then crash
    # drawing the project's thumbnail. The G-code is complete (it was renamed from .tmp only once fully written), so it
    # is used and the exit is reported as a warning; the project 3MF from that run is not.
    after_gcode = (r.returncode != 0 and gcode.exists()
                   and "Slicing result exported to" in log and not (out_dir / "plate_1.gcode.tmp").exists())
    if after_gcode and threemf.exists():
        threemf.unlink()
    if (r.returncode != 0 and not after_gcode) or not gcode.exists():
        errors = [ln.split("] ", 2)[-1] for ln in log.splitlines() if "[error]" in ln]
        msg = refusal(fam, r.returncode, said, errors, result)
        tail = errors[-8:] or [ln for ln in (own or said).splitlines() if ln.strip()][-12:]
        raise SlicerFailed(f"{fam.label} refused to slice: {msg}",
                           "The full log is kept beside the failed slice. Check that the presets match the printer.",
                           "\n".join(tail))
    info = fam.parse_header(gcode)
    if threemf.exists():
        info.update(read_3mf(threemf, out_dir))
    info.update({
        "seconds": round(time.time() - t0, 2), "slicer_version": sliced_version(fam, resolved["app"], gcode),
        "gcode": gcode.name, "threemf": threemf.name if threemf.exists() else None,
        "gcode_sha256": hashlib.sha256(gcode.read_bytes()).hexdigest(),
        "presets": {k: {"name": v["name"], "sha": v["sha"]} for k, v in resolved["presets"].items()},
        "warnings": sorted({ln.split("] ", 2)[-1][:200] for ln in log.splitlines()
                            if "[warning]" in ln and "cli mode" not in ln}
                           | {ln[len("got warnings: "):][:200] for ln in log.splitlines()
                              if ln.startswith("got warnings: ")})[:12],
    })
    if after_gcode:
        info["warnings"] = [f"{fam.label} exited with code {r.returncode} after writing the G-code, while drawing the "
                            "project thumbnail. The G-code is complete; no project 3MF was kept from this run."] + info["warnings"]
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
