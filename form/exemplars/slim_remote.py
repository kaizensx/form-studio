"""Slim remote control: a crowned, soft-sided bar split along its waist by a shadow line into a gloss top shell and a
matte base, with a metal navigation ring, a centre key and two rows of pill keys on a rhythm. Form Studio exemplar
design (premium everyday object, original; the housing only)."""
from build123d import Align, Axis, Cylinder, Pos, Rot, SlotCenterToCenter, Torus, extrude

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

UP = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Slim remote: two shells, nav ring and pill keys",
    "category": "consumer",
    "tags": ["remote", "remote control", "controller", "handheld", "tv remote", "buttons", "keys", "nav ring",
             "premium", "beautiful", "split line", "shadow gap", "loft", "two shells", "everyday"],
    "techniques": ["two lofts of superellipse plan sections stacked in Z (base and top shell) sharing the waist section",
                   "a shadow line at the waist cut as a thin superellipse ring: the split between two materials",
                   "keys as recess + smaller domed key: a constant gap round every key",
                   "a metal ring as a torus cut and a flush ring part: the navigation ring",
                   "pill keys on a 2 x 3 grid at a fixed pitch, centred on the axis"],
    "lessons": [
        "A handheld reads premium when it is two shells with a clean split line between them: build the base and the "
        "top as separate lofts that share their waist section, then cut a 0.6-0.8 mm shadow line there.",
        "Crown the top: plan sections that shrink by a few millimetres over the top third give a pebble-like bar that "
        "fits the hand and catches one long highlight.",
        "Every key sits in a recess 0.5-0.7 mm larger all round; the gap is what makes keys look fitted.",
        "Group keys by function and space them on one pitch; the navigation ring is the one big element, everything "
        "else is smaller and quieter.",
        "Contrast by material, not by shape: gloss top, matte base, metal ring, rubber keys, all in one hue family.",
    ],
}


class Design(FeatureDesign):
    title, summary = "Slim remote", "A crowned two-shell remote with a shadow-line split, a metal nav ring and pill keys."
    params = [
        Param("length", "Length", 156, 110, 210, 1, "mm", "form", "base"),
        Param("width", "Width", 40, 30, 56, 0.5, "mm", "form", "base"),
        Param("thick", "Thickness", 16, 10, 24, 0.5, "mm", "form", "top"),
        Param("waist", "Split height", 6.5, 3, 12, 0.25, "mm", "form", "split"),
        Param("ring_d", "Nav ring diameter", 30, 20, 40, 0.5, "mm", "form", "nav"),
    ]

    def setup(self, v):
        return {"a": v["length"] / 2, "b": v["width"] / 2, "n": 2.7, "xn": v["length"] / 2 - 34}

    def constraints(self, v):
        if v["ring_d"] > v["width"] - 6:
            return [RecipeError("The nav ring is wider than the remote", "nav", "A smaller ring or a wider remote.",
                                ["ring_d", "width"])]
        if v["waist"] > v["thick"] - 4:
            return [RecipeError("The split is above the top", "split", "Lower the split.", ["waist", "thick"])]
        return []

    def _sec(self, v, z, shrink):
        c = self.ctx
        return craft.superellipse_face(c["a"] - shrink, c["b"] - shrink * 0.6, c["n"], z=z, count=160)

    @feature("Base shell")                                  # skeleton: the matte lower shell up to the waist
    def base(self, v, body):
        w = v["waist"]
        secs = [self._sec(v, 0, 2.2), self._sec(v, w * 0.45, 0.4), self._sec(v, w, 0.0)]
        b = craft.loft_sections(secs)
        return craft.safe_fillet(b, b.edges().group_by(Axis.Z)[0], 1.6)

    @feature("Top shell")
    def top(self, v, body):
        w, t = v["waist"], v["thick"]
        # --- snippet: a crowned top shell lofted from the waist section (shared with the base)
        h = t - w
        secs = [self._sec(v, w, 0.0), self._sec(v, w + h * 0.5, 0.5), self._sec(v, w + h * 0.85, 1.8),
                self._sec(v, t, 3.6)]
        top = craft.loft_sections(secs)
        top = craft.safe_fillet(top, top.edges().group_by(Axis.Z)[-1], 2.0)
        # --- end snippet
        return craft.safe_union(body, top)

    @feature("Split line", role="finish")
    def split(self, v, body):
        c = self.ctx
        # --- snippet: a shadow line at the split: a thin ring cut round the waist
        outer = craft.superellipse_face(c["a"] + 2, c["b"] + 2, c["n"], z=v["waist"] - 0.35, count=96)
        inner = craft.superellipse_face(c["a"] - 0.6, c["b"] - 0.6, c["n"], z=v["waist"] - 0.35, count=96)
        ring = extrude(outer, 0.7) - extrude(inner, 0.7)
        return craft.safe_cut(body, ring)
        # --- end snippet

    @feature("Nav ring", role="interface")
    def nav(self, v, body):
        c = self.ctx
        x, t, R = c["xn"], v["thick"], v["ring_d"] / 2
        body = craft.safe_cut(body, Pos(x, 0, t - 1.0) * Cylinder(R, 5, align=UP))          # the ring's recess
        ring = Pos(x, 0, t - 1.4) * Cylinder(R - 0.6, 1.2, align=UP)
        ring = ring - Pos(x, 0, t - 3) * Cylinder(R - 7.5, 6, align=UP)
        ring = craft.safe_fillet(ring, ring.edges().group_by(Axis.Z)[-1], 0.4)
        ring = craft.safe_cut(ring, Pos(x, 0, t - 0.2) * Torus(R - 3.8, 0.5))             # a turned groove
        return craft.safe_union(body, ring)

    @feature("Keys", role="interface")
    def keys(self, v, body):
        c = self.ctx
        x, t, R = c["xn"], v["thick"], v["ring_d"] / 2
        # centre key in the ring
        key = Pos(x, 0, t - 1.4) * Cylinder(R - 8.2, 1.3, align=UP)
        body = craft.safe_union(body, craft.safe_fillet(key, key.edges().group_by(Axis.Z)[-1], 0.8))
        # --- snippet: pill keys on a 2 x 3 grid: recess, then a smaller domed key (constant gap)
        for i in range(3):
            for j in (-1, 1):
                px, py = x - R - 16 - i * 13, j * 8.5
                rec = Pos(px, py, t - 3.2 - 1.0) * extrude(SlotCenterToCenter(7, 6.4), 5)
                body = craft.safe_cut(body, rec)
                pill = Pos(px, py, t - 3.2 - 1.0) * extrude(SlotCenterToCenter(7, 5.2), 4.0 + 0.6)
                pill = craft.safe_fillet(pill, pill.edges().group_by(Axis.Z)[-1], 1.0)
                body = craft.safe_union(body, pill)
        # --- end snippet
        return body

    def appearance(self, v):
        return [{"features": ["top"], "finish": "gloss", "color": "#202327", "label": "gloss black top"},
                {"features": ["base", "split"], "finish": "matte", "color": "#8d9298", "label": "matte grey base"},
                {"features": ["nav"], "finish": "metal", "color": "#c4c6c8", "label": "brushed ring"},
                {"features": ["keys"], "finish": "rubber", "color": "#3a3e44", "label": "rubber keys"}]
