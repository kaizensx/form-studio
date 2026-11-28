"""The cut-file check: is this DXF ready for a laser, a waterjet or a CNC router? (numpy and ezdxf, no kernel)

Each layer's intent is read from its name (cut, bend, etch, ignore; form/sheet/dxf.py); cut geometry is chained
into contours and measured; the limits are the rule tables form/sheet/rules/cut_<process>.toml, judged by the same
code as manufacturability (form/dfm/rules.py), each with the page it was read from:

    open contours (the gap between free ends), duplicate and overlapping lines, contours that cross, tiny
    segments, text not converted to outlines, cut geometry on several layers, units, the smallest hole or slot
    (the width of its narrowest strip), hole to edge, hole to bend line, inside corner radius (waterjet and
    router), part size (router)

    check_file("part.dxf", "cut_laser", {"t": 1.5})
    check(entities, texts, bends, "cut_laser", {"t": 1.5})     # entities in geom2d form with "intent"

Options: t (the sheet thickness, mm; rules in multiples of t are not checked without it), units ("mm" or "in" to
override $INSUNITS), tol (chaining tolerance, default 0.001 mm).
"""
from __future__ import annotations

import math

import numpy as np

from ..dfm import rules
from . import dxf as dxfmod
from . import geom2d

PROCESSES = ("cut_laser", "cut_waterjet", "cut_router")
ALIASES = {"laser": "cut_laser", "waterjet": "cut_waterjet", "router": "cut_router", "cnc_router": "cut_router",
           "plasma": "cut_laser"}
TINY_LIST = 1.0           # segments shorter than this are listed (the rule's own threshold judges them)
ROUTER_MIN = (25.4, 50.8)                 # 1 x 2 in (form/sheet/rules/cut_router.toml)
ROUTER_MAX = {"default": (762.0, 1117.6), "delrin": (584.2, 1117.6)}


def process_id(name: str) -> str:
    s = str(name or "cut_laser").strip().lower().replace("-", "_").replace(" ", "_")
    s = ALIASES.get(s, s)
    if s not in PROCESSES:
        raise ValueError(f"Unknown cut process {name!r}: laser, waterjet or router.")
    return s


def _m(items, method, **kw) -> dict:
    return {"state": "measured", "items": items, "method": method, **kw}


def _pt(p) -> list:
    return [round(float(p[0]), 4), round(float(p[1]), 4)]


def _duplicates(ents: list, tol: float) -> list:
    """Pairs of cut entities lying on each other: collinear overlapping lines (polylines split into lines),
    concentric arcs of one radius whose spans overlap."""
    segs = []
    for i, e in enumerate(ents):
        if e["t"] == "line":
            segs.append((i, np.asarray(e["a"], float), np.asarray(e["b"], float)))
        elif e["t"] == "poly":
            P = geom2d.polyline(e)
            for a, b in zip(P[:-1], P[1:]):
                segs.append((i, a, b))
    groups: dict = {}
    for k, (i, a, b) in enumerate(segs):
        d = b - a
        L = float(np.hypot(*d))
        if L < 1e-12:
            continue
        ang = math.atan2(d[1], d[0]) % math.pi
        nrm = np.array([-math.sin(ang), math.cos(ang)])
        off = float(a @ nrm)
        key = (round(ang, 4), round(off / max(tol * 10, 1e-6)))
        groups.setdefault(key, []).append(k)
    out = []
    for ks in groups.values():
        if len(ks) < 2:
            continue
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                i, a, b = segs[ks[x]]
                j, c, d = segs[ks[y]]
                if i == j:
                    continue
                u = (b - a) / np.linalg.norm(b - a)
                nrm = np.array([-u[1], u[0]])
                if abs(float((c - a) @ nrm)) > tol or abs(float((d - a) @ nrm)) > tol:
                    continue
                s0, s1 = sorted([0.0, float((b - a) @ u)])
                t0, t1 = sorted([float((c - a) @ u), float((d - a) @ u)])
                ov = min(s1, t1) - max(s0, t0)
                if ov > tol:
                    mid = a + u * ((max(s0, t0) + min(s1, t1)) / 2)
                    out.append({"value": round(ov, 4), "at": _pt(mid), "handles": [ents[i].get("handle"), ents[j].get("handle")],
                                "what": f"{ents[i]['t']} and {ents[j]['t']} on each other for {ov:.3f} mm"})
    arcs = [(i, e) for i, e in enumerate(ents) if e["t"] in ("arc", "circle")]
    for x in range(len(arcs)):
        for y in range(x + 1, len(arcs)):
            i, e = arcs[x]
            j, f = arcs[y]
            if abs(e["r"] - f["r"]) > tol or float(np.hypot(*np.subtract(e["c"], f["c"]))) > tol:
                continue
            span = _arc_overlap(e, f)
            if span > 1e-6:
                ov = math.radians(span) * e["r"]
                if ov > tol:
                    out.append({"value": round(ov, 4), "at": _pt(e["c"]), "handles": [e.get("handle"), f.get("handle")],
                                "what": f"two {e['t']}s of radius {e['r']:g} on each other for {ov:.3f} mm"})
    return out


def _arc_overlap(e: dict, f: dict) -> float:
    def span(x):
        return (0.0, 360.0) if x["t"] == "circle" else (float(x["a0"]) % 360, float(x["a0"]) % 360 + geom2d.sweep(x))
    a0, a1 = span(e)
    b0, b1 = span(f)
    best = 0.0
    for sh in (-360.0, 0.0, 360.0):
        best = max(best, min(a1, b1 + sh) - max(a0, b0 + sh))
    return max(best, 0.0)


def _corners(loop: dict, ents: list, outer: bool) -> list:
    """Inside corners of a contour: where two entities meet at an angle turning into the material (radius 0), and
    arcs that curve into it (their radius). Material is inside an outer contour and outside a hole."""
    items = loop["items"]
    if len(items) == 1 and ents[items[0][0]]["t"] == "circle":
        return []
    m = (1 if loop["area"] > 0 else -1) * (1 if outer else -1)
    out = []
    dirs = []
    for k, rev in items:
        P = geom2d.polyline(ents[k])
        if rev:
            P = P[::-1]
        d0, d1 = geom2d.end_tangents(ents[k], rev)
        dirs.append((P[0], d0, P[-1], d1))
        e = ents[k]
        if e["t"] == "arc":
            turn = -1 if rev else 1
            if turn == -m:
                mid = P[len(P) // 2]
                out.append({"value": round(float(e["r"]), 4), "at": _pt(mid), "kind": "arc",
                            "handles": [e.get("handle")]})
    n = len(dirs)
    for i in range(n):
        _s, _ds, end, dout = dirs[i]
        _s2, din, _e2, _d2 = dirs[(i + 1) % n]
        cr = float(dout[0] * din[1] - dout[1] * din[0])
        dot = float(dout @ din)
        if abs(cr) < math.sin(math.radians(1.0)) and dot > 0:
            continue                               # tangent: no corner
        if np.sign(cr) == -m or (abs(cr) < 1e-12 and dot < 0):
            out.append({"value": 0.0, "at": _pt(end), "kind": "sharp",
                        "what": f"a sharp inside corner turning {math.degrees(math.atan2(abs(cr), dot)):.1f}°"})
    return out


def measure(entities: list, texts: list, bends: list, options: dict, units: dict | None = None,
            process: str = "cut_laser") -> tuple[dict, dict]:
    """The measures of form/sheet/rules/cut_*.toml on cut entities (those whose intent is cut)."""
    tol = float(options.get("tol") or 1e-3)
    cut = [e for e in entities if e.get("intent", "cut") == "cut"]
    loops, opens = geom2d.chain(cut, tol)
    geom2d.nest(loops)
    m: dict = {}
    m["open_contours"] = _m([{"value": round(float(np.hypot(*np.subtract(o["ends"][0], o["ends"][1]))), 4),
                              "at": _pt(o["ends"][0]), "to": _pt(o["ends"][1]),
                              "what": f"a chain of {len(o['items'])} entities with free ends"} for o in opens],
                            f"cut entities joined end to end within {tol:g} mm", none=None)
    dup = _duplicates(cut, tol)
    m["duplicate_lines"] = _m(dup, "collinear lines and concentric arcs of one radius whose spans overlap")
    X = []
    for i, a in enumerate(loops):
        for p in geom2d.crossings(a["pts"]):
            X.append({"value": 1, "at": _pt(p), "loop": i, "what": "a contour crossing itself"})
        for j in range(i + 1, len(loops)):
            b = loops[j]
            for p in geom2d.crossings(a["pts"], b["pts"]):
                X.append({"value": 1, "at": _pt(p), "loop": [i, j], "what": "two contours crossing"})
    m["crossings"] = _m(X[:200], f"segment crossings of the closed contours (arcs at {geom2d.ARC_STEP_DEG:g}° steps)")
    tiny = []
    for e in cut:
        L = geom2d.length(e)
        if L < TINY_LIST:
            P = geom2d.polyline(e)
            tiny.append({"value": round(L, 5), "at": _pt(P[0]), "handles": [e.get("handle")], "what": e["t"]})
    m["segment_mm"] = _m(tiny, f"the length of every cut entity; those under {TINY_LIST:g} mm listed",
                         none=None)
    tx = [{"value": 1, "at": t["at"], "layer": t["layer"], "text": t["text"][:40]} for t in texts
          if t.get("intent") in ("cut", "etch")]
    m["text_entities"] = _m(tx, "TEXT, MTEXT and attributes on cut or etch layers (they are not outlines)")
    cut_layers = sorted({e.get("layer", "0") for e in cut})
    m["cut_layers"] = _m([{"value": len(cut_layers), "layer": cut_layers}], "distinct layers holding cut geometry")
    if units is not None:
        ok = units.get("units") in ("mm", "in")
        m["units_ok"] = _m([{"value": ok, "what": f"{units.get('units')} ({units.get('units_source')}; the file says "
                                                  f"{units.get('units_found')})"}], "the DXF header $INSUNITS")
    else:
        m["units_ok"] = _m([{"value": True, "what": "mm (written here)"}], "written by Form Studio in mm")
    holes = [(i, lp) for i, lp in enumerate(loops) if lp["depth"] % 2 == 1]
    hw = []
    for i, lp in holes:
        w = geom2d.loop_width(lp, cut)
        hw.append({"value": round(w, 4), "at": _pt(lp["pts"][0]), "loop": i})
    m["hole_width_mm"] = _m(hw, "the width of each hole's narrowest enclosing strip (a circle's diameter, a slot's "
                                "width)", none=None if hw else "no holes")
    he = []
    for i, lp in holes:
        par = loops[lp["parent"]] if lp["parent"] is not None else None
        if par is None:
            continue
        d, p, _q = geom2d.seg_dist(lp["pts"], par["pts"])
        he.append({"value": round(d, 4), "at": _pt(p), "loop": i})
    m["hole_edge_mm"] = _m(he, "the shortest distance from each hole to the contour around it",
                           none=None if he else "no holes")
    hb = []
    for i, lp in holes:
        for k, b in enumerate(bends):
            d, p, _q = geom2d.seg_dist(lp["pts"], np.asarray(b["line"], float))
            hb.append({"value": round(d, 4), "at": _pt(p), "loop": i, "bend": b.get("id", k)})
    if bends:
        m["hole_bend_mm"] = _m(hb, "the shortest distance from each hole to each bend centre line",
                               none=None if hb else "no holes")
    else:
        m["hole_bend_mm"] = _m([], "bend lines", none="no bend lines in the file")
    cr = []
    for i, lp in enumerate(loops):
        for c in _corners(lp, cut, lp["depth"] % 2 == 0):
            c["loop"] = i
            cr.append(c)
    m["corner_r_mm"] = _m(cr, "inside corners of every contour: two entities meeting at an angle into the material "
                              "(radius 0) and arcs curving into it (their radius)", none=None if cr else "no inside corners")
    outer = [lp for lp in loops if lp["depth"] == 0]
    sizes = [geom2d.min_rect(lp["pts"]) for lp in outer]
    mat = str(options.get("material", "")).lower()
    mx = ROUTER_MAX["delrin"] if "delrin" in mat or "acetal" in mat else ROUTER_MAX["default"]
    m["part_min_fits"] = _m([{"value": bool(w >= ROUTER_MIN[0] - 1e-6 and L >= ROUTER_MIN[1] - 1e-6),
                              "size_mm": [round(w, 3), round(L, 3)], "loop": k} for k, (w, L) in enumerate(sizes)],
                            "each part's narrowest enclosing rectangle against 25.4 × 50.8 mm")
    m["part_max_fits"] = _m([{"value": bool(w <= mx[0] + 1e-6 and L <= mx[1] + 1e-6), "size_mm": [round(w, 3), round(L, 3)],
                              "machine_mm": list(mx), "loop": k} for k, (w, L) in enumerate(sizes)],
                            f"each part's narrowest enclosing rectangle against {mx[0]:g} × {mx[1]:g} mm")
    data = {"contours": len(loops), "open_chains": len(opens), "parts": len(outer), "holes": len(holes),
            "cut_entities": len(cut), "layers": cut_layers, "part_sizes_mm": [[round(w, 3), round(L, 3)] for w, L in sizes],
            "loops": [{"depth": lp["depth"], "area_mm2": round(abs(lp["area"]), 4), "n": len(lp["items"])} for lp in loops]}
    return m, data


def check(entities: list, texts: list, bends: list, process: str = "cut_laser", options: dict | None = None,
          units: dict | None = None, layers: dict | None = None) -> dict:
    process = process_id(process)
    o = dict(options or {})
    if o.get("t") not in (None, ""):
        o["t"] = float(o["t"])
        o["t_band"] = "thin" if o["t"] <= 0.914 + 1e-9 else "thick"
    meas, data = measure(entities, texts, bends, o, units, process)
    ev = rules.evaluate(process, {"measures": meas}, o)
    t = rules.table(process)
    unknown = sorted(k for k, v in (layers or {}).items() if not v.get("known"))
    res = {"process": process, "label": t["process"]["label"], "verdict": ev["verdict"], "rows": ev["rows"],
           "findings": ev["findings"], "data": data, "evidence": t["process"].get("evidence"),
           "not_judged": t["process"].get("not_judged", ""),
           "sources": [rules.source_text(s) for s in t["sources"].values()], "options": o}
    if layers is not None:
        res["layers"] = layers
    if unknown:
        res["layers_assumed_cut"] = unknown
    n = {s: sum(r["status"] == s for r in ev["rows"]) for s in ("fail", "warn", "not_checked", "pass")}
    bits = [f"{n[k]} {k.replace('_', ' ')}" for k in ("fail", "warn", "not_checked") if n[k]]
    res["headline"] = f"{res['label']}: {ev['verdict']}" + (f" ({', '.join(bits)})" if bits else f" ({n['pass']} rules pass)")
    return res


def check_file(path, process: str = "cut_laser", options: dict | None = None) -> dict:
    """Read a DXF and check it. Bend lines are the lines on bend layers."""
    o = dict(options or {})
    got = dxfmod.read(path, units=o.get("units"))
    bends = [{"line": [e["a"], e["b"]], "id": e.get("handle"), "layer": e["layer"]}
             for e in got["entities"] if e["intent"] == "bend" and e["t"] == "line"]
    ents = [e for e in got["entities"] if e["intent"] in ("cut", "etch")]
    res = check(ents, got["texts"], bends, process, o, units=got, layers=got["layers"])
    res["file"] = str(path)
    res["units"] = {k: got[k] for k in ("units", "units_found", "units_source", "scale")}
    if got["skipped"]:
        res["skipped"] = got["skipped"]
    return res
