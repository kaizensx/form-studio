"""Three-stage planetary gearbox for a NEMA17 stepper, 4:1 per stage, 64:1 overall. Modelled assembled, in place:
housing with one continuous ring gear, input sun on the motor's D-shaft, three carriers (each carrying the next sun),
nine planets, and a lid with the output bushing.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
N_STAGES, N_PLANETS = 3, 3


class Design(Recipe):
    title, summary = "NEMA17 planetary gearbox 64:1", "Three 4:1 planetary stages in one ring housing on a NEMA17 face."
    solids = 2 + 1 + N_STAGES * (N_PLANETS + 1)
    params = [
        Param("module", "Module", 1.0, 0.8, 1.5, 0.05, "mm", "form", "ring"),
        Param("face_w", "Housing face", 42.3, 40, 46, 0.1, "mm", "brief", "housing", "NEMA17 face (NEMA ICS 16).", "specified"),
        Param("hole_pitch", "Mounting hole pitch", 31.0, 30, 32, 0.05, "mm", "brief", "housing", "NEMA17: 31 mm.", "specified"),
        Param("pilot_d", "Motor pilot", 22.0, 21, 23, 0.05, "mm", "brief", "housing", "NEMA17 pilot 22 mm.", "specified"),
        Param("shaft_d", "Motor shaft", 5.0, 4.5, 5.5, 0.01, "mm", "brief", "sun_in", "NEMA17: 5 mm D-shaft.", "specified"),
        Param("gear_t", "Gear face width", 8, 5, 12, 0.5, "mm", "form", "ring"),
        Param("backlash", "Backlash", 0.15, 0.05, 0.4, 0.01, "mm", "interface", "planets"),
        Param("pin_clear", "Planet pin clearance / side", 0.2, 0.1, 0.4, 0.01, "mm", "interface", "carriers"),
        Param("out_d", "Output shaft", 8.0, 6, 10, 0.1, "mm", "form", "output"),
    ]
    features = [Feature("housing", "Housing and NEMA17 flange", "structure"), Feature("ring", "Ring gear (3 stages)", "interface"),
                Feature("sun_in", "Input sun on the motor shaft", "interface"), Feature("planets", "Planets (3 x 3)", "interface"),
                Feature("carriers", "Carriers with pins and next suns", "structure"), Feature("output", "Output shaft", "interface"),
                Feature("lid", "Lid with output bushing", "structure"), Feature("bolts", "M3 through-bolt holes", "access")]

    SUN, PLANET = 12, 12

    def constraints(self, v):
        rd = v["face_w"] - 2.0
        if v["module"] * (self.SUN + 2 * self.PLANET + 2.5) + 1 > rd + 1:
            return [RecipeError("The ring gear does not fit inside the NEMA17 face", "ring", "Use a smaller module.", ["module"])]
        return []

    def _z(self, v):
        T = v["gear_t"]
        base = 5.0
        pitch = T + 0.5 + 3.0 + 0.6                    # gears, gap, carrier plate, gap to the next gears
        zg = [base + 0.6 + k * pitch for k in range(N_STAGES)]
        top = zg[-1] + T + 0.5 + 3.0 + 0.6
        return T, base, zg, top

    def build(self, v):
        m, W, T = v["module"], v["face_w"], v["gear_t"]
        T, base, zg, top = self._z(v)
        rd = W - 2.4
        pg = craft.planetary(m, self.SUN, self.PLANET, N_PLANETS, T, backlash=v["backlash"], sun_bore=3,
                             planet_bore=3.0 + 2 * v["pin_clear"], ring_od=rd, ring_height=top - base)
        self._pg = pg
        # housing: a soft-square block matching the motor face, the ring gear fused into a bore that overlaps it 0.2 mm
        block = Box(W, W, top, align=BOTTOM)
        block = craft.safe_fillet(block, block.edges().filter_by(Axis.Z), 4.0)
        block = block - Pos(0, 0, base) * Cylinder(rd / 2 - 0.2, top, align=BOTTOM)
        block = block - Pos(0, 0, -0.01) * Cylinder(v["pilot_d"] / 2 + 0.1, 2.0, align=BOTTOM)      # pilot recess
        block = block - Pos(0, 0, -0.1) * Cylinder(6.5, base + 1, align=BOTTOM)                     # hub clearance
        outline = [e for g in (block.edges().group_by(Axis.Z)[0], block.edges().group_by(Axis.Z)[-1]) for e in g
                   if e.geom_type.name != "CIRCLE"]
        block = craft.safe_fillet(block, outline, 1.0)
        # a shallow groove at each stage line: the outside says how the inside is built
        for z in [zg[k] + T + 2.0 for k in range(N_STAGES - 1)] + [base + 0.3]:
            outer = craft.safe_fillet(Box(W + 2, W + 2, 1.2, align=BOTTOM), Box(W + 2, W + 2, 1.2, align=BOTTOM).edges().filter_by(Axis.Z), 5.0)
            inner = Box(W - 1.6, W - 1.6, 1.2, align=BOTTOM)
            inner = craft.safe_fillet(inner, inner.edges().filter_by(Axis.Z), 3.2)
            block = block - Pos(0, 0, z) * (outer - inner)
        stages = [Stage("housing", block)]
        housing = block + Pos(0, 0, base) * pg["ring"]
        stages.append(Stage("ring", housing))
        # input sun: gear plus a hub down into the base with an M3 set screw onto the D-flat
        sun = pg["sun"] + Cylinder(2.0, T, align=BOTTOM)
        sun = Pos(0, 0, zg[0]) * sun + Pos(0, 0, 0.6) * Cylinder(5.5, base - 0.6 - 0.3, align=BOTTOM) + Pos(0, 0, base - 0.4) * Cylinder(4.2, zg[0] - base + 0.6, align=BOTTOM)
        d = v["shaft_d"] + 0.2
        bore = Cylinder(d / 2, zg[0] + T, align=BOTTOM) - Pos(d / 2 - 0.4 + 5, 0, 0) * Box(10, 10, 60, align=BOTTOM)
        sun = sun - Pos(0, 0, 0.5) * bore
        sun = sun - Pos(4.0, 0, 0.6 + (zg[0] - 0.6) / 2) * Rot(0, 90, 0) * Cylinder(1.25, 3, align=BOTTOM)
        sun = craft.safe_fillet(sun, sun.edges().group_by(Axis.Z)[0], 0.5)
        body = housing + sun
        stages.append(Stage("sun_in", body))
        planets = []
        for k in range(N_STAGES):
            for i in range(N_PLANETS):
                p = pg[f"planet{i}"]
                planets.append(Pos(0, 0, zg[k]) * p)
        for p in planets:
            body = body + p
        stages.append(Stage("planets", body))
        # carriers: a disc above each stage's planets, pins down into the planet bores, the next sun on top
        pin_d = 3.0
        cr = m * (self.SUN + 2 * self.PLANET - 2.5) / 2 - 0.6          # inside the ring's tips
        carriers = []
        for k in range(N_STAGES):
            z0 = zg[k] + T + 0.5
            c = Pos(0, 0, z0) * Cylinder(cr, 3.0, align=BOTTOM)
            for (x, y) in pg.info["planet_centres"]:
                c = c + Pos(x, y, zg[k] + 0.4) * Cylinder(pin_d / 2, T + 0.2, align=BOTTOM)
            if k + 1 < N_STAGES:
                nxt = pg["sun"] + Cylinder(2.0, T, align=BOTTOM)
                c = c + Pos(0, 0, z0 + 2.9) * Cylinder(4.0, zg[k + 1] - z0 - 2.9 + 0.1, align=BOTTOM) + Pos(0, 0, zg[k + 1]) * nxt
            else:
                c = c + Pos(0, 0, z0 + 2.9) * Cylinder(v["out_d"] / 2, top - z0 + 26, align=BOTTOM)
            c = craft.safe_fillet(c, [e for e in c.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - cr) < 0.01], 0.8)
            carriers.append(c)
        for c in carriers[:-1]:
            body = body + c
        stages.append(Stage("carriers", body))
        body = body + carriers[-1]
        stages.append(Stage("output", body))
        # lid: a plate over the housing with a bushing boss for the output shaft, 0.3 mm above the housing
        lid = Pos(0, 0, top + 0.3) * Box(W, W, 4.0, align=BOTTOM)
        lid = craft.safe_fillet(lid, lid.edges().filter_by(Axis.Z), 4.0)
        lid = lid + Pos(0, 0, top + 4.2) * Cylinder(9.0, 5.0, align=BOTTOM)
        lid = lid - Pos(0, 0, top) * Cylinder(v["out_d"] / 2 + 0.25, 12, align=BOTTOM)
        lid = craft.safe_fillet(lid, lid.edges().group_by(Axis.Z)[-1], 1.2)
        body = body + lid
        stages.append(Stage("lid", body))
        # M3 through-bolts into the motor: clearance holes through housing and lid, counterbored in the lid
        h = v["hole_pitch"] / 2
        for sx in (-1, 1):
            for sy in (-1, 1):
                body = body - Pos(sx * h, sy * h, -0.5) * Cylinder(1.7, top + 6, align=BOTTOM)
                body = body - Pos(sx * h, sy * h, top + 4.3 - 3.2) * Cylinder(2.9, 4, align=BOTTOM)
        stages.append(Stage("bolts", body))
        self._top = top
        return parts.checked(stages)

    def derived(self, v):
        r = 1 + (self.SUN + 2 * self.PLANET) / self.SUN
        return [{"key": "stage_ratio", "label": "Ratio per stage", "value": r, "unit": "", "feature": "carriers",
                 "formula": "1 + Zr / Zs (ring fixed, sun in, carrier out)", "interface": False},
                {"key": "total_ratio", "label": "Overall ratio", "value": r ** N_STAGES, "unit": "", "feature": "output",
                 "formula": "(1 + Zr / Zs)^3", "interface": False},
                {"key": "ring_teeth", "label": "Ring teeth", "value": self.SUN + 2 * self.PLANET, "unit": "", "feature": "ring",
                 "formula": "Zs + 2 Zp", "interface": True},
                {"key": "carrier_r", "label": "Planet circle radius", "value": v["module"] * (self.SUN + self.PLANET) / 2,
                 "unit": "mm", "feature": "carriers", "formula": "m (Zs + Zp) / 2", "interface": True}]

    def assembly(self, v):
        # each part named by a point inside it (Part(solid=(x, y, z))): no counting of solids that share one axis
        T, base, zg, top = self._z(v)
        W = v["face_w"]
        pg = getattr(self, "_pg", None)
        cents = pg.info["planet_centres"] if pg else []
        P = [Part("housing", "Housing", (W / 2 - 1.5, 0, top / 2), explode=(-W - 20, 0, 0),
                  note="Bolt-through housing; the ring gear is inside it."),
             Part("sun_in", "Input sun", (0, -4.0, 2.5), note="Push onto the motor shaft, tighten the set screw.")]
        mates, j = [], 1
        for k in range(N_STAGES):
            for i, (x, y) in enumerate(cents):
                P.append(Part(f"planet{k + 1}{i + 1}", f"Planet {k + 1}.{i + 1}", (x * 1.25, y * 1.25, zg[k] + T / 2),
                              explode=(0, 0, 12 * j), note=f"Drop the stage {k + 1} planets in around the sun."))
                mates.append(Mate(f"carrier{k + 1}", f"planet{k + 1}{i + 1}", "pin", v["pin_clear"], f"Planet pin {k + 1}.{i + 1}"))
            P.append(Part(f"carrier{k + 1}", f"Carrier {k + 1}", (0, 0, zg[k] + T + 2.0), explode=(0, 0, 12 * (j + 1)),
                          note=f"Carrier {k + 1}: pins into the planets" + (", its sun into the next stage." if k < 2 else ", output shaft up.")))
            j += 2
        P.append(Part("lid", "Lid", (W / 2 - 3, 0, top + 2.0), explode=(0, 0, 12 * j + 10),
                      note="Lid on; four M3 bolts through into the motor."))
        hw = [Hardware("Socket head cap screw", "M3 x 55", 4, "ISO 4762", "Through lid and housing into the motor", after="lid")]
        return Assembly(parts=P, mates=mates, hardware=hw, budget_s=60)
