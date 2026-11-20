"""Twisted creature horn for props and costumes: one smooth loft through oval sections carried along a curling 3D
spine, tapering to a point, turning as it grows and ringed with growth ridges, on a flat base with a dowel socket and
an anti-rotation key for mounting on a helmet, mask or headband. A prop. Form Studio exemplar design.
"""

import math

from build123d import Align, Box, Cylinder, Plane, Pos, Spline, Vector, Vertex

from form import craft
from form.craft import MeshTexture
from form.craft._common import note
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Twisted creature horn",
    "category": "organic",
    "tags": ["horn", "creature", "demon", "ram", "antelope", "prop", "cosplay", "costume", "twisted", "spiral",
             "taper", "ridges", "growth rings", "organic", "loft", "sculpt", "fantasy", "mount"],
    "techniques": ["sections placed on a 3D spline spine with a rotation-minimising frame (no flips)",
                   "craft.superellipse_face on each frame's Plane, egg-shaped (squash_front) so the twist shows",
                   "growth ridges as a radius modulation of the sections (no booleans), fading at both ends",
                   "craft.loft_sections closed by a tip Vertex; organic.loft_report fold check",
                   "a dowel socket and anti-rotation key cut into the flat base",
                   "MeshTexture noise for keratin grain; appearance() zones"],
    "lessons": [
        "A horn is a cone that grows: it tapers (radius falls like (1 - u)^0.65, not linearly, so the tip stays "
        "slender and the base stays massive), curls along a 3D spine, and twists as it grows. Draw the spine first; "
        "everything else hangs on it.",
        "Place sections with a rotation-minimising frame: carry the previous section's 'up' along the spine, "
        "removing its component along the new tangent. A Frenet frame flips where the spine straightens and the "
        "loft twists into a knot.",
        "A round section hides the twist. Make it egg-shaped (a keel on one side, squash_front 0.2-0.3) and turn it "
        "a few degrees per section; the keel spirals round the horn and reads as growth. Turn the shape, not the "
        "seam: pass seam = 180 - rotate so every section still starts at the same place. If the start point turns "
        "with the shape, OCCT's loft fails past about 100 deg of twist.",
        "Growth ridges are a modulation of the section size ((0.5 + 0.5 cos)^3: narrow crests, wide valleys), with at "
        "least four sections per ridge so the loft can follow, fading out near the tip where the horn is too thin.",
        "One loft, no booleans along the length: the body is a single B-spline face, light to build and clean to "
        "print or mould. Check it with loft_report: tight curl plus thick base is where it folds.",
        "Mount it like a prop maker would: a flat base, an 8 mm dowel socket 25 mm deep (or a magnet) and a key "
        "flat so it cannot spin on its pin.",
    ],
}


def _frames(points, count):
    """count (origin, tangent, x_dir) frames along a spline through points, rotation-minimising."""
    sp = Spline(*[Vector(*p) for p in points])
    out, x = [], Vector(1, 0, 0)
    for i in range(count):
        u = i / (count - 1)
        o, t = sp.position_at(u), sp.tangent_at(u).normalized()
        x = (x - t * x.dot(t)).normalized()
        out.append((o, t, x))
    return out, sp.length


class Design(Recipe):
    title, summary = "Creature horn", ("Curling, twisting, tapering horn with growth ridges, lofted in one skin, on a "
                                       "flat base with a dowel socket and key.")
    solids = 1
    photo_color = "#d9c9a6"
    params = [
        Param("size", "Size", 1.0, 0.6, 1.5, 0.05, "", "brief", "horn", "1.0: about 260 mm along the curve."),
        Param("base_d", "Base diameter", 46, 30, 64, 1, "mm", "brief", "horn"),
        Param("curl", "Curl", 1.0, 0.6, 1.3, 0.05, "", "form", "horn",
              "How far the spine bends back and out. Below 0.6 a nearly straight spine with a thick base folds "
              "the loft."),
        Param("twist", "Twist", 120, 0, 240, 5, "deg", "form", "horn", "How far the keel turns, base to tip."),
        Param("ridges", "Growth ridges", 12, 0, 20, 1, "", "form", "ridges"),
        Param("ridge_h", "Ridge height", 0.06, 0.0, 0.1, 0.01, "", "form", "ridges", "Fraction of the radius."),
        Param("dowel_d", "Dowel diameter", 8, 5, 12, 0.5, "mm", "interface", "socket",
              "Wood dowel or steel pin; the bore is 0.2 mm over."),
    ]
    features = [Feature("horn", "Horn", "structure"), Feature("ridges", "Growth ridges", "finish"),
                Feature("socket", "Dowel socket and key", "interface")]

    def constraints(self, v):
        if v["dowel_d"] > v["base_d"] * 0.3:
            return [RecipeError("The dowel is too thick for the base", "socket", "Use a thinner dowel.", ["dowel_d"])]
        return []

    def spine(self, v):
        k, c = v["size"], v["curl"]
        pts = [(0, 0, 0), (0, 0, 30), (-6 * c, 4 * c, 70), (-28 * c, 14 * c, 108), (-62 * c, 26 * c, 126),
               (-96 * c, 36 * c, 114), (-112 * c, 44 * c, 86), (-108 * c, 50 * c, 58)]
        return [(x * k, y * k, z * k) for x, y, z in pts]

    def sections(self, v, ridged=True):
        R0 = v["base_d"] / 2
        n_r = int(v["ridges"]) if ridged else 0
        count = max(36, min(96, 5 * n_r + 16))
        frames, length = _frames(self.spine(v), count + 1)
        faces = []
        for i, (o, t, x) in enumerate(frames[:-1]):
            u = i / count
            r = R0 * (1 - u) ** 0.65 + 1.5 * u                     # tapering, slender toward the tip
            if u < 0.06:                                           # a slight flare into the base
                r *= 1 + 0.06 * (1 - u / 0.06) ** 2
            if n_r and ridged:
                fade = min(1.0, u / 0.08) * max(0.0, min(1.0, (0.88 - u) / 0.15))
                r *= 1 + v["ridge_h"] * fade * (0.5 + 0.5 * math.cos(2 * math.pi * n_r * u)) ** 3
            pl = Plane(origin=o, x_dir=x, z_dir=t)
            faces.append(craft.superellipse_face(r, r * 0.84, 2.0, plane=pl, rotate=v["twist"] * u, squash_front=0.24,
                                                 seam=180.0 - v["twist"] * u, count=48))
        tip = frames[-1][0]
        return faces + [Vertex(tip.X, tip.Y, tip.Z)], length

    def build(self, v):
        # --- snippet: a curling, twisting horn as one loft through sections on a 3D spine
        faces, length = self.sections(v, ridged=False)
        smooth = craft.loft_sections(faces)
        stages = [Stage("horn", smooth)]
        faces, length = self.sections(v, ridged=v["ridges"] > 0 and v["ridge_h"] > 0)
        horn = craft.loft_sections(faces)
        rep = craft.loft_report(horn)
        if rep["folds"]:
            note(f"loft_report: the horn folds near {rep['where'][:2]}; ease the curl or the ridges")
        # --- end snippet
        stages.append(Stage("ridges", horn))

        # base socket: a dowel bore 0.2 mm over, 25 mm deep, and a key slot that stops it spinning
        bore = Pos(0, 0, -1) * Cylinder(v["dowel_d"] / 2 + 0.1, 26, align=BOTTOM)
        # the key: a 3.2 mm slot opening off the bore, 9 mm deep, for a matching tab (or a flat filed on the dowel)
        key = Pos(v["dowel_d"] / 2 + 1.5, 0, -1) * Box(5, 3.2, 10, align=BOTTOM)
        body = craft.cut(horn, bore + key)
        stages.append(Stage("socket", body))
        return stages

    def mesh_texture(self, v):
        return [MeshTexture("noise", amplitude=0.18, scale=2.5, features=["ridges"], edge_falloff=1.0)]

    def appearance(self, v):
        return [{"features": ["socket"], "finish": "matte", "color": "#3a3128"},
                {"features": ["horn", "ridges"], "finish": "silk", "color": "#d9c9a6"}]

    def derived(self, v):
        faces, length = self.sections(v, ridged=False)
        return [{"key": "spine_length", "label": "Length along the curve", "value": round(length, 1), "unit": "mm",
                 "feature": "horn", "formula": "spline length of the spine", "interface": False},
                {"key": "bore", "label": "Dowel bore", "value": v["dowel_d"] + 0.2, "unit": "mm", "feature": "socket",
                 "formula": "dowel + 0.2 mm", "interface": True}]
