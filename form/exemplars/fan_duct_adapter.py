"""Fan to hose adapter: a square flange that screws onto a standard case fan (120 mm by default, 105 mm hole spacing),
a hollow lofted transition from the fan's rounded square to a round spigot, and a spigot with a stop bead for a hose
or a duct. Ported from the "Making Lofts" seed in CADEvolve's hand-written CadQuery examples (kulibinai/CADEvolve,
Apache-2.0) and modified: rewritten for build123d and Form Studio's FeatureDesign and made into a product. Form Studio
exemplar design."""
from build123d import Align, Circle, Cylinder, Plane, Pos, RectangleRounded, extrude, loft

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Fan to hose adapter (lofted square to round)",
    "category": "mechanical",
    "tags": ["fan adapter", "fan duct", "duct", "duct adapter", "transition", "square to round", "reducer", "hose",
             "hose adapter", "120mm fan", "140mm fan", "80mm fan", "fume extractor", "dust collection", "loft",
             "spigot", "flange", "case fan", "ventilation", "airflow"],
    "techniques": ["a solid loft between a RectangleRounded and a Circle (outside), the same loft offset inward cut "
                   "from it (inside), so the wall is a set number, not the result of a shell",
                   "fan sizes from a table (frame side, hole spacing) picked by an index parameter",
                   "flange, spigot and stop bead added as plain prisms around the loft",
                   "the bore cut once through the whole part after everything is added"],
    "lessons": [
        "Standard fans have standard holes: 80 mm fans 71.5 mm apart, 92 mm 82.5, 120 mm 105, 140 mm 124.5. Put the "
        "table in the file and let one parameter pick the fan.",
        "A loft between different shapes (a rounded square and a circle) works when both sections are single closed "
        "faces on parallel planes; make the inside the same loft with every section offset by the wall, and cut it.",
        "Keep the transition gentle: a loft whose wall leans more than about 45 deg from the axis disturbs the flow "
        "and prints with overhangs; constraints() checks the height against the change in size.",
        "Keep the screws outside the duct: a fan's holes sit in the corners of its frame, so a square foot covers "
        "them. Round the foot's corners until each hole and its screw head clear the wall (the radius is solved in "
        "setup()), and the screwdriver reaches them from above.",
        "A hose spigot needs a stop: a bead a little proud of the spigot keeps the hose clamp from sliding off.",
        "Cut the bore last, through everything: features added after a cut would close it again.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/cadquery_examples.txt", "seed": "Making Lofts", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}

FANS = [("80 mm", 80, 71.5), ("92 mm", 92, 82.5), ("120 mm", 120, 105.0), ("140 mm", 140, 124.5)]


class Design(FeatureDesign):
    title, summary = "Fan to hose adapter", ("A fan flange, a hollow lofted square-to-round transition and a hose "
                                             "spigot with a stop bead.")
    params = [
        Param("fan", "Fan size", 2, 0, 3, 1, "", "interface", "flange", "0 = 80, 1 = 92, 2 = 120, 3 = 140 mm."),
        Param("hose_d", "Spigot outside diameter", 63, 20, 125, 0.5, "mm", "interface", "spigot",
              "The hose's inside diameter."),
        Param("height", "Transition height", 70, 20, 200, 1, "mm", "form", "transition"),
        Param("spigot_l", "Spigot length", 35, 10, 100, 1, "mm", "form", "spigot"),
        Param("wall", "Wall", 2.0, 1.2, 5, 0.1, "mm", "form", "transition"),
        Param("flange_t", "Flange thickness", 4, 2.5, 10, 0.5, "mm", "form", "flange"),
        Param("screw_d", "Screw hole", 4.4, 3, 5.5, 0.1, "mm", "interface", "flange", "Fan screws are about 4.3 mm."),
    ]

    def setup(self, v):
        name, side, pitch = FANS[int(round(v["fan"]))]
        outer = side - 2                                     # the loft's foot, just inside the flange
        # Round the foot's corners until each screw hole (and its head, about 2 x the shank) lies outside the duct:
        # sqrt(2) * (R - (outer - pitch) / 2) > R + head  ->  R > (head + sqrt(2) * (outer - pitch) / 2) / (sqrt(2) - 1)
        head = v["screw_d"] + 1.0
        R = min((head + 2 ** 0.5 * (outer - pitch) / 2) / (2 ** 0.5 - 1) + 1.0, outer / 2 - 0.5)
        z0, z1 = v["flange_t"], v["flange_t"] + v["height"]
        return {"side": side, "pitch": pitch, "outer": outer, "R": R, "inner": outer - 2 * v["wall"], "z0": z0,
                "z1": z1}

    def constraints(self, v):
        c = self.setup(v)
        out = []
        if v["hose_d"] > c["inner"] - 4:
            out.append(RecipeError("The spigot is as wide as the fan", "spigot", "Use a larger fan or a smaller hose.",
                                   ["hose_d", "fan"]))
        if v["height"] < (c["inner"] - v["hose_d"]) / 2:
            out.append(RecipeError("The transition is steeper than 45 deg", "transition",
                                   "Make it taller or bring the sizes closer.", ["height", "hose_d", "fan"]))
        return out

    def _foot(self, grow):
        """The duct's rounded-square foot, outside (grow = wall) or inside (grow = 0)."""
        c = self.ctx
        s = c["inner"] + 2 * grow
        return RectangleRounded(s, s, c["R"] - c["outer"] / 2 + s / 2)

    def _loft(self, v, grow):
        c = self.ctx
        a = Plane.XY.offset(c["z0"] - 0.01) * self._foot(grow)
        b = Plane.XY.offset(c["z1"] + 0.01) * Circle(v["hose_d"] / 2 - v["wall"] + grow)
        return loft([a, b])

    @feature("Fan flange", role="interface")              # the skeleton: the flange that sits on the fan
    def flange(self, v, body):
        c = self.ctx
        plate = extrude(RectangleRounded(c["side"], c["side"], 5), v["flange_t"])
        h = c["pitch"] / 2
        for x, y in ((h, h), (-h, h), (-h, -h), (h, -h)):
            plate = plate - Pos(x, y, 0) * Cylinder(v["screw_d"] / 2, 3 * v["flange_t"])
        return plate

    @feature("Transition")
    def transition(self, v, body):
        return craft.safe_union(body, self._loft(v, v["wall"]))

    @feature("Spigot", role="interface")
    def spigot(self, v, body):
        c = self.ctx
        pipe = Pos(0, 0, c["z1"]) * Cylinder(v["hose_d"] / 2, v["spigot_l"], align=(Align.CENTER, Align.CENTER, Align.MIN))
        bead = Pos(0, 0, c["z1"] + 4) * Cylinder(v["hose_d"] / 2 + 1.2, 2.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return craft.safe_union(body, pipe, bead)

    @feature("Bore")
    def bore(self, v, body):
        c = self.ctx
        r = v["hose_d"] / 2 - v["wall"]
        body = body - self._loft(v, 0.0)
        body = body - Pos(0, 0, c["z1"]) * Cylinder(r, v["spigot_l"] + 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return body - Pos(0, 0, -1) * extrude(self._foot(0.0), v["flange_t"] + 1.02)

    @feature("Spigot chamfer", role="finish")
    def edges(self, v, body):
        tip = [e for e in body.edges() if abs(e.center().Z - (self.ctx["z1"] + v["spigot_l"])) < 0.01]
        return craft.safe_chamfer(body, tip, 0.6)
