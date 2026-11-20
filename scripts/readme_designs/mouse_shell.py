"""An ergonomic mouse shell: a dome lofted through rounded sections, with a thumb scoop, split buttons and a wheel slot, hollowed to a wall.

Drawn in the README. Built by Form Studio through create_design, like any agent-written design.
"""
from build123d import Align, Box, RectangleRounded, Plane, Pos, Sphere, loft

from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)

# (height as a share of the body height, width share, length share, shift back as a share of the length)
SECTIONS = ((0.0, 1.0, 1.0, 0.0), (0.3, 0.98, 0.97, 0.02), (0.62, 0.86, 0.84, 0.07), (0.86, 0.62, 0.6, 0.13),
            (1.0, 0.3, 0.3, 0.17))


class Design(Recipe):
    title = "Ergonomic mouse shell"
    summary = "A lofted mouse shell with a thumb scoop, split buttons and a wheel slot, hollowed to an even wall."
    params = [
        Param("length", "Length", 118, 90, 140, 0.5, "mm", "brief", "body", "Hand length sets it."),
        Param("width", "Width", 64, 50, 80, 0.5, "mm", "brief", "body"),
        Param("height", "Height", 38, 28, 48, 0.5, "mm", "form", "body"),
        Param("wall", "Wall", 1.8, 1.2, 4, 0.1, "mm", "form", "body"),
        Param("scoop", "Thumb scoop depth", 4, 0, 10, 0.5, "mm", "form", "scoop"),
        Param("gap", "Button gap", 1.2, 0.6, 3, 0.1, "mm", "interface", "buttons"),
    ]
    features = [Feature("body", "Shell", "structure"), Feature("scoop", "Thumb scoop", "finish"),
                Feature("buttons", "Button split", "interface"), Feature("wheel", "Wheel slot", "access")]

    def constraints(self, v):
        if v["height"] > v["width"] * 0.75:
            return [RecipeError("The shell is taller than it is comfortable to hold", "body", "Lower the height.",
                                ["height", "width"])]
        return []

    def build(self, v):
        L, W, H = v["length"], v["width"], v["height"]
        t = v["wall"]

        def dome(inset, z0):
            secs = [Plane.XY.offset(z0 + (H - t * inset - z0) * z) * Pos(0, -L * back, 0)
                    * RectangleRounded(W * w - 2 * t * inset, L * l - 2 * t * inset, min(W * w, L * l) * 0.42 - t * inset) for z, w, l, back in SECTIONS]
            return loft(secs)
        outer, inner = dome(0, 0), dome(1, -1)        # the inner dome, one wall in, opens through the floor
        body = outer - inner
        stages = [Stage("body", body)]
        if v["scoop"] > 0:                            # a dent, not a hole: the inner dome is scooped one wall further in
            R = 70.0
            at = Pos(-W / 2 - R + v["scoop"], -L * 0.08, H * 0.42)
            body = (outer - at * Sphere(R)) - (inner - at * Sphere(R + t))
            stages.append(Stage("scoop", body))
        g = v["gap"]
        body = body - Pos(0, L * 0.3, 0) * Box(g, L * 0.4, H * 1.2, align=A)
        stages.append(Stage("buttons", body))
        body = body - Pos(0, L * 0.18, H * 0.5) * Box(7.5, 22, H, align=A)
        stages.append(Stage("wheel", body))
        return stages
