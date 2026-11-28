"""Mass properties (form/massprops.py) against closed-form solids, and the sourced materials library.

Each solid is built by the kernel from a design's code; the reference is the textbook formula for that shape with the
material's density, in g and g·mm². Accepted error: 1e-6 relative (OCCT integrates analytic faces exactly; what is
left is floating point). Tests use their own FORM_DATA, never the owner's data."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="form-mass-")
os.environ["FORM_DATA"] = TMP

from form import config, massprops, material_library as ml, materials  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

REL = 1e-6

HEAD = '''from build123d import Align, Box, Cylinder, Pos, Rot, Sphere
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage, hinge

MIN = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Mass test"
    summary = "A solid with a closed-form inertia."
    params = [Param("s", "Scale", 1, 0.5, 2, 0.1, "", "form", "body")]
    features = [Feature("body", "Body", "structure")]
'''

BOX = HEAD + '''
    def build(self, v):
        return [Stage("body", Pos(5, 7, 11) * Box(10, 20, 30, align=MIN))]
'''
CYL = HEAD + '''
    def build(self, v):
        return [Stage("body", Pos(-3, 4, 0) * Cylinder(5, 40, align=MIN))]
'''
TUBE = HEAD + '''
    def build(self, v):
        return [Stage("body", Pos(0, 0, 10) * (Cylinder(10, 50) - Cylinder(7, 50)))]
'''
SHELL = HEAD + '''
    def build(self, v):
        return [Stage("body", Pos(1, 2, 3) * (Sphere(10) - Sphere(8)))]
'''
# two separate bodies, no assembly declared: one part each (form/assembly.py numbers them by X)
TWO = HEAD + '''
    solids = 2

    def build(self, v):
        return [Stage("body", Box(10, 10, 10, align=MIN) + Pos(30, 0, 0) * Box(20, 10, 5, align=MIN))]
'''
# a base and an arm on a hinge about -Y through the origin
ARM = HEAD.replace("solid with a closed-form inertia", "base and a hinged arm") + '''
    solids = 2

    def build(self, v):
        base = Pos(-30, -10, -10) * Box(20, 20, 10, align=MIN)
        arm = Pos(0, -5, 0) * Box(40, 10, 4, align=MIN)
        return [Stage("body", base + arm)]

    def assembly(self, v):
        return Assembly(parts=[Part("base", "Base", 0), Part("arm", "Arm", 1)],
                        joints=[hinge("arm", (0, -1, 0), (0, 0, 0), (0, 120), id="arm_hinge", parent="base")])
'''


def rot(axis, deg):
    u = np.asarray(axis, float) / np.linalg.norm(axis)
    t = math.radians(deg)
    K = np.array([[0, -u[2], u[1]], [u[2], 0, -u[0]], [-u[1], u[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)


def box_I(m, a, b, c):
    return np.diag([m * (b * b + c * c) / 12, m * (a * a + c * c) / 12, m * (a * a + b * b) / 12])


class MassProps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())
        cls.rho = ml.density("AL-6061")["value"] * 1e-6        # g/mm³

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def design(self, name, src, material="AL-6061"):
        p = self.st.create_design(name, src, purpose="model")
        if material:
            materials.set_appearance(self.st, p["id"], "", "keep", material)
        return self.st.load(p["id"])

    def close(self, got, want, rel=REL, msg=""):
        got, want = np.asarray(got, float), np.asarray(want, float)
        scale = max(float(np.max(np.abs(want))), 1e-12)
        self.assertLessEqual(float(np.max(np.abs(got - want))) / scale, rel, f"{msg}: {got} != {want}")

    def test_box_offset(self):
        r = massprops.compute(self.st, self.design("Box", BOX))
        m = 10 * 20 * 30 * self.rho
        t = r["total"]
        self.close(t["mass_g"], m, msg="mass")
        self.close(t["com_mm"], [10, 17, 26], msg="centre")
        self.close(t["inertia_g_mm2"], box_I(m, 10, 20, 30), msg="inertia about the centre")
        self.close(t["principal"]["moments_g_mm2"], sorted(np.diag(box_I(m, 10, 20, 30))), msg="principal")
        d = np.array([10, 17, 26.0])
        self.close(t["inertia_origin_g_mm2"], box_I(m, 10, 20, 30) + m * (d @ d * np.eye(3) - np.outer(d, d)),
                   msg="about the origin (parallel axis)")
        self.close(t["inertia_kg_m2"], box_I(m, 10, 20, 30) * 1e-9, msg="kg·m²")
        self.assertEqual(r["evidence"], "computed (B-rep)")
        self.assertEqual(r["parts"][0]["material"]["density_evidence"], "specified (datasheet)")
        self.assertIn("matweb", r["parts"][0]["material"]["density_url"])
        ax = np.abs(np.array(t["principal"]["axes"]))
        self.close(ax, np.eye(3)[[2, 1, 0]], rel=1e-9, msg="axes")       # smallest moment about the longest side, Z

    def test_cylinder(self):
        r = massprops.compute(self.st, self.design("Cylinder", CYL))
        R, h = 5.0, 40.0
        m = math.pi * R * R * h * self.rho
        t = r["total"]
        self.close(t["mass_g"], m)
        self.close(t["com_mm"], [-3 + R, 4 + R, h / 2])
        Ix = m * (3 * R * R + h * h) / 12
        self.close(t["inertia_g_mm2"], np.diag([Ix, Ix, m * R * R / 2]))
        self.assertEqual(t["principal"]["repeated"], [[1, 2]])           # two equal moments: axes not unique
        self.assertIn("not unique", t["principal"]["note"])

    def test_hollow_tube(self):
        r = massprops.compute(self.st, self.design("Tube", TUBE))
        Ro, Ri, h = 10.0, 7.0, 50.0
        m = math.pi * (Ro * Ro - Ri * Ri) * h * self.rho
        t = r["total"]
        self.close(t["mass_g"], m)
        self.close(t["com_mm"], [0, 0, 10])
        Ix = m * (3 * (Ro * Ro + Ri * Ri) + h * h) / 12
        self.close(t["inertia_g_mm2"], np.diag([Ix, Ix, m * (Ro * Ro + Ri * Ri) / 2]))

    def test_hollow_sphere(self):
        r = massprops.compute(self.st, self.design("Shell", SHELL))
        Ro, Ri = 10.0, 8.0
        m = 4 / 3 * math.pi * (Ro ** 3 - Ri ** 3) * self.rho
        t = r["total"]
        self.close(t["mass_g"], m)
        self.close(t["com_mm"], [1, 2, 3])
        Ic = 2 / 5 * m * (Ro ** 5 - Ri ** 5) / (Ro ** 3 - Ri ** 3)
        self.close(t["inertia_g_mm2"], np.eye(3) * Ic)

    def test_two_bodies_two_materials_and_parallel_axis(self):
        p = self.design("Two", TWO, material=None)
        ids = [x["id"] for x in massprops.compute(self.st, p)["parts"]]
        self.assertEqual(len(ids), 2)
        materials.set_appearance(self.st, p["id"], ids[0], "keep", "STEEL")
        materials.set_appearance(self.st, p["id"], ids[1], "keep", "POM")
        r = massprops.compute(self.st, self.st.load(p["id"]))
        r1, r2 = ml.density("STEEL")["value"] * 1e-6, ml.density("POM")["value"] * 1e-6
        m1, m2 = 1000 * r1, 1000 * r2
        c1, c2 = np.array([5, 5, 5.0]), np.array([40, 5, 2.5])
        M = m1 + m2
        C = (m1 * c1 + m2 * c2) / M
        par = lambda m, d: m * (d @ d * np.eye(3) - np.outer(d, d))      # noqa: E731
        I = box_I(m1, 10, 10, 10) + par(m1, c1 - C) + box_I(m2, 20, 10, 5) + par(m2, c2 - C)
        t = r["total"]
        self.close(t["mass_g"], M)
        self.close(t["com_mm"], C)
        self.close(t["inertia_g_mm2"], I)
        self.assertEqual({x["material"]["id"] for x in r["parts"]}, {"STEEL", "POM"})
        self.assertEqual(r["parts"][0]["material"]["why"], "chosen for this part")
        # one part only: the total is still the whole
        one = massprops.compute(self.st, self.st.load(p["id"]), part=ids[1])
        self.assertEqual([x["id"] for x in one["parts"]], [ids[1]])
        self.close(one["total"]["mass_g"], M)

    def test_assembly_in_two_poses(self):
        p = self.design("Arm", ARM)
        m_b, m_a = 20 * 20 * 10 * self.rho, 40 * 10 * 4 * self.rho
        cb, ca = np.array([-20, 0, -5.0]), np.array([20, 0, 2.0])
        for deg in (0, 90, 35):
            r = massprops.compute(self.st, p, pose={"arm_hinge": deg} if deg else None)
            self.assertEqual(r["frame"], "assembled")
            R = rot((0, -1, 0), deg)
            ca_w = R @ ca
            C = (m_b * cb + m_a * ca_w) / (m_b + m_a)
            self.close(r["total"]["com_mm"], C, msg=f"centre at {deg}°")
            arm = next(x for x in r["parts"] if x["id"] == "arm")
            self.close(arm["inertia_g_mm2"], R @ box_I(m_a, 40, 10, 4) @ R.T, rel=1e-9, msg=f"arm rotated {deg}°")
            self.close(arm["com_mm"], ca_w, msg=f"arm centre {deg}°")
        up = massprops.compute(self.st, p, pose={"arm_hinge": 90})["total"]["com_mm"]
        self.assertGreater(up[2], -5 * m_b / (m_b + m_a) + 2 * m_a / (m_b + m_a))          # the arm raised lifts the centre
        built = massprops.compute(self.st, p, frame="as_built")
        self.assertEqual(built["frame"], "as_built")
        with self.assertRaises(StudioError):
            massprops.compute(self.st, p, pose={"nope": 1})
        with self.assertRaises(StudioError):
            massprops.compute(self.st, p, pose={"arm_hinge": 500})
        with self.assertRaises(StudioError):
            massprops.compute(self.st, p, frame="as_built", pose={"arm_hinge": 10})

    def test_no_material_means_no_mass_and_what_if(self):
        p = self.design("Bare", BOX, material=None)
        r = massprops.compute(self.st, p)
        self.assertIsNone(r["total"])
        self.assertEqual(r["missing_material"], [""])
        self.close(r["volume_centroid_mm"], [10, 17, 26])
        self.assertIn("no mass is given", r["text"])
        w = massprops.compute(self.st, p, material="BRASS")
        self.close(w["total"]["mass_g"], 6000 * ml.density("BRASS")["value"] * 1e-6)
        self.assertEqual(w["parts"][0]["material"]["why"], "what if (not saved)")
        self.assertIsNone(self.st.load(p["id"]).get("material"))
        self.assertIn("kg/m³", massprops.headline(w))
        a = massprops.compute(self.st, p, assume="PLA")
        self.assertEqual(a["parts"][0]["material"]["why"], "assumed (no material chosen)")
        self.assertIn("100 % infill", a["parts"][0]["note"])
        with self.assertRaises(StudioError):
            massprops.compute(self.st, p, material="unobtainium")

    def test_geometry_is_stored_and_the_key_follows_material(self):
        p = self.design("Keyed", BOX)
        a = massprops.compute(self.st, p)
        files = list((self.st.dir(p["id"]) / "artifacts" / "mass").glob("geom-*.json"))
        self.assertEqual(len(files), 1)
        k1 = massprops.study_key(self.st, p)
        materials.set_appearance(self.st, p["id"], "", "keep", "TITANIUM")
        p = self.st.load(p["id"])
        b = massprops.compute(self.st, p)
        self.assertEqual(a["geometry_key"], b["geometry_key"])
        self.assertNotEqual(a["key"], b["key"])
        self.assertNotEqual(k1, massprops.study_key(self.st, p))
        self.assertEqual(massprops.BENCH["run"](self.st, p)["headline"], massprops.headline(b))


class MaterialLibrary(unittest.TestCase):
    def test_every_value_cites_its_source(self):
        lib = ml.library()
        self.assertEqual({x["id"] for x in lib}, set(materials.MATERIALS) | set(materials.engineering()))
        n = 0
        for rec in lib:
            for name, v in rec["properties"].items():
                n += 1
                for k in ("source", "url", "quote", "retrieved", "unit", "evidence"):
                    self.assertTrue(v.get(k) is not None, f"{rec['id']}.{name} has no {k}")
                self.assertTrue(v["url"].startswith("https://"), v["url"])
                self.assertTrue(v.get("value") is not None or v.get("min") is not None, f"{rec['id']}.{name}")
            d = rec["density"]
            self.assertGreater(d["value"], 0)
            self.assertTrue(d["source"])
        self.assertGreater(n, 200)

    def test_unsourced_is_said_never_filled(self):
        self.assertEqual(ml.prop("PTFE", "E")["status"], "unsourced")
        self.assertIn("poisson", ml.record("PLA")["unsourced"])
        self.assertEqual(ml.prop("PLA", "poisson")["status"], "unsourced")

    def test_printed_filaments_carry_both_directions_and_a_modelled_knockdown(self):
        for k in materials.MATERIALS:
            rec = ml.record(k)
            self.assertIn("E_xy", rec["properties"], k)
            self.assertIn("uts_z", rec["properties"], k)
            kd = rec["knockdown_z"]["uts"]
            self.assertEqual(kd["evidence"], "modelled")
            self.assertAlmostEqual(kd["ratio"], kd["z"] / kd["xy"], places=3)
            self.assertLessEqual(kd["ratio"], 1.0, k)
        self.assertEqual(ml.prop("PLA", "E")["name"], "E_xy")
        self.assertEqual(ml.prop("PLA", "E", direction="z")["name"], "E_z")

    def test_densities_agree_with_the_filament_table(self):
        for k, v in materials.MATERIALS.items():
            self.assertAlmostEqual(ml.density(k)["value"], v["density_g_cm3"] * 1000, places=6, msg=k)
        self.assertEqual(ml.density("AL-6061")["value"], 2700.0)
        self.assertEqual(ml.density("OAK")["evidence"], ml.EVIDENCE_TYPICAL)      # wood: the catalogue's density


if __name__ == "__main__":
    unittest.main()
