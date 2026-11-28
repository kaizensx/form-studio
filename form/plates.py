"""Several plates: when a design's printed parts do not fit one plate of the printer, lay them out on as many as needed.

Each part is laid on the plate on its own, in its own print orientation:

    project["parts"][<part id>]["orientation"]   one of the named orientations, a "down:x,y,z" id, or "auto"
                                                 (the best-ranked way for that part to lie, form/analysis.py)
    otherwise                                    the design's print orientation, applied to the part by itself

The parts' footprints (bounding boxes as printed) are packed with form/packing.py, plate after plate, largest first,
with the gap between parts ([printer].plate_spacing_mm, default 6 mm) and the keep-out margin at the bed edge
([printer].plate_margin_mm). Parts in different materials never share a plate: one filament per plate.

A design whose parts fit as modelled on one plate, in one material, is sliced as one plate, exactly as before.
A part larger than the plate in every way it can lie cannot be placed: the plan says which, and the
"Fits the build volume" check fails on it.

The layout is computed by Form Studio from bounding boxes. Each plate is handed to the slicer as one model (the parts
at their packed places) and sliced on its own; the slicer re-centres it on the bed. Times and filament are the
slicer's estimates, per plate and summed.
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import packing

PLATES_VERSION = 2          # 2: a brim's room, excluded zones, each part's place as a matrix, too-big suggestions
DEFAULT_SPACING_MM = packing.DEFAULT_SPACING_MM


def spacing(cfg: dict) -> float:
    try:
        return max(0.0, float((cfg.get("printer") or {}).get("plate_spacing_mm", DEFAULT_SPACING_MM)))
    except (TypeError, ValueError):
        return DEFAULT_SPACING_MM


def part_orientations(p: dict) -> dict:
    """{part id: orientation} the person set for single parts (project["parts"][id]["orientation"])."""
    own = p.get("parts") if isinstance(p.get("parts"), dict) else {}
    return {k: str(v["orientation"]) for k, v in sorted(own.items())
            if isinstance(v, dict) and isinstance(v.get("orientation"), str) and v["orientation"]}


def fits_alone(w: float, h: float, z: float, bed: list, margin: float, exclude=(), gap: float = 0.0) -> bool:
    """Whether a w × h × z footprint fits the bed by itself, turned about Z if need be (and `gap` clear of excluded
    zones)."""
    aw, ah = bed[0] - 2 * margin, bed[1] - 2 * margin
    flat = (w <= aw + 1e-6 and h <= ah + 1e-6) or (h <= aw + 1e-6 and w <= ah + 1e-6)
    if flat and exclude:
        flat = bool(packing.pack([{"id": "x", "w": w, "h": h}], bed[:2], gap, margin, True, exclude)["placed"])
    return flat and (len(bed) < 3 or z <= bed[2] + 1e-6)


def too_big_entry(x: dict, bed: list, margin: float, exclude=(), gap: float = 0.0) -> dict:
    """What to say about a part that does not fit the plate however it lies: its size against the bed, and what would
    make it fit (lying on another side, scaling, splitting, a larger printer). All arithmetic on bounding boxes."""
    size = [float(v) for v in x["size"]]
    aw, ah, ahz = bed[0] - 2 * margin, bed[1] - 2 * margin, (bed[2] if len(bed) > 2 else float("inf"))
    sides = []
    for k in range(3):                       # the three ways a box can stand: each dimension upright once
        up = size[k]
        flat = [size[i] for i in range(3) if i != k]
        row = {"footprint_mm": [round(flat[0], 1), round(flat[1], 1)], "height_mm": round(up, 1)}
        if k != 2 and row not in sides and fits_alone(flat[0], flat[1], up, bed, margin, exclude, gap):
            sides.append(row)
    scale = max(min(aw / max(size[0], 1e-9), ah / max(size[1], 1e-9)), min(aw / max(size[1], 1e-9), ah / max(size[0], 1e-9)))
    scale = min(scale, ahz / max(size[2], 1e-9))
    tips = []
    if sides:
        s = sides[0]
        tips.append(f"Lay it on another side ({s['footprint_mm'][0]:g} × {s['footprint_mm'][1]:g} mm on the plate, "
                    f"{s['height_mm']:g} mm tall): set its print orientation in Prove.")
    tips.append(f"Scale it to {int(scale * 100)} % or less.")
    tips.append("Split it into parts that each fit (and join them after printing).")
    tips.append("Choose a printer with a larger bed.")
    return {"id": x["id"], "label": x.get("label") or x["id"], "size": [round(v, 1) for v in size],
            "bed_mm": [round(float(v), 1) for v in bed[:3]], "usable_mm": [round(aw, 1), round(ah, 1), round(ahz, 1)],
            "fits_on_side": sides, "max_scale": round(scale, 3), "suggestions": tips}


def plan(parts: list, bed: list, spacing_mm: float = DEFAULT_SPACING_MM, margin: float = 0.0, clearance: float = 0.0,
         exclude=()) -> dict:
    """Pack parts ([{"id", "label", "size": [w, d, h], "material"?, "color"?, "matrix"?}]) onto as few plates as this
    packer can: largest first, each free to turn 90° about Z, never off the plate.

    clearance: room kept around every part for its brim (mm each side), on top of the gap between parts; a part that
    fits only without it is placed without it. exclude: zones of the bed nothing may cover ([[x0, y0, x1, y1]]).

    Returns {"plates": [{"n", "material", "parts": [{"id", "label", "x", "y", "w", "h", "rotated", "z", "material",
    "color", "orientation", "matrix"?}], "used_mm"}], "too_big": [too_big_entry], "count", "bed_mm", "spacing_mm",
    "margin_mm", "clearance_mm", "evidence"}. x, y are a part's lower-left corner on its plate (bed coordinates); with
    "matrix" (the part as modelled -> laid flat, centred on the origin) each placed part carries "matrix": where it
    is on its plate. Deterministic: the same parts give the same plates."""
    bed = [float(x) for x in bed]
    exclude = [list(map(float, z)) for z in exclude or ()]
    too_big = [x for x in parts if not fits_alone(x["size"][0], x["size"][1], x["size"][2], bed, margin, exclude,
                                       spacing_mm)]
    big_ids = {x["id"] for x in too_big}
    groups: dict = {}
    for x in parts:
        if x["id"] not in big_ids:
            groups.setdefault(x.get("material") or "", []).append(x)
    room = {}
    for x in parts:                                           # a brim's room, only where the part still fits with it
        c = max(0.0, float(clearance))
        room[x["id"]] = c if c and fits_alone(x["size"][0] + 2 * c, x["size"][1] + 2 * c, x["size"][2], bed, margin,
                                               exclude, spacing_mm) else 0.0
    plates = []
    for material, todo in groups.items():
        left = sorted(todo, key=lambda x: -(x["size"][0] * x["size"][1]))
        while left:
            r = packing.pack([{"id": x["id"], "w": x["size"][0] + 2 * room[x["id"]], "h": x["size"][1] + 2 * room[x["id"]]}
                              for x in left], bed[:2], spacing_mm, margin, True, exclude)
            if not r["placed"]:                                   # cannot happen for parts that fit alone; never loop
                too_big += left
                break
            by_id = {x["id"]: x for x in left}
            placed = []
            for q in r["placed"]:
                src, c = by_id[q["id"]], room[q["id"]]
                row = {"id": q["id"], "label": src.get("label") or q["id"], "x": round(q["x"] + c, 2),
                       "y": round(q["y"] + c, 2), "w": round(q["w"] - 2 * c, 2), "h": round(q["h"] - 2 * c, 2),
                       "rotated": q["rotated"], "z": round(float(src["size"][2]), 2),
                       "material": src.get("material") or "", "color": src.get("color") or "",
                       "orientation": src.get("orientation") or ""}
                if src.get("matrix"):
                    row["matrix"] = on_plate(src["matrix"], row)
                placed.append(row)
            plates.append({"n": len(plates) + 1, "material": material, "parts": placed, "used_mm": r["used_mm"]})
            done = {q["id"] for q in r["placed"]}
            left = [x for x in left if x["id"] not in done]
    big, cursor = [], 0.0
    for x in too_big:                                          # where a view draws it: beside the last plate, off it
        e = too_big_entry(x, bed, margin, exclude, spacing_mm)
        if x.get("matrix"):
            e["matrix"] = on_plate(x["matrix"], {"x": cursor, "y": 0.0, "w": float(x["size"][0]), "h": float(x["size"][1]),
                                                 "rotated": False})
            cursor += float(x["size"][0]) + spacing_mm
        big.append(e)
    return {"plates": plates, "too_big": big,
            "count": len(plates), "bed_mm": bed[:3], "spacing_mm": spacing_mm, "margin_mm": margin,
            "clearance_mm": round(float(clearance), 2), "exclude_mm": exclude, "evidence": "computed",
            "note": "Bounding boxes packed by Form Studio, one filament per plate, nothing off the plate. The slicer "
                    "slices each plate on its own."}


def on_plate(m: list, q: dict) -> list:
    """3×4 matrix: the part as modelled -> on its plate at q (x, y lower-left, turned 90° about Z when "rotated").
    m is the part as modelled -> laid flat in its print orientation, centred on the origin, standing on z = 0."""
    import numpy as np
    M = np.asarray(m, dtype=np.float64).reshape(3, 4)
    R = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]) if q["rotated"] else np.eye(3)
    t = np.array([q["x"] + q["w"] / 2, q["y"] + q["h"] / 2, 0.0])
    out = np.hstack([R @ M[:, :3], (R @ M[:, 3] + t)[:, None]])
    return [[round(float(v), 6) for v in r] for r in out]


def copies_of(parts: list, n: int) -> list:
    """N copies of every part, each its own id ("<id>#2"), labelled "<label> · 2" (copy 1 keeps the plain id)."""
    if n <= 1:
        return [dict(x) for x in parts]
    return [dict(x, id=x["id"] if k == 0 else f"{x['id']}#{k + 1}", copy=k + 1,
                 label=f"{x.get('label') or x['id']} · {k + 1}") for k in range(n) for x in parts]


def _points(v) -> list:
    if isinstance(v, str):
        v = v.split(",")
    out = []
    for pt in v or []:
        try:
            x, y = str(pt).split("x")[:2]
            out.append((float(x), float(y)))
        except ValueError:
            continue
    return out


def bed_zones(machine: dict) -> list:
    """Zones of the bed nothing may cover, from the slicer's machine preset, in bed coordinates (the printable area's
    lower-left corner at 0, 0): Bambu Studio / OrcaSlicer "bed_exclude_area" (an X1's cutter corner), and for a round
    bed (PrusaSlicer "bed_shape" or "printable_area" with more than four corners) the strips outside the largest
    square inside it, so a part is never packed where the round bed is not. [[x0, y0, x1, y1]]."""
    import math
    machine = machine or {}
    area = _points(machine.get("printable_area") or machine.get("bed_shape") or [])
    if not area:
        return []
    x0, y0 = min(p[0] for p in area), min(p[1] for p in area)
    x1, y1 = max(p[0] for p in area), max(p[1] for p in area)
    zones = []
    ex = _points(machine.get("bed_exclude_area") or [])
    if len(ex) >= 3:
        xs, ys = [p[0] - x0 for p in ex], [p[1] - y0 for p in ex]
        if max(xs) - min(xs) > 0 and max(ys) - min(ys) > 0:
            zones.append([round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)])
    if len(set(area)) > 4:                                   # a round (or many-sided) bed: keep to the square inside it
        w, h = x1 - x0, y1 - y0
        r = min(w, h) / 2
        s = r * math.sqrt(2) / 2                              # half the side of the inscribed square
        cx, cy = w / 2, h / 2
        lo_x, hi_x, lo_y, hi_y = cx - s, cx + s, cy - s, cy + s
        zones += [[0, 0, round(lo_x, 2), h], [round(hi_x, 2), 0, w, h], [0, 0, w, round(lo_y, 2)], [0, round(hi_y, 2), w, h]]
    return zones


def clearance(resolved: dict) -> tuple[float, str]:
    """Room a part needs around it on the plate for the slicer's brim, from the process preset the slice uses:
    (mm, where it comes from). 0 when the preset has no brim."""
    data = (((resolved or {}).get("presets") or {}).get("process") or {}).get("data") or {}
    kind = data.get("brim_type")
    try:
        width = float(str(data.get("brim_width") or 0).split(",")[0] or 0)
    except ValueError:
        width = 0.0
    if kind is not None:                                     # Bambu Studio, OrcaSlicer and their forks
        if str(kind) in ("no_brim", "") or width <= 0:
            return 0.0, ""
        return round(width, 2), f"brim {width:g} mm ({kind}) in the process preset"
    if width > 0:                                            # PrusaSlicer and its forks: brim_width > 0 is a brim
        return round(width, 2), f"brim {width:g} mm in the print settings"
    return 0.0, ""


def needed(parts: list, whole: list, bed: list, margin: float) -> bool:
    """Whether the design needs the plate plan: it does not fit one plate as modelled, or its parts differ in material."""
    if len(parts) < 2:
        return False
    if len({x.get("material") or "" for x in parts}) > 1:
        return True
    return not (whole[0] <= bed[0] - 2 * margin + 1e-6 and whole[1] <= bed[1] - 2 * margin + 1e-6
                and (len(bed) < 3 or whole[2] <= bed[2] + 1e-6))


def summary(pl: dict) -> str:
    n = pl["count"]
    s = f"{n} plate" + ("" if n == 1 else "s")
    if pl["too_big"]:
        s += "; " + ", ".join(x["label"] for x in pl["too_big"]) + (" does" if len(pl["too_big"]) == 1 else " do") + \
             " not fit the plate"
    return s


# ---- one plate as one STL -----------------------------------------------------------------------------------

def read_triangles(path: Path):
    """Triangles of an STL as an (n, 3, 3) float array (binary read directly; ASCII through mesh_audit)."""
    import numpy as np
    data = Path(path).read_bytes()
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * n:
            rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
            return np.frombuffer(data, dtype=rec, count=n, offset=84)["v"].astype(np.float64)
    from .mesh_audit import read_stl
    return np.asarray(read_stl(path)[0], dtype=np.float64).reshape(-1, 3, 3)


def write_plate_stl(path: Path, placed: list, stl_of: dict) -> dict:
    """Write the parts of one plate into one binary STL, each part at its packed place (turned 90° about Z when
    "rotated"). stl_of maps part id -> that part's STL. Returns {"triangles", "bbox"}."""
    import numpy as np
    chunks = []
    for q in placed:
        t = read_triangles(Path(stl_of[q["id"]]))
        if not len(t):
            continue
        if q["rotated"]:                                      # (x, y) -> (-y, x)
            t = np.stack([-t[..., 1], t[..., 0], t[..., 2]], axis=-1)
        lo = t.reshape(-1, 3).min(axis=0)
        chunks.append(t + np.array([q["x"] - lo[0], q["y"] - lo[1], -lo[2]]))
    tris = np.concatenate(chunks) if chunks else np.zeros((0, 3, 3))
    u, v = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    nrm = np.cross(u, v)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, ln, out=np.zeros_like(nrm), where=ln > 0)
    rec = np.zeros(len(tris), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = nrm, tris
    with open(Path(path), "wb") as f:
        f.write(b"Form Studio plate".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        f.write(rec.tobytes())
    pts = tris.reshape(-1, 3)
    bbox = [pts.min(axis=0).round(3).tolist(), pts.max(axis=0).round(3).tolist()] if len(pts) else None
    return {"triangles": int(len(tris)), "bbox": bbox}


# ---- the project's parts laid on its plates, and the 3MF of them --------------------------------------------------

def project_parts(st, p: dict, work: Path) -> list:
    """Every printed part of the head revision as it lies on the plate by itself, written as STLs under `work`:
    [{"id", "label", "stl", "size", "material", "color", "matrix"?}]. A design of one solid is one part: its exported STL."""
    from . import materials as looks
    keys, rev = st.keys(p), st.rev(p)
    name = f"{p['id']}_r{rev['n']:02d}"
    if getattr(st.recipe(p), "solids", 1) > 1:
        parts = st._plate_parts(p, rev, keys, name, st.slicer_info(p=p), out_dir=Path(work))
        if parts:
            return parts
    ex = st.read(p, "exports", keys["exports"])
    if not ex:
        from .studio import StudioError
        raise StudioError("There is no current exported model.", "Run the pipeline first (form run <project>).", status=409)
    stl = st.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
    look = looks.resolved(p, "")
    return [{"id": p["id"], "label": p["name"], "stl": str(stl), "size": list(ex.get("print_bbox") or [0, 0, 0]),
             "material": look.get("material") or "", "color": look.get("color") or ""}]


def layout(st, p: dict, work: Path, copies: int = 1) -> tuple[dict, dict, list]:
    """(plan, meshes, parts): the parts (copies of each, when asked) packed onto this design's printer's plates, and
    each part's mesh as it lies, centred on the origin (form/plate3mf.py places them)."""
    from . import plate3mf
    parts = project_parts(st, p, work)
    pe = st.printer_env(p)
    pl = st.plate_plan(p, parts, pe["envelope"], pe["margin"], copies)
    meshes = {x["id"]: plate3mf.mesh_of(read_triangles(Path(x["stl"]))) for x in parts}
    return pl, meshes, parts


def write_3mf(st, p: dict, folder: Path, copies: int = 1, kind: str | None = None) -> dict:
    """The design's plates as a 3MF (or several, where the slicer needs them: form/plate3mf.py) in `folder`, in the
    form the design's slicer (or `kind`) reads as several plates. Parts too big for the plate are not in any file:
    they are listed under "too_big" with what would make them fit. Computed by Form Studio; nothing is sliced."""
    import shutil
    from . import plate3mf, slicer
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    work = folder / ".parts"
    shutil.rmtree(work, ignore_errors=True)
    try:
        pl, meshes, _ = layout(st, p, work, copies)
        kind = kind or st.slicer_info(p=p).get("kind") or (st.cfg.get("slicer") or {}).get("kind") or "bambu"
        dial = plate3mf.dialect(kind)
        stem = f"{p['id']}_r{p['head']:02d}" + (f"_x{copies}" if copies > 1 else "") + "_plates"
        files = plate3mf.write_all(folder, stem, pl["plates"], meshes, dial, pl["bed_mm"],
                                   f"{p['name']} r{p['head']:02d}") if pl["plates"] else []
    finally:
        shutil.rmtree(work, ignore_errors=True)
    label = slicer.label(kind) if kind in plate3mf.BBL_KINDS + plate3mf.PRUSA_KINDS else kind
    how = ("one file; " + label + " reads each plate from Metadata/model_settings.config") if dial == "bbl" else \
        (f"{label} 2.9 or later reads the beds from where the parts sit"
         + (f"; {len(files)} files, at most {plate3mf.PRUSA_MAX_BEDS} plates each" if len(files) > 1 else ""))
    return {"project": p["id"], "rev": p["head"], "files": [str(f) for f in files], "dialect": dial, "slicer": label,
            "plates": pl["count"], "copies": copies, "too_big": pl["too_big"], "summary": summary(pl), "how": how,
            "plan": {k: pl[k] for k in ("count", "bed_mm", "spacing_mm", "margin_mm", "clearance_mm", "evidence", "note")},
            "evidence": "computed"}


# ---- the project: what the checks know, before any slice -------------------------------------------------------

def for_project(st, p: dict) -> dict:
    """The plate plan for the head revision from its current checks (part sizes as printed), and the slice's plates
    if there is a current one. Raises StudioError when there are no current checks."""
    from .studio import StudioError
    keys = st.keys(p)
    ch = st.read(p, "checks", keys["checks"])
    if not ch:
        raise StudioError("The checks have not been produced for this revision.", "Run the pipeline first (form run <project>).",
                          status=409)
    pe = st.printer_env(p)
    parts = ch.get("parts") or []
    out = {"project": p["id"], "rev": p["head"], "parts": parts, "bed_mm": pe["envelope"], "margin_mm": pe["margin"],
           "spacing_mm": spacing(st.cfg), "printer": pe["name"]}
    pl = (ch.get("context") or {}).get("plates")
    out["plan"] = pl
    out["summary"] = summary(pl) if pl else "1 plate"
    sl = st.read(p, "slice", keys["slice"])
    if sl:
        out["sliced"] = {"plates": [{k: x.get(k) for k in ("n", "material", "filament", "time_s", "filament_g", "layers",
                                                            "parts", "gcode", "threemf", "thumbnail")} for x in sl.get("plates", [])]
                         or [{"n": 1, "time_s": sl.get("time_s"), "filament_g": sl.get("filament_g"), "layers": sl.get("layers"),
                              "gcode": sl.get("gcode"), "threemf": sl.get("threemf")}],
                         "time_s": sl.get("time_s"), "filament_g": sl.get("filament_g"), "evidence": "simulated"}
    return out


def main_cli(argv: list) -> int:
    """form plates <project> [--orient PART=O] [--material PART=M] [--color PART=#hex]
       form design-only <project> on|off
       form material <project> <material | "">
       form purpose <project> [print | model] [--process cnc]    Each prints JSON."""
    import json
    import sys
    from . import config
    from .studio import Studio, StudioError
    cmd, args = argv[0], argv[1:]

    def out(d):
        print(json.dumps(d, indent=1, ensure_ascii=False, default=str))
    if not args:
        print(main_cli.__doc__, file=sys.stderr)
        return 2
    st = Studio(config.load())
    try:
        pid = args[0]
        if cmd == "design-only":
            if len(args) < 2 or args[1] not in ("on", "off"):
                raise StudioError("Say on or off.", "form design-only <project> on|off")
            p = st.settings(st.load(pid), {"design_only": args[1] == "on"})
            out({"project": pid, "design_only": bool(p.get("design_only")), "slicing": st.slice_mode(p),
                 "gate": st.gate(p)})
            return 0
        if cmd == "purpose":                      # form/purpose.py: print or model, and for a model how it is made
            body, rest = {}, args[1:]
            if rest and not rest[0].startswith("--"):
                body["purpose"] = rest.pop(0)
            if rest[:1] == ["--process"]:
                body["process"] = rest[1] if len(rest) > 1 else ""
            from . import purpose as purpose_mod
            p = st.settings(st.load(pid), body) if body else st.load(pid)
            out({"project": pid, **purpose_mod.describe(p), "slicing": st.slice_mode(p)})
            return 0
        if cmd == "material":
            p = st.settings(st.load(pid), {"material": args[1] if len(args) > 1 else ""})
            s = st.slicer_info(p=p)
            out({"project": pid, "material": p.get("material"), "filament": (s.get("material") or {}),
                 "presets": {k: v["name"] for k, v in (s.get("presets") or {}).items()}})
            return 0
        rest, changes = args[1:], {}
        while rest:
            flag, val = rest[0], rest[1] if len(rest) > 1 else ""
            rest = rest[2:]
            if flag not in ("--orient", "--material", "--color") or "=" not in val:
                raise StudioError(f"Unknown option {flag} {val}".strip(),
                                  "Use --orient PART=ORIENTATION, --material PART=MATERIAL or --color PART=#rrggbb.")
            part, v = val.split("=", 1)
            changes.setdefault(part, {})[{"--orient": "orientation"}.get(flag, flag[2:])] = v
        for part, ch in changes.items():
            st.set_part(pid, part, by="cli", **ch)
        if changes:
            st.run_sync(pid, ["geometry", "exports", "checks"])
        out(for_project(st, st.load(pid)))
        return 0
    except StudioError as e:
        out({"error": e.public()})
        return 2
