"""Pegboard accessory for IKEA SKÅDIS: a hook, a cup, a shelf or tool rack, or a bin, on real SKÅDIS pegs.

SKÅDIS slots are 5 × 15 mm, 40 mm centre to centre across a row and up a column (alternate rows are offset by 20 mm),
in a board about 5 mm thick (IKEA; justhangingpegboards.com). Every accessory hangs on one or more columns of two pegs
40 mm apart: the top peg passes through the board and drops a tab down behind it, the lower peg rests in the slot below
and takes the push of the load. To hang it, tilt it in tab first, lower it, then swing the bottom in.

Print orientation, chosen so nothing needs support:
  hook          on its side, the profile flat on the plate (layers run along the arm, its strongest direction)
  cup/shelf/bin upside down, rim or shelf face on the plate; the pegs' upper faces are 45° ramps and the tabs grow
                upward from them. A part printed the right way up would have to start each tab in mid-air.
"""
from __future__ import annotations

import math

from build123d import (Align, Axis, Box, Cone, Cylinder, Plane, Polygon, Pos, Rectangle, Rot, chamfer, extrude, fillet)

from .base import Feature, Param, Recipe, RecipeError, Stage
from .style import FOOT, rbox

A = (Align.CENTER, Align.CENTER, Align.MIN)
KINDS = {0: "hook", 1: "cup", 2: "shelf", 3: "bin"}
TAB_T = 3.5          # tab thickness behind the board (mm)
TAB_DROP = 4.5       # tab length below the slot's lower edge
TOP_H = 9.5          # top peg height at the back plate, before its 45° ramp
LOW_H = 9.0          # lower peg height at the back plate
LOW_GAP = 0.6        # the lower peg sits this far above its slot's lower edge, so the top peg carries the weight
PLATE_TOP = 2.5      # back plate above the top peg
FLAT = 8.0           # widest flat ceiling left inside an upside-down cup or bin (prints as a short bridge)
SLOPE = 55.0         # floor slopes inside a cup or bin, degrees from horizontal: steeper than 45° so a faceted cone
                     # still prints without support


def floor_height(Ro: float, rb: float, rf: float, Ri: float, hc: float, wall: float) -> float:
    """How high the cup's sloped floor must start so it stays `wall` clear of the rounded outside bottom edge
    (radius rb, centre at (Ro − rb, rb) in the cup's (radius, height) section)."""
    cx, cz = Ro - rb, rb
    z0 = wall
    for _ in range(200):
        worst = min(math.hypot(x - cx, z0 + (x - rf) * hc / max(Ri - rf, 1e-6) - cz) - rb
                    if x > cx and z0 + (x - rf) * hc / max(Ri - rf, 1e-6) < cz else float("inf")
                    for x in [rf + (Ri - rf) * i / 40 for i in range(41)])
        if worst >= wall or rb <= 0:
            return z0
        z0 += 0.1
    return z0


def foot(shape, w: float = 0.3, h: float = 0.5):
    """Chamfer the edges on the print plate, w in and h up: steeper than 45°, so the faceted chamfer round a curved
    edge never reads as an overhang, and it still hides the first layer's flare."""
    z0 = shape.bounding_box().min.Z
    cs = [f.center() for f in shape.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z - z0) < 1e-6
          and f.normal_at().Z < -0.999]
    for c in cs:
        try:
            f = min((f for f in shape.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z - z0) < 1e-6
                     and f.normal_at().Z < -0.999), key=lambda f: (f.center() - c).length)
            shape = chamfer(f.edges(), length=w, length2=h, reference=f)
        except Exception:
            pass
    return shape


def peg_profile(top: bool, T: float, cb: float, y0: float = 0.0) -> list:
    """A peg's side profile in (u, y): u away from the wall (the board's front face at u = 0, the board behind it),
    y up, with y0 the lower edge of the slot it sits in. Upper faces are 45° ramps so it prints upside down."""
    L = T + cb
    if top:
        return [(1.0, y0), (-L, y0), (-L, y0 - TAB_DROP), (-L - TAB_T, y0 - TAB_DROP),
                (-L - TAB_T, y0 + TOP_H - L - TAB_T), (0.0, y0 + TOP_H), (1.0, y0 + TOP_H)]
    Lb = L + 1.0
    y = y0 + LOW_GAP
    return [(1.0, y), (-Lb, y), (-Lb, y + LOW_H - Lb), (0.0, y + LOW_H), (1.0, y + LOW_H)]


class Pegboard(Recipe):
    id = "pegboard"
    title = "SKÅDIS pegboard accessory"
    summary = ("A hook, cup, shelf, tool rack or bin for an IKEA SKÅDIS pegboard, on real SKÅDIS pegs "
               "(5 × 15 mm slots, 40 mm pitch). Prints without supports.")
    category = "Wall & desk"
    tags = ("skadis", "ikea", "pegboard", "hook", "shelf", "cup", "bin", "tools", "workshop", "wall")

    params = [
        Param("kind", "Accessory", 0, 0, 3, 1, "", "form", "plate",
              "0 = hook, 1 = cup (pens, brushes, screwdrivers), 2 = shelf (holes make it a tool rack), 3 = bin."),
        # ---- the board (brief: facts about the pegboard) ----
        Param("board_t", "Board thickness", 5.0, 3.0, 6.0, 0.1, "mm", "brief", "pegs",
              "IKEA SKÅDIS is about 5 mm. Measure it with calipers if your board is another make (3–6 mm).", "specified"),
        Param("slot_w", "Slot width", 5.0, 4.0, 7.0, 0.05, "mm", "brief", "pegs", "SKÅDIS: 5 mm.", "specified"),
        Param("slot_h", "Slot height", 15.0, 12.0, 20.0, 0.1, "mm", "brief", "pegs", "SKÅDIS: 15 mm.", "specified"),
        Param("pitch", "Slot pitch", 40.0, 25.0, 50.0, 0.5, "mm", "brief", "pegs",
              "Centre to centre, across a row and up a column. SKÅDIS: 40 mm.", "specified"),
        # ---- how it meets the board ----
        Param("peg_clear", "Peg clearance / side", 0.3, 0.1, 0.6, 0.05, "mm", "interface", "pegs",
              "Gap each side of a peg in the 5 mm slot."),
        Param("board_clear", "Board clearance", 0.4, 0.2, 1.0, 0.05, "mm", "interface", "pegs",
              "Extra length of the top peg past the board's back face, before the tab drops."),
        # ---- form ----
        Param("columns", "Peg columns", 0, 0, 4, 1, "", "form", "pegs",
              "Columns of pegs, 40 mm apart. 0 = as many as the back plate allows. A hook always has one."),
        Param("plate_t", "Back plate thickness", 4.0, 3.0, 8.0, 0.1, "mm", "form", "plate"),
        Param("reach", "Hook reach", 40, 20, 100, 0.5, "mm", "form", "arm", "Hook: from the board face to the tip."),
        Param("arm_t", "Hook arm depth", 9, 5, 20, 0.5, "mm", "form", "arm", "Hook: strength grows with its square."),
        Param("tip_h", "Hook tip height", 12, 5, 40, 0.5, "mm", "form", "tip", "Hook: how far the tip rises above the arm."),
        Param("cup_d", "Cup inner diameter", 40, 15, 80, 0.5, "mm", "brief", "cup", "Cup: what has to fit in it."),
        Param("width", "Width", 80, 30, 160, 0.5, "mm", "brief", "shelf", "Shelf and bin: along the board."),
        Param("depth", "Depth", 50, 15, 120, 0.5, "mm", "brief", "shelf", "Shelf and bin: out from the board."),
        Param("height", "Height", 60, 20, 120, 0.5, "mm", "brief", "cavity", "Cup and bin: outside height."),
        Param("wall", "Wall", 1.6, 1.3, 4.0, 0.1, "mm", "form", "cavity", "Cup and bin walls; four lines at 1.6 mm."),
        Param("shelf_t", "Shelf thickness", 4.0, 2.4, 10, 0.1, "mm", "form", "shelf"),
        Param("holes", "Tool holes", 0, 0, 12, 1, "", "form", "holes",
              "Shelf: a row of round holes for screwdrivers, pliers or brushes. 0 = a plain shelf."),
        Param("hole_d", "Tool hole diameter", 10, 3, 30, 0.5, "mm", "brief", "holes", "Measure the shank it holds."),
        Param("corner_r", "Corner radius", 4, 1, 12, 0.5, "mm", "form", "plate"),
        # ---- load model ----
        Param("load_kg", "Load", 1.0, 0.1, 10, 0.1, "kg", "brief", "pegs", "Heaviest thing it will hold."),
        Param("strength_mpa", "Material strength", 40, 10, 120, 1, "MPa", "process", "pegs",
              "Assumed flexural strength of the printed material (PLA is often quoted at 40–60 MPa)."),
        Param("layer_factor", "Layer-adhesion factor", 0.5, 0.1, 1.0, 0.05, "", "process", "pegs",
              "Fraction of the strength trusted across layer lines (cup, shelf and bin tabs load across them)."),
    ]
    features = [
        Feature("plate", "Back plate", "structure"),
        Feature("pegs", "SKÅDIS pegs", "interface", "Top peg with a tab behind the board; lower peg resting in the slot below."),
        Feature("arm", "Hook arm", "structure"),
        Feature("tip", "Hook tip", "access", "Keeps what hangs from sliding off."),
        Feature("cup", "Cup", "structure"),
        Feature("shelf", "Shelf", "structure"),
        Feature("gussets", "Gussets", "structure"),
        Feature("cavity", "Cavity", "access", "45° floor slopes inside: it prints upside down without support."),
        Feature("holes", "Tool holes", "access"),
        Feature("soften", "Edges", "finish", "45° chamfers on the plate side, soft top edges."),
    ]

    # ---- helpers ------------------------------------------------------------------------------------------------
    @staticmethod
    def k(v) -> str:
        return KINDS[int(round(v["kind"]))]

    def g(self, v) -> dict:
        kind = self.k(v)
        P, p = v["plate_t"], v["pitch"]
        peg_w = v["slot_w"] - 2 * v["peg_clear"]
        top = TOP_H + PLATE_TOP                                # back plate top, above the top slot's lower edge
        bot = -p + LOW_GAP - 3.0                               # back plate bottom, below the lower peg
        if kind == "cup":
            Ro = v["cup_d"] / 2 + v["wall"]
            W = max(2 * Ro, peg_w + 12)
            bot = min(bot, top - v["height"])
        elif kind == "hook":
            W = peg_w
        else:
            W = v["width"]
            if kind == "bin":
                bot = min(bot, top - v["height"])
        n = int(round(v["columns"]))
        fit_n = max(1, int((W - peg_w - 8) // p) + 1)
        n = 1 if kind == "hook" else (fit_n if n == 0 else n)
        xs = [(i - (n - 1) / 2) * p for i in range(n)]
        return {"kind": kind, "P": P, "peg_w": peg_w, "top": top, "bot": bot, "W": W, "n": n, "fit_n": fit_n,
                "xs": xs, "stub": v["board_t"] + v["board_clear"]}

    def constraints(self, v):
        out = []
        for key in ("kind", "columns", "holes"):
            if abs(v[key] - round(v[key])) > 1e-9:
                out.append(RecipeError(f"{self.spec(key).label} must be a whole number", self.spec(key).feature,
                                       "Use a whole number.", [key]))
        if out:
            return out
        g = self.g(v)
        if TOP_H + TAB_DROP > v["slot_h"] - 0.8:
            out.append(RecipeError(f"The top peg and its tab are {TOP_H + TAB_DROP:.1f} mm tall; the slot is {v['slot_h']:g} mm",
                                   "pegs", "This board's slots are too short for SKÅDIS pegs.", ["slot_h"]))
        if g["peg_w"] < 3.0:
            out.append(RecipeError(f"Pegs would be {g['peg_w']:.1f} mm wide; under 3 mm they bend", "pegs",
                                   "Reduce the peg clearance.", ["peg_clear", "slot_w"]))
        if g["n"] > g["fit_n"]:
            out.append(RecipeError(f"{g['n']} peg columns need {g['peg_w'] + 8 + (g['n'] - 1) * v['pitch']:.0f} mm; "
                                   f"the back plate is {g['W']:.0f} mm wide", "pegs",
                                   "Use fewer columns (0 = as many as fit), or widen the accessory.", ["columns", "width"]))
        k = g["kind"]
        if k == "hook":
            P = max(g["P"], v["arm_t"] * 0.8)
            tip_t = max(5.0, v["arm_t"] * 0.7)
            if v["reach"] - P - tip_t < 8:
                out.append(RecipeError(f"The hook leaves {v['reach'] - P - tip_t:.0f} mm between plate and tip", "arm",
                                       f"Lengthen the reach to at least {P + tip_t + 8:.0f} mm, or thin the arm.", ["reach", "arm_t"]))
            if v["tip_h"] + v["arm_t"] > 60:
                out.append(RecipeError("The hook tip rises over 60 mm", "tip", "Lower the tip.", ["tip_h"]))
        if k == "cup":
            Ri = v["cup_d"] / 2
            need = v["wall"] + max(0.0, Ri - FLAT / 2) + 8
            if v["height"] < need:
                out.append(RecipeError(f"A {v['cup_d']:g} mm cup needs to be at least {need:.0f} mm tall for its 45° floor",
                                       "cavity", "Make it taller or narrower.", ["height", "cup_d"]))
        if k == "bin":
            di = v["depth"] - 2 * v["wall"]
            need = v["wall"] + max(0.0, (di - FLAT) / 2) + 8
            if v["height"] < need:
                out.append(RecipeError(f"A {v['depth']:g} mm deep bin needs to be at least {need:.0f} mm tall for its 45° floor",
                                       "cavity", "Make it taller or shallower.", ["height", "depth"]))
            if v["width"] < 2 * v["wall"] + 12:
                out.append(RecipeError("The bin is too narrow", "cavity", "Widen it.", ["width"]))
        if k == "shelf" and v["holes"] > 0:
            n, d = int(v["holes"]), v["hole_d"]
            if n * d + (n + 1) * 3 > v["width"] - 2 * (3.2 + 4):
                out.append(RecipeError(f"{n} holes of {d:g} mm do not fit across {v['width']:g} mm with 3 mm between them",
                                       "holes", "Use fewer or smaller holes, or widen the shelf.", ["holes", "hole_d", "width"]))
            if d + 6 > v["depth"]:
                out.append(RecipeError("The tool holes are deeper than the shelf", "holes", "Deepen the shelf or use smaller holes.",
                                       ["hole_d", "depth"]))
        if v["corner_r"] * 2 >= min(g["W"], g["top"] - g["bot"]) and k != "hook":
            out.append(RecipeError("Corner radius is larger than the back plate", "plate", "Reduce the corner radius.", ["corner_r"]))
        return out

    # ---- geometry -----------------------------------------------------------------------------------------------
    def _pegs_use(self, v, g):
        """Peg columns in the use frame: X along the board, Y away from the wall (board front at 0), Z up."""
        out = None
        for x in g["xs"]:
            for top, y0 in ((True, 0.0), (False, -v["pitch"])):
                prof = Plane.YZ * Polygon(*peg_profile(top, v["board_t"], v["board_clear"], y0), align=None)
                s = Pos(x, 0, 0) * extrude(prof, g["peg_w"] / 2, both=True)
                out = s if out is None else out + s
        return out

    def _hook(self, v, g):
        """Built straight in the print frame: X away from the wall, Y up, Z across (the profile lies on the plate)."""
        t = g["peg_w"]
        P = max(g["P"], v["arm_t"] * 0.8)                      # in the profile the plate is a spine as deep as the arm
        bot = -v["pitch"] + LOW_GAP - 3.0 - v["arm_t"] * 0.6
        plate = Pos(P / 2, (g["top"] + bot) / 2) * Rectangle(P, g["top"] - bot)
        plate = fillet(plate.vertices().group_by(Axis.Y)[-1], min(P / 2 - 0.05, 3.0))     # round the top of the spine
        stages = [Stage("plate", extrude(plate, t))]
        yb = bot
        tip_t = max(5.0, v["arm_t"] * 0.7)
        arm = Pos(v["reach"] / 2, yb + v["arm_t"] / 2) * Rectangle(v["reach"], v["arm_t"])
        tip = Pos(v["reach"] - tip_t / 2, yb + (v["arm_t"] + v["tip_h"]) / 2) * Rectangle(tip_t, v["arm_t"] + v["tip_h"])
        prof = plate + arm
        free = v["reach"] - P - tip_t                           # flat top of the arm, before fillets
        root = min(free * 0.6, v["arm_t"] * 1.2, 10)
        concave = [p for p in prof.vertices() if abs(p.X - P) < 1e-6 and abs(p.Y - (yb + v["arm_t"])) < 1e-6]
        if root > 0.5 and concave:
            prof = fillet(concave, root)
        stages.append(Stage("arm", extrude(prof, t)))
        prof = prof + tip
        # soft outer corners: under the arm, and a full round on the tip
        r_out = min(tip_t / 2 - 0.1, v["arm_t"] / 2 - 0.1, 4.0)
        outer = [p for p in prof.vertices() if abs(p.Y - yb) < 1e-6 or abs(p.Y - (yb + v["arm_t"] + v["tip_h"])) < 1e-6]
        prof = fillet(outer, r_out)
        r_in = min(3.0, v["tip_h"] - r_out - 0.2, free * 0.3)
        inner = [p for p in prof.vertices() if abs(p.X - (v["reach"] - tip_t)) < 1e-6 and abs(p.Y - (yb + v["arm_t"])) < 1e-6]
        if inner and r_in > 0.3:
            prof = fillet(inner, r_in)
        s = extrude(prof, t)
        stages.append(Stage("tip", s))
        for top, y0 in ((True, 0.0), (False, -v["pitch"])):
            s = s + extrude(Polygon(*peg_profile(top, v["board_t"], v["board_clear"], y0), align=None), t, dir=(0, 0, 1))
        stages.append(Stage("pegs", s))
        s = foot(s)
        try:
            s = chamfer(s.edges().group_by(Axis.Z)[-1], 0.6)
        except Exception:
            pass
        stages.append(Stage("soften", s))
        return stages

    def _plate_use(self, v, g):
        """The back plate in the use frame: soft lower corners; the upper edge stands on the print plate, so it stays square."""
        P, W, top, bot = g["P"], g["W"], g["top"], g["bot"]
        H = top - bot
        b = Pos(0, 0, bot) * Box(W, P, H, align=(Align.CENTER, Align.MIN, Align.MIN))
        if g["kind"] == "bin" and v["height"] >= H - 1e-6:
            return b                                           # the bin's own rounded bottom edge finishes it
        r = min(v["corner_r"], W / 2 - 0.1, H / 2 - 0.1)
        ys = b.edges().filter_by(Axis.Y)
        return fillet([e for e in ys if e.center().Z < bot + 1e-6], r)

    def _upside_down(self, v, g):
        k, P, W = g["kind"], g["P"], g["W"]
        top, bot = g["top"], g["bot"]
        H = top - bot
        s = self._plate_use(v, g)
        stages = [Stage("plate", s)]
        rise = math.tan(math.radians(SLOPE))
        if k == "cup":
            Ri = v["cup_d"] / 2
            Ro = Ri + v["wall"]
            cy = P + Ri + max(0.0, v["wall"] - P)               # the cup's back wall merges into the plate
            zb = top - v["height"]
            body = Pos(0, cy, zb) * Cylinder(Ro, v["height"], align=A)
            rb = min(Ro - 1, v["height"] / 3, 8)
            try:
                body = fillet(body.edges().group_by(Axis.Z)[0], rb)
            except Exception:
                rb = 0.0
            s = s + body
            stages.append(Stage("cup", s))
            rf = min(FLAT / 2, Ri - 0.5)
            hc = (Ri - rf) * rise
            zf = zb + floor_height(Ro, rb, rf, Ri, hc, v["wall"])
            cav = Pos(0, cy, zf) * Cone(rf, Ri, hc, align=A) + Pos(0, cy, zf + hc) * Cylinder(Ri, top - zf - hc + 1, align=A)
            s = s - cav
            stages.append(Stage("cavity", s))
        elif k == "bin":
            D = v["depth"]
            zb = top - v["height"]
            wi, di = W - 2 * v["wall"], D - v["wall"]            # the back plate is the bin's back wall
            c = max(0.0, (di - FLAT) / 2)
            rb = min(v["corner_r"] + 2, W / 2 - 0.1, D / 2 - 0.1)
            ri = min(max(0.5, rb - v["wall"]), max(0.5, c * 0.9), di / 3, wi / 2 - 0.1)
            rb = min(rb, ri + v["wall"])                         # inner and outer corners concentric: an even wall
            body = Box(W, D + P / 2, v["height"], align=(Align.CENTER, Align.MIN, Align.MIN))
            body = fillet([e for e in body.edges().filter_by(Axis.Z) if e.center().Y > 1], rb)
            s = s + Pos(0, P / 2, zb) * body
            rbb = min(3.0, v["height"] / 4, 2 * v["wall"])
            try:                                               # a soft bottom edge (it is the top as printed)
                es = [e for e in s.edges() if abs(e.center().Z - zb) < 1e-6 and e.bounding_box().size.Z < 1e-6
                      and (zb <= bot + 1e-6 or e.center().Y > P + 0.1)]
                t_ = fillet(es, rbb)
                s = t_ if t_.is_valid else s
            except Exception:
                pass
            stages.append(Stage("cup", s))
            # the floor clears the rounded bottom edge by a wall everywhere: at the ends that means at least its radius
            zf = zb + max(v["wall"], rbb, floor_height(di / 2 + v["wall"], rbb, FLAT / 2, di / 2, c * rise, v["wall"]))
            yc = P + di / 2
            hz = top - zf + 1
            prof = Plane.YZ * Polygon((-di / 2 + c, 0), (di / 2 - c, 0), (di / 2, c * rise), (di / 2, hz),
                                       (-di / 2, hz), (-di / 2, c * rise), align=None)
            cav = Pos(0, yc, zf) * extrude(prof, wi / 2, both=True)
            try:                                               # round the cavity's front corners, down to the slopes
                fr = [e for e in cav.edges().filter_by(Axis.Z) if e.center().Y > yc + 1]
                t_ = fillet(fr, ri)
                cav = t_ if t_.is_valid else cav
            except Exception:
                pass
            s = s - cav
            stages.append(Stage("cavity", s))
        else:                                                  # shelf (or tool rack) at the top of the back plate
            D, st = v["depth"], v["shelf_t"]
            rs = min(v["corner_r"] + 2, W / 2 - 0.1, D / 2 - 0.1)
            shelf = Box(W, D + P / 2, st, align=(Align.CENTER, Align.MIN, Align.MIN))
            shelf = fillet([e for e in shelf.edges().filter_by(Axis.Z) if e.center().Y > 1], rs)
            s = s + Pos(0, P / 2, top - st) * shelf
            stages.append(Stage("shelf", s))
            gt = 3.2
            gd = min(D * 0.7, H - st - 4)
            for sx in (-1, 1):
                x = sx * (W / 2 - gt / 2 - 2)
                tri = Plane.YZ * Polygon((P - 0.5, top - st + 0.5), (P + gd, top - st + 0.5), (P - 0.5, top - st - gd), align=None)
                s = s + Pos(x, 0, 0) * extrude(tri, gt / 2, both=True)
            stages.append(Stage("gussets", s))
            n = int(round(v["holes"]))
            if n:
                d = v["hole_d"]
                yc = P + D / 2 + 1
                span = W - 2 * (gt + 4)                        # clear of the gussets under the ends
                step = span / n
                for i in range(n):
                    x = -span / 2 + step * (i + 0.5)
                    s = s - Pos(x, yc, top - st - 1) * Cylinder(d / 2, st + 2, align=A)
                stages.append(Stage("holes", s))
        s = s + self._pegs_use(v, g)
        stages.append(Stage("pegs", s))
        # to the print frame: upside down, the rim / shelf face on the plate
        T = Pos(0, 0, top) * Rot(0, 180, 0)
        stages = [Stage(st_.feature, T * st_.shape) for st_ in stages]
        stages.append(Stage("soften", foot(stages[-1].shape)))
        return stages

    def build(self, v):
        g = self.g(v)
        return self._hook(v, g) if g["kind"] == "hook" else self._upside_down(v, g)

    # ---- interfaces ---------------------------------------------------------------------------------------------
    def derived(self, v):
        g = self.g(v)
        out = [{"key": "peg_w", "label": "Peg width", "value": g["peg_w"], "unit": "mm", "feature": "pegs",
                "formula": "slot width − 2 × clearance", "interface": True},
               {"key": "stub", "label": "Top peg reach behind the board face", "value": g["stub"], "unit": "mm",
                "feature": "pegs", "formula": "board thickness + board clearance", "interface": True},
               {"key": "columns_n", "label": "Peg columns", "value": g["n"], "unit": "", "feature": "pegs",
                "formula": "as set, or as many 40 mm columns as the plate allows", "interface": False}]
        if g["kind"] in ("cup", "bin"):
            out.append({"key": "bridge_span", "label": "Floor bridge (printed upside down)", "value": FLAT, "unit": "mm",
                        "feature": "cavity", "formula": "flat left between the 45° floor slopes", "interface": False})
        return out

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        faces = [f for f in faces_by_feature.get("pegs", []) if f.geom_type.name == "PLANE"]
        if not faces:
            return []
        out = []
        if g["kind"] == "hook":                                # the peg width is the whole profile's thickness
            zs = [f.center().Z for fs in faces_by_feature.values() for f in fs if f.geom_type.name == "PLANE"
                  and abs(abs(f.normal_at().Z) - 1) < 1e-6]
            out.append({"key": "peg_w", "label": "Peg width", "intended": g["peg_w"], "modelled": max(zs) - min(zs)})
            ax = 0                                             # the wall is towards −X in the print frame
        else:
            xs = sorted((f.center().X, round(f.normal_at().X)) for f in faces if abs(abs(f.normal_at().X) - 1) < 1e-6)
            ws = [b[0] - a[0] for a, b in zip(xs, xs[1:]) if a[1] != b[1]]
            if ws:
                out.append({"key": "peg_w", "label": "Peg width", "intended": g["peg_w"], "modelled": min(ws)})
            ax = 1
        # the tab's face towards the board, against the plate's face on the board
        tab = [tuple(f.center())[ax] for f in faces if abs(tuple(f.normal_at())[ax] - 1) < 1e-6]
        back = [tuple(f.center())[ax] for f in faces_by_feature.get("plate", []) + faces
                if f.geom_type.name == "PLANE" and abs(tuple(f.normal_at())[ax] + 1) < 1e-6]
        if tab and back:
            u0 = max(b for b in back if b > min(tab))
            out.append({"key": "stub", "label": "Top peg reach behind the board face", "intended": g["stub"],
                        "modelled": u0 - max(t for t in tab if t < u0)})
        return out

    # ---- load model ---------------------------------------------------------------------------------------------
    def statics(self, v, solid_volume_mm3, com):
        g = self.g(v)
        F = v["load_kg"] * 9.81
        k, P = g["kind"], g["P"]
        if k == "hook":
            lever = v["reach"] - max(5.0, v["arm_t"] * 0.7) / 2
        elif k == "cup":
            lever = P + v["cup_d"] / 2 + v["wall"]
        else:
            lever = P + v["depth"] / 2
        M = F * lever
        F_tab = M / v["pitch"] / g["n"]                        # the top tab and the lower contact form a couple
        arm = TAB_DROP / 2 + 1.0
        s_tab = 6 * F_tab * arm / (g["peg_w"] * TAB_T ** 2)
        across = k != "hook"                                    # printed upside down, the tab bends across its layers
        allow_tab = v["strength_mpa"] * (v["layer_factor"] if across else 0.8)
        sf_tab = allow_tab / s_tab if s_tab > 0 else float("inf")
        st = lambda sf: "PASS" if sf >= 2 else ("WARN" if sf >= 1.2 else "FAIL")
        checks = [{"id": "peg_tab", "label": "Peg tab safety factor", "status": st(sf_tab), "value": f"{sf_tab:.1f}×",
                   "detail": f"{F:.0f} N at {lever:.0f} mm from the board makes a {M / 1000:.2f} N·m moment, taken as a couple "
                             f"between the top tab and the lower peg {v['pitch']:g} mm below: {F_tab:.0f} N on each of {g['n']} "
                             f"tab(s), {s_tab:.1f} MPa in bending against {allow_tab:.0f} MPa allowed "
                             + (f"({v['strength_mpa']:.0f} MPa × {v['layer_factor']:.2f} across layers, both assumed)."
                                if across else f"({v['strength_mpa']:.0f} MPa × 0.8 along the layers, assumed).")
                             + " A beam estimate, not a load rating. Target ≥ 2×.",
                   "evidence": "model", "feature": "pegs"}]
        out = {"tab_safety_factor": sf_tab, "moment_nmm": M}
        if k == "hook":
            L = v["reach"] - P
            sig = 6 * F * L / (g["peg_w"] * v["arm_t"] ** 2)
            allow = v["strength_mpa"] * 0.8
            sf = allow / sig if sig > 0 else float("inf")
            out["safety_factor"] = min(sf, sf_tab)
            checks.insert(0, {"id": "strength", "label": "Hook arm safety factor", "status": st(sf), "value": f"{sf:.1f}×",
                              "detail": f"Cantilever: {F:.0f} N at {L:.0f} mm on a {g['peg_w']:.1f} × {v['arm_t']:g} mm arm gives "
                                        f"{sig:.1f} MPa at the root against {allow:.0f} MPa ({v['strength_mpa']:.0f} MPa × 0.8; "
                                        "printed on its side, the arm bends along its layers). Ignores the root fillet. Target ≥ 2×.",
                              "evidence": "model", "feature": "arm"})
        else:
            out["safety_factor"] = sf_tab
        out["checks"] = checks
        return out
