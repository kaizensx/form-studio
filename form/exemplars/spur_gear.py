"""Hubbed spur gear with true involute teeth computed in the file: the outline is generated from the module, the tooth
count and the 20 degree pressure angle, extruded, recessed on both faces to leave a rim and a web with lightening
holes, and given a hub with a bore, a DIN 6885 keyway and a radial set-screw hole. Ported from the "spur_gear" seed
generator in CADEvolve's evolution pipeline (kulibinai/CADEvolve, Apache-2.0) and modified: rewritten for build123d
and Form Studio's FeatureDesign, the rectangular teeth replaced by involute flanks. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Cylinder, Polyline, Pos, Rot, extrude, make_face

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Hubbed spur gear with involute teeth",
    "category": "mechanical",
    "tags": ["spur gear", "gear", "involute", "teeth", "module", "pressure angle", "hub", "keyway", "key", "bore",
             "set screw", "grub screw", "web", "lightening holes", "rim", "transmission", "drive", "pinion",
             "mechanical"],
    "techniques": ["involute flanks computed as points (base circle, roll angle) and mirrored about each tooth's "
                   "centre line, root and tip joined on their circles, one closed Polyline for the whole gear",
                   "addendum one module, dedendum 1.25 modules, base circle from the pitch circle and the 20 deg "
                   "pressure angle", "web recessed from both faces leaving a rim of about 2.5 modules under the roots "
                   "and a hub", "lightening holes on the web's mid circle",
                   "bore with a DIN 6885 keyway and a radial M3 set screw"],
    "lessons": [
        "Generate the tooth, do not draw it: an involute flank is the curve a string traces as it unwinds from the "
        "base circle (outline() has the formula), from the base circle to the tip circle. Rotate it so the tooth is "
        "centred on its axis (half the tooth's angle at the base circle is a quarter pitch plus the involute "
        "function of the pressure angle) and mirror it.",
        "The tooth sizes follow from the module: pitch diameter = module x teeth, tip = module x (teeth + 2), root = "
        "module x (teeth - 2.5). Two gears mesh only when their modules and pressure angles match; their centre "
        "distance is module x (teeth1 + teeth2) / 2.",
        "Below about 17 teeth a 20 deg gear is undercut by the generating tool; a printed gear has no tool, but its "
        "roots are then thin. constraints() warns under 12 teeth.",
        "Leave a rim of at least 2-2.5 modules under the tooth roots when recessing the web; a thinner rim lets a tooth "
        "break out with its root.",
        "A keyway transmits the torque and the set screw only stops the gear walking along the shaft; put the screw "
        "over the key, so it presses the key, not the shaft.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/pipeline.py (seed_primitives)", "seed": "spur_gear", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}

PA = math.radians(20.0)                    # pressure angle
KEYS = [(6, 8, 2, 1.0), (8, 10, 3, 1.4), (10, 12, 4, 1.8), (12, 17, 5, 2.3), (17, 22, 6, 2.8)]   # d from, to, b, t2


def _inv(a: float) -> float:
    return math.tan(a) - a


def outline(m: float, z: int, n: int = 10) -> list[tuple[float, float]]:
    """The gear's closed outline (x, y), one involute flank pair per tooth, tooth 0 centred on +X."""
    rp, ra, rf = m * z / 2, m * (z + 2) / 2, m * (z - 2.5) / 2
    rb = rp * math.cos(PA)
    half = math.pi / (2 * z) + _inv(PA)                     # half tooth angle at the base circle
    t_tip = math.sqrt((ra / rb) ** 2 - 1)
    flank = []
    for i in range(n + 1):
        t = t_tip * i / n
        x, y = rb * (math.cos(t) + t * math.sin(t)), rb * (math.sin(t) - t * math.cos(t))
        r, a = math.hypot(x, y), math.atan2(y, x)
        flank.append((max(r, rf), a - half))               # polar, the flank under the tooth's axis (negative side)
    pts = []
    for k in range(z):
        c = 2 * math.pi * k / z
        side = [(r, c + a) for r, a in flank]                  # root to tip on the tooth's negative side
        other = [(r, c - a) for r, a in reversed(flank)]       # tip to root on its positive side
        b = flank[0][1]                                        # where the flank leaves the root circle (negative)
        for r, a in [(rf, c - math.pi / z), (rf, c + b)] + side + other + [(rf, c - b)]:
            p = (r * math.cos(a), r * math.sin(a))
            if not pts or math.dist(p, pts[-1]) > 1e-4:        # no zero-length edges where rf > rb
                pts.append(p)
    return pts


class Design(FeatureDesign):
    title, summary = "Spur gear", ("An involute spur gear with a recessed web, lightening holes and a hub with a "
                                   "keyed bore and a set screw.")
    params = [
        Param("module", "Module", 2.0, 0.8, 5, 0.1, "mm", "interface", "teeth"),
        Param("teeth", "Teeth", 36, 10, 120, 1, "", "interface", "teeth"),
        Param("face", "Face width", 10, 4, 40, 0.5, "mm", "form", "teeth"),
        Param("bore", "Bore", 12, 4, 40, 0.5, "mm", "interface", "bore"),
        Param("hub_d", "Hub diameter", 26, 10, 80, 0.5, "mm", "form", "hub"),
        Param("hub_l", "Hub projection", 8, 0, 30, 0.5, "mm", "form", "hub"),
        Param("web_t", "Web thickness", 4, 2, 20, 0.5, "mm", "form", "web"),
        Param("holes", "Lightening holes", 6, 0, 12, 1, "", "form", "web"),
    ]

    def setup(self, v):
        m, z = v["module"], int(round(v["teeth"]))
        rf = m * (z - 2.5) / 2
        rim_in = rf - 2.5 * m
        return {"z": z, "rf": rf, "rim_in": rim_in, "web_mid": (rim_in + v["hub_d"] / 2) / 2,
                "web_gap": rim_in - v["hub_d"] / 2}

    def constraints(self, v):
        c = self.setup(v)
        out = []
        if c["z"] < 12:
            out.append(RecipeError("Under 12 teeth the roots of a 20 deg gear get thin", "teeth",
                                   "Use 12 or more teeth, or a larger module.", ["teeth"]))
        if v["hub_d"] < v["bore"] + 6:
            out.append(RecipeError("The hub is too thin round the bore", "hub", "Make the hub larger or the bore "
                                   "smaller.", ["hub_d", "bore"]))
        if v["hub_d"] / 2 > c["rf"] - 2 * v["module"]:
            out.append(RecipeError("The hub reaches the tooth roots", "hub", "Make the hub smaller.", ["hub_d"]))
        return out

    @feature("Teeth", role="interface")                    # the skeleton: the toothed blank, face on z = 0
    def teeth(self, v, body):
        pts = outline(v["module"], self.ctx["z"])
        return extrude(make_face(Polyline(*pts, close=True)), v["face"])

    @feature("Web")
    def web(self, v, body):
        c = self.ctx
        if c["web_gap"] < 4 or v["web_t"] >= v["face"]:
            return body
        depth = (v["face"] - v["web_t"]) / 2
        ring = Cylinder(c["rim_in"], depth + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN)) - \
            Cylinder(v["hub_d"] / 2, 3 * depth, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        body = body - Pos(0, 0, v["face"] - depth) * ring
        return body - Pos(0, 0, -0.01) * ring

    @feature("Lightening holes")
    def holes(self, v, body):
        c, n = self.ctx, int(round(v["holes"]))
        d = c["web_gap"] * 0.6
        if n == 0 or d < 3 or v["web_t"] >= v["face"]:
            return body
        if n * d * 1.4 > 2 * math.pi * c["web_mid"]:
            raise RecipeError("The lightening holes overlap", "web", "Use fewer holes.", ["holes"])
        for i in range(n):
            a = 2 * math.pi * i / n
            body = body - Pos(c["web_mid"] * math.cos(a), c["web_mid"] * math.sin(a), -1) * \
                Cylinder(d / 2, v["face"] + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return body

    @feature("Hub")
    def hub(self, v, body):
        if v["hub_l"] <= 0:
            return body
        return craft.safe_union(body, Pos(0, 0, v["face"] - 0.01) *
                                Cylinder(v["hub_d"] / 2, v["hub_l"] + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN)))

    @feature("Keyed bore", role="interface")
    def bore(self, v, body):
        top = v["face"] + v["hub_l"]
        body = body - Pos(0, 0, -1) * Cylinder(v["bore"] / 2, top + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        key = next(((b, t2) for lo, hi, b, t2 in KEYS if lo < v["bore"] <= hi), None)
        if key:
            b, t2 = key
            body = body - Pos(v["bore"] / 2, 0, -1) * Box(2 * t2, b, top + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return body

    @feature("Set screw", role="interface")
    def set_screw(self, v, body):
        if v["hub_l"] < 5:
            return body
        z = v["face"] + v["hub_l"] / 2
        return body - Pos(v["hub_d"] / 4, 0, z) * Rot(0, 90, 0) * Cylinder(1.25, v["hub_d"] / 2 + 2)   # M3 tap drill

    @feature("Chamfers", role="finish")
    def chamfers(self, v, body):
        hub_top = [e for e in body.edges().filter_by(Axis.Z, reverse=True)
                   if abs(e.center().Z - (v["face"] + v["hub_l"])) < 0.01 and e.length > v["hub_d"] * 2]
        return craft.safe_chamfer(body, hub_top, 0.6) if hub_top else body
