"""Desk cable dock: a weighted soft-square block that holds three cables at the desk's edge. A crowned top, keyhole
channels on a rhythm with soft-touch linings, and a recessed foot that leaves a shadow line, so the block seems to
float. Form Studio exemplar design (premium everyday object, original)."""
from build123d import Axis, Box, Cylinder, Pos, Rot, extrude

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Desk cable dock with keyhole channels",
    "category": "consumer",
    "tags": ["cable holder", "cable dock", "cable organizer", "cable clip", "desk", "charger cable", "premium",
             "beautiful", "soft square", "superellipse", "shadow gap", "keyhole", "two material", "everyday"],
    "techniques": ["plan as a superellipse (n = 4): curvature-continuous corners, no G1 fillet seam on the main form",
                   "three-tier radius hierarchy: crown R (big), foot and channel mouths (medium), lips (small)",
                   "shadow gap: a foot inset under the body so a dark line separates it from the desk",
                   "keyhole channels (throat narrower than the seat) cut as one tool, spaced on an odd rhythm",
                   "material pairing through appearance(): body, soft-touch channel linings, rubber foot"],
    "lessons": [
        "Design language first: a soft monolith (one calm block) with one gesture, the crown, and every detail "
        "(channels, foot) cut into it, never stuck on. Write that sentence before the code.",
        "A superellipse plan (n about 4) reads as premium where a box with filleted corners reads as a part: its "
        "curvature changes smoothly round the corner, so the highlight runs on without a kink.",
        "Radius hierarchy in three tiers, each about a third of the one above: the crown R5-6 on the body, R1.5-2 on "
        "the foot and the channel mouths, R0.5-0.8 on the lips. One radius everywhere looks inflated; none looks raw.",
        "A foot inset 1-1.5 mm under the body throws a shadow line that lifts the object off the desk. It is the "
        "cheapest premium detail there is.",
        "Odd counts on a rhythm (3 channels, equal pitch, centred) read as designed; even counts split the face in two.",
        "Round the cutter, not the cavity: fillet a channel's mouth after the cut with safe_fillet and a small radius; "
        "if it does not fit, reduce it, never drop it.",
    ],
}


class Design(FeatureDesign):
    title, summary = "Cable dock", "A weighted soft-square block with three keyhole cable channels and a floating foot."
    params = [
        Param("length", "Length", 78, 50, 140, 1, "mm", "form", "body"),
        Param("depth", "Depth", 44, 32, 70, 1, "mm", "form", "body"),
        Param("height", "Height", 24, 18, 40, 0.5, "mm", "form", "body"),
        Param("crown_r", "Crown radius", 6, 2, 10, 0.5, "mm", "form", "crown", "The big radius: tier 1."),
        Param("channels", "Channels", 3, 1, 5, 1, "", "form", "channels"),
        Param("cable_d", "Cable seat diameter", 6.5, 3, 10, 0.25, "mm", "interface", "channels",
              "A USB-C cable is about 3.5-4.5 mm; the seat leaves room for the lining to grip."),
        Param("throat", "Channel throat", 4.0, 2.5, 8, 0.25, "mm", "interface", "channels",
              "Narrower than the cable seat, so the cable clicks in and stays."),
        Param("foot_inset", "Foot inset", 1.4, 0.6, 3, 0.1, "mm", "form", "foot", "The shadow gap's depth."),
    ]

    def setup(self, v):
        return {"a": v["length"] / 2, "b": v["depth"] / 2, "foot_h": 2.4}

    def constraints(self, v):
        n = int(round(v["channels"]))
        if v["throat"] >= v["cable_d"] - 0.8:
            return [RecipeError("The throat is as wide as the seat: cables fall out", "channels",
                                "Keep the throat at least 0.8 mm narrower than the seat.", ["throat", "cable_d"])]
        if n * (v["cable_d"] + 7) > v["length"] - 12:
            return [RecipeError("The channels do not fit along the block", "channels",
                                "Fewer channels, a smaller seat or a longer block.", ["channels", "cable_d", "length"])]
        return []

    @feature("Body")                                       # skeleton: the soft-square block above the foot
    def body(self, v, body):
        c = self.ctx
        plan = craft.superellipse_face(c["a"], c["b"], 4.0, count=96)
        return Pos(0, 0, c["foot_h"]) * extrude(plan, v["height"] - c["foot_h"])

    @feature("Crown", role="finish")
    def crown(self, v, body):
        top = body.edges().group_by(Axis.Z)[-1]
        body = craft.safe_fillet(body, top, v["crown_r"])                       # tier 1
        bottom = body.edges().group_by(Axis.Z)[0]
        return craft.safe_fillet(body, bottom, 1.2)                             # tier 2: the edge over the shadow gap

    @feature("Foot", role="structure")
    def foot(self, v, body):
        c = self.ctx
        # --- snippet: a recessed foot that leaves a shadow line under the body
        i = v["foot_inset"]
        plan = craft.superellipse_face(c["a"] - i, c["b"] - i, 4.0, count=96)
        foot = extrude(plan, c["foot_h"] + 0.4)                                 # overlaps the body by 0.4 mm
        foot = craft.safe_fillet(foot, foot.edges().group_by(Axis.Z)[0], 0.8)   # tier 3 on the desk edge
        return craft.safe_union(body, foot)
        # --- end snippet

    def _layout(self, v):
        n = int(round(v["channels"]))
        pitch = min(v["cable_d"] + 12, (v["length"] - 16) / max(n, 1))
        return [(k - (n - 1) / 2) * pitch for k in range(n)], v["height"] - v["cable_d"] / 2 - 4.5

    @feature("Channels", role="interface")
    def channels(self, v, body):
        xs, z_seat = self._layout(v)
        # --- snippet: cable seats on a centred rhythm, cut as one tool (their faces take the lining colour)
        tool = None
        for x in xs:
            seat = Pos(x, 0, z_seat) * Rot(90, 0, 0) * Cylinder(v["cable_d"] / 2, v["depth"] + 4)
            tool = seat if tool is None else tool + seat
        return craft.safe_cut(body, tool)
        # --- end snippet

    @feature("Throats", role="interface")
    def throats(self, v, body):
        xs, z_seat = self._layout(v)
        # the narrow entries from the top, cut separately so their walls stay in the body's colour
        tool = None
        for x in xs:
            t = Pos(x, 0, (z_seat + v["height"] + 2) / 2) * Box(v["throat"], v["depth"] + 4, v["height"] - z_seat + 2)
            tool = t if tool is None else tool + t
        body = craft.safe_cut(body, tool)
        mouths = [e for e in body.edges() if e.center().Z > z_seat + v["cable_d"] / 2 + 0.5
                  and abs(e.center().Z - v["height"]) < v["crown_r"] + 1 and e.length > 1.0
                  and any(abs(e.center().X - x) < v["throat"] / 2 + v["crown_r"] for x in xs)]
        return craft.safe_fillet(body, mouths, 0.8)                             # tier 3 on the lips

    def appearance(self, v):
        return [{"features": ["body", "crown", "throats"], "finish": "matte", "color": "#d9d2c5", "label": "warm stone"},
                {"features": ["channels"], "finish": "rubber", "color": "#d2703f", "label": "soft-touch lining"},
                {"features": ["foot"], "finish": "rubber", "color": "#2b2c2e", "label": "rubber foot"}]
