"""Gridfinity bin: the storage bin of Zack Freedman's open Gridfinity system.

Dimensions follow the published Gridfinity specification: a 42 mm grid, 7 mm height units, the stepped foot
(0.8 mm 45° chamfer, 1.8 mm straight, 2.15 mm 45° chamfer: 4.75 mm) and the stacking lip that takes the feet of the
bin above. Magnet pockets (6 × 2 mm discs) and M3 screw holes sit on the spec's 26 mm square under every foot.

Print rules: the downward-facing 45° chamfers are drawn a little steeper (42°: same widths as the spec, the straight
part of the foot is 0.3 mm shorter) so no facet of them faces down past 45°; the step under the lip, the label tab and the scoop all rise
at 45° or less; the only bridges are the magnet and screw pocket roofs and the 0.5 mm grooves between feet.
Fitting a given baseplate is a claim to test with one printed foot (the test piece), not something this file proves.
"""
from __future__ import annotations

from build123d import Align, Axis, Box, Cylinder, Plane, Polygon, Pos, RectangleRounded, extrude, fillet, loft

from .base import Feature, Param, Recipe, RecipeError, Stage

PITCH = 42.0         # grid pitch, mm (spec)
UNIT_H = 7.0         # height unit, mm (spec)
GAP = 0.5            # a bin is 42 n - 0.5 mm wide (spec)
FOOT_H = 4.75        # 0.8 chamfer + 1.8 straight + 2.15 chamfer (spec)
FOOT_TOP = 41.5      # foot width where it meets the body (spec)
OUTER_R = 3.75       # outer corner radius (spec)
LIP_H = 4.0          # spec lip is 4.4 mm to a knife edge; stopped 0.4 mm short so the rim is a printable 0.8 mm
LIP_IN = 3.0         # inset of the lip's inner face at its foot, from the outer wall
MAG_OFF = 13.0       # magnet / screw positions: ±13 mm from each foot's centre (26 mm square, spec)
SCREW_D = 3.0        # M3 tapping hole for baseplate screws (spec)
SCREW_DEPTH = 6.0    # spec screw-hole depth from the underside
STEEP = 1.1          # rise / run of every "45°" chamfer that faces down (42°), so no tessellated facet tips past 45°


def _rr(w, d, r, z):
    r = max(0.3, min(r, w / 2 - 0.01, d / 2 - 0.01))
    return Plane.XY.offset(z) * RectangleRounded(w, d, r)


def foot():
    """One Gridfinity foot, 41.5 mm square at the top, standing on z = 0."""
    # spec widths (35.6, 37.2, 41.5 mm); the two chamfers rise 10% more than they run, eating into the straight part
    c1, c2 = 0.8, 2.15
    waist = FOOT_TOP - 2 * c2
    base = waist - 2 * c1
    return loft([_rr(base, base, OUTER_R - c1 - c2, 0), _rr(waist, waist, OUTER_R - c2, c1 * STEEP),
                 _rr(waist, waist, OUTER_R - c2, FOOT_H - c2 * STEEP), _rr(FOOT_TOP, FOOT_TOP, OUTER_R, FOOT_H)], ruled=True)


class GridfinityBin(Recipe):
    id = "gridfinity_bin"
    title = "Gridfinity bin"
    summary = ("A bin for the 42 mm Gridfinity grid: spec feet and stacking lip, compartments, scoops, a label tab, "
               "and magnet or screw pockets under every foot.")
    category = "Storage"
    tags = ("gridfinity", "bin", "organiser", "drawer", "workshop", "magnets", "modular")
    fit = {"cavity": "magnet_hole", "mating": "magnet_d", "clearance": "magnet_clearance",
           "label": "Magnet pocket ↔ magnet", "per_side": True, "window": [0.0, 0.6]}

    params = [
        Param("grid_x", "Width", 2, 1, 4, 1, "u", "form", "body", "Grid units across, 42 mm each. 4 u is the most a 180 mm bed takes."),
        Param("grid_y", "Depth", 1, 1, 4, 1, "u", "form", "body", "Grid units front to back, 42 mm each."),
        Param("height_u", "Height", 6, 3, 20, 1, "u", "form", "body",
              "Height units of 7 mm, feet included, lip not. 3 u fits under a lid, 6 u is the common drawer bin."),
        Param("compart_x", "Compartments across", 2, 1, 8, 1, "", "form", "dividers", "Columns of compartments, left to right."),
        Param("compart_y", "Compartments front to back", 1, 1, 6, 1, "", "form", "dividers", "Rows of compartments."),
        Param("wall", "Wall", 1.25, 1.2, 2.4, 0.05, "mm", "form", "cavity", "Three lines of a 0.4 mm nozzle (1.25 mm leaves the slicer room for all three)."),
        Param("divider_t", "Divider thickness", 1.25, 1.2, 2.4, 0.05, "mm", "form", "dividers"),
        Param("floor", "Floor", 1.2, 0.8, 6, 0.1, "mm", "form", "cavity",
              "Solid floor above the feet. Screw holes need 2.45 mm or more (they are 6 mm deep from the underside)."),
        Param("scoop", "Scoop", 1, 0, 1, 1, "", "form", "scoop", "1 = a curved front in every compartment, so small parts slide out."),
        Param("scoop_r", "Scoop radius", 12, 4, 25, 0.5, "mm", "form", "scoop",
              "Larger is easier to scoop from; it takes floor space. A short or crowded compartment gets a smaller one."),
        Param("label", "Label tab", 1, 0, 1, 1, "", "form", "label", "1 = an angled tab along the back of each row for a 12 mm label."),
        Param("label_w", "Label tab depth", 12, 6, 20, 0.5, "mm", "form", "label",
              "How far the tab reaches in from the back wall. A short bin gets a shallower tab (its underside rises at 45°)."),
        Param("lip", "Stacking lip", 1, 0, 1, 1, "", "interface", "lip", "1 = the spec lip, so another bin stacks on top; 0 = a flat, rounded rim."),
        Param("magnets", "Magnet pockets", 1, 0, 1, 1, "", "interface", "magnets", "1 = four pockets under every foot."),
        Param("magnet_d", "Magnet diameter", 6.0, 3, 10, 0.05, "mm", "brief", "magnets",
              "Gridfinity uses 6 × 2 mm neodymium discs. Measure yours; they vary by a tenth.", "specified"),
        Param("magnet_h", "Magnet thickness", 2.0, 1, 4, 0.05, "mm", "brief", "magnets", "", "specified"),
        Param("magnet_clearance", "Magnet clearance / side", 0.15, -0.1, 0.4, 0.01, "mm", "interface", "magnets",
              "0.15 takes a drop of glue; 0 or less is a press fit that depends on your printer."),
        Param("screws", "Screw holes", 0, 0, 1, 1, "", "interface", "screws",
              "1 = M3 holes, 6 mm deep, on the magnet positions: screw the bin to a baseplate."),
    ]
    features = [
        Feature("feet", "Feet", "interface", "Spec stepped profile that seats in a Gridfinity baseplate or another bin's lip."),
        Feature("body", "Body", "structure"),
        Feature("cavity", "Cavity", "access"),
        Feature("lip", "Stacking lip", "interface", "Receives the feet of the bin above."),
        Feature("dividers", "Dividers", "structure"),
        Feature("scoop", "Scoops", "access"),
        Feature("label", "Label tabs", "access"),
        Feature("magnets", "Magnet pockets", "interface"),
        Feature("screws", "Screw holes", "interface"),
    ]

    # ---- geometry ----------------------------------------------------------------------------------
    @staticmethod
    def g(v):
        nx, ny = int(round(v["grid_x"])), int(round(v["grid_y"]))
        W, D = PITCH * nx - GAP, PITCH * ny - GAP
        top = UNIT_H * v["height_u"]
        zf = FOOT_H + v["floor"]
        Wi, Di = W - 2 * v["wall"], D - 2 * v["wall"]
        st = max(0.0, LIP_IN - v["wall"]) if v["lip"] >= 0.5 else 0.0       # inward step under the lip
        z_div = top - st * STEEP - 1.0 if v["lip"] >= 0.5 else top - 1.0      # dividers stop below the rim
        cx, cy = int(round(v["compart_x"])), int(round(v["compart_y"]))
        t = v["divider_t"]
        cd = (Di - (cy - 1) * t) / cy
        usable = z_div - zf
        # the tab and the scoop shrink to fit a short or crowded bin, so every height works at the defaults:
        # the tab's underside must end 3 mm above the floor, the scoop stay under the rim, and the two leave 4 mm between
        lw = min(v["label_w"], (usable - 3 - 1.6) / STEEP, cd * 0.5) if v["label"] >= 0.5 else 0.0
        lw = lw if lw >= 4 else 0.0
        sr = min(v["scoop_r"], usable - 3, cd * 0.6, cd - 4 - lw) if v["scoop"] >= 0.5 else 0.0
        sr = sr if sr >= 3 else 0.0
        return {"nx": nx, "ny": ny, "W": W, "D": D, "top": top, "zf": zf, "Wi": Wi, "Di": Di, "st": st, "z_div": z_div,
                "ri": max(0.6, OUTER_R - v["wall"]), "cx": cx, "cy": cy, "lw": lw, "sr": sr,
                "cw": (Wi - (cx - 1) * t) / cx, "cd": cd,
                "hole": v["magnet_d"] + 2 * v["magnet_clearance"], "mag_depth": v["magnet_h"] + 0.2}

    def constraints(self, v):
        out = []
        for k in ("grid_x", "grid_y", "height_u", "compart_x", "compart_y", "scoop", "label", "lip", "magnets", "screws"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        if out:
            return out
        g = self.g(v)
        usable = g["z_div"] - g["zf"]
        if usable < 6:
            out.append(RecipeError(f"Only {usable:.1f} mm of usable depth inside", "cavity", "Add a height unit or thin the floor.",
                                   ["height_u", "floor"]))
        if min(g["cw"], g["cd"]) < 10:
            out.append(RecipeError(f"Compartments would be {g['cw']:.0f} × {g['cd']:.0f} mm; 10 mm is the least a finger reaches into",
                                   "dividers", "Use fewer compartments or a bigger bin.", ["compart_x", "compart_y", "grid_x", "grid_y"]))
        if v["magnets"] and g["mag_depth"] > FOOT_H - 1.0:
            out.append(RecipeError("Magnet pockets would cut through the foot", "magnets", "Use thinner magnets.", ["magnet_h"]))
        if v["magnets"] and g["hole"] / 2 + MAG_OFF > FOOT_TOP / 2 - 2.15 - 0.8:
            out.append(RecipeError("Magnet pockets run into the foot chamfer", "magnets", "Use smaller magnets.", ["magnet_d"]))
        if v["screws"] and SCREW_DEPTH > g["zf"] - 1.2 + 1e-9:
            out.append(RecipeError("6 mm screw holes would leave under 1.2 mm of floor above them", "screws",
                                   "Raise the floor to 2.45 mm or more.", ["floor", "screws"]))
        return out

    def _feet_at(self, g):
        return [((i - (g["nx"] - 1) / 2) * PITCH, (j - (g["ny"] - 1) / 2) * PITCH) for i in range(g["nx"]) for j in range(g["ny"])]

    def build(self, v):
        g = self.g(v)
        W, D, top, zf, Wi, Di, st, ri = g["W"], g["D"], g["top"], g["zf"], g["Wi"], g["Di"], g["st"], g["ri"]
        lip = v["lip"] >= 0.5
        one = foot()
        feet = None
        for x, y in self._feet_at(g):
            feet = Pos(x, y, 0) * one if feet is None else feet + Pos(x, y, 0) * one
        stages = [Stage("feet", feet)]

        body = Pos(0, 0, FOOT_H) * Box(W, D, top - FOOT_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        body = fillet(body.edges().filter_by(Axis.Z), OUTER_R)
        s = feet + body
        stages.append(Stage("body", s))

        # the cavity: straight walls, then (under a lip) a step inward that rises steeper than 45°
        if lip:
            rise = st * STEEP
            secs = [_rr(Wi, Di, ri, zf), _rr(Wi, Di, ri, top - rise), _rr(Wi - 2 * st, Di - 2 * st, max(0.6, ri - st), top)]
        else:
            secs = [_rr(Wi, Di, ri, zf), _rr(Wi, Di, ri, top + 1)]
        s = s - loft(secs, ruled=True)
        stages.append(Stage("cavity", s))

        if lip:
            ring = Pos(0, 0, top) * Box(W, D, LIP_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
            ring = fillet(ring.edges().filter_by(Axis.Z), OUTER_R)
            b0 = LIP_IN
            # from the foot of the lip up: 0.7 chamfer out, 1.8 straight, chamfer out to the 0.8 mm rim (spec, truncated)
            cut = loft([_rr(W - 2 * b0, D - 2 * b0, max(0.6, OUTER_R - b0), top - 0.001),
                        _rr(W - 2 * b0 + 1.4, D - 2 * b0 + 1.4, max(0.6, OUTER_R - b0 + 0.7), top + 0.7),
                        _rr(W - 2 * b0 + 1.4, D - 2 * b0 + 1.4, max(0.6, OUTER_R - b0 + 0.7), top + 2.5),
                        _rr(W - 1.6, D - 1.6, OUTER_R - 0.8, top + LIP_H + 0.001)], ruled=True)
            s = (s + ring) - cut
            stages.append(Stage("lip", s))
        else:
            try:
                s = fillet([e for e in s.edges() if abs(e.center().Z - top) < 1e-4 and e.bounding_box().size.Z < 1e-4], 0.5)
            except Exception:
                pass
            stages.append(Stage("lip", s))

        # compartments: dividers stop 1 mm under the label tabs (2 mm under the rim), with a rounded top
        cx, cy, t, zd = g["cx"], g["cy"], v["divider_t"], g["z_div"]
        zw = zd - 1.0
        clip = Pos(0, 0, zf - 0.01) * Box(Wi + 0.02, Di + 0.02, zd - zf + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
        xs = [-Wi / 2 + k * (g["cw"] + t) - t / 2 for k in range(1, cx)]
        ys = [-Di / 2 + k * (g["cd"] + t) - t / 2 for k in range(1, cy)]
        if xs or ys:
            walls = None
            for x in xs:
                w = Pos(x, 0, zf - 0.01) * Box(t, Di + 1, zw - zf + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
                walls = w if walls is None else walls + w
            for y in ys:
                w = Pos(0, y, zf - 0.01) * Box(Wi + 1, t, zw - zf + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
                walls = w if walls is None else walls + w
            walls = walls & clip
            try:
                walls = fillet(walls.edges().group_by(Axis.Z)[-1], t / 2 - 0.05)
            except Exception:
                pass
            s = s + walls
            stages.append(Stage("dividers", s))

        # rows: the front edge (y0) and back edge (y1) of each row of compartments
        rows = []
        for j in range(cy):
            y0 = -Di / 2 + j * (g["cd"] + t)
            rows.append((y0, y0 + g["cd"]))
        if g["sr"] > 0:
            r = g["sr"]
            sc = None
            for y0, _ in rows:
                blk = Pos(0, y0 - 0.01, zf - 0.01) * Box(Wi + 1, r + 0.01, r + 0.01, align=(Align.CENTER, Align.MIN, Align.MIN))
                cyl = Pos(0, y0 + r, zf + r) * (Plane.YZ * Cylinder(r, Wi + 2))
                piece = blk - cyl
                sc = piece if sc is None else sc + piece
            s = s + (sc & clip)
            stages.append(Stage("scoop", s))

        if g["lw"] > 0:
            lw, nose, ztab = g["lw"], 1.6, zd
            tabs = None
            for _, y1 in rows:
                # flat top, a 1.6 mm nose, then an underside that rises back to the wall steeper than 45°
                prof = Plane.YZ * Polygon((y1 + 0.01, ztab), (y1 - lw, ztab), (y1 - lw, ztab - nose),
                                          (y1 + 0.01, ztab - nose - lw * STEEP), align=None)
                tab = extrude(prof, amount=Wi / 2 + 0.5, both=True)
                tabs = tab if tabs is None else tabs + tab
            s = s + (tabs & clip)
            stages.append(Stage("label", s))

        if v["magnets"]:
            holes = None
            for x, y in self._feet_at(g):
                for dx in (-MAG_OFF, MAG_OFF):
                    for dy in (-MAG_OFF, MAG_OFF):
                        c = Pos(x + dx, y + dy, -0.01) * Cylinder(g["hole"] / 2, g["mag_depth"] + 0.01,
                                                                 align=(Align.CENTER, Align.CENTER, Align.MIN))
                        holes = c if holes is None else holes + c
            s = s - holes
            stages.append(Stage("magnets", s))

        if v["screws"]:
            holes = None
            for x, y in self._feet_at(g):
                for dx in (-MAG_OFF, MAG_OFF):
                    for dy in (-MAG_OFF, MAG_OFF):
                        c = Pos(x + dx, y + dy, -0.01) * Cylinder(SCREW_D / 2, SCREW_DEPTH + 0.01,
                                                                 align=(Align.CENTER, Align.CENTER, Align.MIN))
                        holes = c if holes is None else holes + c
            s = s - holes
            stages.append(Stage("screws", s))
        return stages

    # ---- reporting ---------------------------------------------------------------------------------
    def derived(self, v):
        g = self.g(v)
        out = [
            {"key": "outer_w", "label": "Outer width", "value": g["W"], "unit": "mm", "feature": "body", "formula": "42 × units − 0.5"},
            {"key": "outer_d", "label": "Outer depth", "value": g["D"], "unit": "mm", "feature": "body", "formula": "42 × units − 0.5"},
            {"key": "height", "label": "Height", "value": g["top"] + (LIP_H if v["lip"] >= 0.5 else 0), "unit": "mm", "feature": "body",
             "formula": "7 × height units + lip"},
            {"key": "compartment", "label": "Compartment", "value": round(g["cw"], 2), "unit": "mm", "feature": "dividers",
             "formula": f"{g['cw']:.1f} × {g['cd']:.1f} mm, {g['z_div'] - g['zf']:.1f} mm deep"},
            {"key": "magnet_hole", "label": "Magnet pocket diameter", "value": g["hole"], "unit": "mm", "feature": "magnets",
             "formula": "magnet diameter + 2 × clearance", "interface": True},
            {"key": "scoop_built", "label": "Scoop radius as built", "value": round(g["sr"], 2), "unit": "mm", "feature": "scoop",
             "formula": "scoop radius, limited by the compartment's height and depth"},
            {"key": "label_built", "label": "Label tab as built", "value": round(g["lw"], 2), "unit": "mm", "feature": "label",
             "formula": "tab depth, limited so its underside ends 3 mm above the floor"},
        ]
        spans = [0.5]                                              # grooves between neighbouring feet
        if v["magnets"]:
            spans.append(g["hole"])
        if v["screws"]:
            spans.append(SCREW_D)
        out.append({"key": "bridge_span", "label": "Widest bridge", "value": max(spans), "unit": "mm", "feature": "feet",
                    "formula": "magnet or screw pocket roof, or the 0.5 mm groove between feet"})
        if v["screws"]:
            out.append({"key": "screw_hole", "label": "Screw hole", "value": SCREW_D, "unit": "mm", "feature": "screws",
                        "formula": "M3 tapping size, 6 mm deep (spec)", "interface": True})
        return out

    def measure(self, v, faces_by_feature):
        out = []
        for feat, key, label, want in (("magnets", "magnet_hole", "Magnet pocket diameter", self.g(v)["hole"]),
                                       ("screws", "screw_hole", "Screw hole", SCREW_D)):
            if not v[feat]:
                continue
            ds = [max(f.bounding_box().size.X, f.bounding_box().size.Y) for f in faces_by_feature.get(feat, [])
                  if f.geom_type.name == "CYLINDER"]
            if ds:
                out.append({"key": key, "label": label, "intended": want, "modelled": max(ds)})
        return out

    def test_piece(self, v, shape):
        g = self.g(v)
        x, y = self._feet_at(g)[0]
        h = g["zf"]
        slab = Pos(x, y, 0) * Box(PITCH, PITCH, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return shape & slab, {"label": "One foot", "doc": f"The first foot and {v['floor']:g} mm of floor, with its pockets. "
                              "Checks the magnets and how the foot seats in your baseplate.", "height": h}
