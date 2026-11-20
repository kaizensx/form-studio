"""Pebble-shaped earbud charging case: one lofted pebble split into a solid base (two earbud pockets, an LED window,
a USB-C opening and a thumb notch) and a hollow lid, joined by a three-knuckle pin hinge on the back, with a 0.4 mm
split line all round. Form Studio exemplar design (a 3D model and form study)."""
import math

from build123d import Align, Box, Cylinder, Pos, Rot, SlotOverall, Sphere, extrude, scale

from form import craft, parts
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Pebble earbud case",
    "category": "consumer",
    "tags": ["earbuds", "earbud case", "charging case", "pebble", "case", "lid", "hinge", "split line", "consumer "
             "electronics", "pocket", "led", "usb-c", "loft", "assembly", "organic"],
    "techniques": ["craft.section_body pebble (sections on an elliptical law, closed by a crown point)",
                   "one body split into base and lid by two half-spaces 0.4 mm apart (the split line)",
                   "lid hollowed with craft.inset_body (a crown point defeats offset shells)",
                   "three-knuckle pin hinge built by hand: knuckles, pin, webs into each body, reliefs in the other",
                   "earbud pockets: an ellipsoid bowl plus a stem slot", "assembly() with a hinge joint"],
    "lessons": [
        "Model the closed object first and split it: one pebble lofted from sections, cut into a base and a lid by two "
        "half-spaces 0.4 mm apart. The split line is then exactly where the surfaces meet, and the lid always fits.",
        "Put the hinge axis on (or just outside) the outer surface at the split. Any lid material behind the axis "
        "swings down into the base as the lid opens; with the axis at the surface the lid can open 105 deg freely.",
        "A hand-built pin hinge is four things: knuckles alternating between the parts with an axial gap, a pin fused "
        "to one part, a bore with radial clearance in the other, and a relief (knuckle radius + clearance) cut from "
        "each body where the other part's knuckles pass.",
        "A dome lofted to a crown point cannot be offset reliably; hollow it by insetting its sections "
        "(craft.inset_body) and subtracting.",
        "Proportions from real cases: 50-65 mm wide, 45-50 mm deep, 25-30 mm tall, the split about 60 % up so the "
        "pockets hold the buds by their stems and the lid covers their heads.",
        "Details that make it read as a product: a thumb notch at the front of the split, a pin-hole LED window, a "
        "USB-C opening (8.94 x 3.26 mm receptacle) on the back, and a two-material appearance().",
    ],
}


class Design(Recipe):
    title, summary = "Earbud case", ("Pebble charging case: solid base with two earbud pockets, hollow lid on a "
                                     "back hinge, split line, LED and USB-C.")
    solids = 2
    params = [
        Param("width", "Width", 62, 54, 70, 0.5, "mm", "brief", "pebble"),
        Param("depth", "Depth", 48, 42, 54, 0.5, "mm", "brief", "pebble"),
        Param("height", "Height", 28, 24, 34, 0.5, "mm", "brief", "pebble"),
        Param("split", "Split height", 0.6, 0.5, 0.7, 0.01, "", "form", "split", "Fraction of the height."),
        Param("wall", "Lid wall", 1.6, 1.2, 2.4, 0.1, "mm", "form", "lid"),
        Param("bud_d", "Earbud head diameter", 19, 16, 22, 0.5, "mm", "brief", "pockets", "Measure the bud."),
        Param("hinge_clearance", "Hinge clearance", 0.3, 0.2, 0.5, 0.05, "mm", "interface", "hinge"),
    ]
    features = [Feature("pebble", "Pebble form", "structure"), Feature("split", "Split line", "finish"),
                Feature("lid", "Hollow lid", "structure"), Feature("pockets", "Earbud pockets", "access"),
                Feature("details", "LED, USB-C and thumb notch", "access"), Feature("hinge", "Pin hinge", "interface")]

    GAP = 0.4                    # the split line

    def constraints(self, v):
        if 2 * v["bud_d"] + 8 > v["width"] - 8:
            return [RecipeError("Two earbuds do not fit side by side", "pockets", "Widen the case.", ["width", "bud_d"])]
        if v["bud_d"] + 6 > v["depth"] - 10:
            return [RecipeError("The earbud does not fit front to back", "pockets", "Deepen the case.", ["depth", "bud_d"])]
        return []

    def _law(self, u):
        """Plan size as a fraction of the waist at height fraction u: a foot 82 %, full at 40-55 %, a soft crown."""
        if u <= 0.45:
            return 0.82 + 0.18 * math.sin(math.pi / 2 * u / 0.45) ** 0.8
        return math.sqrt(max(0.0, 1 - ((u - 0.45) / 0.555) ** 2))                     # an ellipse to the crown

    def _secs(self, v):
        A, B, H = v["width"] / 2, v["depth"] / 2, v["height"]
        us = [0.0, 0.06, 0.15, 0.3, 0.45, 0.6, 0.72, 0.82, 0.9, 0.95, 0.98, 0.993]
        secs = [{"z": u * H, "a": A * self._law(u), "b": B * self._law(u), "n": 2.5} for u in us]
        return secs, (0, 0, H)

    def _axis(self, v):
        H, B = v["height"], v["depth"] / 2
        zs = H * v["split"]
        return -(B * self._law(v["split"])) - 0.3, zs              # the axis just outside the back at the split

    def build(self, v):
        H, t, g = v["height"], v["wall"], self.GAP
        secs, tip = self._secs(v)
        zs = H * v["split"]
        # --- snippet: one pebble, split into base and lid by two half-spaces (the split line is their gap)
        outer = craft.section_body(secs, tip=tip, count=64)
        outer = craft.safe_fillet(outer, outer.edges().group_by(lambda e: e.center().Z)[0], 2.0)   # soft foot
        stages = [Stage("pebble", outer)]
        big = 4 * v["width"]
        base = outer & Pos(0, 0, zs - g / 2 - big) * Box(big, big, big, align=BOTTOM)
        lid = outer & Pos(0, 0, zs + g / 2) * Box(big, big, big, align=BOTTOM)
        stages.append(Stage("split", base + lid))
        # --- end snippet
        # lid: hollowed by the inset sections (a crown point cannot be offset), open toward the base
        inner = craft.inset_body(secs, t, tip=tip, open_bottom=False)
        lid = craft.cut(lid, inner & Pos(0, 0, zs - 1) * Box(big, big, big, align=BOTTOM))
        stages.append(Stage("lid", base + lid))
        # pockets: an ellipsoid bowl for each bud's head and a slot for its stem, toward the front
        d = v["bud_d"]
        xs = v["width"] / 4 + 1.0
        for sx in (-1, 1):
            bowl = Pos(sx * xs, 2.0, zs) * scale(Sphere(d / 2 + 0.6), (1.0, 1.0, 13.0 / (d / 2 + 0.6)))
            stem = Pos(sx * (xs - 2.0), -2.5, zs - 15) * Rot(0, 0, sx * 12) * extrude(SlotOverall(14, 6.2), 20)
            base = craft.cut(base, bowl + stem)
        mouth = [e for e in base.edges() if abs(e.bounding_box().max.Z - (zs - g / 2)) < 0.05
                 and abs(e.bounding_box().min.Z - (zs - g / 2)) < 0.05 and e.bounding_box().size.X < v["width"] * 0.6]
        base = craft.safe_fillet(base, mouth, 1.0)
        stages.append(Stage("pockets", base + lid))
        # details: thumb notch at the front of the split, LED pin hole below it, USB-C opening on the back
        B = v["depth"] / 2
        notch = Pos(0, B * self._law(v["split"]) + 3.0, zs - g / 2) * scale(Sphere(6.0), (1.6, 1.0, 0.55))
        base = craft.cut(base, notch)
        led = Pos(0, B, zs - 7.0) * Rot(90, 0, 0) * Cylinder(0.8, 12)
        base = craft.cut(base, led)
        usb = Pos(0, -B - 1, 5.2) * Rot(-90, 0, 0) * extrude(SlotOverall(8.94 + 0.2, 3.26 + 0.2), 8)
        base = craft.cut(base, usb)
        stages.append(Stage("details", base + lid))
        # --- snippet: a three-knuckle pin hinge built by hand
        ya, za = self._axis(v)
        c, Rk, rp, ax_g = v["hinge_clearance"], 2.6, 1.15, 0.4
        Lh = min(26.0, v["width"] * 0.42)
        seg = (Lh - 2 * ax_g) / 3
        x0s = [-Lh / 2 + i * (seg + ax_g) for i in range(3)]

        def barrel(r, xa, xb):
            return Pos(xa, ya, za) * Rot(0, 90, 0) * Cylinder(r, xb - xa, align=BOTTOM)

        for i, xa in enumerate(x0s):
            if i % 2 == 0:                           # base knuckles: web down into the back wall
                web = Pos(xa + seg / 2, ya + 2.2, za - g / 2 - 0.3) * Box(seg, 4.4, 8.0, align=(Align.CENTER, Align.CENTER, Align.MAX))
                kn = barrel(Rk, xa, xa + seg) + (web & outer)
                lid = craft.cut(lid, barrel(Rk + c, xa - ax_g + 0.05, xa + seg + ax_g - 0.05))
                base = craft.fuse(base, kn)
            else:                                    # lid knuckle: web up into the lid, bored for the pin
                web = Pos(xa + seg / 2, ya + 2.2, za + g / 2 + 0.3) * Box(seg, 4.4, 8.0, align=BOTTOM)
                kn = barrel(Rk, xa, xa + seg) + (web & outer)
                bore = barrel(rp + c, xa - 1, xa + seg + 1)
                base = craft.cut(base, barrel(Rk + c, xa - ax_g + 0.05, xa + seg + ax_g - 0.05))
                lid = craft.cut(craft.fuse(lid, kn), bore)          # the bore also clears the lid wall
        base = craft.fuse(base, barrel(rp, x0s[0] + 0.5, x0s[-1] + seg - 0.5))        # the pin, part of the base
        body = craft.fuse(base, lid, max_solids=2, min_solids=2)                        # nothing touches
        # --- end snippet
        stages.append(Stage("hinge", body))
        return parts.checked(stages)

    def assembly(self, v):
        ya, za = self._axis(v)
        H = v["height"]
        return Assembly(parts=[Part("base", "Base", (v["width"] / 4 + 1.0, 8.0, 1.5), note="Charging base, pockets up."),
                               Part("lid", "Lid", (0, 0, H - 0.7), note="The lid closes over the buds on its hinge.")],
                        joints=[hinge("lid", (1, 0, 0), (0, ya, za), (0, 105), 15, parent="base", id="lid_hinge",
                                      label="Lid")])

    def appearance(self, v):
        return [{"features": ["pockets"], "finish": "matte", "color": "#2b2d31"},
                {"features": ["pebble", "split", "lid", "details", "hinge"], "finish": "gloss", "color": "#f2f1ed"}]

    def derived(self, v):
        ya, za = self._axis(v)
        return [{"key": "hinge_axis", "label": "Hinge axis (y, z)", "value": f"{ya:.1f}, {za:.1f}", "unit": "mm",
                 "feature": "hinge", "formula": "on the back surface at the split", "interface": True},
                {"key": "split_gap", "label": "Split line", "value": self.GAP, "unit": "mm", "feature": "split",
                 "formula": "gap between the two half-spaces", "interface": True}]
