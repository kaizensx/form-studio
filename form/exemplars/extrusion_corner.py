"""Corner bracket for 2020 aluminium extrusion: two legs with M5 holes for drop-in T-nuts, keys under each leg that
locate in the 6 mm slots and square the joint, two triangular cheeks and a filleted root. Form Studio exemplar
design."""
from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "2020 extrusion corner bracket",
    "category": "mechanical",
    "tags": ["2020", "extrusion", "aluminium", "aluminum", "v-slot", "t-slot", "corner", "bracket", "angle", "frame",
             "m5", "t-nut", "key", "printer frame", "mechanical", "cnc"],
    "techniques": ["legs and cheeks from XZ profiles extruded across the width", "slot keys sized from the profile's "
                   "slot width minus a clearance, with lead-in chamfers", "M5 clearance holes on the slot centre line "
                   "(parts.clearance_d)", "root fillet inside, edge breaks outside", "derived(): key width, hole "
                   "centres from the corner"],
    "lessons": [
        "Take the profile's numbers from its drawing: a 2020 (Misumi HFS5-2020, 20 x 20 mm, series 5) has a 6.2 mm "
        "slot opening on a 20 mm pitch and takes M5 T-nuts. The bracket's holes sit on the slot centre line, 10 mm "
        "in from the edges.",
        "Keys are what make a printed bracket square: a 1.5 mm tongue under each leg, the slot width minus a clearance "
        "(0.1-0.2 mm per side), registers the bracket in both slots, so the screws only clamp and the joint is 90 deg "
        "without a square. Chamfer their ends so they drop into the slot.",
        "The root carries the moment: fillet the inside corner and close the corner with two cheeks at the sides, "
        "leaving the middle open so a hex key reaches both screws straight.",
        "Print it on a cheek (the bracket on its side): both legs and the corner then lie in each layer, so the corner "
        "cannot split along a layer line; the keys print as plain walls.",
    ],
}


class Design(Recipe):
    title, summary = "2020 corner bracket", "Keyed corner bracket for 2020 extrusion, M5 holes for T-nuts."
    params = [
        Param("slot_w", "Slot opening", 6.2, 6.2, 6.2, 0.1, "mm", "brief", "keys",
              "Misumi HFS5-2020 (series 5): 6.2 mm slot, 20 mm profile.", "specified"),
        Param("leg", "Leg length", 20, 20, 40, 1, "mm", "form", "legs"),
        Param("thickness", "Leg thickness", 4, 3, 6, 0.5, "mm", "form", "legs"),
        Param("key_clearance", "Key clearance / side", 0.15, 0.05, 0.3, 0.01, "mm", "interface", "keys"),
        Param("key_h", "Key height", 1.5, 1.0, 2.0, 0.1, "mm", "interface", "keys",
              "Keep below the slot lip thickness (about 1.8 mm on series 5)."),
        Param("cheek", "Cheek thickness", 2.5, 1.6, 4, 0.1, "mm", "form", "cheeks"),
    ]
    features = [Feature("legs", "Legs", "structure"), Feature("cheeks", "Cheeks", "structure"),
                Feature("keys", "Slot keys", "interface"), Feature("holes", "M5 holes", "interface"),
                Feature("edges", "Edge breaks", "finish")]

    W = 20.0                                                         # profile width

    def constraints(self, v):
        if v["leg"] < v["thickness"] + 9.5 / 2 + 10 - 4:
            return [RecipeError("The screw head does not clear the other leg", "holes", "Lengthen the legs.", ["leg"])]
        return []

    def _holes(self, v):
        """Hole centres from the corner: the middle of the leg's free length, at least 10 mm (one slot pitch / 2)."""
        return max(10.0, (v["leg"] + v["thickness"]) / 2)

    def build(self, v):
        L, t, W, tc = v["leg"], v["thickness"], self.W, v["cheek"]
        # --- snippet: an L from one XZ profile, extruded across the profile's width (Y)
        lsec = craft.polygon_profile([(0, 0), (L, 0), (L, t), (t, t), (t, L), (0, L)], plane=Plane.XZ)
        legs = Pos(0, W / 2, 0) * extrude(lsec, W)
        legs = Pos(0, -(legs.bounding_box().min.Y + legs.bounding_box().max.Y) / 2, 0) * legs
        root = [e for e in legs.edges().filter_by(Axis.Y) if abs(e.center().X - t) < 1e-3 and abs(e.center().Z - t) < 1e-3]
        legs = craft.safe_fillet(legs, root, 2.5)
        # --- end snippet
        stages = [Stage("legs", legs)]
        # cheeks: triangles at both sides, flush with the profile's faces, closing the corner
        tri = craft.polygon_profile([(t - 0.2, t - 0.2), (L - 0.6, t - 0.2), (t - 0.2, L - 0.6)], plane=Plane.XZ)
        cheek = extrude(tri, tc)
        cb = cheek.bounding_box()
        body = legs
        for y in (-W / 2 - cb.min.Y, W / 2 - cb.max.Y):
            body = craft.fuse(body, Pos(0, y, 0) * cheek)
        stages.append(Stage("cheeks", body))
        # --- snippet: keys under each leg, the slot width less a clearance per side, chamfered to drop in
        kw = v["slot_w"] - 2 * v["key_clearance"]
        kh = v["key_h"]
        kx = Box(L - 1.5, kw, kh + 0.2, align=(Align.MIN, Align.CENTER, Align.MAX))        # under the base leg, along X
        kz = Box(kh + 0.2, kw, L - 1.5, align=(Align.MAX, Align.CENTER, Align.MIN))        # behind the upright, along Z
        kx = craft.attempt("key lead-in", [("0.5 mm chamfer", lambda: kx.chamfer(0.5, None, kx.edges().group_by(Axis.Z)[0])),
                                           ("square", lambda: kx)], "", ["key_h"])
        kz = craft.attempt("key lead-in", [("0.5 mm chamfer", lambda: kz.chamfer(0.5, None, kz.edges().group_by(Axis.X)[0])),
                                           ("square", lambda: kz)], "", ["key_h"])
        # break each key round its screw hole: a hole through a 5.9 mm key would leave 0.2 mm slivers either side
        hx, d = self._holes(v), parts.clearance_d("M5")[0]
        kx = kx - Pos(hx, 0, -5) * Box(d + 3, kw + 2, 10, align=BOTTOM)
        kz = kz - Pos(-5, 0, hx) * Box(10, kw + 2, d + 3, align=(Align.MIN, Align.CENTER, Align.CENTER))
        body = craft.fuse(body, Pos(1.0, 0, 0.2) * kx)
        body = craft.fuse(body, Pos(0.2, 0, 1.0) * kz)
        # --- end snippet
        stages.append(Stage("keys", body))
        body = body - Pos(hx, 0, -5) * Cylinder(d / 2, t + 10, align=BOTTOM)
        body = body - Pos(-5, 0, hx) * Rot(0, 90, 0) * Cylinder(d / 2, t + 10, align=BOTTOM)
        stages.append(Stage("holes", body))
        # edge breaks: the legs' free ends and the outer corner; the cheeks' long edges
        ends = [e for e in body.edges() if (abs(e.center().X - L) < 1e-3 and e.center().Z > 0.1)
                or (abs(e.center().Z - L) < 1e-3 and e.center().X > 0.1)]
        body = craft.safe_fillet(body, ends, 0.75)                    # the cheeks stop 0.6 mm short of the ends
        corner = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().X) < 1e-3 and abs(e.center().Z) < 1e-3]
        body = craft.safe_fillet(body, corner, 0.75)
        hyp = [e for e in body.edges() if e.geom_type.name == "LINE" and abs((e @ 1 - e @ 0).X) > 1
               and abs((e @ 1 - e @ 0).Z) > 1]
        body = craft.safe_fillet(body, hyp, 0.6)
        stages.append(Stage("edges", body))
        return parts.checked(stages)

    def derived(self, v):
        return [{"key": "key_w", "label": "Key width", "value": round(v["slot_w"] - 2 * v["key_clearance"], 2), "unit": "mm",
                 "feature": "keys", "formula": "slot opening - 2 x clearance", "interface": True},
                {"key": "hole_from_corner", "label": "Hole centre from the corner", "value": self._holes(v), "unit": "mm",
                 "feature": "holes", "formula": "max(10, (leg + thickness) / 2)", "interface": True},
                {"key": "hole_d", "label": "M5 clearance hole", "value": parts.clearance_d("M5")[0], "unit": "mm",
                 "feature": "holes", "formula": parts.clearance_d("M5")[1], "interface": True}]

    def appearance(self, v):
        return [{"features": ["legs", "cheeks", "keys", "holes", "edges"], "finish": "matte", "color": "#1f2328"}]
