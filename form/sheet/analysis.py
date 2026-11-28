"""The measures of the sheet-metal rules (form/dfm/rules/sheet_metal.toml), taken on an unfold result (numpy only).

    unfolds        the part is one sheet that lays flat (the unfold's reasons when not)
    fold_back_mm   the fold-back's largest error
    flat_crossings places where the flat overlaps itself
    flange_mm      per bend and side, the straight run from the bend zone to the next bend or the free edge,
                   over the bend's own span (a jog's web counts: a jog shorter than the rule needs a jog tool)
    hole_d_mm      each hole's narrowest width
    hole_edge_mm   each hole to the contour around it
    hole_bend_mm   each hole to the nearest bend zone (its start or end line; 0 when it crosses the zone)
    hem_d_mm       each hem's (a bend of 179° or more) inside diameter, 2 r
    bend_r_mm      each bend's inside radius (information)
"""
from __future__ import annotations

import numpy as np

from . import geom2d


def _m(items, method, **kw) -> dict:
    return {"state": "measured", "items": items, "method": method, **kw}


def _not(reason: str) -> dict:
    return {"state": "not_checked", "items": [], "reason": reason}


def _pt(p) -> list:
    return [round(float(p[0]), 4), round(float(p[1]), 4)]


def _face_points(ents: list, faces) -> np.ndarray:
    fs = set(faces)
    P = [geom2d.polyline(e) for e in ents if e.get("face") in fs]
    return np.vstack(P) if P else np.zeros((0, 2))


def flanges(res: dict) -> list:
    """Per bend and side: the straight run of the flat beside the zone, within the bend's span along its line."""
    ents = res["entities"]
    bends = res["bends"]
    out = []
    for b in bends:
        u = np.asarray(b["u"], float)
        d = np.asarray(b["d"], float)
        S0 = np.asarray(b["start"][0], float)
        E0 = np.asarray(b["end"][0], float)
        L = float(b["length"])
        for side, faces, origin, sign in (("after", b.get("after") or [], E0, 1.0),
                                          ("before", [b["before"]] if b.get("before") is not None else [], S0, -1.0)):
            P = _face_points(ents, faces)
            if len(P):
                along = (P - origin) @ u
                keep = (along > -1e-6) & (along < L + 1e-6)
                run = float(np.max(sign * ((P[keep] - origin) @ d))) if keep.any() else 0.0
            else:
                run = 0.0
            # stop at the next bend zone on that side
            for c in bends:
                if c is b:
                    continue
                for line in (c["start"], c["end"]):
                    Q = np.asarray(line, float)
                    a = (Q - origin) @ u
                    if np.all(a < -1e-6) or np.all(a > L + 1e-6):
                        continue
                    dist = sign * ((Q - origin) @ d)
                    if np.all(dist > 1e-6):
                        run = min(run, float(dist.min())) if len(P) else float(dist.min())
            at = origin + u * (L / 2) + sign * d * (run / 2)
            kind = "flange" if len(P) else "between bends"
            out.append({"value": round(max(run, 0.0), 4), "at": _pt(at), "bend": b["id"], "kind": kind, "what": side})
    return out


def measures(res: dict) -> tuple[dict, dict]:
    """(measures, data) for the sheet-metal rules from one unfold result."""
    m: dict = {}
    ok = bool(res.get("entities")) and not res.get("reasons") and not res.get("open_ends")
    why = "; ".join(r["why"] for r in res.get("reasons", [])[:4]) or ""
    m["unfolds"] = _m([{"value": ok, "what": why or "one sheet, unfolded",
                        "faces": sorted({r["face"] for r in res.get("reasons", []) if "face" in r})}],
                      "the skin walked across tangent edges from the base; thickness and volume checked")
    if not res.get("entities"):
        for k in ("fold_back_mm", "flat_crossings", "flange_mm", "hole_d_mm", "hole_edge_mm", "hole_bend_mm",
                  "hem_d_mm", "bend_r_mm"):
            m[k] = _not("Not checked: the part does not unfold" + (f" ({why})" if why else "") + ".")
        return m, {}
    v = res.get("verify") or {}
    m["fold_back_mm"] = _m([{"value": round(float(v.get("max_mm", 0.0)), 9), "what": f"{v.get('samples', 0)} samples",
                             **({"at": v["worst"]["at"]} if v.get("worst") else {})}], v.get("method", ""))
    X = res.get("flat_crossings") or []
    m["flat_crossings"] = _m([{"value": 1, "at": _pt(p)} for p in X], "segment crossings of the flat's contours")
    m["flange_mm"] = _m(flanges(res), "per bend and side, the straight run beside the zone over the bend's span",
                        none=None if res["bends"] else "no bends")
    ents = res["entities"]
    loops, _opens = geom2d.chain(ents, 1e-3)
    geom2d.nest(loops)
    holes = [(i, lp) for i, lp in enumerate(loops) if lp["depth"] % 2 == 1]
    hd, he, hb = [], [], []
    zones = []
    for b in res["bends"]:
        Z = np.array([b["start"][0], b["start"][1], b["end"][1], b["end"][0], b["start"][0]], float)
        zones.append((b["id"], Z))
    for i, lp in holes:
        w = geom2d.loop_width(lp, ents)
        hd.append({"value": round(w, 4), "at": _pt(lp["pts"][0]), "loop": i})
        if lp["parent"] is not None:
            d, p, _q = geom2d.seg_dist(lp["pts"], loops[lp["parent"]]["pts"])
            he.append({"value": round(d, 4), "at": _pt(p), "loop": i})
        best = None
        for bid, Z in zones:
            inside = any(geom2d.inside(p, Z) for p in lp["pts"][::max(1, len(lp["pts"]) // 16)])
            d, p, _q = geom2d.seg_dist(lp["pts"], Z)
            d = 0.0 if inside else d
            if best is None or d < best["value"]:
                best = {"value": round(d, 4), "at": _pt(p), "loop": i, "bend": bid}
        if best is not None:
            hb.append(best)
    m["hole_d_mm"] = _m(hd, "each hole's narrowest enclosing strip in the flat", none=None if hd else "no holes")
    m["hole_edge_mm"] = _m(he, "each hole to the contour around it, in the flat", none=None if he else "no holes")
    m["hole_bend_mm"] = _m(hb, "each hole to the nearest bend zone, in the flat",
                           none=None if hb else ("no holes" if not holes else "no bends"))
    hem = [{"value": round(2 * b["r"], 4), "bend": b["id"], "at": _pt(np.mean(b["line"], axis=0))}
           for b in res["bends"] if b["angle"] >= 179.0]
    m["hem_d_mm"] = _m(hem, "2 × the inside radius of every bend of 179° or more", none=None if hem else "no hems")
    m["bend_r_mm"] = _m([{"value": round(b["r"], 4), "bend": b["id"], "at": _pt(np.mean(b["line"], axis=0))}
                         for b in res["bends"]], "each bend's inside radius", none=None if res["bends"] else "no bends")
    data = {"t": res["t"], "bends": len(res["bends"]), "holes": len(holes), "size_mm": res.get("size_mm"),
            "area_mm2": res.get("area_mm2")}
    return m, data
