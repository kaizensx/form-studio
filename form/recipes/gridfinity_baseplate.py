"""Gridfinity baseplate: the grid that Gridfinity bins lock into, sized to your bed or your drawer.

Each cell is the published socket: 42 mm square at the top with 4 mm corners, then 2.15 mm at 45°, 1.8 mm straight
and 0.7 mm at 45° down to a 36.3 mm opening, 4.65 mm in all. Every socket face looks up, so the plate prints flat
with no support. The plain plate is an open frame (the "lite" baseplate most people print). Add a floor for magnet
pockets on the bins' 26 mm square, or for one countersunk screw per cell to fix the plate in a drawer.

Margins fill the gap between the grid and a drawer wall; a drawer bigger than the bed takes several plates.
"""
from __future__ import annotations

from build123d import Align, Axis, Box, Cone, Cylinder, Plane, Pos, RectangleRounded, chamfer, fillet, loft

from .base import Feature, Param, Recipe, RecipeError, Stage

PITCH = 42.0          # grid pitch (spec)
SOCKET_H = 4.65       # 0.7 + 1.8 + 2.15 (spec)
CELL_R = 4.0          # corner radius of a socket at the top (spec)
BOTTOM = 42.0 - 2 * (2.15 + 0.7)        # 36.3 mm opening at the bottom of a socket
WAIST = 42.0 - 2 * 2.15                 # 37.7 mm across the straight band
MAG_OFF = 13.0        # magnet positions, ±13 mm from each cell centre (spec)
BED = 175.0           # the most one plate may span on a 180 mm bed with a margin


def _rr(w, d, r, z):
    r = max(0.3, min(r, w / 2 - 0.01, d / 2 - 0.01))
    return Plane.XY.offset(z) * RectangleRounded(w, d, r)


def socket(z0: float):
    """The void of one socket, its bottom at z0, a little proud of the top so it cuts cleanly."""
    return loft([_rr(BOTTOM, BOTTOM, CELL_R - 2.85, z0 - 0.01), _rr(BOTTOM, BOTTOM, CELL_R - 2.85, z0),
                 _rr(42 - 2 * 2.15, 42 - 2 * 2.15, CELL_R - 2.15, z0 + 0.7),
                 _rr(42 - 2 * 2.15, 42 - 2 * 2.15, CELL_R - 2.15, z0 + 2.5),
                 _rr(42.0, 42.0, CELL_R, z0 + SOCKET_H), _rr(42.0, 42.0, CELL_R, z0 + SOCKET_H + 0.01)], ruled=True)


class GridfinityBaseplate(Recipe):
    id = "gridfinity_baseplate"
    title = "Gridfinity baseplate"
    summary = ("The grid Gridfinity bins lock into: spec sockets, margins that fill a drawer, and an optional floor "
               "with magnet pockets or screw holes.")
    category = "Storage"
    tags = ("gridfinity", "baseplate", "drawer", "organiser", "workshop", "magnets", "modular")

    params = [
        Param("grid_x", "Width", 4, 1, 4, 1, "u", "form", "frame", "Cells across, 42 mm each. Four fill a 180 mm bed."),
        Param("grid_y", "Depth", 4, 1, 4, 1, "u", "form", "frame", "Cells front to back."),
        Param("pad_x", "Side margin", 0, 0, 20, 0.5, "mm", "brief", "margin",
              "Solid border added left and right: measure the drawer, subtract 42 mm per cell, halve it."),
        Param("pad_y", "Front and back margin", 0, 0, 20, 0.5, "mm", "brief", "margin", "As the side margin, front to back."),
        Param("corner_r", "Outer corner radius", 4, 0.5, 8, 0.5, "mm", "form", "frame", "4 mm matches the bins' corners."),
        Param("floor", "Floor", 0, 0, 1, 1, "", "form", "floor",
              "0 = open frame (light, quick); 1 = a floor under the sockets, needed for magnets and screws."),
        Param("magnets", "Magnet pockets", 0, 0, 1, 1, "", "interface", "magnets",
              "1 = four pockets per cell, under the bins' magnets. Needs the floor."),
        Param("magnet_d", "Magnet diameter", 6.0, 3, 10, 0.05, "mm", "brief", "magnets",
              "Gridfinity uses 6 × 2 mm discs. Measure yours.", "specified"),
        Param("magnet_h", "Magnet thickness", 2.0, 1, 4, 0.05, "mm", "brief", "magnets", "", "specified"),
        Param("magnet_clearance", "Magnet clearance / side", 0.15, -0.1, 0.4, 0.01, "mm", "interface", "magnets",
              "0.15 takes a drop of glue; 0 or less is a press fit."),
        Param("screws", "Screw holes", 0, 0, 1, 1, "", "interface", "screws",
              "1 = a countersunk hole in every cell for a 3.5–4 mm wood screw. Needs the floor."),
    ]
    features = [
        Feature("frame", "Frame", "structure"),
        Feature("sockets", "Sockets", "interface", "Spec socket profile; the bins' feet drop in."),
        Feature("margin", "Margins", "structure", "Solid border that fills the drawer."),
        Feature("floor", "Floor", "structure"),
        Feature("magnets", "Magnet pockets", "interface"),
        Feature("screws", "Screw holes", "interface"),
        Feature("soften", "Edge finish", "finish"),
    ]

    @staticmethod
    def g(v):
        nx, ny = int(round(v["grid_x"])), int(round(v["grid_y"]))
        fl = (v["magnet_h"] + 0.2 + 1.4) if v["floor"] >= 0.5 else 0.0
        if v["floor"] >= 0.5 and v["screws"] >= 0.5:
            fl = max(fl, 3.6)
        return {"nx": nx, "ny": ny, "W": PITCH * nx + 2 * v["pad_x"], "D": PITCH * ny + 2 * v["pad_y"],
                "floor_t": fl, "H": fl + SOCKET_H, "hole": v["magnet_d"] + 2 * v["magnet_clearance"],
                "cells": [((i - (nx - 1) / 2) * PITCH, (j - (ny - 1) / 2) * PITCH) for i in range(nx) for j in range(ny)]}

    def constraints(self, v):
        out = []
        for k in ("grid_x", "grid_y", "floor", "magnets", "screws"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        if out:
            return out
        g = self.g(v)
        if g["W"] > BED or g["D"] > BED:
            out.append(RecipeError(f"The plate is {g['W']:.0f} × {g['D']:.0f} mm; a 180 mm bed takes about {BED:.0f}", "frame",
                                   "Use fewer cells or smaller margins, and print the drawer in several plates.",
                                   ["grid_x", "grid_y", "pad_x", "pad_y"]))
        if v["corner_r"] > CELL_R + min(v["pad_x"], v["pad_y"]):
            out.append(RecipeError("The outer corner cuts into the corner socket", "frame",
                                   "Use a corner radius of 4 mm plus the margin, or less.", ["corner_r", "pad_x", "pad_y"]))
        if (v["magnets"] or v["screws"]) and not v["floor"]:
            out.append(RecipeError("Magnets and screws sit in the floor; the plate has none", "floor", "Turn the floor on.",
                                   ["floor", "magnets", "screws"]))
        if v["magnets"] and g["hole"] / 2 + MAG_OFF > BOTTOM / 2 - 0.8:
            out.append(RecipeError("Magnet pockets reach past the socket floor", "magnets", "Use smaller magnets.", ["magnet_d"]))
        return out

    def build(self, v):
        g = self.g(v)
        W, D, H, fl = g["W"], g["D"], g["H"], g["floor_t"]
        nx, ny = g["nx"], g["ny"]
        r = min(v["corner_r"], W / 2 - 0.1, D / 2 - 0.1)
        grid = Box(PITCH * nx, PITCH * ny, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        grid = fillet(grid.edges().filter_by(Axis.Z), min(CELL_R, r))
        stages = [Stage("frame", grid)]
        cut = None
        for x, y in g["cells"]:
            c = Pos(x, y, 0) * socket(fl)
            cut = c if cut is None else cut + c
        s = grid - cut
        stages.append(Stage("sockets", s))
        if v["pad_x"] > 0 or v["pad_y"] > 0:
            outer = Box(W, D, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
            outer = fillet(outer.edges().filter_by(Axis.Z), r)
            inner = Box(PITCH * nx - 0.02, PITCH * ny - 0.02, H + 2, align=(Align.CENTER, Align.CENTER, Align.CENTER))
            s = s + (outer - inner)
            # the frame's own outer corners leave notches against the margin: fill them
            fill = Box(PITCH * nx, PITCH * ny, H, align=(Align.CENTER, Align.CENTER, Align.MIN)) - fillet(
                Box(PITCH * nx, PITCH * ny, H + 2, align=(Align.CENTER, Align.CENTER, Align.CENTER)).edges().filter_by(Axis.Z), min(CELL_R, r))
            s = s + fill - cut
            stages.append(Stage("margin", s))
        if fl > 0:
            # light the floor: an open square in each cell, unless it carries a screw
            if not v["screws"] and not v["magnets"]:
                holes = None
                for x, y in g["cells"]:
                    h = Pos(x, y, -0.01) * fillet(Box(20, 20, fl + 0.02, align=(Align.CENTER, Align.CENTER, Align.MIN))
                                                  .edges().filter_by(Axis.Z), 4)
                    holes = h if holes is None else holes + h
                s = s - holes
            elif not v["screws"]:
                holes = None
                for x, y in g["cells"]:
                    h = Pos(x, y, -0.01) * Cylinder(5, fl + 0.02, align=(Align.CENTER, Align.CENTER, Align.MIN))
                    holes = h if holes is None else holes + h
                s = s - holes
            stages.append(Stage("floor", s))
        if v["magnets"]:
            pk = None
            d = v["magnet_h"] + 0.2
            for x, y in g["cells"]:
                for dx in (-MAG_OFF, MAG_OFF):
                    for dy in (-MAG_OFF, MAG_OFF):
                        c = Pos(x + dx, y + dy, fl - d) * Cylinder(g["hole"] / 2, d + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
                        pk = c if pk is None else pk + c
            s = s - pk
            stages.append(Stage("magnets", s))
        if v["screws"]:
            sk = None
            for x, y in g["cells"]:
                # 4.5 mm clearance hole and a 90° countersink for an 8.5 mm head, flush with the floor top
                hole = Pos(x, y, -0.01) * Cylinder(2.25, fl + 0.02, align=(Align.CENTER, Align.CENTER, Align.MIN))
                cs = Pos(x, y, fl - 2.0) * Cone(2.25, 4.25, 2.0 + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
                c = hole + cs
                sk = c if sk is None else sk + c
            s = s - sk
            stages.append(Stage("screws", s))
        # a 45° foot chamfer round the outside, where the first layer flares
        try:
            base = max((f for f in s.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z) < 1e-4
                        and f.normal_at().Z < -0.99), key=lambda f: f.area)
            outer_bottom = base.outer_wire().edges()
            s = chamfer(outer_bottom, 0.4)
            stages.append(Stage("soften", s))
        except Exception:
            pass
        return stages

    def derived(self, v):
        g = self.g(v)
        out = [{"key": "plate_w", "label": "Plate width", "value": g["W"], "unit": "mm", "feature": "frame", "formula": "42 × cells + 2 × margin"},
               {"key": "plate_d", "label": "Plate depth", "value": g["D"], "unit": "mm", "feature": "frame", "formula": "42 × cells + 2 × margin"},
               {"key": "height", "label": "Height", "value": g["H"], "unit": "mm", "feature": "frame", "formula": "4.65 mm socket + floor"},
               {"key": "socket_waist", "label": "Socket width at its straight band", "value": WAIST, "unit": "mm", "feature": "sockets",
                "formula": "42 − 2 × 2.15, spec", "interface": True}]
        if v["magnets"]:
            out.append({"key": "magnet_hole", "label": "Magnet pocket diameter", "value": g["hole"], "unit": "mm", "feature": "magnets",
                        "formula": "magnet diameter + 2 × clearance", "interface": True})
        return out

    def measure(self, v, faces_by_feature):
        out = []
        # the 1.8 mm straight band of each socket: opposite faces are 37.7 mm apart
        xs = sorted({round(f.center().X, 4) for f in faces_by_feature.get("sockets", []) if f.geom_type.name == "PLANE"
                     and abs(f.normal_at().X) > 0.99 and abs(f.bounding_box().size.Z - 1.8) < 0.01})
        gaps = [b - a for a, b in zip(xs, xs[1:]) if abs((b - a) - WAIST) < 1.0]
        if gaps:
            out.append({"key": "socket_waist", "label": "Socket width at its straight band", "intended": WAIST, "modelled": gaps[0]})
        if v["magnets"]:
            ds = [max(f.bounding_box().size.X, f.bounding_box().size.Y) for f in faces_by_feature.get("magnets", [])
                  if f.geom_type.name == "CYLINDER"]
            if ds:
                out.append({"key": "magnet_hole", "label": "Magnet pocket diameter", "intended": self.g(v)["hole"], "modelled": max(ds)})
        return out
