"""Designs the stack-up tests build (tests/test_stack.py). Each is a design's code, as an agent would write it."""

# A box with a centre boss and a blind pilot hole, a lid with a clearance hole, and a screw through both. Printed
# side by side; assembled: the lid on the rim, the screw head on the lid, its tip above the floor of the hole.
# gap (tip to hole floor) = lid_t + hole_depth - screw_l
BOX_LID_SCREW = '''from build123d import Align, Box, Cylinder, Pos
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, Stage

MIN_Z = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Box, lid and screw"
    summary = "A box with a boss, a lid and a screw for the stack-up tests."
    solids = 3
    params = [
        Param("box_h", "Box height", 20, 10, 40, 0.1, "mm", "form", "box"),
        Param("floor", "Floor", 2, 1, 4, 0.1, "mm", "form", "box"),
        Param("wall", "Wall", 2, 1.2, 4, 0.1, "mm", "form", "box"),
        Param("hole_depth", "Pilot hole depth", 12, 5, 16, 0.1, "mm", "interface", "hole"),
        Param("lid_t", "Lid thickness", 3, 1.5, 6, 0.1, "mm", "form", "lid"),
        Param("screw_l", "Screw length", 12, 6, 20, 0.1, "mm", "interface", "screw"),
        Param("head_k", "Head height", 2, 1, 4, 0.1, "mm", "form", "screw"),
    ]
    features = [Feature("box", "Box", "structure"), Feature("boss", "Boss", "structure"),
                Feature("hole", "Pilot hole", "interface"), Feature("lid", "Lid", "structure"),
                Feature("screw", "Screw", "interface")]

    def build(self, v):
        h, f, w = v["box_h"], v["floor"], v["wall"]
        box = Box(40, 30, h, align=MIN_Z) - Pos(0, 0, f) * Box(40 - 2 * w, 30 - 2 * w, h, align=MIN_Z)
        boss = box + Cylinder(4, h, align=MIN_Z)
        hole = boss - Pos(0, 0, h - v["hole_depth"]) * Cylinder(1.25, v["hole_depth"] + 1, align=MIN_Z)
        lid = hole + Pos(60, 0, 0) * (Box(40, 30, v["lid_t"], align=MIN_Z) - Cylinder(1.7, 20))
        L, k = v["screw_l"], v["head_k"]
        screw = lid + Pos(100, 0, 0) * (Cylinder(1.5, L, align=MIN_Z) + Pos(0, 0, L) * Cylinder(2.75, k, align=MIN_Z))
        return [Stage("box", box), Stage("boss", boss), Stage("hole", hole), Stage("lid", lid), Stage("screw", screw)]

    def assembly(self, v):
        h, t, L = v["box_h"], v["lid_t"], v["screw_l"]
        return Assembly(parts=[Part("box", "Box", (0, 0, 1)), Part("lid", "Lid", (60, 0, 0.5), move=(-60, 0, h)),
                               Part("screw", "Screw", (100, 0, 1), move=(-100, 0, h + t - L))],
                        mates=[Mate("screw", "lid", "contact"), Mate("lid", "box", "contact"),
                               Mate("screw", "box", "thread", axis=(0, 0, 1))])
'''

# A pin with a square cap in a hole of a plate that has a wall. The gap from the cap's side to the wall, square to the
# pin: gap = wall_x - hole_x - cap_w / 2, and the pin floats in its hole by (hole_d - pin_d) / 2 either way.
PIN = '''from build123d import Align, Box, Cylinder, Pos
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, Stage

MIN = (Align.MIN, Align.MIN, Align.MIN)
MIN_Z = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Pin in a plate"
    summary = "A radial fit across the gap, for the stack-up tests."
    solids = 2
    params = [
        Param("hole_x", "Hole from the edge", 20, 10, 30, 0.1, "mm", "interface", "hole"),
        Param("wall_x", "Wall from the edge", 50, 40, 55, 0.1, "mm", "form", "wall"),
        Param("hole_d", "Hole", 6.2, 6.05, 7, 0.01, "mm", "interface", "hole"),
        Param("pin_d", "Pin", 6, 5, 6, 0.01, "mm", "interface", "pin"),
        Param("cap_w", "Cap width", 10, 8, 14, 0.1, "mm", "form", "cap"),
    ]
    features = [Feature("plate", "Plate", "structure"), Feature("wall", "Wall", "structure"),
                Feature("hole", "Hole", "interface"), Feature("pin", "Pin", "interface"), Feature("cap", "Cap", "form")]

    def build(self, v):
        plate = Box(60, 30, 4, align=MIN)
        wall = plate + Pos(v["wall_x"], 0, 4) * Box(4, 30, 10, align=MIN)
        hole = wall - Pos(v["hole_x"], 15, 0) * Cylinder(v["hole_d"] / 2, 10)
        pin = hole + Pos(20, 60, 0) * Cylinder(v["pin_d"] / 2, 8, align=MIN_Z)
        c = v["cap_w"]
        cap = pin + Pos(20, 60, 8) * Box(c, c, 3, align=MIN_Z)
        return [Stage("plate", plate), Stage("wall", wall), Stage("hole", hole), Stage("pin", pin), Stage("cap", cap)]

    def assembly(self, v):
        return Assembly(parts=[Part("plate", "Plate", (2, 2, 2)), Part("pin", "Pin", (20, 60, 9),
                                                                         move=(v["hole_x"] - 20, 15 - 60, -4))],
                        mates=[Mate("pin", "plate", "pin")])
'''

# A plate with a post, a ramp seated on the plate and a cover seated on the post. The gap from the ramp's high edge
# up to the cover depends on the ramp's angle: gap = post_h - h - W tan(theta), d gap / d theta = -W sec^2(theta)
# per radian. Printed apart (y = 0, 60, 120); assembled on the plate.
RAMP = '''import math
from build123d import Align, Box, Plane, Polygon, Pos, extrude
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, Stage

MIN = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Ramp under a cover"
    summary = "A gap set by an angle, for the stack-up tests."
    solids = 3
    params = [
        Param("plate_t", "Plate", 2, 1, 5, 0.1, "mm", "form", "base"),
        Param("post_h", "Post height", 20, 12, 40, 0.1, "mm", "form", "post"),
        Param("ramp_w", "Ramp length", 30, 10, 40, 0.1, "mm", "form", "ramp"),
        Param("ramp_h", "Ramp low end", 5, 2, 10, 0.1, "mm", "form", "ramp"),
        Param("theta", "Ramp angle", 10, 0, 20, 0.1, "deg", "form", "ramp"),
        Param("cover_t", "Cover", 2, 1, 5, 0.1, "mm", "form", "cover"),
    ]
    features = [Feature("base", "Plate", "structure"), Feature("post", "Post", "structure"),
                Feature("ramp", "Ramp", "structure"), Feature("cover", "Cover", "structure")]

    def build(self, v):
        W, h = v["ramp_w"], v["ramp_h"]
        top = h + W * math.tan(math.radians(v["theta"]))
        base = Box(60, 30, v["plate_t"], align=MIN)
        post = base + Pos(50, 0, v["plate_t"]) * Box(5, 30, v["post_h"], align=MIN)
        prof = Plane.XZ * Polygon((0, 0), (W, 0), (W, top), (0, h), align=None)
        ramp = post + Pos(0, 80, 0) * extrude(prof, 20)
        cover = ramp + Pos(0, 120, 0) * Box(60, 30, v["cover_t"], align=MIN)
        return [Stage("base", base), Stage("post", post), Stage("ramp", ramp), Stage("cover", cover)]

    def assembly(self, v):
        t, ph = v["plate_t"], v["post_h"]
        return Assembly(parts=[Part("base", "Plate", (25, 15, t / 2)), Part("ramp", "Ramp", (1, 70, 0.5), move=(0, -55, t)),
                               Part("cover", "Cover", (25, 135, v["cover_t"] / 2), move=(0, -120, t + ph))],
                        mates=[Mate("ramp", "base", "contact"), Mate("cover", "base", "contact")])
'''
