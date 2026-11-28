"""Read a KiCad board (.kicad_pcb, KiCad 5 to 9) without KiCad: outline, holes, footprints with their courtyards,
heights the file states, keep-out areas, copper sizes and the board's own rules.

The file is read with Form Studio's own S-expression reader (form/board/sexpr.py). The project file next to it
(<name>.kicad_pro, JSON) is read for the rules KiCad 6 and later keep there (net classes, minimum clearance and
track width); without it the rules are what the board file itself states.

A footprint's height is taken from a property the footprint carries ("Height", "Component Height", "3D Height",
"Max Height"), as the footprint's author states it; the 3D model file it points to is not opened (it lives in
KiCad's libraries on the person's machine). A board STEP (KiCad's own export) gives measured heights instead
(form/board/fit.py op_board_step).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from . import model
from .sexpr import atoms, children, first, head, num, parse, value, xy

HEIGHT_PROPS = ("height", "component height", "3d height", "max height", "component_height", "height_mm")
CU = re.compile(r"^(F|B|In\d+)\.Cu$")


def _layer(node) -> str:
    v = value(node, "layer")
    return str(v) if v is not None else ""


def _layers(node) -> list[str]:
    c = first(node, "layers")
    if c is not None:
        return [str(a) for a in atoms(c)]
    lay = _layer(node)
    return [lay] if lay else []


def _width(node) -> float:
    w = num(value(node, "width"))
    if w is None:
        st = first(node, "stroke")
        w = num(value(st, "width")) if st is not None else None
    return w or 0.0


def _pts(node) -> list:
    c = first(node, "pts")
    return [(num(atoms(p)[0]), num(atoms(p)[1])) for p in children(c, "xy")] if c is not None else []


def _shape_polyline(g, kind: str):
    """A graphic item (gr_* or fp_*) as (closed loop or None, open polyline or None, circle (c, d) or None)."""
    t = kind.split("_", 1)[1]
    if t == "line":
        a, b = xy(g, "start"), xy(g, "end")
        return None, ([a, b] if a and b else None), None
    if t == "rect":
        a, b = xy(g, "start"), xy(g, "end")
        if not (a and b):
            return None, None, None
        return [(a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1])], None, None
    if t == "circle":
        c, e = xy(g, "center"), xy(g, "end")
        if not (c and e):
            return None, None, None
        return None, None, (c, 2 * math.hypot(e[0] - c[0], e[1] - c[1]))
    if t == "arc":
        a, m, b = xy(g, "start"), xy(g, "mid"), xy(g, "end")
        if a and m and b:                                       # KiCad 6 and later: start, mid, end
            return None, model.arc3(a, m, b), None
        ang = num(value(g, "angle"))
        if a and b and ang is not None:                         # KiCad 5: start is the centre, end the arc's start
            return None, model.arc_center(a, b, -ang), None
        return None, None, None
    if t in ("poly", "polygon"):
        p = _pts(g)
        return (p if len(p) >= 3 else None), None, None
    return None, None, None


def _prop(fp, name: str) -> str | None:
    for p in children(fp, "property"):
        a = atoms(p)
        if len(a) >= 2 and str(a[0]).lower() == name.lower():
            return str(a[1])
    for p in children(fp, "fp_text"):
        a = atoms(p)
        if len(a) >= 2 and str(a[0]).lower() == name.lower():
            return str(a[1])
    return None


def _height(fp) -> dict | None:
    for p in children(fp, "property"):
        a = atoms(p)
        if len(a) >= 2 and str(a[0]).strip().lower() in HEIGHT_PROPS:
            m = re.match(r"\s*([0-9]*\.?[0-9]+)\s*(mm)?\s*$", str(a[1]), re.I)
            if m:
                return {"value": float(m.group(1)), "provenance": "specified",
                        "source": f"the footprint's “{a[0]}” property in the board file"}
    return None


def _drill(pad) -> float | None:
    d = first(pad, "drill")
    if d is None:
        return None
    vals = [num(x) for x in atoms(d) if num(x) is not None]
    return min(vals) if vals else None


def read_rules(pcb: Path) -> dict:
    """The design rules KiCad 6+ keeps in the .kicad_pro beside the board (JSON), or {}."""
    pro = pcb.with_suffix(".kicad_pro")
    if not pro.is_file():
        return {}
    try:
        j = json.loads(pro.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": f"{pro.name} could not be read"}
    ds = ((j.get("board") or {}).get("design_settings") or {}).get("rules") or {}
    classes = ((j.get("net_settings") or {}).get("classes") or [])
    out = {"file": pro.name}
    for k in ("min_clearance", "min_track_width", "min_via_annular_width", "min_via_diameter", "min_through_hole_diameter",
              "min_hole_clearance", "min_copper_edge_clearance", "min_hole_to_hole"):
        if isinstance(ds.get(k), (int, float)):
            out[k] = float(ds[k])
    if classes:
        cl = [c.get("clearance") for c in classes if isinstance(c.get("clearance"), (int, float))]
        tw = [c.get("track_width") for c in classes if isinstance(c.get("track_width"), (int, float))]
        vd = [c.get("via_drill") for c in classes if isinstance(c.get("via_drill"), (int, float))]
        if cl:
            out["netclass_min_clearance"] = min(cl)
        if tw:
            out["netclass_min_track_width"] = min(tw)
        if vd:
            out["netclass_min_via_drill"] = min(vd)
        out["netclasses"] = [c.get("name") for c in classes]
    return out


def _seg_dist(a, b, c, d) -> float:
    """Shortest distance between segments ab and cd."""
    def pt_seg(p, s0, s1):
        vx, vy = s1[0] - s0[0], s1[1] - s0[1]
        L = vx * vx + vy * vy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - s0[0]) * vx + (p[1] - s0[1]) * vy) / L))
        return math.hypot(p[0] - s0[0] - t * vx, p[1] - s0[1] - t * vy)

    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2, d3, d4 = cross(c, d, a), cross(c, d, b), cross(a, b, c), cross(a, b, d)
    if (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0):
        return 0.0
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))


def track_spacing(segs: list, limit: int = 6000) -> dict | None:
    """The smallest edge-to-edge gap between two tracks of different nets on the same layer (computed on the
    segments; pads, vias and zones are not included: that is KiCad's DRC)."""
    if not segs or len(segs) > limit:
        return None
    cell = 2.0
    grid: dict = {}
    for i, s in enumerate(segs):
        (x0, y0), (x1, y1), w = s["a"], s["b"], s["w"]
        for gx in range(int(math.floor((min(x0, x1) - w) / cell)), int(math.floor((max(x0, x1) + w) / cell)) + 1):
            for gy in range(int(math.floor((min(y0, y1) - w) / cell)), int(math.floor((max(y0, y1) + w) / cell)) + 1):
                grid.setdefault((s["layer"], gx, gy), []).append(i)
    best = None
    seen = set()
    for idx in grid.values():
        for ii in range(len(idx)):
            for jj in range(ii + 1, len(idx)):
                i, j = idx[ii], idx[jj]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                a, b = segs[i], segs[j]
                if a["net"] == b["net"] and a["net"] != 0:
                    continue
                gap = _seg_dist(a["a"], a["b"], b["a"], b["b"]) - a["w"] / 2 - b["w"] / 2
                if best is None or gap < best["gap"]:
                    best = {"gap": round(gap, 4), "layer": a["layer"], "at": [round(v, 3) for v in a["a"]]}
    return best or {"gap": None}


def read(path: str | Path, origin=None) -> dict:
    """The board model (form/board/model.py) of a .kicad_pcb."""
    p = Path(path)
    data = p.read_bytes()
    text = data.decode("utf-8", errors="replace")
    tree = parse(text)
    if head(tree) not in ("kicad_pcb",):
        raise ValueError(f"{p.name} is not a KiCad board (it starts with “{head(tree) or '?'}”, not kicad_pcb).")
    notes = []
    gen = first(tree, "general")
    t = num(value(gen, "thickness")) if gen is not None else None
    if t is not None:
        thickness = {"value": t, "source": "the board file (general thickness)", "provenance": "specified"}
    else:
        thickness = {"value": 1.6, "source": "not in the file: 1.6 mm assumed (the common FR-4 thickness)",
                     "provenance": "assumed"}
        notes.append("The board file states no thickness; 1.6 mm is assumed.")
    layers = [str(l[1]) for l in (first(tree, "layers") or [])[1:] if isinstance(l, list) and len(l) >= 2]
    cu_layers = [x for x in layers if CU.match(x)]

    raw = {"format": "kicad_pcb", "y_down": True, "file": p.name, "sha256": hashlib.sha256(data).hexdigest(),
           "version": str(value(tree, "version") or ""), "generator": str(value(tree, "generator") or ""),
           "thickness": thickness, "edge_polylines": [], "edge_loops": [], "edge_circles": [], "holes": [],
           "components": [], "keepouts": [], "notes": notes, "origin": list(origin) if origin else None}

    def edge(g, kind, xf=None):
        loop, line, circ = _shape_polyline(g, kind)
        tr = xf or (lambda q: q)
        if loop:
            raw["edge_loops"].append([tr(q) for q in loop])
        if line:
            raw["edge_polylines"].append([tr(q) for q in line])
        if circ:
            c, d = circ
            raw["edge_circles"].append((tr(c), d))

    for g in tree[1:]:
        if isinstance(g, list) and head(g).startswith("gr_") and _layer(g) == "Edge.Cuts":
            edge(g, head(g))

    pads_drill, pads_annular, npth = [], [], []
    for fp in [c for c in tree[1:] if isinstance(c, list) and head(c) in ("footprint", "module")]:
        at = first(fp, "at")
        aa = atoms(at) if at is not None else []
        pos = (num(aa[0], 0.0), num(aa[1], 0.0)) if len(aa) >= 2 else (0.0, 0.0)
        ang = num(aa[2], 0.0) if len(aa) >= 3 else 0.0
        side = "bottom" if _layer(fp).startswith("B.") else "top"
        name = str(atoms(fp)[0]) if atoms(fp) else ""
        ref = _prop(fp, "Reference") or _prop(fp, "reference") or ""
        val = _prop(fp, "Value") or _prop(fp, "value") or ""
        xf = lambda q, pos=pos, ang=ang: (pos[0] + model.rot(q, ang)[0], pos[1] + model.rot(q, ang)[1])
        court = []
        for g in fp[1:]:
            if not (isinstance(g, list) and head(g).startswith("fp_")):
                continue
            lay = _layer(g)
            if lay == "Edge.Cuts":
                edge(g, head(g), xf)
            elif lay.endswith(".CrtYd"):
                loop, line, circ = _shape_polyline(g, head(g))
                court += (loop or []) + (line or [])
                if circ:
                    (cx, cy), d = circ
                    court += [(cx - d / 2, cy - d / 2), (cx + d / 2, cy + d / 2)]
        pads_local = []
        is_mount = bool(model.MOUNT_LIB.search(name))
        for pad in children(fp, "pad"):
            a = atoms(pad)
            kind = str(a[1]) if len(a) > 1 else ""
            pat = xy(pad, "at") or (0.0, 0.0)
            size = first(pad, "size")
            sz = [num(x) for x in atoms(size)] if size is not None else []
            sz = [x for x in sz if x is not None]
            if len(sz) >= 2:
                pads_local += [(pat[0] - sz[0] / 2, pat[1] - sz[1] / 2), (pat[0] + sz[0] / 2, pat[1] + sz[1] / 2)]
            dr = _drill(pad)
            if dr:
                w = xf(pat)
                plated = kind == "thru_hole"
                raw["holes"].append({"at": w, "d": dr, "plated": plated, "ref": ref,
                                     "mount": is_mount and dr >= 2.0})
                if plated:
                    pads_drill.append(dr)
                    if sz:
                        pads_annular.append((min(sz) - dr) / 2)
                else:
                    npth.append(dr)
        raw["components"].append({"ref": ref, "value": val, "footprint": name, "side": side, "at": pos, "rot": ang,
                                  "courtyard_local": court, "pads_local": pads_local, "height": _height(fp),
                                  "mount": is_mount})
    # mounting-hole footprints are holes, not components that need room
    raw["components"] = [c for c in raw["components"] if not c.pop("mount")]

    segs, widths = [], []
    for s in children(tree, "segment") + children(tree, "arc"):
        a, b = xy(s, "start"), xy(s, "end")
        w = num(value(s, "width")) or 0.0
        if a and b and w:
            widths.append(w)
            segs.append({"a": a, "b": b, "w": w, "layer": _layer(s), "net": int(num(value(s, "net"), 0) or 0)})
    vias = []
    for v in children(tree, "via"):
        sz, dr = num(value(v, "size")), num(value(v, "drill"))
        if sz and dr:
            vias.append((sz, dr))
    raw["copper"] = {
        "layers": len(cu_layers) or 2, "layer_names": cu_layers, "tracks": len(segs), "vias": len(vias),
        "min_track_width": min(widths) if widths else None,
        "min_via_drill": min(d for _s, d in vias) if vias else None,
        "min_via_annular": round(min((s - d) / 2 for s, d in vias), 4) if vias else None,
        "min_pth_drill": min(pads_drill) if pads_drill else None,
        "min_pad_annular": round(min(pads_annular), 4) if pads_annular else None,
        "min_npth_drill": min(npth) if npth else None,
        "track_spacing": track_spacing(segs),
    }
    for z in children(tree, "zone"):
        ko = first(z, "keepout")
        if ko is None:
            continue
        pol = first(z, "polygon")
        pts = _pts(pol) if pol is not None else []
        if len(pts) < 3:
            continue
        rules = {head(r): str(atoms(r)[0]) for r in ko[1:] if isinstance(r, list) and atoms(r)}
        raw["keepouts"].append({"name": str(value(z, "name") or ""), "layers": _layers(z), "rules": rules,
                                "polygon": pts})
    raw["rules"] = read_rules(p)
    setup = first(tree, "setup")
    if setup is not None:
        for k in ("pad_to_mask_clearance", "solder_mask_min_width"):
            v = num(value(setup, k))
            if v is not None:
                raw["rules"][k] = v
    return model.finish(raw)


def write_fixture(path: str | Path, *, w: float = 80.0, d: float = 50.0, t: float = 1.6,
                  holes: tuple = ((3.5, 3.5), (76.5, 3.5), (3.5, 46.5), (76.5, 46.5)), hole_d: float = 3.2,
                  usb_x: float = 40.0, usb_height: float | None = 3.26, cap_height: float | None = 10.0,
                  origin: tuple = (100.0, 100.0), track_w: float = 0.25, via=(0.6, 0.3)) -> Path:
    """A small synthetic KiCad 8 board for tests and demos: a w x d outline with four mounting holes, a USB-C
    receptacle on the front edge, a tall electrolytic capacitor and a pin header, a few tracks and a via. Its
    numbers are made up for testing; it is not a real product."""
    ox, oy = origin
    q = lambda v: f"{v:.4f}".rstrip("0").rstrip(".")
    lines = ["(kicad_pcb (version 20240108) (generator \"form_studio_fixture\") (generator_version \"8.0\")",
             f"  (general (thickness {q(t)}) (legacy_teardrops no))",
             "  (paper \"A4\")",
             "  (layers (0 \"F.Cu\" signal) (31 \"B.Cu\" signal) (44 \"Edge.Cuts\" user) (46 \"B.CrtYd\" user \"B.Courtyard\")"
             " (47 \"F.CrtYd\" user \"F.Courtyard\"))",
             "  (setup (pad_to_mask_clearance 0))",
             "  (net 0 \"\") (net 1 \"GND\") (net 2 \"VBUS\")"]
    corners = [(ox, oy), (ox + w, oy), (ox + w, oy + d), (ox, oy + d)]
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        lines.append(f"  (gr_line (start {q(a[0])} {q(a[1])}) (end {q(b[0])} {q(b[1])}) (stroke (width 0.05) (type default))"
                     " (layer \"Edge.Cuts\"))")
    for i, (hx, hy) in enumerate(holes):
        lines.append(f"  (footprint \"MountingHole:MountingHole_{q(hole_d)}mm_M3\" (layer \"F.Cu\") (at {q(ox + hx)} {q(oy + hy)})"
                     f" (property \"Reference\" \"H{i + 1}\" (at 0 -4 0) (layer \"F.SilkS\"))"
                     f" (fp_circle (center 0 0) (end {q(hole_d / 2 + 0.25)} 0) (stroke (width 0.05) (type solid)) (layer \"F.CrtYd\"))"
                     f" (pad \"\" np_thru_hole circle (at 0 0) (size {q(hole_d)} {q(hole_d)}) (drill {q(hole_d)}) (layers \"*.Cu\" \"*.Mask\")))")
    # USB-C receptacle: its courtyard reaches the front edge (KiCad's y grows toward the front, so the front is +y)
    uy = oy + d - 3.6
    hp = f" (property \"Height\" \"{q(usb_height)}\")" if usb_height is not None else ""
    lines.append(f"  (footprint \"Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal\" (layer \"F.Cu\")"
                 f" (at {q(ox + usb_x)} {q(uy)}) (property \"Reference\" \"J1\" (at 0 -5 0) (layer \"F.SilkS\"))"
                 f" (property \"Value\" \"USB_C_Receptacle\" (at 0 5 0) (layer \"F.Fab\")){hp}"
                 " (fp_rect (start -4.72 -3.6) (end 4.72 4.1) (stroke (width 0.05) (type solid)) (layer \"F.CrtYd\"))"
                 " (pad \"A1\" smd rect (at -3.2 -2.5) (size 0.6 1.1) (layers \"F.Cu\" \"F.Paste\" \"F.Mask\") (net 1 \"GND\"))"
                 " (pad \"A4\" smd rect (at -2.4 -2.5) (size 0.6 1.1) (layers \"F.Cu\" \"F.Paste\" \"F.Mask\") (net 2 \"VBUS\"))"
                 " (pad \"S1\" thru_hole oval (at -4.32 1.0) (size 1.0 2.1) (drill oval 0.6 1.7) (layers \"*.Cu\" \"*.Mask\")))")
    hp = f" (property \"Height\" \"{q(cap_height)}\")" if cap_height is not None else ""
    lines.append(f"  (footprint \"Capacitor_THT:CP_Radial_D8.0mm_P3.50mm\" (layer \"F.Cu\") (at {q(ox + 20)} {q(oy + 20)})"
                 f" (property \"Reference\" \"C1\" (at 0 -5 0) (layer \"F.SilkS\")) (property \"Value\" \"470u\" (at 0 5 0) (layer \"F.Fab\")){hp}"
                 " (fp_circle (center 1.75 0) (end 6.0 0) (stroke (width 0.05) (type solid)) (layer \"F.CrtYd\"))"
                 " (pad \"1\" thru_hole rect (at 0 0) (size 1.6 1.6) (drill 0.8) (layers \"*.Cu\" \"*.Mask\") (net 2 \"VBUS\"))"
                 " (pad \"2\" thru_hole circle (at 3.5 0) (size 1.6 1.6) (drill 0.8) (layers \"*.Cu\" \"*.Mask\") (net 1 \"GND\")))")
    lines.append(f"  (footprint \"Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical\" (layer \"F.Cu\") (at {q(ox + 55)} {q(oy + 20)} 90)"
                 " (property \"Reference\" \"J2\" (at 0 -2.33 0) (layer \"F.SilkS\")) (property \"Height\" \"8.5\")"
                 " (fp_rect (start -1.8 -1.8) (end 1.8 9.4) (stroke (width 0.05) (type solid)) (layer \"F.CrtYd\"))"
                 + "".join(f" (pad \"{k + 1}\" thru_hole circle (at 0 {q(k * 2.54)}) (size 1.7 1.7) (drill 1.0) (layers \"*.Cu\" \"*.Mask\"))"
                           for k in range(4)) + ")")
    lines.append(f"  (segment (start {q(ox + 20)} {q(oy + 20)}) (end {q(ox + 37.6)} {q(oy + 20)}) (width {q(track_w)}) (layer \"F.Cu\") (net 2))")
    lines.append(f"  (segment (start {q(ox + 23.5)} {q(oy + 21)}) (end {q(ox + 36.8)} {q(oy + 21)}) (width {q(track_w)}) (layer \"F.Cu\") (net 1))")
    lines.append(f"  (via (at {q(ox + 30)} {q(oy + 30)}) (size {q(via[0])}) (drill {q(via[1])}) (layers \"F.Cu\" \"B.Cu\") (net 1))")
    lines.append(f"  (zone (net 0) (net_name \"\") (layers \"F&B.Cu\") (name \"antenna\") (hatch edge 0.5)"
                 f" (keepout (tracks not_allowed) (vias not_allowed) (pads not_allowed) (copperpour not_allowed) (footprints allowed))"
                 f" (polygon (pts (xy {q(ox + 60)} {q(oy + 30)}) (xy {q(ox + 75)} {q(oy + 30)}) (xy {q(ox + 75)} {q(oy + 40)}) (xy {q(ox + 60)} {q(oy + 40)}))))")
    lines.append(")")
    path = Path(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
