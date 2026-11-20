"""A planetary gear stage, assembled: a ring gear in a flanged housing, a sun, three planets and their carrier.

Drawn in the README. Built by Form Studio through create_design, like any agent-written design; the gears are
involute (py_gearworks, through form.parts' library), and the ring is turned until it meshes with the planets.
"""
import math

import py_gearworks as gw
from build123d import Align, Box, Cylinder, Pos

from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


def _gear(z, m, h, backlash, ring=False, angle=0.0):
    if ring:
        return gw.SpurRingGear(number_of_teeth=int(z), module=m, height=h, backlash=backlash / m, angle=angle,
                               outside_ring_coefficient=1.6)
    return gw.SpurGear(number_of_teeth=int(z), module=m, height=h, root_fillet=0.25, tip_fillet=0.1, backlash=backlash / m)


def _solid(g):
    part = g.build_part()
    return part.solids()[0] if len(part.solids()) == 1 else part


class Design(Recipe):
    title = "Planetary gear stage"
    summary = "Sun, three planets and a ring gear in a flanged housing, with the planet carrier, assembled."
    solids = 6
    params = [
        Param("module", "Module", 1.5, 0.8, 3, 0.1, "mm", "form", "ring"),
        Param("z_sun", "Sun teeth", 12, 9, 30, 1, "", "form", "sun"),
        Param("z_planet", "Planet teeth", 18, 9, 40, 1, "", "form", "planets"),
        Param("face", "Face width", 8, 3, 30, 0.5, "mm", "form", "ring"),
        Param("backlash", "Backlash per gear", 0.05, 0, 0.3, 0.01, "mm", "interface", "planets"),
        Param("bore", "Planet bore", 5, 2, 10, 0.1, "mm", "interface", "planets"),
        Param("shaft", "Sun shaft", 5, 2, 10, 0.1, "mm", "interface", "sun"),
    ]
    features = [Feature("ring", "Ring gear and housing", "structure"), Feature("sun", "Sun gear", "structure"),
                Feature("planets", "Planet gears", "structure"), Feature("carrier", "Planet carrier", "structure")]

    def _z_ring(self, v):
        return int(v["z_sun"] + 2 * v["z_planet"])

    def constraints(self, v):
        if (v["z_sun"] + self._z_ring(v)) % 3:
            return [RecipeError("Three planets cannot be spaced evenly with these tooth counts", "planets",
                                "Make sun teeth + ring teeth a multiple of 3.", ["z_sun", "z_planet"])]
        m = v["module"]
        if v["bore"] >= m * (v["z_planet"] - 2.4) - 2 or v["shaft"] >= m * (v["z_sun"] - 2.4) - 2:
            return [RecipeError("A bore leaves under 1 mm below the tooth roots", "planets", "Use a smaller bore or more teeth.",
                                ["bore", "shaft"])]
        return []

    def build(self, v):
        m, h, bl = v["module"], v["face"], v["backlash"]
        zs, zp, zr = int(v["z_sun"]), int(v["z_planet"]), self._z_ring(v)
        cd = m * (zs + zp) / 2
        sun_g = _gear(zs, m, h, bl)
        r = v["shaft"] / 2
        d_bore = Pos(0, 0, -0.1) * Cylinder(r, h + 0.2, align=A) - Pos(r - 0.5 + 5, 0, -1) * Box(10, 10, h + 2, align=A)
        sun = _solid(sun_g) - d_bore                                                     # a D bore: 0.5 mm flat
        planets = []
        for k in range(3):
            a = 2 * math.pi * k / 3
            g = _gear(zp, m, h, bl)
            g.mesh_to(sun_g, target_dir=[math.cos(a), math.sin(a), 0.0])
            s = _solid(g)
            c = g.center
            planets.append(s - Pos(float(c[0]), float(c[1]), -0.1) * Cylinder(v["bore"] / 2, h + 0.2, align=A))
        # the ring, turned until its teeth sit in the planets' gaps: of no turn and half a tooth, the one that clears
        def overlap(solid):
            vols = [(solid & p) for p in planets]
            return sum(x.volume for x in vols if x is not None)
        cands = [_solid(_gear(zr, m, h, bl, ring=True, angle=a)) for a in (0.0, math.pi / zr)]
        ring = min(cands, key=overlap)
        r_out = m * zr / 2 + 2.5 * m + 6
        flange = Cylinder(r_out, 4, align=A) - Cylinder(m * zr / 2 + 1.2 * m, 4, align=A)
        for k in range(4):
            a = math.pi / 4 + k * math.pi / 2
            flange = flange - Pos((r_out - 4.5) * math.cos(a), (r_out - 4.5) * math.sin(a), 0) * Cylinder(1.7, 4, align=A)
        ring_stage = ring + flange
        # the carrier below the planets: a plate with three pins into the planet bores and an output hub
        plate_r = cd + v["bore"] / 2 + 4
        carrier = Pos(0, 0, -6) * Cylinder(plate_r, 4, align=A) + Pos(0, 0, -14) * Cylinder(6, 8, align=A)
        for k in range(3):
            a = 2 * math.pi * k / 3
            carrier = carrier + Pos(cd * math.cos(a), cd * math.sin(a), -2) * Cylinder(v["bore"] / 2 - 0.1, h + 2, align=A)
        carrier = carrier - Pos(0, 0, -14.1) * Cylinder(2.5, 8.2, align=A)
        planet_set = planets[0] + planets[1] + planets[2]
        return [Stage("ring", ring_stage), Stage("sun", ring_stage + sun), Stage("planets", ring_stage + sun + planet_set),
                Stage("carrier", ring_stage + sun + planet_set + carrier)]

    def derived(self, v):
        zs, zp, zr = v["z_sun"], v["z_planet"], self._z_ring(v)
        m = v["module"]
        return [{"key": "z_ring", "label": "Ring teeth", "value": zr, "unit": "", "feature": "ring",
                 "formula": "sun teeth + 2 x planet teeth", "interface": False},
                {"key": "centre_distance", "label": "Planet centre distance", "value": m * (zs + zp) / 2, "unit": "mm",
                 "feature": "planets", "formula": "module (sun teeth + planet teeth) / 2", "interface": True},
                {"key": "ratio_carrier", "label": "Ratio, ring held (sun in, carrier out)", "value": 1 + zr / zs, "unit": "",
                 "feature": "carrier", "formula": "1 + ring teeth / sun teeth", "interface": False},
                {"key": "ratio_star", "label": "Ratio, carrier held (sun in, ring out)", "value": zr / zs, "unit": "",
                 "feature": "ring", "formula": "ring teeth / sun teeth, reversed", "interface": False}]
