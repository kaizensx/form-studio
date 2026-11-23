"""Valet tray for a desk or a hall table: a soft-square glazed shell with a felt-lined well, split by a low ridge at
the golden section into a key bay and a coin bay. The well's floor runs into its walls on a large radius, so coins
slide out with a finger; the tray floats on a recessed cork foot. Form Studio exemplar design (premium everyday
object, original)."""
from build123d import Axis, Box, Pos, extrude

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Valet tray with felt-lined well and golden-section ridge",
    "category": "consumer",
    "tags": ["tray", "valet tray", "desk tray", "catch-all", "key tray", "coin tray", "organizer", "dish",
             "premium", "beautiful", "superellipse", "felt lining", "shadow gap", "two material", "everyday"],
    "techniques": ["soft-square plan (superellipse n = 4.5) for shell, well and foot: one shape language at three sizes",
                   "round the cutter, not the cavity: the well's tool gets its floor radius before the cut",
                   "a ridge made as a box intersected with the well's tool, so its ends follow the walls exactly",
                   "golden-section split (1 : 1.618) of the well's length for the ridge",
                   "appearance(): glazed shell, felt lining (the well's own faces), cork foot"],
    "lessons": [
        "One shape repeated at three sizes (shell, well, foot) is what makes a tray read as a family product. "
        "Change only the size, never the superellipse exponent, between them.",
        "Round the cutter before you cut: a well tool with its floor radius already on it cuts a filleted cavity in "
        "one boolean; filleting the cavity's inside edges afterwards is where kernels fail.",
        "A large floor radius (6-10 mm) is a function, not decoration: coins and keys slide up and out. Small radii "
        "on the rim (1-1.5 mm) keep the edge crisp; the outside bottom edge sits between them. That is the "
        "three-tier hierarchy.",
        "Split a length at the golden section (0.382 / 0.618), not in the middle: two unequal bays read as "
        "considered, two equal ones as a divider.",
        "Make an inner part follow curved walls by intersecting a simple block with the cavity's own tool.",
        "Line the working surface in a second material (felt, rubber) and keep the outside calm: the lining is the "
        "detail that sells it.",
    ],
}


class Design(FeatureDesign):
    title, summary = "Valet tray", "A soft-square glazed tray with a felt-lined well, a golden-section ridge and a cork foot."
    params = [
        Param("length", "Length", 190, 120, 300, 1, "mm", "form", "shell"),
        Param("width", "Width", 118, 70, 200, 1, "mm", "form", "shell"),
        Param("height", "Height", 26, 16, 45, 0.5, "mm", "form", "shell"),
        Param("wall", "Rim width", 6, 3, 12, 0.25, "mm", "form", "well"),
        Param("floor", "Floor thickness", 4, 2.5, 8, 0.25, "mm", "form", "well"),
        Param("floor_r", "Floor radius", 9, 3, 14, 0.5, "mm", "form", "well", "Tier 1: coins slide out on it."),
        Param("ridge_h", "Ridge height", 9, 0, 20, 0.5, "mm", "form", "ridge", "0: no ridge."),
    ]

    def setup(self, v):
        return {"a": v["length"] / 2, "b": v["width"] / 2, "n": 4.5, "foot_h": 2.0, "foot_in": 3.0}

    def constraints(self, v):
        if v["floor_r"] > v["height"] - v["floor"] - 2:
            return [RecipeError("The floor radius is taller than the well", "well", "Use a smaller floor radius.",
                                ["floor_r", "height", "floor"])]
        if v["ridge_h"] > v["height"] - v["floor"] - 3:
            return [RecipeError("The ridge stands above the rim", "ridge", "Lower the ridge.", ["ridge_h", "height"])]
        return []

    def _well_tool(self, v, rounded=True):
        c = self.ctx
        z0 = c["foot_h"] + v["floor"]
        plan = craft.superellipse_face(c["a"] - v["wall"], c["b"] - v["wall"], c["n"], count=96)
        tool = Pos(0, 0, z0) * extrude(plan, v["height"] + 10)
        if rounded:
            tool = craft.safe_fillet(tool, tool.edges().group_by(Axis.Z)[0], v["floor_r"])
        return tool

    @feature("Shell")                                     # skeleton: the solid tray body above the foot
    def shell(self, v, body):
        c = self.ctx
        plan = craft.superellipse_face(c["a"], c["b"], c["n"], count=96)
        body = Pos(0, 0, c["foot_h"]) * extrude(plan, v["height"] - c["foot_h"])
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[0], 3.0)      # tier 2: the bottom edge
        return craft.safe_fillet(body, body.edges().group_by(Axis.Z)[-1], 1.5)     # tier 3: the outer rim

    @feature("Well", role="interface")
    def well(self, v, body):
        # --- snippet: a filleted cavity in one boolean: round the cutter, then cut
        body = craft.safe_cut(body, self._well_tool(v))
        # --- end snippet
        rim = [e for e in body.edges() if abs(e.center().Z - v["height"]) < 0.05]
        inner = sorted(rim, key=lambda e: e.length)[: max(1, len(rim) // 2)]      # the shorter loop: the well's lip
        return craft.safe_fillet(body, inner, 1.2)                                  # tier 3: the inner rim

    @feature("Ridge")
    def ridge(self, v, body):
        if v["ridge_h"] <= 0:
            return body
        c = self.ctx
        # --- snippet: a ridge at the golden section whose ends follow the walls (block ∩ the well's tool)
        x = -(c["a"] - v["wall"]) + 2 * (c["a"] - v["wall"]) * 0.382
        z0 = c["foot_h"] + v["floor"]
        block = Pos(x, 0, z0 - 1 + (v["ridge_h"] + 1) / 2) * Box(5.0, v["width"], v["ridge_h"] + 1)
        block = craft.safe_fillet(block, block.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1], 2.4)
        rib = block & self._well_tool(v, rounded=False)
        return craft.safe_union(body, rib)
        # --- end snippet

    @feature("Cork foot", role="structure")
    def foot(self, v, body):
        c = self.ctx
        plan = craft.superellipse_face(c["a"] - c["foot_in"], c["b"] - c["foot_in"], c["n"], count=96)
        foot = extrude(plan, c["foot_h"] + 0.5)
        foot = craft.safe_fillet(foot, foot.edges().group_by(Axis.Z)[0], 0.6)
        return craft.safe_union(body, foot)

    def appearance(self, v):
        return [{"features": ["shell", "ridge"], "finish": "gloss", "color": "#ece6da", "label": "glazed shell"},
                {"features": ["well"], "finish": "rubber", "color": "#2e4a3f", "label": "felt lining"},
                {"features": ["foot"], "finish": "matte", "color": "#a8865f", "label": "cork foot"}]
