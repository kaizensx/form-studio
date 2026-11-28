"""The board as Form Studio reads it, whatever file it came from: one JSON-able dict in the board frame.

Board frame: millimetres, x to the right and y away from the viewer seen from the top (KiCad's y points down, so
y is negated), z up from the board's bottom face, origin at the centre of the outline's bounding box. `origin`
keeps where that centre is in the source file's own coordinates, so a board read again later is placed in the
same frame and a connector that moved shows up as moved.

    {"format", "file", "sha256", "thickness": {"value", "source"}, "origin": [x, y], "size": [w, d],
     "outline": [[x, y], ...], "cutouts": [[[x, y], ...]], "holes": [...], "mounting_holes": [...],
     "components": [...], "connectors": [...], "keepouts": [...], "copper": {...}, "rules": {...}, "notes": [...]}

Pure Python; no kernel. Heights are only what the file, a board STEP or the person states: a component without one
has height None and every check that needs it says "not checked" instead of guessing.
"""
from __future__ import annotations

import math
import re

ARC_STEP_DEG = 5.0
JOIN_TOL = 0.01                 # mm: two segment ends closer than this are the same point of the outline
EDGE_NEAR = 2.5                 # mm: a connector whose courtyard comes this close to a board edge opens through it
SIDES = ("-x", "+x", "-y", "+y")
SIDE_NAMES = {"-x": "left", "+x": "right", "-y": "front", "+y": "back", "up": "top (mates from above)"}

# plug envelopes Form Studio knows from a published specification; everything else is assumed and said so
USB_C_PLUG = {"w": 12.35, "h": 6.5, "source": "USB Type-C Cable and Connector Specification: plug overmold "
                                              "12.35 x 6.5 mm maximum (specified)", "provenance": "specified"}
PLUG_MARGIN = 1.5               # mm per side added to a connector's face when no plug envelope is known (assumed)
CONNECTOR_REF = re.compile(r"^(J|P|CN|CON|USB|X)\d", re.I)
CONNECTOR_LIB = re.compile(r"connector|usb|jack|header|terminal|barrel|rj45|hdmi|sd_card|microsd", re.I)
MOUNT_LIB = re.compile(r"mountinghole|mounting_hole|mount_hole", re.I)


# ---- plane geometry ------------------------------------------------------------------------------------------------
def rot(p, deg: float, y_down: bool = True):
    """Rotate a footprint-local point by a KiCad angle (counter-clockwise as seen on screen)."""
    a = math.radians(deg or 0.0)
    c, s = math.cos(a), math.sin(a)
    x, y = p
    if y_down:
        return (x * c + y * s, -x * s + y * c)
    return (x * c - y * s, x * s + y * c)


def arc3(a, m, b, step_deg: float = ARC_STEP_DEG) -> list:
    """Points on the circular arc from a through m to b (a and b included)."""
    (ax, ay), (mx, my), (bx, by) = a, m, b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12:
        return [a, b]
    ux = ((ax * ax + ay * ay) * (my - by) + (mx * mx + my * my) * (by - ay) + (bx * bx + by * by) * (ay - my)) / d
    uy = ((ax * ax + ay * ay) * (bx - mx) + (mx * mx + my * my) * (ax - bx) + (bx * bx + by * by) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0, tm, t1 = (math.atan2(p[1] - uy, p[0] - ux) for p in (a, m, b))

    def ccw(t_from, t_to):
        return (t_to - t_from) % (2 * math.pi)
    sweep = ccw(t0, t1)
    if ccw(t0, tm) > sweep:          # the mid point is not on the counter-clockwise way: go clockwise
        sweep -= 2 * math.pi
    n = max(2, int(abs(math.degrees(sweep)) / step_deg) + 1)
    return [(ux + r * math.cos(t0 + sweep * i / n), uy + r * math.sin(t0 + sweep * i / n)) for i in range(n + 1)]


def arc_center(c, start, angle_deg: float, step_deg: float = ARC_STEP_DEG) -> list:
    """Points of an arc given by its centre, start point and swept angle (KiCad 5 gr_arc, IDF loops)."""
    r = math.hypot(start[0] - c[0], start[1] - c[1])
    t0 = math.atan2(start[1] - c[1], start[0] - c[0])
    sw = math.radians(angle_deg)
    n = max(2, int(abs(angle_deg) / step_deg) + 1)
    return [(c[0] + r * math.cos(t0 + sw * i / n), c[1] + r * math.sin(t0 + sw * i / n)) for i in range(n + 1)]


def circle(c, r: float, step_deg: float = ARC_STEP_DEG) -> list:
    n = max(8, int(360 / step_deg))
    return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def area(poly) -> float:
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return s / 2


def bbox(points) -> tuple:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys)), (max(xs), max(ys))


def inside(pt, poly) -> bool:
    x, y = pt
    c = False
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[i - 1]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0 + 1e-300) + x0:
            c = not c
    return c


def chain(polylines: list, tol: float = JOIN_TOL) -> tuple[list, list]:
    """Join open polylines end to end into closed loops: (loops, polylines that could not be closed)."""
    open_ = [list(p) for p in polylines if len(p) >= 2]
    loops, bad = [], []
    close = lambda a, b: abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
    while open_:
        cur = open_.pop(0)
        grew = True
        while grew and not close(cur[0], cur[-1]):
            grew = False
            for i, q in enumerate(open_):
                if close(cur[-1], q[0]):
                    cur += q[1:]
                elif close(cur[-1], q[-1]):
                    cur += list(reversed(q))[1:]
                elif close(cur[0], q[-1]):
                    cur = q[:-1] + cur
                elif close(cur[0], q[0]):
                    cur = list(reversed(q))[:-1] + cur
                else:
                    continue
                open_.pop(i)
                grew = True
                break
        if close(cur[0], cur[-1]) and len(cur) >= 4:
            loops.append(cur[:-1])
        else:
            bad.append(cur)
    return loops, bad


def circle_fit(loop) -> tuple | None:
    """(centre, diameter) when a closed loop is a circle (every point at the same distance from the centroid)."""
    if len(loop) < 8:
        return None
    cx, cy = sum(p[0] for p in loop) / len(loop), sum(p[1] for p in loop) / len(loop)
    rs = [math.hypot(p[0] - cx, p[1] - cy) for p in loop]
    r = sum(rs) / len(rs)
    return ((cx, cy), 2 * r) if r > 0 and max(rs) - min(rs) <= max(0.01, 0.01 * r) else None


def screw_for_hole(d: float) -> str | None:
    """The largest metric screw whose ISO 273 close clearance hole fits a hole of diameter d (a board's mounting
    hole is a clearance hole). None when the hole is smaller than an M2's."""
    from .. import parts
    best = None
    for size, (close, _normal, _loose) in parts.CLEARANCE.items():
        if close <= d + 0.051:
            best = size if best is None or float(size[1:]) > float(best[1:]) else best
    return best


# ---- assembling the board ------------------------------------------------------------------------------------------
def to_frame(pt, origin, y_down: bool):
    x, y = pt
    return (round(x - origin[0], 4), round((origin[1] - y) if y_down else (y - origin[1]), 4))


def finish(raw: dict) -> dict:
    """The raw reading of a board file (source coordinates) as the board model in the board frame.

    raw: {"format", "y_down", "thickness": {...}, "edge_polylines": [...], "edge_loops": [...], "edge_circles":
    [(c, d)], "holes": [{"at", "d", "plated", "ref", "mount"}], "components": [{"ref", "value", "footprint", "side",
    "at", "rot", "courtyard_local": [...] or None, "pads_local": [...], "height": {...} or None}], "keepouts": [...],
    "copper": {...}, "rules": {...}, "notes": [...], "origin": optional [x, y] to reuse}"""
    y_down = raw.get("y_down", True)
    notes = list(raw.get("notes") or [])
    loops, bad = chain(raw.get("edge_polylines") or [])
    loops = [list(lp) for lp in (raw.get("edge_loops") or [])] + loops
    for c, d in raw.get("edge_circles") or []:
        loops.append(circle(c, d / 2))
    if bad:
        notes.append(f"{len(bad)} piece(s) of the board outline do not close into a loop; they are left out.")
    if not loops:
        raise ValueError("No closed board outline was found (Edge.Cuts in KiCad, BOARD_OUTLINE in IDF).")
    loops.sort(key=lambda lp: -abs(area(lp)))
    outer = loops[0]
    (x0, y0), (x1, y1) = bbox(outer)
    origin = raw.get("origin") or [round((x0 + x1) / 2, 4), round((y0 + y1) / 2, 4)]
    f = lambda p: to_frame(p, origin, y_down)
    outline = [f(p) for p in outer]
    if area(outline) < 0:
        outline.reverse()
    holes, cutouts = [], []
    for lp in loops[1:]:
        cf = circle_fit(lp)
        if cf:
            (cx, cy), d = f(cf[0]), cf[1]
            holes.append({"x": cx, "y": cy, "d": round(d, 4), "plated": False, "kind": "edge_cut", "ref": ""})
        else:
            q = [f(p) for p in lp]
            cutouts.append(q[::-1] if area(q) > 0 else q)
    for h in raw.get("holes") or []:
        x, y = f(h["at"])
        holes.append({"x": x, "y": y, "d": round(h["d"], 4), "plated": bool(h.get("plated")),
                      "kind": "mounting" if h.get("mount") else "pad", "ref": h.get("ref", "")})

    comps = []
    for c in raw.get("components") or []:
        at, a = c["at"], c.get("rot") or 0.0
        local = c.get("courtyard_local")
        src = "courtyard"
        if not local:
            local, src = c.get("pads_local") or [], "pads (no courtyard in the footprint)"
        if not local:
            continue
        (lx0, ly0), (lx1, ly1) = bbox(local)
        corners = [(lx0, ly0), (lx1, ly0), (lx1, ly1), (lx0, ly1)]
        world = [(at[0] + q[0], at[1] + q[1]) for q in (rot(p, a, y_down) for p in corners)]
        poly = [f(p) for p in world]
        if area(poly) < 0:
            poly.reverse()
        (bx0, by0), (bx1, by1) = bbox(poly)
        cx, cy = f(at)
        comps.append({"ref": c.get("ref", ""), "value": c.get("value", ""), "footprint": c.get("footprint", ""),
                      "side": c.get("side", "top"), "x": cx, "y": cy, "rot": round(a, 3), "outline": poly,
                      "outline_from": src, "bbox": [[round(bx0, 4), round(by0, 4)], [round(bx1, 4), round(by1, 4)]],
                      "height": c.get("height")})

    w, d = round(x1 - x0, 4), round(y1 - y0, 4)
    if raw.get("origin"):
        notes.append("Placed in the frame of the board's first import, so parts that moved read as moved.")
    board = {"format": raw["format"], "file": raw.get("file", ""), "sha256": raw.get("sha256", ""),
             "generator": raw.get("generator", ""), "version": raw.get("version", ""),
             "thickness": raw["thickness"], "origin": origin, "size": [w, d],
             "frame": "mm; x right, y back (the file's y flipped when it points down), z up from the board's bottom; "
                      "origin at the centre of the outline's bounding box",
             "outline": outline, "cutouts": cutouts, "holes": holes, "components": comps,
             "keepouts": [{**k, "polygon": [f(p) for p in k["polygon"]]} for k in raw.get("keepouts") or []],
             "copper": raw.get("copper") or {}, "rules": raw.get("rules") or {}, "notes": notes}
    board["mounting_holes"] = mounting_holes(board)
    board["connectors"] = connectors(board)
    return board


def mounting_holes(board: dict) -> list:
    """Holes a screw holds the board by: mounting-hole footprints, and non-plated or edge-cut holes of M2 size and up."""
    out = []
    for h in board["holes"]:
        if h["kind"] == "pad" and h["plated"]:
            continue
        if h["kind"] == "pad" and not h["plated"] and h["d"] < 2.1:
            continue
        size = screw_for_hole(h["d"])
        if not size:
            continue
        if any(abs(o["x"] - h["x"]) < 0.05 and abs(o["y"] - h["y"]) < 0.05 for o in out):
            continue
        out.append({"ref": h["ref"], "x": h["x"], "y": h["y"], "d": h["d"], "screw": size,
                    "from": {"mounting": "mounting-hole footprint", "pad": "non-plated hole",
                             "edge_cut": "hole in the board outline (Edge.Cuts)"}[h["kind"]],
                    "screw_source": f"largest screw whose ISO 273 close clearance hole fits Ø{h['d']:g} (computed)"})
    return out


def is_connector(c: dict) -> bool:
    return bool(CONNECTOR_REF.match(c.get("ref") or "")) and bool(
        CONNECTOR_LIB.search(c.get("footprint") or "") or (c.get("ref") or "").upper().startswith(("J", "USB", "CN")))


def plug_for(c: dict, face_w: float, face_h: float | None) -> dict:
    fp = (c.get("footprint") or "") + " " + (c.get("value") or "")
    if re.search(r"usb[_ -]?c|type[_ -]?c|usb_c", fp, re.I):
        return dict(USB_C_PLUG)
    if face_h is None:
        return {"w": round(face_w + 2 * PLUG_MARGIN, 3), "h": None, "provenance": "assumed",
                "source": "the connector's face + 1.5 mm per side (assumed; give the plug's size)"}
    return {"w": round(face_w + 2 * PLUG_MARGIN, 3), "h": round(face_h + 2 * PLUG_MARGIN, 3), "provenance": "assumed",
            "source": "the connector's face + 1.5 mm per side (assumed; measure the plug and give its size)"}


def connector_side(c: dict, board: dict) -> tuple[str, float]:
    """The board edge a connector opens through and how far its courtyard is from that edge (negative: overhangs)."""
    (bx0, by0), (bx1, by1) = c["bbox"]
    (ox0, oy0), (ox1, oy1) = bbox(board["outline"])
    gaps = {"-x": bx0 - ox0, "+x": ox1 - bx1, "-y": by0 - oy0, "+y": oy1 - by1}
    side = min(gaps, key=gaps.get)
    return side, round(gaps[side], 4)


def connectors(board: dict, overrides: dict | None = None) -> list:
    """Each connector with the side it mates from and the face its plug passes through.

    Mating side: the board edge its courtyard is nearest (within EDGE_NEAR mm, overhangs included); a connector
    further in mates from above. overrides: {ref: {"side": "-y" | ... | "up", "plug": [w, h]}} from the person."""
    out = []
    ov = overrides or {}
    for c in board["components"]:
        o = ov.get(c["ref"]) or {}
        if not (is_connector(c) or o):
            continue
        side, gap = connector_side(c, board)
        how = f"computed: its courtyard is {gap:.2f} mm from the {SIDE_NAMES[side]} edge"
        if gap > EDGE_NEAR:
            side, how = "up", f"computed: its courtyard is {gap:.2f} mm from the nearest edge, so it mates from above"
        if o.get("side"):
            side, how = o["side"], "given by the person"
        (bx0, by0), (bx1, by1) = c["bbox"]
        if side in ("-y", "+y"):
            u0, u1 = bx0, bx1
            face = by0 if side == "-y" else by1
        elif side in ("-x", "+x"):
            u0, u1 = by0, by1
            face = bx0 if side == "-x" else bx1
        else:
            u0 = u1 = face = None
        h = (c.get("height") or {}).get("value")
        plug = plug_for(c, (u1 - u0) if u0 is not None else 0.0, h)
        if o.get("plug"):
            plug = {"w": float(o["plug"][0]), "h": float(o["plug"][1]), "provenance": "given",
                    "source": "plug size given by the person"}
        out.append({"ref": c["ref"], "footprint": c["footprint"], "side": side, "side_name": SIDE_NAMES[side],
                    "side_from": how, "board_side": c["side"], "face": face, "u": [u0, u1],
                    "centre_u": None if u0 is None else round((u0 + u1) / 2, 4), "height": c.get("height"),
                    "plug": plug})
    return out


def summary(board: dict) -> dict:
    """A short reading of the board for a reply or the app."""
    top = [c for c in board["components"] if c["side"] == "top"]
    known = [c for c in top if (c.get("height") or {}).get("value") is not None]
    tallest = max(known, key=lambda c: c["height"]["value"]) if known else None
    return {"file": board["file"], "format": board["format"], "size_mm": board["size"],
            "thickness_mm": board["thickness"]["value"], "components": len(board["components"]),
            "heights_known": f"{sum(1 for c in board['components'] if (c.get('height') or {}).get('value') is not None)}"
                             f" of {len(board['components'])}",
            "tallest": ({"ref": tallest["ref"], "height_mm": tallest["height"]["value"],
                         "source": tallest["height"]["source"]} if tallest else None),
            "mounting_holes": [f"{h['ref'] or 'hole'} Ø{h['d']:g} -> {h['screw']}" for h in board["mounting_holes"]],
            "connectors": [f"{c['ref']} {c['side_name']}" for c in board["connectors"]],
            "keepouts": len(board["keepouts"]), "notes": board["notes"]}


def missing_heights(board: dict) -> list:
    return [c["ref"] for c in board["components"] if (c.get("height") or {}).get("value") is None]


def set_heights(board: dict, heights: dict, source: str = "given by the person") -> list:
    """Apply component heights {ref: mm}; returns the refs that are not on the board."""
    unknown = []
    by = {c["ref"]: c for c in board["components"]}
    for ref, h in (heights or {}).items():
        c = by.get(ref)
        if c is None:
            unknown.append(ref)
            continue
        c["height"] = {"value": round(float(h), 4), "source": source,
                       "provenance": "measured" if "measured" in source else "given"}
    board["connectors"] = connectors(board, board.get("connector_overrides"))
    return unknown
