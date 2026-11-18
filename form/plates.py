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

PLATES_VERSION = 1
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


def fits_alone(w: float, h: float, z: float, bed: list, margin: float) -> bool:
    aw, ah = bed[0] - 2 * margin, bed[1] - 2 * margin
    flat = (w <= aw + 1e-6 and h <= ah + 1e-6) or (h <= aw + 1e-6 and w <= ah + 1e-6)
    return flat and (len(bed) < 3 or z <= bed[2] + 1e-6)


def plan(parts: list, bed: list, spacing_mm: float = DEFAULT_SPACING_MM, margin: float = 0.0) -> dict:
    """Pack parts ([{"id", "label", "size": [w, d, h], "material"?, "color"?}]) onto as few plates as this packer can.

    Returns {"plates": [{"n", "material", "parts": [{"id", "label", "x", "y", "w", "h", "rotated", "material", "color"}],
    "used_mm"}], "too_big": [{"id", "label", "size"}], "count", "bed_mm", "spacing_mm", "margin_mm", "evidence"}."""
    bed = [float(x) for x in bed]
    too_big = [x for x in parts if not fits_alone(x["size"][0], x["size"][1], x["size"][2], bed, margin)]
    big_ids = {x["id"] for x in too_big}
    groups: dict = {}
    for x in parts:
        if x["id"] not in big_ids:
            groups.setdefault(x.get("material") or "", []).append(x)
    plates = []
    for material, todo in groups.items():
        left = sorted(todo, key=lambda x: -(x["size"][0] * x["size"][1]))
        while left:
            r = packing.pack([{"id": x["id"], "w": x["size"][0], "h": x["size"][1]} for x in left], bed[:2], spacing_mm, margin)
            if not r["placed"]:                                   # cannot happen for parts that fit alone; never loop
                too_big += left
                break
            by_id = {x["id"]: x for x in left}
            placed = []
            for q in r["placed"]:
                src = by_id[q["id"]]
                placed.append({"id": q["id"], "label": src.get("label") or q["id"], "x": q["x"], "y": q["y"], "w": q["w"],
                               "h": q["h"], "rotated": q["rotated"], "z": round(float(src["size"][2]), 2),
                               "material": src.get("material") or "", "color": src.get("color") or "",
                               "orientation": src.get("orientation") or ""})
            plates.append({"n": len(plates) + 1, "material": material, "parts": placed, "used_mm": r["used_mm"]})
            done = {q["id"] for q in r["placed"]}
            left = [x for x in left if x["id"] not in done]
    return {"plates": plates, "too_big": [{"id": x["id"], "label": x.get("label") or x["id"],
                                           "size": [round(float(v), 1) for v in x["size"]]} for x in too_big],
            "count": len(plates), "bed_mm": bed[:3], "spacing_mm": spacing_mm, "margin_mm": margin, "evidence": "computed",
            "note": "Bounding boxes packed by Form Studio, one filament per plate. The slicer slices each plate on its own."}


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
       form material <project> <material | "">          Each prints JSON."""
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
