"""Soap dish: a soft pebble body lofted from sections, a rim that dips at the sides and rises at the ends, a shallow
floor sloped toward one end, raised rounded ribs the soap rests on, drain slots in line with the channels between them,
and a recessed underside with a notch that lets the water out. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Compound, Plane, Pos, Rot, SlotOverall, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Soap dish with drain ribs",
    "category": "consumer",
    "tags": ["soap", "soap dish", "dish", "tray", "bathroom", "kitchen", "drain", "ribs", "slots", "organic", "pebble",
             "rim", "sloped floor", "loft", "consumer", "home"],
    "techniques": ["craft.section_body pebble with a narrower foot (sections from one size law)",
                   "rim shaped by a side-view spline cutter (craft.spline_profile on Plane.XZ)",
                   "cavity tool filleted BEFORE it is cut, so the floor-to-wall round is a convex fillet on the tool",
                   "sloped floor: the cavity tool cut by a tilted half-space",
                   "rounded ribs: plan slot extruded, top edges filleted to a full round, tilted with the floor",
                   "drain slots aligned with the rib channels; recessed underside with a drain notch",
                   "craft.safe_fillet on the rim's two edges for a full round rim"],
    "lessons": [
        "Soap stays wet and slimy on a flat floor. Lift it on ribs (2-3 mm tall, 8-10 mm apart, rounded so they do not "
        "dig into the bar), slope the floor 2-4 deg so water runs off, and put the drain slots at the low end exactly "
        "in line with the channels between the ribs: the water's path decides where every feature goes.",
        "Water that leaves through the slots must also leave the dish: recess the underside so it stands on a foot "
        "ring, and cut a notch through the ring at the low end. A dish without that sits in its own puddle.",
        "Round the inside corner by filleting the cavity TOOL (a convex edge, which OCCT rounds easily) before "
        "cutting it from the body; filleting the concave edge on the dish afterwards is the fragile way.",
        "An organic rim is a side-view decision: a spline cutter that dips at the long sides and rises at the ends "
        "gives the boat-like line, and both rim edges rounded to nearly half the wall make it read as one soft lip "
        "rather than a cut.",
        "The pebble reads soft because its foot is smaller than its waist (the sections widen up to the rim) and the "
        "plan is a superellipse (n ~ 2.6), not a rounded rectangle.",
    ],
}


class Design(Recipe):
    title, summary = "Soap dish", ("Pebble soap dish with an organic rim, sloped floor, rounded drain ribs, slots "
                                   "and a drained foot.")
    params = [
        Param("length", "Length", 120, 95, 150, 1, "mm", "brief", "body", "A bar of soap is about 90 x 60 mm."),
        Param("width", "Width", 86, 66, 110, 1, "mm", "brief", "body"),
        Param("height", "Height at the ends", 26, 23, 36, 0.5, "mm", "form", "body"),
        Param("wall", "Wall", 3.0, 2.0, 4.5, 0.1, "mm", "form", "cavity"),
        Param("slope", "Floor slope", 3.0, 1.5, 4.0, 0.5, "deg", "form", "cavity", "Toward the drain end (-X)."),
        Param("rim_dip", "Rim dip at the sides", 3.0, 1.0, 5.0, 0.25, "mm", "form", "rim"),
        Param("ribs", "Number of ribs", 6, 4, 9, 1, "", "form", "ribs"),
        Param("rib_h", "Rib height", 2.5, 1.5, 4, 0.1, "mm", "form", "ribs"),
    ]
    features = [Feature("body", "Pebble body", "structure"), Feature("rim", "Organic rim", "finish"),
                Feature("cavity", "Sloped cavity", "structure"), Feature("rim_round", "Rounded lip", "finish"),
                Feature("ribs", "Drain ribs", "structure"), Feature("slots", "Drain slots", "access"),
                Feature("foot", "Foot and drain notch", "structure")]

    FOOT = 2.5            # underside recess depth
    FLOOR = 3.0           # floor thickness above the recess at the low end

    def constraints(self, v):
        A = v["length"] / 2
        rise = 2 * A * math.tan(math.radians(v["slope"]))
        top = self.FOOT + self.FLOOR + rise + v["rib_h"]
        if top > v["height"] - v["rim_dip"] - 6:
            return [RecipeError("The high end of the floor and its ribs come too close to the rim", "cavity",
                                "Reduce the slope, lower the ribs or make the dish taller.", ["slope", "height", "rib_h"])]
        pitch = (v["width"] - 2 * v["wall"] - 22) / max(v["ribs"] - 1, 1)
        if pitch < 7:
            return [RecipeError("The ribs are too close together to drain", "ribs", "Use fewer ribs or a wider dish.",
                                ["ribs", "width"])]
        return []

    def _secs(self, v, inset=0.0, top=None):
        """The body's sections: a foot 84 % of the waist, widening to the rim (the pebble). inset shrinks them in plan
        (the cavity); top extends the stack (a cavity tool that reaches past the rim)."""
        A, B, H = v["length"] / 2, v["width"] / 2, v["height"] + 4
        law = [(0.0, 0.84), (0.1, 0.92), (0.35, 0.985), (0.7, 1.0), (1.0, 0.99)]
        out = [{"z": u * H, "a": A * f - inset, "b": B * f - inset, "n": 2.6} for u, f in law]
        if top is not None:
            out.append({**out[-1], "z": top})
        return out

    def build(self, v):
        A, B, H, t = v["length"] / 2, v["width"] / 2, v["height"], v["wall"]
        body = craft.section_body(self._secs(v), count=48)
        stages = [Stage("body", body)]
        # --- snippet: an organic rim from a side-view spline cutter
        d = v["rim_dip"]
        line = [(-A - 12, H + 0.6), (-A * 0.75, H - d * 0.45), (-A * 0.3, H - d), (A * 0.3, H - d),
                (A * 0.75, H - d * 0.45), (A + 12, H + 0.6)]
        cutter = craft.spline_profile(line + [(A + 12, H + 30), (-A - 12, H + 30)], plane=Plane.XZ)
        body = craft.cut(body, extrude(cutter, B + 10, both=True))
        # --- end snippet
        stages.append(Stage("rim", body))
        # --- snippet: fillet the cavity tool, then cut it (a round inside corner and a sloped floor)
        a = math.radians(v["slope"])
        z_lo = self.FOOT + self.FLOOR
        tool = craft.section_body(self._secs(v, inset=t, top=H + 20), count=48)
        tool = tool & self._above_floor(v)                              # the floor: a plane tilted by the slope
        low = [e for e in tool.edges() if e.bounding_box().max.Z < z_lo + 2 * A * math.tan(a) + 0.5]
        tool = craft.safe_fillet(tool, low, 6.0)
        body = craft.cut(body, tool)
        # --- end snippet
        stages.append(Stage("cavity", body))
        # rounded lip: both rim edges (outer and inner loop) to nearly half the wall, a full soft round
        rim = [e for e in body.edges() if e.bounding_box().min.Z > H - d - 1.0]
        body = craft.safe_fillet(body, rim, t * 0.45)
        stages.append(Stage("rim_round", body))
        # ribs: rounded bars running down the slope, ending short of the slots
        n, h = int(v["ribs"]), v["rib_h"]
        pitch = (2 * (B - t) - 22) / (n - 1)
        x0, x1 = -A + 30, A - 14
        rib = extrude(SlotOverall(x1 - x0, 3.2), h + 1.0)
        rib = craft.safe_fillet(rib, rib.edges().group_by(Axis.Z)[-1], 1.5)
        ys = [-(n - 1) * pitch / 2 + i * pitch for i in range(n)]
        xm = (x0 + x1) / 2
        zf = z_lo + (xm + A) * math.tan(a)                              # floor height under the ribs' middle
        bars = [Pos(xm, y, zf - 1.0) * Rot(0, -v["slope"], 0) * rib for y in ys]
        body = craft.fuse(body, Compound(bars))                         # one boolean for all of them
        stages.append(Stage("ribs", body))
        # drain slots at the low end, in line with the channels between the ribs
        gaps = [(ys[i] + ys[i + 1]) / 2 for i in range(n - 1)]
        xs = -A + 21
        sl = [Pos(xs, y, -1) * extrude(SlotOverall(12, min(4.0, pitch - 4.2)), z_lo + 8) for y in gaps]
        body = craft.cut(body, Compound(sl))
        stages.append(Stage("slots", body))
        # foot: recess the underside (a foot ring stays), notch the ring at the low end so the water runs out
        rec = extrude(craft.superellipse_face(A * 0.84 - 6, B * 0.84 - 6, 2.6, count=48), self.FOOT)
        rec = Pos(0, 0, -0.01) * craft.safe_fillet(rec, rec.edges().group_by(Axis.Z)[-1], 1.0)
        notch = Pos(-A, 0, -0.01) * Box(30, 24, self.FOOT, align=BOTTOM)
        notch = craft.safe_fillet(notch, notch.edges().filter_by(Axis.Z), 3.0)
        body = craft.cut(body, rec + notch)
        stages.append(Stage("foot", body))
        return parts.checked(stages)

    def _above_floor(self, v):
        """The half-space above the sloped floor plane: z >= z_lo + (x + A) tan(slope)."""
        A = v["length"] / 2
        z_lo = self.FOOT + self.FLOOR
        big = 6 * A
        return Pos(-A, 0, z_lo) * Rot(0, -v["slope"], 0) * Box(2 * big, 2 * big, big, align=BOTTOM)

    def appearance(self, v):
        return [{"features": ["body", "rim", "cavity", "rim_round", "ribs", "slots", "foot"], "finish": "gloss",
                 "color": "#e9e4da"}]

    def derived(self, v):
        A = v["length"] / 2
        rise = 2 * A * math.tan(math.radians(v["slope"]))
        n = int(v["ribs"])
        pitch = (v["width"] - 2 * v["wall"] - 22) / (n - 1)
        return [{"key": "floor_rise", "label": "Floor rise end to end", "value": round(rise, 1), "unit": "mm",
                 "feature": "cavity", "formula": "length x tan(slope)", "interface": False},
                {"key": "rib_pitch", "label": "Rib pitch", "value": round(pitch, 1), "unit": "mm", "feature": "ribs",
                 "formula": "(inner width - 22) / (ribs - 1)", "interface": False}]
