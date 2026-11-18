"""Battery and card holder: a desk or drawer tray with one pocket per battery, coin cell, memory card or USB stick.

Pick what it holds with `kind`; pockets are sized from the standard's largest allowed dimensions plus a clearance,
so any brand drops in. Cylindrical cells and 9 V blocks stand upright; coin cells and cards stand on edge in slots;
USB-A sticks stand plug-down. Finger grooves run front to back through every column so you can pinch the item.

Sizes (maximum dimensions, mm):
  AA (IEC LR6)            Ø14.5 × 50.5         AAA (IEC LR03)          Ø10.5 × 44.5
  18650 Li-ion            Ø18.6 × 65.2         CR2032 (IEC)            Ø20.0 × 3.2
  9 V (IEC 6LR61)         26.5 × 17.5 × 48.5   SD card (SD Association) 32 × 24 × 2.1
  microSD (SD Association) 15 × 11 × 1.0       USB-A plug shell        12.0 × 4.5, 12 long

Everything prints flat without support: pockets are straight down, their mouths are chamfered (they lead the item in
and face up), and the grooves are troughs that open upward.
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Box, Cylinder, Plane, Pos, chamfer, fillet

from .base import Feature, Param, Recipe, RecipeError, Stage
from .style import rbox

A = (Align.CENTER, Align.CENTER, Align.MIN)

# kind -> (name, shape, across X, across Y, standing height, source). "round": X = Y = diameter.
KINDS = {
    0: ("AA", "round", 14.5, 14.5, 50.5, "IEC 60086 LR6, maximum"),
    1: ("AAA", "round", 10.5, 10.5, 44.5, "IEC 60086 LR03, maximum"),
    2: ("18650", "round", 18.6, 18.6, 65.2, "18650 Li-ion cell, typical maximum unprotected"),
    3: ("CR2032", "slot", 20.0, 3.2, 20.0, "IEC 60086 CR2032, maximum"),
    4: ("9 V", "rect", 26.5, 17.5, 48.5, "IEC 60086 6LR61, maximum"),
    5: ("SD card", "slot", 24.0, 2.1, 32.0, "SD Association, full size card"),
    6: ("microSD", "slot", 11.0, 1.0, 15.0, "SD Association, microSD card"),
    7: ("USB-A stick", "rect", 12.0, 4.5, 12.0, "USB-A plug shell, 12 mm long; the stick stands on it"),
}


class BatteryHolder(Recipe):
    id = "battery_holder"
    title = "Battery and card holder"
    summary = ("A tray for AA, AAA, 18650, coin cells, 9 V, SD and microSD cards or USB sticks: pockets sized from the "
               "standards, finger grooves, soft edges.")
    category = "Storage"
    tags = ("battery", "AA", "AAA", "18650", "CR2032", "9V", "SD card", "microSD", "USB", "organiser", "drawer", "desk")

    params = [
        Param("kind", "Holds", 0, 0, 7, 1, "", "brief", "pockets",
              "0 = AA, 1 = AAA, 2 = 18650, 3 = CR2032 coin cell, 4 = 9 V, 5 = SD card, 6 = microSD, 7 = USB-A stick.",
              "specified"),
        Param("cols", "Columns", 4, 1, 10, 1, "", "form", "pockets", "Pockets across."),
        Param("rows", "Rows", 3, 1, 12, 1, "", "form", "pockets", "Pockets front to back. Coin cells and cards stack closely."),
        Param("clearance", "Clearance / side", 0.35, 0.1, 1.0, 0.05, "mm", "interface", "pockets",
              "Added to the standard's largest size on every side, so any brand drops in."),
        Param("depth_pct", "Pocket depth", 45, 25, 80, 1, "%", "form", "pockets",
              "Share of the item's height that sits in the pocket. Under half leaves plenty to grab."),
        Param("web", "Wall between pockets", 2.0, 1.2, 6, 0.1, "mm", "form", "pockets", "Three lines or more prints solid."),
        Param("border", "Border", 4.0, 2.0, 15, 0.5, "mm", "form", "body", "Solid rim around the pockets."),
        Param("floor", "Floor", 1.6, 1.2, 5, 0.1, "mm", "form", "body", "Under the pockets."),
        Param("corner_r", "Corner radius", 6, 3, 15, 0.5, "mm", "form", "body"),
        Param("grooves", "Finger grooves", 1, 0, 1, 1, "", "form", "grooves", "1 = a shallow trough front to back along every column, inside the rim."),
        Param("groove_w", "Groove width", 60, 30, 90, 1, "%", "form", "grooves", "Width at the top, as a share of the pocket."),
    ]
    features = [
        Feature("body", "Tray", "structure"),
        Feature("pockets", "Pockets", "interface", "Sized from the standard's maximum dimensions plus clearance."),
        Feature("grooves", "Finger grooves", "access"),
        Feature("lead_in", "Pocket lead-in", "finish", "45° chamfer at every pocket mouth."),
    ]

    @staticmethod
    def g(v):
        name, shape, ax, ay, ht, src = KINDS[int(round(v["kind"]))]
        c, w = v["clearance"], v["web"]
        px, py = ax + 2 * c, ay + 2 * c
        if shape == "slot":
            depth = round(ht * v["depth_pct"] / 100, 1)
            depth = min(depth, ht * 0.8)
        else:
            depth = round(ht * v["depth_pct"] / 100, 1)
        if shape == "rect" and name == "USB-A stick":
            depth = 10.0                                   # the plug shell stands in it; the stick's body rests on top
        nx, ny = int(round(v["cols"])), int(round(v["rows"]))
        W = nx * px + (nx - 1) * w + 2 * v["border"]
        D = ny * py + (ny - 1) * w + 2 * v["border"]
        H = depth + v["floor"]
        xs = [(i - (nx - 1) / 2) * (px + w) for i in range(nx)]
        ys = [(j - (ny - 1) / 2) * (py + w) for j in range(ny)]
        return {"name": name, "shape": shape, "ax": ax, "ay": ay, "ht": ht, "src": src, "px": px, "py": py,
                "depth": depth, "W": W, "D": D, "H": H, "xs": xs, "ys": ys, "nx": nx, "ny": ny}

    def constraints(self, v):
        out = []
        for k in ("kind", "cols", "rows", "grooves"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        if out:
            return out
        g = self.g(v)
        if g["nx"] * g["ny"] > 60:
            out.append(RecipeError(f"{g['nx'] * g['ny']} pockets is more than one tray builds quickly (60)", "pockets",
                                   "Use fewer rows or columns and print two trays.", ["cols", "rows"]))
        if max(g["W"], g["D"]) > 175:
            out.append(RecipeError(f"The tray is {g['W']:.0f} × {g['D']:.0f} mm; a 180 mm bed takes about 175", "body",
                                   "Use fewer columns or rows, and print two trays.", ["cols", "rows"]))
        # material left at the corner pocket: r - √2 (r - border) when the corner is rounder than the border is wide
        r, b = v["corner_r"], v["border"]
        if r > b and r - math.sqrt(2) * (r - b) < 1.6:
            out.append(RecipeError(f"A {r:g} mm corner leaves under 1.6 mm outside the corner pocket", "body",
                                   f"Keep the corner radius under {(math.sqrt(2) * b - 1.6) / (math.sqrt(2) - 1):.1f} mm, or widen the border.",
                                   ["corner_r", "border"]))
        if g["depth"] < 3:
            out.append(RecipeError(f"Pockets would be {g['depth']:.1f} mm deep; nothing stays in that", "pockets",
                                   "Raise the pocket depth.", ["depth_pct"]))
        return out

    def build(self, v):
        g = self.g(v)
        W, D, H, depth = g["W"], g["D"], g["H"], g["depth"]
        body = rbox(W, D, H, v["corner_r"], top=1.2)
        stages = [Stage("body", body)]
        zf = v["floor"]
        cut = None
        for x in g["xs"]:
            for y in g["ys"]:
                if g["shape"] == "round":
                    p = Pos(x, y, zf) * Cylinder(g["px"] / 2, depth + 1, align=A)
                else:
                    r = min(0.8, g["py"] / 2 - 0.05)
                    p = Pos(x, y, zf) * fillet(Box(g["px"], g["py"], depth + 1, align=A).edges().filter_by(Axis.Z), r)
                cut = p if cut is None else cut + p
        s = body - cut
        stages.append(Stage("pockets", s))

        # 45° lead-in on every pocket mouth (edges in the top plane that bound a pocket)
        try:
            # pocket mouths: every edge in the top plane inside the border (the grooves are cut after this)
            top = [e for e in s.edges() if abs(e.center().Z - H) < 1e-4 and e.bounding_box().size.Z < 1e-4
                   and abs(e.center().X) < W / 2 - v["border"] + 0.5 and abs(e.center().Y) < D / 2 - v["border"] + 0.5]
            if top:
                s = chamfer(top, min(0.6, v["web"] / 3))
                stages.append(Stage("lead_in", s))
        except Exception:
            pass
        if v["grooves"]:
            # a circular trough along Y through each column, its axis above the top so it only opens upward
            gw = v["groove_w"] / 100 * g["px"]
            gd = min(depth * 0.4, gw * 0.5)
            R = (gw * gw / 4 + gd * gd) / (2 * gd)
            tr = None
            for x in g["xs"]:
                # from the first pocket to the last: its ends fall inside those pockets, so the rim stays whole
                t = Pos(x, 0, H - gd + R) * (Plane.XZ * Cylinder(R, (g["ny"] - 1) * (g["py"] + v["web"]) + 0.5 * g["py"]))
                tr = t if tr is None else tr + t
            s = s - tr
            stages.append(Stage("grooves", s))

        return stages

    def derived(self, v):
        g = self.g(v)
        out = [{"key": "holds", "label": "Holds", "value": g["nx"] * g["ny"], "unit": "", "feature": "pockets",
                "formula": f"{g['nx']} × {g['ny']} {g['name']} ({g['src']})"},
               {"key": "tray", "label": "Tray", "value": round(g["W"], 2), "unit": "mm", "feature": "body",
                "formula": f"{g['W']:.1f} × {g['D']:.1f} × {g['H']:.1f} mm"},
               {"key": "pocket_depth", "label": "Pocket depth", "value": g["depth"], "unit": "mm", "feature": "pockets",
                "formula": f"{v['depth_pct']:g}% of {g['ht']:g} mm" if g["name"] != "USB-A stick" else "plug shell, 10 mm"}]
        if g["shape"] == "round":
            out.append({"key": "pocket_d", "label": "Pocket diameter", "value": g["px"], "unit": "mm", "feature": "pockets",
                        "formula": f"{g['ax']:g} mm + 2 × clearance", "interface": True})
        else:
            out.append({"key": "pocket_w", "label": "Pocket width", "value": g["px"], "unit": "mm", "feature": "pockets",
                        "formula": f"{g['ax']:g} mm + 2 × clearance", "interface": True})
        return out

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        faces = faces_by_feature.get("pockets", [])
        if g["shape"] == "round":
            ds = [max(f.bounding_box().size.X, f.bounding_box().size.Y) for f in faces if f.geom_type.name == "CYLINDER"]
            return [{"key": "pocket_d", "label": "Pocket diameter", "intended": g["px"], "modelled": max(ds)}] if ds else []
        xs = sorted({round(f.center().X, 4) for f in faces if f.geom_type.name == "PLANE" and abs(f.normal_at().X) > 0.99})
        gaps = [b - a for a, b in zip(xs, xs[1:]) if abs((b - a) - g["px"]) < 0.5]
        return [{"key": "pocket_w", "label": "Pocket width", "intended": g["px"], "modelled": gaps[0]}] if gaps else []

    def test_piece(self, v, shape):
        g = self.g(v)
        x, y = g["xs"][0], g["ys"][0]
        h = min(g["H"], v["floor"] + 6)
        slab = Pos(x, y, 0) * Box(g["px"] + 2 * v["web"], g["py"] + 2 * v["web"], h, align=A)
        return shape & slab, {"label": "One pocket", "doc": f"The corner pocket, {h:.0f} mm tall. Drop a {g['name']} in to check the clearance.",
                              "height": h}
