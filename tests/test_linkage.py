"""Four-bar synthesis (wave AF) against known answers.

Burmester, three positions: the dyad equation holds for every free choice; the synthesised linkage carries its coupler
through the three poses (closed form: 1e-9 mm; played by form/motion.py's Newton solver, which knows nothing of the
synthesis: 1e-4 mm and 1e-4 degrees), on one assembly mode, in order. Freudenstein: three angle pairs taken from a known
linkage give that linkage's lengths back (1e-6 mm). Path generation: targets sampled from a known coupler curve are
met within 1.5 % of the path's size, and the reported error is the error of the simulated path. Grashof, transmission
angle and the defect checks against cases built to have them. One linkage is built as a design and played on its real
parts. Tests use their own FORM_DATA, never the owner's data."""
import cmath
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="form-linkage-")
os.environ["FORM_DATA"] = TMP

from form import linkage as L, motion  # noqa: E402

POSES = [{"at": [0, 0], "angle": 0}, {"at": [30, 20], "angle": 20}, {"at": [60, 15], "angle": 45}]
KNOWN = {"O2": [0, 0], "O4": [55, 0], "a": 20.0, "b": 60.0, "c": 50.0, "d": 55.0, "branch": 1,
         "coupler_point": [30.0, 25.0], "theta1": 0.0}


class Burmester(unittest.TestCase):
    def test_dyad_equation(self):
        d2, d3 = complex(30, 20), complex(60, 15)
        a2, a3 = math.radians(20), math.radians(45)
        rng = np.random.default_rng(3)
        b2, b3 = rng.uniform(0.2, 6.0, 50), rng.uniform(0.2, 6.0, 50)
        W, Z, det = L.dyad(d2, d3, a2, a3, b2, b3)
        ok = np.abs(det) > 1e-6
        for j, (dl, al, be) in enumerate(((d2, a2, b2), (d3, a3, b3))):
            res = W * (np.exp(1j * be) - 1) + Z * (cmath.exp(1j * al) - 1) - dl
            self.assertLess(float(np.abs(res[ok]).max()), 1e-9, f"dyad equation, position {j + 2}")

    def test_coupler_passes_through_the_three_poses(self):
        r = L.synthesise("motion", poses=POSES, alternatives=4)
        cands = [r["link"]] + [a["link"] for a in r["alternatives"]]
        self.assertGreaterEqual(len(cands), 2)
        for link in cands:
            th = np.array([link["theta1"]] + [link["theta1"] + d for d in link["deltas"]])
            pos = L.positions(link, th)
            self.assertTrue(pos["ok"].all())
            for k, pose in enumerate(POSES):
                self.assertLess(abs(pos["P"][k] - complex(*pose["at"])), 1e-9, f"position {k + 1}")
                turned = math.degrees(pos["theta3"][k] - pos["theta3"][0])
                want = pose["angle"] - POSES[0]["angle"]
                self.assertLess(abs((turned - want + 180) % 360 - 180), 1e-9, f"angle {k + 1}")

    def test_simulation_knows_nothing_of_the_synthesis(self):
        r = L.synthesise("motion", poses=POSES)
        v = r["verification"]
        self.assertEqual(v["status"], "PASS")
        self.assertLess(v["max_point_error_mm"], 1e-4)
        self.assertLess(v["max_angle_error_deg"], 1e-4)
        self.assertEqual(v["evidence"], L.EVIDENCE_SIM)
        self.assertEqual(r["evidence"], L.EVIDENCE_EXACT)
        self.assertEqual(r["checks"]["defects"]["branch"]["status"], "PASS")
        self.assertEqual(r["checks"]["defects"]["order"]["status"], "PASS")

    def test_require_crank(self):
        r = L.synthesise("motion", poses=POSES, require_crank=True)
        self.assertTrue(r["checks"]["crank_turns_fully"])
        self.assertTrue(r["checks"]["grashof"]["grashof"])
        self.assertIn(r["checks"]["grashof"]["class"], ("crank-rocker", "double crank"))
        self.assertEqual(r["verification"]["status"], "PASS")

    def test_bad_input(self):
        with self.assertRaises(L.LinkageError):
            L.synthesise("motion", poses=POSES[:2])
        with self.assertRaises(L.LinkageError):
            L.synthesise("motion", poses=[{"at": [1, 1], "angle": 0}] * 3)
        with self.assertRaises(L.LinkageError):
            L.synthesise("orbit")


class Freudenstein(unittest.TestCase):
    def test_recovers_a_known_linkage(self):
        a, b, c, d = 20.0, 60.0, 50.0, 55.0
        pairs = [[t, motion.fourbar_rocker(a, b, c, d, t)] for t in (40.0, 75.0, 120.0)]
        r = L.freudenstein(pairs, ground=d)
        self.assertAlmostEqual(r["link"]["a"], a, places=6)
        self.assertAlmostEqual(r["link"]["b"], b, places=6)
        self.assertAlmostEqual(r["link"]["c"], c, places=6)
        self.assertLess(r["residual_mm"], 1e-9)
        K1, K2, K3 = r["K"]
        self.assertAlmostEqual(K1, d / a, places=8)
        self.assertAlmostEqual(K2, d / c, places=8)
        self.assertAlmostEqual(K3, (a * a - b * b + c * c + d * d) / (2 * a * c), places=8)

    def test_played_through_its_three_pairs(self):
        r = L.synthesise("function", pairs=[[40, 70], [60, 85], [85, 110]], ground=100)
        self.assertEqual(r["verification"]["status"], "PASS")
        self.assertLess(r["verification"]["max_angle_error_deg"], 1e-4)
        for row, want in zip(r["verification"]["positions"], (70, 85, 110)):
            self.assertAlmostEqual(row["output_deg"], want, places=4)

    def test_pairs_on_two_assembly_modes_are_a_branch_defect(self):
        a, b, c, d = 20.0, 60.0, 50.0, 55.0
        pairs = [[40.0, motion.fourbar_rocker(a, b, c, d, 40.0, True)], [75.0, motion.fourbar_rocker(a, b, c, d, 75.0, False)],
                 [120.0, motion.fourbar_rocker(a, b, c, d, 120.0, True)]]
        r = L.freudenstein(pairs, ground=d)
        # one linkage through three points always exists; these three were not taken from one assembly mode of one
        # linkage, so whatever comes out either has a defect or is a different linkage that reaches them honestly
        v = L.synthesise("function", pairs=pairs, ground=d)["verification"]
        if r["analysis"]["defects"]["branch"]["status"] == "PASS" and r["analysis"]["defects"]["order"]["status"] == "PASS":
            self.assertEqual(v["status"], "PASS")
        else:
            self.assertNotEqual(v.get("status"), "PASS")


class Checks(unittest.TestCase):
    def test_grashof_and_transmission_of_a_known_linkage(self):
        an = L.analyse(KNOWN)
        self.assertEqual(an["grashof"]["class"], "crank-rocker")
        self.assertTrue(an["crank_turns_fully"])
        # transmission angle extremes of a crank-rocker: at the crank in line with the ground (Norton, eq. 4.33)
        a, b, c, d = 20.0, 60.0, 50.0, 55.0
        mu1 = math.degrees(math.acos((b * b + c * c - (d - a) ** 2) / (2 * b * c)))
        mu2 = math.degrees(math.acos((b * b + c * c - (d + a) ** 2) / (2 * b * c)))
        self.assertAlmostEqual(an["transmission"]["min_deg"], min(mu1, 180 - mu1, mu2, 180 - mu2), delta=0.02)
        self.assertEqual(an["transmission"]["status"], "PASS" if an["transmission"]["min_deg"] >= 40 else "WARN")

    def test_circuit_defect_is_found(self):
        # a non-Grashof linkage whose loop opens while the crank is within about 29 degrees of the ground line
        link = {**KNOWN, "O4": [30.0, 0.0], "a": 40.0, "b": 70.0, "c": 50.0, "d": 30.0}
        self.assertFalse(L.analyse(link)["grashof"]["grashof"])
        self.assertFalse(L.positions(link, np.array([0.0]))["ok"][0])
        th1 = math.radians(60.0)
        self.assertTrue(L.positions(link, np.array([th1, math.radians(300.0), math.radians(100.0)]))["ok"].all())
        # crank at 60, 300, 100 degrees in that order: counter-clockwise they are out of order, clockwise the crank
        # must cross the ground line, where the loop is open
        an = L.analyse(link, th1, [math.radians(240.0), math.radians(40.0)])
        self.assertEqual(an["defects"]["order"]["status"], "FAIL")
        # 60, 100, 300 counter-clockwise never comes near the ground line
        ok = L.analyse(link, th1, [math.radians(40.0), math.radians(240.0)])
        self.assertEqual(ok["defects"]["order"]["status"], "PASS")

    def test_positions_against_the_closed_form(self):
        for t in (10.0, 80.0, 170.0, 260.0, 340.0):
            pos = L.positions(KNOWN, np.array([math.radians(t)]))
            got = math.degrees(float(pos["theta4"][0]))
            ref = [motion.fourbar_rocker(20.0, 60.0, 50.0, 55.0, t, br) for br in (True, False)]
            self.assertLess(min(abs((got - x + 180) % 360 - 180) for x in ref), 1e-9)


class PathGeneration(unittest.TestCase):
    def test_targets_from_a_known_coupler_curve(self):
        P = L.positions(KNOWN, np.linspace(0, 2 * math.pi, 16, endpoint=False))["P"]
        targets = [[p.real, p.imag] for p in P]
        size = max(np.ptp(P.real), np.ptp(P.imag))
        r = L.synthesise("path", targets=targets, seed=1)
        self.assertEqual(r["evidence"], L.EVIDENCE_PATH)
        self.assertLess(r["error"]["max_mm"], 0.015 * size, "path error against 1.5 % of the path's size")
        self.assertLessEqual(r["error"]["rms_mm"], r["error"]["max_mm"])
        self.assertTrue(r["checks"]["crank_turns_fully"])                 # closed=True asks for a crank that turns
        v = r["verification"]
        # the simulated path (145 frames joined by straight segments) is the same curve: its distances agree with the
        # closed form's to within the chord error of 2.5 degree steps on a crank of this size
        self.assertEqual(v["closed_frames"], v["frames"])
        self.assertLess(abs(v["max_distance_mm"] - r["error"]["max_mm"]), 0.05)
        again = L.synthesise("path", targets=targets, seed=1, verify=False)
        self.assertEqual(again["linkage"]["links_mm"], r["linkage"]["links_mm"], "deterministic for a seed")

    def test_needs_four_points(self):
        with self.assertRaises(L.LinkageError):
            L.path([[0, 0], [1, 0], [1, 1]])


class AsADesign(unittest.TestCase):
    def test_built_and_played_on_its_parts(self):
        from form import config
        from form.linkage import tools
        from form.studio import Studio
        st = Studio(config.load())
        try:
            r = tools.call(st, "motion", poses=POSES, require_crank=True, build=True, name="Linkage test")
            p = st.load(r["project"])
            view = st.view(p)
            self.assertEqual(len(view["assembly"]["parts"]), 4)
            self.assertEqual(sorted(j["id"] for j in view["assembly"]["joints"]), ["coupler", "crank", "rocker"])
            m = r["motion_study"]
            self.assertEqual(m["closed_frames"], m["frames"], "the built linkage closes over the whole turn")
            # the traced pin of the built assembly passes through pose 1 by construction; the study is of the real parts
            res = motion.run(st, p, drivers=[{"joint": "crank", "from": 0, "to": 360}], frames=73, torque_check=False,
                             clearance_check=False, traces=[{"part": "coupler", "at": [0.0, 0.0, 0.0], "label": "P"}])
            pts = np.array([q[:2] for q in res["traces"][0]["positions_mm"]])
            for pose in POSES:
                self.assertLess(float(np.linalg.norm(pts - np.array(pose["at"]), axis=1).min()), 1.0,
                                "the coupler point of the built design passes each pose (73 frames: within a step)")
        finally:
            st.kernel.stop()


if __name__ == "__main__":
    unittest.main()
