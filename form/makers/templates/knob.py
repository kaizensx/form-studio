"""Knob, made by Form Studio's knob generator: a skirt on the panel, a knurled (or smooth) grip band, a dished cap
with a pointer groove, and a D-shaft bore with an optional M3 set screw. It prints standing on its skirt, the bore
opening on the bed, so nothing needs support."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot, Sphere

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

MAKE = {
    "generator": "knob",
}


class Design(Recipe):
    title, summary = "Knob", "A knurled or smooth knob for a D-shaft, with a dished cap, a pointer and a set screw."
    category, tags = "Makers", ("knob", "d-shaft", "knurl")
    params = [
        Param("knob_d", "Knob diameter", 32, 16, 70, 0.5, "mm", "form", "grip"),
        Param("height", "Height", 20, 12, 40, 0.5, "mm", "form", "grip"),
        Param("knurl", "Knurled", 1, 0, 1, 1, "", "form", "grip", "1 = a diamond knurl band; 0 = a smooth band."),
        Param("pitch", "Knurl pitch", 1.5, 0.9, 3, 0.1, "mm", "form", "grip"),
        Param("knurl_depth", "Knurl depth", 0.55, 0.3, 1.2, 0.05, "mm", "form", "grip"),
        Param("shaft_d", "Shaft diameter", 6.0, 3, 10, 0.05, "mm", "brief", "bore",
              "Measure the shaft. 6 mm is the common potentiometer and encoder shaft."),
        Param("flat", "D-flat depth", 1.5, 0, 3, 0.05, "mm", "brief", "bore",
              "Shaft diameter minus the across-flat size (6 mm shafts: 4.5 mm across the flat). 0 = a round bore."),
        Param("fit", "Bore clearance / side", 0.12, 0, 0.4, 0.01, "mm", "interface", "bore",
              "A push fit on FDM; raise it if the knob will not go on."),
        Param("bore_depth", "Bore depth", 12, 5, 30, 0.5, "mm", "brief", "bore", "How far the shaft goes in."),
        Param("dish", "Cap dish depth", 0.8, 0, 2, 0.1, "mm", "form", "cap"),
        Param("set_screw", "Set screw", 1, 0, 1, 1, "", "interface", "set_screw", "1 = a radial M3 pilot onto the flat."),
    ]
    features = [Feature("skirt", "Skirt", "structure"), Feature("grip", "Grip band", "finish"),
                Feature("cap", "Dished cap", "structure"), Feature("pointer", "Pointer groove", "finish"),
                Feature("bore", "D-shaft bore", "interface"), Feature("set_screw", "Set screw", "interface")]

    def _zones(self, v):
        H = v["height"]
        return H, max(2.2, H * 0.12), max(3.0, H * 0.2)

    def constraints(self, v):
        if v["shaft_d"] + 2 * v["fit"] + 6 > v["knob_d"] - 2 * v["knurl_depth"]:
            return [RecipeError("The knob is too small around this shaft", "bore", "Use a larger knob.", ["knob_d", "shaft_d"])]
        if v["flat"] >= v["shaft_d"] / 2:
            return [RecipeError("The D-flat cuts past the shaft's centre", "bore", "Reduce the flat depth.", ["flat"])]
        H, skirt_h, cap_h = self._zones(v)
        if v["bore_depth"] > H - 1.6:
            return [RecipeError("The bore would break through the cap", "bore", "Make the bore shallower or the knob taller.",
                                ["bore_depth", "height"])]
        return []

    def build(self, v):
        R = v["knob_d"] / 2
        H, skirt_h, cap_h = self._zones(v)
        skirt = Cylinder(R + 1.4, skirt_h, align=BOTTOM)
        skirt = craft.safe_fillet(skirt, skirt.edges().group_by(Axis.Z)[-1], min(1.2, skirt_h * 0.5))
        skirt = skirt.chamfer(0.4, None, skirt.edges().group_by(Axis.Z)[0])
        stages = [Stage("skirt", skirt)]
        band_h = H - skirt_h - cap_h + 0.6
        if v["knurl"] >= 0.5:
            band = Pos(0, 0, skirt_h - 0.3) * craft.knurl(v["knob_d"], band_h, v["pitch"], v["knurl_depth"], "diamond", 30,
                                                          chamfer=0.7)
        else:
            band = Pos(0, 0, skirt_h - 0.3) * Cylinder(R - v["knurl_depth"] / 2, band_h, align=BOTTOM)
        body = skirt + band
        stages.append(Stage("grip", body))
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
        groove = Pos(R * 0.55, 0, H - v["dish"] - 0.7) * Box(R * 0.9, 1.4, 3, align=BOTTOM)
        body = body - groove
        stages.append(Stage("pointer", body))
        d = v["shaft_d"] + 2 * v["fit"]
        depth = v["bore_depth"]
        bore = Cylinder(d / 2, depth + 0.2, align=BOTTOM)
        if v["flat"] > 0:
            bore = bore - Pos(d / 2 - (v["flat"] - v["fit"]) + 10, 0, 0) * Box(20, 20, depth + 1, align=BOTTOM)
        body = body - Pos(0, 0, -0.2) * bore
        body = body - Pos(0, 0, -0.01) * Cylinder(d / 2 + 0.6, 0.6, align=BOTTOM)
        stages.append(Stage("bore", body))
        if v["set_screw"] >= 0.5:
            pilot = parts.self_tap_pilot("M3", R + 2)
            body = body - Pos(-(R + 1.5), 0, min(skirt_h + depth * 0.45, depth - 2)) * Rot(0, -90, 0) * pilot.shape
        stages.append(Stage("set_screw", body))
        return parts.checked(stages)

    def derived(self, v):
        d = v["shaft_d"] + 2 * v["fit"]
        out = [{"key": "bore_d", "label": "Bore diameter", "value": round(d, 3), "unit": "mm", "feature": "bore",
                "formula": "shaft d + 2 x clearance", "interface": True},
               {"key": "across_flat", "label": "Bore across the flat", "value": round(d - v["flat"] + v["fit"], 3) if v["flat"] > 0 else round(d, 3),
                "unit": "mm", "feature": "bore", "formula": "bore d - flat depth + clearance (the flat is held back by the clearance)", "interface": True}]
        if v["knurl"] >= 0.5:
            out.append({"key": "knurl_teeth", "label": "Knurl teeth around", "unit": "", "feature": "grip",
                        "value": max(6, int(round(math.pi * v["knob_d"] / v["pitch"]))), "formula": "round(pi x d / pitch)",
                        "interface": False})
        return out
