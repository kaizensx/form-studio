"""Remote control, CAD plus asset: real CAD for a maker (a kernel design, STEP) and a game prop from the same solid.

How it is made: build123d. A rounded body (plan, top and bottom fillets of three sizes); a shallow well cut round every
button and the buttons raised out of them as real geometry with rounded tops (a power button, a round pad with a centre
key, two rocker pills, a 3 x 4 number grid); a dark window recessed in the top at the front tip; a battery cover split
line and a thumb latch underneath. Its appearance() zones are the game materials' regions. The wells, the split line and
the latch are too small for LOD0's budget: the bake carries them from the full tessellation.
"""
from __future__ import annotations

TITLE = "Remote control, CAD plus asset"
ORIGINALITY = ("A generic TV remote laid out from common remote anatomy (power, navigation pad, rockers, number "
               "grid). No maker's shape, logo or button legend.")
MATERIALS = {"default": {"material": "plastic", "tint": "#2b2e33", "grain_mm": 5, "wear": 0.45},
             "buttons": {"material": "rubber", "tint": "#8a9099", "grain_mm": 2, "wear": 0.35},
             "pad": {"material": "plastic", "tint": "#c7ccd2", "grain_mm": 3, "wear": 0.4},
             "power": {"material": "rubber", "tint": "#c23a2b", "grain_mm": 2, "wear": 0.3},
             "window": {"material": "plastic", "tint": "#0b0d10", "roughness": 0.08, "wear": 0.1}}

SOURCE = '''"""A generic TV remote: a rounded body, raised buttons in shallow wells, a front window, a battery cover split
line and latch underneath. Form Studio game exemplar (form/exemplars/game/tv_remote.py)."""
from build123d import Align, Axis, Box, Cylinder, Pos, Rot, fillet

from form.recipes.base import Feature, Param, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


def pill(L, W, H):
    """A pill-shaped key (round ends), rounded on top."""
    p = Box(L - W, W, H, align=A) + Pos(-(L - W) / 2, 0, 0) * Cylinder(W / 2, H, align=A) \\
        + Pos((L - W) / 2, 0, 0) * Cylinder(W / 2, H, align=A)
    return fillet(p.edges().group_by(Axis.Z)[-1], min(0.9, H * 0.4))


def key(r, H):
    k = Cylinder(r, H, align=A)
    return fillet(k.edges().group_by(Axis.Z)[-1], min(0.9, H * 0.4, r * 0.4))


class Design(Recipe):
    title = "Remote control"
    summary = "A rounded remote body with raised buttons in wells, a front window and a battery cover."
    solids = 1
    params = [Param("length", "Length", 190, 140, 240, 1, "mm", "form", "body"),
              Param("width", "Width", 50, 40, 70, 1, "mm", "form", "body"),
              Param("thickness", "Thickness", 21, 14, 30, 0.5, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure"), Feature("wells", "Button wells", "detail"),
                Feature("buttons", "Buttons", "detail"), Feature("pad", "Navigation pad", "detail"),
                Feature("power", "Power button", "detail"), Feature("window", "Front window", "detail"),
                Feature("battery_cover", "Battery cover", "detail")]

    def keys(self, v):
        L, W, T = v["length"], v["width"], v["thickness"]
        top = T
        grid = [(L * 0.02 - i * 15.0, (j - 1) * 13.5) for i in range(4) for j in range(3)]
        return {"power": [(L * 0.40, W * 0.22, 5.0)],
                "pad": [(L * 0.20, 0.0, 12.5)],
                "rockers": [(L * 0.20 - 25.0, s * W * 0.25) for s in (-1, 1)],
                "grid": grid, "top": top}

    def build(self, v):
        L, W, T = v["length"], v["width"], v["thickness"]
        body = Box(L, W, T, align=A)
        body = fillet(body.edges().filter_by(Axis.Z), W * 0.3)
        body = fillet(body.edges().group_by(Axis.Z)[-1], T * 0.3)
        body = fillet(body.edges().group_by(Axis.Z)[0], T * 0.14)
        out = [Stage("body", body)]
        k = self.keys(v)
        wells = None
        def add(c):
            nonlocal wells
            wells = c if wells is None else wells + c
        for x, y, r in k["power"] + k["pad"]:
            add(Pos(x, y, T - 1.0) * Cylinder(r + 1.2, 3, align=A))
        for x, y in k["rockers"]:
            add(Pos(x, y, T - 1.0) * Rot(0, 0, 90) * pill(26.0, 11.0, 3))
        for x, y in k["grid"]:
            add(Pos(x, y, T - 1.0) * Cylinder(5.4, 3, align=A))
        body = body - wells
        out.append(Stage("wells", body))
        keys = None
        for x, y in k["grid"]:
            c = Pos(x, y, T - 1.0) * key(4.4, 2.6)
            keys = c if keys is None else keys + c
        for x, y in k["rockers"]:
            keys += Pos(x, y, T - 1.0) * Rot(0, 0, 90) * pill(23.5, 8.6, 2.8)
        body = body + keys
        out.append(Stage("buttons", body))
        x, y, r = k["pad"][0]
        ring = Pos(x, y, T - 1.0) * key(r, 2.4) - Pos(x, y, T - 1.0) * Cylinder(5.6, 6, align=A)
        body = body + ring + Pos(x, y, T - 1.0) * key(4.4, 3.0)
        out.append(Stage("pad", body))
        x, y, r = k["power"][0]
        body = body + Pos(x, y, T - 1.0) * key(r - 0.4, 3.0)
        out.append(Stage("power", body))
        win = Pos(L / 2 - 17.0, 0, T - 1.2) * Box(13.0, W * 0.42, 4.0, align=A)
        body = body - win
        out.append(Stage("window", body))
        cut = Pos(-L * 0.24, 0, -0.01) * Box(L * 0.4, W * 0.7, 1.0, align=A)
        inner = Pos(-L * 0.24, 0, -0.02) * Box(L * 0.4 - 1.2, W * 0.7 - 1.2, 1.2, align=A)
        latch = Pos(-L * 0.035, 0, -0.02) * Box(4, 12, 1.6, align=A)
        body = body - (cut - inner) - latch
        out.append(Stage("battery_cover", body))
        return out

    def appearance(self, v):
        return [{"features": ["buttons"], "finish": "rubber", "color": "#8a9099", "label": "buttons"},
                {"features": ["pad"], "finish": "matte", "color": "#c7ccd2", "label": "pad"},
                {"features": ["power"], "finish": "rubber", "color": "#c23a2b", "label": "power"},
                {"features": ["window"], "finish": "gloss", "color": "#0b0d10", "label": "window"}]
'''
