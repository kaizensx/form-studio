"""Fit coupon — a comb of slots stepping up from a gauge width.

Measure each printed slot with caliper inside jaws. The difference between
nominal and measured widths is this printer/material's bias and spread for
internal features, which FORM then applies to pocket fits.
"""
from __future__ import annotations

from build123d import Align, Axis, Box, Pos, chamfer

from .base import Feature, Param, Recipe, RecipeError, Stage


class Coupon(Recipe):
    id = "coupon"
    category = "Calibration"
    tags = ("fit", "tolerance", "calibration")
    title = "Fit coupon"
    summary = "A slot comb for calibrating internal-feature accuracy on your printer and material."
    fit = None

    params = [
        Param("gauge", "Gauge width", 10.0, 3, 40, 0.5, "mm", "interface", "slots",
              "Nominal width of the first slot. Pick something your calipers measure comfortably."),
        Param("step", "Step between slots", 0.1, 0.02, 0.5, 0.01, "mm", "interface", "slots"),
        Param("slots", "Slot count", 5, 3, 8, 1, "", "interface", "slots"),
        Param("wall", "Wall between slots", 4.0, 2, 10, 0.5, "mm", "form", "bar"),
        Param("height", "Height", 10.0, 6, 30, 0.5, "mm", "form", "bar"),
        Param("depth", "Depth", 12.0, 6, 40, 0.5, "mm", "form", "bar"),
        Param("floor", "Floor", 3.0, 1.2, 10, 0.2, "mm", "form", "bar"),
    ]
    features = [
        Feature("bar", "Bar", "structure", "Carrier for the slots."),
        Feature("slots", "Slots", "interface", "Vertical-walled slots, printed the same way as a pocket."),
        Feature("origin", "Origin mark", "finish", "Chamfered corner marks the narrowest slot."),
    ]

    @staticmethod
    def widths(v):
        return [round(v["gauge"] + i * v["step"], 4) for i in range(int(round(v["slots"])))]

    def length(self, v):
        w = self.widths(v)
        return sum(w) + (len(w) + 1) * v["wall"]

    def constraints(self, v):
        out = []
        if abs(v["slots"] - round(v["slots"])) > 1e-9:
            out.append(RecipeError("Slot count must be a whole number", "slots", "Use 3–8 slots.", ["slots"]))
        if self.length(v) > 170:
            out.append(RecipeError(f"Coupon is {self.length(v):.0f} mm long; the plate allows 170 mm", "bar",
                                   "Use fewer slots or a smaller gauge.", ["slots", "gauge"]))
        if v["floor"] > v["height"] - 4:
            out.append(RecipeError("Slots are shallower than 4 mm", "slots", "Raise the height or lower the floor.", ["height", "floor"]))
        return out

    def build(self, v):
        L = self.length(v)
        bar = Box(L, v["depth"], v["height"], align=(Align.MIN, Align.CENTER, Align.MIN))
        stages = [Stage("bar", bar)]
        s, x = bar, v["wall"]
        for w in self.widths(v):
            s = s - Pos(x, 0, v["floor"]) * Box(w, v["depth"] + 2, v["height"], align=(Align.MIN, Align.CENTER, Align.MIN))
            x += w + v["wall"]
        stages.append(Stage("slots", s))
        corner = [e for e in s.edges().filter_by(Axis.Z) if e.center().X < 1e-6 and e.center().Y < 0]
        s = chamfer(corner, min(v["wall"] - 1, 2.5))
        stages.append(Stage("origin", s))
        return stages

    def derived(self, v):
        out = [{"key": f"slot_{i+1}", "label": f"Slot {i+1}", "value": w, "unit": "mm", "feature": "slots",
                "formula": f"gauge + {i} × step", "interface": True} for i, w in enumerate(self.widths(v))]
        out.append({"key": "length", "label": "Overall length", "value": self.length(v), "unit": "mm", "feature": "bar",
                    "formula": "slots + walls"})
        return out

    def measure(self, v, faces_by_feature):
        xs = sorted(f.center().X for f in faces_by_feature.get("slots", [])
                    if f.geom_type.name == "PLANE" and abs(abs(f.normal_at(f.center()).X) - 1) < 1e-6)
        out = []
        for i, w in enumerate(self.widths(v)):
            if 2 * i + 1 < len(xs):
                out.append({"key": f"slot_{i+1}", "label": f"Slot {i+1}", "intended": w, "modelled": xs[2 * i + 1] - xs[2 * i]})
        return out
