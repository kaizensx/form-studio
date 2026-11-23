"""Small speaker: a soft cube with a perforated grille set into its face behind a shadow gap, three flush controls on
the top on a rhythm, and a recessed rubber foot. Form Studio exemplar design (premium everyday object, original;
the enclosure only, no acoustic claims)."""
from build123d import Align, Axis, Box, Cylinder, Pos, Rot, extrude

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

UP = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Small speaker: soft cube, inset grille, flush controls",
    "category": "consumer",
    "tags": ["speaker", "bluetooth speaker", "smart speaker", "audio", "grille", "perforation", "controls", "buttons",
             "premium", "beautiful", "soft cube", "shadow gap", "hex grid", "three material", "everyday"],
    "techniques": ["a near-square superellipse (n = 6) plan: flat faces with soft, curvature-continuous corners",
                   "a grille plate set into a pocket with a constant 0.8 mm gap all round: the shadow gap",
                   "perforations on a staggered grid clipped to the plate's outline, cut as one compound tool",
                   "controls: three domed keys in recesses at equal pitch on the top, the middle one larger",
                   "appearance(): matte body, dark metal grille, rubber keys and foot"],
    "lessons": [
        "Archetype: a soft cube. The corners are where it is made or lost: a superellipse plan (n 5-7) keeps the faces "
        "flat for the grille and the corners soft, with no fillet seam where the highlight breaks.",
        "A grille set INTO the body with a 0.6-1 mm gap all round reads as precision; a grille flush with the face, "
        "or proud of it, reads as a cover.",
        "Perforations: a staggered (hex) grid, hole about 55-65 % of the pitch, stopped a full pitch from the plate's "
        "edge; build them as one compound tool and cut once.",
        "Controls on a rhythm: three keys at equal pitch on the centreline, the main one larger. Asymmetric control "
        "layouts look accidental on a symmetric object.",
        "Three tiers: R big on the body's top and bottom edges, R small on the grille plate and key recesses, the "
        "keys' domes as the detail.",
        "Fillet the body before cutting the grille pocket: the pocket then never meets a fillet it would break.",
    ],
}


class Design(FeatureDesign):
    title, summary = "Cube speaker", "A soft cube with an inset perforated grille, three flush keys and a rubber foot."
    params = [
        Param("size", "Width and depth", 92, 60, 160, 1, "mm", "form", "body"),
        Param("height", "Height", 98, 60, 180, 1, "mm", "form", "body"),
        Param("edge_r", "Top and bottom radius", 9, 3, 16, 0.5, "mm", "form", "body", "Tier 1."),
        Param("gap", "Grille gap", 0.8, 0.4, 1.5, 0.05, "mm", "form", "grille", "The shadow gap round the grille."),
        Param("hole", "Perforation diameter", 2.4, 1.2, 4, 0.1, "mm", "form", "grille"),
        Param("pitch", "Perforation pitch", 4.0, 2.5, 7, 0.1, "mm", "form", "grille"),
    ]

    def setup(self, v):
        a = v["size"] / 2
        gw, gh = v["size"] - 22, v["height"] - 30                       # grille plate outline
        return {"a": a, "gw": gw, "gh": gh, "gz": 3 + v["height"] / 2 - 2, "foot_h": 3.0}

    def constraints(self, v):
        if v["hole"] > v["pitch"] * 0.75:
            return [RecipeError("Perforations nearly touch", "grille", "Smaller holes or a larger pitch.",
                                ["hole", "pitch"])]
        return []

    @feature("Body")                                       # skeleton: the soft cube above the foot
    def body(self, v, body):
        c = self.ctx
        plan = craft.superellipse_face(c["a"], c["a"], 6.0, count=120)
        b = Pos(0, 0, c["foot_h"]) * extrude(plan, v["height"] - c["foot_h"])
        b = craft.safe_fillet(b, b.edges().group_by(Axis.Z)[-1], v["edge_r"])
        return craft.safe_fillet(b, b.edges().group_by(Axis.Z)[0], v["edge_r"] * 0.45)

    def _plate(self, v, w, h, r, depth, x0):
        """A rounded rectangle in the YZ plane, extruded along -X from x0 (the front face is +X)."""
        from build123d import Plane, RectangleRounded
        prof = Plane.YZ * RectangleRounded(w, h, r)
        return Pos(x0, 0, self.ctx["gz"]) * Rot(0, 0, 0) * extrude(prof, -depth)

    @feature("Grille", role="interface")
    def grille(self, v, body):
        c = self.ctx
        a = c["a"]
        # --- snippet: an inset grille plate behind a constant shadow gap
        pocket = self._plate(v, c["gw"], c["gh"], 8, 4.0, a + 2)            # cut 2 mm into the face
        body = craft.safe_cut(body, pocket)
        g = v["gap"]
        plate = self._plate(v, c["gw"] - 2 * g, c["gh"] - 2 * g, 8 - g, 2.6, a - 0.6)   # face 0.6 mm below the body
        plate = craft.safe_fillet(plate, plate.edges().group_by(Axis.X)[-1], 0.5)
        body = craft.safe_union(body, plate)
        # --- end snippet
        return body

    @feature("Perforation", role="finish")
    def perforation(self, v, body):
        c = self.ctx
        a, p, hr = c["a"], v["pitch"], v["hole"] / 2
        # --- snippet: a staggered perforation clipped to the plate outline, one compound cut
        ny, nz = int((c["gw"] - 4 * p) / p), int((c["gh"] - 4 * p) / (p * 0.866))
        holes = []
        for j in range(nz + 1):
            z = c["gz"] + (j - nz / 2) * p * 0.866
            off = p / 2 if j % 2 else 0.0
            for i in range(ny + 1):
                y = (i - ny / 2) * p + off
                if abs(y) > c["gw"] / 2 - 2 * p:
                    continue
                holes.append(Pos(a - 0.6, y, z) * Rot(0, 90, 0) * Cylinder(hr, 2.4))
        from build123d import Compound
        return craft.safe_cut(body, Compound(holes))
        # --- end snippet

    @feature("Keys", role="interface")
    def keys(self, v, body):
        top, out = v["height"], body
        for k, d in ((-1, 9.0), (0, 13.0), (1, 9.0)):
            x = k * 18.0
            out = craft.safe_cut(out, Pos(x, 0, top - 1.2) * Cylinder(d / 2 + 0.7, 4, align=UP))
            key = Pos(x, 0, top - 1.4) * Cylinder(d / 2, 1.6, align=UP)
            key = craft.safe_fillet(key, key.edges().group_by(Axis.Z)[-1], d * 0.08)
            out = craft.safe_union(out, key)
        return out

    @feature("Foot", role="structure")
    def foot(self, v, body):
        c = self.ctx
        plan = craft.superellipse_face(c["a"] - 4, c["a"] - 4, 6.0, count=120)
        f = extrude(plan, c["foot_h"] + 0.5)
        f = craft.safe_fillet(f, f.edges().group_by(Axis.Z)[0], 0.8)
        return craft.safe_union(body, f)

    def appearance(self, v):
        return [{"features": ["body"], "finish": "matte", "color": "#d8d3ca", "label": "warm grey shell"},
                {"features": ["grille", "perforation"], "finish": "metal", "color": "#3a3c40", "label": "graphite grille"},
                {"features": ["keys", "foot"], "finish": "rubber", "color": "#2a2b2d", "label": "rubber keys and foot"}]
