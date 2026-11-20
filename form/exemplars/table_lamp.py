"""Table lamp: a weighted revolved base, a slender stem, and a lofted shade that twists from a soft square at the
rim to a circle at the top, carried on three spokes from an E27 socket ring. Form Studio exemplar design (a 3D model)."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Lamp with lofted shade",
    "category": "consumer",
    "tags": ["lamp", "shade", "lampshade", "light", "loft", "twist", "decor", "organic", "revolve", "e27", "styled"],
    "techniques": ["craft.section_shell with open top and bottom (a shade)", "sections that morph soft square -> circle "
                   "and rotate (a twisted loft)", "revolved base with a profile spline", "spokes from a socket ring",
                   "proportions in thirds"],
    "lessons": [
        "A shade is a section loft: the rim a soft square (n ~ 4), the top a circle (n = 2), each section turned a "
        "little more, so the surface twists without a single seam or boolean.",
        "Hollow a lofted shade by insetting its sections (craft.section_shell), open at both ends; an offset of a "
        "twisted loft is fragile, the inset is exact.",
        "Proportion: base, stem and shade relate in thirds; the shade is the largest mass and the base is wide and low "
        "enough to be stable (its diameter about 0.6 of the shade's).",
        "Real interfaces stay real: the socket ring takes an E27 lampholder (40 mm body), and the cable runs down the "
        "stem bore and out through the base.",
    ],
}


class Design(Recipe):
    title, summary = "Table lamp", "Weighted base, slender stem and a twisted lofted shade on three spokes."
    solids = 1
    photo_color = "#e8e2d4"
    params = [
        Param("height", "Overall height", 360, 220, 600, 5, "mm", "form", "shade"),
        Param("shade_d", "Shade diameter at the rim", 240, 140, 400, 5, "mm", "form", "shade"),
        Param("twist", "Shade twist", 45, 0, 120, 5, "deg", "form", "shade"),
        Param("wall", "Shade wall", 1.6, 1.0, 3, 0.1, "mm", "form", "shade"),
        Param("socket_d", "Lampholder body diameter", 40, 28, 50, 0.5, "mm", "brief", "socket", "E27 lampholder.",
              "specified"),
    ]
    features = [Feature("base", "Weighted base", "structure"), Feature("stem", "Stem", "structure"),
                Feature("socket", "Socket ring and spokes", "interface"), Feature("shade", "Lofted shade", "finish")]

    def constraints(self, v):
        if v["shade_d"] < v["socket_d"] + 60:
            return [RecipeError("The shade is too small around the lampholder", "shade", "Widen the shade.", ["shade_d"])]
        return []

    def _shade_sections(self, v):
        H, D = v["height"], v["shade_d"]
        z0, z1 = H * 0.42, H                         # the shade spans the top 58 %
        secs = []
        for i in range(7):
            u = i / 6
            r = D / 2 * (1 - 0.42 * u ** 1.25)        # tapering toward the top
            secs.append({"z": z0 + (z1 - z0) * u, "a": r, "b": r, "n": 4.2 - 2.2 * u, "rotate": v["twist"] * u})
        return secs

    def build(self, v):
        H, D = v["height"], v["shade_d"]
        bd = D * 0.6
        # base: a low revolved dome with a crisp foot, bored for the stem and the cable exit
        base = craft.revolve_profile([(bd / 2, 0), (bd / 2, 4), (bd * 0.45, 14), (bd * 0.25, 24), (14, 28)], spline=False)
        base = craft.safe_fillet(base, [e for e in base.edges() if e.geom_type.name == "CIRCLE" and e.center().Z > 3], 6.0)
        stages = [Stage("base", base)]
        stem_top = H * 0.42 + 30
        stem = Cylinder(9, stem_top - 20, align=BOTTOM).moved(Pos(0, 0, 20))
        body = base + stem
        body = body - Pos(0, 0, 4) * Cylinder(4.0, stem_top, align=BOTTOM)          # cable bore
        body = body - Pos(0, -bd / 4, 5) * Box(8, bd / 2, 6)                        # cable exit to the back, under the base
        stages.append(Stage("stem", body))
        # socket ring for the lampholder at the stem top, and three spokes out to the shade rim
        zs = stem_top
        ring = Pos(0, 0, zs) * (Cylinder(v["socket_d"] / 2 + 3, 12, align=BOTTOM) - Pos(0, 0, 3) * Cylinder(v["socket_d"] / 2 + 0.3, 30, align=BOTTOM))
        ring = ring - Pos(0, 0, zs - 1) * Cylinder(4.0, 6, align=BOTTOM)          # the cable passes the ring's floor
        body = body + Pos(0, 0, -0.5) * Cylinder(9, 1, align=BOTTOM).moved(Pos(0, 0, zs)) + ring
        secs = self._shade_sections(v)
        s0, n0 = secs[0], secs[0]["n"]
        for i in range(3):
            a = 120 * i + 90
            th = math.radians(a)
            # the rim's radius in this direction (superellipse), minus half the wall: the spoke ends inside the wall
            r_rim = (abs(math.cos(th)) ** n0 / s0["a"] ** n0 + abs(math.sin(th)) ** n0 / s0["b"] ** n0) ** (-1 / n0)
            r0, r1 = v["socket_d"] / 2 + 1.0, r_rim - v["wall"] / 2
            spoke = Rot(0, 0, a) * Pos((r0 + r1) / 2, 0, zs + 4) * Box(r1 - r0, 6, 6)
            body = body + spoke
        stages.append(Stage("socket", body))
        # shade: twisted loft, hollowed by inset sections, open top and bottom; the spokes meet its inside
        lift = [dict(s, z=s["z"] + (zs + 8 - secs[0]["z"]) - 6) for s in secs]
        outer, shade = craft.section_shell(lift, v["wall"], open_bottom=True, open_top=True, count=96)
        body = body + shade
        stages.append(Stage("shade", body))
        return parts.checked(stages)

    def derived(self, v):
        return [{"key": "base_ratio", "label": "Base / shade diameter", "value": 0.6, "unit": "", "feature": "base",
                 "formula": "stability and proportion", "interface": False},
                {"key": "socket_bore", "label": "Socket ring bore", "value": v["socket_d"] + 0.6, "unit": "mm",
                 "feature": "socket", "formula": "lampholder body + 2 x 0.3 mm", "interface": True}]
