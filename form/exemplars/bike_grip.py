"""Bicycle handlebar grip for 22.2 mm (7/8") bars: a revolved body with an ergonomic palm swell, an inboard flange,
helical drain grooves cut to an even depth over the swell, a fine diamond knurl on the lands (mesh texture), and a
separate bar-end plug whose finned shank presses into the bar and whose cap closes the grip's end. Form Studio
exemplar design.
"""

import math

from build123d import Align, Compound, Cylinder, Pos, Solid, Vector, Wire, make_face

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Textured bike grip with end plug",
    "category": "textured",
    "tags": ["bike", "bicycle", "grip", "handlebar", "mtb", "22.2", "7/8", "texture", "spiral", "knurl",
             "helical grooves", "flange", "end plug", "bar end", "revolve", "ergonomic", "rubber"],
    "techniques": ["craft.revolve_profile(spline=True) body with a palm swell; a filleted flange",
                   "helical grooves: twisted wedges (Solid.extrude_linear_with_rotation) as one Compound, "
                   "intersected with a skin layer and cut, so every groove has the same depth over the swell",
                   "MeshTexture knurl (diamond, around Z) on the lands: fine texture that follows the swell",
                   "texture zone fades out: the skin layer is clipped short of the flange and the end",
                   "a separate bar-end plug with a finned shank (fuse min_solids=2), assembly() with a press Mate",
                   "appearance() zones: rubber grip, metal plug"],
    "lessons": [
        "Start from the bar: 22.2 mm (7/8\") is the grip diameter of nearly every flat and riser bar (ISO 4210 "
        "bicycle handlebars). A push-on rubber grip is bored 0.2-0.4 mm under it so it grips the bar; the bar's "
        "inside is about 18.6-19.2 mm for alloy bars, which is what the end plug's fins must seal in.",
        "Size it from the hand: MTB grips are 130-140 mm long and 29-34 mm across; the swell (+1.5-3 mm in radius) "
        "sits under the palm, on the outboard half, where the hand's heel bears down.",
        "Make texture follow the form: cut the grooves only from a skin layer (the body minus the body shrunk by the "
        "groove depth), so every groove is the same depth over the swell. Grooves cut by fixed cylinders are deep "
        "on the swell and vanish at the ends.",
        "Split texture by scale: the grooves you see and that shed water and mud are B-rep (16 helical grooves, one "
        "boolean with a Compound of disjoint wedges); the fine diamond you feel is a mesh texture (knurl around the "
        "axis), which follows the swell for free. Crossing two sets of B-rep helices instead costs minutes and the "
        "second cut fails on the first one's faces.",
        "Stop the texture short of the ends (8 mm from the flange, 6 mm from the cap): a smooth band at each end "
        "reads as finished and keeps the flange and cap edges clean.",
        "A separate plug is a separate solid: keep 0.4 mm between cap and grip and declare the press fit (Mate) "
        "between the plug's fins and the bar instead of fusing it.",
    ],
}


def _wedge(r_out, half_deg, angle):
    """A thin radial sector face on XY, from the axis out to r_out, centred on `angle` degrees."""
    a0, a1 = math.radians(angle - half_deg), math.radians(angle + half_deg)
    pts = [Vector(0, 0, 0), Vector(r_out * math.cos(a0), r_out * math.sin(a0), 0),
           Vector(r_out * math.cos(a1), r_out * math.sin(a1), 0)]
    return make_face(Wire.make_polygon(pts, close=True)).faces()[0]


class Design(Recipe):
    title, summary = "Bike grip", ("Grip for 22.2 mm bars: palm swell, flange, helical grooves and a diamond knurl "
                                   "that follow the swell, and a separate finned bar-end plug.")
    solids = 2
    photo_color = "#232427"
    params = [
        Param("bar_d", "Bar diameter", 22.2, 22.2, 22.2, 0.1, "mm", "brief", "body",
              "7/8\" handlebar grip area (ISO 4210).", "specified"),
        Param("squeeze", "Bore interference", 0.3, 0.0, 0.6, 0.05, "mm", "interface", "body",
              "Bore under the bar diameter: push-on rubber grips 0.2-0.4 mm."),
        Param("length", "Length", 135, 110, 150, 1, "mm", "brief", "body", "MTB grips 130-140 mm."),
        Param("od", "Outside diameter", 31, 29, 35, 0.5, "mm", "brief", "body", "29-34 mm; larger hands, larger."),
        Param("swell", "Palm swell", 2.0, 0.0, 3.5, 0.25, "mm", "form", "body", "Extra radius under the palm."),
        Param("grooves", "Helical grooves", 16, 8, 24, 1, "", "form", "texture"),
        Param("depth", "Groove depth", 1.0, 0.5, 1.6, 0.1, "mm", "form", "texture"),
        Param("knurl", "Knurl depth", 0.3, 0.0, 0.5, 0.05, "mm", "form", "texture", "Mesh texture; 0 = smooth lands."),
        Param("bar_id", "Bar inside diameter", 19.0, 17.0, 20.0, 0.1, "mm", "interface", "plug",
              "Alloy bars 18.6-19.2 mm; measure yours."),
    ]
    features = [Feature("body", "Grip body", "structure"), Feature("flange", "Flange", "structure"),
                Feature("texture", "Grooves and knurl", "finish"), Feature("bore", "Bar bore", "interface"),
                Feature("plug", "Bar-end plug", "interface")]

    def constraints(self, v):
        if v["od"] / 2 - v["depth"] - (v["bar_d"] - v["squeeze"]) / 2 < 2.5:
            return [RecipeError("The grooves leave under 2.5 mm of rubber over the bar", "texture",
                                "Shallower grooves or a larger diameter.", ["depth", "od"])]
        return []

    def profile(self, v, grow=0.0):
        """The outer profile (r, z) from just above the flange to the end, with the palm swell at 62 % of the length."""
        L, R, s = v["length"], v["od"] / 2, v["swell"]
        pts = [(R - 0.4, 3.0), (R - 0.2, L * 0.15), (R + s * 0.35, L * 0.40), (R + s, L * 0.64),
               (R + s * 0.55, L * 0.84), (R + 0.1, L - 2.0)]
        return [(r + grow, z) for r, z in pts]

    def build(self, v):
        L, R = v["length"], v["od"] / 2
        body = craft.revolve_profile(self.profile(v), spline=True)
        top = [e for e in body.edges() if abs(e.center().Z - (L - 2.0)) < 0.5]
        body = craft.safe_fillet(body, top, 2.5)
        stages = [Stage("body", body)]

        fl_r = R + 4.5                                           # flange: 4.5 mm proud, 4 mm thick
        flange = Cylinder(fl_r, 4.0, align=BOTTOM)
        flange = craft.safe_fillet(flange, flange.edges(), 1.5)
        body = craft.fuse(body, flange)
        body = craft.safe_fillet(body, [e for e in body.edges() if 3.5 < e.center().Z < 5 and
                                        abs(math.hypot(e.center().X, e.center().Y)) < fl_r], 1.0)
        stages.append(Stage("flange", body))

        # --- snippet: grooves of even depth over a swelling body
        z0, z1 = 12.0, L - 8.0                                    # smooth bands at both ends
        n, d = int(v["grooves"]), v["depth"]
        half = math.degrees(1.6 / (R + v["swell"]))               # groove 3.2 mm wide at the surface
        twist = math.degrees((z1 - z0) / R)                       # 45 deg helix: one radius of turn per radius of rise
        skin = craft.cut(craft.revolve_profile(self.profile(v, 1.0), spline=True),
                         craft.revolve_profile(self.profile(v, -d), spline=True))
        skin = skin & Pos(0, 0, z0) * Cylinder(R + 10, z1 - z0, align=BOTTOM)
        # (wedges start half a pitch off 0 deg: a wedge on the revolve's seam plane is cut away unreliably)
        wedges = Compound([Solid.extrude_linear_with_rotation(_wedge(R + 8, half, 360 * (i + 0.5) / n), (0, 0, z0),
                                                              (0, 0, z1 - z0), twist) for i in range(n)])
        body = craft.cut(body, skin & wedges)
        # --- end snippet
        stages.append(Stage("texture", body))

        bore = Pos(0, 0, -1) * Cylinder((v["bar_d"] - v["squeeze"]) / 2, L + 2, align=BOTTOM)
        body = craft.cut(body, bore)
        body = craft.safe_fillet(body, [e for e in body.edges() if abs(math.hypot(e.center().X, e.center().Y)) < R - 3
                                        and (e.center().Z < 0.5 or e.center().Z > L - 0.5)], 0.8)
        stages.append(Stage("bore", body))

        # bar-end plug: a domed cap 0.4 mm above the grip's end, a finned shank into the bar's inside
        gap = 0.4
        cap = Pos(0, 0, L + gap) * craft.revolve_profile([(R + 0.5, 0), (R + 0.5, 3.0), (R - 2.0, 6.5), (0, 7.5)],
                                                           spline=False)
        cap = craft.safe_fillet(cap, [e for e in cap.edges() if e.center().Z > L + gap + 0.1], 1.5)
        rb = v["bar_id"] / 2
        shank = Pos(0, 0, L + gap - 22) * Cylinder(rb - 1.6, 22.5, align=BOTTOM)
        for k in range(3):                                        # three fins, 0.4 mm over the bar's inside
            zf = L + gap - 20 + k * 6
            fin = Pos(0, 0, zf) * Solid.make_cone(rb + 0.4, rb - 1.6, 3.5)
            shank = shank + fin
        plug = craft.fuse(cap, shank)
        body = craft.fuse(body, plug, max_solids=2, min_solids=2)
        stages.append(Stage("plug", body))
        return stages

    def mesh_texture(self, v):
        if v["knurl"] <= 0:
            return []
        L = v["length"]
        return [MeshTexture("knurl", amplitude=v["knurl"], scale=2.2, features=["texture"], axis=(0, 0, 1),
                            facing="out", edge_falloff=0.8, region=((-40, -40, 12.0), (40, 40, L - 8.0)))]

    def appearance(self, v):
        return [{"features": ["plug"], "finish": "metal", "color": "#7d8187"},
                {"features": ["body", "flange", "texture", "bore"], "finish": "rubber", "color": "#232427"}]

    def assembly(self, v):
        L = v["length"]
        return Assembly(parts=[Part("grip", "Grip", (0.0, (v["bar_d"] - v["squeeze"]) / 2 + 1.5, L / 2),
                                    note="Slide the grip onto the bar, flange inboard (soapy water helps)."),
                               Part("plug", "Bar-end plug", (0.0, 0.0, L + 3.0), explode=(0, 0, 35),
                                    note="Press the plug into the bar end until the cap meets the grip.")],
                        mates=[Mate("plug", "grip", "contact", 0.4, "Cap against the grip's end")])

    def derived(self, v):
        return [{"key": "bore", "label": "Grip bore", "value": round(v["bar_d"] - v["squeeze"], 2), "unit": "mm",
                 "feature": "bore", "formula": "bar diameter - interference", "interface": True},
                {"key": "fin_od", "label": "Plug fin diameter", "value": round(v["bar_id"] + 0.8, 2), "unit": "mm",
                 "feature": "plug", "formula": "bar inside diameter + 0.8 mm (fins flex in)", "interface": True}]
