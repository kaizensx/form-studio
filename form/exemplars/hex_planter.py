"""Tapered planter with a raised hexagonal relief on its conical wall: hex tiles that grow with the radius, drawn on
the cone and clipped to a grown copy of it so every tile top follows the taper; a rounded lip, a recessed foot with
drain channels and holes, and a drip saucer with standoff ribs as a second solid. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Compound, Cylinder, Plane, Pos, Rot, Solid, Vector, Wire

from form import craft, parts
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Planter with hex relief and saucer",
    "category": "textured",
    "tags": ["planter", "pot", "flower pot", "plant", "saucer", "drip tray", "hex", "hexagon", "honeycomb", "relief",
             "texture", "textured", "brep texture", "emboss", "cone", "tapered", "drainage", "garden"],
    "techniques": ["revolved outer and inner profiles (a shell without an offset)",
                   "hex tiles laid on a cone: N columns, row pitch from the local radius",
                   "tiles as drafted frusta clipped by a grown cone (relief tops follow the taper)",
                   "one boolean for all tiles (Compound tool) then craft.fuse",
                   "craft.safe_fillet full-round lip", "recessed foot with drain channels",
                   "second solid with standoff ribs, assembly() with a contact Mate"],
    "lessons": [
        "Relief on a curved wall is a layer, not stickers: draw each tile as a prism along the surface normal, union "
        "them into one Compound, and intersect with the body grown by the relief height. Every tile top is then the "
        "grown cone itself, so the relief follows the taper exactly and its roots sit inside the wall (no coincident "
        "faces, a robust fuse).",
        "Tile a cone with a fixed number of columns: the cell grows with the radius, the rows pack by the local pitch "
        "(pitch x sqrt(3) / 2), and the honeycomb closes around the pot with no seam or odd half-tile.",
        "Draft the tile sides (about 30 deg): a stepped relief reads crisper, prints without overhangs and a mould "
        "would release it. Keep the groove at least two nozzle widths (0.8 mm) so the pattern survives printing.",
        "Frame a texture with plain bands: a smooth foot and a smooth collar under a rounded lip make the field read "
        "as designed; a pattern running into the edges reads as wallpaper.",
        "A planter is a water system: holes in the floor, a recessed foot with channels so water is never trapped "
        "under it, and a saucer whose ribs hold the pot above the water it catches. The saucer is a second body, so "
        "it is declared in assembly() with the pot resting on its ribs (a contact Mate).",
    ],
}


class Design(Recipe):
    title, summary = "Hex relief planter", "Tapered planter with a raised hexagonal relief, drain holes and a drip saucer."
    solids = 2
    photo_color = "#c9c2b4"
    params = [
        Param("height", "Height", 130, 80, 220, 1, "mm", "form", "body"),
        Param("base_d", "Foot diameter", 120, 70, 200, 1, "mm", "form", "body"),
        Param("flare", "Flare (rim - foot diameter)", 40, 0, 80, 1, "mm", "form", "body",
              "0 = a straight cylinder; the rim is foot diameter + flare."),
        Param("wall", "Wall", 3.0, 2.0, 5.0, 0.1, "mm", "form", "body"),
        Param("cells", "Hex cells around", 18, 12, 24, 1, "", "form", "relief"),
        Param("relief_h", "Relief height", 1.4, 0.6, 2.5, 0.1, "mm", "form", "relief"),
        Param("groove", "Groove between cells", 1.6, 0.8, 4.0, 0.1, "mm", "form", "relief",
              ">= 2 nozzle widths so it prints."),
        Param("saucer_gap", "Saucer rim clearance", 8, 4, 20, 0.5, "mm", "form", "saucer",
              "Radial room between the pot foot and the saucer wall."),
    ]
    features = [Feature("body", "Tapered pot", "structure"), Feature("lip", "Rounded lip", "finish"),
                Feature("relief", "Hex relief", "finish"), Feature("drainage", "Foot and drain holes", "access"),
                Feature("saucer", "Drip saucer", "structure")]

    def constraints(self, v):
        if v["flare"] / 2 > v["height"] * 0.6:
            return [RecipeError("The wall flares more than 31 deg", "body", "Raise the pot or reduce the flare.",
                                ["flare", "height"])]
        if math.pi * v["base_d"] / v["cells"] < 3 * v["groove"] + 4:
            return [RecipeError("Hex cells are too small for the groove", "relief", "Use fewer cells or a narrower groove.",
                                ["cells", "groove"])]
        return []

    def _cone(self, v):
        H, rb, rt = v["height"], v["base_d"] / 2, (v["base_d"] + v["flare"]) / 2
        al = math.atan2(rt - rb, H)                       # wall angle from vertical
        return H, rb, rt, al, (lambda z: rb + (rt - rb) * z / H)

    def build(self, v):
        H, rb, rt, al, r = self._cone(v)
        t, bt = v["wall"], 4.0
        tc = t / math.cos(al)                            # wall measured horizontally
        outer = craft.revolve_profile([(0, 0), (rb, 0), (rt, H), (0, H)])
        inner = craft.revolve_profile([(0, bt), (r(bt) - tc, bt), (rt - tc, H + 1), (0, H + 1)])
        body = outer - inner
        stages = [Stage("body", body)]

        # lip: both rim circles rounded into one full round; the foot's outer edge softened
        rim = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z - H) < 0.01]
        body = craft.safe_fillet(body, rim, t / 2 - 0.05)
        foot = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and e.center().Z < 0.01 and e.radius > rb - 0.1]
        body = craft.safe_fillet(body, foot, 2.0)
        stages.append(Stage("lip", body))

        # --- snippet: raised hex relief that follows a tapered (conical) wall
        h, g, N = v["relief_h"], v["groove"], int(v["cells"])
        z_lo, z_hi = 16.0, H - 14.0                       # plain foot band and collar frame the field
        nrm = lambda a: Vector(math.cos(al) * math.cos(a), math.cos(al) * math.sin(a), -math.sin(al))
        tiles = []
        p = 2 * math.pi * r(z_lo) / N
        z = z_lo + p / math.sqrt(3) * math.cos(al)        # first row: its points just inside the band
        row = 0
        while True:
            p = 2 * math.pi * r(z) / N                    # local pitch around the cone
            R0 = (p - g) / math.sqrt(3)                   # tile circumradius at its root (flats face around)
            if z + R0 * math.cos(al) > z_hi:
                break
            R1 = max(R0 - (h + 1.2) * math.tan(math.radians(30)) * 2 / math.sqrt(3), R0 * 0.4)
            for i in range(N):
                a = 2 * math.pi * (i + 0.5 * (row % 2)) / N
                c = Vector(r(z) * math.cos(a), r(z) * math.sin(a), z)
                pl = Plane(origin=c, x_dir=Vector(-math.sin(a), math.cos(a), 0), z_dir=nrm(a))
                hexw = lambda RR, dz: Wire.make_polygon(
                    [pl.from_local_coords((RR * math.cos(math.radians(90 + 60 * k)),
                                           RR * math.sin(math.radians(90 + 60 * k)), dz)) for k in range(6)], close=True)
                tiles.append(Solid.make_loft([hexw(R0, -1.0), hexw(R1, h + 0.2)]))
            # next row: half a hex height plus a quarter (pointy rows interlock), measured along the slant
            z += (p * math.sqrt(3) / 2) * math.cos(al)
            row += 1
        grown = craft.revolve_profile([(0, -5), (rb + h / math.cos(al) - 5 * math.tan(al), -5),
                                       (rt + h / math.cos(al) + 5 * math.tan(al), H + 5), (0, H + 5)])
        relief = grown & Compound(children=tiles)       # one boolean: every tile top is the grown cone
        body = craft.fuse(body, relief)
        # --- end snippet
        self._rows = row
        stages.append(Stage("relief", body))

        # drainage: a recessed foot (water never sits under the pot), channels through the foot ring, floor holes
        rf = rb - 8
        body = body - Pos(0, 0, -0.1) * Cylinder(rf, 1.6, align=BOTTOM)
        for k in range(4):
            body = body - Rot(0, 0, 45 + 90 * k) * Pos(rb, 0, -0.1) * Box(rb, 6, 1.6, align=BOTTOM)
        holes = [(0, 0, 5.0)] + [(rf * 0.55 * math.cos(math.radians(a)), rf * 0.55 * math.sin(math.radians(a)), 3.0)
                                 for a in (45, 135, 225, 315)]
        for x, y, rr in holes:
            body = body - Pos(x, y, -1) * Cylinder(rr, bt + 3, align=BOTTOM)
        ring = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z - 1.5) < 0.01
                and abs(e.radius - rf) < 0.01]
        body = craft.safe_fillet(body, ring, 0.8)
        stages.append(Stage("drainage", body))

        # saucer beside the pot: a shallow dish with radial standoff ribs the pot foot rests on
        Rf, Hs, ts = rb + v["saucer_gap"], 22.0, 2.4
        xs = rt + Rf + 14 + 12
        dish = craft.revolve_profile([(0, 0), (Rf, 0), (Rf + 12, Hs), (0, Hs)])
        dish = craft.safe_fillet(dish, [e for e in dish.edges() if e.center().Z < 0.01 and e.radius > 1], 3.0)
        cav = craft.revolve_profile([(0, ts), (Rf - ts * 0.6, ts), (Rf + 12 - ts, Hs + 1), (0, Hs + 1)])
        dish = dish - cav
        lip = [e for e in dish.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z - Hs) < 0.01]
        dish = craft.safe_fillet(dish, lip, ts / 2 - 0.05)
        for k in range(6):
            rib = Box(rb * 0.7 - 3, 3.0, 3.3, align=BOTTOM)
            rib = craft.safe_fillet(rib, rib.edges().group_by(Axis.Z)[-1].filter_by(Axis.X), 1.0)
            dish = dish + Rot(0, 0, 30 + 60 * k) * Pos((rb * 0.3 + rb - 3) / 2, 0, ts - 0.3) * rib
        body = craft.fuse(body, Pos(xs, 0, 0) * dish, max_solids=2, min_solids=2)
        stages.append(Stage("saucer", body))
        self._xs, self._rest = xs, ts + 3.0
        return parts.checked(stages)

    def derived(self, v):
        H, rb, rt, al, r = self._cone(v)
        return [{"key": "wall_angle", "label": "Wall angle from vertical", "value": round(math.degrees(al), 1),
                 "unit": "deg", "feature": "body", "formula": "atan(flare / 2 / height)", "interface": False},
                {"key": "cell_foot", "label": "Hex cell pitch at the foot", "value": round(math.pi * v["base_d"] / v["cells"], 2),
                 "unit": "mm", "feature": "relief", "formula": "pi x base_d / cells", "interface": False},
                {"key": "volume_l", "label": "Soil volume",
                 "value": round(math.pi * (H - 4) / 3 * ((rb - v["wall"]) ** 2 + (rb - v["wall"]) * (rt - v["wall"])
                                                          + (rt - v["wall"]) ** 2) / 1e6, 2),
                 "unit": "l", "feature": "body", "formula": "frustum of the inside", "interface": False}]

    def assembly(self, v):
        H, rb, rt, al, r = self._cone(v)
        Rf = rb + v["saucer_gap"]
        xs = rt + Rf + 14 + 12
        return Assembly(parts=[Part("saucer", "Drip saucer", (xs + Rf * 0.8, 0, 1.0), note="Set the saucer down."),
                               Part("pot", "Planter", (rb * 0.75, 0, 3.0), move=(xs, 0, 2.4 + 3.0), explode=(0, 0, 60),
                                    note="Stand the pot on the saucer's ribs.")],
                        mates=[Mate("pot", "saucer", "contact", 0.0, "Pot foot on the saucer ribs")])

    def appearance(self, v):
        return [{"features": ["saucer"], "finish": "matte", "color": "#8f8a80"},
                {"features": ["body", "lip", "relief", "drainage"], "finish": "satin", "color": "#c9c2b4"}]
