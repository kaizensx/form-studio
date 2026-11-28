"""Wall hook, made by Form Studio's hook generator: a back plate with two countersunk screw holes and a J-shaped arm.
The hook is one side profile extruded by its width and printed lying on that profile, so the layers run along the
plate and around the bend (printed standing, the arm would break between layers). The wall is the plane x = 0, up
is +y; the screws go through the plate along x, their heads on the hook side."""
from build123d import Align, Axis, Box, Cone, Cylinder, Pos, Rot

from form import craft
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

MAKE = {
    "generator": "hook",
}


class Design(Recipe):
    title, summary = "Wall hook", "A J hook on a back plate with two countersunk screw holes, printed on its side."
    category, tags = "Makers", ("hook", "wall")
    params = [
        Param("plate_h", "Plate height", 70, 30, 160, 1, "mm", "form", "plate"),
        Param("t", "Thickness", 5, 3, 10, 0.1, "mm", "form", "plate", "Of the plate and the arm, in the print plane."),
        Param("width", "Width", 16, 8, 40, 0.5, "mm", "form", "plate", "Across the hook (the extrusion)."),
        Param("opening", "Opening", 18, 6, 60, 0.5, "mm", "brief", "arm", "Inside width of the J: what it holds."),
        Param("tip_h", "Tip height", 14, 4, 50, 0.5, "mm", "form", "arm", "How far the tip rises from the bottom of the bend."),
        Param("screw_d", "Screw diameter", 4, 2.5, 6, 0.1, "mm", "brief", "screws", "A 4 mm wood screw by default."),
    ]
    features = [Feature("plate", "Back plate", "structure"), Feature("arm", "J arm", "structure"),
                Feature("screws", "Screw holes", "interface")]

    def constraints(self, v):
        if v["screw_d"] * 2 + 1.2 > v["width"]:
            return [RecipeError("The countersink is wider than the hook", "screws", "Make the hook wider or the screw smaller.",
                                ["width", "screw_d"])]
        if v["plate_h"] < v["opening"] / 2 + v["t"] + 4 * v["screw_d"]:
            return [RecipeError("The plate is too short for two screws above the bend", "plate", "Make the plate taller.",
                                ["plate_h"])]
        return []

    def build(self, v):
        t, w, ri = v["t"], v["width"], v["opening"] / 2
        ro = ri + t
        plate = Pos(t / 2, v["plate_h"] / 2, 0) * Box(t, v["plate_h"], w, align=BOTTOM)
        plate = craft.safe_fillet(plate, plate.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1], t * 0.45)
        stages = [Stage("plate", plate)]
        cx, cy = ro, ro                               # bend centre: the plate's outer face is the bend's left side
        bend = Pos(cx, cy, 0) * (Cylinder(ro, w, align=BOTTOM) - Pos(0, 0, -1) * Cylinder(ri, w + 2, align=BOTTOM))
        bend = bend - Pos(cx, cy + ro, -1) * Box(2 * ro + 2, 2 * ro, w + 2, align=BOTTOM)   # the lower half
        leg = Pos(cx + ri + t / 2, cy + v["tip_h"] / 2, 0) * Box(t, v["tip_h"], w, align=BOTTOM)
        leg = craft.safe_fillet(leg, leg.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1], t * 0.45)
        body = craft.fuse(craft.fuse(plate, bend), leg)
        stages.append(Stage("arm", body))
        y_lo = ro + ri * 0.2 + 2.5 * v["screw_d"]
        for y in (y_lo, v["plate_h"] - 2.5 * v["screw_d"]):
            hole = Pos(-0.1, y, w / 2) * Rot(0, 90, 0) * Cylinder(v["screw_d"] / 2 + 0.2, t + 0.2, align=BOTTOM)
            r = v["screw_d"] + 0.2
            sink = Pos(t + 0.01, y, w / 2) * Rot(0, -90, 0) * Cone(r, 0.01, r, align=BOTTOM)
            body = body - hole - sink
        stages.append(Stage("screws", body))
        return stages

    def derived(self, v):
        return [{"key": "reach", "label": "Reach from the wall", "value": round(2 * (v["opening"] / 2 + v["t"]), 2),
                 "unit": "mm", "feature": "arm", "formula": "opening + 2 x thickness", "interface": False},
                {"key": "opening_w", "label": "Opening", "value": v["opening"], "unit": "mm", "feature": "arm",
                 "formula": "inside width of the J", "interface": True}]
