"""Twisted polygon planter: a lofted shell whose sides spiral as they rise.

The twist is where it gets interesting for printing: more twist and more taper
mean steeper overhangs. FORM measures them on the real mesh, so an agent can
search for the most twist that still prints without supports.
"""
from __future__ import annotations

import math

from build123d import Align, Cylinder, Plane, Pos, RegularPolygon, Rot, loft

from .base import Feature, Param, Recipe, RecipeError, Stage


class TwistPlanter(Recipe):
    id = "planter"
    legacy = True          # retired from the library: still opens and builds for designs that use it
    title = "Twisted planter"
    summary = "A polygon planter that twists as it rises, with a drainage hole that fits a standard cork or mesh plug."
    fit = {"cavity": "drain_hole", "mating": "plug_d", "clearance": "plug_clearance",
           "label": "Drain hole ↔ plug", "per_side": True, "window": [0.0, 0.4]}

    params = [
        Param("diameter", "Top diameter (across corners)", 110, 40, 175, 0.5, "mm", "form", "shell"),
        Param("height", "Height", 100, 30, 175, 0.5, "mm", "form", "shell"),
        Param("sides", "Sides", 6, 3, 12, 1, "", "form", "shell"),
        Param("twist", "Twist", 60, 0, 180, 1, "deg", "form", "shell", "Rotation of the top relative to the base."),
        Param("taper", "Base / top ratio", 0.72, 0.4, 1.0, 0.01, "", "form", "shell"),
        Param("bulge", "Bulge", 0.08, 0, 0.3, 0.01, "", "form", "shell", "Mid-height swell as a fraction of the top size."),
        Param("wall", "Wall", 2.4, 1.2, 6, 0.1, "mm", "form", "cavity"),
        Param("bottom", "Bottom", 3.0, 1.6, 10, 0.1, "mm", "form", "cavity"),
        Param("plug_d", "Drain plug diameter", 12.0, 0, 30, 0.1, "mm", "brief", "drain", "0 = no drainage hole."),
        Param("plug_clearance", "Drain clearance / side", 0.1, -0.2, 1, 0.05, "mm", "interface", "drain"),
    ]
    features = [
        Feature("shell", "Shell", "structure"),
        Feature("cavity", "Cavity", "access"),
        Feature("drain", "Drain hole", "interface"),
    ]

    @staticmethod
    def radius(v, t):
        top = v["diameter"] / 2
        base = top * v["taper"]
        return base + (top - base) * t + top * v["bulge"] * math.sin(math.pi * t)

    def constraints(self, v):
        out = []
        if abs(v["sides"] - round(v["sides"])) > 1e-9:
            out.append(RecipeError("Sides must be a whole number", "shell", "Use 3–12 sides.", ["sides"]))
        rmin = min(self.radius(v, t / 10) for t in range(11)) * math.cos(math.pi / max(3, round(v["sides"])))
        if v["wall"] * 2 + 10 > rmin * 2:
            out.append(RecipeError("Walls leave no room inside at the narrowest point", "cavity", "Thin the walls or widen the base.",
                                   ["wall", "taper"]))
        if v["plug_d"] and v["plug_d"] + 2 * v["plug_clearance"] > rmin * 2 - 2 * v["wall"] - 6:
            out.append(RecipeError("Drain hole is too wide for the base", "drain", "Use a smaller plug.", ["plug_d"]))
        if v["bottom"] > v["height"] / 3:
            out.append(RecipeError("Bottom is more than a third of the height", "cavity", "Thin the bottom.", ["bottom"]))
        return out

    def _sections(self, v, inset, z0, z1, n=9):
        sides = int(round(v["sides"]))
        secs = []
        for i in range(n):
            t = i / (n - 1)
            z = z0 + (z1 - z0) * t
            tt = z / v["height"]
            r = self.radius(v, min(max(tt, 0), 1))
            r_in = r - inset / math.cos(math.pi / sides)
            secs.append(Plane.XY.offset(z) * Rot(0, 0, v["twist"] * tt) * RegularPolygon(r_in, sides))
        return secs

    def build(self, v):
        shell = loft(self._sections(v, 0, 0, v["height"]))
        stages = [Stage("shell", shell)]
        cav = loft(self._sections(v, v["wall"], v["bottom"], v["height"] + 0.5))
        s = shell - cav
        stages.append(Stage("cavity", s))
        if v["plug_d"] > 0:
            hole = Pos(0, 0, -0.5) * Cylinder(v["plug_d"] / 2 + v["plug_clearance"], v["bottom"] + 1,
                                              align=(Align.CENTER, Align.CENTER, Align.MIN))
            s = s - hole
            stages.append(Stage("drain", s))
        return stages

    def derived(self, v):
        sides = int(round(v["sides"]))
        top = v["diameter"] / 2
        # steepest side overhang from geometry: lateral run per unit height along the twisted edge
        run = 2 * math.pi * top * (v["twist"] / 360) / v["height"]
        lean = math.degrees(math.atan(run + abs(top - top * v["taper"]) / v["height"]))
        vol_l = math.pi * (top * v["taper"] * 0.95) ** 2 * (v["height"] - v["bottom"]) / 1e6
        return [
            {"key": "drain_hole", "label": "Drain hole diameter", "value": v["plug_d"] + 2 * v["plug_clearance"], "unit": "mm",
             "feature": "drain", "formula": "plug + 2 × clearance", "interface": True},
            {"key": "edge_lean", "label": "Corner edge lean (estimate)", "value": lean, "unit": "deg", "feature": "shell",
             "formula": "atan(twist travel + taper per height)"},
            {"key": "soil_l", "label": "Soil volume (rough)", "value": vol_l, "unit": "L", "feature": "cavity",
             "formula": "inner base area × height"},
            {"key": "sides_n", "label": "Sides", "value": sides, "unit": "", "feature": "shell", "formula": "whole number"},
        ]

    def measure(self, v, faces_by_feature):
        if not v["plug_d"]:
            return []
        ds = [max(f.bounding_box().size.X, f.bounding_box().size.Y) for f in faces_by_feature.get("drain", [])
              if f.geom_type.name == "CYLINDER"]
        return [{"key": "drain_hole", "label": "Drain hole diameter", "intended": v["plug_d"] + 2 * v["plug_clearance"],
                 "modelled": max(ds)}] if ds else []
