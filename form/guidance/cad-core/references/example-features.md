```python
"""Wall bracket built one feature at a time (form.featureprog). Form Studio example design."""
from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(FeatureDesign):
    title = "Wall bracket"
    summary = "An L bracket with a shelf bore and two screw slots, built skeleton first."
    params = [
        Param("w", "Width", 50, 30, 120, 1, "mm", "form", "plate"),
        Param("reach", "Reach", 60, 30, 150, 1, "mm", "brief", "arm", "How far the shelf sits from the wall."),
        Param("t", "Thickness", 5, 3, 10, 0.5, "mm", "form", "plate"),
        Param("bore_d", "Shelf pin bore", 8, 4, 16, 0.5, "mm", "interface", "bore"),
        Param("slot_w", "Screw slot width", 4.5, 3, 7, 0.1, "mm", "interface", "slots"),
        Param("r", "Edge radius", 1.5, 0.5, 3, 0.25, "mm", "form", "edges"),
    ]

    def setup(self, v):                       # shared values, read by every feature as self.ctx
        return {"h": v["w"] * 1.2}

    @feature("Wall plate")                    # the skeleton: create_design with only this feature first
    def plate(self, v, body):
        return Box(v["w"], v["t"], self.ctx["h"], align=(Align.CENTER, Align.MIN, Align.MIN))

    @feature("Arm")
    def arm(self, v, body):
        arm = Box(v["w"], v["reach"], v["t"], align=(Align.CENTER, Align.MIN, Align.MIN))
        return craft.safe_union(body, Pos(0, v["t"] - 0.2, 0) * arm)

    @feature("Shelf pin bore", role="interface")
    def bore(self, v, body):
        return body - Pos(0, v["t"] + v["reach"] * 0.7, -1) * Cylinder(v["bore_d"] / 2, v["t"] + 2, align=A)

    @feature("Screw slots", role="interface")
    def slots(self, v, body):
        h = self.ctx["h"]
        for z in (h * 0.45, h * 0.8):
            body = body - Pos(0, v["t"] / 2, z) * Rot(90, 0, 0) * Box(v["slot_w"] * 2.2, v["slot_w"], v["t"] + 2)
        return body

    @feature("Edges", role="finish")          # fillets last; a fillet that fails is skipped, the bracket stays
    def edges(self, v, body):
        return craft.safe_fillet(body, body.edges().filter_by(Axis.Y), v["r"])
```
