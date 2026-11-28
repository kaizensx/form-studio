"""Hinged box, made by Form Studio's hinge_box generator: a box and a lid printed open, side by side and rim up, in one
piece: a print-in-place pin hinge joins them along the back and a cantilever snap latch closes them. The hinge
clearance is the one parameter that decides whether the hinge turns or fuses: the generator takes it from the fit
model (0.35 mm per side, moved by the measured bias of a calibrated printer) and records where it came from.
Adapted from Form Studio's hinged_case exemplar."""
from build123d import Align, Axis, Box, Plane, Pos, Rot, Wire, extrude, make_face

from form import craft, parts
from form.recipes.base import Assembly, Param, Feature, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

MAKE = {
    "generator": "hinge_box",
}


class Design(Recipe):
    title, summary = "Hinged box", "A box and a lid printed open in one piece, joined by a pin hinge, closed by a snap latch."
    category, tags = "Makers", ("box", "hinge", "print-in-place")
    solids = 2
    params = [
        Param("inner_w", "Inner width", 80, 40, 160, 1, "mm", "brief", "base", "Along the hinge."),
        Param("inner_d", "Inner depth", 52, 30, 120, 1, "mm", "brief", "base"),
        Param("half_h", "Height of each half", 16, 10, 40, 0.5, "mm", "form", "base", "The case closes to twice this."),
        Param("wall", "Wall", 2.0, 1.2, 4, 0.1, "mm", "form", "base"),
        Param("corner_r", "Corner radius", 6, 2, 15, 0.5, "mm", "form", "base"),
        Param("clearance", "Hinge clearance / side", 0.35, 0.2, 0.6, 0.01, "mm", "interface", "hinge",
              "Radial and axial room in the print-in-place hinge. The generator sets it from the fit model: 0.35 mm "
              "moved by the printer's measured bias when the printer is calibrated."),
        Param("latch_undercut", "Latch undercut", 0.9, 0.4, 1.6, 0.05, "mm", "interface", "latch"),
    ]
    features = [Feature("base", "Base", "structure"), Feature("lid", "Lid", "structure"),
                Feature("hinge", "Pin hinge", "interface"), Feature("latch", "Snap latch", "interface"),
                Feature("catch", "Latch catch", "interface")]

    def constraints(self, v):
        if v["corner_r"] >= min(v["inner_w"], v["inner_d"]) / 2:
            return [RecipeError("Corner radius is larger than the case", "base", "Reduce the corner radius.", ["corner_r"])]
        return []

    def _dims(self, v):
        W, D, t = v["inner_w"] + 2 * v["wall"], v["inner_d"] + 2 * v["wall"], v["wall"]
        Hb = Hl = v["half_h"]                       # equal halves: the barrel stands above both rims
        R = 4.0                                     # knuckle radius
        gap = R + 0.8
        h = (Hb + Hl) / 2
        return W, D, t, Hb, Hl, R, gap, h

    def _tray(self, W, D, H, t, r, y0):
        """An open-topped rounded tray standing on z = 0, spanning y0 to y0 + D (y0 > 0) or y0 - D to y0 (y0 < 0)."""
        yc = y0 + D / 2 if y0 > 0 else y0 - D / 2
        outer = Box(W, D, H, align=BOTTOM)
        outer = craft.safe_fillet(outer, outer.edges().filter_by(Axis.Z), r)
        outer = craft.safe_fillet(outer, outer.edges().group_by(Axis.Z)[0], 1.5)
        inner = Pos(0, 0, t) * Box(W - 2 * t, D - 2 * t, H, align=BOTTOM)
        inner = craft.safe_fillet(inner, inner.edges().filter_by(Axis.Z), max(r - t, 0.5))
        return Pos(0, yc, 0) * (outer - inner)

    def build(self, v):
        W, D, t, Hb, Hl, R, gap, h = self._dims(v)
        base = self._tray(W, D, Hb, t, v["corner_r"], -gap)
        stages = [Stage("base", base)]
        lid = self._tray(W, D, Hl, t, v["corner_r"], gap)
        body = base + lid
        stages.append(Stage("lid", body))
        # hinge: knuckles between the halves at height h, leaves reaching into both back walls
        hl = W - 2 * v["corner_r"] - 4
        hg = craft.pin_hinge(length=hl, outer_d=2 * R, pin_d=2.6, knuckles=5, clearance=v["clearance"],
                             leaf_w=gap + t * 0.8, leaf_t=2.4)
        lift = Pos(0, 0, h - R)
        a, b = lift * hg.shapes["leaf_a"], lift * hg.shapes["leaf_b"]
        base_side = base + a                        # leaf A (y < 0) joins the base
        lid_side = lid + b
        body = base_side + lid_side
        stages.append(Stage("hinge", body))
        # latch: a cantilever hook on the lid's front wall, rising above its rim, lip pointing back toward the hinge
        y_front = gap + D
        snap = craft.cantilever_snap(length=14, thickness=1.8, width=14, undercut=v["latch_undercut"], lead_angle=35)
        hook = Pos(0, y_front + 1.8 - 0.2, Hl - 6) * Rot(0, 0, -90) * snap.shapes["hook"]
        lid_side = lid_side + hook
        body = base_side + lid_side
        stages.append(Stage("latch", body))
        # catch: a ledge on the base's front wall, square underneath, ramped on top. Closed, the hook's retaining face
        # sits at z' = Hb + Hl - (Hl - 6 + 14) on the base side.
        z_hold = Hb + Hl - (Hl - 6 + 14)
        y_out = -(gap + D)
        u = v["latch_undercut"] + 0.4
        prof = [(0, 0), (-u, 0), (-u, 1.0), (0, 1.0 + u * 1.6)]
        f = make_face(Wire.make_polygon([Plane.YZ.from_local_coords((y, z, 0)) for y, z in prof], close=True)).faces()[0]
        ledge = Pos(-7, y_out + 0.2, z_hold - 1.0 - 0.3) * extrude(f, 14)
        base_side = base_side + ledge
        body = base_side + lid_side
        stages.append(Stage("catch", body))
        self._snap = snap
        return parts.checked(stages)

    def derived(self, v):
        snap = craft.cantilever_snap(length=14, thickness=1.8, width=14, undercut=v["latch_undercut"], lead_angle=35)
        W, D, t, Hb, Hl, R, gap, h = self._dims(v)
        return snap.derived("latch", "latch.") + [
            {"key": "hinge_axis_z", "label": "Hinge axis height", "value": h, "unit": "mm", "feature": "hinge",
             "formula": "(base height + lid height) / 2", "interface": True},
            {"key": "hinge_clearance", "label": "Hinge clearance per side", "value": v["clearance"], "unit": "mm",
             "feature": "hinge", "formula": "print-in-place clearance (from the fit model when the generator made it)", "interface": True}]

    def assembly(self, v):
        W, D, t, Hb, Hl, R, gap, h = self._dims(v)
        return Assembly(parts=[Part("base", "Base", 0, note="Base, open side up."),
                               Part("lid", "Lid", 1, note="Lid, printed open; it swings over on the hinge.")],
                        # swept to 170 degrees: over the last ten the latch hook rides over the catch, flexing by its undercut (a
                        # snap overlaps by design when closed; its strain is in derived as latch.strain)
                        joints=[hinge("lid", (1, 0, 0), (0, 0, h), (0, 170), 13, parent="base", id="lid_hinge",
                                      label="Lid")])
