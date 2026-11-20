"""Gusseted L shelf bracket: a wall leg and a shelf leg of one thickness, a root fillet sized from the bending stress,
an outside corner that keeps the section constant round the bend, two edge gussets and slotted holes in both legs.
Form Studio exemplar design."""

from build123d import Align, Axis, Plane, Pos, Rot, SlotOverall, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Gusseted angle bracket",
    "category": "mechanical",
    "tags": ["bracket", "angle", "l bracket", "shelf", "gusset", "rib", "corner", "slot", "slotted", "fillet", "load",
             "structural", "mounting", "wall", "mechanical"],
    "techniques": ["L section as one XZ profile extruded across the width", "inside root fillet sized from r/t and "
                   "outside radius = inside radius + thickness", "craft.gusset at both edges, overlapped 0.2 mm",
                   "SlotOverall slots turned into each leg", "derived() root bending stress from the load path",
                   "craft.safe_fillet hierarchy: root, plan corners, small edge breaks"],
    "lessons": [
        "Follow the load path: a shelf load F at arm a bends the corner with M = F a. The root carries it, so the root "
        "gets the material: section stress 6 M / (w t^2), shown in derived() with the load it assumed.",
        "A sharp inside corner multiplies that stress (Kt above 2.5); a root fillet of about the thickness brings Kt "
        "near 1.3. Make the outside radius the inside radius plus the thickness, so the section is the same all round "
        "the bend and there is no thin spot or lump.",
        "Gussets at the two edges, not in the middle: they stiffen the corner where the legs would twist, leave the "
        "middle free for the screws and the shelf, and a 45 deg-ish hypotenuse prints without support.",
        "Slots, not holes, on a bracket: the wall leg's slots run vertically (level the shelf), the shelf's run along "
        "it (set the reach). Keep them clear of the root fillet and the gussets by a washer radius.",
        "Printed as modelled the wall leg's layers lie across its bending stress; for heavy shelves print it on its side "
        "(the L flat on the bed, supports under the far gusset) so every layer runs round the corner.",
    ],
}


class Design(Recipe):
    title, summary = "Gusseted shelf bracket", "L bracket with a load-sized root fillet, edge gussets and slotted holes."
    params = [
        Param("width", "Width", 40, 32, 80, 1, "mm", "form", "legs"),
        Param("wall_leg", "Wall leg height", 70, 40, 140, 1, "mm", "form", "legs"),
        Param("shelf_leg", "Shelf leg length", 80, 40, 160, 1, "mm", "form", "legs"),
        Param("thickness", "Thickness", 5, 3, 10, 0.5, "mm", "form", "legs"),
        Param("root_r", "Root fillet / thickness", 1.0, 0.4, 2.0, 0.1, "", "form", "root",
              "Peterson: Kt about 1.3 at r/t = 1, above 2.5 when sharp."),
        Param("gusset", "Gusset size (of the legs)", 0.6, 0.3, 0.85, 0.05, "", "form", "gussets"),
        Param("screw", "Screw size", 5, 4, 6, 1, "", "brief", "slots", "Metric screw diameter (M4-M6)."),
        Param("load", "Shelf load", 150, 20, 1000, 10, "N", "brief", "root", "At the middle of the shelf leg."),
    ]
    features = [Feature("legs", "L legs", "structure"), Feature("root", "Root fillet", "structure"),
                Feature("gussets", "Edge gussets", "structure"), Feature("slots", "Mounting slots", "interface"),
                Feature("edges", "Edge breaks", "finish")]

    G_T = 4.0                                                        # gusset thickness

    def constraints(self, v):
        t, ri = v["thickness"], v["root_r"] * v["thickness"]
        d = parts.clearance_d(f"M{int(v['screw'])}")[0]
        clear = t + ri + d + 4
        errs = []
        if min(v["wall_leg"], v["shelf_leg"]) < clear + 2 * d + 6:
            errs.append(RecipeError("The legs are too short for a slot past the root fillet", "slots",
                                    "Lengthen the legs or use a smaller screw.", ["wall_leg", "shelf_leg", "screw"]))
        if v["width"] < 2 * self.G_T + 2 * (d + 6):
            errs.append(RecipeError("The bracket is too narrow for two slots between the gussets", "slots",
                                    "Widen it or use a smaller screw.", ["width", "screw"]))
        return errs

    def build(self, v):
        W, Hv, Lh, t = v["width"], v["wall_leg"], v["shelf_leg"], v["thickness"]
        ri = v["root_r"] * t
        # one profile in XZ, extruded across the width (Y): the wall leg at x = 0..t, the shelf at z = 0..t
        prof = craft.polygon_profile([(0, 0), (Lh, 0), (Lh, t), (t, t), (t, Hv), (0, Hv)], plane=Plane.XZ)
        body = Pos(0, W / 2, 0) * extrude(prof, W)
        body = Pos(0, -(body.bounding_box().min.Y + body.bounding_box().max.Y) / 2, 0) * body
        stages = [Stage("legs", body)]
        # --- snippet: root fillet from r/t, outside radius = inside + thickness (constant section round the bend)
        inside = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().X - t) < 1e-3 and abs(e.center().Z - t) < 1e-3]
        outside = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().X) < 1e-3 and abs(e.center().Z) < 1e-3]
        body = craft.safe_fillet(body, inside, ri)
        body = craft.safe_fillet(body, outside, ri + t)
        # --- end snippet
        stages.append(Stage("root", body))
        # gussets: craft.gusset fills the corner between the shelf (z = t) and the wall (x = t); 0.2 mm overlap
        g = v["gusset"]
        gx, gz = g * (Lh - t), g * (Hv - t)
        for y in (-(W / 2 - self.G_T / 2), W / 2 - self.G_T / 2):
            body = craft.fuse(body, craft.gusset(gx + 0.2, gz + 0.2, t=self.G_T, at=(t - 0.2, 0, t - 0.2), y=y))
        hyp = [e for e in body.edges() if e.geom_type.name == "LINE" and abs(abs(e.center().Y) - W / 2 + self.G_T / 2) < self.G_T
               and abs((e @ 1 - e @ 0).X) > 1 and abs((e @ 1 - e @ 0).Z) > 1]
        body = craft.safe_fillet(body, hyp, 1.2)
        stages.append(Stage("gussets", body))
        # --- snippet: slots turned into each leg; wall slots vertical, shelf slots along the shelf
        d = parts.clearance_d(f"M{int(v['screw'])}")[0]
        start = t + ri + d / 2 + 4                                        # clear of the root by a washer radius
        ys = (W / 2 - self.G_T) / 2                                       # midway between centre and gusset
        s_wall = min(Hv - start - d - 4, 3 * d + 6)
        s_shelf = min(Lh - start - d - 4, 3 * d + 6)
        cut = extrude(SlotOverall(s_wall, d), t + 2)
        for y in (-ys, ys):
            body = body - Pos(-1, y, (start + Hv) / 2) * Rot(0, 90, 0) * cut
            body = body - Pos((start + Lh) / 2, y, -1) * extrude(SlotOverall(s_shelf, d), t + 2)
        # --- end snippet
        stages.append(Stage("slots", body))
        # edge hierarchy: big plan radii on the free corners, 0.6 mm on every other outer edge
        corners = [e for e in body.edges() if e.geom_type.name == "LINE"
                   and ((abs(e.center().X - Lh) < 1e-3 and abs(abs(e.center().Y) - W / 2) < 1e-3)
                        or (abs(e.center().Z - Hv) < 1e-3 and abs(abs(e.center().Y) - W / 2) < 1e-3))]
        body = craft.safe_fillet(body, corners, 6.0)
        rims = [e for e in body.edges() if (abs(e.center().X - Lh) < 1e-3 or abs(e.center().Z - Hv) < 1e-3)]
        body = craft.safe_fillet(body, rims, 0.8)
        stages.append(Stage("edges", body))
        return parts.checked(stages)

    def derived(self, v):
        W, t = v["width"], v["thickness"]
        arm = v["shelf_leg"] / 2
        M = v["load"] * arm                                               # N mm
        sigma = 6 * M / (W * t * t)
        r_t = v["root_r"]
        kt = 1 + 0.3 / max(r_t, 0.1) ** 0.5                               # rough fit to Peterson's shoulder-fillet charts
        return [{"key": "root_moment", "label": "Root bending moment", "value": round(M / 1000, 2), "unit": "N m",
                 "feature": "root", "formula": "load x half the shelf length", "interface": False},
                {"key": "root_stress", "label": "Root bending stress (gussets ignored)", "value": round(sigma, 1),
                 "unit": "MPa", "feature": "root", "formula": "6 M / (w t^2), conservative", "interface": False},
                {"key": "root_kt", "label": "Stress concentration at the root (approx.)", "value": round(kt, 2), "unit": "",
                 "feature": "root", "formula": "about 1 + 0.3 / sqrt(r/t) (heuristic fit to Peterson)",
                 "interface": False},
                {"key": "peak_stress", "label": "Peak root stress", "value": round(sigma * kt, 1), "unit": "MPa",
                 "feature": "root", "formula": "Kt x section stress; compare with ~20 MPa for PLA across layers",
                 "interface": False}]

    def appearance(self, v):
        return [{"features": ["legs", "root", "gussets", "slots", "edges"], "finish": "matte", "color": "#3a3f45"}]
