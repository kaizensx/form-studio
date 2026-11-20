"""Ergonomic right-hand mouse top shell: a lofted palm dome with its hump behind centre, a thumb scoop on the left
flank, split primary buttons with a wheel opening, screw bosses inside, and a fine grain texture on both flanks.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Box, Cylinder, Pos, Rot, Sphere, scale

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Ergonomic mouse shell", "Right-hand palm-grip mouse top shell with thumb scoop and split buttons."
    solids = 1
    params = [
        Param("length", "Length", 122, 100, 135, 0.5, "mm", "brief", "shell", "Hand length 180-195 mm: 120-128 mm."),
        Param("width", "Width", 66, 58, 75, 0.5, "mm", "brief", "shell"),
        Param("height", "Height", 40, 34, 46, 0.5, "mm", "brief", "shell"),
        Param("hump", "Hump behind centre", 14, 0, 30, 0.5, "mm", "form", "shell"),
        Param("wall", "Wall", 1.8, 1.2, 3, 0.1, "mm", "form", "shell"),
        Param("thumb_depth", "Thumb scoop depth", 6.0, 0, 8, 0.25, "mm", "form", "thumb"),
        Param("split", "Button split width", 0.8, 0.4, 2, 0.1, "mm", "form", "buttons"),
        Param("grain", "Flank grain depth", 0.18, 0, 0.5, 0.02, "mm", "form", "shell", "Mesh texture on the flanks."),
    ]
    features = [Feature("shell", "Palm shell, grained flanks", "structure"), Feature("thumb", "Thumb scoop", "finish"),
                Feature("buttons", "Button split and wheel opening", "access"), Feature("bosses", "Screw bosses", "interface")]

    def constraints(self, v):
        if v["height"] > v["width"] * 0.75:
            return [RecipeError("Taller than three quarters of its width reads as a dome, not a mouse", "shell",
                                "Lower the height or widen it.", ["height", "width"])]
        return []

    def _sections(self, v):
        L, W, H = v["length"], v["width"], v["height"]
        secs, tip = craft.dome_sections(L, W, H - 3.0, levels=9, crown_back=v["hump"], squash_front=0.06, n_base=2.6,
                                        n_top=2.1, z0=3.0, power=2.4)
        # a short straight skirt at the bottom so the shell meets the base plate square
        base = dict(secs[0])
        secs = [{**base, "z": 0.0}] + secs
        # right-hand asymmetry: the thumb side (+Y) bulges low, the little-finger side (-Y) falls away
        for s in secs:
            k = max(0.0, 1 - (s["z"] / H) * 1.6)
            s["cy"] = s.get("cy", 0.0) + 1.6 * k            # 2.5 folds the smooth loft near the base (invalid booleans)
        return secs, tip

    def build(self, v):
        L, W, H, t = v["length"], v["width"], v["height"], v["wall"]
        secs, tip = self._sections(v)
        outer = craft.section_body(secs, tip=tip)
        inner = craft.inset_body(secs, t, tip=tip, open_bottom=True)
        shell = outer - inner
        stages = [Stage("shell", shell)]
        # thumb scoop: a flattened ellipsoid pressed into the left flank; shape and round the OUTSIDE, then hollow
        if v["thumb_depth"] > 0:
            r = 34.0
            at = Pos(-L * 0.06, W / 2 + r - v["thumb_depth"] + 1.6, H * 0.36)
            outer = outer - at * scale(Sphere(r), (1.2, 1.0, 0.6))
            edge = [e for e in outer.edges() if e.center().Y > W * 0.25 and 3 < e.center().Z < H * 0.8]
            outer = craft.safe_fillet(outer, edge, 4.0)
            inner = inner - at * scale(Sphere(r + t), ((1.2 * r + t) / (r + t), 1.0, (0.6 * r + t) / (r + t)))
            shell = outer - inner
        self._outer = outer
        stages.append(Stage("thumb", shell))
        # buttons: one centre split from the nose back to the palm, two side splits, and the wheel opening
        bl = L * 0.42
        x0 = L / 2 - bl
        # buttons stay joined to the shell behind x0 (they flex there) and are free along the sides and the centre
        for y in (0.0, -W * 0.3, W * 0.28):
            shell = shell - Pos(x0 + (bl - 7) / 2, y, H * 0.42) * Box(bl - 7, v["split"], H, align=BOTTOM)
        wheel = Pos(L / 2 - 26, 0, H * 0.5) * Box(22, 9.5, H, align=BOTTOM)
        wheel = craft.safe_fillet(wheel, wheel.edges().filter_by(lambda e: abs(e.tangent_at(0.5).Z) > 0.99), 3.0)
        shell = shell - wheel
        stages.append(Stage("buttons", shell))
        # screw bosses: posts from the inside of the dome down to the bottom plane, with 2.5 mm self-tap pilots
        for (bx, by) in ((-L * 0.3, 0), (L * 0.12, -W * 0.28), (L * 0.12, W * 0.24)):
            post = (Pos(bx, by, 1.0) * Cylinder(3.4, H, align=BOTTOM)) & self._outer
            post = post - Pos(bx, by, 0.5) * Cylinder(1.25, 10, align=BOTTOM)
            shell = shell + post
        stages.append(Stage("bosses", shell))
        return stages

    def mesh_texture(self, v):
        if v["grain"] <= 0:
            return []
        L, W, H = v["length"], v["width"], v["height"]
        # both flanks, below the shoulder line; the buttons and the palm stay smooth
        return [MeshTexture("grain", amplitude=v["grain"], scale=1.2, features=["shell", "thumb"], facing="out",
                            region=((-L, W * 0.22, 0.5), (L, W, H * 0.62)), edge_falloff=3.0),
                MeshTexture("grain", amplitude=v["grain"], scale=1.2, features=["shell"], facing="out",
                            region=((-L, -W, 0.5), (L, -W * 0.22, H * 0.62)), edge_falloff=3.0)]

    def derived(self, v):
        return [{"key": "palm_hump_x", "label": "Hump position from the back", "value": round(v["length"] / 2 - v["hump"], 1),
                 "unit": "mm", "feature": "shell", "formula": "L/2 - hump", "interface": False}]
