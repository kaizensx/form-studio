"""Knurled control knob for a 6 mm D-shaft: diamond knurl band, dished cap with a pointer, flared skirt, set screw.
Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot, Sphere

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Knurled knob",
    "tags": ["knob", "knurl", "knurled", "texture", "shaft", "potentiometer", "dial", "grip", "brep texture"],
    "techniques": ["craft.knurl diamond", "revolved cap with dish", "D-shaft bore", "radial set screw", "safe_fillet"],
    "lessons": [
        "A knob reads as designed when it has three zones: a skirt that meets the panel, a working grip band, and a "
        "cap the thumb rests on. Give each its own profile and round every transition.",
        "Knurl is B-rep texture here (it does work: grip), made by craft.knurl as an exact faceted solid with eased ends, "
        "so the teeth never end in burrs.",
        "The pointer is a sunk groove in the dish, not a raised fin: it prints cleaner and does not catch.",
        "Bore and set screw come from published numbers (form.parts), and their sizes go in derived().",
    ],
}


class Design(Recipe):
    title, summary = "Knurled knob", "Diamond-knurled knob with a dished cap, pointer and set screw for a 6 mm D-shaft."
    solids = 1
    params = [
        Param("knob_d", "Knob diameter", 32, 18, 60, 0.5, "mm", "form", "grip"),
        Param("height", "Height", 20, 12, 40, 0.5, "mm", "form", "grip"),
        Param("pitch", "Knurl pitch", 1.5, 0.9, 3, 0.1, "mm", "form", "grip"),
        Param("knurl_depth", "Knurl depth", 0.55, 0.3, 1.2, 0.05, "mm", "form", "grip"),
        Param("shaft_d", "Shaft diameter", 6.0, 3, 10, 0.05, "mm", "brief", "bore", "Measure the shaft."),
        Param("flat", "D-flat depth", 1.5, 0, 3, 0.05, "mm", "brief", "bore", "Shaft diameter minus the across-flat size."),
        Param("fit", "Bore clearance / side", 0.12, 0, 0.4, 0.01, "mm", "interface", "bore"),
        Param("dish", "Cap dish depth", 0.8, 0, 2, 0.1, "mm", "form", "cap"),
    ]
    features = [Feature("skirt", "Skirt", "structure"), Feature("grip", "Knurled grip", "finish"),
                Feature("cap", "Dished cap", "structure"), Feature("pointer", "Pointer groove", "finish"),
                Feature("bore", "D-shaft bore", "interface"), Feature("set_screw", "Set screw", "interface")]

    def constraints(self, v):
        if v["shaft_d"] + 2 * v["fit"] + 6 > v["knob_d"] - 2 * v["knurl_depth"]:
            return [RecipeError("The knob is too small around this shaft", "bore", "Use a larger knob.", ["knob_d", "shaft_d"])]
        if v["flat"] >= v["shaft_d"] / 2:
            return [RecipeError("The D-flat cuts past the shaft's centre", "bore", "Reduce the flat depth.", ["flat"])]
        return []

    def _zones(self, v):
        H = v["height"]
        skirt_h = max(2.2, H * 0.12)
        cap_h = max(3.0, H * 0.2)
        return H, skirt_h, cap_h

    def build(self, v):
        R, H = v["knob_d"] / 2, v["height"]
        H, skirt_h, cap_h = self._zones(v)
        # skirt: a flared foot slightly wider than the grip, chamfered on the bed, rounded on top
        skirt = Cylinder(R + 1.4, skirt_h, align=BOTTOM)
        skirt = craft.safe_fillet(skirt, skirt.edges().group_by(Axis.Z)[-1], min(1.2, skirt_h * 0.5))
        skirt = skirt.chamfer(0.4, None, skirt.edges().group_by(Axis.Z)[0])
        stages = [Stage("skirt", skirt)]
        band_h = H - skirt_h - cap_h + 0.6
        band = Pos(0, 0, skirt_h - 0.3) * craft.knurl(v["knob_d"], band_h, v["pitch"], v["knurl_depth"], "diamond", 30,
                                                      chamfer=0.7)
        body = skirt + band
        stages.append(Stage("grip", body))
        # cap: full-diameter crown with a soft edge and a shallow dish for the thumb
        cap = Pos(0, 0, H - cap_h) * Cylinder(R, cap_h, align=BOTTOM)
        cap = craft.safe_fillet(cap, cap.edges().group_by(Axis.Z)[-1], min(2.4, cap_h * 0.7))
        body = body + cap
        if v["dish"] > 0:
            rs = (R * 0.78) ** 2 / (2 * v["dish"]) + v["dish"] / 2
            body = body - Pos(0, 0, H + rs - v["dish"]) * Sphere(rs)
            rim = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z - H) < 0.05
                   and e.radius < R * 0.85]
            body = craft.safe_fillet(body, rim, 0.6)
        stages.append(Stage("cap", body))
        # pointer: a sunk groove from near the centre to the edge, along +X
        groove = Pos(R * 0.55, 0, H - v["dish"] - 0.1) * Box(R * 0.9, 1.4, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
        groove = Pos(0, 0, -0.6) * groove
        body = body - groove
        stages.append(Stage("pointer", body))
        # D-shaft bore from the bed, with a lead-in chamfer
        d = v["shaft_d"] + 2 * v["fit"]
        depth = min(H - cap_h - 1.0, 14)
        bore = Cylinder(d / 2, depth + 0.2, align=BOTTOM)
        if v["flat"] > 0:
            bore = bore - Pos(d / 2 - (v["flat"] - v["fit"]) + 10, 0, 0) * Box(20, 20, depth + 1, align=BOTTOM)
        body = body - Pos(0, 0, -0.2) * bore
        body = body - Pos(0, 0, -0.01) * Cylinder(d / 2 + 0.6, 0.6, align=BOTTOM)
        stages.append(Stage("bore", body))
        # radial M3 set screw onto the flat, self-tapping pilot from the side (-X so it bears on the D-flat)
        pilot = parts.self_tap_pilot("M3", R + 2)
        body = body - Pos(-(R + 1.5), 0, skirt_h + depth * 0.45) * Rot(0, -90, 0) * pilot.shape
        stages.append(Stage("set_screw", body))
        return parts.checked(stages)

    def derived(self, v):
        d = v["shaft_d"] + 2 * v["fit"]
        teeth = max(6, int(round(math.pi * v["knob_d"] / v["pitch"])))
        return [{"key": "bore_d", "label": "Bore diameter", "value": d, "unit": "mm", "feature": "bore",
                 "formula": "shaft d + 2 x clearance", "interface": True},
                {"key": "knurl_teeth", "label": "Knurl teeth around", "value": teeth, "unit": "", "feature": "grip",
                 "formula": "round(pi x d / pitch)", "interface": False}]
