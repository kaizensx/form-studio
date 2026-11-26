"""Screw-down cable clip: a ring that snaps over a cable of measured diameter, on a plate with two screw tabs."""
from build123d import Align, Box, Cylinder, Pos, Rot

from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)
SEAT = 0.8   # mm the bore sinks into the plate


class Design(Recipe):
    title = "Cable clip"
    summary = "A screw-down clip that snaps over a cable of measured diameter, with a fit model for the bore."
    params = [
        Param("cable_d", "Cable diameter", 6.0, 2, 20, 0.1, "mm", "brief", "ring",
              "Measure the cable with calipers; the fit model uses this value."),
        Param("clearance", "Clearance / side", 0.3, 0.0, 1.0, 0.05, "mm", "interface", "ring",
              "Gap between the cable and the bore on each side."),
        Param("wall", "Ring wall", 2.0, 1.2, 5, 0.1, "mm", "form", "ring"),
        Param("width", "Clip width", 10, 6, 30, 0.5, "mm", "form", "plate"),
        Param("plate_t", "Plate thickness", 2.4, 1.6, 6, 0.1, "mm", "form", "plate"),
        Param("tab", "Screw tab length", 9, 6, 20, 0.5, "mm", "form", "plate"),
        Param("screw_d", "Screw hole diameter", 3.4, 2, 6, 0.1, "mm", "brief", "screws",
              "3.4 mm clears an M3 or a #4 wood screw."),
        Param("opening", "Snap opening", 0.8, 0.5, 0.95, 0.01, "", "form", "opening",
              "Opening width as a fraction of the cable diameter."),
    ]
    features = [
        Feature("plate", "Base plate", "structure"),
        Feature("ring", "Ring", "interface", "Holds the cable."),
        Feature("opening", "Snap opening", "access", "The cable is pressed in through here."),
        Feature("screws", "Screw holes", "interface"),
    ]
    fit = {"cavity": "bore_d", "mating": "cable_d", "clearance": "clearance",
           "label": "Bore ↔ cable", "per_side": True, "window": [0.0, 1.0]}

    def _g(self, v):
        r_in = v["cable_d"] / 2 + v["clearance"]
        r_out = r_in + v["wall"]
        return {"r_in": r_in, "r_out": r_out, "length": 2 * r_out + 2 * v["tab"]}

    def constraints(self, v):
        g = self._g(v)
        if v["plate_t"] - SEAT < 1.0:
            return [RecipeError("The plate under the cable is under 1 mm thick", "plate",
                                "Make the plate thicker.", ["plate_t"])]
        if v["screw_d"] + 2 * 1.2 > v["tab"]:
            return [RecipeError("The screw hole leaves under 1.2 mm of plate around it", "screws",
                                "Lengthen the tabs or use a smaller screw.", ["tab", "screw_d"])]
        if v["screw_d"] + 2 * 1.2 > v["width"]:
            return [RecipeError("The clip is too narrow for the screw hole", "screws",
                                "Widen the clip or use a smaller screw.", ["width", "screw_d"])]
        if g["r_in"] * 2 * v["opening"] < 1.0:
            return [RecipeError("The snap opening is under 1 mm wide", "opening",
                                "Raise the opening fraction.", ["opening", "cable_d"])]
        return []

    def derived(self, v):
        g = self._g(v)
        return [
            {"key": "bore_d", "label": "Bore diameter", "value": 2 * g["r_in"], "unit": "mm", "feature": "ring",
             "formula": "cable_d + 2 × clearance", "interface": True},
            {"key": "length", "label": "Overall length", "value": g["length"], "unit": "mm", "feature": "plate",
             "formula": "2 × (bore/2 + wall) + 2 × tab", "interface": False},
        ]

    def build(self, v):
        g = self._g(v)
        w, t = v["width"], v["plate_t"]
        plate = Box(g["length"], w, t, align=A)
        stages = [Stage("plate", plate)]

        cz = t - SEAT + g["r_in"]                                     # the bore sinks SEAT mm into the plate, so the
                                                                      # ring meets the plate at an angle, not a knife edge
        ring = Pos(0, 0, cz) * Rot(90, 0, 0) * Cylinder(g["r_out"], w)
        ring = ring - Pos(0, 0, -50) * Box(200, 200, 50, align=A)     # nothing below the bed
        bore = Pos(0, 0, cz) * Rot(90, 0, 0) * Cylinder(g["r_in"], w + 2)
        body = (plate + ring) - bore
        stages.append(Stage("ring", body))

        gap = 2 * g["r_in"] * v["opening"]
        body = body - Pos(0, 0, cz) * Box(gap, w + 2, g["r_out"] + 5, align=A)
        # Flat-top the two horns: where the opening meets the outer ring they would end in a sharp edge.
        body = body - Pos(0, 0, cz + 0.9 * g["r_in"]) * Box(200, w + 2, 50, align=A)
        stages.append(Stage("opening", body))

        x = g["r_out"] + v["tab"] / 2
        for sx in (-1, 1):
            body = body - Pos(sx * x, 0, -1) * Cylinder(v["screw_d"] / 2, t + 2, align=A)
        stages.append(Stage("screws", body))
        return stages
