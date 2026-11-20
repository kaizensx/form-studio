"""Knurled thumb knob for an M6 hex-head bolt: the head drops into a hex pocket from the top, the shank leaves through
a bearing hub at the bottom.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Axis, Cylinder, Pos

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "M6 thumb knob", "Diamond-knurled thumb knob that captures an M6 hex bolt head."
    solids = 1
    params = [
        Param("knob_d", "Knob diameter", 34, 22, 60, 0.5, "mm", "form", "grip"),
        Param("height", "Height", 18, 12, 30, 0.5, "mm", "form", "body"),
        Param("pitch", "Knurl pitch", 1.6, 1.0, 3, 0.1, "mm", "form", "grip"),
        Param("knurl_depth", "Knurl depth", 0.6, 0.3, 1.2, 0.05, "mm", "form", "grip"),
        Param("hub_d", "Hub diameter", 15, 12, 24, 0.5, "mm", "form", "body"),
        Param("head_af", "Bolt head across flats", 10.0, 8, 13, 0.05, "mm", "brief", "head_pocket",
              "ISO 4017 M6: s = 10 mm (specified)."),
        Param("head_k", "Bolt head height", 4.0, 3, 6, 0.05, "mm", "brief", "head_pocket", "ISO 4017 M6: k = 4 mm."),
        Param("fit", "Head pocket clearance / side", 0.15, 0, 0.4, 0.01, "mm", "interface", "head_pocket"),
    ]
    features = [Feature("body", "Knob body", "structure"), Feature("grip", "Knurled grip band", "finish"),
                Feature("crown", "Domed crown", "finish"), Feature("head_pocket", "M6 hex head pocket", "interface"),
                Feature("bore", "M6 clearance bore", "interface")]

    def constraints(self, v):
        corner = (v["head_af"] + 2 * v["fit"]) / math.cos(math.pi / 6)
        if corner + 6 > v["knob_d"] - 2 * v["knurl_depth"]:
            return [RecipeError("The knob is too small around the bolt head", "head_pocket", "Use a larger knob.",
                                ["knob_d", "head_af"])]
        if v["hub_d"] > v["knob_d"] - 6:
            return [RecipeError("The hub is as wide as the knob", "body", "Use a smaller hub.", ["hub_d"])]
        return []

    def build(self, v):
        R, H, hub = v["knob_d"] / 2, v["height"], v["hub_d"] / 2
        hub_h = 3.0
        band_lo, band_hi = hub_h + 1.6, H - 4.2
        core = R - v["knurl_depth"]
        # one revolved spline profile: hub, a flare up to the band, the band at the knurl root, a domed crown
        prof = [(hub, 0.0), (hub, hub_h - 0.6), (hub + 1.2, hub_h + 0.2), (core - 1.0, band_lo - 0.4), (core, band_lo + 0.4),
                (core, band_hi - 0.2), (core - 0.6, band_hi + 1.2), (core - 3.0, H - 0.9), (core - 6.5, H - 0.1), (0.0, H)]
        body = craft.revolve_profile(prof, spline=True)
        body = body.chamfer(0.4, None, body.edges().group_by(Axis.Z)[0])
        stages = [Stage("body", body)]
        band = Pos(0, 0, band_lo) * craft.knurl(v["knob_d"], band_hi - band_lo, v["pitch"], v["knurl_depth"], "diamond", 30,
                                                chamfer=0.8)
        body = body + band
        stages.append(Stage("grip", body))
        # crown: the flat-topped pocket rim, softened
        af = v["head_af"] + 2 * v["fit"]
        land_z = H - 0.9                                    # a flat land around the pocket: crisp, filletable rim
        land_r = af / math.sqrt(3) + 2.0
        body = body - Pos(0, 0, land_z) * Cylinder(land_r, 5, align=BOTTOM)
        trap = parts.nut_trap("M6", "hex", v["fit"], depth=v["head_k"] + 0.2)
        body = body - Pos(0, 0, land_z + 0.01) * trap.shape
        stages.append(Stage("head_pocket", body))
        bore_d = parts.clearance_d("M6", "close")[0]
        body = body - Pos(0, 0, -0.1) * Cylinder(bore_d / 2, H, align=BOTTOM)
        stages.append(Stage("bore", body))
        rim = [e for e in body.edges() if e.bounding_box().min.Z > land_z - 0.05]    # land circle, land step, hex mouth
        body = craft.safe_fillet(body, rim, 0.35)
        low = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z) < 0.01 and e.radius < bore_d]
        body = body.chamfer(0.5, None, low)                                         # lead-in for the shank
        stages.append(Stage("crown", body))
        return parts.checked(stages)

    def derived(self, v):
        teeth = max(6, int(round(math.pi * v["knob_d"] / v["pitch"])))
        return [{"key": "pocket_af", "label": "Head pocket across flats", "value": v["head_af"] + 2 * v["fit"], "unit": "mm",
                 "feature": "head_pocket", "formula": "s + 2 x clearance", "interface": True},
                {"key": "bore_d", "label": "Shank bore", "value": parts.clearance_d("M6", "close")[0], "unit": "mm",
                 "feature": "bore", "formula": "ISO 273 close", "interface": True},
                {"key": "knurl_teeth", "label": "Knurl teeth", "value": teeth, "unit": "", "feature": "grip",
                 "formula": "round(pi d / pitch)", "interface": False}]
