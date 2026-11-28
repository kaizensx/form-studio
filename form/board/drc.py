"""Form Studio's own geometric check of a board's copper. It is not KiCad's DRC and never says it is.

What it computes, in closed form on the shapes of form/board/geom.py (no grid, no sampling):

    clearance      copper to copper between different nets on the same layer: track, via and pad against each
                   other, against the larger of the two nets' class clearances
    edge           tracks and vias against the board outline and its cut-outs
    hole           tracks and vias against non-plated holes; drilled hole to drilled hole
    keep-out       tracks and vias inside a keep-out area that forbids them
    width          track width and via size against the board's minimums
    unconnected    for each net, the groups of pads its copper does not join

What it does not look at is listed in the result under "not_checked": zone fills, solder mask, silkscreen,
courtyards, annular rings, custom-shaped pads (their bounding box is used, which can only report too little room),
differential pairs, length rules. KiCad's DRC covers those; `route` runs it when kicad-cli is installed.
"""
from __future__ import annotations

import math

from . import geom
from .pcb import Pcb, pad_copper

BY = "Form Studio geometric check (not KiCad's DRC)"
EPS = 1e-6                      # mm: KiCad's own resolution is 1 nm
NOT_CHECKED = ["zone fills (copper pours) and thermal reliefs", "solder mask, paste and silkscreen",
               "courtyard overlaps", "annular rings", "differential pairs and length rules",
               "custom rules in a .kicad_dru file", "pads of the same footprint against each other"]


def items(doc: Pcb) -> tuple[list, list]:
    """(copper items, notes). Each item: {"kind", "shape", "net", "layers", "ref", "at", "cls"...}."""
    out, notes = [], []
    names = doc.nets()
    inexact = 0
    for f in doc.footprints():
        for p in f["pads"]:
            shape, exact = pad_copper(p)
            if not exact:
                inexact += 1
            if p["kind"] == "np_thru_hole":
                if p["drill"]:
                    out.append({"kind": "hole", "shape": geom.circle((p["x"], p["y"]), p["drill_max"] or p["drill"]),
                                "net": -1, "layers": doc.cu_layers(), "ref": f["ref"], "pad": p["num"],
                                "at": (p["x"], p["y"]), "fp": id(f["node"]), "drill": p["drill"]})
                continue
            if not p["layers"]:
                continue
            out.append({"kind": "pad", "shape": shape, "net": p["net"], "layers": p["layers"], "ref": f["ref"],
                        "pad": p["num"], "at": (p["x"], p["y"]), "fp": id(f["node"]), "drill": p["drill"],
                        "tht": p["kind"] == "thru_hole"})
    for t in doc.tracks():
        out.append({"kind": "track", "shape": geom.capsule(t["a"], t["b"], t["w"]), "net": t["net"], "layers": [t["layer"]],
                    "at": t["a"], "w": t["w"]})
    if any(t["arc"] for t in doc.tracks()):
        notes.append("Arc tracks are checked as their chord (start to end), not the arc.")
    for v in doc.vias():
        out.append({"kind": "via", "shape": geom.circle(v["at"], v["size"]), "net": v["net"], "layers": v["layers"],
                    "at": v["at"], "drill": v["drill"], "size": v["size"]})
    if inexact:
        notes.append(f"{inexact} pad(s) have a custom or trapezoid shape: their bounding rectangle is used.")
    for it in out:
        it["name"] = names.get(it["net"], "") if it["net"] > 0 else ""
    return out, notes


def _label(it: dict) -> str:
    if it["kind"] in ("pad", "hole"):
        return f"{it['kind']} {it['ref']}.{it['pad']}" if it["pad"] else f"{it['kind']} of {it['ref']}"
    return f"{it['kind']} of {it['name'] or 'no net'} at {it['at'][0]:.3f}, {it['at'][1]:.3f}"


def connectivity(doc: Pcb, its: list | None = None) -> dict:
    """For each net with pads: the groups its tracks and vias join. Two items of a net are joined when their copper
    touches on a shared layer. A net with a zone is "by_zone": its fill may join it and is not computed here."""
    its = its if its is not None else items(doc)[0]
    zone_nets = {z["net"] for z in doc.zones() if z["keepout"] is None and z["net"] > 0}
    by: dict = {}
    for i, it in enumerate(its):
        if it["net"] > 0 and it["kind"] != "hole":
            by.setdefault(it["net"], []).append(i)
    names = doc.nets()
    out = {}
    for net, idx in sorted(by.items()):
        parent = {i: i for i in idx}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        index = geom.Index(2.0)
        ids = {}
        for i in idx:
            ids[index.add(its[i]["shape"])] = i
        for k, i in ids.items():
            a = its[i]
            for k2, s2, _m in index.near(geom.bbox(a["shape"])):
                j = ids[k2]
                if j <= i or find(i) == find(j):
                    continue
                b = its[j]
                if not set(a["layers"]) & set(b["layers"]):
                    continue
                if geom.gap(a["shape"], s2) <= EPS:
                    parent[find(i)] = find(j)
        groups: dict = {}
        for i in idx:
            if its[i]["kind"] == "pad":
                groups.setdefault(find(i), []).append(f"{its[i]['ref']}.{its[i]['pad']}")
        pads = sum(len(g) for g in groups.values())
        if pads < 2:
            continue
        gl = sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])
        out[names.get(net, str(net))] = {"net": net, "pads": pads, "groups": gl, "missing": len(gl) - 1,
                                         "by_zone": net in zone_nets}
    return out


def check(doc: Pcb, limit: int = 500) -> dict:
    """The whole check. Rows are violations only; "min_clearance" is the tightest gap measured, violation or not."""
    its, notes = items(doc)
    rules = doc.rules
    names = doc.nets()
    cls = {n: rules.for_net(nm) for n, nm in names.items()}
    dflt = rules.for_net("")
    clr = lambda it: (cls.get(it["net"]) or dflt)["clearance"]
    rows: list = []
    tight = None

    def row(kind, desc, need, got, a, b=None):
        rows.append({"type": kind, "severity": "error", "description": desc, "required_mm": round(need, 4),
                     "measured_mm": round(got, 4), "at": [round(a["at"][0], 4), round(a["at"][1], 4)],
                     "items": [_label(a)] + ([_label(b)] if b else [])})

    index = geom.Index(2.0)
    ids = {}
    for i, it in enumerate(its):
        ids[index.add(it["shape"])] = i
    max_clr = max([c["clearance"] for c in cls.values()] + [dflt["clearance"], rules.board["min_hole_clearance"],
                                                               rules.board["min_hole_to_hole"]])
    pairs = 0
    for k, i in ids.items():
        a = its[i]
        for k2, s2, _m in index.near(geom.bbox(a["shape"]), max_clr + 0.01):
            j = ids[k2]
            if j <= i:
                continue
            b = its[j]
            # drilled hole to drilled hole, whatever the nets
            if a.get("drill") and b.get("drill") and (a["kind"], b["kind"]) != ("pad", "pad"):
                need = rules.board["min_hole_to_hole"]
                got = math.hypot(a["at"][0] - b["at"][0], a["at"][1] - b["at"][1]) - (a["drill"] + b["drill"]) / 2
                if got < need - EPS:
                    row("hole_to_hole", f"{_label(a)} and {_label(b)}: drilled holes {got:.3f} mm apart, {need:g} needed",
                        need, got, a, b)
            if not set(a["layers"]) & set(b["layers"]):
                continue
            if a["kind"] == "hole" or b["kind"] == "hole":
                h, o = (a, b) if a["kind"] == "hole" else (b, a)
                if o["kind"] in ("track", "via"):
                    need = rules.board["min_hole_clearance"]
                    got = geom.gap(a["shape"], s2)
                    pairs += 1
                    if got < need - EPS:
                        row("hole_clearance", f"{_label(o)} is {got:.3f} mm from the {_label(h)}, {need:g} needed", need, got, o, h)
                continue
            if a["net"] == b["net"] and a["net"] > 0:
                continue
            if a["kind"] == "pad" and b["kind"] == "pad" and (a["fp"] == b["fp"] or (a["net"] == 0 and b["net"] == 0)):
                continue
            need = max(clr(a), clr(b))
            got = geom.gap(a["shape"], s2)
            pairs += 1
            if a["kind"] != "pad" or b["kind"] != "pad":
                if tight is None or got < tight["gap_mm"]:
                    tight = {"gap_mm": round(got, 4), "required_mm": round(need, 4), "between": [_label(a), _label(b)],
                             "layer": sorted(set(a["layers"]) & set(b["layers"]))[0]}
            if got < need - EPS:
                row("clearance", f"{_label(a)} and {_label(b)}: {got:.3f} mm apart, {need:g} needed", need, got, a, b)

    outline, cutouts, enotes = doc.edges()
    notes += enotes
    edge = rules.board["min_copper_edge_clearance"]
    kos = doc.keepouts()
    for it in its:
        if it["kind"] not in ("track", "via"):
            continue
        pts = it["shape"][0]
        a, b = pts[0], pts[-1]
        if outline:
            d = min([geom.poly_seg_dist(outline, a, b)] + [geom.poly_seg_dist(c, a, b) for c in cutouts]) - it["shape"][1]
            out_of = not geom.inside(a, outline) or any(geom.inside(a, c) for c in cutouts)
            if out_of:
                row("edge", f"{_label(it)} is outside the board outline", edge, -1.0, it)
            elif d < edge - EPS:
                row("edge", f"{_label(it)} is {d:.3f} mm from the board edge, {edge:g} needed", edge, d, it)
        for z in kos:
            flag = "tracks" if it["kind"] == "track" else "vias"
            if z["keepout"].get(flag) != "not_allowed" or not set(z["layers"]) & set(it["layers"]):
                continue
            if geom.inside(a, z["polygon"]) or geom.inside(b, z["polygon"]) or \
                    geom.poly_seg_dist(z["polygon"], a, b) < it["shape"][1] - EPS:
                row("keepout", f"{_label(it)} is in the keep-out area “{z['name'] or 'unnamed'}” ({flag} not allowed)",
                    0.0, 0.0, it)
        if it["kind"] == "track" and rules.board["min_track_width"] and it["w"] < rules.board["min_track_width"] - EPS:
            row("track_width", f"{_label(it)} is {it['w']:g} mm wide, {rules.board['min_track_width']:g} is the minimum",
                rules.board["min_track_width"], it["w"], it)
        if it["kind"] == "via" and rules.board["min_via_diameter"] and it["size"] < rules.board["min_via_diameter"] - EPS:
            row("via_size", f"{_label(it)} is Ø{it['size']:g}, Ø{rules.board['min_via_diameter']:g} is the minimum",
                rules.board["min_via_diameter"], it["size"], it)

    conn = connectivity(doc, its)
    unconnected = [{"net": n, "groups": c["groups"], "missing_connections": c["missing"]}
                   for n, c in conn.items() if c["missing"] and not c["by_zone"]]
    zone_nets = [n for n, c in conn.items() if c["missing"] and c["by_zone"]]
    counts: dict = {}
    for r in rows:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
    if zone_nets:
        notes.append("Nets with a zone (" + ", ".join(zone_nets) + ") are not counted as unconnected: the zone's fill "
                     "may join them, and fills are not computed here.")
    if any(z["keepout"] is None for z in doc.zones()):
        notes.append("This board has copper zones. Their fills are not checked, and tracks added since the last fill "
                     "need the zones filled again in KiCad.")
    total = len(rows)
    return {"by": BY, "evidence": "computed (closed-form distances between copper shapes)", "rows": rows[:limit],
            "total": total, "counts": counts, "pairs_measured": pairs, "min_clearance": tight,
            "unconnected": unconnected, "unconnected_total": sum(u["missing_connections"] for u in unconnected),
            "rules": rules.describe(), "not_checked": NOT_CHECKED, "notes": notes,
            "ok": total == 0 and not unconnected,
            "headline": (f"{total} clearance or rule " + ("finding" if total == 1 else "findings") if total else
                         "no clearance or rule findings") +
                        (f", {sum(u['missing_connections'] for u in unconnected)} connection(s) not made" if unconnected else
                         ", every net joined") + " (Form Studio's own check, not KiCad's DRC)"}
