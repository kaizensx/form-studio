"""Tolerance stack-up (form/stack): the arithmetic against hand calculation, Monte Carlo against the analytic normal,
temperature against hand calculation, an angle by finite differences on the rebuilt CAD, and the loop found by itself
in a box, lid and screw. Tests use their own FORM_DATA, never the owner's data."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
TMP = tempfile.mkdtemp(prefix="form-stack-")
os.environ["FORM_DATA"] = TMP

from form import config, materials, stack  # noqa: E402
from form import material_library as ml  # noqa: E402
from form.stack import analysis as AN  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402
from stack_designs import BOX_LID_SCREW, PIN, RAMP  # noqa: E402

# the screw's tip, as built (the screw stands on its tip at x = 100), and the floor of the pilot hole (z = 20 - 12)
TIP, FLOOR = {"at": [100, 0, 0], "part": "screw"}, {"at": [0, 0, 8]}
HAND = {"screw_l": 0.2, "lid_t": 0.1, "hole_depth": 0.15}


class Arithmetic(unittest.TestCase):
    """A 1D linear stack, by hand."""

    CS = [  # a 30 mm housing bore depth, two 10 mm spacers stacked in it, a g6-like asymmetric shaft shoulder
        {"id": "bore", "sensitivity": 1.0, "lower": -0.1, "upper": 0.1},
        {"id": "sp1", "sensitivity": -1.0, "lower": -0.05, "upper": 0.05},
        {"id": "sp2", "sensitivity": -1.0, "lower": -0.05, "upper": 0.05},
        {"id": "shoulder", "sensitivity": -1.0, "lower": -0.020, "upper": -0.007},
        {"id": "washer", "sensitivity": -1.0, "lower": -0.06, "upper": 0.06, "dist": "uniform"},
    ]

    def test_worst_case_by_hand(self):
        wc = AN.worst_case(0.5, self.CS)
        mean = 0.5 - (-0.0135)                    # only the shoulder is off centre: its middle is -13.5 µm
        half = 0.1 + 0.05 + 0.05 + 0.0065 + 0.06
        self.assertAlmostEqual(wc["mean"], mean, places=12)
        self.assertAlmostEqual(wc["min"], mean - half, places=12)
        self.assertAlmostEqual(wc["max"], mean + half, places=12)

    def test_rss_by_hand(self):
        rs = AN.rss(0.5, self.CS)
        var = (0.1 / 3) ** 2 + 2 * (0.05 / 3) ** 2 + (0.0065 / 3) ** 2 + (0.06 / math.sqrt(3)) ** 2
        self.assertAlmostEqual(rs["sigma"], math.sqrt(var), places=12)
        self.assertAlmostEqual(rs["max"] - rs["mean"], 3 * math.sqrt(var), places=12)
        shares = {r["id"]: r["variance_share"] for r in AN.contributions(self.CS)}
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=12)
        self.assertAlmostEqual(shares["bore"], (0.1 / 3) ** 2 / var, places=12)
        # the classic RSS of equal-reliability normals: sqrt(sum t^2) when every contributor is ±3 sigma
        normals = [c for c in self.CS if c.get("dist") != "uniform"]
        t = math.sqrt(sum(((c["upper"] - c["lower"]) / 2) ** 2 for c in normals))
        self.assertAlmostEqual(AN.rss(0, normals)["max"] - AN.rss(0, normals)["mean"], t, places=12)

    def test_capability_by_hand(self):
        c = AN.capability(1.0, 0.1, 0.7, 1.6)
        self.assertAlmostEqual(c["cpk"], 1.0, places=12)
        self.assertAlmostEqual(c["out_of_spec"], 1 - AN.phi(3.0) + 1 - AN.phi(6.0), places=12)
        self.assertIsNone(AN.capability(1.0, 0.1, None, None)["cpk"])

    def test_thermal_shift_by_hand(self):
        r = AN.thermal_shift([{"part": "a", "length": 40.0, "alpha": 23.6e-6}, {"part": "b", "length": -39.5, "alpha": 11.5e-6}], 80)
        self.assertAlmostEqual(r["shift"], 60 * (40 * 23.6e-6 - 39.5 * 11.5e-6), places=15)
        self.assertIsNone(AN.thermal_shift([{"part": "a", "length": 1.0, "alpha": None}], 80)["shift"])


class MonteCarlo(unittest.TestCase):
    def test_converges_to_the_analytic_normal(self):
        cs = [{"id": f"c{i}", "sensitivity": s, "lower": -t, "upper": t + m}
              for i, (s, t, m) in enumerate([(1, 0.1, 0.0), (-1, 0.05, 0.01), (2.0, 0.02, 0.0), (-0.5, 0.2, -0.04)])]
        rs = AN.rss(1.0, cs)
        lsl, usl = rs["mean"] - 2.5 * rs["sigma"], rs["mean"] + 2.0 * rs["sigma"]
        mc = AN.monte_carlo(1.0, cs, samples=400_000, seed=7, lsl=lsl, usl=usl)
        n = mc["samples"]
        self.assertLess(abs(mc["mean"] - rs["mean"]), 4 * rs["sigma"] / math.sqrt(n))
        self.assertLess(abs(mc["sigma"] / rs["sigma"] - 1), 4 / math.sqrt(2 * n))
        p = AN.capability(rs["mean"], rs["sigma"], lsl, usl)["out_of_spec"]
        self.assertLess(abs(mc["out_of_spec"] - p), 4 * mc["out_of_spec_se"])
        self.assertAlmostEqual(mc["q99865"], rs["mean"] + 3 * rs["sigma"], delta=0.03 * rs["sigma"] * 3)
        again = AN.monte_carlo(1.0, cs, samples=400_000, seed=7, lsl=lsl, usl=usl)
        self.assertEqual(again["mean"], mc["mean"])                       # seeded: it repeats exactly
        self.assertNotEqual(AN.monte_carlo(1.0, cs, samples=400_000, seed=8)["mean"], mc["mean"])


class Sources(unittest.TestCase):
    def test_precedence_and_labels(self):
        ctx = {"tolerances": {}, "drawing": {}, "provenance": {}, "purpose": "print", "calibration": {"source": "assumed"}}
        t = stack.tolerance_of("w", "p", 12.0, "mm", None, ctx)
        self.assertEqual((t["lower"], t["upper"], t["dist"], t["evidence"]), (-0.2, 0.2, "uniform", "assumed"))
        self.assertIn("FDM", t["rule"])
        ctx["calibration"] = {"source": "calibrated", "sigma": 0.04, "n": 6, "profile": "X"}
        t = stack.tolerance_of("w", "p", 12.0, "mm", None, ctx)
        self.assertAlmostEqual(t["upper"], 0.12)
        self.assertEqual((t["evidence"], t["dist"]), ("calibrated", "normal"))
        ctx["provenance"] = {"w": {"source": "measured", "sigma": 0.03, "instrument": "calipers"}}
        t = stack.tolerance_of("w", "p", 12.0, "mm", None, ctx)
        self.assertEqual((t["evidence"], t["upper"]), ("measured", 0.09))
        ctx["drawing"] = {"fits": [{"class": "g6", "at": {"param": "w"}}]}
        t = stack.tolerance_of("w", "p", 12.0, "mm", None, ctx)
        self.assertAlmostEqual(t["upper"], -0.006)                       # g6 at 12 mm: -6 / -17 µm (ISO 286-2)
        self.assertAlmostEqual(t["lower"], -0.017)
        ctx["tolerances"] = {"p:w": [-0.01, 0.03]}
        t = stack.tolerance_of("w", "p", 12.0, "mm", None, ctx)
        self.assertEqual((t["lower"], t["upper"], t["source"]), (-0.01, 0.03, "given in the request"))
        model = {"tolerances": {}, "drawing": {}, "provenance": {}, "purpose": "model"}
        t = stack.tolerance_of("w", "p", 12.0, "mm", None, model)
        self.assertEqual((t["upper"], t["evidence"], t["dist"]), (0.2, "assumed", "uniform"))   # ISO 2768-m, 6-30 mm
        model["drawing"] = {"general": "f"}
        t = stack.tolerance_of("w", "p", 12.0, "mm", None, model)
        self.assertEqual((t["upper"], t["evidence"], t["dist"]), (0.1, "specified", "normal"))


class Assembled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())
        p = cls.st.create_design("Box lid screw", BOX_LID_SCREW, purpose="model")
        cls.bls = cls.st.load(p["id"])
        p = cls.st.create_design("Ramp", RAMP, purpose="model")
        cls.ramp = cls.st.load(p["id"])

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_loop_found_in_box_lid_screw(self):
        r = stack.compute(self.st, self.bls, a=TIP, b=FLOOR, tolerances=HAND, samples=20000)
        self.assertEqual(r["loop"]["chain"], ["screw", "lid", "box"])
        self.assertAlmostEqual(r["gap"]["nominal"], 3 + 12 - 12, places=9)
        self.assertLess(abs(r["gap"]["closure"]), 1e-9)
        self.assertEqual([round(x["length"], 9) for x in r["loop"]["links"]], [-12, 3, 12])
        self.assertEqual([x["kind"] for x in r["loop"]["interfaces"]], ["seat", "seat"])
        thread = next(m for m in r["loop"]["mates"] if m["kind"] == "thread")
        self.assertFalse(thread["edge"])                       # a thread along the gap holds nothing along it
        sens = {c["id"]: c["sensitivity"] for c in r["contributors"]}
        self.assertEqual(set(sens), {"screw:screw_l", "lid:lid_t", "box:hole_depth"})
        for k, want in (("screw:screw_l", -1), ("lid:lid_t", 1), ("box:hole_depth", 1)):
            self.assertAlmostEqual(sens[k], want, places=6)
        self.assertIn("box_h", r["not_moving"])                # the box's height places the lid, but sets no link
        wc = r["worst_case"]
        self.assertAlmostEqual(wc["min"], 3 - 0.45, places=6)
        self.assertAlmostEqual(r["rss"]["sigma"], math.sqrt(sum((t / 3) ** 2 for t in HAND.values())), places=6)
        self.assertEqual(r["suggestions"][0]["id"], "screw:screw_l")
        self.assertAlmostEqual(sum(x["percent"] for x in r["chart"]), 100, places=1)
        roles = {f["role"] for f in r["draw"]["faces"]}
        self.assertEqual(roles, {"gap_a", "gap_b", "interface"})
        self.assertTrue(all(f["model_face"] >= 0 for f in r["draw"]["faces"]))
        self.assertEqual([s["kind"] for s in r["draw"]["segments"]][-1], "gap")

    def test_drawing_tolerances_and_gdt(self):
        from form import drawing
        drawing.set_spec(self.st, self.bls["id"], {"general": "f", "fits": [{"class": "js11", "at": {"param": "screw_l"}}],
                                                   "gdt": [{"type": "profile_surface", "value": 0.2,
                                                            "at": {"feature": "hole", "normal": [0, 0, 1]}}]}, replace=True)
        try:
            r = stack.compute(self.st, self.st.load(self.bls["id"]), a=TIP, b=FLOOR, samples=20000)
        finally:
            drawing.set_spec(self.st, self.bls["id"], {}, replace=True)
        by = {c["id"]: c for c in r["contributors"]}
        self.assertAlmostEqual(by["screw:screw_l"]["upper"], 0.055)                # IT11 at 10-18 mm = 110 µm
        self.assertIn("ISO 286", by["screw:screw_l"]["source"])
        self.assertEqual((by["lid:lid_t"]["upper"], by["lid:lid_t"]["evidence"]), (0.05, "specified"))   # 2768-f, 0.5-3
        self.assertEqual(by["box:hole_depth"]["upper"], 0.1)                        # 2768-f, 6-30
        g = next(c for c in r["contributors"] if c["kind"] == "gdt")
        self.assertEqual((g["lower"], g["upper"], g["sensitivity"]), (-0.1, 0.1, 1.0))

    def test_thermal_against_hand(self):
        pid = self.bls["id"]
        for part, mat in (("box", "AL-6061"), ("lid", "AL-6061"), ("screw", "STAINLESS")):
            materials.set_appearance(self.st, pid, part, "keep", mat)
        try:
            p = self.st.load(pid)
            r = stack.compute(self.st, p, a=TIP, b=FLOOR, tolerances=HAND, t_min=-20, t_max=80, samples=20000)
            a_al, a_ss = ml.prop("AL-6061", "cte")["value"], ml.prop("STAINLESS", "cte")["value"]
            per_k = 12 * a_al + 3 * a_al - 12 * a_ss                  # box link + lid link - screw link
            th = r["thermal"]
            self.assertAlmostEqual(th["per_kelvin"], per_k, places=12)
            hot = next(x for x in th["at"] if x["t"] == 80)
            self.assertAlmostEqual(hot["shift"], 60 * per_k, places=12)
            self.assertAlmostEqual(hot["nominal"], 3 + 60 * per_k, places=9)
            cold = next(x for x in th["at"] if x["t"] == -20)
            self.assertAlmostEqual(cold["shift"], -40 * per_k, places=12)
            self.assertEqual(th["alpha"]["screw"]["evidence"], "specified")
            # a part with no sourced expansion leaves the result out and says what to give
            materials.set_appearance(self.st, pid, "lid", "keep", "PLA")
            r = stack.compute(self.st, self.st.load(pid), a=TIP, b=FLOOR, tolerances=HAND, t_min=-20, t_max=80, samples=20000)
            self.assertNotIn("at", r["thermal"])
            self.assertTrue(any("alpha" in w for w in r["thermal"]["not_computed"]))
            r = stack.compute(self.st, self.st.load(pid), a=TIP, b=FLOOR, tolerances=HAND, t_min=20, t_max=80,
                              alpha={"lid": 1e-4}, samples=20000)
            self.assertAlmostEqual(next(x for x in r["thermal"]["at"] if x["t"] == 80)["shift"],
                                   60 * (12 * a_al + 3 * 1e-4 - 12 * a_ss), places=12)
        finally:
            for part in ("box", "lid", "screw"):
                materials.set_appearance(self.st, pid, part, "keep", None)

    def test_angle_by_finite_differences(self):
        # A: the ramp's sloped top, as built (x = 15 on the slope); B: the cover's underside, as built
        z = 5 + 15 * math.tan(math.radians(10))
        r = stack.compute(self.st, self.ramp, a={"at": [15, 70, z]}, b={"at": [10, 135, 0], "part": "cover"},
                          direction=[0, 0, 1], tolerances={"theta": 0.5, "ramp_h": 0.1, "post_h": 0.1, "ramp_w": 0.2},
                          samples=20000)
        W, th = 30.0, math.radians(10)
        self.assertEqual(r["loop"]["chain"], ["ramp", "base", "cover"])
        self.assertAlmostEqual(r["gap"]["nominal"], 20 - 5 - W * math.tan(th), places=9)
        by = {c["id"]: c["sensitivity"] for c in r["contributors"]}
        self.assertAlmostEqual(by["ramp:theta"], -W / math.cos(th) ** 2 * math.pi / 180, places=6)     # mm per degree
        self.assertAlmostEqual(by["ramp:ramp_w"], -math.tan(th), places=6)
        self.assertAlmostEqual(by["ramp:ramp_h"], -1, places=6)
        self.assertAlmostEqual(by["base:post_h"], 1, places=6)
        self.assertNotIn("base:plate_t", by)                   # the plate seats both: it cancels in the loop

    def test_radial_fit_floats_across_the_gap(self):
        pid = self.st.create_design("Pin", PIN, purpose="model")["id"]
        r = stack.compute(self.st, self.st.load(pid), a={"at": [25, 60, 9.5], "part": "pin"}, b={"at": [50, 15, 8]},
                          tolerances={"hole_x": 0.05, "wall_x": 0.05, "cap_w": 0.1}, samples=20000)
        self.assertEqual(r["loop"]["chain"], ["pin", "plate"])
        self.assertEqual(r["gap"]["direction"], [1.0, 0.0, 0.0])
        self.assertAlmostEqual(r["gap"]["nominal"], 50 - 20 - 5, places=9)
        it = r["loop"]["interfaces"][0]
        self.assertEqual(it["kind"], "fit")
        self.assertAlmostEqual(it["float"], 0.1, places=9)
        by = {c["id"]: c for c in r["contributors"]}
        f = by["float:pin/plate"]
        self.assertEqual((f["dist"], f["evidence"]), ("uniform", "computed"))
        self.assertAlmostEqual(f["upper"], 0.1, places=9)
        self.assertAlmostEqual(by["plate:hole_x"]["sensitivity"], -1, places=6)
        self.assertAlmostEqual(by["plate:wall_x"]["sensitivity"], 1, places=6)
        self.assertAlmostEqual(by["pin:cap_w"]["sensitivity"], -0.5, places=6)
        self.assertNotIn("plate:hole_d", by)                   # the bore's size moves the float, not the axis
        self.assertAlmostEqual(r["worst_case"]["min"], 25 - (0.05 + 0.05 + 0.05 + 0.1), places=6)

    def test_kept_stack_and_bench(self):
        from form import studies
        from form.stack import tools
        pid = self.st.create_design("Kept stack", BOX_LID_SCREW, purpose="model")["id"]
        self.assertEqual(studies.show(self.st, self.st.load(pid), "stack")["state"], "never")
        r = tools.call(self.st, pid, a=TIP, b=FLOOR, save=True, name="Tip to floor", tolerances=HAND, samples=20000)
        sid = r["saved"]
        e = studies.show(self.st, self.st.load(pid), "stack")
        self.assertEqual(e["state"], "current")
        self.assertIn("Tip to floor", e["headline"])
        self.assertEqual(tools.read(self.st, pid, sid)["state"], "current")
        p = self.st.load(pid)
        self.st.commit(p, {"lid_t": 3.2}, expect_head=p["head"])
        self.assertEqual(studies.show(self.st, self.st.load(pid), "stack")["state"], "stale")
        r2 = tools.call(self.st, pid, stack=sid)
        self.assertAlmostEqual(r2["gap"]["nominal"], 3.2, places=9)
        self.assertEqual(studies.show(self.st, self.st.load(pid), "stack")["state"], "current")

    def test_errors_say_what_to_do(self):
        from form.stack import tools
        with self.assertRaises(StudioError) as e:
            tools.call(self.st, self.bls["id"], a=TIP)
        self.assertIn("two faces", str(e.exception))
        with self.assertRaises(StackErrorOrStudio):
            stack.compute(self.st, self.bls, a={"at": [500, 500, 500]}, b=FLOOR, samples=20000)


StackErrorOrStudio = (stack.StackError, StudioError)


if __name__ == "__main__":
    unittest.main()
