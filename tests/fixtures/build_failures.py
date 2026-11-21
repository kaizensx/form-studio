"""Designs that fail the way the seven kernel failures of one owner conversation failed: an agent rebuilding a sliding
wallet from meshes as lofts between level sections, fused steps and a pivot. The conversation did not save its
sources, so each class reproduces its failure from the recorded error and line. With SAFE = True the failing call is
replaced by its form.craft.safe_* counterpart. tests/test_build_diag.py builds both.

    F1 item_44  loft through three level sections            -> BRep_API: command not done    safe_loft
    F2 item_45  "Fusion failed at step 0": steps 0.01 mm apart                                 safe_union
    F3 item_46  "Fusion failed at step 0": a pivot boss resting 0.02 mm above the deck         safe_union
    F4 item_54  "The result is 5 solid(s); this design declares 1": cascade steps not touching safe_union
    F5 item_55  "Solid details [...]": a part 3 mm away from the body                          (none: it is apart)
    F6 item_66  loft([f0, f1], ruled=True) between an L and a star -> BRep_API: command not done   safe_loft
    F7 item_67  "Loft failed (1.499, 2.3, [0, 0], 9, 14) BRep_API: command not done"           safe_loft
    F8 base     "Failed creating a fillet with radius of 2.0"                                  safe_fillet
    F9 base     "Failed creating a chamfer"                                                    safe_chamfer
"""
import math

from build123d import Align, Box, Cylinder, Pos, Vector, Wire, loft, make_face

from form import craft
from form.recipes.base import Feature, Param, Recipe, Stage

SAFE = False
BOTTOM = (Align.MIN, Align.MIN, Align.MIN)

L_LEVEL = [(0, 0), (40, 0), (40, 10), (10, 10), (10, 30), (0, 30)]
RECT = [(0, 0), (40, 0), (40, 30), (0, 30)]
STAR = [((16 if i % 2 else 8) * math.cos(2 * math.pi * i / 14) + 20,
         (16 if i % 2 else 8) * math.sin(2 * math.pi * i / 14) + 15) for i in range(14)]
P9 = [(20 + 10 * math.cos(2 * math.pi * i / 9), 15 + 6 * math.sin(2 * math.pi * i / 9)) for i in range(9)]
P14 = [(20 + 8 * math.cos(2 * math.pi * i / 14 + 2.5), 15 + 5 * math.sin(2 * math.pi * i / 14 + 2.5))
       for i in range(14)][::-1]


def level(pts, z):
    return make_face(Wire.make_polygon([Vector(x, y, z) for x, y in pts], close=True))


class _Base(Recipe):
    title, summary = "Failure fixture", "A design that reproduces a recorded kernel failure."
    params = [Param("h", "Height", 3.0, 1.0, 6.0, 0.1, "mm", "form", "base")]
    features = [Feature("base", "Base plate", "form"), Feature("steps", "Cascade steps", "form"),
                Feature("pivot", "Pivot", "interface")]


class F1(_Base):
    def build(self, v):
        base = Box(40, 30, 1.0, align=BOTTOM)
        stages = [Stage("base", base)]
        secs = [level(L_LEVEL, 1.0), level(RECT, 1.0 + v["h"]), level(L_LEVEL, 1.0 + 2 * v["h"])]
        skin = craft.safe_loft(secs) if SAFE else loft(secs)
        body = base + skin
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body - Pos(5, 5, -1) * Cylinder(2, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))))
        return stages


class F2(_Base):
    def build(self, v):
        body = Box(40, 30, 1.0, align=BOTTOM)
        stages = [Stage("base", body)]
        z = 1.0
        for i, w in enumerate((34, 28, 22)):
            step = Pos(0, 0, z + 0.01) * Box(w, 30, v["h"] / 3, align=BOTTOM)    # 0.01 mm above: never touches
            body = craft.safe_union(body, step) if SAFE else body + step
            if len(body.solids()) != 1:
                raise ValueError("Fusion failed at step " + str(i))
            z += v["h"] / 3 + 0.01
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body))
        return stages


class F3(_Base):
    def build(self, v):
        body = Box(40, 30, 1.0, align=BOTTOM)
        stages = [Stage("base", body), Stage("steps", body)]
        boss = Pos(8, 8, 1.02) * Cylinder(4, v["h"], align=(Align.CENTER, Align.CENTER, Align.MIN))
        body = craft.safe_union(body, boss) if SAFE else body + boss
        if len(body.solids()) != 1:
            raise ValueError("Fusion failed at step 0")
        stages.append(Stage("pivot", body))
        return stages


class F4(_Base):
    def build(self, v):
        body = Box(40, 30, 1.0, align=BOTTOM)
        stages = [Stage("base", body)]
        steps = [Pos(8 * i, 0, 1.02) * Box(7.98, 30, 0.5 + 0.4 * i, align=BOTTOM) for i in range(4)]
        body = craft.safe_union(body, *steps) if SAFE else body + steps[0] + steps[1] + steps[2] + steps[3]
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body))
        return stages


class F5(_Base):
    def build(self, v):
        body = Box(40, 30, 1.0, align=BOTTOM)
        stages = [Stage("base", body)]
        tab = Pos(43, 0, 0) * Box(10, 30, 1.0, align=BOTTOM)                       # 3 mm away
        body = craft.safe_union(body, tab) if SAFE else body + tab
        if len(body.solids()) != 1:
            raise ValueError("Solid details " + str([(round(s.volume, 1), str(s.bounding_box())) for s in body.solids()]))
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body))
        return stages


class F6(_Base):
    def build(self, v):
        base = Box(40, 30, 1.0, align=BOTTOM)
        stages = [Stage("base", base)]
        f0, f1 = level(L_LEVEL, 1.0), level(STAR, 1.0 + v["h"] / 4)
        s = craft.safe_loft([f0, f1], ruled=True) if SAFE else loft([f0, f1], ruled=True)
        body = base + s
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body))
        return stages


class F7(_Base):
    def build(self, v):
        base = Box(40, 30, 1.0, align=BOTTOM)
        stages = [Stage("base", base)]
        z0, z1 = 1.0, 1.0 + v["h"] / 3
        secs = [level(P9, z0), level(P14, z1), level(P9, z1 + v["h"] / 3)]
        try:
            s = craft.safe_loft(secs) if SAFE else loft(secs)
        except Exception as e:
            raise ValueError("Loft failed " + str((z0, z1, [0, 0], 9, 14)) + " " + str(e))
        body = base + s
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body))
        return stages


class F8(_Base):
    def build(self, v):
        plate = Box(40, 30, 3.0, align=BOTTOM)
        stages = [Stage("base", plate)]
        body = craft.safe_fillet(plate, plate.edges(), 2.0) if SAFE else plate.fillet(2.0, plate.edges())
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body))
        return stages


class F9(_Base):
    def build(self, v):
        plate = Box(40, 30, 3.0, align=BOTTOM)
        stages = [Stage("base", plate)]
        body = craft.safe_chamfer(plate, plate.edges(), 2.0) if SAFE else plate.chamfer(2.0, None, plate.edges())
        stages.append(Stage("steps", body))
        stages.append(Stage("pivot", body))
        return stages


ALL = {"F1": F1, "F2": F2, "F3": F3, "F4": F4, "F5": F5, "F6": F6, "F7": F7, "F8": F8, "F9": F9}
REPAIRABLE = ("F1", "F2", "F3", "F4", "F6", "F7", "F8", "F9")


# ---- boolean failures of the owner's helmet conversation (d244f7900cc0) ---------------------------------------------
# The conversation saved no sources; each pair rebuilds the recorded call's situation on a small lofted dome shell
# (80 x 60 x 40 mm, 2 mm wall). tests/test_boolean_engine.py runs them through form.craft.boolean.
#
#   H1 line 99/105  craft.fuse(body, craft.surface_band(...))   a band on the same offset surface as a band already
#                                                                fused, meeting it edge to edge   -> coincident_faces
#   H2 line 127     craft.fuse(back, face, min_solids=2, max_solids=2)   two halves touching at the split plane
#                                                                                                 -> parts_touch
#   H3 line 99      craft.cut(body, cut)   a tool whose face runs 0.0005 mm outside the shell's skin -> grazing
#                   (OCCT returns the shell unchanged and valid: a silent wrong result the oracle must catch)
#   H4              an operand that is not a valid solid (an open shell: a box with its top face missing)
#                                                                                                 -> invalid_operand

_H: dict = {}


def _fresh(shape):
    """A deep copy: a plain boolean raises its operands' tolerances in place, so every pair gets its own shell."""
    from form.craft.boolean import _copy
    return _copy(shape)


def helmet_shell():
    """(sections, tip, outer, shell): the dome and its 2 mm shell, built once per process."""
    if not _H:
        secs, tip = craft.dome_sections(80, 60, 40, levels=6)
        outer = craft.section_body(secs, tip=tip)
        inner = craft.inset_body(secs, 2.0, tip=tip)
        _H.update(secs=secs, tip=tip, outer=outer, shell=outer - inner)
    return _H["secs"], _H["tip"], _H["outer"], _H["shell"]


def coincident_band():
    """H1: (body, band). body = shell + a 1 mm band; band = a second 1 mm band (the same offset surface) whose region
    meets the first one edge to edge, its root sunk 1 mm into the wall (so the two do overlap)."""
    if "h1" not in _H:
        secs, tip, _o, shell = helmet_shell()
        b1 = craft.surface_band(secs, tip, 1.0, Pos(0, 0, 30) * Box(20, 20, 30), depth=1.0)
        b2 = craft.surface_band(secs, tip, 1.0, Pos(20, 0, 30) * Box(20, 20, 30), depth=1.0)
        _H["h1"] = (_fresh(shell) + b1, b2)
    return _H["h1"]


def touching_halves():
    """H2: (back, face): the shell split at x = 0 into two halves that touch over the split plane."""
    if "h2" not in _H:
        _s, _t, _o, shell = helmet_shell()
        _H["h2"] = (_fresh(shell) & Pos(-50, 0, 0) * Box(100, 200, 200), _fresh(shell) & Pos(50, 0, 0) * Box(100, 200, 200))
    return _H["h2"]


def grazing_cut():
    """H3: (shell, tool): the dome grown by 0.0005 mm, clipped to a 30 mm box at the crown; it should take a 30 mm
    patch out of the wall."""
    if "h3" not in _H:
        secs, tip, _o, shell = helmet_shell()
        _H["h3"] = (_fresh(shell), craft.offset_body(secs, tip, 0.0005) & Pos(0, 0, 30) * Box(30, 30, 30))
    return _H["h3"]


def invalid_operand():
    """H4: (body, tool): body is a box with its top face missing made into a solid (not valid: an open shell)."""
    from build123d import Shell, Solid
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.TopoDS import TopoDS
    box = Box(20, 20, 20)
    ms = BRepBuilderAPI_MakeSolid()
    ms.Add(TopoDS.Shell(Shell(box.faces()[:-1]).wrapped))
    return Solid(ms.Solid()), Cylinder(3, 40)


BOOLEAN = {"H1": ("fuse", coincident_band, {}, "coincident_faces"),
           "H2": ("fuse", touching_halves, {"min_solids": 2, "max_solids": 2}, "parts_touch"),
           "H3": ("cut", grazing_cut, {}, "grazing"),
           "H4": ("cut", invalid_operand, {}, "invalid_operand")}
