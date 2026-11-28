"""Open in <Slicer>: the design sliced with settings chosen for this part on this printer, opened as a project.

    from form import slicer_open
    r = slicer_open.run(st, p)                    # choose, slice for real, write the project 3MF, open it
    r = slicer_open.run(st, p, open_app=False)    # the same without opening the slicer (CLI --no-open, tests)
    d = slicer_open.choose(inputs)                # the pure part: inputs -> decisions with reasons

What it does, in order:

1. Orientation: the orientation finder's first choice (form/analysis.py, a computed ranking). A part of several
   solids keeps the orientation set for each part (the plate plan).
2. Settings: layer height, walls, top and bottom layers, infill, supports, brim, seam, filament and the speed profile
   (which of the printer's own process presets to start from). Each decision says what it is, why, and how that is
   known: "computed" (measured on the geometry or arithmetic from it) or "heuristic" (a rule of thumb applied to
   computed inputs). Nothing is a physical result.
3. Starts from the slicer's own process preset for the printer at the chosen layer height and overrides only the keys
   decided here, and only keys that preset already has, with values from the slicer's own vocabulary. Numbers come
   from the printer's presets (layer heights) or are counts and percentages the slicer accepts.
4. Slices for real with the slicer's CLI (form/slicer.py), so time and grams are the slicer's own estimate (simulated),
   and keeps the project 3MF the CLI writes: plate, oriented part, process with the overrides, filament. For Bambu
   Studio and OrcaSlicer the changed keys are listed in the project's different_settings_to_system, as the program
   does when you change a setting yourself, so it shows them as edits of its preset.
5. Reads the project 3MF back and checks every override is in it, then opens it in the slicer's own app.

Nothing is sent anywhere and nothing is printed. A slice is a simulation, not a print.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
import zipfile
from pathlib import Path

VERSION = 1

BBL_KINDS = ("bambu", "orca", "elegoo", "snapmaker")       # one CLI and one project format (form/adapters/_bbl.py)

# the slicer's own words for each setting: an override is written only when the preset already uses this vocabulary
VOCAB = {
    "bbl": {
        "layer": "layer_height", "walls": "wall_loops", "top": "top_shell_layers", "bottom": "bottom_shell_layers",
        "infill": "sparse_infill_density", "pattern": "sparse_infill_pattern", "support": "enable_support",
        "support_style": "support_type", "brim": "brim_type", "brim_width": "brim_width", "seam": "seam_position",
    },
    "prusa": {
        "layer": "layer_height", "walls": "perimeters", "top": "top_solid_layers", "bottom": "bottom_solid_layers",
        "infill": "fill_density", "pattern": "fill_pattern", "support": "support_material",
        "support_style": "support_material_style", "brim": "brim_type", "brim_width": "brim_width", "seam": "seam_position",
    },
}
ENUMS = {
    "bbl": {
        "pattern": {"concentric", "zig-zag", "grid", "line", "cubic", "triangles", "tri-hexagon", "gyroid", "honeycomb",
                    "adaptivecubic", "alignedrectilinear", "3dhoneycomb", "hilbertcurve", "archimedeanchords",
                    "octagramspiral", "supportcubic", "lightning", "crosshatch", "zigzag", "rectilinear"},
        "support_style": {"normal(auto)", "tree(auto)", "normal(manual)", "tree(manual)", "hybrid(auto)"},
        "brim": {"auto_brim", "brim_ears", "outer_only", "inner_only", "outer_and_inner", "no_brim", "painted"},
        "seam": {"nearest", "aligned", "back", "random", "aligned_back"},
    },
    "prusa": {
        "pattern": {"rectilinear", "alignedrectilinear", "grid", "triangles", "stars", "cubic", "line", "concentric",
                    "honeycomb", "3dhoneycomb", "gyroid", "hilbertcurve", "archimedeanchords", "octagramspiral",
                    "adaptivecubic", "supportcubic", "lightning", "zigzag", "crosshatch"},
        "support_style": {"grid", "snug", "organic"},
        "brim": {"no_brim", "outer_only", "inner_only", "outer_and_inner"},
        "seam": {"random", "nearest", "aligned", "rear", "cost", "near", "scarf"},
    },
}
# our abstract value -> the slicer's word
WORDS = {
    "bbl": {"tree": "tree(auto)", "normal": "normal(auto)", "back": "back", "outer": "outer_only"},
    "prusa": {"tree": "organic", "normal": "grid", "back": "rear", "outer": "outer_only"},
}

LOAD_WORDS = re.compile(r"\b(loads?|weight|heavy|holds?|holding|bears?|bearing|brackets?|hooks?|hang(s|er|ing)?|mounts?|"
                        r"clamps?|strong|strength|shel(f|ves)|structural|tension|torque|lever|handle)\b", re.I)
COSMETIC_WORDS = re.compile(r"\b(decor|decorative|display|vase|figurine|ornament|sculpture|statue|visible|gift|art|"
                            r"pretty|cosmetic|showpiece)\b", re.I)
LOAD_CHECKS = re.compile(r"safety factor|pull-out|load|strength|stress|deflection", re.I)
STRONG_PRESET = re.compile(r"\b(strength|structural|strong)\b", re.I)
PLAIN_PRESET = re.compile(r"\b(standard|optimal|quality|fine|normal|speed|draft)\b", re.I)
AVOID_PRESET = re.compile(r"\b(support|test|calibrat|vase|spiral)\b", re.I)


def _err(msg, hint="", status=409):
    from .studio import StudioError
    return StudioError(msg, hint, status=status)


def family(kind: str) -> str:
    return "bbl" if kind in BBL_KINDS else "prusa"


def _f(v):
    """A preset value as a number: "15%" -> 15, ["0.28"] -> 0.28, "" -> None."""
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None:
        return None
    try:
        return float(str(v).strip().rstrip("%"))
    except ValueError:
        return None


def _s(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v if v is not None else "")


def layer_of(name: str):
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*mm\b", name or "")
    return float(m.group(1)) if m else None


# ---- the pure part: inputs -> decisions ---------------------------------------------------------------------------

def choose(i: dict) -> dict:
    """Decide the settings for one part from computed inputs. Deterministic; no files, no slicer.

    i: nozzle_mm, layer_options (layer heights of the printer's own process presets), min_layer_mm, max_layer_mm,
       height_mm, footprint_mm [a, b], contact_mm2, steep_mm2, ceiling_mm2, support_mm3, sloped_share (0..1),
       thin_wall_mm (or None), load {"bearing": bool, "why": str}, cosmetic {"is": bool, "why": str},
       material {"key", "warp", "flexible"} (or None), orientation {"label", "why", "evidence"} (optional),
       preset {walls, top, bottom, infill, pattern, support, brim, brim_width, seam} (the starting preset's values).

    Returns {"want": {setting: value}, "decisions": [{id, label, value, why, evidence, changed}]}. Only settings in
    "want" are written over the preset; the rest of the decisions explain why the preset's value stays."""
    nz = float(i.get("nozzle_mm") or 0.4)
    pre = i.get("preset") or {}
    load = i.get("load") or {}
    cos = i.get("cosmetic") or {}
    mat = i.get("material") or {}
    H = float(i.get("height_mm") or 0)
    fp = sorted(float(x) for x in (i.get("footprint_mm") or [0, 0]))
    slope = float(i.get("sloped_share") or 0)
    thin = i.get("thin_wall_mm")
    want, out = {}, []

    def add(id_, label, value, why, evidence, changed):
        out.append({"id": id_, "label": label, "value": value, "why": why, "evidence": evidence, "changed": changed})

    # orientation (decided by the caller from the orientation finder)
    o = i.get("orientation")
    if o:
        add("orientation", "Orientation", o["label"], o["why"], o.get("evidence", "computed"), bool(o.get("changed")))

    # layer height: half the nozzle unless the surface or the size argues otherwise, then the nearest preset's height
    target, why = 0.5 * nz, f"half the {nz:g} mm nozzle: the usual balance of detail and print time"
    if slope >= 0.35:
        target, why = 0.4 * nz, f"{slope:.0%} of the surface is sloped or curved; thinner layers show less stair-stepping"
    elif 0 < H < 12:
        target, why = 0.4 * nz, f"a short part ({H:.1f} mm): finer layers cost little time"
    elif H > 120 and slope < 0.15:
        target, why = 0.6 * nz, f"tall ({H:.0f} mm) with mostly flat and vertical surfaces: thicker layers save time without visible steps"
    lo = max(0.25 * nz, float(i.get("min_layer_mm") or 0))
    hi = min(0.75 * nz, float(i.get("max_layer_mm") or 9))
    target = min(max(target, lo), hi)
    opts = sorted({round(float(x), 3) for x in (i.get("layer_options") or []) if lo - 1e-6 <= float(x) <= hi + 1e-6})
    layer = min(opts, key=lambda x: (abs(x - target), -x)) if opts else round(target, 2)
    want["layer"] = layer
    add("layer", "Layer height", f"{layer:g} mm", why + (f"; {layer:g} mm is the nearest of this printer's presets"
                                                       if opts and abs(layer - target) > 1e-6 else ""), "heuristic", True)

    # walls: strength in bending and pull-out comes mostly from perimeters
    line = 1.125 * nz
    walls_pre = int(_f(pre.get("walls")) or 2)
    if load.get("bearing"):
        walls = max(walls_pre, 4)
        add("walls", "Walls", str(walls), f"load-bearing ({load.get('why')}): bending and pull-out strength come mostly "
            "from the perimeters" + (f"; the preset already has {walls_pre}" if walls == walls_pre else ", so at least 4"),
            "heuristic", walls != walls_pre)
    elif thin is not None and thin <= 4 * line:
        walls = max(walls_pre, 2)
        add("walls", "Walls", str(walls), f"the thinnest wall ({thin:.2f} mm, computed) is filled by perimeters anyway",
            "computed", walls != walls_pre)
    else:
        walls = max(walls_pre, 2)
        add("walls", "Walls", str(walls), "no stated load: the preset's walls are enough", "heuristic", walls != walls_pre)
    if walls != walls_pre:
        want["walls"] = walls

    # top and bottom layers: a solid skin of about 1 mm (1.2 mm when loaded), counted in layers of the chosen height
    skin_top, skin_bot = (1.2, 1.0) if load.get("bearing") else (0.8, 0.6)
    top = max(int(_f(pre.get("top")) or 0), math.ceil(skin_top / layer - 1e-9))
    bot = max(int(_f(pre.get("bottom")) or 0), math.ceil(skin_bot / layer - 1e-9))
    for k, n, skin, name in (("top", top, skin_top, "Top layers"), ("bottom", bot, skin_bot, "Bottom layers")):
        was = int(_f(pre.get(k)) or 0)
        add(k, name, str(n), f"at least {skin:g} mm of solid skin at {layer:g} mm layers" + (" (load-bearing)" if load.get("bearing") else ""),
            "computed", n != was)
        if n != was:
            want[k] = n

    # infill
    inf_pre = _f(pre.get("infill"))
    if load.get("bearing"):
        want["infill"], want["pattern"] = 40, "gyroid"
        add("infill", "Infill", "40% gyroid", "load-bearing: denser infill backs the walls, and gyroid is about as strong in "
            "every direction", "heuristic", True)
    elif mat.get("flexible"):
        want["infill"], want["pattern"] = 20, "gyroid"
        add("infill", "Infill", "20% gyroid", f"{mat.get('key')} is flexible: gyroid compresses evenly instead of buckling",
            "heuristic", True)
    else:
        add("infill", "Infill", f"{inf_pre:g}% {_s(pre.get('pattern'))}".strip() if inf_pre is not None else "the preset's",
            "no stated load: the preset's infill holds the shape at the least material", "heuristic", False)

    # supports: only where overhangs need them
    steep, ceil_, sup = float(i.get("steep_mm2") or 0), float(i.get("ceiling_mm2") or 0), float(i.get("support_mm3") or 0)
    if steep > 20:
        mean_h = sup / max(steep + ceil_, 1e-6)
        style = "tree" if (mean_h > 8 or slope >= 0.35) else "normal"
        want["support"], want["support_style"] = True, style
        add("support", "Supports", f"on, {style}", f"{steep:.0f} mm² of overhang steeper than 45° in this orientation "
            f"(computed); " + ("tree supports reach it from the plate with less material and come off cleanly"
                               if style == "tree" else "the overhang is low and broad, so normal supports hold it flat"),
            "computed", True)
    else:
        want["support"] = False
        add("support", "Supports", "off", (f"only {steep:.0f} mm² steeper than 45° (computed)" if steep else
                                          "no overhang steeper than 45° in this orientation (computed)")
            + ("; flat ceilings bridge" if ceil_ > 0 else ""), "computed", _f(pre.get("support")) not in (0, None))

    # brim: tall and narrow, a small first layer, or a material that warps
    narrow = fp[0] if fp else 0
    ratio = H / narrow if narrow > 0 else 0
    contact = float(i.get("contact_mm2") or 0)
    reasons, width = [], 5
    if ratio > 2.5:
        reasons.append(f"tall for its base (height {ratio:.1f}× the narrowest side, computed)")
    if 0 < contact < 100:
        reasons.append(f"little on the plate ({contact:.0f} mm², computed)")
    if mat.get("warp") == "high" and (fp[-1] if fp else 0) > 60:
        reasons.append(f"{mat.get('key')} warps and the part is {fp[-1]:.0f} mm long")
        width = 8
    if reasons:
        want["brim"], want["brim_width"] = True, width
        add("brim", "Brim", f"{width} mm outside", "; ".join(reasons), "heuristic", True)
    else:
        add("brim", "Brim", _s(pre.get("brim")) or "the preset's", f"stable on the plate ({contact:.0f} mm² contact, "
            f"height {ratio:.1f}× the narrowest side, computed): the preset's brim setting stays", "heuristic", False)

    # seam
    if cos.get("is"):
        want["seam"] = "back"
        add("seam", "Seam", "back", f"a part people look at ({cos.get('why')}): the seam goes to the back", "heuristic", True)
    else:
        add("seam", "Seam", _s(pre.get("seam")) or "the preset's", "a functional part: the preset's seam stays", "heuristic", False)
    return {"want": want, "decisions": out}


# ---- settings -> the slicer's keys ------------------------------------------------------------------------------

def overrides(kind: str, want: dict, data: dict) -> tuple[dict, list]:
    """The keys to write over the process preset `data` and what was left out and why.

    Only keys the preset already has are written, in the same shape (string, list), and enum values only when the
    preset's own value shows the slicer speaks that vocabulary."""
    fam = family(kind)
    keys, enums, words = VOCAB[fam], ENUMS[fam], WORDS[fam]
    out, skipped = {}, []

    def put(setting, value):
        key = keys[setting]
        if key not in data:
            skipped.append({"setting": setting, "key": key, "why": "the preset has no such key"})
            return
        if setting in enums:
            if _s(data[key]) not in enums[setting] or value not in enums[setting]:
                skipped.append({"setting": setting, "key": key, "why": f"“{value}” is not a value this slicer's preset uses"})
                return
        out[key] = [value] if isinstance(data[key], list) else value

    for setting, v in want.items():
        if setting == "layer":
            put("layer", f"{v:g}")
        elif setting in ("walls", "top", "bottom"):
            put(setting, str(int(v)))
        elif setting == "infill":
            put("infill", f"{int(round(v))}%")
        elif setting == "pattern":
            put("pattern", v)
        elif setting == "support":
            put("support", "1" if v else "0")
            if v and fam == "prusa" and "support_material_auto" in data:
                out["support_material_auto"] = "1"
        elif setting == "support_style":
            put("support_style", words[v])
        elif setting == "brim":
            if fam == "bbl" or "brim_type" in data:
                put("brim", words["outer"])
        elif setting == "brim_width":
            put("brim_width", f"{v:g}")
        elif setting == "seam":
            put("seam", words[v])
    # nothing that equals the preset already
    out = {k: v for k, v in out.items() if _s(v) != _s(data.get(k))}
    return out, skipped


def preset_summary(kind: str, data: dict) -> dict:
    k = VOCAB[family(kind)]
    return {"walls": data.get(k["walls"]), "top": data.get(k["top"]), "bottom": data.get(k["bottom"]),
            "infill": data.get(k["infill"]), "pattern": _s(data.get(k["pattern"])), "support": data.get(k["support"]),
            "brim": _s(data.get(k["brim"])) or (f"{_s(data.get(k['brim_width']))} mm" if data.get(k["brim_width"]) else ""),
            "brim_width": data.get(k["brim_width"]), "seam": _s(data.get(k["seam"]))}


# ---- the project 3MF ---------------------------------------------------------------------------------------------

def read_project_settings(path: Path) -> dict:
    """The process, filament and printer settings a project 3MF carries (Bambu/Orca JSON or PrusaSlicer INI)."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "Metadata/project_settings.config" in names:
            return json.loads(z.read("Metadata/project_settings.config"))
        for n in ("Metadata/Slic3r_PE.config", "Metadata/PrusaSlicer.config", "Metadata/SuperSlicer.config",
                  "Metadata/QIDISlicer.config"):
            if n in names:
                out = {}
                for ln in z.read(n).decode("utf-8", "replace").splitlines():
                    m = re.match(r"^;\s*([\w-]+)\s*=\s*(.*)$", ln)
                    if m:
                        out[m.group(1)] = m.group(2).strip()
                return out
    return {}


def mark_changed(path: Path, keys: list) -> bool:
    """List the overridden keys as edits of the process preset (different_settings_to_system[0]) in a Bambu/Orca
    project, as the program does when you change a setting yourself. Returns whether the file changed."""
    if not keys:
        return False
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(path) as z:
        if "Metadata/project_settings.config" not in z.namelist():
            return False
        cfg = json.loads(z.read("Metadata/project_settings.config"))
        diff = list(cfg.get("different_settings_to_system") or [])
        if not diff:
            return False
        have = [x for x in str(diff[0]).split(";") if x]
        diff[0] = ";".join(sorted(set(have) | set(keys)))
        cfg["different_settings_to_system"] = diff
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as w:
            for info in z.infolist():
                body = z.read(info.filename)
                if info.filename == "Metadata/project_settings.config":
                    body = json.dumps(cfg, indent=4).encode()
                w.writestr(info, body)
    tmp.replace(path)
    return True


def verify(path: Path, changes: dict) -> dict:
    """Each override against what the project 3MF says: {key: {"want", "found", "ok"}}."""
    got = read_project_settings(path)
    out = {}
    for k, v in changes.items():
        found = got.get(k)
        out[k] = {"want": _s(v), "found": _s(found) if found is not None else None, "ok": found is not None and _s(found) == _s(v)}
    return out


def app_bundle(app: str) -> str:
    """What to open the project with: on macOS the .app bundle the program sits in, elsewhere the program."""
    if sys.platform == "darwin":
        for parent in Path(app).parents:
            if parent.suffix == ".app":
                return str(parent)
    return app


def launch(resolved: dict, path: Path, new_instance: bool = False) -> dict:
    """Open the project in the slicer's own app (form/cad_bridges.open_file; FORM_FAKE_LAUNCH records instead).
    new_instance: in a window of its own (macOS open -n), for a slicer that holds one project per window."""
    from .cad_bridges import open_file
    try:
        return open_file(str(path), app_bundle(resolved.get("app") or ""), new_instance=new_instance)
    except (RuntimeError, OSError) as e:
        raise _err(f"{resolved.get('label') or 'The slicer'} could not be opened: {e}",
                   f"Open {path.name} from the slicer's File menu; it is at {path}.")


# ---- inputs from a design ---------------------------------------------------------------------------------------

def geometry(stl: Path) -> dict:
    """Computed on the STL as it lies on the plate: size, plate contact, overhangs, support volume, sloped share."""
    import numpy as np
    from . import analysis, meshio
    P, T = meshio.read_stl(stl)
    row = analysis.orientation_row(P, T, "as_modelled")
    n, area, _c = analysis.tri_normals(P, T)
    nz = np.abs(n[:, 2])
    sloped = (nz > 0.17) & (nz < 0.985)                    # neither a wall (within ~10°) nor flat (within ~10°)
    total = float(area.sum()) or 1.0
    row["sloped_share"] = round(float(area[sloped].sum()) / total, 4)
    return row


def _thin_wall(checks: dict | None):
    for c in (checks or {}).get("checks", []):
        if c.get("id") == "wall":
            m = re.search(r"(\d+(?:\.\d+)?)\s*mm", str(c.get("value") or ""))
            if m:
                return float(m.group(1))
    return None


def _load(st, p, checks) -> dict:
    for c in (checks or {}).get("checks", []):
        if c.get("evidence") == "model" and LOAD_CHECKS.search(str(c.get("label") or "")):
            return {"bearing": True, "why": f"its “{c['label']}” check models a load"}
    text = " ".join([p.get("name") or "", (p.get("brief") or {}).get("text") or "", st.rid(p)])
    m = LOAD_WORDS.search(text.replace("_", " "))
    if m:
        return {"bearing": True, "why": f"“{m.group(0)}” in the design's name or brief"}
    return {"bearing": False, "why": ""}


def _cosmetic(st, p) -> dict:
    text = " ".join([p.get("name") or "", (p.get("brief") or {}).get("text") or "", st.rid(p)]).replace("_", " ")
    m = COSMETIC_WORDS.search(text)
    return {"is": bool(m), "why": f"“{m.group(0)}” in the design's name or brief" if m else ""}


def _printer(st, p, printer: str | None) -> dict:
    """The printer choice {kind, machine, filament, filament_source} for this design (or the printer id given)."""
    from . import filaments, printers, slicer
    mat = filaments.stated(p)
    if printer:
        kind, _, machine = printer.partition(":")
        if kind not in slicer.SLICERS or not machine:
            raise _err(f"Unknown printer “{printer}”.", "Use an id from `form printers` (kind:machine).", 404)
        c = printers.complete(st.cfg, {"kind": kind, "machine": machine})
        fil, src = c["filament"], f"{slicer.label(kind)}'s default filament for this printer"
        if mat:
            pick = filaments.pick_filament(st.cfg, kind, machine, mat)
            if pick:
                fil, src = pick, f"the {filaments.MATERIALS[mat]['label']} set for this design"
        return {"kind": kind, "machine": machine, "filament": fil, "filament_source": src, "default_process": c["process"]}
    s = st.slicer_info(p=p)
    if not s.get("available"):
        raise _err(s.get("reason") or "No slicer is set up.", "Install a slicer and choose a printer (Settings › Printer).")
    pr = s["presets"]
    src = (s.get("source") or {}).get("filament") or "the slicer's selection"
    if (s.get("material") or {}).get("changed"):
        src = f"the {filaments.MATERIALS[s['material']['material']]['label']} set for this design" \
            if s["material"].get("material") in filaments.MATERIALS else src
    return {"kind": s.get("kind", "bambu"), "machine": pr["machine"]["name"], "filament": pr["filament"]["name"],
            "filament_source": src, "default_process": pr["process"]["name"]}


def base_process(st, kind: str, machine: str, layer_target: float, load: bool, nozzle: float, fallback: str) -> tuple:
    """(process preset name, its layer height, every layer height on offer): one of the printer's own system process
    presets, at the layer height nearest the target, the plain one (Standard, Optimal, Quality...) or for a loaded part
    a Strength / Structural one when there is one at that height."""
    from . import printers
    try:
        opts = printers.options(st.cfg, kind, machine)["processes"]
    except Exception:
        opts = []
    rows = [(o["name"], layer_of(o["name"])) for o in opts if o.get("source") != "user" and o.get("checked", True)]
    rows = [(n, lh) for n, lh in rows if lh and not AVOID_PRESET.search(n) and 0.2 * nozzle <= lh <= 0.8 * nozzle]
    if not rows:
        return fallback, layer_of(fallback), []
    heights = sorted({lh for _, lh in rows})
    best_h = min(heights, key=lambda h: (abs(h - layer_target), -h))
    at = [n for n, lh in rows if lh == best_h]
    pick = None
    if load:
        pick = next((n for n in at if STRONG_PRESET.search(n)), None)
    pick = pick or next((n for n in at if PLAIN_PRESET.search(n) and not STRONG_PRESET.search(n)), None) or sorted(at)[0]
    return pick, best_h, heights


def _orientation(st, p) -> dict:
    """The orientation to print in: the orientation finder's first choice that fits (computed ranking)."""
    from . import analysis
    r = analysis.orientations(st, p)
    cands = [c for c in r["candidates"] if c.get("fits")] or r["candidates"]
    best = cands[0]
    cur = next((c for c in r["candidates"] if c.get("current")), None)
    same = bool(best.get("current"))
    why = (f"ranked first of {len(r['candidates'])} by the orientation finder (support, overhang, plate contact, height, "
           f"weakest layer; score {best['score']:.2f})")
    if not same and cur:
        why += f"; the design is set to “{cur['label']}” (score {cur['score']:.2f}), which is left as it is"
    return {"id": best["id"], "label": best.get("label") or analysis.orientation_label(best["id"]), "why": why,
            "evidence": "computed", "changed": not same,
            "row": {k: best[k] for k in ("height_mm", "footprint_mm", "contact_mm2", "steep_mm2", "ceiling_mm2", "support_mm3")}}


def plan(st, p, printer: str | None = None, *, _orient: dict | None = None, _stl: Path | None = None) -> dict:
    """Decide everything without slicing: printer, orientation, inputs, decisions, the process preset, the overrides."""
    from . import capabilities, filaments, printers, purpose
    if not capabilities.has(st.cfg, "print"):
        raise _err("3D printing is off.", "Turn it on in Settings (Set up for › 3D printing).")
    if purpose.is_model(p):
        raise _err("This design is a 3D model, not made for 3D printing.",
                   "Make it printable first (Prove › Make it for 3D printing), then open it in your slicer.")
    keys = st.keys(p)
    ex = st.read(p, "exports", keys["exports"])
    if not ex or "stl" not in (ex.get("files") or {}):
        raise _err("There is no current exported model.", "Run the pipeline first.")
    pr = _printer(st, p, printer)
    multi = getattr(st.recipe(p), "solids", 1) > 1
    checks = st.read(p, "checks", keys["checks"])
    load, cos = _load(st, p, checks), _cosmetic(st, p)
    mat_key = filaments.stated(p) or filaments.material_of_preset(pr["filament"])
    mat = dict(filaments.info(mat_key), key=mat_key) if mat_key else None
    orient = _orient if _orient is not None else (None if multi else _orientation(st, p))
    stl = _stl or (st.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"])
    geo = geometry(stl)
    if orient and orient.get("row"):                       # the same numbers as the orientation finder and the checks
        geo.update(orient["row"])
    # the printer's nozzle and layer limits, from its preset
    base0 = printers.resolve(st.cfg, {"kind": pr["kind"], "machine": pr["machine"], "process": pr["default_process"],
                                      "filament": pr["filament"]})
    if not base0.get("available"):
        raise _err(base0.get("reason") or "That printer cannot slice here.", "Choose another printer or filament.")
    m = base0["presets"]["machine"]["data"]
    nozzle = float(base0.get("nozzle_mm") or 0.4)
    inputs = {"nozzle_mm": nozzle, "min_layer_mm": _f(m.get("min_layer_height")), "max_layer_mm": _f(m.get("max_layer_height")),
              "height_mm": geo["height_mm"], "footprint_mm": geo["footprint_mm"], "contact_mm2": geo["contact_mm2"],
              "steep_mm2": geo["steep_mm2"], "ceiling_mm2": geo["ceiling_mm2"], "support_mm3": geo["support_mm3"],
              "sloped_share": geo["sloped_share"], "thin_wall_mm": _thin_wall(checks), "load": load, "cosmetic": cos,
              "material": mat and {"key": mat["key"], "warp": mat.get("warp"), "flexible": mat.get("flexible", False)},
              "orientation": orient and {k: v for k, v in orient.items() if k != "row"}}
    first = choose(dict(inputs, layer_options=[]))          # the layer height it would like, before the presets
    proc, proc_h, heights = base_process(st, pr["kind"], pr["machine"], first["want"]["layer"], load["bearing"], nozzle,
                                         pr["default_process"])
    choice = {"kind": pr["kind"], "machine": pr["machine"], "process": proc, "filament": pr["filament"]}
    res = printers.resolve(st.cfg, choice)
    if not res.get("available"):
        raise _err(res.get("reason") or "That printer cannot slice here.", "Choose another printer or filament.")
    data = res["presets"]["process"]["data"]
    inputs["layer_options"] = heights
    inputs["preset"] = preset_summary(pr["kind"], data)
    d = choose(inputs)
    changes, skipped = overrides(pr["kind"], d["want"], data)
    d["decisions"].append({"id": "filament", "label": "Filament", "value": pr["filament"],
                           "why": f"set by {pr['filament_source']}" + (f"; read as {mat['label']}" if mat else ""),
                           "evidence": "heuristic", "changed": False})          # a preset matched by its name
    d["decisions"].append({"id": "profile", "label": "Speed profile", "value": proc,
                           "why": f"{res.get('label') or pr['kind']}'s own process preset for this printer at {proc_h:g} mm"
                                  + (", its strength variant for a loaded part" if STRONG_PRESET.search(proc) else "")
                                  + "; its speeds, temperatures and cooling stay as the slicer ships them",
                           "evidence": "heuristic", "changed": proc != pr["default_process"]})
    for x in d["decisions"]:
        if x["id"] == "layer" and abs(proc_h - d["want"]["layer"]) > 1e-6:
            x["why"] += f" (over the preset's {proc_h:g} mm)"
    return {"printer": pr, "choice": choice, "resolved": res, "inputs": inputs, "decisions": d["decisions"],
            "want": d["want"], "changes": changes, "skipped": skipped, "multi": multi, "orientation": orient,
            "keys": keys, "exports": ex}


def _with_changes(res: dict, changes: dict) -> dict:
    import hashlib
    proc = res["presets"]["process"]
    data = dict(proc["data"], **changes)
    sha = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    return {**res, "presets": {**res["presets"], "process": {**proc, "data": data, "sha": sha,
                                                             "name": proc["name"] + " (Form Studio)"}}}


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "printer"


def _plates(st, p, ex_dir: Path, ex: dict, orient: dict | None, keys: dict, out: Path) -> list:
    """The STL of each plate: one oriented part, or the plates the pipeline sliced for a design of several parts."""
    from .studio import STL_TOL
    if orient is not None:
        if not orient["changed"]:
            return [ex_dir / ex["files"]["stl"]["name"]]
        tmp = out / "oriented"
        shutil.rmtree(tmp, ignore_errors=True)
        r = st.rev(p)
        res = st._k("export", key=keys["geometry"], recipe_id=st.rid(p), values=r["values"], out_dir=str(tmp),
                    name=f"{p['id']}_r{r['n']:02d}", orientation=orient["id"], tol=STL_TOL, p=p)
        return [Path(res["stl"])]
    sl = st.read(p, "slice", keys["slice"]) if keys.get("slice") else None
    if sl and sl.get("plates"):
        d = st.apath(p, "slice", keys["slice"])
        return [d / x["stl"] for x in sl["plates"]]
    return [ex_dir / ex["files"]["stl"]["name"]]


def _part_rows(st, p, multi: bool, single: Path, work: Path) -> list:
    """The printed parts as they lie: each part of a design of several (form/plates.py), or the one oriented STL."""
    from . import materials as looks
    from . import plates as plates_mod
    if multi:
        return plates_mod.project_parts(st, p, work / "parts")
    pts = plates_mod.read_triangles(single).reshape(-1, 3)
    size = (pts.max(axis=0) - pts.min(axis=0)).tolist() if len(pts) else [0, 0, 0]
    look = looks.resolved(p, "")
    return [{"id": p["id"], "label": p["name"], "stl": str(single), "size": size,
             "material": look.get("material") or "", "color": look.get("color") or ""}]


def _layout(st, p, res: dict, parts: list, copies: int) -> dict:
    """The plate plan on the bed of the printer the slice uses, with the brim the decisions chose (form/plates.py)."""
    from . import plates as plates_mod
    pe = st.printer_env(p)
    bed = [float(x) for x in (res.get("envelope_mm") or pe["envelope"])]
    machine = ((res.get("presets") or {}).get("machine") or {}).get("data") or {}
    room, why = plates_mod.clearance(res)
    pl = plates_mod.plan(plates_mod.copies_of(parts, copies), bed, plates_mod.spacing(st.cfg), pe["margin"], room,
                         plates_mod.bed_zones(machine))
    if why:
        pl["clearance_source"] = why
    return pl


def _plate_names(plan: dict) -> dict:
    return {x["n"]: [q["label"] for q in x["parts"]] for x in plan["plates"]}


def run(st, p, printer: str | None = None, open_app: bool = True, copies: int = 1) -> dict:
    """Choose, slice for real, write and check the project 3MF, and open it in the slicer. See the module docstring.

    Parts that do not fit one plate (a design of several parts, or `copies` of it) are packed onto as many plates as
    it takes on the chosen printer's bed (form/plates.py). Bambu Studio, OrcaSlicer and the Orca forks get one
    project with every plate, sliced plate by plate by the program itself; PrusaSlicer and its forks get one project
    per plate (each opened in its own window) and a 3MF with every plate for PrusaSlicer 2.9's several beds."""
    from . import plate3mf, slicer
    from . import plates as plates_mod
    from .studio import H, _slicer_tag
    keys = st.keys(p)
    ex = st.read(p, "exports", keys["exports"])
    if not ex:
        raise _err("There is no current exported model.", "Run the pipeline first.")
    multi = getattr(st.recipe(p), "solids", 1) > 1
    copies = max(1, int(copies or 1))
    from . import capabilities, purpose
    if not capabilities.has(st.cfg, "print"):
        raise _err("3D printing is off.", "Turn it on in Settings (Set up for › 3D printing).")
    if purpose.is_model(p):
        raise _err("This design is a 3D model, not made for 3D printing.",
                   "Make it printable first (Prove › Make it for 3D printing), then open it in your slicer.")
    orient = None if multi else _orientation(st, p)
    side = st.dir(p["id"]) / "artifacts" / "side"
    work = side / ("slicer-open-" + H("slicer-open-geo", VERSION, keys["exports"], keys.get("checks"), orient and orient["id"]))
    work.mkdir(parents=True, exist_ok=True)
    ex_dir = st.apath(p, "exports", keys["exports"])
    whole = _plates(st, p, ex_dir, ex, orient, keys, work)[0] if not multi else ex_dir / ex["files"]["stl"]["name"]
    parts = _part_rows(st, p, multi, whole, work)
    pl = plan(st, p, printer, _orient=orient, _stl=Path(parts[0]["stl"]) if multi else whole)
    res = _with_changes(pl["resolved"], pl["changes"])
    layout = _layout(st, p, res, parts, copies)
    bed = layout["bed_mm"]
    one_plate = copies == 1 and not layout["too_big"] and (
        not multi or not plates_mod.needed(parts, ex.get("print_bbox") or [0, 0, 0], bed, layout["margin_mm"]))
    presets = {k: v.get("sha") for k, v in res["presets"].items()}
    label = res.get("label") or slicer.label(pl["choice"]["kind"])
    name = f"{p['id']}_r{p['head']:02d}_{_safe(pl['choice']['machine'])}" + (f"_x{copies}" if copies > 1 else "")
    together = not one_plate and slicer.takes_plates(res)
    lay_key = None if one_plate else [[(q["id"], q["x"], q["y"], q["rotated"]) for q in x["parts"]] for x in layout["plates"]]
    key = H("slicer-open", VERSION, keys["exports"], whole.name, [x["id"] for x in parts], orient and orient["id"], presets,
            lay_key, together, *_slicer_tag(res))
    out = side / ("slicer-open-" + key)
    stl_of = {}
    for x in parts:
        stl_of[x["id"]] = Path(x["stl"])
    for x in layout["plates"]:
        for q in x["parts"]:
            stl_of.setdefault(q["id"], stl_of.get(str(q["id"]).split("#")[0]))
    if one_plate:
        stls = [whole]
    elif together:
        stls = []
    else:                                               # one model per plate, the parts at their packed places
        stls = []
        for x in layout["plates"]:
            f = work / f"plate_{x['n']}_{H('plate', lay_key, x['n'])}.stl"
            if not f.is_file():
                plates_mod.write_plate_stl(f, x["parts"], stl_of)
            stls.append(f)
    if not one_plate and not layout["plates"]:
        b = layout["too_big"][0]
        raise _err(f"{b['label']} is {' × '.join(f'{v:g}' for v in b['size'])} mm: larger than the plate of "
                   f"{pl['choice']['machine']} ({bed[0]:g} × {bed[1]:g} mm) however it lies.", " ".join(b["suggestions"]), 422)
    rows, extra = [], {}
    if together:
        rows, extra = _slice_together(st, p, res, pl, layout, parts, out, name, label)
    else:
        for n, stl in enumerate(stls, 1):
            pdir = out / f"plate_{n}"
            meta_f = pdir / "meta.json"
            if meta_f.is_file():
                row = json.loads(meta_f.read_text(encoding="utf-8"))
            else:
                tmp = pdir.with_name(pdir.name + ".tmp")
                shutil.rmtree(tmp, ignore_errors=True)
                info = slicer.slice_stl(res, stl, tmp, timeout=st.cfg["slicer"]["timeout_s"])
                proj = info.get("threemf") or info.get("project_3mf")
                if not proj or not (tmp / proj).is_file():
                    raise _err(f"{label} sliced the part but wrote no project file.",
                               "Update the slicer, or open the G-code instead.", 502)
                final = f"{name}" + (f"_plate{n}" if len(stls) > 1 else "") + ".3mf"
                shutil.move(str(tmp / proj), tmp / final)
                marked = mark_changed(tmp / final, list(pl["changes"])) if family(pl["choice"]["kind"]) == "bbl" else False
                row = {"n": n, "project": final, "marked_as_edits": marked,
                       **{k: info.get(k) for k in ("time_s", "filament_g", "filament_mm", "layers", "max_z_mm", "support_used",
                                                   "slicer_version", "warnings")}}
                (tmp / "meta.json").write_text(json.dumps(row, indent=1), encoding="utf-8")
                shutil.rmtree(pdir, ignore_errors=True)
                tmp.rename(pdir)
            row["path"] = str(pdir / row["project"])
            row["verified"] = verify(Path(row["path"]), pl["changes"])
            if not one_plate:
                row["parts"] = _plate_names(layout).get(n, [])
            rows.append(row)
        if not one_plate and family(pl["choice"]["kind"]) != "bbl":
            # every plate in one 3MF too, for PrusaSlicer 2.9's several beds (no settings in it: those are the projects')
            meshes = {x["id"]: plate3mf.mesh_of(plates_mod.read_triangles(Path(x["stl"]))) for x in parts}
            files = plate3mf.write_all(out, f"{name}_all_plates", layout["plates"], meshes, "prusa", bed,
                                       f"{p['name']} r{p['head']:02d}")
            extra["all_plates_files"] = [str(f) for f in files]

    def total(k):
        vals = [r.get(k) for r in rows]
        return None if any(v is None for v in vals) else round(sum(vals), 3)
    ok = all(v["ok"] for r in rows for v in (r.get("verified") or {}).values())
    projects = list(dict.fromkeys(r["path"] for r in rows))
    result = {
        "project": p["id"], "rev": p["head"], "slicer": label, "kind": pl["choice"]["kind"], "printer": pl["choice"]["machine"],
        "process": pl["choice"]["process"], "filament": pl["choice"]["filament"],
        "decisions": pl["decisions"], "overrides": pl["changes"], "not_written": pl["skipped"],
        "inputs": {k: v for k, v in pl["inputs"].items() if k not in ("preset",)},
        "plates": rows, "plate_count": len(rows), "time_s": total("time_s"), "filament_g": total("filament_g"),
        "file": projects[0], "files": projects, "settings_in_file": ok, "copies": copies,
        "layout": {k: layout[k] for k in ("count", "bed_mm", "spacing_mm", "margin_mm", "clearance_mm", "evidence", "note")},
        "evidence": "simulated",
        "note": ("The settings are Form Studio's choices for this part: each says whether it is computed from the geometry or "
                 "a heuristic. Time and grams are the slicer's simulation of its own slice. Nothing was printed or sent anywhere."),
        **extra,
    }
    if layout["too_big"]:
        result["too_big"] = layout["too_big"]
        result["warning"] = ("Not in the project, larger than the plate however it lies: "
                             + "; ".join(f"{b['label']} {' × '.join(f'{v:g}' for v in b['size'])} mm" for b in layout["too_big"])
                             + ". " + " ".join(layout["too_big"][0]["suggestions"]))
    if not ok:
        result["warning"] = (result.get("warning", "") + " Some settings were not found in the project file: "
                             "see plates[].verified.").strip()
    if len(projects) > 1:
        result["other_plates"] = (f"{label} takes one plate per project: each plate is its own project, and each opens "
                                  "in its own window." + (" Every plate is also in one 3MF for PrusaSlicer 2.9 or later: "
                                                          + ", ".join(extra["all_plates_files"]) if extra.get("all_plates_files") else ""))
    if open_app:
        opened = [launch(res, Path(f), new_instance=len(projects) > 1) for f in projects]
        result["opened"] = opened[0] if len(opened) == 1 else opened
    return result


def _slice_together(st, p, res: dict, pl: dict, layout: dict, parts: list, out: Path, name: str,
                    label: str) -> tuple[list, dict]:
    """Every plate in one project: the plates 3MF (form/plate3mf.py, the program's plate entries) sliced by the
    program, which writes each plate's G-code into the project it saves. Rows from its own slice_info."""
    from . import plate3mf, slicer
    from . import plates as plates_mod
    meta_f = out / "meta.json"
    if meta_f.is_file():
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
    else:
        tmp = out.with_name(out.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        meshes = {x["id"]: plate3mf.mesh_of(plates_mod.read_triangles(Path(x["stl"]))) for x in parts}
        inp = tmp / "plates.in.3mf"
        plate3mf.write(inp, layout["plates"], meshes, "bbl", layout["bed_mm"], f"{p['name']} r{p['head']:02d}")
        info = slicer.slice_plates(res, inp, tmp / "sliced", timeout=st.cfg["slicer"]["timeout_s"] * max(1, layout["count"]))
        proj = tmp / "sliced" / (info.get("threemf") or "plate.3mf")
        if not proj.is_file():
            raise _err(f"{label} sliced the plates but wrote no project file.", "Update the slicer, or open the G-code instead.", 502)
        final = f"{name}_{layout['count']}plates.3mf"
        shutil.move(str(proj), tmp / final)
        marked = mark_changed(tmp / final, list(pl["changes"]))
        read = plate3mf.read(tmp / final)
        meta = {"project": final, "marked_as_edits": marked, "plates": info.get("plates") or [],
                "read": read["plates"], "slicer_version": info.get("slicer_version"), "warnings": info.get("warnings")}
        shutil.rmtree(tmp / "sliced", ignore_errors=True)
        (tmp / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        shutil.rmtree(out, ignore_errors=True)
        tmp.rename(out)
    path = out / meta["project"]
    verified = verify(path, pl["changes"])
    names = _plate_names(layout)
    on = {x["n"]: x["objects"] for x in meta["read"]}            # the plates the saved project holds (its own record)
    rows = []
    for r in meta["plates"]:
        rows.append({"n": r["n"], "project": meta["project"], "path": str(path), "time_s": r.get("time_s"),
                     "filament_g": r.get("filament_g"), "support_used": r.get("support_used"), "outside": r.get("outside"),
                     "parts": on.get(r["n"]) or names.get(r["n"], []),       # what the project says is on it
                     "slicer_version": meta.get("slicer_version"), "verified": verified,
                     "marked_as_edits": meta.get("marked_as_edits")})
    extra = {"plates_in_project": len(meta["read"]), "plates_sliced": len(meta["plates"])}
    if len(meta["plates"]) != layout["count"] or len(meta["read"]) != layout["count"]:
        extra["plates_warning"] = (f"Form Studio laid out {layout['count']} plates; {label} read {len(meta['read'])} and "
                                   f"sliced {len(meta['plates'])}.")
    elif any(sorted(on.get(n, [])) != sorted(v) for n, v in names.items()):
        extra["plates_warning"] = f"{label} put the parts on its plates differently from Form Studio's plan."
    if any(r.get("outside") for r in rows):
        extra["plates_warning"] = (extra.get("plates_warning", "") + f" {label} says a part is outside its plate.").strip()
    return rows, extra


def explain(result: dict) -> str:
    """The decisions as plain lines (CLI --explain)."""
    lines = [f"{result['slicer']} · {result['printer']} · {result['filament']}"]
    for d in result["decisions"]:
        lines.append(f"  {d['label']}: {d['value']}  [{d['evidence']}]  {d['why']}")
    if result.get("time_s") is not None:
        lines.append(f"  Slice (simulated): {result['time_s'] / 60:.0f} min, {result.get('filament_g') or 0:.1f} g")
    return "\n".join(lines)
