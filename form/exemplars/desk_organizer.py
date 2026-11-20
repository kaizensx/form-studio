"""Desk organizer: one rounded block stepped down from a tall pen cup at the back left to a low clip tray at the front
right, with compartments sized for what goes in them (pens, business cards standing up, small stationery, a phone
leaning in an angled slot, clips), every inside corner filleted and every wall the same thickness. Form Studio exemplar
design."""
import math

from build123d import Align, Axis, Box, Compound, Plane, Pos, Rot

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Stepped desk organizer",
    "category": "consumer",
    "tags": ["desk organizer", "organiser", "desk tidy", "pen holder", "pen cup", "card holder", "business card",
             "phone stand", "phone slot", "tray", "compartments", "stepped", "office", "storage", "consumer"],
    "techniques": ["zones (x, y, height) fused into one block, clipped by a rounded-rectangle plan",
                   "craft.safe_fillet on step corners and top edges after the fuse",
                   "pockets from a zone table: inset wall on outside sides, wall/2 on shared sides",
                   "pocket tools filleted before cutting (inside radius = outside radius - wall at plan corners)",
                   "angled phone slot: a tilted, filleted box cutter", "one Compound cut for all pockets"],
    "lessons": [
        "Lay it out from the objects, then the steps: business cards are 85 x 55 mm (ISO 7810 ID-1 size cards 85.6 x "
        "54) and must stand up with 15-20 mm showing; a phone needs a 12-14 mm slot tilted 12-18 deg back; pens want "
        "a cup about 100 mm tall. Heights step down toward the user so everything stays visible and reachable.",
        "One wall thickness everywhere: a pocket is inset by the full wall on an outside side and by half the wall on "
        "each side of a shared partition, so every partition is exactly one wall thick.",
        "Inside radius = outside radius - wall at the plan corners (a concentric round, the wall stays even); "
        "elsewhere a small inside radius (3-4 mm) that a finger and a cleaning cloth can follow.",
        "Fillet the pocket TOOL (convex edges) before the cut, never the pocket afterwards; and cut every pocket in one "
        "boolean with a Compound, which is faster and avoids a dozen intermediate solids.",
        "Fuse the zones first and round the step edges afterwards on the whole block: rounding each zone before the "
        "fuse leaves grooves where a lower zone meets a taller one.",
    ],
}


class Design(Recipe):
    title, summary = "Desk organizer", ("Rounded block under one sculpted top falling from a pen cup to a clip tray, "
                                        "with card, stationery, phone and tool compartments.")
    params = [
        Param("pen_h", "Height at the pen cup", 105, 92, 130, 1, "mm", "form", "block", "Pens are 140-150 mm long."),
        Param("low_h", "Height of the front row", 34, 30, 42, 0.5, "mm", "form", "block"),
        Param("taper", "Back row falls to the right by", 0.3, 0, 0.38, 0.01, "", "form", "block",
              "Fraction of the rise lost from the left end to the right end."),
        Param("wall", "Wall", 2.4, 1.6, 3.2, 0.1, "mm", "form", "pockets", "Every wall and partition; 2.4 mm is 6 "
              "perimeters of a 0.4 mm nozzle."),
        Param("corner_r", "Plan corner radius", 14, 8, 20, 0.5, "mm", "form", "block"),
        Param("phone_tilt", "Phone slot tilt", 15, 8, 22, 0.5, "deg", "form", "phone"),
        Param("phone_slot", "Phone slot width", 13, 10, 18, 0.5, "mm", "brief", "phone", "Phone thickness with its "
              "case + 2 mm."),
    ]
    features = [Feature("block", "Sculpted block", "structure"), Feature("pockets", "Compartments", "access"),
                Feature("phone", "Phone slot", "access"), Feature("lips", "Rounded lips", "finish"),
                Feature("feet", "Underside relief", "finish")]

    X0, X1, Y0, Y1 = -100.0, 100.0, -55.0, 55.0
    CARD_SHOW = 20.0          # how much of a standing business card shows above the lowest point of its pocket
    CARD_H = 54.0             # ISO 7810 ID-1 short side (business cards 51-55 mm)

    # (name, x0, x1, y0, y1, floor z or None for "cards", bottom radius): the layout everything is derived from.
    # Back row (y > 15): pens, cards standing up, a pencil trough, a tool cup. Front row: a stationery cup, a tray for
    # keys and earbuds, the phone slot, a clip tray.
    ZONES = [("pens", -100, -40, 15, 55, 3, 5), ("cards", -40, 55, 33, 55, None, 4), ("trough", -40, 55, 15, 33, 3, 6),
             ("tools", 55, 100, 15, 55, 3, 5), ("stationery", -100, -40, -55, 15, 3, 6),
             ("tray", -40, 50, -18, 15, 3, 8), ("phone", -40, 50, -55, -18, "solid", 0), ("clips", 50, 100, -55, 15, 3, 9)]
    SLOT_DEPTH, SLOT_Y, SLOT_X = 22.0, -37.0, 5.0

    def constraints(self, v):
        if v["corner_r"] - v["wall"] < 3:
            return [RecipeError("The corner radius leaves no inside round", "pockets", "Increase the corner radius.",
                                ["corner_r", "wall"])]
        if v["pen_h"] * (1 - v["taper"]) < v["low_h"] + 30:
            return [RecipeError("The back row falls to the height of the front row", "block",
                                "Reduce the taper or raise the pen cup.", ["taper", "pen_h", "low_h"])]
        return []

    def _rise(self, y):
        """0 over the front row, 1 over the back row: a cosine S-curve between y = -26 and y = 20."""
        u = min(1.0, max(0.0, (y + 26) / 46))
        return 0.5 - 0.5 * math.cos(math.pi * u)

    def surf(self, v, x, y):
        """Height of the sculpted top at (x, y): the front row level at low_h, an S-curve up to the back row, which
        falls from pen_h at the left end by `taper` of the rise toward the right."""
        k = 1 - v["taper"] * (x - self.X0) / (self.X1 - self.X0)
        return v["low_h"] + (v["pen_h"] - v["low_h"]) * self._rise(y) * k

    def _plan(self, v, h):
        b = Box(self.X1 - self.X0, self.Y1 - self.Y0, h, align=BOTTOM)
        return b.fillet(v["corner_r"], b.edges().filter_by(Axis.Z))

    def _floor(self, v, z):
        name, x0, x1, y0, y1, fz, rb = z
        if fz is None:                               # cards stand on a raised floor and show CARD_SHOW mm
            low = min(self.surf(v, x, y) for x in (x0, x1) for y in (y0, y1))
            return low + self.CARD_SHOW - self.CARD_H
        return fz

    def _pocket(self, v, z):
        """The cutter for zone z: inset by the wall on outside sides, wall/2 on shared sides, rounded concentric with
        the plan at its corners and 3.5 mm elsewhere, filleted at the bottom; it runs up through the top."""
        name, x0, x1, y0, y1, fz, rb = z
        t, R = v["wall"], v["corner_r"]
        fz = self._floor(v, z)
        ins = lambda val, edge: t if abs(val - edge) < 1e-6 else t / 2
        ax0, ax1 = x0 + ins(x0, self.X0), x1 - ins(x1, self.X1)
        ay0, ay1 = y0 + ins(y0, self.Y0), y1 - ins(y1, self.Y1)
        tool = Pos((ax0 + ax1) / 2, (ay0 + ay1) / 2, fz) * Box(ax1 - ax0, ay1 - ay0, v["pen_h"] + 20 - fz, align=BOTTOM)
        corner, inner = [], []
        for e in tool.edges().filter_by(Axis.Z):
            c = e.center()
            at_corner = (abs(c.X - (self.X0 + t)) < 1e-3 or abs(c.X - (self.X1 - t)) < 1e-3) and \
                        (abs(c.Y - (self.Y0 + t)) < 1e-3 or abs(c.Y - (self.Y1 - t)) < 1e-3)
            (corner if at_corner else inner).append(e)
        tool = craft.safe_fillet(tool, inner, 3.5)
        tool = craft.safe_fillet(tool, [e for e in tool.edges() if e.geom_type.name == "LINE" and
                                        abs(e.tangent_at(0.5).Z) > 0.99 and abs(e.center().X - (ax0 if e.center().X < (ax0 + ax1) / 2 else ax1)) < 1e-3
                                        and abs(e.center().Y - (ay0 if e.center().Y < (ay0 + ay1) / 2 else ay1)) < 1e-3], R - t)
        tool = craft.safe_fillet(tool, tool.edges().group_by(Axis.Z)[0], rb)
        return tool

    def build(self, v):
        t = v["wall"]
        # --- snippet: one sculpted top over a rounded plan (a loft through side-view splines, cut from the block)
        xs = [self.X0 - 10 + i * (self.X1 - self.X0 + 20) / 8 for i in range(9)]
        faces = []
        for y in [self.Y0 - 8 + i * (self.Y1 - self.Y0 + 16) / 12 for i in range(13)]:
            line = [(x, self.surf(v, x, y)) for x in xs]
            pts = line + [(xs[-1], v["pen_h"] + 80), (xs[0], v["pen_h"] + 80)]
            faces.append(craft.spline_profile(pts, plane=Plane.XZ.offset(-y)))    # Plane.XZ's normal is -Y
        above = craft.loft_sections(faces)                             # smooth skin through 13 side views
        body = craft.cut(self._plan(v, v["pen_h"] + 30), above)
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[0], 1.0)
        # --- end snippet
        stages = [Stage("block", body)]
        # --- snippet: every compartment from the zone table, cut in one boolean
        tools = [self._pocket(v, z) for z in self.ZONES if z[5] != "solid"]
        body = craft.cut(body, Compound(tools))
        # --- end snippet
        stages.append(Stage("pockets", body))
        # phone slot: a filleted box tilted back (the phone leans on its back wall), its mouth on the level front row
        w, a = v["phone_slot"], v["phone_tilt"]
        depth, yc, xc = self.SLOT_DEPTH, self.SLOT_Y, self.SLOT_X
        zt = v["low_h"]                                                  # the front row is level
        slot = Box(80, w, depth + 40, align=BOTTOM)
        slot = craft.safe_fillet(slot, slot.edges().filter_by(Axis.Z), 4.0)
        slot = craft.safe_fillet(slot, slot.edges().group_by(Axis.Z)[0], min(w / 2 - 0.5, 5.0))
        slot = Pos(xc, yc, zt - depth) * Rot(-a, 0, 0) * slot
        body = craft.cut(body, slot)
        stages.append(Stage("phone", body))
        # lips: every edge of the sculpted top (outer edge, pocket mouths, the phone slot's mouth) rounded to
        # 0.45 x wall from both sides, so each partition ends in a soft, full round; one fillet call for all
        def on_top(e):
            return all(abs(p.Z - self.surf(v, p.X, p.Y)) < 0.4 for p in (e.position_at(0), e.position_at(0.5), e.position_at(1)))
        body = craft.safe_fillet(body, [e for e in body.edges() if on_top(e)], 0.45 * t)
        stages.append(Stage("lips", body))
        # feet: a 0.8 mm relief under the middle, so it stands on its rim and does not rock on an uneven desk
        relief = Pos(0, 0, -0.01) * (self._plan(v, 0.8) & Box(self.X1 - self.X0 - 24, self.Y1 - self.Y0 - 24, 2,
                                                               align=BOTTOM))
        body = craft.cut(body, relief)
        stages.append(Stage("feet", body))
        return parts.checked(stages)

    def appearance(self, v):
        return [{"features": ["block", "pockets", "phone", "lips", "feet"], "finish": "matte", "color": "#d8d2c6"}]

    def derived(self, v):
        t = v["wall"]
        return [{"key": "card_pocket", "label": "Card pocket length", "value": round(95 - t, 1), "unit": "mm",
                 "feature": "pockets", "formula": "zone 95 mm - two half walls; cards 85-89 mm long", "interface": True},
                {"key": "inner_r", "label": "Inside corner radius", "value": round(v["corner_r"] - t, 1), "unit": "mm",
                 "feature": "pockets", "formula": "outside radius - wall (concentric)", "interface": False},
                {"key": "slot_depth", "label": "Phone slot depth", "value": self.SLOT_DEPTH, "unit": "mm",
                 "feature": "phone", "formula": "about a third of a phone's width keeps it upright", "interface": False}]
