"""Motion studies, robot files and assembly sequences (waves I and Y) against known answers.

Kinematics (no kernel): a planar four-bar solved by Newton's method on its loop-closure equation, against the closed
form (Freudenstein; Norton, Design of Machinery, eq. 4.10) for a Grashof crank-rocker over a full turn of the crank
(accepted error 1e-5 degrees), and a non-Grashof linkage, whose frames that do not close must be exactly the crank
angles where the closed form has no real root. Couplings against their ratios. On real designs (the kernel): the
holding torque of a hinged arm against m g (x cos t - z sin t); the URDF's inertia equal to wave C's mass properties;
the MJCF loaded by MuJoCo where it is installed; the sequence of a box with a lid and two screws. Tests use their own
FORM_DATA, never the owner's data."""
import math
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="form-motion-")
os.environ["FORM_DATA"] = TMP

from form import config, instructions, massprops, materials, motion, robot, sequence  # noqa: E402
from form.recipes.assembly import (Assembly, Coupling, Loop, Part, ball, cam, cylindrical, gears, hinge,  # noqa: E402
                                   joint_matrix, lead_screw, rack, slide)
from form.studio import Studio, StudioError  # noqa: E402

DEG_TOL = 1e-5


def fourbar(a, b, c, d, t20=60.0):
    """A planar four-bar modelled at crank angle t20: ground pivots at (0, 0) and (d, 0), the coupler pinned to the
    rocker by a Loop."""
    t40 = motion.fourbar_rocker(a, b, c, d, t20)
    A = (a * math.cos(math.radians(t20)), a * math.sin(math.radians(t20)), 0.0)
    B = (d + c * math.cos(math.radians(t40)), c * math.sin(math.radians(t40)), 0.0)
    spec = Assembly(parts=[Part("ground", "Ground", 0), Part("crank", "Crank", 1), Part("coupler", "Coupler", 2),
                           Part("rocker", "Rocker", 3)],
                    joints=[hinge("crank", (0, 0, 1), (0, 0, 0), (0, 360), id="crank", parent="ground"),
                            hinge("coupler", (0, 0, 1), A, (-360, 360), id="coupler", parent="crank"),
                            hinge("rocker", (0, 0, 1), (d, 0, 0), (-360, 360), id="rocker", parent="ground")],
                    loops=[Loop("coupler", "rocker", B, (0, 0, 1))])
    return spec, t40, A, B


def wrap(x):
    return (x + 180.0) % 360.0 - 180.0


class FourBar(unittest.TestCase):
    def test_grashof_classes(self):
        self.assertEqual(motion.grashof(20, 60, 50, 55)["class"], "crank-rocker")
        self.assertEqual(motion.grashof(40, 50, 45, 30)["class"], "double crank")
        self.assertEqual(motion.grashof(40, 20, 45, 50)["class"], "double rocker")
        self.assertFalse(motion.grashof(40, 70, 50, 30)["grashof"])
        self.assertEqual(motion.grashof(40, 60, 50, 30)["class"], "change point (s + l = p + q)")
        self.assertEqual(motion.grashof(40, 70, 50, 30)["class"], "non-Grashof (triple rocker)")

    def test_crank_rocker_against_closed_form(self):
        dims = (20.0, 60.0, 50.0, 55.0)
        spec, t40, A, B = fourbar(*dims)
        r = motion.study(spec, [{"joint": "crank", "from": 0, "to": 360}], duration_s=2.0, frames=145,
                         traces=[{"part": "coupler", "at": list(B), "label": "pin B"}])
        self.assertEqual(r["closed_frames"], 145)                      # Grashof, crank shortest: a full turn
        rk = next(j for j in r["joints"] if j["joint"] == "rocker")
        self.assertEqual(rk["role"], "solved (loop)")
        worst = 0.0
        for f, v in zip(r["frames"], rk["value"]):
            t2 = 60.0 + f["t"] / 2.0 * 360.0
            ref = motion.fourbar_rocker(*dims, t2)
            worst = max(worst, abs(wrap(t40 + v - ref)))
        self.assertLess(worst, DEG_TOL, "rocker angle against Freudenstein")
        # the traced pin B sits on the rocker's circle about (d, 0) and on the coupler's about A, every frame
        tr = r["traces"][0]
        for f, P in zip(r["frames"], tr["positions_mm"]):
            t2 = math.radians(60.0 + f["t"] / 2.0 * 360.0)
            Ax, Ay = dims[0] * math.cos(t2), dims[0] * math.sin(t2)
            self.assertAlmostEqual(math.hypot(P[0] - dims[3], P[1]), dims[2], places=5)
            self.assertAlmostEqual(math.hypot(P[0] - Ax, P[1] - Ay), dims[1], places=5)
        # rocker angular velocity against the derivative of the closed form (central differences in both)
        dt = 2.0 / 144
        for i in range(10, 140, 13):
            t2 = 60.0 + r["frames"][i]["t"] / 2.0 * 360.0
            ref = wrap(motion.fourbar_rocker(*dims, t2 + 180.0 * dt) - motion.fourbar_rocker(*dims, t2 - 180.0 * dt)) / (2 * dt)
            self.assertAlmostEqual(rk["velocity"][i], ref, delta=max(0.5, abs(ref) * 0.01))

    def test_non_grashof_frames_that_do_not_close(self):
        dims = (40.0, 70.0, 50.0, 30.0)                                # s + l = 100 > p + q = 90: no link turns fully
        spec, t40, A, B = fourbar(*dims, t20=90.0)
        n = 181
        r = motion.study(spec, [{"joint": "crank", "from": -90, "to": 90}], duration_s=1.0, frames=n)
        self.assertLess(r["closed_frames"], n)
        self.assertTrue(r["open_frames"])
        for f in r["frames"]:
            t2 = 90.0 + (-90.0 + 180.0 * f["t"])
            ref = motion.fourbar_rocker(*dims, t2)
            near_limit = any(motion.fourbar_rocker(*dims, t2 + s) is None for s in (-1.5, 1.5))
            if near_limit:
                continue                                               # within a frame step of the limit
            self.assertEqual(f["closed"], ref is not None, f"t2 = {t2:g}")
        self.assertTrue(any("do not close" in x for x in r["notes"]))

    def test_loop_must_close_as_modelled(self):
        spec, _, A, B = fourbar(20.0, 60.0, 50.0, 55.0)
        spec.couplings = [Coupling("crank", "rocker", 0.0, 10.0)]     # holds the rocker at 10° at rest: the loop is open
        with self.assertRaises(motion.MotionError):
            motion.study(spec)

    def test_placement_round_trip(self):
        from form.recipes.assembly import _move_rotate, placement_matrix
        for rot in ((0, 0, 0), (10, 20, 30), (-80, 45, 170), (90, 0, -90), (0, 90, 0)):
            p = Part("a", "A", 0, move=(1, 2, 3), rotate=rot)
            M = placement_matrix(p)
            q = Part("a", "A", 0, **_move_rotate(M[:3].tolist()))
            np.testing.assert_allclose(placement_matrix(q), M, atol=1e-9)


class Couplings(unittest.TestCase):
    def two(self, j1, j2, c):
        return Assembly(parts=[Part("base", "Base", 0), Part("a", "A", 1), Part("b", "B", 2)], joints=[j1, j2], couplings=[c])

    def test_gear_rack_screw_cam(self):
        a = hinge("a", (0, 0, 1), (0, 0, 0), (0, 720), id="a", parent="base")
        b = hinge("b", (0, 0, 1), (30, 0, 0), (-720, 720), id="b", parent="base")
        r = motion.study(self.two(a, b, gears("a", "b", 12, 36)), frames=9)
        va, vb = (next(j for j in r["joints"] if j["joint"] == k)["value"] for k in ("a", "b"))
        for x, y in zip(va, vb):
            self.assertAlmostEqual(y, -x * 12 / 36, places=9)
        s = slide("b", (1, 0, 0), (-500, 500), id="b", parent="base")
        r = motion.study(self.two(a, s, rack("a", "b", 20.0)), frames=5)
        vb = next(j for j in r["joints"] if j["joint"] == "b")["value"]
        self.assertAlmostEqual(vb[-1], math.pi * 20.0 * 2, places=6)      # two turns of a 20 mm pinion
        r = motion.study(self.two(a, s, lead_screw("a", "b", 2.0)), frames=5)
        self.assertAlmostEqual(next(j for j in r["joints"] if j["joint"] == "b")["value"][-1], 4.0, places=9)
        c = cam("a", "b", [(0, 0), (90, 5), (180, 5), (270, 0)])
        self.assertAlmostEqual(c.value(45), 2.5)
        self.assertAlmostEqual(c.value(315 + 360), 0.0)
        self.assertAlmostEqual(c.value(135), 5.0)

    def test_driving_a_follower_is_refused(self):
        a = hinge("a", (0, 0, 1), (0, 0, 0), (0, 360), id="a", parent="base")
        b = hinge("b", (0, 0, 1), (30, 0, 0), (-360, 360), id="b", parent="base")
        with self.assertRaises(motion.MotionError):
            motion.study(self.two(a, b, gears("a", "b", 10, 20)), drivers=[{"joint": "b"}])

    def test_coupling_validation(self):
        a = hinge("a", (0, 0, 1), (0, 0, 0), (0, 360), id="a", parent="base")
        b = hinge("b", (0, 0, 1), (30, 0, 0), (-360, 360), id="b", parent="base")
        spec = self.two(a, b, Coupling("a", "b", 1.0))
        spec.couplings.append(Coupling("b", "a", 1.0))
        self.assertTrue(any("circle" in x for x in spec.validate(3)))
        spec = self.two(a, b, Coupling("a", "nope", 1.0))
        self.assertTrue(any("unknown joint" in x for x in spec.validate(3)))

    def test_cylindrical_and_ball_joints(self):
        j = cylindrical("a", (0, 0, 1), (10, 0, 0), (0, 360), (0, 20), id="c")
        M = joint_matrix(j, [90.0, 5.0])
        p = M @ np.array([20.0, 0, 0, 1])
        np.testing.assert_allclose(p[:3], [10.0, 10.0, 5.0], atol=1e-12)
        np.testing.assert_allclose(joint_matrix(j, 90.0) @ np.array([20.0, 0, 0, 1]), [10, 10, 0, 1], atol=1e-12)
        b = ball("a", (0, 0, 0), (-45, 45), id="b")
        np.testing.assert_allclose(joint_matrix(b, [0, 0, 90]) @ np.array([1.0, 0, 0, 1]), [0, 1, 0, 1], atol=1e-12)
        spec = Assembly(parts=[Part("base", "Base", 0), Part("a", "A", 1)], joints=[j])
        r = motion.study(spec, [{"joint": "c", "dof": 1, "from": 0, "to": 20}], frames=5)
        self.assertEqual(r["frames"][-1]["pose"]["c"], [0.0, 20.0])


# ── on real designs ────────────────────────────────────────────────────────────────────────────────────────────

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

ARM = '''from build123d import Align, Box, Pos
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage, hinge

MIN = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Hinged arm"
    summary = "A base and an arm on a hinge about -Y."
    params = [Param("s", "Scale", 1, 0.5, 2, 0.1, "", "form", "body")]
    features = [Feature("body", "Body", "structure")]
    solids = 2

    def build(self, v):
        return [Stage("body", Pos(-30, -10, -10) * Box(20, 20, 10, align=MIN) + Pos(0, -5, 0) * Box(40, 10, 4, align=MIN))]

    def assembly(self, v):
        return Assembly(parts=[Part("base", "Base", 0), Part("arm", "Arm", 1)],
                        joints=[hinge("arm", (0, -1, 0), (0, 0, 0), (0, 120), id="arm_hinge", parent="base")])
'''

BOX = '''from build123d import Align, Box, Cylinder, Pos
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, Stage

UP = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Box with lid and screws"
    summary = "A box, a lid with a lip, two screws, laid out apart and placed by the assembly."
    params = [Param("s", "Scale", 1, 0.5, 2, 0.1, "", "form", "box")]
    features = [Feature("box", "Box", "structure")]
    solids = 4

    def build(self, v):
        box = Box(40, 40, 20, align=UP) - Pos(0, 0, 3) * Box(34, 34, 20, align=UP)
        box += Pos(10, 10, 0) * Cylinder(3.5, 20, align=UP) + Pos(-10, -10, 0) * Cylinder(3.5, 20, align=UP)
        box -= Pos(10, 10, 8) * Cylinder(1.7, 13, align=UP) + Pos(-10, -10, 8) * Cylinder(1.7, 13, align=UP)
        lid = Pos(0, 0, 20) * Box(40, 40, 3, align=UP) + Pos(0, 0, 17) * (Box(33.6, 33.6, 3, align=UP) - Box(30, 30, 3, align=UP))
        lid -= Pos(10, 10, 15) * Cylinder(1.7, 10, align=UP) + Pos(-10, -10, 15) * Cylinder(1.7, 10, align=UP)
        s1 = Pos(10, 10, 23) * Cylinder(3, 2, align=UP) + Pos(10, 10, 10) * Cylinder(1.5, 13, align=UP)
        s2 = Pos(-10, -10, 23) * Cylinder(3, 2, align=UP) + Pos(-10, -10, 10) * Cylinder(1.5, 13, align=UP)
        return [Stage("box", box + Pos(60, 0, 0) * lid + Pos(120, 0, 0) * s1 + Pos(150, 0, 0) * s2)]

    def assembly(self, v):
        return Assembly(parts=[Part("box", "Box", 0), Part("lid", "Lid", 1, move=(-60, 0, 0)),
                               Part("screw1", "Screw 1", 2, move=(-120, 0, 0)), Part("screw2", "Screw 2", 3, move=(-150, 0, 0))],
                        mates=[Mate("screw1", "box", "thread", 0.2, axis=(0, 0, 1), origin=(10, 10, 0)),
                               Mate("screw2", "box", "thread", 0.2, axis=(0, 0, 1), origin=(-10, -10, 0))])
'''

# a closed hollow box with a cube inside its cavity: no part can leave on a straight line
TRAPPED = '''from build123d import Align, Box, Pos
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage

UP = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Trapped cube"
    summary = "A closed shell with a cube inside it."
    params = [Param("s", "Scale", 1, 0.5, 2, 0.1, "", "form", "box")]
    features = [Feature("box", "Box", "structure")]
    solids = 2

    def build(self, v):
        shell = Box(30, 30, 30, align=UP) - Pos(0, 0, 3) * Box(24, 24, 24, align=UP)
        return [Stage("box", shell + Pos(60, 0, 8) * Box(10, 10, 10, align=UP))]

    def assembly(self, v):
        return Assembly(parts=[Part("shell", "Shell", 0), Part("cube", "Cube", 1, move=(-60, 0, 0))])
'''


class OnDesigns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def design(self, name, src, material="AL-6061"):
        p = self.st.create_design(name, src, purpose="model")
        if material:
            materials.set_appearance(self.st, p["id"], "", "keep", material)
        return self.st.load(p["id"])

    def test_fourbar_clearance_along_the_cycle(self):
        p = self.design("Four-bar", FOURBAR)
        r = motion.run(self.st, p, drivers=[{"joint": "crank", "from": 0, "to": 360}], frames=37)
        self.assertEqual(r["closed_frames"], 37)
        c = r["clearance"]
        self.assertIn(c["status"], ("PASS", "WARN"))
        self.assertFalse(c["overlap_frames"])
        # the links sit in layers 1 mm apart: the smallest gap is that layer gap, within the mesh tolerance
        self.assertAlmostEqual(c["min"]["clearance_mm"], 1.0, delta=c["tolerance_mm"])
        self.assertIn("Coupler / Rocker", c["joined"])                  # pinned by the Loop: not compared
        self.assertEqual(len(c["proven"]) + len(c["sampled"]), 36)
        # in plane with gravity along -Z: nothing to hold
        self.assertLess(r["torque"]["joints"][0]["max_abs"], 1e-9)
        again = motion.run(self.st, p, drivers=[{"joint": "crank", "from": 0, "to": 360}], frames=37)
        self.assertEqual(again["key"], r["key"])

    def test_holding_torque_of_a_hinged_arm(self):
        p = self.design("Arm", ARM)
        r = motion.run(self.st, p, frames=13, clearance_check=False)
        m = massprops.compute(self.st, p)
        arm = next(x for x in m["parts"] if x["id"] == "arm")
        kg, (x, _, z) = arm["mass_g"] / 1000.0, arm["com_mm"]
        tq = r["torque"]["joints"][0]
        self.assertEqual(tq["unit"], "N·m")
        for f, v in zip(r["frames"], tq["values"]):
            t = math.radians(f["pose"]["arm_hinge"])
            ref = kg * motion.G * (x * math.cos(t) - z * math.sin(t)) / 1000.0
            self.assertAlmostEqual(v, ref, delta=abs(ref) * 1e-4 + 1e-9)
        q = self.design("Arm no material", ARM, material=None)
        r = motion.run(self.st, q, frames=5, clearance_check=False)
        self.assertEqual(r["torque"]["joints"], [])
        self.assertEqual(r["torque"]["missing_material"], ["base", "arm"])

    def test_no_joint_no_motion(self):
        p = self.design("Trapped", TRAPPED)
        with self.assertRaises(StudioError):
            motion.run(self.st, p)

    def test_urdf_inertia_equals_wave_c(self):
        p = self.design("Four-bar robot", FOURBAR)
        r = robot.write(self.st, p, collision="hull", samples=16)
        bad = [c for c in r["checks"] if c["status"] == "FAIL"]
        self.assertFalse(bad, bad)
        m = massprops.compute(self.st, p, frame="assembled")
        root = ET.parse(r["paths"]["urdf"]).getroot()
        links = {ln.get("name"): ln for ln in root.findall("link")}
        org = {x["part"]: np.asarray(x["origin_mm"]) for x in r["links"]}
        for part in m["parts"]:
            el = links[part["id"]].find("inertial")
            self.assertAlmostEqual(float(el.find("mass").get("value")), part["mass_g"] / 1000.0, places=9)
            xyz = np.array([float(v) for v in el.find("origin").get("xyz").split()])
            np.testing.assert_allclose(xyz, (np.asarray(part["com_mm"]) - org[part["id"]]) / 1000.0, atol=1e-11)
            i = el.find("inertia").attrib
            I = np.array([[float(i["ixx"]), float(i["ixy"]), float(i["ixz"])],
                          [float(i["ixy"]), float(i["iyy"]), float(i["iyz"])],
                          [float(i["ixz"]), float(i["iyz"]), float(i["izz"])]])
            want = np.asarray(part["inertia_kg_m2"])
            np.testing.assert_allclose(I, want, rtol=1e-8, atol=1e-8 * float(np.abs(want).max()))
        joints = {j.get("name"): j for j in root.findall("joint")}
        self.assertEqual(joints["crank"].get("type"), "continuous")    # a full turn
        self.assertEqual(joints["rocker"].get("type"), "continuous")
        # the Loop is not in the URDF (a tree) and is said so; it is in the MJCF as a connect
        self.assertTrue(any("not in the URDF" in n for n in r["notes"]))
        mj = ET.parse(r["paths"]["mjcf"]).getroot()
        self.assertEqual(len(mj.findall("./equality/connect")), 1)
        srdf = ET.parse(r["paths"]["srdf"]).getroot()
        reasons = {(d.get("link1"), d.get("link2")): d.get("reason") for d in srdf.findall("disable_collisions")}
        self.assertEqual(reasons[("coupler", "rocker")], "Default")
        self.assertEqual(reasons[("crank", "ground")], "Adjacent")
        v = r["validation"]
        for k in ("urdf", "mjcf"):
            self.assertTrue(v[k]["ok"], v[k])
            self.assertIn("parser", v[k])

    def test_mjcf_loads_in_mujoco(self):
        from form import engines
        here = True
        try:
            import mujoco  # noqa: F401
        except ImportError:
            here = False
        if not here and engines.python(robot.ENGINE, self.st.cfg) is None:
            self.skipTest("MuJoCo is not installed here or as the robot.mujoco engine")
        p = self.design("Four-bar mujoco", FOURBAR)
        r = robot.write(self.st, p, collision="hull", samples=8)
        v = r["validation"]["mjcf"]
        self.assertTrue(v["parser"].startswith("MuJoCo"), v)
        self.assertTrue(v["ok"], v)
        self.assertTrue(v["finite_after"])
        self.assertEqual(v["joints"], 3)
        self.assertTrue(r["validation"]["urdf"]["parser"].startswith(("yourdfpy", "urdfpy")))

    def test_no_material_fails_the_mass_check(self):
        p = self.design("Four-bar bare", FOURBAR, material=None)
        r = robot.write(self.st, p, collision="box", samples=4)
        row = next(c for c in r["checks"] if c["id"] == "robot_mass")
        self.assertEqual(row["status"], "FAIL")
        r = robot.write(self.st, p, collision="box", samples=4, assume_material="PLA")
        self.assertEqual(next(c for c in r["checks"] if c["id"] == "robot_mass")["status"], "PASS")
        self.assertIn("assumed", r["links"][1]["inertial"]["why"])

    def test_sequence_box_lid_screws(self):
        p = self.design("Box", BOX)
        r = sequence.plan(self.st, p)
        self.assertTrue(r["complete"], r.get("stuck"))
        self.assertEqual(r["order"][:2], ["box", "lid"])
        self.assertEqual(set(r["order"][2:]), {"screw1", "screw2"})
        for s in r["steps"][1:]:
            np.testing.assert_allclose(s["insert"], [0, 0, -1], atol=1e-9)    # from above
        screw = next(s for s in r["steps"] if s["part"] == "screw1")
        self.assertEqual(screw["joined"], [{"with": "box", "kind": "thread"}])
        self.assertIn("Geometric feasibility only", r["limits"])
        # while the screws are in, the lid cannot go up: its top face touches the heads' undersides (normal +Z)
        from form import collide
        from form.recipes.assembly import Assembly as Asm, placement_matrix
        view = self.st.view(p)
        spec = Asm.from_public(view["assembly"])
        meshes = motion.part_meshes(view)
        B = {k: collide.Body(*meshes[k], 0.05) for k in ("lid", "screw1")}
        M = {x.id: placement_matrix(x) for x in spec.parts}
        N = sequence.contact_normals(B["lid"], B["screw1"], M["lid"], M["screw1"], 0.25)
        self.assertTrue(len(N) and float(np.max(N @ np.array([0, 0, 1.0]))) > 0.99)
        # the exploded view and the instructions follow it
        x = {q["id"]: q for q in view["assembly"]["parts"]}
        self.assertGreater(x["screw1"]["sequence_explode"][2], x["lid"]["sequence_explode"][2])
        self.assertEqual(view["assembly"]["sequence"]["order"], r["order"])
        ins = instructions.build(self.st, p)
        self.assertEqual([s["part"] for s in ins["steps"]], r["order"])
        self.assertTrue(ins["steps"][1]["from_sequence"])
        self.assertIn("from above", ins["steps"][1]["text"])

    def test_sequence_reports_what_cannot_come_apart(self):
        p = self.design("Trapped seq", TRAPPED)
        r = sequence.plan(self.st, p)
        self.assertFalse(r["complete"])
        self.assertEqual(set(r["stuck"]["parts"]), {"shell", "cube"})
        self.assertFalse(r["steps"])
        self.assertNotIn("sequence", self.st.view(p)["assembly"])


if __name__ == "__main__":
    unittest.main()
