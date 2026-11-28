"""The board against its enclosure, measured on the solids (kernel worker only; OCCT is imported inside the ops).

op_board_fit    the enclosure of the head revision and the board as it is now in the project:
                board to wall clearance, standoffs under the mounting holes, each connector's plug envelope swept
                out through the wall, each part against the box and the lid as assembled, and the screwdriver's way
                down to each board screw. Every number is computed on the B-rep; a part with no height is "not
                checked", never a pass.
op_board_step   a board STEP (KiCad's own export): the board's slab and each component's height by the solids over
                its courtyard; also writes the STEP moved into the enclosure's frame for drawing beside the design.
op_board_model  a simple board STEP from the board model (slab and part boxes of known height), for the drawing
                when no board STEP was given.
"""
from __future__ import annotations

DUST = 1e-3            # mm3: below this an overlap is numerical noise
LID_SWEEP = 30.0       # mm a plug envelope is swept out from the connector's face
MIN_GAP = 0.2          # mm: a part or the board closer than this to the enclosure is called touching (WARN)


def _poly_face(pts):
    from build123d import Face, Polyline
    w = Polyline(*[(x, y, 0) for x, y in pts], close=True)
    from build123d import Wire
    return Face(Wire(w.edges()))


def board_solid(board: dict, z0: float):
    """The board's slab: its outline with its holes and cut-outs, board thickness, bottom at z0."""
    from build123d import Circle, Pos, extrude
    t = board["thickness"]["value"]
    f = _poly_face(board["outline"])
    s = Pos(0, 0, z0) * extrude(f, amount=t)
    for h in board["holes"]:
        if h["d"] >= 0.8:
            s = s - Pos(h["x"], h["y"], z0 - 0.1) * extrude(Circle(h["d"] / 2), amount=t + 0.2)
    for c in board["cutouts"]:
        s = s - Pos(0, 0, z0 - 0.1) * extrude(_poly_face(c), amount=t + 0.2)
    return s


def part_solid(c: dict, zb: float, zt: float):
    from build123d import Pos, extrude
    h = (c.get("height") or {}).get("value")
    if not h:
        return None
    z = zt if c["side"] == "top" else zb - h
    return Pos(0, 0, z) * extrude(_poly_face(c["outline"]), amount=h)


def _vol(a, b) -> float:
    try:
        i = a & b
        return float(i.volume) if i is not None and i.solids() else 0.0
    except Exception:                                    # noqa: BLE001
        return float("nan")


def _gap(a, b) -> float:
    try:
        return float(a.distance_to(b))
    except Exception:                                    # noqa: BLE001
        return float("nan")


def _split(shape, split_y: float):
    from build123d import Compound
    box, lid = [], []
    for s in shape.solids():
        (box if s.center().Y > split_y else lid).append(s)
    return (Compound(box) if box else None), (Compound(lid) if lid else None)


def op_board_fit(key, recipe_id, values, board, tol=0.05):
    from build123d import Box, Compound, Cylinder, Pos, Rot, Align
    from ..kernel import _get_near, resolve
    from .. import parts
    shape = _get_near(key, recipe_id, values, tol)["shape"]
    recipe = resolve(recipe_id)
    v = recipe.validate(values)
    if not hasattr(recipe, "board_layout"):
        raise ValueError("This design was not made around a board (it has no board_layout()).")
    lay = recipe.board_layout(v)
    box, lid = _split(shape, lay["split_y"])
    if box is None or lid is None:
        raise ValueError("The design does not have a box and a lid to check.")
    lid_on = Pos(*lay["lid_move"]) * Rot(*lay["lid_rotate"]) * lid
    both = Compound(list(box.solids()) + list(lid_on.solids()))
    zb, zt, H = lay["board_z"], lay["board_top"], lay["H"]
    rows = []

    # 1. the board against the walls and everything else
    slab = board_solid(board, zb)
    over = _vol(slab, both)
    band = box & (Pos(0, 0, zb + 0.05) * Box(1e4, 1e4, max(zt - zb - 0.05, 0.05), align=(Align.CENTER, Align.CENTER, Align.MIN)))
    gap = _gap(slab, band) if band is not None and band.solids() else float("inf")
    st = "FAIL" if over > DUST else "WARN" if gap < MIN_GAP else "PASS"
    rows.append({"id": "board.walls", "label": "Board to enclosure", "status": st,
                 "value": f"{gap:.2f} mm" if gap != float("inf") else "no wall at the board's height",
                 "measured": {"min_gap_mm": round(gap, 4) if gap != float("inf") else None, "overlap_mm3": round(over, 4)},
                 "detail": (f"The board runs into the enclosure: {over:.3f} mm³ of overlap." if over > DUST else
                            f"Smallest gap between the board's edge and a wall: {gap:.2f} mm."),
                 "evidence": "computed (B-rep distance and boolean)"})

    # 2. standoffs under the mounting holes
    sd = float(v.get("standoff_d", 0) or 0)
    from build123d import Vector
    for h in board["mounting_holes"]:
        r = h["d"] / 2 + min(0.6, max(0.2, (sd / 2 - h["d"] / 2) / 2)) if sd else h["d"] / 2 + 0.5
        under = box.is_inside(Vector(h["x"] + r, h["y"], zb - 0.3))
        flush = not box.is_inside(Vector(h["x"] + r, h["y"], zb + 0.1))
        pocket = not box.is_inside(Vector(h["x"], h["y"], zb - 1.0))
        ok = under and flush and pocket
        why = [] if ok else [w for w, bad in (("no material under the hole's ring", not under),
                                               ("material above the board's underside", not flush),
                                               ("no screw pocket under the hole", not pocket)) if bad]
        rows.append({"id": f"board.standoff.{h['ref'] or len(rows)}", "label": f"Standoff under {h['ref'] or 'hole'} ({h['screw']})",
                     "status": "PASS" if ok else "FAIL", "value": "on the hole" if ok else "; ".join(why),
                     "detail": (f"A standoff meets the board's underside at z = {zb:.2f} mm around the Ø{h['d']:g} hole, "
                                "with a pocket for the insert under it." if ok else
                                f"At the hole ({h['x']:.2f}, {h['y']:.2f}): " + "; ".join(why) + "."),
                     "evidence": "computed (B-rep point tests)"})

    # 3. connectors: the plug's envelope swept out from the connector's face through the wall
    for k in board["connectors"]:
        if k["side"] == "up":
            rows.append({"id": f"board.connector.{k['ref']}", "label": f"{k['ref']} plug", "status": "INFO",
                         "value": "mates from above", "detail": f"{k['ref']} {k['side_from']}; the lid is not cut for it.",
                         "evidence": "computed (courtyard to edge distance)"})
            continue
        hgt = (k.get("height") or {}).get("value")
        pl = k["plug"]
        if hgt is None or pl.get("h") is None:
            rows.append({"id": f"board.connector.{k['ref']}", "label": f"{k['ref']} plug", "status": "NOT CHECKED",
                         "value": "height unknown",
                         "detail": f"{k['ref']} has no height in the board file: give it (heights={{\"{k['ref']}\": mm}}) or a board STEP.",
                         "evidence": "not checked"})
            continue
        zc = (zt + hgt / 2) if k["board_side"] == "top" else (zb - hgt / 2)
        w, ph, u, f = pl["w"], pl["h"], k["centre_u"], k["face"]
        if k["side"] in ("-y", "+y"):
            sgn = -1 if k["side"] == "-y" else 1
            env = Pos(u, f + sgn * LID_SWEEP / 2, zc) * Box(w, LID_SWEEP, ph)
            outer = lay["outer"][1] if sgn < 0 else lay["outer"][3]
        else:
            sgn = -1 if k["side"] == "-x" else 1
            env = Pos(f + sgn * LID_SWEEP / 2, u, zc) * Box(LID_SWEEP, w, ph)
            outer = lay["outer"][0] if sgn < 0 else lay["outer"][2]
        ov = _vol(env, both)
        reach = abs(outer - f)
        # the opening itself, in the middle of the wall: open on the connector's axis, wall beside it
        pc = float(v.get("port_clearance", 0.35) or 0)
        mid = (outer + (lay["cavity"][1] if k["side"] == "-y" else lay["cavity"][3] if k["side"] == "+y"
                        else lay["cavity"][0] if k["side"] == "-x" else lay["cavity"][2])) / 2
        side_off = w / 2 + pc + 0.6
        pt = (lambda a, b: Vector(a, mid, b)) if k["side"] in ("-y", "+y") else (lambda a, b: Vector(mid, a, b))
        opening = {"centre_open": not box.is_inside(pt(u, zc)),
                   "wall_beside": [bool(box.is_inside(pt(u - side_off, zc))), bool(box.is_inside(pt(u + side_off, zc)))]}
        rows.append({"id": f"board.connector.{k['ref']}", "label": f"{k['ref']} plug through the {k['side_name']} wall",
                     "status": "FAIL" if ov > DUST else "PASS", "value": (f"{ov:.2f} mm³ in the way" if ov > DUST else "clear"),
                     "measured": {"overlap_mm3": round(ov, 4), "plug_mm": [w, ph], "face_to_outside_mm": round(reach, 3),
                                  "opening": opening},
                     "detail": (f"A {w:g} × {ph:g} mm plug envelope ({pl['source']}) swept {LID_SWEEP:g} mm out from "
                                f"{k['ref']}'s face " + ("hits the enclosure: the opening does not line up with the connector."
                                                         if ov > DUST else "passes the wall without touching.") +
                                f" The plug must reach {reach:.2f} mm from the outer face to the connector's face."),
                     "evidence": "computed (B-rep boolean of the swept plug envelope)" +
                                 ("" if pl.get("provenance") == "specified" else "; the plug size is assumed")})

    # 4. parts on the board against the box and the lid
    unknown = []
    closest = None
    for c in board["components"]:
        s = part_solid(c, zb, zt)
        if s is None:
            unknown.append(c["ref"])
            continue
        ov = _vol(s, both)
        g = _gap(s, lid_on) if c["side"] == "top" else _gap(s, box)
        if closest is None or g < closest[1]:
            closest = (c["ref"], g)
        if ov > DUST or g < MIN_GAP:
            rows.append({"id": f"board.part.{c['ref']}", "label": f"{c['ref']} against the enclosure",
                         "status": "FAIL" if ov > DUST else "WARN",
                         "value": f"{ov:.2f} mm³ overlap" if ov > DUST else f"{g:.2f} mm",
                         "detail": (f"{c['ref']} ({c['height']['value']:g} mm, {c['height']['source']}) "
                                    + ("runs into the box or the lid." if ov > DUST else "nearly touches the lid.")),
                         "evidence": "computed (B-rep boolean and distance)"})
    if closest:
        rows.append({"id": "board.headroom", "label": "Tallest parts to the lid", "status": "PASS" if closest[1] >= MIN_GAP else "WARN",
                     "value": f"{closest[1]:.2f} mm", "measured": {"ref": closest[0], "gap_mm": round(closest[1], 4)},
                     "detail": f"The part closest to the lid (or, under the board, to the floor) is {closest[0]}: {closest[1]:.2f} mm.",
                     "evidence": "computed (B-rep distance)"})
    if unknown:
        rows.append({"id": "board.heights", "label": "Parts without a height", "status": "NOT CHECKED",
                     "value": f"{len(unknown)} parts", "detail": "Not checked against the lid: " + ", ".join(unknown[:20])
                     + ". Give heights (board_import heights=...) or a board STEP.", "evidence": "not checked"})

    # 5. screw access: a screwdriver straight down to each board screw, before the lid goes on
    bodies = [part_solid(c, zb, zt) for c in board["components"]]
    bodies = [b for b in bodies if b is not None]
    for h in board["mounting_holes"]:
        try:
            head_d = parts.head_dims(h["screw"], "pan")[0]
        except Exception:                                # noqa: BLE001
            head_d = 2 * float(h["screw"][1:])
        tool = Pos(h["x"], h["y"], zt + 0.6) * Cylinder(head_d / 2 + 0.5, H + 60 - zt, align=(Align.CENTER, Align.CENTER, Align.MIN))
        hit = [c["ref"] for c, b in zip([c for c in board["components"] if part_solid(c, zb, zt) is not None], bodies)
               if _vol(tool, b) > DUST]
        wall = _vol(tool, box)
        ok = not hit and wall <= DUST
        rows.append({"id": f"board.access.{h['ref'] or 'hole'}", "label": f"Screwdriver to {h['ref'] or 'hole'}",
                     "status": "PASS" if ok else "FAIL",
                     "value": "clear" if ok else ("blocked by " + ", ".join(hit) if hit else "blocked by the box"),
                     "detail": f"A Ø{head_d + 1:.1f} mm path straight down to the {h['screw']} screw head (head Ø{head_d:g} from "
                               "the screw table + 0.5 mm per side, assumed for the driver).",
                     "evidence": "computed (B-rep boolean)"})
    return {"rows": rows, "layout": {k: lay[k] for k in ("board_z", "board_top", "H")}}


def op_board_step(path, board, z0=0.0, out=None):
    """Heights from a board STEP: the board's slab is found (the flat solid as large as the outline), the file is moved
    so the slab's centre is the board frame's origin and its underside at z0, and each component gets the height of
    the solids standing over (or under) its outline."""
    from build123d import Compound, Pos, export_step, import_step
    shp = import_step(str(path))
    sol = list(shp.solids())
    if not sol:
        raise ValueError("The STEP file has no solids.")
    t = board["thickness"]["value"]
    w, d = board["size"]

    def score(s):
        bb = s.bounding_box()
        return abs(bb.size.X - w) + abs(bb.size.Y - d) + 4 * abs(bb.size.Z - t)
    slab = min(sol, key=score)
    bb = slab.bounding_box()
    if score(slab) > 0.1 * (w + d) + 1.0:
        raise ValueError("No solid in the STEP matches the board's outline and thickness: is it this board's export?")
    dx, dy, dz = -(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, z0 - bb.min.Z
    rest = [Pos(dx, dy, dz) * s for s in sol if s is not slab]
    heights = {}
    for c in board["components"]:
        (x0, y0), (x1, y1) = c["bbox"]
        top, bot = None, None
        for s in rest:
            b = s.bounding_box()
            cx, cy = (b.min.X + b.max.X) / 2, (b.min.Y + b.max.Y) / 2
            if x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5:
                if b.max.Z > z0 + t + 0.01:
                    top = max(top or 0.0, b.max.Z - (z0 + t))
                if b.min.Z < z0 - 0.01:
                    bot = max(bot or 0.0, z0 - b.min.Z)
        hh = top if c["side"] == "top" else bot
        if hh:
            heights[c["ref"]] = round(hh, 3)
    if out:
        export_step(Compound([Pos(dx, dy, dz) * slab] + rest), str(out))
    return {"heights": heights, "solids": len(sol), "slab_bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


def op_board_model(board, z0, out):
    """A plain board STEP for the drawing: the slab and a box for each part of known height."""
    from build123d import Compound, export_step
    zt = z0 + board["thickness"]["value"]
    items = [board_solid(board, z0)] + [s for s in (part_solid(c, z0, zt) for c in board["components"]) if s is not None]
    export_step(Compound(items), str(out))
    return {"file": str(out), "parts": len(items) - 1}


KERNEL_OPS = {"board_fit": op_board_fit, "board_step": op_board_step, "board_model": op_board_model}
