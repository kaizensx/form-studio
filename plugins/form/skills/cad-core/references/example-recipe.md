```python
"""Two-part box with a press-fit lid and a cable notch. Form Studio example design."""
from build123d import Align, Axis, Box, Pos, fillet

from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Box with lid"
    summary = "Rounded box and a press-fit lid printed side by side, with a cable notch."
    solids = 2
    fit = None          # use fit when an outside object (measured param) goes into a cavity
    params = [
        Param("inner_w", "Inner width", 60, 20, 150, 0.5, "mm", "brief", "body", "What it must hold."),
        Param("inner_d", "Inner depth", 40, 20, 150, 0.5, "mm", "brief", "body"),
        Param("inner_h", "Inner height", 30, 5, 120, 0.5, "mm", "brief", "body"),
        Param("wall", "Wall", 2.0, 1.2, 5, 0.1, "mm", "form", "body"),
        Param("corner_r", "Corner radius", 4, 0.5, 12, 0.5, "mm", "form", "body"),
        Param("lid_clearance", "Lid clearance / side", 0.15, 0, 0.6, 0.05, "mm", "interface", "plug"),
        Param("notch_w", "Cable notch width", 8, 0, 20, 0.5, "mm", "form", "notch", "0 = none."),
    ]
    features = [Feature("body", "Body", "structure"), Feature("notch", "Cable notch", "access"),
                Feature("lid", "Lid", "structure"), Feature("plug", "Lid plug", "interface")]

    def constraints(self, v):
        if v["corner_r"] >= min(v["inner_w"], v["inner_d"]) / 2 + v["wall"]:
            return [RecipeError("Corner radius is larger than the box", "body", "Reduce the corner radius.", ["corner_r"])]
        if v["notch_w"] > v["inner_w"] - 6:
            return [RecipeError("Notch is wider than the wall allows", "notch", "Narrow the notch.", ["notch_w"])]
        return []

    def build(self, v):
        W, D, H, t = v["inner_w"] + 2 * v["wall"], v["inner_d"] + 2 * v["wall"], v["inner_h"] + v["wall"], v["wall"]
        outer = Box(W, D, H, align=A)
        outer = fillet(outer.edges().filter_by(Axis.Z), v["corner_r"])
        body = outer - Pos(0, 0, t) * Box(v["inner_w"], v["inner_d"], H, align=A)
        stages = [Stage("body", body)]
        if v["notch_w"] > 0:
            body = body - Pos(0, D / 2, H - 6) * Box(v["notch_w"], 3 * t, 7, align=A)
            stages.append(Stage("notch", body))
        x = W + 8                                            # lid printed beside the box, upside down = flat on the bed
        lid = Pos(x, 0, 0) * fillet(Box(W, D, t, align=A).edges().filter_by(Axis.Z), v["corner_r"])
        s = body + lid
        stages.append(Stage("lid", s))
        c = v["lid_clearance"]
        plug = Pos(x, 0, t) * Box(v["inner_w"] - 2 * c, v["inner_d"] - 2 * c, 4, align=A)
        stages.append(Stage("plug", s + plug))
        return stages

    def derived(self, v):
        return [{"key": "inner_w", "label": "Box opening width", "value": v["inner_w"], "unit": "mm", "feature": "body",
                 "formula": "inner width", "interface": True},
                {"key": "plug_w", "label": "Lid plug width", "value": v["inner_w"] - 2 * v["lid_clearance"], "unit": "mm",
                 "feature": "plug", "formula": "inner width - 2 x clearance", "interface": True}]

    def assembly(self, v):
        """The lid is printed upside down beside the box: flip it about X, move it over the box, rest it on the walls."""
        W, H, t = v["inner_w"] + 2 * v["wall"], v["inner_h"] + v["wall"], v["wall"]
        return Assembly(parts=[
            Part("box", "Box", 0, note="Set the box down, open side up."),
            Part("lid", "Lid", 1, move=(-(W + 8), 0, H + t), rotate=(180, 0, 0), explode=(0, 0, 30),
                 note="Press the lid on, plug first."),
        ])
```
