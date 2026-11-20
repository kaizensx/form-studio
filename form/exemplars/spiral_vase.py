"""Vase with spiral ribs: one smooth B-spline skin whose ribs turn a quarter turn up a bellied profile, hollowed by an
inset copy of the same ribbed body, with a weighted base and a rolled lip. Form Studio exemplar design."""
from build123d import Align, Cylinder, Pos, Torus

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Vase with spiral ribs",
    "category": "textured",
    "tags": ["vase", "spiral", "ribs", "ribbed", "fluted", "texture", "decor", "revolve", "loft", "brep texture", "pot"],
    "techniques": ["craft.spiral_ribbed_body (B-rep texture as one skin)", "hollow by a revolve inset from the rib roots (not an offset)",
                   "profile as a few (r, z) points through a spline", "rolled lip with safe_fillet"],
    "lessons": [
        "Ribs you see across a room are B-rep: craft.spiral_ribbed_body lofts sections that each carry the rib pattern "
        "turned a little further, so the whole vase is one smooth surface rather than 24 booleans.",
        "Give the profile a belly and a neck (wide at 35 %, narrow at 80 %, flaring at the lip): a straight cylinder "
        "with ribs reads as a pipe.",
        "Hollow it with a smooth revolve of the profile inset by the wall: an offset of a heavily ribbed surface is "
        "fragile and slow, a revolve is exact at the rib roots, quick, and leaves the ribs solid and stiff.",
        "Finish the lip: a rolled edge (fillet) makes it read as made, and the base is thicker for weight and a flat "
        "first layer.",
    ],
}


class Design(Recipe):
    title, summary = "Spiral vase", "Bellied vase with 24 spiral ribs, a thick base and a rolled lip."
    solids = 1
    photo_color = "#c96f4a"
    params = [
        Param("height", "Height", 180, 80, 300, 1, "mm", "form", "body"),
        Param("belly_r", "Belly radius", 52, 25, 90, 0.5, "mm", "form", "body"),
        Param("neck_r", "Neck radius", 30, 15, 70, 0.5, "mm", "form", "body"),
        Param("ribs", "Ribs", 24, 6, 48, 1, "", "form", "body"),
        Param("rib_depth", "Rib depth", 3.0, 0.8, 6, 0.1, "mm", "form", "body"),
        Param("twist", "Twist", 90, -240, 240, 5, "deg", "form", "body"),
        Param("wall", "Wall", 2.0, 1.2, 4, 0.1, "mm", "form", "hollow"),
        Param("base_t", "Base thickness", 4.0, 1.6, 10, 0.2, "mm", "form", "hollow"),
    ]
    features = [Feature("body", "Ribbed body", "structure"), Feature("hollow", "Hollow", "structure"),
                Feature("lip", "Rolled lip", "finish")]

    def constraints(self, v):
        if v["neck_r"] - v["wall"] < 8:
            return [RecipeError("The neck is too narrow to hollow", "hollow", "Widen the neck or thin the wall.",
                                ["neck_r", "wall"])]
        return []

    def _profile(self, v, inset=0.0, z0=0.0, z1=None):
        H, rb, rn = v["height"], v["belly_r"], v["neck_r"]
        base_r = rb * 0.62
        lip_r = rn * 1.18
        pts = [(base_r, 0.0), (rb * 0.92, H * 0.17), (rb, H * 0.36), (rb * 0.86, H * 0.56), (rn, H * 0.8), (lip_r, H)]
        return [(r - inset, z) for r, z in pts]

    def build(self, v):
        H, t = v["height"], v["wall"]
        n, d, tw = int(v["ribs"]), v["rib_depth"], v["twist"]
        body = craft.spiral_ribbed_body(self._profile(v), ribs=n, rib_depth=d, twist=tw, levels=16)
        stages = [Stage("body", body)]
        # the inside: a smooth revolve inset by the wall from the rib roots. The ribs stay solid (stiff, and the wall
        # is never thinner than `wall`); a revolve is a cheap, exact boolean against the ribbed skin.
        # sample the same profile curve the ribbed body follows, and inset each point along the curve's normal
        from build123d import Spline, Vector
        prof = Spline(*[Vector(r, 0, z) for r, z in self._profile(v)])
        pts = [prof.position_at(i / 60) for i in range(61)]
        inner_prof = []
        for i, p in enumerate(pts):
            q0, q1 = pts[max(i - 1, 0)], pts[min(i + 1, 60)]
            dz, dr = q1.Z - q0.Z, q1.X - q0.X
            ln = (dz * dz + dr * dr) ** 0.5 or 1.0
            if p.Z >= v["base_t"]:
                inner_prof.append((p.X - t * dz / ln, p.Z + t * dr / ln))
        inner_prof.insert(0, (inner_prof[0][0], v["base_t"]))
        inner_prof.append((inner_prof[-1][0] + 0.4, H + 2.0))
        inner = craft.revolve_profile(inner_prof, spline=True)
        body = body - inner
        stages.append(Stage("hollow", body))
        # a rolled bead round the inside of the rim: a torus half buried in the wall, so the lip reads thick and soft
        r_top = min(r for r, z in inner_prof if z > H - 3)
        body = body + Pos(0, 0, H - t * 0.75) * Torus(r_top + t * 0.1, t * 0.75)
        body = body - Pos(0, 0, H) * Cylinder(r_top + 50, 10, align=BOTTOM)            # trimmed flush with the rim
        foot = [e for e in body.edges() if abs(e.center().Z) < 0.05]
        body = craft.safe_fillet(body, foot, 1.0)
        stages.append(Stage("lip", body))
        return parts.checked(stages)

    def derived(self, v):
        return [{"key": "rib_pitch_belly", "label": "Rib pitch at the belly", "value": 2 * 3.14159 * v["belly_r"] / v["ribs"],
                 "unit": "mm", "feature": "body", "formula": "2 pi r / ribs", "interface": False}]
