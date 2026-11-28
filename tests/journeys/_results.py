"""Real small studies for the journeys of the results drawn on the part (tests/journeys/results.py).

Each design is a few lines of build123d; each study is run by the engine it belongs to, in the journey's own data
folder. Nothing here is a canned result: the journeys read what the engines computed.

BRACKET  an L bracket: a static and a modal strength study (needs the FEA engine, $FORM_FEA_PYTHON or installed),
         the CNC manufacturability check and a drawing
POCKET   a plate with a pocket: CNC toolpaths and the stock simulation
TRAY     a sheet-metal tray with four flanges: the flat pattern
FOURBAR  a crank-rocker linkage: a motion study with clearance along the cycle
CUP      an open box with straight walls: the moulding check fails on draft, and its fix passes
"""

BRACKET = '''
from build123d import Align, Box, Cylinder, Pos, Rot, fillet
from form.recipes.base import Feature, Param, Recipe, Stage

M = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Bracket"
    summary = "An L bracket with a filleted inside corner and three holes."
    params = [Param("t", "Thickness", 6, 3, 12, 0.5, "mm", "form", "body"),
              Param("r", "Fillet", 6, 0, 10, 0.5, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        t = v["t"]
        s = Box(80, 40, t, align=M) + Box(t, 40, 60, align=M)
        if v["r"] > 0:
            e = [e for e in s.edges() if abs(e.center().X - t) < 1e-6 and abs(e.center().Z - t) < 1e-6]
            s = fillet(e, v["r"])
        s -= Pos(30, 20, 0) * Cylinder(3, 3 * t)
        s -= Pos(62, 20, 0) * Cylinder(3, 3 * t)
        s -= Pos(0, 20, 42) * Rot(0, 90, 0) * Cylinder(3, 3 * t)
        return [Stage("body", s)]
'''

POCKET = '''
from build123d import Box, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Pocket plate"
    params = [Param("depth", "Pocket depth", 4.0, 1, 8, 0.5, "mm", "form", "pocket")]

    @feature("Body")
    def body(self, v, body):
        return Box(40, 30, 10)

    @feature("Pocket")
    def pocket(self, v, body):
        return body - Pos(0, 0, 5 - v["depth"] / 2) * Box(20, 14, v["depth"])
'''

TRAY = '''
from build123d import Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param
from form.sheet.build import Sheet


class Design(FeatureDesign):
    params = [Param("t", "Thickness", 1.5, 0.5, 6), Param("w", "Width", 80, 20, 300), Param("d", "Depth", 50, 20, 300),
              Param("h", "Flange", 20, 3, 100)]

    @feature("Sheet")
    def body(self, v, body):
        s = Sheet(t=v["t"], r=v["t"], material="steel_mild")
        b = s.base([(0, 0), (v["w"], 0), (v["w"], v["d"]), (0, v["d"])])
        for i in range(4):
            s.flange(b.edge(i), v["h"], 90)
        return s.solid()

    @feature("Hole")
    def hole(self, v, body):
        return body - Pos(v["w"] / 2, v["d"] / 2, 0) * Cylinder(3, 20)
'''

FOURBAR = '''import math

from build123d import Align, Box, Cylinder, Pos, Rot
from form.recipes.base import Assembly, Feature, Loop, Param, Part, Recipe, Stage, hinge

A_, B_, C_, D_, T20 = 20.0, 60.0, 50.0, 55.0, 60.0
UP = (Align.CENTER, Align.CENTER, Align.MIN)


def rocker_angle():
    t2 = math.radians(T20)
    K1, K2, K3 = D_ / A_, D_ / C_, (A_ * A_ - B_ * B_ + C_ * C_ + D_ * D_) / (2 * A_ * C_)
    a = math.cos(t2) - K1 - K2 * math.cos(t2) + K3
    b = -2 * math.sin(t2)
    c = K1 - (K2 + 1) * math.cos(t2) + K3
    return 2 * math.atan2(-b - math.sqrt(b * b - 4 * a * c), 2 * a)


def bar(p, q, z):
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    ang = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, z)
    return (Pos(*mid) * Rot(0, 0, ang) * Box(L, 6, 3, align=UP) + Pos(p[0], p[1], z) * Cylinder(3, 3, align=UP)
            + Pos(q[0], q[1], z) * Cylinder(3, 3, align=UP))


class Design(Recipe):
    title = "Four-bar linkage"
    summary = "A crank-rocker four-bar on a ground plate."
    params = [Param("s", "Scale", 1, 0.5, 2, 0.1, "", "form", "links")]
    features = [Feature("links", "Links", "structure")]
    solids = 4

    def pts(self):
        t2, t4 = math.radians(T20), rocker_angle()
        return (0.0, 0.0), (D_, 0.0), (A_ * math.cos(t2), A_ * math.sin(t2)), (D_ + C_ * math.cos(t4), C_ * math.sin(t4))

    def build(self, v):
        O2, O4, A, B = self.pts()
        ground = Pos(D_ / 2, -40, 0) * Box(D_ + 20, 16, 4, align=UP)
        return [Stage("links", ground + bar(O2, A, 5) + bar(A, B, 9) + bar(O4, B, 5))]

    def assembly(self, v):
        O2, O4, A, B = self.pts()
        mid = lambda p, q, z: ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, z)
        return Assembly(
            parts=[Part("ground", "Ground", (D_ / 2, -40, 2)), Part("crank", "Crank", mid(O2, A, 6.5)),
                   Part("coupler", "Coupler", mid(A, B, 10.5)), Part("rocker", "Rocker", mid(O4, B, 6.5))],
            joints=[hinge("crank", (0, 0, 1), (*O2, 0), (0, 360), id="crank", label="Crank", parent="ground"),
                    hinge("coupler", (0, 0, 1), (*A, 0), (-360, 360), id="coupler", label="Coupler pin", parent="crank"),
                    hinge("rocker", (0, 0, 1), (*O4, 0), (-360, 360), id="rocker", label="Rocker", parent="ground")],
            loops=[Loop("coupler", "rocker", (*B, 0), (0, 0, 1), label="Coupler to rocker pin")])
'''

CUP = '''
from build123d import Box, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Cup"
    params = [Param("wall", "Wall", 2.0, 0.4, 6, 0.1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        w = v["wall"]
        return Box(40, 30, 20) - Pos(0, 0, w) * Box(40 - 2 * w, 30 - 2 * w, 20)
'''

ALU = {"name": "6061-T6 (test)", "E_GPa": 68.9, "poisson": 0.33, "yield_MPa": 276, "density_kg_m3": 2700,
       "source": "test fixture"}
STATIC = {"kind": "static", "name": "Shelf load", "material": ALU,
          "fixtures": [{"type": "fixed", "faces": [[33, 20, 3], [65, 20, 3]]}],
          "loads": [{"type": "force", "faces": [[3, 20, 45]], "vector": [300, 0, -200]}],
          "mesh": {"budget_s": 40}}
MODAL = {"kind": "modal", "name": "Modes", "material": ALU, "modes": 3,
         "fixtures": [{"type": "fixed", "faces": [[33, 20, 3], [65, 20, 3]]}], "mesh": {"budget_s": 30}}
FLAT_TOOL = {"kind": "flat", "d": 6, "flutes": 3, "flute_l": 18, "length": 30, "holder_d": 28, "holder_l": 30}
CAM_OPTS = {"tools": [FLAT_TOOL], "material": "aluminum"}


def design(st, name, src, material="AL-6061", **kw):
    """A design from source, with a material from the library. Returns its id."""
    from form import materials
    p = st.create_design(name, src, purpose="model", **kw)
    if material:
        materials.set_appearance(st, p["id"], "", "keep", material)
    return p["id"]


def fea_ready(st) -> bool:
    from form import fea
    return fea.python(st.cfg) is not None


def strength(st, pid, body):
    """Define and solve one strength study; returns its id."""
    from form.fea import study
    d = study.define(st, st.load(pid), body, by="person")
    study.run(st, pid, d["id"])
    return d["id"]


def bench(st, pid, sid, **opts):
    """Run one Bench entry to the end (the same call the window's Run makes) and return the entry."""
    from form import studies
    return studies.start(st, pid, sid, wait=True, **opts)["entry"]


def seed(st, fea=None) -> dict:
    """The four designs with their studies run through the Bench. Returns {name: project id}. Strength is left
    undefined when the FEA engine is not here (the journeys then check the "not run" state instead)."""
    from form.cam import project as cam
    ids = {"bracket": design(st, "Bracket", BRACKET)}
    if fea if fea is not None else fea_ready(st):
        ids["static"] = strength(st, ids["bracket"], STATIC)
        ids["modal"] = strength(st, ids["bracket"], MODAL)
    bench(st, ids["bracket"], "dfm_injection")
    bench(st, ids["bracket"], "dfm_cnc", options={"tool_d": 6, "material": "metal"})
    bench(st, ids["bracket"], "drawing")
    ids["cup"] = design(st, "Cup", CUP, material=None)
    bench(st, ids["cup"], "dfm_injection", options={"resin": "abs"})
    ids["pocket"] = design(st, "Pocket plate", POCKET, process="cnc")
    cam.plan(st, st.load(ids["pocket"]), CAM_OPTS)
    bench(st, ids["pocket"], "cam_3axis")
    ids["tray"] = design(st, "Tray", TRAY, material=None)
    bench(st, ids["tray"], "sheet_flat")
    ids["fourbar"] = design(st, "Four-bar", FOURBAR)
    bench(st, ids["fourbar"], "motion", drivers=[{"joint": "crank", "from": 0, "to": 360}], frames=37)
    return ids
