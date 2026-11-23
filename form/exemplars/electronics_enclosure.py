"""Two-part electronics enclosure: a rounded box with corner screw bosses for M3 heat-set inserts, a raised lip that
seats in a groove under the lid, a PCB standoff pattern (Raspberry Pi 58 x 49 mm holes), side vent grilles and a
PG7 cable-gland hole; the lid is printed top-down beside the box and fixed with countersunk M3 screws.
Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import (Access, Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError,
                               Stage)

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Electronics enclosure with lid",
    "category": "enclosure",
    "tags": ["enclosure", "box", "case", "electronics", "project box", "pcb", "raspberry pi", "lid", "heat-set insert",
             "insert", "boss", "standoff", "vent", "gland", "seal", "lip", "groove", "assembly"],
    "techniques": ["rounded box: vertical radius R outside, R - wall inside (even wall at the corners)",
                   "parts.heat_insert_pocket in corner bosses sized from boss_min_d",
                   "lip on the box, groove in the lid, clearance per side named",
                   "craft.boss_array PCB standoffs with parts.self_tap_pilot holes",
                   "craft.slot_grille side vents", "parts.screw_clearance countersunk holes in the lid",
                   "lid printed top-down; assembly() flips it on with hardware and tool access"],
    "lessons": [
        "Size bosses from the insert, not by eye: parts.heat_insert_pocket(\"M3\") gives the published 4.0 mm hole and "
        "boss_min_d (hole + 2 x 1.6 mm wall); the boss here is 8 mm and merges into both walls at the corner, so it "
        "cannot snap off when the insert is pressed in hot.",
        "A lid seal is a labyrinth: a lip standing on the inner half of the box wall, a groove in the lid a named "
        "clearance wider on each side and deeper than the lip. It locates the lid, stops dust and splashes, and hides "
        "the parting line; add a cord or foam in the groove for a real IP rating.",
        "Keep the wall even round corners: radius R outside and R - wall inside. Bottom edges get a smaller radius "
        "(2 mm outside) so the box still sits flat and prints without a large overhang.",
        "Print the lid top-down so its visible face is the smooth bed side and the groove faces up; assembly() then "
        "flips it on (Rot 180 about X) and the screws are countersunk so the top stays flush.",
        "Interfaces from standards: Raspberry Pi boards use 58 x 49 mm M2.5 holes; a PG7 cable gland needs a 12.5 mm "
        "hole and a flat land round it for its seal; a gland and vents go on the walls, never on the lid where water "
        "would sit.",
    ],
}


def _rrect(w, d, h, r):
    """A box standing on z = 0 with vertical edges rounded to r."""
    b = Box(w, d, h, align=BOTTOM)
    return craft.safe_fillet(b, b.edges().filter_by(Axis.Z), r) if r > 0.05 else b


class Design(Recipe):
    title, summary = "Electronics enclosure", ("Rounded box and lid with insert bosses, a lip-and-groove seal, PCB "
                                               "standoffs, vents and a cable-gland hole.")
    solids = 2
    params = [
        Param("inner_w", "Inner length", 100, 88, 180, 1, "mm", "brief", "box", "Along X."),
        Param("inner_d", "Inner width", 70, 62, 140, 1, "mm", "brief", "box"),
        Param("inner_h", "Inner height", 36, 20, 80, 1, "mm", "brief", "box", "Floor to rim."),
        Param("wall", "Wall", 2.6, 2.0, 4.0, 0.1, "mm", "form", "box"),
        Param("corner_r", "Corner radius", 6, 5.5, 12, 0.5, "mm", "form", "box"),
        Param("lid_t", "Lid thickness", 3.6, 3.5, 5.0, 0.1, "mm", "form", "lid"),
        Param("lip_h", "Lip height", 2.0, 1.2, 2.0, 0.1, "mm", "interface", "lip"),
        Param("lip_clearance", "Lip clearance / side", 0.2, 0.1, 0.4, 0.05, "mm", "interface", "groove",
              "Sliding fit; 0.15-0.25 mm per side on FDM."),
        Param("pcb_x", "PCB hole spacing X", 58, 30, 70, 0.5, "mm", "brief", "standoffs",
              "Raspberry Pi 4/5 mechanical drawing: 58 x 49 mm, M2.5.", "specified"),
        Param("pcb_y", "PCB hole spacing Y", 49, 20, 58, 0.5, "mm", "brief", "standoffs",
              "Raspberry Pi 4/5 mechanical drawing.", "specified"),
        Param("standoff_h", "Standoff height", 5, 3, 12, 0.5, "mm", "form", "standoffs"),
        Param("gland_d", "Cable gland hole", 12.5, 0, 20.5, 0.1, "mm", "brief", "gland",
              "PG7 gland thread 12.5 mm (DIN 40430); M16 x 1.5 = 16.2. 0 = none.", "specified"),
    ]
    features = [Feature("box", "Box", "structure"), Feature("lip", "Seal lip", "interface"),
                Feature("bosses", "Insert bosses", "interface"), Feature("standoffs", "PCB standoffs", "interface"),
                Feature("vents", "Vent grilles", "access"), Feature("gland", "Cable gland hole", "access"),
                Feature("lid", "Lid", "structure"), Feature("groove", "Lid groove", "interface"),
                Feature("lid_screws", "Lid screw holes", "interface")]

    def constraints(self, v):
        if v["corner_r"] < v["wall"] + 1.5:
            return [RecipeError("The corner radius is too small for the wall", "box", "Raise the corner radius.",
                                ["corner_r", "wall"])]
        if v["pcb_x"] + 8 > v["inner_w"] - 22 or v["pcb_y"] + 8 > v["inner_d"] - 4:
            return [RecipeError("The PCB pattern does not fit beside the bosses", "standoffs", "Enlarge the box or use a "
                                "smaller board.", ["pcb_x", "pcb_y", "inner_w", "inner_d"])]
        if v["gland_d"] > v["inner_h"] - 6:
            return [RecipeError("The gland hole is taller than the wall", "gland", "Use a smaller gland or a taller box.",
                                ["gland_d", "inner_h"])]
        if v["lip_h"] + 0.3 > v["lid_t"] - 1.2:
            return [RecipeError("The groove leaves under 1.2 mm of lid", "groove", "Thicken the lid or lower the lip.",
                                ["lid_t", "lip_h"])]
        return []

    def _dims(self, v):
        t = v["wall"]
        W, D = v["inner_w"] + 2 * t, v["inner_d"] + 2 * t
        Hb = v["inner_h"] + t                     # floor as thick as the wall
        bo = 3.6                                   # boss centre in from the inner walls
        bosses = [(sx * (v["inner_w"] / 2 - bo), sy * (v["inner_d"] / 2 - bo)) for sx in (-1, 1) for sy in (-1, 1)]
        xo = W + 12                                # the lid prints beside the box
        return t, W, D, Hb, bosses, xo

    def build(self, v):
        t, W, D, Hb, bosses, xo = self._dims(v)
        R = v["corner_r"]
        outer = _rrect(W, D, Hb, R)
        outer = craft.safe_fillet(outer, outer.edges().group_by(Axis.Z)[0], 2.0)
        cav = Pos(0, 0, t) * _rrect(v["inner_w"], v["inner_d"], Hb, R - t)
        cav = craft.safe_fillet(cav, cav.edges().group_by(Axis.Z)[0], 1.0)
        box = outer - cav
        stages = [Stage("box", box)]

        # --- snippet: lip on the box, groove in the lid, the clearance named once
        c, lh = v["lip_clearance"], v["lip_h"]
        lip = Pos(0, 0, Hb - 0.2) * (_rrect(W - t, D - t, lh + 0.2, R - t / 2)
                                     - _rrect(v["inner_w"], v["inner_d"], lh + 1, R - t))
        box = box + lip
        stages.append(Stage("lip", box))
        # --- end snippet

        ins = parts.heat_insert_pocket("M3")
        bd = max(8.0, ins["boss_min_d"] + 0.8)
        for x, y in bosses:
            box = box + Pos(x, y, t - 0.2) * Cylinder(bd / 2, Hb - t + 0.2, align=BOTTOM)
            box = box - Pos(x, y, Hb) * ins.shape
        stages.append(Stage("bosses", box))

        pilot = parts.self_tap_pilot("M2.5", v["standoff_h"])
        pts = [(sx * v["pcb_x"] / 2 + 6, sy * v["pcb_y"] / 2) for sx in (-1, 1) for sy in (-1, 1)]
        box = craft.boss_array(box, pts, outer_d=6.0, height=v["standoff_h"], hole_d=pilot["hole_d"], top_z=t - 0.2,
                               hole_depth=v["standoff_h"] + 0.8)
        stages.append(Stage("standoffs", box))

        # side vents: a lens of horizontal slots in each long wall, high up where warm air leaves
        zv = t + v["inner_h"] * 0.62
        for sy in (-1, 1):
            g = craft.slot_grille((6, sy * D / 2, zv), (0, sy, 0), count=max(3, int(v["inner_h"] * 0.42 / 4.8)),
                                  length=min(44, v["inner_w"] * 0.45), width=2.4, pitch=4.8, depth=3 * t, taper=0.3)
            box = craft.cut(box, g)
        stages.append(Stage("vents", box))

        if v["gland_d"] > 0:
            zg = t + v["inner_h"] * 0.45
            box = box - Pos(-W / 2, 0, zg) * Rot(0, 90, 0) * Cylinder(v["gland_d"] / 2, 4 * t)
            stages.append(Stage("gland", box))
        else:
            stages.append(Stage("gland", box))

        # lid, modelled closed on the box (z from Hb up), then laid top-down beside it for printing
        lt = v["lid_t"]
        lid = Pos(0, 0, Hb) * _rrect(W, D, lt, R)
        lid = craft.safe_fillet(lid, lid.edges().group_by(Axis.Z)[-1], 1.6)
        place = lambda s: Pos(xo, 0, lt) * Rot(180, 0, 0) * Pos(0, 0, -Hb) * s
        stages.append(Stage("lid", box + place(lid)))
        groove = Pos(0, 0, Hb - 0.2) * (_rrect(W - t + 2 * c, D - t + 2 * c, lh + 0.5, R - t / 2 + c)
                                        - _rrect(v["inner_w"] - 2 * c, v["inner_d"] - 2 * c, lh + 1, R - t - c))
        lid = lid - groove
        stages.append(Stage("groove", box + place(lid)))
        cs = parts.screw_clearance("M3", lt, head="countersunk")
        for x, y in bosses:
            lid = lid - Pos(x, y, Hb + lt) * cs.shape
        stages.append(Stage("lid_screws", box + place(lid)))
        self._cs, self._ins = cs, ins
        return parts.checked(stages)

    def derived(self, v):
        ins, cs = parts.heat_insert_pocket("M3"), parts.screw_clearance("M3", v["lid_t"], head="countersunk")
        return ins.derived("bosses", "insert.") + cs.derived("lid_screws", "lid_screw.") + [
            {"key": "groove_w", "label": "Groove width", "value": round(v["wall"] / 2 + 2 * v["lip_clearance"], 2),
             "unit": "mm", "feature": "groove", "formula": "lip (wall / 2) + 2 x clearance", "interface": True},
            {"key": "lip_t", "label": "Lip thickness", "value": round(v["wall"] / 2, 2), "unit": "mm", "feature": "lip",
             "formula": "inner half of the wall", "interface": True}]

    def assembly(self, v):
        t, W, D, Hb, bosses, xo = self._dims(v)
        lt = v["lid_t"]
        L = int(round(lt + 6))
        return Assembly(
            parts=[Part("box", "Box", (0, -v["inner_d"] / 2 + 1, t / 2), note="Press the four M3 inserts into the "
                        "bosses with a soldering iron, screw the board to the standoffs."),
                   Part("lid", "Lid", (xo, 0, lt / 2), move=(-xo, 0, Hb + lt), rotate=(180, 0, 0), explode=(0, 0, 40),
                        note="Turn the lid over and seat its groove on the box lip.")],
            # one Mate per pair: the lid rests on the rim and bosses (contact); the lip's clearance in the groove is a
            # derived() row, since a pair's gap is measured once, at its closest point
            mates=[Mate("lid", "box", "contact", 0.0, "Lid on the rim and bosses, lip in the groove")],
            hardware=[Hardware("M3 heat-set insert", "M3 x 5.7", 4, "CNC Kitchen", "Press into the bosses.", after="box"),
                      Hardware("M2.5 screw", "M2.5 x 6", 4, "ISO 7045 pan head", "Board to the standoffs.", after="box"),
                      Hardware("M3 countersunk screw", f"M3 x {L}", 4, "ISO 10642", "Lid to the box.", after="lid",
                               access=tuple(Access((x, y, Hb + lt), (0, 0, -1), 5.5, 60) for x, y in bosses))])

    def appearance(self, v):
        return [{"features": ["lid", "groove", "lid_screws"], "finish": "matte", "color": "#3a3f45"},
                {"features": ["box", "lip", "bosses", "standoffs", "vents", "gland"], "finish": "matte",
                 "color": "#d9d6cf"}]
