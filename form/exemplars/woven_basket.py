"""Storage basket with a woven look: a flared soft-rectangle body lofted from three sections and hollowed by inset
sections, a rolled rim band, raised frames round two hand-hold cut-outs, and a twill weave carried as a mesh texture
on the outside of the walls (the STEP stays smooth). Form Studio exemplar design."""
import math

from build123d import Box, Plane, Pos, SlotOverall, extrude

from form import craft, parts
from form.craft import MeshTexture
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

META = {
    "title": "Woven storage basket",
    "category": "textured",
    "tags": ["basket", "storage", "bin", "tote", "woven", "weave", "wicker", "rattan", "texture", "textured",
             "mesh texture", "handles", "rim", "loft", "superellipse", "home"],
    "techniques": ["craft.section_body soft-rectangle sections (n ~ 3.5) with flare and a slight belly",
                   "craft.inset_body hollowing (open top, closed floor)",
                   "craft.surface_band rolled rim and handle frames", "slot cut-outs through both ends in one cut",
                   "MeshTexture weave limited to the walls with region= and facing=\"out\""],
    "lessons": [
        "Fine texture you see up close is a mesh texture: a woven look modelled in B-rep would be thousands of strands "
        "and booleans. MeshTexture(\"weave\") displaces the exported mesh and the renders; the STEP stays the smooth "
        "body for tooling, and Form Studio labels it so.",
        "Keep the texture where the material would be: region= limits it to the walls between the floor and the rim, "
        "facing=\"out\" keeps the inside smooth (it is easier to clean), and its edge_falloff lets it fade into the "
        "rim and foot instead of ending in a cut.",
        "A soft rectangle (superellipse n ~ 3.5) flared 8 % and given a slight belly reads as a woven basket; straight "
        "vertical walls read as a plastic crate.",
        "Frame what a hand uses: the hand-holds get a raised band (surface_band) that is both stiffening and the "
        "visual edge of the weave, and their cut edges are rounded so fingers never meet a sharp edge.",
        "Rounded rim: the rim band and the wall top form one flat ring, so both of its edges take one large fillet and "
        "the rim reads rolled, like the rattan edge of a real basket.",
        "Round a hollow body's foot on both sides with concentric radii (R outside, R - wall inside). A sharp inner "
        "corner under an 8 mm outer round leaves the wall about 0.4 mm thick at the corner, or pokes through it when "
        "the wall is thin: the hollow then falls apart into two solids.",
    ],
}


class Design(Recipe):
    title, summary = "Woven basket", "Flared storage basket with a woven-look texture, rolled rim and hand-holds."
    solids = 1
    photo_color = "#b89a6a"
    params = [
        Param("length", "Length at the rim", 280, 240, 400, 5, "mm", "form", "body"),
        Param("width", "Width at the rim", 200, 150, 240, 5, "mm", "form", "body"),
        Param("height", "Height", 150, 80, 250, 5, "mm", "form", "body"),
        Param("flare", "Flare", 0.08, 0.0, 0.18, 0.01, "", "form", "body", "Foot is (1 - flare) x the rim."),
        Param("wall", "Wall", 2.6, 1.6, 4.0, 0.1, "mm", "form", "body"),
        Param("handle_w", "Hand-hold length", 90, 60, 110, 1, "mm", "form", "handles",
              "A four-finger hand needs about 85-95 mm (ANSUR II hand breadth 90 mm)."),
        Param("weave", "Weave depth", 0.9, 0.0, 1.5, 0.1, "mm", "form", "body", "0 = smooth. Mesh texture."),
    ]
    features = [Feature("body", "Woven walls", "structure"), Feature("rim", "Rolled rim", "finish"),
                Feature("frames", "Hand-hold frames", "structure"), Feature("handles", "Hand-holds", "access")]

    def constraints(self, v):
        if v["handle_w"] > v["width"] * 0.62:
            return [RecipeError("The hand-holds are wider than the ends", "handles", "Shorten the hand-holds.",
                                ["handle_w", "width"])]
        if v["width"] > v["length"]:
            return [RecipeError("The basket is wider than it is long", "body", "Swap length and width.",
                                ["width", "length"])]
        return []

    def _sections(self, v):
        a, b, H, f = v["length"] / 2, v["width"] / 2, v["height"], v["flare"]
        k = lambda u: 1 - f * (1 - u) + 0.012 * math.sin(math.pi * u)        # flare plus a slight belly
        return [{"z": H * u, "a": a * k(u), "b": b * k(u), "n": 3.5, "seam": 90} for u in (0.0, 0.5, 1.0)]

    def build(self, v):
        H, t = v["height"], v["wall"]
        secs = self._sections(v)
        # the foot is rounded on both sides of the wall with concentric radii (8 outside, 8 - wall inside): a sharp
        # inner corner under a rounded outer one would leave the wall thinnest exactly where the basket is loaded
        outer = craft.section_body(secs)
        outer = craft.safe_fillet(outer, craft.faces_at(outer, "bottom")[0].edges(), 8.0)
        inner = craft.inset_body(secs, t, open_bottom=False, open_top=True)
        inner = craft.safe_fillet(inner, craft.faces_at(inner, "bottom")[0].edges(), 8.0 - t)
        body = craft.cut(outer, inner)
        stages = [Stage("body", body)]

        # --- snippet: rolled rim from a surface band, both edges of the ring rounded as one
        rim_h, rim_t = 12.0, 3.0
        slab = Pos(0, 0, H - rim_h / 2 + 0.5) * Box(4 * v["length"], 4 * v["width"], rim_h + 1)
        band = craft.surface_band(secs, None, rim_t, slab, depth=t / 2)
        body = craft.fuse(body, band)
        top = [e for e in body.edges() if abs(e.center().Z - H) < 0.01]
        body = craft.safe_fillet(body, top, (t + rim_t) / 2 - 0.3)
        step = [e for e in body.edges() if abs(e.center().Z - (H - rim_h)) < 0.01]
        body = craft.safe_fillet(body, step, 1.2)
        # --- end snippet
        stages.append(Stage("rim", body))

        # raised frames round the hand-holds: a band 2 mm proud, clipped to a grown slot through both ends
        zc, hh = H - rim_h - 22, 26.0
        slot = lambda w, h: Plane.YZ * Pos(0, zc) * SlotOverall(w, h)
        frame_reg = extrude(slot(v["handle_w"] + 16, hh + 16), v["length"], both=True)
        frames = craft.surface_band(secs, None, 2.0, frame_reg, depth=t / 2)
        frames = craft.safe_fillet(frames, [e for e in frames.edges() if abs(e.center().X) > v["length"] * 0.3], 0.9)
        body = craft.fuse(body, frames)
        stages.append(Stage("frames", body))

        hole = extrude(slot(v["handle_w"], hh), v["length"], both=True)
        body = craft.cut(body, hole)
        lips = [e for e in body.edges() if abs(e.center().X) > v["length"] * 0.3 and abs(e.center().Z - zc) < hh / 2 + 0.5
                and abs(e.center().Y) < v["handle_w"] / 2 + 0.5]
        body = craft.safe_fillet(body, lips, 1.2)
        stages.append(Stage("handles", body))
        return parts.checked(stages)

    def mesh_texture(self, v):
        if v["weave"] <= 0:
            return []
        L, W, H = v["length"], v["width"], v["height"]
        return [MeshTexture("weave", amplitude=v["weave"], scale=9.0, features=["body"], facing="out",
                            region=((-L, -W, 6.0), (L, W, H - 13.0)), edge_falloff=3.0)]

    def appearance(self, v):
        return [{"features": ["rim", "frames", "handles"], "finish": "satin", "color": "#8a6a3e"},
                {"features": ["body"], "finish": "matte", "color": "#b89a6a"}]

    def derived(self, v):
        secs = self._sections(v)
        a, b = secs[0]["a"] - v["wall"], secs[0]["b"] - v["wall"]
        return [{"key": "volume_l", "label": "Capacity (approx.)",
                 "value": round(0.95 * 4 * a * b * (v["height"] - v["wall"]) * (1 + v["flare"]) / 1e6, 1), "unit": "l",
                 "feature": "body", "formula": "soft rectangle ~ 0.95 x box, mean of foot and rim", "interface": False},
                {"key": "weave", "label": "Weave", "value": v["weave"], "unit": "mm", "feature": "body",
                 "formula": "mesh texture; STEP carries the smooth body", "interface": False}]
