"""Drawer divider, made by Form Studio's drawer_divider generator: an insert that fills a drawer (its inside size
less a clearance) and divides it into rows and columns of compartments with rounded corners, so small things can be
swept out with a finger. A drawer larger than the bed takes several inserts side by side: set the width and depth
to one share of the drawer."""
from build123d import Align, Axis, Box, Pos

from form import craft
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

MAKE = {
    "generator": "drawer_divider",
}


class Design(Recipe):
    title, summary = "Drawer divider", "An insert that fills a drawer and divides it into rounded compartments."
    category, tags = "Makers", ("drawer", "divider", "insert")
    params = [
        Param("width", "Drawer width", 160, 40, 175, 0.5, "mm", "brief", "insert", "Inside the drawer, left to right."),
        Param("depth", "Drawer depth", 160, 40, 175, 0.5, "mm", "brief", "insert", "Inside the drawer, front to back."),
        Param("height", "Height", 45, 15, 120, 0.5, "mm", "form", "insert"),
        Param("clearance", "Clearance / side", 0.5, 0, 3, 0.1, "mm", "interface", "insert",
              "Room on each side so the insert drops in."),
        Param("cols", "Columns", 3, 1, 8, 1, "", "form", "compartments"),
        Param("rows", "Rows", 1, 1, 8, 1, "", "form", "compartments"),
        Param("wall", "Wall", 1.6, 1.2, 4, 0.1, "mm", "form", "compartments", "Outer wall and dividers. 1.6 mm is four lines "
              "of a 0.4 mm nozzle."),
        Param("floor", "Floor", 1.6, 1.2, 4, 0.1, "mm", "form", "insert"),
        Param("radius", "Inside radius", 6, 0, 20, 0.5, "mm", "form", "compartments", "Rounds every compartment's corners."),
    ]
    features = [Feature("insert", "Insert", "structure"), Feature("compartments", "Compartments", "structure")]

    def _cell(self, v):
        W = v["width"] - 2 * v["clearance"]
        D = v["depth"] - 2 * v["clearance"]
        c, r, t = int(round(v["cols"])), int(round(v["rows"])), v["wall"]
        return W, D, c, r, (W - (c + 1) * t) / c, (D - (r + 1) * t) / r

    def constraints(self, v):
        W, D, c, r, cw, cd = self._cell(v)
        if min(cw, cd) < 10:
            return [RecipeError(f"Compartments would be {min(cw, cd):.1f} mm wide", "compartments",
                                "Use fewer rows or columns, or a larger insert.", ["cols", "rows"])]
        return []

    def build(self, v):
        W, D, c, r, cw, cd = self._cell(v)
        t, H = v["wall"], v["height"]
        outer = Box(W, D, H, align=BOTTOM)
        outer = craft.safe_fillet(outer, outer.edges().filter_by(Axis.Z), min(v["radius"] + t, 25))
        stages = [Stage("insert", outer)]
        rr = min(v["radius"], min(cw, cd) / 2 - 0.5)
        pockets = None
        for i in range(c):
            for j in range(r):
                x = -W / 2 + t + cw / 2 + i * (cw + t)
                y = -D / 2 + t + cd / 2 + j * (cd + t)
                p = Box(cw, cd, H, align=BOTTOM)
                if rr > 0.2:
                    p = craft.safe_fillet(p, p.edges().filter_by(Axis.Z), rr)
                    p = craft.safe_fillet(p, p.edges().group_by(Axis.Z)[0], min(rr, H - v["floor"] - 1) * 0.6)
                p = Pos(x, y, v["floor"]) * p
                pockets = p if pockets is None else pockets + p
        body = craft.cut(outer, pockets)
        stages.append(Stage("compartments", body))
        return stages

    def derived(self, v):
        W, D, c, r, cw, cd = self._cell(v)
        return [{"key": "cell_w", "label": "Compartment width", "value": round(cw, 2), "unit": "mm", "feature": "compartments",
                 "formula": "(insert width - (columns + 1) x wall) / columns", "interface": False},
                {"key": "cell_d", "label": "Compartment depth", "value": round(cd, 2), "unit": "mm", "feature": "compartments",
                 "formula": "(insert depth - (rows + 1) x wall) / rows", "interface": False},
                {"key": "insert_w", "label": "Insert width", "value": round(W, 2), "unit": "mm", "feature": "insert",
                 "formula": "drawer width - 2 x clearance", "interface": True}]
