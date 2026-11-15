"""Gridfinity-style storage bin.

Dimensions follow the openly published Gridfinity system (42 mm grid, 7 mm
height units, stepped foot profile, stacking lip). Compatibility with a given
baseplate is a claim to test with a printed bin, not something this file proves.
"""
from __future__ import annotations

from build123d import Align, Axis, Box, Cylinder, Plane, Polygon, Pos, RectangleRounded, extrude, loft

from .base import Feature, Param, Recipe, RecipeError, Stage

PITCH = 42.0
UNIT_H = 7.0
FOOT_H = 4.75                       # 0.8 chamfer + 1.8 straight + 2.15 chamfer
FOOT_TOP = 41.5
OUTER_R = 3.75
LIP_H = 4.0          # published lip is 4.4 mm; truncated 0.4 mm so its rim is 0.8 mm (two perimeters), profile below unchanged


def _rr(w, d, r, z):
    r = max(0.3, min(r, w / 2 - 0.01, d / 2 - 0.01))
    return Plane.XY.offset(z) * RectangleRounded(w, d, r)


class GridfinityBin(Recipe):
    id = "gridfinity"
    title = "Gridfinity-style bin"
    summary = "A storage bin on the 42 mm Gridfinity grid: stepped feet, stacking lip, optional dividers, scoop, label shelf and magnet pockets."
    fit = {"cavity": "magnet_hole", "mating": "magnet_d", "clearance": "magnet_clearance",
           "label": "Magnet pocket ↔ magnet", "per_side": True, "window": [0.0, 0.25]}

    params = [
        Param("grid_x", "Grid units wide", 2, 1, 6, 1, "u", "form", "body", "Multiples of 42 mm."),
        Param("grid_y", "Grid units deep", 1, 1, 6, 1, "u", "form", "body", "Multiples of 42 mm."),
        Param("height_u", "Height units", 6, 2, 15, 1, "u", "form", "body", "Multiples of 7 mm, measured without the lip."),
        Param("wall", "Wall", 1.2, 0.8, 2.6, 0.05, "mm", "form", "cavity", "Two or three nozzle widths prints cleanly."),
        Param("floor", "Floor above feet", 1.0, 0.6, 6, 0.1, "mm", "form", "cavity"),
        Param("lip", "Stacking lip", 1, 0, 1, 1, "", "interface", "lip", "1 = lip that the bin above locks into, 0 = flat top."),
        Param("dividers_x", "Dividers across", 1, 0, 5, 1, "", "form", "dividers"),
        Param("dividers_y", "Dividers front-back", 0, 0, 5, 1, "", "form", "dividers"),
        Param("divider_t", "Divider thickness", 1.2, 0.8, 3, 0.05, "mm", "form", "dividers"),
        Param("scoop_r", "Scoop radius", 10, 0, 25, 0.5, "mm", "form", "scoop", "Rounds the front floor edge so parts slide out. 0 = none."),
        Param("label_w", "Label shelf depth", 12, 0, 20, 0.5, "mm", "form", "label", "Angled shelf along the back wall for a label. 0 = none."),
        Param("magnets", "Magnet pockets", 1, 0, 1, 1, "", "interface", "magnets", "1 = four pockets under every foot."),
        Param("magnet_d", "Magnet diameter", 6.0, 3, 10, 0.05, "mm", "brief", "magnets", "Measure your magnets; 6 × 2 mm is the usual size."),
        Param("magnet_h", "Magnet thickness", 2.0, 1, 4, 0.05, "mm", "brief", "magnets"),
        Param("magnet_clearance", "Magnet clearance / side", 0.05, -0.1, 0.4, 0.01, "mm", "interface", "magnets",
              "Small or negative for a press fit."),
    ]
    features = [
        Feature("feet", "Feet", "interface", "Stepped profile that seats in a Gridfinity baseplate."),
        Feature("body", "Body", "structure"),
        Feature("cavity", "Cavity", "access"),
        Feature("lip", "Stacking lip", "interface", "Receives the feet of the bin above."),
        Feature("dividers", "Dividers", "structure"),
        Feature("scoop", "Scoop", "access"),
        Feature("label", "Label shelf", "access"),
        Feature("magnets", "Magnet pockets", "interface"),
    ]

    @staticmethod
    def g(v):
        nx, ny = int(round(v["grid_x"])), int(round(v["grid_y"]))
        W, D = PITCH * nx - 0.5, PITCH * ny - 0.5
        top = UNIT_H * v["height_u"]
        z_floor = FOOT_H + v["floor"]
        Wi, Di = W - 2 * v["wall"], D - 2 * v["wall"]
        lip_in = 3.0                                     # lip cavity is inset this much per side at its base
        return {"nx": nx, "ny": ny, "W": W, "D": D, "top": top, "z_floor": z_floor, "Wi": Wi, "Di": Di,
                "ri": max(0.5, OUTER_R - v["wall"]), "lip_in": lip_in,
                "step": max(0.0, lip_in - v["wall"]),        # inward step under the lip, printed as a 45° chamfer
                "hole": v["magnet_d"] + 2 * v["magnet_clearance"]}

    def constraints(self, v):
        out = []
        for k in ("grid_x", "grid_y", "height_u", "lip", "dividers_x", "dividers_y", "magnets"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole units.", [k]))
        if out:
            return out
        g = self.g(v)
        if g["W"] > 175 or g["D"] > 175:
            out.append(RecipeError(f"Bin is {g['W']:.0f} × {g['D']:.0f} mm; the plate allows about 175 mm", "body",
                                   "Use fewer grid units.", ["grid_x", "grid_y"]))
        usable = g["top"] - g["z_floor"] - g["step"]
        if usable < 5:
            out.append(RecipeError(f"Only {usable:.1f} mm of usable depth", "cavity", "Add a height unit or thin the floor.", ["height_u", "floor"]))
        if v["scoop_r"] > usable - 1:
            out.append(RecipeError("Scoop is taller than the usable depth", "scoop", "Reduce the scoop radius.", ["scoop_r", "height_u"]))
        if v["label_w"] and v["label_w"] > g["Di"] / 2:
            out.append(RecipeError("Label shelf covers more than half the depth", "label", "Make the shelf shallower.", ["label_w"]))
        cx = g["Wi"] / (int(v["dividers_x"]) + 1)
        cy = g["Di"] / (int(v["dividers_y"]) + 1)
        if min(cx, cy) < 8 + v["divider_t"]:
            out.append(RecipeError(f"Compartments would be {min(cx, cy) - v['divider_t']:.1f} mm wide", "dividers",
                                   "Use fewer dividers or a bigger bin.", ["dividers_x", "dividers_y", "grid_x", "grid_y"]))
        if v["magnets"] and v["magnet_h"] + 0.4 > FOOT_H + v["floor"] - 0.6:
            out.append(RecipeError("Magnet pockets would break through the floor", "magnets", "Raise the floor or use thinner magnets.",
                                   ["magnet_h", "floor"]))
        if v["magnets"] and g["hole"] / 2 + 13 > FOOT_TOP / 2 - 2.95 - 0.8:
            out.append(RecipeError("Magnet pockets run into the foot chamfer", "magnets", "Use smaller magnets.", ["magnet_d"]))
        return out

    def build(self, v):
        g = self.g(v)
        W, D, top, zf = g["W"], g["D"], g["top"], g["z_floor"]
        feet = None
        for i in range(g["nx"]):
            for j in range(g["ny"]):
                x = (i - (g["nx"] - 1) / 2) * PITCH
                y = (j - (g["ny"] - 1) / 2) * PITCH
                f = Pos(x, y, 0) * loft([_rr(35.6, 35.6, 0.8, 0), _rr(37.2, 37.2, 1.6, 0.8), _rr(37.2, 37.2, 1.6, 2.6),
                                        _rr(FOOT_TOP, FOOT_TOP, OUTER_R, FOOT_H)], ruled=True)
                feet = f if feet is None else feet + f
        stages = [Stage("feet", feet)]

        body = Pos(0, 0, FOOT_H) * Box(W, D, top - FOOT_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        body = body.fillet(OUTER_R, body.edges().filter_by(Axis.Z))
        s = feet + body
        stages.append(Stage("body", s))

        # cavity: straight walls, then a 45° chamfer inward so the lip above needs no support
        Wi, Di, ri, st = g["Wi"], g["Di"], g["ri"], g["step"]
        if v["lip"]:
            secs = [_rr(Wi, Di, ri, zf), _rr(Wi, Di, ri, top - st), _rr(Wi - 2 * st, Di - 2 * st, max(0.5, ri - st), top)]
        else:
            secs = [_rr(Wi, Di, ri, zf), _rr(Wi, Di, ri, top + 1)]
        cav = loft(secs, ruled=True)
        s = s - cav
        stages.append(Stage("cavity", s))

        if v["lip"]:
            ring = Pos(0, 0, top) * Box(W, D, LIP_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
            ring = ring.fillet(OUTER_R, ring.edges().filter_by(Axis.Z))
            b0 = g["lip_in"]
            lipcut = loft([_rr(W - 2 * b0, D - 2 * b0, max(0.5, OUTER_R - b0), top - 0.001),
                           _rr(W - 2 * b0 + 1.4, D - 2 * b0 + 1.4, max(0.5, OUTER_R - b0 + 0.7), top + 0.7),
                           _rr(W - 2 * b0 + 1.4, D - 2 * b0 + 1.4, max(0.5, OUTER_R - b0 + 0.7), top + 2.5),
                           _rr(W - 1.6 + 0.02, D - 1.6 + 0.02, OUTER_R - 0.8, top + LIP_H + 0.01)], ruled=True)
            s = (s + ring) - lipcut
            stages.append(Stage("lip", s))

        z_top_div = top - (st if v["lip"] else 0) - 0.5
        clip = Pos(0, 0, zf) * Box(Wi, Di, z_top_div - zf, align=(Align.CENTER, Align.CENTER, Align.MIN))
        z_div = z_top_div - 1.5            # dividers stop below the label shelf so the two stay separate faces
        clip_div = Pos(0, 0, zf) * Box(Wi, Di, z_div - zf, align=(Align.CENTER, Align.CENTER, Align.MIN))
        nx_d, ny_d = int(v["dividers_x"]), int(v["dividers_y"])
        if nx_d or ny_d:
            walls = None
            for k in range(1, nx_d + 1):
                x = -Wi / 2 + k * Wi / (nx_d + 1)
                w = Pos(x, 0, zf) * Box(v["divider_t"], Di + 1, z_div - zf, align=(Align.CENTER, Align.CENTER, Align.MIN))
                walls = w if walls is None else walls + w
            for k in range(1, ny_d + 1):
                y = -Di / 2 + k * Di / (ny_d + 1)
                w = Pos(0, y, zf) * Box(Wi + 1, v["divider_t"], z_div - zf, align=(Align.CENTER, Align.CENTER, Align.MIN))
                walls = w if walls is None else walls + w
            s = s + (walls & clip_div)
            stages.append(Stage("dividers", s))

        if v["scoop_r"] > 0:
            r = v["scoop_r"]
            blk = Pos(0, -Di / 2, zf) * Box(Wi, r, r, align=(Align.CENTER, Align.MIN, Align.MIN))
            cyl = Pos(0, -Di / 2 + r, zf + r) * (Plane.YZ * Cylinder(r, Wi + 2))
            s = s + ((blk - cyl) & clip)
            stages.append(Stage("scoop", s))

        if v["label_w"] > 0:
            lw = v["label_w"]
            yb, zt = Di / 2, z_top_div
            tri = Plane.YZ * Polygon((yb, zt), (yb - lw, zt), (yb - lw, zt - 1.2), (yb, zt - 1.2 - lw), align=None)   # blunt 1.2 mm nose, 45° underside
            wedge = extrude(tri, amount=Wi / 2, both=True)
            s = s + (wedge & clip)
            stages.append(Stage("label", s))

        if v["magnets"]:
            holes = None
            for i in range(g["nx"]):
                for j in range(g["ny"]):
                    cx = (i - (g["nx"] - 1) / 2) * PITCH
                    cy = (j - (g["ny"] - 1) / 2) * PITCH
                    for dx in (-13, 13):
                        for dy in (-13, 13):
                            hcyl = Pos(cx + dx, cy + dy, -0.01) * Cylinder(g["hole"] / 2, v["magnet_h"] + 0.21,
                                                                          align=(Align.CENTER, Align.CENTER, Align.MIN))
                            holes = hcyl if holes is None else holes + hcyl
            s = s - holes
            stages.append(Stage("magnets", s))
        return stages

    def derived(self, v):
        g = self.g(v)
        return [
            {"key": "outer_w", "label": "Outer width", "value": g["W"], "unit": "mm", "feature": "body", "formula": "42 × units − 0.5"},
            {"key": "outer_d", "label": "Outer depth", "value": g["D"], "unit": "mm", "feature": "body", "formula": "42 × units − 0.5"},
            {"key": "height", "label": "Height without lip", "value": g["top"], "unit": "mm", "feature": "body", "formula": "7 × height units"},
            {"key": "usable_depth", "label": "Usable depth", "value": g["top"] - g["z_floor"] - g["step"], "unit": "mm", "feature": "cavity",
             "formula": "height − feet − floor − lip step"},
            {"key": "magnet_hole", "label": "Magnet pocket diameter", "value": g["hole"], "unit": "mm", "feature": "magnets",
             "formula": "magnet diameter + 2 × clearance", "interface": True},
        ]

    def measure(self, v, faces_by_feature):
        if not v["magnets"]:
            return []
        ds = []
        for f in faces_by_feature.get("magnets", []):
            if f.geom_type.name == "CYLINDER":
                bb = f.bounding_box()
                ds.append(max(bb.size.X, bb.size.Y))
        if not ds:
            return []
        return [{"key": "magnet_hole", "label": "Magnet pocket diameter", "intended": self.g(v)["hole"], "modelled": max(ds)}]

    def test_piece(self, v, shape):
        g = self.g(v)
        cx = -(g["nx"] - 1) / 2 * PITCH
        cy = -(g["ny"] - 1) / 2 * PITCH
        h = FOOT_H + v["floor"]
        slab = Pos(cx, cy, 0) * Box(PITCH, PITCH, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
        piece = shape & slab
        return piece, {"label": "One foot", "doc": f"The first foot and {h:.1f} mm of floor, with its magnet pockets. "
                       "Checks magnet fit and how the foot seats in your baseplate.", "height": h}
