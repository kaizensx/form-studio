"""Control knob for a potentiometer or encoder shaft (D-flat or round), press fit or set screw with a captive nut.

Printed top-down: the face you touch sits on the bed, so the bore opens upward and needs no support. Shaft
defaults are the common 6 mm D-shaft of 9 mm potentiometers (flat to 4.5 mm); measure yours.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Cone, Cylinder, Pos, Rot

from .. import parts
from .base import Feature, Param, Recipe, RecipeError, Stage
from ..parts import checked

A = (Align.CENTER, Align.CENTER, Align.MIN)
SKIRT_SLOPE = 1.25       # skirt cone height per mm of overhang: about 39° from vertical


class Knob(Recipe):
    id = "knob"
    title = "Control knob"
    summary = ("A knurled knob for a D-flat or round shaft: press fit or an M3 set screw in a captive nut, "
               "a pointer line and an optional skirt. Printed face down, no supports.")
    fit = {"cavity": "bore_d", "mating": "shaft_d", "clearance": "shaft_clearance",
           "label": "Bore ↔ shaft", "per_side": True, "window": [0.0, 0.4]}

    params = [
        Param("shaft_d", "Shaft diameter", 6.0, 3, 12, 0.05, "mm", "brief", "bore",
              "6 mm is the usual potentiometer / encoder shaft. Measure it.", "specified"),
        Param("shaft_type", "Shaft type", 1, 0, 1, 1, "", "brief", "flat", "1 = D-flat, 0 = round."),
        Param("shaft_flat", "Across the flat", 4.5, 2, 11, 0.05, "mm", "brief", "flat",
              "From the flat to the far side of the shaft. 4.5 mm on a 6 mm D-shaft.", "specified"),
        Param("shaft_clearance", "Shaft clearance / side", 0.1, -0.1, 0.4, 0.01, "mm", "interface", "bore",
              "Small or negative for a press fit; more when a set screw holds it."),
        Param("bore_depth", "Bore depth", 12, 4, 30, 0.5, "mm", "brief", "bore", "How far the shaft goes in."),
        Param("knob_d", "Knob diameter", 25, 10, 60, 0.5, "mm", "form", "body"),
        Param("knob_h", "Knob height", 16, 8, 40, 0.5, "mm", "form", "body"),
        Param("grip_n", "Grip grooves", 24, 0, 60, 1, "", "form", "grip", "0 = smooth."),
        Param("grip_depth", "Grip groove depth", 0.8, 0.3, 2, 0.05, "mm", "form", "grip"),
        Param("skirt", "Skirt overhang", 3, 0, 8, 0.5, "mm", "form", "skirt", "A flange at the panel end. 0 = none."),
        Param("skirt_h", "Skirt height", 2.5, 1, 6, 0.1, "mm", "form", "skirt"),
        Param("pointer", "Pointer line", 1, 0, 1, 1, "", "form", "pointer", "A groove on the top, in line with the flat."),
        Param("set_screw", "Set screw", 1, 0, 1, 1, "", "interface", "set_screw",
              "1 = M3 set screw through the side into a captive M3 nut, 0 = press fit only."),
        Param("edge", "Top edge chamfer", 0.8, 0, 3, 0.1, "mm", "form", "body"),
    ]
    features = [
        Feature("body", "Body", "structure"),
        Feature("skirt", "Skirt", "finish"),
        Feature("grip", "Grip grooves", "finish"),
        Feature("pointer", "Pointer line", "access"),
        Feature("bore", "Shaft bore", "interface"),
        Feature("flat", "D flat", "interface"),
        Feature("set_screw", "Set screw hole", "interface"),
        Feature("nut", "Captive nut", "interface"),
    ]

    @staticmethod
    def g(v):
        R = v["knob_d"] / 2
        bore = v["shaft_d"] + 2 * v["shaft_clearance"]
        flat_y = v["shaft_flat"] - v["shaft_d"] / 2 + v["shaft_clearance"]     # flat plane, from the axis
        H = v["knob_h"]
        cone_h = v["skirt"] * SKIRT_SLOPE
        skirt_total = (cone_h + v["skirt_h"]) if v["skirt"] > 0 else 0.0
        # set screw: mid-way along the shaft, but below the skirt when there is room, and fully on the shaft
        corner_r = parts.nut_trap("M3", "hex", clearance=0.15)["pocket_corner_d"] / 2
        lo = H - v["bore_depth"] + corner_r + 1.0
        hi = (H - skirt_total - 1.7 - 0.8) if skirt_total else H
        z_screw = max(lo, min(H - v["bore_depth"] / 2, hi))
        return {"R": R, "bore": bore, "flat_y": flat_y, "H": H, "skirt_total": skirt_total, "cone_h": cone_h,
                "z_screw": z_screw, "corner_r": corner_r}

    def _nut(self):
        return parts.nut_trap("M3", "hex", clearance=0.15)

    def _screw(self, v):
        return parts.screw_clearance("M3", self.g(v)["R"] + v["skirt"] + 2, head="socket", fit="normal", recess=False)

    def _nut_y(self, v, nut):
        """Nut centred in the wall between the bore and the grip (on the flat side, +Y)."""
        g = self.g(v)
        inner = g["flat_y"] if v["shaft_type"] else g["bore"] / 2
        return (inner + g["R"] - v["grip_depth"]) / 2

    def constraints(self, v):
        out = []
        for k in ("shaft_type", "grip_n", "pointer", "set_screw"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        if out:
            return out
        g = self.g(v)
        if v["shaft_type"] and not (v["shaft_d"] / 2 < v["shaft_flat"] < v["shaft_d"] - 0.2):
            out.append(RecipeError("The flat must be between the shaft's centre and its far side", "flat",
                                   "Measure across the flat: on a 6 mm D-shaft it is about 4.5 mm.", ["shaft_flat", "shaft_d"]))
        if v["bore_depth"] > g["H"] - 1.6:
            out.append(RecipeError("The bore leaves under 1.6 mm at the top of the knob", "bore", "Make the knob taller or the bore shallower.",
                                   ["bore_depth", "knob_h"]))
        if g["R"] - v["grip_depth"] - g["bore"] / 2 < 2:
            out.append(RecipeError("The knob wall around the shaft is under 2 mm", "body", "Make the knob wider.", ["knob_d", "shaft_d"]))
        if g["skirt_total"] > g["H"] - 3:
            out.append(RecipeError("The skirt is taller than the knob allows", "skirt", "Reduce the skirt or make the knob taller.",
                                   ["skirt", "skirt_h", "knob_h"]))
        if v["grip_n"]:
            pitch = 2 * math.pi * g["R"] / v["grip_n"]
            if pitch < 2.5 * v["grip_depth"] or pitch < 1.6:
                out.append(RecipeError("Grip grooves are too close to print", "grip", "Use fewer or shallower grooves.", ["grip_n", "grip_depth"]))
            if pitch > g["R"]:
                out.append(RecipeError("Too few grip grooves for this diameter", "grip", "Use more grooves, or 0 for a smooth knob.", ["grip_n"]))
        if v["set_screw"]:
            nut = self._nut()
            inner = g["flat_y"] if v["shaft_type"] else g["bore"] / 2
            wall = g["R"] - v["grip_depth"] - inner
            if wall < nut["depth"] + 2.4:
                out.append(RecipeError(f"The wall ({wall:.1f} mm) is too thin for the M3 nut and 1.2 mm on each side", "nut",
                                       "Make the knob wider, or use a press fit.", ["knob_d", "set_screw"]))
            if g["z_screw"] + g["corner_r"] > g["H"] - 0.5 or g["z_screw"] - 1.7 < g["H"] - v["bore_depth"] + 0.5:
                out.append(RecipeError("The bore is too shallow for the set screw nut", "nut", "Deepen the bore.", ["bore_depth"]))
        return out

    def build(self, v):
        g = self.g(v)
        R, H, e = g["R"], g["H"], v["edge"]
        # body: chamfered top edge on the bed, straight wall up to the skirt
        z_sk = H - g["skirt_total"]
        body = Cylinder(R, H, align=A)
        if e > 0:
            body = Cone(R - e, R, e, align=A) + Pos(0, 0, e - 0.01) * Cylinder(R, H - e + 0.01, align=A)
        stages = [Stage("body", body)]
        s = body
        if g["skirt_total"]:
            k, sh = v["skirt"], v["skirt_h"]
            ch = g["cone_h"]                                                       # steeper than 45° so it prints unsupported
            sk = Pos(0, 0, z_sk) * Cone(R - 0.01, R + k, ch, align=A) + Pos(0, 0, z_sk + ch - 0.01) * Cylinder(R + k, sh + 0.01, align=A)
            s = s + sk
            stages.append(Stage("skirt", s))
        if v["grip_n"]:
            n, dpt = int(v["grip_n"]), v["grip_depth"]
            rg = max(dpt * 1.25, math.pi * R / n * 0.45)                        # groove radius: half a pitch, at least deep enough
            zc = (z_sk - 0.6) if g["skirt_total"] else H + 1
            grooves = None
            for i in range(n):
                a = 2 * math.pi * (i + 0.5) / n + math.pi / 2                  # a land, not a groove, faces the pointer
                c = Pos((R + rg - dpt) * math.cos(a), (R + rg - dpt) * math.sin(a), -1) * Cylinder(rg, zc + 1, align=A)
                if g["skirt_total"]:                                               # pointed end: no flat ceiling under the skirt
                    c = c + Pos((R + rg - dpt) * math.cos(a), (R + rg - dpt) * math.sin(a), zc - 0.01) * Cone(rg, rg * 0.25, rg * 0.9, align=A)
                grooves = c if grooves is None else grooves + c
            s = s - grooves
            stages.append(Stage("grip", s))
        if v["pointer"]:
            L = R * 0.55
            s = s - Pos(0, R - L / 2 + 0.5, -0.1) * Box(1.2, L + 1, 0.9, align=A)
            stages.append(Stage("pointer", s))
        b = g["bore"]
        bore = Pos(0, 0, H - v["bore_depth"]) * Cylinder(b / 2, v["bore_depth"] + 0.1, align=A)
        bore = bore + Pos(0, 0, H - 0.6) * Cone(b / 2, b / 2 + 0.6, 0.61, align=A)                # lead-in
        s = s - bore
        stages.append(Stage("bore", s))
        if v["shaft_type"]:
            w = b + 2
            fill = Pos(0, g["flat_y"], H - v["bore_depth"] - 0.01) * Box(w, b, v["bore_depth"] - 0.6, align=(Align.CENTER, Align.MIN, Align.MIN))
            fill = fill & (Pos(0, 0, H - v["bore_depth"] - 0.01) * Cylinder(b / 2 + 0.05, v["bore_depth"], align=A))
            s = s + fill
            stages.append(Stage("flat", s))
        if v["set_screw"]:
            zs = g["z_screw"]
            hole = Pos(0, 0, zs) * Rot(90, 0, 0) * self._screw(v).shape        # cutter axis -Z turned to +Y: bore to outside
            s = s - hole
            stages.append(Stage("set_screw", s))
            nut = self._nut()
            ny = self._nut_y(v, nut)
            trap = parts.nut_trap("M3", "hex", clearance=0.15, slot=H - zs + 1)
            # nut axis (local Z) onto Y, insertion slot (local +X) up to the open end of the knob
            s = s - Pos(0, ny - nut["depth"] / 2, zs) * (Rot(0, -90, 0) * Rot(90, 0, 0) * trap.shape)
            stages.append(Stage("nut", s))
        return checked(stages)

    def derived(self, v):
        g = self.g(v)
        rows = [
            {"key": "bore_d", "label": "Bore diameter", "value": g["bore"], "unit": "mm", "feature": "bore",
             "formula": "shaft + 2 × clearance", "interface": True},
            {"key": "flat_offset", "label": "Bore flat from axis", "value": g["flat_y"], "unit": "mm", "feature": "flat",
             "formula": "across-flat − shaft radius + clearance"},
            {"key": "outer_d", "label": "Outside diameter", "value": v["knob_d"] + 2 * (v["skirt"] if g["skirt_total"] else 0),
             "unit": "mm", "feature": "skirt", "formula": "knob + 2 × skirt"},
        ]
        if v["set_screw"]:
            rows.append({"key": "set_screw_len", "label": "Set screw length (M3)", "value": round(g["R"] - (g["flat_y"] if v["shaft_type"] else g["bore"] / 2) - 1.0),
                         "unit": "mm", "feature": "set_screw", "formula": "wall to the flat, sunk 1 mm below the grip"})
            rows += self._nut().derived("nut", "nut.")
        return rows

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        ds = [max(f.bounding_box().size.X, f.bounding_box().size.Y) for f in faces_by_feature.get("bore", [])
              if f.geom_type.name == "CYLINDER" and f.bounding_box().size.Z > 1]
        out = [{"key": "bore_d", "label": "Bore diameter", "intended": g["bore"], "modelled": max(ds)}] if ds else []
        ys = [f.center().Y for f in faces_by_feature.get("flat", []) if f.geom_type.name == "PLANE"
              and abs(f.normal_at().Y) > 0.99]
        if ys and v["shaft_type"]:
            out.append({"key": "flat_offset", "label": "Bore flat from axis", "intended": g["flat_y"], "modelled": min(ys)})
        return out

    def statics(self, v, solid_volume_mm3, com):
        g = self.g(v)
        checks = []
        if v["set_screw"]:
            nut = self._nut()
            ny = self._nut_y(v, nut)
            inner = g["flat_y"] if v["shaft_type"] else g["bore"] / 2
            w_in = ny - nut["depth"] / 2 - inner
            w_out = g["R"] - v["grip_depth"] - (ny + nut["depth"] / 2)
            w = min(w_in, w_out)
            checks.append({"id": "nut_wall", "label": "Wall around the captive nut", "value": f"{w:.1f} mm",
                           "status": "PASS" if w >= 1.2 else "FAIL",
                           "detail": f"{w_in:.1f} mm to the bore, {w_out:.1f} mm to the grip. ISO 4032 M3 nut, 5.5 mm across "
                                     "flats (specified), pocket +0.15 mm per side (assumed). Target ≥ 1.2 mm (3 lines).",
                           "evidence": "computed", "feature": "nut"})
        if v["shaft_type"]:
            depth = v["shaft_d"] - v["shaft_flat"]
            checks.append({"id": "flat_depth", "label": "D-flat depth", "value": f"{depth:.2f} mm",
                           "status": "PASS" if depth >= 0.8 else "WARN",
                           "detail": "How far the flat cuts into the shaft. Under 0.8 mm the knob can slip under torque.",
                           "evidence": "computed", "feature": "flat"})
        return {"checks": checks} if checks else None

    def test_piece(self, v, shape):
        g = self.g(v)
        h = min(6.0, v["bore_depth"])
        slab = Pos(0, 0, g["H"] - h) * Cylinder(g["R"] + v["skirt"] + 1, h, align=A)
        piece = Pos(0, 0, -(g["H"] - h)) * (shape & slab)
        return piece, {"label": "Shaft ring", "doc": f"The last {h:g} mm of the knob around the bore opening. Checks the fit on "
                       "the shaft before printing the whole knob.", "height": h}
