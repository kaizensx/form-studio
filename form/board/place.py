"""Place a board's parts against its enclosure: force-directed placement, then constraints made exact.

What holds a part where it is, or keeps it out of somewhere, comes from the enclosure and the board:

    fixed          a connector that mates through a wall opening stays on its opening; locked footprints; anything
                   the caller names
    keep-outs      the standoff and screw head under and over each mounting hole, the board's own keep-out areas
                   that forbid footprints, areas the caller gives
    height         the room under the lid over the board (less under the lid's lip), and under the board down to the
                   floor; a part whose height is not known is "not checked", never passed
    the outline    every courtyard inside the board edge by a margin
    spacing        courtyards of parts on the same side apart by a gap; a through-hole part takes both sides

How it places

1.  Forces. Each movable part is pulled toward the other pads of its nets (a spring to each net's centroid,
    weaker for nets with many pins), pushed off the parts it overlaps, out of keep-outs and back inside the outline.
    The step shrinks every iteration. No random numbers: the same board places the same way.
2.  Legalising. Largest part first, each is moved to the nearest position on the placement grid where every
    constraint holds (a spiral search), trying the four rotations when that is allowed.
3.  Improving. Each part tries the other rotations and a swap with each part of the same footprint; a move is kept
    when the total wire length (half-perimeter of each net's pads) drops and every constraint still holds.

`check` measures any placement against the same constraints. Everything is computed on courtyard rectangles in
the plane (a rotated courtyard is its bounding rectangle); it is not a 3D fit, which `board_check what="fit"`
measures on the solids.
"""
from __future__ import annotations

import math

from . import geom, model
from .pcb import Pcb

GAP = 0.25            # mm between courtyards (assumed: KiCad's courtyards already carry the assembly margin)
EDGE = 0.5            # mm from a courtyard to the board edge (assumed)
STEP = 0.5            # mm placement grid


def _rect(part: dict, x: float, y: float, rot: float) -> tuple:
    """The courtyard's bounding rectangle at a position and rotation (file coordinates, y down)."""
    x0, y0, x1, y1 = part["box"]
    cs = [model.rot(q, rot) for q in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs, ys = [x + q[0] for q in cs], [y + q[1] for q in cs]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap(a, b, gap: float = 0.0) -> tuple:
    return min(a[2], b[2]) - max(a[0], b[0]) + gap, min(a[3], b[3]) - max(a[1], b[1]) + gap


def _rect_poly(r):
    return [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]


def _rect_hits_poly(r, poly) -> bool:
    rp = _rect_poly(r)
    if any(geom.inside(p, poly) for p in rp) or any(r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3] for p in poly):
        return True
    return any(geom.seg_cross(rp[i], rp[(i + 1) % 4], poly[j], poly[(j + 1) % len(poly)])
               for i in range(4) for j in range(len(poly)))


def _rect_in_poly(r, poly, margin: float) -> bool:
    rp = _rect_poly((r[0] - margin, r[1] - margin, r[2] + margin, r[3] + margin))
    if not all(geom.inside(p, poly) for p in rp):
        return False
    return not any(geom.seg_cross(rp[i], rp[(i + 1) % 4], poly[j], poly[(j + 1) % len(poly)])
                   for i in range(4) for j in range(len(poly)))


def _rect_circle(r, c, rad) -> bool:
    dx = max(r[0] - c[0], 0.0, c[0] - r[2])
    dy = max(r[1] - c[1], 0.0, c[1] - r[3])
    return dx * dx + dy * dy < rad * rad - 1e-12


def parts_of(doc: Pcb) -> list[dict]:
    out = []
    for f in doc.footprints():
        if f["mount"] or not f["box"] or not f["ref"]:
            continue
        h = (f["height"] or {}).get("value")
        out.append({"ref": f["ref"], "lib": f["lib"], "x": f["x"], "y": f["y"], "rot": f["rot"], "side": f["side"],
                    "box": f["box"], "height": h, "tht": f["tht"], "locked": f["locked"],
                    "pads": [((p["local"][0], p["local"][1]), p["net"]) for p in f["pads"] if p["net"] > 0]})
    return out


class Constraints:
    """Everything a placement must respect, in the board file's coordinates."""

    def __init__(self, outline: list, cutouts: list | None = None):
        self.outline, self.cutouts = outline, cutouts or []
        self.fixed: dict[str, str] = {}             # ref -> why
        self.keepouts: list[dict] = []              # {"circle": (c, r)} or {"polygon": [...]}, "side": top|bottom|both, "why"
        self.max_h = {"top": None, "bottom": None}  # mm, or None when not known
        self.max_h_from = {"top": "", "bottom": ""}
        self.zones: list[dict] = []                 # {"polygon", "side", "max_h", "why"}: less room in an area
        self.gap, self.edge = GAP, EDGE
        self.notes: list[str] = []

    def describe(self) -> dict:
        return {"fixed": self.fixed, "keepouts": [{"why": k["why"], "side": k["side"],
                                                   **({"circle": [list(k["circle"][0]), k["circle"][1]]} if "circle" in k
                                                      else {"polygon": [list(p) for p in k["polygon"]]})} for k in self.keepouts],
                "max_height_mm": self.max_h, "max_height_from": self.max_h_from,
                "height_zones": [{"why": z["why"], "side": z["side"], "max_h": z["max_h"]} for z in self.zones],
                "courtyard_gap_mm": self.gap, "edge_margin_mm": self.edge, "notes": self.notes}

    def problems(self, part: dict, rect, others: list) -> list[dict]:
        """Why a part cannot be at rect. others: (ref, rect, side, tht) of the parts already placed."""
        out = []
        # a fixed part is where its opening or its owner put it: a connector may overhang the edge by design
        if part["ref"] not in self.fixed and not _rect_in_poly(rect, self.outline, self.edge):
            out.append({"type": "outside", "text": f"{part['ref']} is not inside the board outline by {self.edge:g} mm"})
        for c in self.cutouts:
            if _rect_hits_poly(rect, c):
                out.append({"type": "cutout", "text": f"{part['ref']} is over a cut-out in the board"})
        sides = ("top", "bottom") if part["tht"] else (part["side"],)
        for k in self.keepouts:
            if k["side"] != "both" and k["side"] not in sides:
                continue
            hit = _rect_circle(rect, *k["circle"]) if "circle" in k else _rect_hits_poly(rect, k["polygon"])
            if hit:
                out.append({"type": "keepout", "text": f"{part['ref']} is in a keep-out: {k['why']}"})
        for ref, r, side, tht in others:
            if ref == part["ref"] or not (tht or part["tht"] or side == part["side"]):
                continue
            ox, oy = _overlap(rect, r, self.gap)
            if ox > 1e-9 and oy > 1e-9:
                out.append({"type": "overlap", "with": ref,
                            "text": f"{part['ref']} and {ref} are closer than {self.gap:g} mm (courtyards)"})
        h = part["height"]
        if h is not None:
            lim, why = self.max_h[part["side"]], self.max_h_from[part["side"]]
            for z in self.zones:
                if z["side"] == part["side"] and _rect_hits_poly(rect, z["polygon"]) and (lim is None or z["max_h"] < lim):
                    lim, why = z["max_h"], z["why"]
            if lim is not None and h > lim + 1e-9:
                out.append({"type": "height", "text": f"{part['ref']} is {h:g} mm tall; there is {lim:g} mm ({why})"})
        return out


def hpwl(parts: list, pos: dict) -> float:
    """Total wire length estimate: the half-perimeter of the box around each net's pads."""
    nets: dict = {}
    for p in parts:
        x, y, r = pos[p["ref"]]
        for (lx, ly), net in p["pads"]:
            q = model.rot((lx, ly), r)
            nets.setdefault(net, []).append((x + q[0], y + q[1]))
    return sum((max(a for a, _ in v) - min(a for a, _ in v)) + (max(b for _, b in v) - min(b for _, b in v))
               for v in nets.values() if len(v) > 1)


def check(doc: Pcb, cons: Constraints, pos: dict | None = None) -> dict:
    """Measure a placement against the constraints (computed on courtyards, in the plane)."""
    parts = parts_of(doc)
    pos = pos or {p["ref"]: (p["x"], p["y"], p["rot"]) for p in parts}
    rects = [(p["ref"], _rect(p, *pos[p["ref"]]), p["side"], p["tht"]) for p in parts]
    rows, seen = [], set()
    for p, (_r, rect, _s, _t) in zip(parts, rects):
        for pr in cons.problems(p, rect, rects):
            key = (pr["type"], tuple(sorted((p["ref"], pr.get("with", "")))))
            if pr["type"] == "overlap" and key in seen:
                continue
            seen.add(key)
            rows.append({"ref": p["ref"], **pr})
    unknown = [p["ref"] for p in parts if p["height"] is None and (cons.max_h[p["side"]] is not None)]
    return {"by": "Form Studio placement check", "evidence": "computed (courtyard rectangles in the plane; not a 3D fit)",
            "rows": rows, "ok": not rows, "parts": len(parts), "height_not_checked": unknown,
            "wire_length_mm": round(hpwl(parts, pos), 3),
            "headline": (f"{len(rows)} placement " + ("finding" if len(rows) == 1 else "findings") if rows else
                         "every part is inside the outline, clear of the keep-outs and of the others") +
                        (f"; {len(unknown)} part(s) without a height are not checked against the lid" if unknown else "")}


def place(doc: Pcb, cons: Constraints, rotate: bool = True, iterations: int = 250, only: list | None = None,
          step: float = STEP) -> dict:
    """Place the movable parts and write their positions into doc. Returns what moved and the check of the result.
    A part that has no legal position is left where it was and reported; it is never put somewhere illegal."""
    parts = parts_of(doc)
    by = {p["ref"]: p for p in parts}
    fixed = dict(cons.fixed)
    for p in parts:
        if p["locked"]:
            fixed.setdefault(p["ref"], "locked in the board file")
        if only is not None and p["ref"] not in only:
            fixed.setdefault(p["ref"], "not among the parts asked for")
    pos = {p["ref"]: (p["x"], p["y"], p["rot"] % 360.0) for p in parts}
    start = dict(pos)
    before = hpwl(parts, pos)
    mov = [p for p in parts if p["ref"] not in fixed]
    xs, ys = [q[0] for q in cons.outline], [q[1] for q in cons.outline]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    diag = math.hypot(bx1 - bx0, by1 - by0)

    def pads_xy(p, st):
        x, y, r = st
        return [(x + q[0], y + q[1], net) for (l, net) in p["pads"] for q in (model.rot(l, r),)]

    # 1. forces
    for it in range(iterations):
        temp = 1.0 - it / iterations
        cent: dict = {}
        for p in parts:
            for x, y, net in pads_xy(p, pos[p["ref"]]):
                c = cent.setdefault(net, [0.0, 0.0, 0])
                c[0] += x
                c[1] += y
                c[2] += 1
        rects = {p["ref"]: _rect(p, *pos[p["ref"]]) for p in parts}
        new = {}
        for p in mov:
            x, y, r = pos[p["ref"]]
            fx = fy = 0.0
            for px, py, net in pads_xy(p, pos[p["ref"]]):         # a spring to the centroid of the net's other pads
                sx, sy, n = cent[net]
                if n > 1:
                    k = 1.0 / math.sqrt(n - 1)
                    fx += k * ((sx - px) / (n - 1) - px)
                    fy += k * ((sy - py) / (n - 1) - py)
            a = rects[p["ref"]]
            for q in parts:
                if q["ref"] == p["ref"] or not (q["tht"] or p["tht"] or q["side"] == p["side"]):
                    continue
                b = rects[q["ref"]]
                ox, oy = _overlap(a, b, cons.gap + 0.3)
                if ox > 0 and oy > 0:
                    w = 2.5 if q["ref"] in fixed else 1.25
                    if ox < oy:
                        fx += w * ox * (1 if (a[0] + a[2]) >= (b[0] + b[2]) else -1)
                    else:
                        fy += w * oy * (1 if (a[1] + a[3]) >= (b[1] + b[3]) else -1)
            for k in cons.keepouts:
                if k["side"] != "both" and k["side"] != p["side"] and not p["tht"]:
                    continue
                if "circle" in k:
                    (kx, ky), rad = k["circle"]
                    if _rect_circle(a, (kx, ky), rad):
                        dx, dy = (a[0] + a[2]) / 2 - kx, (a[1] + a[3]) / 2 - ky
                        d = math.hypot(dx, dy) or 1.0
                        fx += 2.0 * rad * dx / d
                        fy += 2.0 * rad * dy / d
                elif _rect_hits_poly(a, k["polygon"]):
                    kx = sum(q[0] for q in k["polygon"]) / len(k["polygon"])
                    ky = sum(q[1] for q in k["polygon"]) / len(k["polygon"])
                    dx, dy = (a[0] + a[2]) / 2 - kx, (a[1] + a[3]) / 2 - ky
                    d = math.hypot(dx, dy) or 1.0
                    fx += 2.0 * dx / d
                    fy += 2.0 * dy / d
            m = cons.edge
            if a[0] < bx0 + m:
                fx += 2 * (bx0 + m - a[0])
            if a[2] > bx1 - m:
                fx -= 2 * (a[2] - bx1 + m)
            if a[1] < by0 + m:
                fy += 2 * (by0 + m - a[1])
            if a[3] > by1 - m:
                fy -= 2 * (a[3] - by1 + m)
            if not p["pads"]:
                fx += 0.02 * (cx - x)
                fy += 0.02 * (cy - y)
            lim = max(0.05, 0.08 * diag * temp)
            f = math.hypot(fx, fy)
            s = 0.5 * (lim / f if f * 0.5 > lim else 1.0) if f else 0.0
            if f * 0.5 > lim:
                s = lim / f
            new[p["ref"]] = (x + fx * s, y + fy * s, r)
        pos.update(new)

    # 2. legalise
    placed = [(p["ref"], _rect(p, *pos[p["ref"]]), p["side"], p["tht"]) for p in parts if p["ref"] in fixed]
    failed = []
    rots = (0.0, 90.0, 180.0, 270.0)
    nring = int(diag / step) + 2

    def legal(p, x, y, r):
        return not cons.problems(p, _rect(p, x, y, r), placed)
    for p in sorted(mov, key=lambda p: (-(p["box"][2] - p["box"][0]) * (p["box"][3] - p["box"][1]), p["ref"])):
        x0, y0, r0 = pos[p["ref"]]
        gx, gy = round(x0 / step) * step, round(y0 / step) * step
        cand = [r0] + ([(r0 + d) % 360.0 for d in rots[1:]] if rotate else [])
        found = None
        for ring in range(nring):
            best = None
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy)) != ring:
                        continue
                    x, y = gx + dx * step, gy + dy * step
                    if not (bx0 <= x <= bx1 and by0 <= y <= by1):
                        continue
                    for r in cand:
                        if legal(p, x, y, r):
                            d = (math.hypot(x - x0, y - y0), cand.index(r), dx, dy)
                            if best is None or d < best[0]:
                                best = (d, (x, y, r))
                            break
            if best:
                found = best[1]
                break
        if found is None:
            failed.append(p["ref"])
            found = start[p["ref"]]
        pos[p["ref"]] = found
        placed.append((p["ref"], _rect(p, *found), p["side"], p["tht"]))

    # 3. improve: rotations and swaps that shorten the wires and stay legal
    def others(skip):
        return [q for q in placed if q[0] not in skip]

    def setp(ref, st):
        pos[ref] = st
        for i, q in enumerate(placed):
            if q[0] == ref:
                placed[i] = (ref, _rect(by[ref], *st), q[2], q[3])
    good = [p for p in mov if p["ref"] not in failed]
    for _round in range(2):
        changed = False
        cur = hpwl(parts, pos)
        for p in good:
            x, y, r = pos[p["ref"]]
            if rotate:
                for d in rots[1:]:
                    r2 = (r + d) % 360.0
                    if cons.problems(p, _rect(p, x, y, r2), others({p["ref"]})):
                        continue
                    old = pos[p["ref"]]
                    pos[p["ref"]] = (x, y, r2)
                    v = hpwl(parts, pos)
                    if v < cur - 1e-6:
                        cur, changed = v, True
                        setp(p["ref"], (x, y, r2))
                        r = r2
                    else:
                        pos[p["ref"]] = old
            for q in good:
                if q["ref"] <= p["ref"] or q["lib"] != p["lib"] or q["side"] != p["side"]:
                    continue
                a, b = pos[p["ref"]], pos[q["ref"]]
                oth = others({p["ref"], q["ref"]})
                ra, rb = _rect(p, *b), _rect(q, *a)
                if cons.problems(p, ra, oth) or cons.problems(q, rb, oth):
                    continue
                pos[p["ref"]], pos[q["ref"]] = b, a
                v = hpwl(parts, pos)
                if v < cur - 1e-6:
                    cur, changed = v, True
                    setp(p["ref"], b)
                    setp(q["ref"], a)
                else:
                    pos[p["ref"]], pos[q["ref"]] = a, b
        if not changed:
            break

    moved = []
    for p in mov:
        x, y, r = pos[p["ref"]]
        s = start[p["ref"]]
        if abs(x - s[0]) > 1e-6 or abs(y - s[1]) > 1e-6 or abs(r - s[2]) > 1e-6:
            doc.move_footprint(p["ref"], x, y, r)
            moved.append({"ref": p["ref"], "from": [round(s[0], 4), round(s[1], 4), s[2]], "to": [round(x, 4), round(y, 4), r]})
    res = check(doc, cons)
    return {"by": "Form Studio placement", "moved": moved, "fixed": fixed, "not_placed": [
                {"ref": r, "why": "no position on the board meets every constraint; it was left where it was"} for r in failed],
            "wire_length_mm": {"before": round(before, 3), "after": res["wire_length_mm"]},
            "constraints": cons.describe(), "check": res, "complete": not failed and res["ok"]}


# ---- constraints from the enclosure ------------------------------------------------------------------------------------
def constraints(doc: Pcb, board: dict | None = None, layout: dict | None = None, values: dict | None = None,
                fixed: dict | None = None, keepouts: list | None = None, max_height: float | None = None) -> Constraints:
    """The constraints of a board, and of its enclosure when there is one.

    board: the board model (form/board/model.py) for its connectors and mounting holes. layout and values: the
    enclosure's board_layout() and parameter values (the room under the lid, the lip, the standoffs). fixed: {ref:
    why} from the caller. keepouts: [{"polygon": [[x, y], ...] or "circle": [[x, y], r], "side", "why"}] in the
    board file's coordinates. max_height: the room over the board when there is no enclosure to measure."""
    outline, cutouts, notes = doc.edges()
    c = Constraints(outline, cutouts)
    c.notes += notes
    origin = doc.frame_origin()
    F = lambda p: doc.from_frame(p, origin)
    for z in doc.keepouts():
        if z["keepout"].get("footprints") == "not_allowed":
            sides = {"F.Cu": "top", "B.Cu": "bottom"}
            s = {sides[x] for x in z["layers"] if x in sides}
            c.keepouts.append({"polygon": z["polygon"], "side": "both" if len(s) != 1 else s.pop(),
                               "why": f"the board's keep-out area “{z['name'] or 'unnamed'}” forbids footprints"})
    if board:
        for k in board.get("connectors") or []:
            if k["side"] != "up":
                c.fixed[k["ref"]] = (f"it mates through the {k['side_name']} wall" +
                                     (": the enclosure's opening is cut for it there" if layout else ""))
        for h in board.get("mounting_holes") or []:
            try:
                from .. import parts as std
                head_d = float(std.head_dims(h["screw"], "pan")[0])
            except Exception:                            # noqa: BLE001 - the tables are optional here
                head_d = None
            sd = (values or {}).get("standoff_d")
            top_r = (head_d / 2 + 0.5) if head_d else h["d"] / 2 + 1.5
            c.keepouts.append({"circle": (F((h["x"], h["y"])), top_r), "side": "top",
                               "why": f"the head of the {h['screw']} screw in {h['ref'] or 'a mounting hole'} and its driver (" +
                                      ("head diameter from the tables + 0.5 mm" if head_d else "hole radius + 1.5 mm, assumed") + ")"})
            c.keepouts.append({"circle": (F((h["x"], h["y"])), (sd / 2 + 0.3) if sd else h["d"] / 2 + 1.5), "side": "bottom",
                               "why": f"the standoff under {h['ref'] or 'a mounting hole'} (" +
                                      ("its diameter + 0.3 mm" if sd else "hole radius + 1.5 mm, assumed") + ")"})
    if layout and values:
        top = layout["H"] - layout["board_top"]
        c.max_h["top"] = round(top, 4)
        c.max_h_from["top"] = "from the board's top to the underside of the lid"
        thick = layout["board_top"] - layout["board_z"]
        del thick
        bottom = layout["board_z"] - values.get("floor", 0.0)
        c.max_h["bottom"] = round(bottom, 4)
        c.max_h_from["bottom"] = "from the board's underside to the enclosure's floor"
        lip_h = values.get("lip_h", 0.0)
        cav = layout.get("cavity")
        if lip_h and cav and len(cav) >= 4:
            band = values.get("lip_clearance", 0.25) + values.get("lip_wall", 1.6)
            x0, y0, x1, y1 = cav[:4]
            for a in ((x0, y0, x1, y0 + band), (x0, y1 - band, x1, y1), (x0, y0, x0 + band, y1), (x1 - band, y0, x1, y1)):
                c.zones.append({"polygon": [F((a[0], a[1])), F((a[2], a[1])), F((a[2], a[3])), F((a[0], a[3]))],
                                "side": "top", "max_h": round(top - lip_h, 4), "why": "under the lid's lip, along the walls"})
    elif max_height is not None:
        c.max_h["top"] = float(max_height)
        c.max_h_from["top"] = "given by the caller"
    else:
        c.notes.append("No enclosure to measure: part heights are not checked. Give max_height, or place in a design "
                       "that has the board's enclosure.")
    for ref, why in (fixed or {}).items():
        c.fixed[str(ref)] = str(why) or "fixed by the caller"
    for k in keepouts or []:
        side = k.get("side", "both")
        if "circle" in k:
            c.keepouts.append({"circle": (tuple(k["circle"][0]), float(k["circle"][1])), "side": side, "why": k.get("why", "given by the caller")})
        elif "polygon" in k:
            c.keepouts.append({"polygon": [tuple(p) for p in k["polygon"]], "side": side, "why": k.get("why", "given by the caller")})
    return c
