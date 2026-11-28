"""Cable clip, made by Form Studio's cable_clip generator: one to four snap-in rings on a strip that is screwed to a
wall or the underside of a desk. The whole clip is one profile extruded by its width, printed lying on that
profile, so it has no overhangs and its layers run around each ring (the direction the ring flexes). The wall is
the plane y = 0; the screw holes go through the strip along y, countersunk on the ring side."""
import math

from build123d import Align, Axis, Box, Cone, Cylinder, Pos, Rot

from form import craft
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

MAKE = {
    "generator": "cable_clip",
}


class Design(Recipe):
    title, summary = "Cable clip", "Snap-in clips for one to four cables on a strip with countersunk screw holes."
    category, tags = "Makers", ("cable", "clip")
    params = [
        Param("cable_d", "Cable diameter", 6, 2, 20, 0.1, "mm", "brief", "rings", "Measure the cable."),
        Param("count", "Cables", 1, 1, 4, 1, "", "form", "rings"),
        Param("fit", "Clearance", 0.3, 0, 1.5, 0.05, "mm", "interface", "rings", "Radial room around the cable."),
        Param("opening", "Opening", 0.7, 0.5, 0.9, 0.01, "", "interface", "rings",
              "Width of the snap opening as a share of the cable diameter: smaller holds tighter."),
        Param("wall", "Ring wall", 2.0, 1.2, 4, 0.1, "mm", "form", "rings", "Thinner flexes more and holds less."),
        Param("width", "Clip width", 10, 5, 30, 0.5, "mm", "form", "strip", "Along the cable."),
        Param("strip_t", "Strip thickness", 3, 2, 6, 0.1, "mm", "form", "strip"),
        Param("screw_d", "Screw diameter", 3.5, 0, 5, 0.1, "mm", "brief", "screws",
              "3.5 mm suits a 3.5 mm wood screw; 0 = no holes (stick it on with tape)."),
    ]
    features = [Feature("strip", "Strip", "structure"), Feature("rings", "Snap rings", "structure"),
                Feature("screws", "Screw holes", "interface")]

    def _dims(self, v):
        ri = v["cable_d"] / 2 + v["fit"]
        ro = ri + v["wall"]
        pitch = 2 * ro - v["wall"] * 0.5
        tab = max(2.6 * v["screw_d"], 8) if v["screw_d"] > 0 else 2.0
        n = int(round(v["count"]))
        span = (n - 1) * pitch + 2 * ro
        L = span + 2 * tab
        return ri, ro, pitch, tab, n, span, L

    def constraints(self, v):
        if v["screw_d"] > 0 and v["screw_d"] * 1.8 + 1 > v["width"]:
            return [RecipeError("The countersink is wider than the clip", "screws", "Make the clip wider or the screw smaller.",
                                ["width", "screw_d"])]
        ri, ro, pitch, tab, n, span, L = self._dims(v)
        if L > 175:
            return [RecipeError("The clip is longer than a 175 mm bed", "strip", "Clip fewer or thinner cables.", ["count", "cable_d"])]
        return []

    def build(self, v):
        ri, ro, pitch, tab, n, span, L = self._dims(v)
        w, t = v["width"], v["strip_t"]
        strip = Pos(0, t / 2, 0) * Box(L, t, w, align=BOTTOM)
        strip = craft.safe_fillet(strip, strip.edges().filter_by(Axis.Z).group_by(Axis.Y)[-1], min(t * 0.45, 1.2))
        stages = [Stage("strip", strip)]
        half = math.asin(min(0.95, v["opening"] * v["cable_d"] / 2 / ri))   # half-angle of the opening, at the inside
        cy = t + ri                                      # the cable touches the strip's face
        xs = [-span / 2 + ro + k * pitch for k in range(n)]
        # the rings' outsides, and a web from the strip up to their centres so no pocket is left between them
        body = strip + Pos((xs[0] + xs[-1]) / 2, (t + cy) / 2 - 0.25, 0) * Box(xs[-1] - xs[0] + 0.01, cy - t + 0.5, w,
                                                                             align=BOTTOM)
        for cx in xs:
            body = craft.fuse(body, Pos(cx, cy, 0) * Cylinder(ro, w, align=BOTTOM))
        gap = v["opening"] * v["cable_d"]
        for cx in xs:
            body = craft.cut(body, Pos(cx, cy, -1) * Cylinder(ri, w + 2, align=BOTTOM))
            body = craft.cut(body, Pos(cx, cy + ri * math.cos(half) + v["wall"], -1) * Box(gap, 2 * v["wall"] + ri, w + 2,
                                                                                         align=BOTTOM))
        # round the tips of each opening so the cable slides in
        tips = [e for e in body.edges().filter_by(Axis.Z) if e.center().Y > t + ri * 1.2]
        body = craft.safe_fillet(body, tips, min(0.6, v["wall"] * 0.3))
        stages.append(Stage("rings", body))
        if v["screw_d"] > 0:
            for sx in (-L / 2 + tab / 2, L / 2 - tab / 2):
                hole = Pos(sx, -0.1, w / 2) * Rot(-90, 0, 0) * Cylinder(v["screw_d"] / 2 + 0.15, t + 0.2, align=BOTTOM)
                sink_r = v["screw_d"] * 0.9 + 0.2
                cone = Pos(sx, t + 0.01, w / 2) * Rot(90, 0, 0) * Cone(sink_r, 0.01, sink_r, align=BOTTOM)
                body = body - hole - cone
        stages.append(Stage("screws", body))
        return stages

    def derived(self, v):
        ri, ro, pitch, tab, n, span, L = self._dims(v)
        return [{"key": "inner_d", "label": "Ring inner diameter", "value": round(2 * ri, 3), "unit": "mm",
                 "feature": "rings", "formula": "cable d + 2 x clearance", "interface": True},
                {"key": "gap", "label": "Snap opening", "value": round(v["opening"] * v["cable_d"], 3), "unit": "mm",
                 "feature": "rings", "formula": "opening x cable d", "interface": True},
                {"key": "length", "label": "Clip length", "value": round(L, 2), "unit": "mm", "feature": "strip",
                 "formula": "rings + two screw tabs", "interface": False}]

