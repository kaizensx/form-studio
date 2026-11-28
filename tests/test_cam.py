"""CAM (form/cam): toolpaths for a 3-axis mill, posted, read back, and measured on a stock simulation.

What is proved here, each against a number known in advance:

* **Drop-cutter** against analytic surfaces: flat, ball, bull-nose, drill and chamfer tools on a sphere and on an
  inclined plane, within the tessellation's own sag.
* **Cycle time** against hand calculation: one long move, a move too short to reach its feed, two collinear moves,
  a right-angle corner at the junction-deviation speed, exact stop, a rapid.
* **Posts**: for Grbl, LinuxCNC, Fanuc, Haas and Marlin the posted file parses back to the same motion, in mm and
  in inches, with each dialect's own codes and none it does not accept.
* **Speeds and feeds**: chip load x flutes x RPM by hand, every row with its source, what has no source is assumed.
* **Stock simulation**: the volume a slot removes; a pocket's corners keep r²(1 − π/4) each; a ball's cusps on a
  pocket floor are within the scallop formula; planted gouges (0.2 mm into a wall, 0.08 mm under one cell, 0.3 mm
  into a floor) are found with their depth; a rapid through stock, a shank deeper than its flutes and a holder
  into the stock are found.
* **Operations**: adaptive clearing holds its engagement; a contour leaves its tabs; a deep hole is pecked; a
  chamfer is a declared edge break, not a gouge; 3D finishing on a dome leaves no gouge.
* **The project**: a plan and a program are current only for the revision, tools, options and post they were made
  for; G-code enters a release only simulated, current, with nothing assumed and a person's approval, labelled
  "simulated, not proven on a machine" until a physical result is recorded.
"""
import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-cam-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from build123d import Box, Cylinder, Pos, Sphere  # noqa: E402

from form import cam, config  # noqa: E402
from form.cam import dropcutter, feeds, motion, paths, posts, sim, target, tools  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

FLAT = {"kind": "flat", "d": 6, "flutes": 3, "flute_l": 18, "length": 30, "holder_d": 28, "holder_l": 30}
BALL = {"kind": "ball", "d": 6, "flutes": 2, "flute_l": 12, "length": 30, "holder_d": 28, "holder_l": 30}
DRILL = {"kind": "drill", "d": 5, "flute_l": 40, "length": 50}
CHAMFER = {"kind": "chamfer", "d": 6, "flutes": 3, "angle": 90, "flute_l": 3, "length": 30}
MACH = {"rapid": 3000, "accel": 500, "junction_deviation": 0.01, "max_feed": 3000, "max_rpm": 24000}
SPEC = {"rpm": 12000, "feed": 900, "plunge": 300}


def sphere_tris(Rs, n=90):
    th = np.linspace(0, math.pi / 2, n)
    ph = np.linspace(0, 2 * math.pi, 2 * n)
    T, P_ = np.meshgrid(th, ph, indexing="ij")
    P = np.stack([Rs * np.sin(T) * np.cos(P_), Rs * np.sin(T) * np.sin(P_), Rs * np.cos(T)], -1)
    a, b, c, d = (P[:-1, :-1].reshape(-1, 3), P[1:, :-1].reshape(-1, 3), P[1:, 1:].reshape(-1, 3), P[:-1, 1:].reshape(-1, 3))
    return np.concatenate([a, a]), np.concatenate([b, c]), np.concatenate([c, d])


def plane_tris(slope, half=30.0):
    """z = slope * x over a square."""
    p = np.array([[-half, -half, -half * slope], [half, -half, half * slope], [half, half, half * slope], [-half, half, -half * slope]])
    return p[[0, 0]], p[[1, 2]], p[[2, 3]]


def tris_of(shape):
    t = target.of_shape(shape)
    return t["tri"], t["holes"]


def run(shape, opts, dialect="grbl", **kw):
    tri, holes = tris_of(shape)
    plan = cam.make_plan(tri, holes, opts)
    s = plan["setups"][0]
    g = cam.post_setup(plan, s, dialect)
    r = cam.simulate_setup(plan, s, tri, g, dialect, **kw)
    return plan, s, g, r


class Tools(unittest.TestCase):
    def test_profiles(self):
        f, b = tools.make(FLAT), tools.make(BALL)
        bull = tools.make("8mm-bull-r2")
        dr, ch = tools.make("6mm-drill"), tools.make({"kind": "chamfer", "d": 6, "tip_d": 1})
        self.assertEqual(float(f.profile(2.0)), 0.0)
        self.assertAlmostEqual(float(b.profile(3.0)), 3.0)
        self.assertAlmostEqual(float(b.profile(1.5)), 3 - math.sqrt(9 - 2.25))
        self.assertEqual(float(bull.profile(2.0)), 0.0)                       # the flat of radius R − r
        self.assertAlmostEqual(float(bull.profile(4.0)), 2.0)
        self.assertAlmostEqual(float(dr.profile(3.0)), 3 / math.tan(math.radians(59)))   # a 118° point
        self.assertAlmostEqual(float(ch.profile(3.0)), 2.5)                   # 45° from a Ø1 flat
        self.assertTrue(np.isinf(f.profile(3.1)))

    def test_inside_is_the_distance_to_the_surface(self):
        b = tools.make(BALL)
        self.assertAlmostEqual(float(b.inside(0.0, 1.0)), 1.0, places=3)      # 1 mm above the tip of a ball
        self.assertAlmostEqual(float(b.inside(0.0, 3.0)), 3.0, places=3)
        self.assertEqual(float(b.inside(0.0, -0.1)), 0.0)                     # under the tip: outside
        f = tools.make(FLAT)
        self.assertAlmostEqual(float(f.inside(2.8, 5.0)), 0.2)                # 0.2 from the cylinder
        self.assertAlmostEqual(float(f.inside(1.0, 0.3)), 0.3)                # 0.3 above the end
        self.assertEqual(f.part(5), "cutter")
        self.assertEqual(f.part(20), "shank")
        self.assertEqual(f.part(31), "holder")
        self.assertAlmostEqual(float(f.envelope(10.0)), 30.0)                 # under the holder
        self.assertTrue(np.isinf(f.envelope(14.5)))

    def test_a_named_tool_is_assumed_and_a_described_one_is_not(self):
        self.assertEqual(tools.make("6mm-flat").provenance, "assumed")
        self.assertEqual(tools.make(FLAT).provenance, "specified")
        self.assertTrue(all(t.provenance == "assumed" for t in tools.library(None)))
        with self.assertRaises(StudioError):
            tools.make("a big one")


class DropCutter(unittest.TestCase):
    def test_on_a_sphere(self):
        Rs = 20.0
        m = dropcutter.Mesh(sphere_tris(Rs))
        # the tessellation lies inside the sphere by its chords' sag (one along each direction), seen along Z on
        # a slope of up to 52° where these points touch
        sag = (Rs * (1 - math.cos(math.pi / 2 / 89 / 2)) + Rs * (1 - math.cos(2 * math.pi / 179 / 2))) / math.cos(math.radians(52))
        rng = np.random.default_rng(3)
        xy = rng.uniform(-9, 9, (500, 2))
        d = np.hypot(xy[:, 0], xy[:, 1])
        for spec in ("6mm-flat", "6mm-ball", "8mm-bull-r2", "6mm-drill", "6mm-chamfer-90"):
            t = tools.make(spec)
            R = t.r
            z = m.drop(t, xy)
            if t.kind == "ball":
                ref = np.sqrt((Rs + R) ** 2 - d ** 2) - R
            elif t.kind == "flat":
                ref = np.where(d <= R, Rs, np.sqrt(Rs ** 2 - np.maximum(d - R, 0) ** 2))
            elif t.kind == "bull":
                rc, R1 = t.corner_r, R - t.corner_r
                ref = np.where(d <= R1, Rs, np.sqrt((Rs + rc) ** 2 - np.maximum(d - R1, 0) ** 2) - rc)
            else:                                                             # a cone: the best over its radius
                rr = np.linspace(0, R, 3001)
                ref = np.array([np.max(np.sqrt(np.maximum(Rs ** 2 - (dd - rr) ** 2, 0)) - t.profile(rr)) for dd in d])
            err = z - ref
            self.assertLessEqual(float(err.max()), 1e-6, spec)               # never above the true surface's answer
            self.assertGreaterEqual(float(err.min()), -sag, spec)

    def test_on_an_inclined_plane(self):
        for slope in (0.25, 1.0, 2.5):
            m = dropcutter.Mesh(plane_tris(slope))
            xy = np.array([[0.0, 0.0], [3.3, -2.0], [-7.0, 5.0]])
            k = math.sqrt(1 + slope * slope)
            for spec in ("6mm-flat", "6mm-ball", "8mm-bull-r2", "6mm-drill"):
                t = tools.make(spec)
                R = t.r
                z = m.drop(t, xy)
                base = slope * xy[:, 0]
                if t.kind == "flat":
                    ref = base + slope * R                                   # the rim, uphill
                elif t.kind == "ball":
                    ref = base + R * k - R                                   # the sphere's centre is R·sqrt(1+m²) above
                elif t.kind == "bull":
                    rc = t.corner_r
                    ref = base + slope * (R - rc) + rc * k - rc
                else:
                    ms = 1 / math.tan(t.half_angle)
                    ref = base if slope <= ms else base + slope * R - t.cone_h   # its point, or its rim
                np.testing.assert_allclose(z, ref, atol=2e-6, err_msg=f"{spec} on slope {slope}")

    def test_the_waterline_of_a_cylinder_is_a_circle(self):
        tri, _ = tris_of(Cylinder(10, 10))
        tr = (tri[:, 0], tri[:, 1], tri[:, 2])
        m = dropcutter.Mesh(tr)
        t = tools.make(FLAT)
        lo, c, shape = (-16.0, -16.0), 0.4, (81, 81)
        lines = dropcutter.waterline(m, t, 0.0, lo, c, shape)
        self.assertEqual(len(lines), 1)
        r = np.hypot(lines[0][:, 0], lines[0][:, 1])
        self.assertTrue(dropcutter.closed(lines[0]))
        self.assertLess(float(np.abs(r - 13.0).max()), 0.02 + 1e-3)          # the tessellation's tolerance
        self.assertGreaterEqual(float(r.min()), 13.0 - 0.021)                # never inside the wall by more
        # the free side is on the left: counter-clockwise around the outside means the part is on the right
        x, y = lines[0][:, 0], lines[0][:, 1]
        self.assertLess(float((x[:-1] * y[1:] - x[1:] * y[:-1]).sum()), 0)   # clockwise around the part: climb


class CycleTime(unittest.TestCase):
    M = {"rapid": 3000, "accel": 100, "junction_deviation": 0.01, "max_feed": 6000}

    def t(self, events, **kw):
        return motion.cycle_time(motion.flatten(events), motion.machine({**self.M, **kw}))["seconds"]

    def test_one_long_move(self):
        # 100 mm at 600 mm/min = 10 mm/s with 100 mm/s²: 0.1 s up, 0.1 s down (0.5 mm each), 99 mm at speed
        self.assertAlmostEqual(self.t([("rapid", 0, 0, 0), ("feed", 100, 0, 0, 600)]), 10.1, places=6)

    def test_a_move_too_short_to_reach_its_feed(self):
        # 0.5 mm: peak sqrt(a·L) = 7.071 mm/s, time 2·sqrt(L/a)
        self.assertAlmostEqual(self.t([("rapid", 0, 0, 0), ("feed", 0.5, 0, 0, 600)]), 2 * math.sqrt(0.5 / 100), places=6)

    def test_two_collinear_moves_are_one(self):
        self.assertAlmostEqual(self.t([("rapid", 0, 0, 0), ("feed", 50, 0, 0, 600), ("feed", 100, 0, 0, 600)]), 10.1, places=6)

    def test_a_right_angle_corner(self):
        s = math.sqrt(0.5)
        vj = math.sqrt(100 * 0.01 * s / (1 - s))                              # 1.5538 mm/s through the corner
        one = 10 / 100 + (10 - vj) / 100 + (100 - 0.5 - (100 - vj * vj) / 200) / 10
        got = self.t([("rapid", 0, 0, 0), ("feed", 100, 0, 0, 600), ("feed", 100, 100, 0, 600)])
        self.assertAlmostEqual(got, 2 * one, places=6)
        self.assertAlmostEqual(got, 20.171338, places=4)

    def test_exact_stop_and_a_rapid(self):
        ev = [("rapid", 0, 0, 0), ("feed", 100, 0, 0, 600), ("feed", 100, 100, 0, 600)]
        self.assertAlmostEqual(self.t(ev, exact_stop=True), 20.2, places=6)
        # 300 mm at 3000 mm/min = 50 mm/s with 500 mm/s²: 6 s + 0.1 s
        self.assertAlmostEqual(self.t([("rapid", 0, 0, 0), ("rapid", 300, 0, 0)], accel=500), 6.1, places=6)

    def test_the_limits_are_stated(self):
        ct = motion.cycle_time(motion.flatten([("rapid", 0, 0, 0), ("feed", 10, 0, 0, 600)]), motion.machine({"accel": 800}))
        self.assertEqual(ct["limits"]["accel_mm_s2"], 800)
        self.assertIn("rapid", ct["limits"]["assumed"])                       # not given: the default, named as assumed
        self.assertNotIn("accel", ct["limits"]["assumed"])


EVENTS = [("op", 1, "test"), ("tool", 1), ("spindle", 12000), ("rapid", 0, 0, 5), ("rapid", 10, 10, 5), ("rapid", 10, 10, 1),
          ("feed", 10, 10, -2, 300), ("feed", 30, 10, -2, 900), ("arc", 30, 20, -2, 30, 15, False, 900),
          ("arc", 30, 20, -3, 30, 15, False, 900), ("arc", 30, 10, -3, 30, 15, True, 900),
          ("feed", 10.1234567, 20.7654321, -3, 900), ("rapid", 10.1234567, 20.7654321, 5), ("stop",), ("tool", 2),
          ("spindle", 3000), ("rapid", 40, 5, 5), ("drill", 40, 5, -12, 1, 3, 200), ("rapid", 45, 5, 5),
          ("drill", 45, 5, -4, 1, 0, 200), ("stop",), ("home",), ("end",)]


class Posts(unittest.TestCase):
    def test_every_dialect_reads_back_as_the_same_motion(self):
        ref = motion.cycle_time(motion.flatten(posts.rounded(EVENTS)), motion.machine(MACH))
        for d in posts.DIALECTS:
            for units in ("mm", "inch"):
                text = posts.post(EVENTS, d, units=units, tools={1: "flat", 2: "drill"}, mach=MACH)
                back = posts.parse(text, d)
                self.assertEqual(back["problems"], [], f"{d} {units}")
                self.assertEqual(back["units"], units)
                same, why = posts.same_motion(EVENTS, back["events"], units, posts.DIALECTS[d]["canned"])
                self.assertTrue(same, f"{d} {units}: {why}")
                self.assertEqual(back["tools"], [1, 2], d)
                if units == "mm":                                             # and so the clock reads the same
                    ct = motion.cycle_time(motion.flatten(back["events"]), motion.machine(MACH))
                    self.assertAlmostEqual(ct["feed_mm"], ref["feed_mm"], delta=0.01)
                    self.assertAlmostEqual(ct["seconds"], ref["seconds"], delta=0.02)

    def test_each_dialect_has_its_own_codes(self):
        t = {d: posts.post(EVENTS, d, tools={1: "flat", 2: "drill"}, mach=MACH) for d in posts.DIALECTS}
        for d, text in t.items():
            self.assertIn("G21", text.splitlines()[:14], d)                   # units and absolute distances up front
            self.assertIn("G90", text.splitlines()[:14], d)
            self.assertIn("simulated, not proven on a machine", text.lower(), d)
        g = t["grbl"]
        self.assertNotIn("M6", g)                                             # Grbl has no tool changer
        self.assertNotIn("G81", g)
        self.assertNotIn("G83", g)
        self.assertIn("\nM0\n", g)                                            # it waits for the person instead
        self.assertIn("\nG54\n", g)
        self.assertTrue(g.rstrip().endswith("G0 Z5.000\nM5\nM2"))               # up at the clearance height, and no
        self.assertNotIn("G53", g)                                            # move in machine coordinates
        self.assertNotIn("G28", g)
        lc = t["linuxcnc"]
        for w in ("T1 M6", "G43 H1", "T2 M6", "G43 H2", "G64 P0.01", "G98 G83", "G98 G81", "G80", "G53 G0 Z0"):
            self.assertIn(w, lc)
        self.assertIn("Q3.000", lc)
        fa = t["fanuc"]
        self.assertTrue(fa.startswith("%\nO1000"))
        self.assertTrue(fa.rstrip().endswith("M30\n%"))
        self.assertIn("G91 G28 Z0\nG90", fa)
        self.assertIn("G43 H1", fa)
        self.assertEqual(fa, "\n".join(ln if not ln.startswith("(") else ln.upper() for ln in fa.splitlines()) + "\n")
        ha = t["haas"]
        self.assertTrue(ha.startswith("%\nO00001"))
        self.assertIn("G53 G0 Z0", ha)
        ma = t["marlin"]
        self.assertNotIn("(", ma)                                             # semicolon comments only
        self.assertNotIn("G54", ma)
        self.assertNotIn("M30", ma)
        self.assertNotIn("M6", ma)
        self.assertRegex(ma, r"G0 Z5\.000 F3000\.0")                          # Marlin runs G0 at the last feedrate
        # modal: a second feed move in a row carries no G word and no repeated feed
        self.assertIn("\nX30.000 F900.0\n", g)
        self.assertIn("G3 X30.000 Y20.000 I0.000 J5.000", g)
        self.assertIn("G3 X30.000 Y20.000 Z-3.000 I0.000 J-5.000", g)         # a full turn down a helix

    def test_inches(self):
        text = posts.post(EVENTS, "linuxcnc", units="inch", mach=MACH)
        self.assertIn("G20", text)
        self.assertIn("X1.1811 F35.43", text)                                 # 30 mm, 900 mm/min
        back = posts.parse(text, "linuxcnc")
        feed = [e for e in back["events"] if e[0] == "feed"][1]
        self.assertAlmostEqual(feed[1], 30.0, delta=0.0013)
        self.assertAlmostEqual(feed[4], 900.0, delta=0.13)

    def test_what_a_controller_would_not_accept_is_named(self):
        fan = posts.post(EVENTS, "fanuc", mach=MACH)
        p = posts.parse(fan, "grbl")["problems"]                              # a Fanuc file fed to Grbl
        self.assertTrue(any("G83" in x for x in p) and any("M6" in x for x in p), p)
        p = posts.parse("G90\nG0 X0 Y0 Z5\nG1 X5 F100\n", "grbl")["problems"]
        self.assertTrue(any("units" in x for x in p))
        p = posts.parse("G21\nG90\nG0 X0 Y0 Z0\nG2 X10 Y0 I4 J0 F100\n", "grbl")["problems"]
        self.assertTrue(any("off its radius" in x for x in p), p)
        self.assertTrue(posts.parse("G21 G90\nG0 X0 Y0 Z0\nG41 G1 X5 F100\n", "linuxcnc")["problems"])
        with self.assertRaises(StudioError):
            posts.post(EVENTS, "heidenhain")

    def test_a_changed_file_is_not_the_plan(self):
        text = posts.post(EVENTS, "grbl", mach=MACH).replace("X30.000 F900.0", "X30.200 F900.0")
        same, why = posts.same_motion(EVENTS, posts.parse(text, "grbl")["events"], "mm", False)
        self.assertFalse(same)


class Feeds(unittest.TestCase):
    def test_every_row_names_its_source(self):
        t = feeds.table()
        for s in t["sources"].values():
            for k in ("title", "publisher", "url", "published", "read", "formula"):
                self.assertTrue(s.get(k), f"source {s['id']} has no {k}")
        for m in t["materials"]:
            self.assertIn(m["source"], t["sources"], m["id"])
            self.assertTrue(m.get("quote"), f"{m['id']}: a sourced row quotes its line")
            self.assertEqual(len(m["sfm"]), 2)
            for d, c in m["chipload_in"].items():                             # the quoted line holds every number
                self.assertIn(f"{c:g}".lstrip("0"), m["quote"], f"{m['id']} {d}")
            self.assertIn(f"{m['sfm'][0]}-{m['sfm'][1]}", m["quote"])

    def test_by_hand(self):
        t = tools.make(FLAT)                                                  # Ø6, 3 flutes, wrought aluminium
        f = feeds.for_op(t, "aluminum", motion.machine(MACH))
        rpm = 3.82 * 800 / (6 / 25.4)
        self.assertEqual(f["rpm"], round(rpm))                                # 12937
        self.assertAlmostEqual(f["feed"], rpm * 0.002 * 3 * 25.4, delta=0.06)  # 1971.6 mm/min
        self.assertEqual(f["provenance"]["rpm"], "computed")
        self.assertEqual(f["provenance"]["feed"], "computed")
        self.assertEqual(f["provenance"]["plunge"], "assumed")
        self.assertIn("Harvey Tool", f["source"])
        # 6.35 mm is the source's own quarter-inch column
        q = feeds.for_op(tools.make({**FLAT, "d": 6.35}), "aluminum", motion.machine(MACH))
        self.assertIn("0.25 in column", q["calc"])
        # between the 1/4 and 3/8 columns: linear
        cl, how = feeds.chipload_in(feeds.material("aluminum"), 8.0)
        self.assertAlmostEqual(cl, 0.002 + 0.001 * (8 / 25.4 - 0.25) / 0.125, places=9)
        self.assertIn("linear", how)

    def test_limits_and_chip_thinning(self):
        t = tools.make({**FLAT, "d": 3.175})                                  # 1/8 in: 800 SFM wants 24448 RPM
        f = feeds.for_op(t, "aluminum", motion.machine({**MACH, "max_rpm": 18000}))
        self.assertEqual(f["rpm"], 18000)
        self.assertAlmostEqual(f["feed"], 18000 * 0.001 * 3 * 25.4, delta=0.06)
        self.assertAlmostEqual(feeds.thinning(1.2, 6.0), 1 / math.sqrt(1 - 0.6 ** 2))   # 1.25 at a fifth of the diameter
        self.assertEqual(feeds.thinning(3.0, 6.0), 1.0)

    def test_what_has_no_source_is_assumed(self):
        m = motion.machine(MACH)
        self.assertEqual(feeds.for_op(tools.make(FLAT), "oak", m)["provenance"], {"rpm": "assumed", "feed": "assumed", "plunge": "assumed"})
        self.assertEqual(feeds.for_op(tools.make(DRILL), "aluminum", m)["provenance"]["feed"], "assumed")
        self.assertEqual(feeds.for_op(tools.make({**FLAT, "d": 1.0}), "aluminum", m)["provenance"]["feed"], "assumed")   # under 1/8 in
        f = feeds.for_op(tools.make(FLAT), "oak", m, SPEC)
        self.assertEqual(f["provenance"], {"rpm": "specified", "feed": "specified", "plunge": "specified"})
        self.assertEqual(f["assumed"], [])
        self.assertEqual((f["rpm"], f["feed"], f["plunge"]), (12000, 900.0, 300.0))


# ---- the stock simulation on hand-written motion ---------------------------------------------------------------

POCKET = (40.0, 30.0, 10.0, 20.0, 12.0, 5.0)        # block x, y, z; pocket x, y, depth (centred, open at the top, z = 0)


def pocket_shape():
    bx, by, bz, px, py, pd = POCKET
    return Pos(0, 0, -bz / 2) * Box(bx, by, bz) - Pos(0, 0, -pd / 2) * Box(px, py, pd)


def pocket_moves(dx=0.0, dz=0.0, f=600):
    """A Ø6 flat tool around the pocket with its side on the walls and its end on the floor: plunge in the middle,
    out to the wall, once around. dx pushes the +X side into the wall; dz the floor pass into the floor."""
    x, y, z = 7.0 + dx, 3.0, -5.0 - dz
    return [("tool", 1), ("rapid", 0, 0, 5), ("rapid", 0, 0, 0.5), ("feed", 0, 0, z, 200), ("feed", 0, -y, z, f),
            ("feed", x, -y, z, f), ("feed", x, y, z, f), ("feed", -7, y, z, f), ("feed", -7, -y, z, f), ("feed", 0, -y, z, f),
            ("feed", 0, 0, z, f), ("rapid", 0, 0, 5)]


def simulate(events, shape, tool=None, cell=0.25, tol=0.05, top=0.0, as_part=False):
    tri, _ = tris_of(shape)
    tr = (tri[:, 0], tri[:, 1], tri[:, 2])
    lo3, hi3 = tri.reshape(-1, 3).min(axis=0), tri.reshape(-1, 3).max(axis=0)
    pad = 6.0
    lo = np.array([lo3[0] - pad, lo3[1] - pad])
    nx, ny = (int(math.ceil((hi3[i] - lo3[i] + 2 * pad) / cell)) for i in (0, 1))
    xc, yc = lo[0] + (np.arange(nx) + 0.5) * cell, lo[1] + (np.arange(ny) + 0.5) * cell
    foot = ((xc >= lo3[0]) & (xc <= hi3[0]))[:, None] & ((yc >= lo3[1]) & (yc <= hi3[1]))[None, :]
    tgt = sim.target_heights(tr, lo, cell, (nx, ny))
    blank = np.where(np.isfinite(tgt), tgt, lo3[2]) if as_part else np.where(foot, hi3[2] + top, lo3[2])
    stock = sim.Stock(lo, cell, (nx, ny), blank, lo3[2])
    t = tools.make(tool or {**FLAT, "number": 1})
    res = sim.simulate(motion.flatten(events), {1: t}, stock, tgt, sim.surface_samples(tr, 0.3), tol=tol)
    res["_Z"], res["_xc"], res["_yc"] = stock.Z, xc, yc
    return res


class Simulation(unittest.TestCase):
    def test_a_slot_removes_its_volume(self):
        ev = [("tool", 1), ("rapid", -10, 0, 5), ("feed", -10, 0, -2, 200), ("feed", 10, 0, -2, 600), ("rapid", 10, 0, 5)]
        r = simulate(ev, Pos(0, 0, -5) * Box(40, 30, 10), cell=0.1)
        want = (20 * 6 + math.pi * 9) * 2                                     # a stadium 20 long, 6 wide, 2 deep
        self.assertAlmostEqual(r["removed_mm3"], want, delta=0.01 * want)
        self.assertEqual(r["evidence"], "simulated")

    def test_a_pocket_cut_to_size(self):
        r = simulate(pocket_moves(), pocket_shape())
        self.assertEqual(r["verdict"], "pass", r["fails"])
        self.assertEqual(r["gouge"]["gouged_samples"], 0)
        self.assertLess(r["gouge"]["max_mm"], 1e-6)
        self.assertEqual(r["rapid_collisions"], 0)
        # what a Ø6 cutter leaves in four square corners: r²(1 − π/4) each, the pocket's depth high
        corner = 9 * (1 - math.pi / 4)
        self.assertAlmostEqual(r["leftover"]["area_mm2"], 4 * corner, delta=4 * 0.25 * 0.25 * 4)   # within 4 cells a corner
        self.assertAlmostEqual(r["leftover"]["volume_mm3"], 4 * corner * 5, delta=5.0)
        self.assertEqual(len(r["leftover"]["regions"]), 4)
        for reg in r["leftover"]["regions"]:                                  # each in its corner, beyond the cutter's arc
            self.assertAlmostEqual(reg["max_mm"], 5.0)
            x, y = abs(reg["at"][0]), abs(reg["at"][1])
            self.assertTrue(7 < x < 10 and 3 < y < 6 and math.hypot(x - 7, y - 3) > 3, reg)
            self.assertAlmostEqual(reg["area_mm2"], corner, delta=0.3)
        self.assertAlmostEqual(r["removed_mm3"], (20 * 12 - 4 * corner) * 5, delta=6.0)

    def test_a_planted_gouge_in_a_wall_is_found(self):
        r = simulate(pocket_moves(dx=0.2), pocket_shape())
        self.assertEqual(r["verdict"], "fail")
        self.assertAlmostEqual(r["gouge"]["max_mm"], 0.2, delta=0.005)
        self.assertGreater(r["gouge"]["gouged_samples"], 10)
        self.assertTrue(all(abs(m["at"][0] - 10.0) < 1e-6 for m in r["gouge"]["marks"]), r["gouge"]["marks"])   # the +X wall
        self.assertIn("gouge", r["fails"][0])

    def test_a_gouge_narrower_than_a_cell_is_found(self):
        r = simulate(pocket_moves(dx=0.08), pocket_shape(), cell=0.25)
        self.assertAlmostEqual(r["gouge"]["max_mm"], 0.08, delta=0.005)
        self.assertEqual(r["verdict"], "fail")
        ok = simulate(pocket_moves(dx=0.03), pocket_shape(), cell=0.25)       # inside the 0.05 tolerance: measured, not failed
        self.assertAlmostEqual(ok["gouge"]["max_mm"], 0.03, delta=0.005)
        self.assertEqual(ok["verdict"], "pass")

    def test_a_planted_gouge_in_the_floor_is_found(self):
        r = simulate(pocket_moves(dz=0.3), pocket_shape())
        self.assertAlmostEqual(r["gouge"]["max_mm"], 0.3, delta=0.005)
        self.assertAlmostEqual(r["overcut_map"]["max_mm"], 0.3, delta=1e-6)
        self.assertTrue(any(abs(m["at"][2] + 5.0) < 1e-6 for m in r["gouge"]["marks"]))

    def test_a_rapid_through_stock_is_found(self):
        ev = [("tool", 1), ("rapid", -30, 0, 5), ("rapid", -30, 0, -2), ("rapid", -12, 0, -2), ("rapid", -12, 0, 5)]
        r = simulate(ev, Pos(0, 0, -5) * Box(40, 30, 10))
        self.assertEqual(r["verdict"], "fail")
        self.assertGreaterEqual(r["rapid_collisions"], 1)
        self.assertAlmostEqual(max(c["depth_mm"] for c in r["collisions"]), 2.0, delta=1e-6)
        self.assertEqual(r["removed_mm3"], 0.0)                               # a rapid cuts nothing in the model
        ok = [("tool", 1), ("rapid", -30, 0, 5), ("rapid", 30, 0, 5), ("rapid", 30, 0, 0.0), ("rapid", 30, 0, 5)]
        self.assertEqual(simulate(ok, Pos(0, 0, -5) * Box(40, 30, 10))["rapid_collisions"], 0)

    def test_a_cut_deeper_than_the_flutes_and_a_holder_in_the_stock_are_found(self):
        ev = pocket_moves()
        r = simulate(ev, pocket_shape(), tool={**FLAT, "flute_l": 3, "number": 1})
        self.assertEqual(r["verdict"], "fail")
        self.assertTrue(any(c["kind"] == "shank" for c in r["collisions"]))
        self.assertAlmostEqual(max(c["depth_mm"] for c in r["collisions"]), 2.0, delta=1e-6)     # 5 deep, 3 of flute
        # a slot 2 deep beside a boss 10 high: the flutes are long enough, the Ø20 holder 8 above the tip is not
        part = Pos(0, 0, -5) * Box(40, 30, 10) + Pos(17, 0, 5) * Box(6, 30, 10)
        slot = [("tool", 1), ("rapid", 5, -20, 15), ("rapid", 5, -20, -2), ("feed", 5, 20, -2, 600), ("rapid", 5, 20, 15)]
        tool = {**FLAT, "flute_l": 6, "length": 8.0, "holder_d": 20, "holder_l": 20, "number": 1}
        h = simulate(slot, part, tool=tool, as_part=True)
        self.assertEqual({c["kind"] for c in h["collisions"]}, {"holder"}, h["collisions"])
        self.assertAlmostEqual(max(c["depth_mm"] for c in h["collisions"]), 10 - (-2 + 8), delta=1e-6)
        self.assertEqual(h["verdict"], "fail")
        self.assertEqual(simulate(slot, part, tool={**tool, "length": 14.0}, as_part=True)["collisions"], [])

    def test_a_ball_on_a_level_floor_leaves_the_scallop(self):
        R, so = 3.0, 1.0
        ev = [("tool", 1), ("rapid", -15, -10, 5)]
        for k, y in enumerate(np.arange(-10.0, 10.0 + 1e-9, so)):
            a, b = (-15, 15) if k % 2 == 0 else (15, -15)
            ev += [("rapid", a, y, 5), ("feed", a, y, 0.0, 300), ("feed", b, y, 0.0, 600), ("rapid", b, y, 5)]
        r = simulate(ev, Pos(0, 0, -5) * Box(20, 12, 10), tool={**BALL, "number": 1}, cell=0.05, top=1.0)
        h = paths.scallop_height(R, so)                                       # 3 − sqrt(9 − 0.25) = 0.04196
        self.assertAlmostEqual(h, R - math.sqrt(R * R - so * so / 4))
        self.assertLessEqual(r["leftover"]["max_mm"], h + 1e-6)
        self.assertGreaterEqual(r["leftover"]["max_mm"], h - 0.169 * 0.025 - 1e-6)   # a cell centre is within 0.025 of the cusp
        self.assertEqual(r["gouge"]["gouged_samples"], 0)
        self.assertAlmostEqual(paths.scallop_stepover(R, h), so)


# ---- operations, planned ---------------------------------------------------------------------------------------

class Operations(unittest.TestCase):
    def test_a_pocket_end_to_end(self):
        body = Box(60, 40, 20) - Pos(0, 0, 5) * Box(40, 24, 10)
        plan, s, g, r = run(body, {"tools": [FLAT], "material": "aluminum"})
        self.assertEqual([o["op"] for o in s["ops"]], ["face", "adaptive", "finish"])
        self.assertEqual(r["verdict"], "pass", r["fails"])
        self.assertTrue(r["gcode"]["same_motion_as_plan"])
        self.assertLess(r["gouge"]["max_mm"], 0.05)
        self.assertEqual(r["collisions"], [])
        corner = 9 * (1 - math.pi / 4)                                        # the corners, and nothing else, are left
        self.assertEqual(len(r["leftover"]["regions"]), 4)
        self.assertGreaterEqual(r["leftover"]["area_mm2"], 4 * corner - 0.3)
        self.assertLessEqual(r["leftover"]["area_mm2"], 4 * corner * 1.25)    # each corner cut short by under a cell
        for reg in r["leftover"]["regions"]:
            self.assertAlmostEqual(reg["max_mm"], 10.0)
        want = 60 * 40 * 1 + (40 * 24 - 4 * corner) * 10                      # the facing and the pocket
        self.assertAlmostEqual(r["removed_mm3"], want, delta=0.005 * want)
        ad = next(o for o in s["ops"] if o["op"] == "adaptive")["info"]
        self.assertLessEqual(ad["mean_engagement_mm"], 1.25 * ad["stepover_mm"])
        self.assertLessEqual(ad["p95_engagement_mm"], 1.6 * ad["stepover_mm"])
        self.assertLess(ad["max_engagement_mm"], 3.0)                         # never half the cutter's width
        self.assertEqual(ad["entries"]["plunge"], 0)                          # down a helix, not straight in
        self.assertGreater(ad["entries"]["helix"], 0)
        self.assertIn("simulated, not proven on a machine", g)
        self.assertEqual(r["label"], "simulated, not proven on a machine")
        self.assertEqual(r["cycle_time"]["evidence"], "simulated")
        self.assertAlmostEqual(sum(o["seconds"] for o in r["ops"]), r["cycle_time"]["seconds"], delta=0.01)

    def test_a_ball_finished_pocket_floor_is_within_the_scallop_formula(self):
        body = Box(60, 40, 20) - Pos(0, 0, 5) * Box(40, 24, 10)
        so = 1.0
        opts = {"tools": [FLAT, BALL], "material": "aluminum", "stock": {"margin_top": 0}, "sim_cell": 0.1,
                "ops": [{"op": "adaptive", "tool": "6mm-flat"}, {"op": "raster", "tool": "6mm-ball", "all": True, "stepover": so, "step": 0.5}]}
        tri, holes = tris_of(body)
        plan = cam.make_plan(tri, holes, opts)
        s = plan["setups"][0]
        r = cam.simulate_setup(plan, s, tri, cam.post_setup(plan, s, "grbl"), "grbl", cell=0.1, keep_arrays=True)
        self.assertEqual(r["gouge"]["gouged_samples"], 0, r["gouge"])
        ar = r["_arrays"]
        nx, ny = ar["Z"].shape
        x = ar["lo"][0] + (np.arange(nx) + 0.5) * 0.1
        y = ar["lo"][1] + (np.arange(ny) + 0.5) * 0.1
        # the floor well away from the walls (a ball cannot reach into the corner under a wall): x 14..46, y 12..28
        inner = ((x > 14) & (x < 46))[:, None] & ((y > 12) & (y < 28))[None, :]
        left = ar["_left"][inner]
        h = paths.scallop_height(3.0, so)
        self.assertLessEqual(float(left.max()), h + 1e-6)                     # 0.042 mm
        self.assertGreater(float(left.max()), 0.6 * h)
        self.assertGreater(float(np.percentile(left, 50)), 0.0)

    def test_holes_are_drilled_and_bored(self):
        body = Box(60, 40, 20) - Pos(-24, 14, 0) * Cylinder(2.5, 40) - Pos(24, -14, 0) * Cylinder(4, 40)
        plan, s, g, r = run(body, {"tools": [FLAT, DRILL], "material": "aluminum", "stock": {"margin_top": 0}}, "linuxcnc")
        ops = {o["op"]: o for o in s["ops"]}
        self.assertIn("drill", ops)
        self.assertIn("bore", ops)
        d = ops["drill"]["info"]["holes"][0]
        self.assertEqual(d["peck_mm"], 5.0)                                   # 20 deep is over 3 × Ø5: pecked by a diameter
        self.assertIn("G98 G83", g)
        self.assertIn("Q5.000", g)
        self.assertEqual(r["verdict"], "pass", r["fails"])
        self.assertFalse(r["left"], r["leftover"]["regions"])
        want = math.pi * 2.5 ** 2 * 20 + math.pi * 16 * 20
        self.assertAlmostEqual(r["removed_mm3"], want, delta=0.03 * want)
        self.assertAlmostEqual(r["below_stock_mm"], tools.make(DRILL).cone_h + 0.3, delta=0.12)   # the point breaks through (seen at a cell centre)
        # without a drill of that size the small hole is left, and the simulation says so
        plan2, s2, g2, r2 = run(body, {"tools": [FLAT], "material": "aluminum", "stock": {"margin_top": 0}})
        self.assertTrue(any("no drill of that size" in n for n in s2["notes"]))
        self.assertTrue(r2["left"])
        self.assertAlmostEqual(r2["leftover"]["above_tolerance_mm3"], math.pi * 2.5 ** 2 * 20, delta=20)

    def test_a_contour_leaves_its_tabs(self):
        body = Box(50, 30, 6)
        plan, s, g, r = run(body, {"tools": [FLAT], "material": "aluminum", "stock": {"margin_xy": 10, "margin_top": 0}},
                            keep_arrays=True)
        con = next(o for o in s["ops"] if o["op"] == "contour")["info"]
        self.assertEqual(con["tabs"]["count"], 4)
        self.assertEqual(r["verdict"], "pass", r["fails"])
        self.assertFalse(r["left"])                                           # tabs are outside the part: not leftover on it
        ar = r["_arrays"]
        zb = s["stock"]["box"][4]
        for tx, ty in con["tabs"]["at"]:                                      # each tab stands 1.5 mm above the underside
            i = int((tx - ar["lo"][0]) / ar["cell"])
            j = int((ty - ar["lo"][1]) / ar["cell"])
            self.assertAlmostEqual(float(ar["Z"][i, j]), zb + 1.5, delta=1e-6)
        self.assertAlmostEqual(r["below_stock_mm"], 0.3, delta=1e-6)          # and the rest is cut through

    def test_a_chamfer_is_a_declared_edge_break(self):
        body = Box(40, 30, 12) - Pos(0, 0, 3) * Box(20, 14, 6)
        opts = {"tools": [FLAT, CHAMFER], "material": "aluminum", "chamfer": 0.5, "stock": {"margin_top": 0}}
        plan, s, g, r = run(body, opts)
        ch = next(o for o in s["ops"] if o["op"] == "chamfer")["info"]
        self.assertAlmostEqual(ch["edge_mm"], 2 * (40 + 30) + 2 * (20 + 14), delta=6.0)   # the outline and the pocket's rim
        self.assertEqual(r["verdict"], "pass", r["fails"])
        self.assertEqual(r["gouge"]["gouged_samples"], 0)
        self.assertAlmostEqual(r["edge_break"]["max_mm"], 0.5 * math.sin(math.radians(45)), delta=0.03)
        # the same moves with no declaration are a gouge
        plain = cam.simulate_setup(plan, {**s, "intended": []}, tris_of(body)[0], g, "grbl")
        self.assertEqual(plain["verdict"], "fail")
        self.assertAlmostEqual(plain["gouge"]["max_mm"], 0.354, delta=0.03)

    def test_3d_finishing_on_a_dome(self):
        body = Box(50, 50, 10) + (Pos(0, 0, 5 - 30) * Sphere(40) & Pos(0, 0, 15) * Box(50, 50, 20))
        plan, s, g, r = run(body, {"tools": [FLAT, BALL], "material": "aluminum", "scallop": 0.02})
        self.assertIn("raster", [o["op"] for o in s["ops"]])
        self.assertEqual(r["verdict"], "pass", r["fails"])
        self.assertLess(r["gouge"]["max_mm"], 0.05)
        ra = next(o for o in s["ops"] if o["op"] == "raster")["info"]
        self.assertAlmostEqual(ra["stepover_mm"], paths.scallop_stepover(3.0, 0.02), delta=0.02)
        # on the dome itself the cusps stay near the scallop asked for (steeper across the passes: more)
        self.assertLess(r["leftover"]["max_mm"], 0.35)
        self.assertLess(r["leftover"]["above_tolerance_mm3"], 12.0)
        # without a ball the dome is left in steps and the plan says so
        plan2, s2, g2, r2 = run(body, {"tools": [FLAT], "material": "aluminum"})
        self.assertTrue(any("no ball end mill" in n for n in s2["notes"]))
        self.assertTrue(r2["left"])
        self.assertGreater(r2["leftover"]["above_tolerance_mm3"], 100.0)

    def test_waterline_on_a_cone(self):
        from build123d import Cone
        body = Pos(0, 0, -6) * Box(40, 40, 4) + Pos(0, 0, 4) * Cone(14, 6, 16)
        opts = {"tools": [FLAT, BALL], "material": "aluminum", "stock": {"margin_top": 0},
                "ops": [{"op": "adaptive", "tool": "6mm-flat"}, {"op": "finish", "tool": "6mm-flat"},
                        {"op": "waterline", "tool": "6mm-ball", "all": True, "stepdown": 0.3}]}
        plan, s, g, r = run(body, opts)
        wl = next(o for o in s["ops"] if o["op"] == "waterline")
        self.assertGreater(wl["info"]["passes"], 20)
        self.assertEqual(r["gouge"]["gouged_samples"], 0, r["gouge"])
        self.assertEqual(r["collisions"], [])

    def test_the_view_has_the_format_the_viewport_reads(self):
        body = Box(30, 20, 10) - Pos(0, 0, 3) * Box(16, 10, 4)
        tri, holes = tris_of(body)
        plan = cam.make_plan(tri, holes, {"tools": [FLAT], "material": "aluminum"})
        s = plan["setups"][0]
        r = cam.simulate_setup(plan, s, tri, cam.post_setup(plan, s, "grbl"), "grbl", keep_arrays=True)
        v = cam.view(plan, [r])
        self.assertEqual(v["format"], "form-cam-view/1")
        self.assertEqual(v["label"], "simulated, not proven on a machine")
        e = v["setups"][0]
        import base64
        kinds = {(t["operation"], t["kind"]) for t in e["toolpaths"]}
        self.assertIn(("adaptive", "feed"), kinds)
        self.assertIn(("finish", "feed"), kinds)
        for t in e["toolpaths"]:
            P = np.frombuffer(base64.b64decode(t["positions"]), np.float32).reshape(-1, 2, 3)
            self.assertEqual(len(P), t["count"])
            self.assertEqual(len(np.frombuffer(base64.b64decode(t["t"]), np.float32)), t["count"])
            self.assertRegex(t["color"], r"^#[0-9a-f]{6}$")
            self.assertLessEqual(float(P[..., 2].max()), 5 + 5 + 1 + 1e-3)    # the design's frame: the part's top is z = 5
        st = e["stock"]
        V = np.frombuffer(base64.b64decode(st["positions"]), np.float32).reshape(-1, 3)
        I = np.frombuffer(base64.b64decode(st["indices"]), np.uint32)
        S = np.frombuffer(base64.b64decode(st["status"]), np.uint8)
        self.assertEqual(len(V), st["vertices"])
        self.assertEqual(len(S), len(V))
        self.assertLess(int(I.max()), len(V))
        self.assertEqual(set(np.unique(S)) - {0, 1, 2}, set())
        self.assertTrue((S == 1).any())                                       # the pocket's corners are leftover
        self.assertTrue(any(m["kind"] == "leftover" for m in e["marks"]))
        json.dumps(v)

    def test_setups_and_frames(self):
        R = cam.frame_for((0, 0, -1))
        np.testing.assert_allclose(R @ np.array([0, 0, -1.0]), [0, 0, 1])     # the tool axis becomes +Z
        self.assertAlmostEqual(float(np.linalg.det(R)), 1.0)
        for up in ((1, 0, 0), (0, -1, 0), (0.3, 0.4, 0.866)):
            R = cam.frame_for(up)
            self.assertAlmostEqual(float(np.linalg.det(R)), 1.0, places=6)
            np.testing.assert_allclose(R @ (np.array(up) / np.linalg.norm(up)), [0, 0, 1], atol=1e-9)
        body = Box(30, 20, 10) - Pos(0, 0, -3) * Box(16, 10, 4)               # the pocket is on the underside
        top = run(body, {"tools": [FLAT], "material": "aluminum", "stock": {"margin_top": 0}})
        self.assertEqual([o["op"] for o in top[1]["ops"] if not o.get("skipped")], [])     # nothing to cut from +Z
        tri, holes = tris_of(body)
        plan = cam.make_plan(tri, holes, {"tools": [FLAT], "material": "aluminum", "stock": {"margin_top": 0}, "setups": ["-Z"]})
        s = plan["setups"][0]
        self.assertEqual(s["name"], "−Z")
        r = cam.simulate_setup(plan, s, tri, cam.post_setup(plan, s, "grbl"), "grbl")
        self.assertEqual(r["verdict"], "pass", r["fails"])
        self.assertAlmostEqual(r["removed_mm3"], (16 * 10 - 4 * 9 * (1 - math.pi / 4)) * 4, delta=12)


# ---- the project: keys, staleness, release ---------------------------------------------------------------------

DESIGN = '''
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
OPTS = {"tools": [FLAT], "material": "aluminum"}
CONFIRMED = {**OPTS, "feeds": {"6mm-flat": SPEC}, "machine": MACH}


class Project(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # every test module sets FORM_DATA when it is imported; in one process the last one imported wins, so this
        # class says its own folder again before it makes its Studio (and the CLI below is pointed at the same one)
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.p = cls.st.create_design("Pocket plate", DESIGN, purpose="model", process="cnc")

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def load(self):
        return self.st.load(self.p["id"])

    def test_1_plan_post_simulate(self):
        st, p = self.st, self.load()
        self.assertEqual(cam.status(st, p)["state"], "none")
        pl = cam.plan(st, p, OPTS)
        self.assertEqual(pl["rev"], p["head"])
        self.assertEqual([o["op"] for o in pl["setups"][0]["ops"]], ["face", "adaptive", "finish"])
        self.assertTrue(pl["assumed"])                                        # the plunge feeds nobody gave
        self.assertEqual(cam.status(st, self.load())["state"], "planned")
        out = cam.post(st, self.load(), "grbl")
        self.assertEqual(out["label"], "simulated, not proven on a machine")
        f = Path(out["programs"][0]["file"])
        self.assertTrue(f.is_file())
        self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), out["programs"][0]["sha256"])
        s = out["simulation"]
        self.assertEqual(s["evidence"], "simulated")
        self.assertEqual(s["summary"]["verdict"], "pass", s["summary"]["fails"])
        self.assertLess(s["summary"]["gouge_max_mm"], 0.05)
        self.assertIn("posted Grbl 1.1 file", s["setups"][0]["source"])
        self.assertTrue(s["setups"][0]["gcode"]["same_motion_as_plan"])
        self.assertEqual(json.loads(Path(s["view_file"]).read_text())["format"], "form-cam-view/1")
        self.assertEqual(out["status"]["state"], "current")
        again = cam.simulate(st, self.load())
        self.assertTrue(again.get("cached"))
        self.assertEqual(again["key"], s["key"])

    def test_2_a_program_asked_into_a_release_needs_everything_confirmed(self):
        st = self.st
        cam.post(st, self.load(), "grbl", include=True)
        g = st.gate(self.load())
        self.assertFalse(g["ready"])
        self.assertTrue(any("nobody confirmed" in r for r in g["reasons"]), g["reasons"])
        # the person's own speeds and feeds, and their machine: nothing assumed is left
        out = cam.post(st, self.load(), "grbl", options=CONFIRMED, include=True)
        self.assertEqual(out["simulation"]["assumed"], [])
        g = st.gate(self.load())
        cam_reasons = [r for r in g["reasons"] if r.startswith("CNC program")]
        self.assertEqual(cam_reasons, [])
        ids = {w["id"] for w in g["warnings"]}
        self.assertIn("cam_not_proven", ids)                                  # the person acknowledges the label
        self.assertIn("cam_leftover", ids)                                    # and the corners the cutter leaves
        self.assertIn("simulated, not proven on a machine", g["evidence_level"])

    def _pipeline(self):
        self.st.run_sync(self.p["id"])

    def test_3_release_carries_the_program_and_its_label(self):
        st = self.st
        p = self.load()
        if cam.status(st, p)["state"] != "current" or not (p.get("cam") or {}).get("include"):
            cam.post(st, p, "grbl", options=CONFIRMED, include=True)
        self._pipeline()
        p = self.load()
        g = st.gate(p)
        if [r for r in g["reasons"] if not r.startswith("CNC program")]:
            self.skipTest("the pipeline's own outputs are not ready here: " + "; ".join(g["reasons"]))
        with self.assertRaises(StudioError):                                  # not without acknowledging the label
            st.approve(p, [w["id"] for w in g["warnings"] if w["id"] != "cam_not_proven"])
        rel = st.approve(self.load(), [w["id"] for w in g["warnings"]], note="first article")
        m = rel["manifest"]
        self.assertEqual(m["cam"]["label"], "simulated, not proven on a machine")
        self.assertEqual(m["cam"]["evidence"], "simulated")
        prog = m["cam"]["programs"][0]
        d = st.dir(self.p["id"]) / "releases" / rel["release"]
        self.assertEqual(hashlib.sha256((d / prog["filename"]).read_bytes()).hexdigest(), prog["sha256"])
        self.assertEqual(m["files"][prog["filename"]], prog["sha256"])
        self.assertIn("simulated, not proven on a machine", (d / "CAM_REPORT.md").read_text().lower())
        self.assertTrue(any("Prove it on the machine" in x for x in m["limits"]))
        self.assertTrue(st.verify_release(self.load(), rel["release"])["intact"])

    def test_4_a_physical_result_changes_the_label(self):
        st = self.st
        p = self.load()
        if cam.status(st, p)["state"] != "current":
            cam.post(st, p, "grbl", options=CONFIRMED, include=True)
        with self.assertRaises(StudioError):
            st.add_evidence(self.load(), {"kind": "machined", "result": "fine"})
        rec = st.add_evidence(self.load(), {"kind": "machined", "result": "good", "note": "6061, router"})
        self.assertEqual(rec["class"], "physical")
        self.assertEqual(rec["programs"], [x["sha256"] for x in self.load()["cam"]["programs"]])
        s = cam.status(st, self.load())
        self.assertIn("machined: good", s["label"])
        self.assertEqual(len(s["physical"]), 1)

    def test_5_stale_when_the_design_the_tools_or_the_file_change(self):
        st = self.st
        p = self.load()
        cam.post(st, p, "grbl", options=CONFIRMED, include=True)
        self.assertEqual(cam.status(st, self.load())["state"], "current")
        # the file is edited by hand
        f = Path(self.load()["cam"]["programs"][0]["file"])
        text = f.read_text()
        f.write_text(text.replace("F900.0", "F2900.0", 1))
        s = cam.status(st, self.load())
        self.assertEqual(s["state"], "stale")
        self.assertIn("changed after it was posted", " ".join(s["why"]))
        self.assertTrue(any("no current simulation" in r for r in st.gate(self.load())["reasons"]))
        with self.assertRaises(StudioError):                                  # the stored result is not this file's
            cam.simulate(st, self.load())
        f.write_text(text)
        self.assertEqual(cam.status(st, self.load())["state"], "current")
        # another post: its own program and its own simulation
        out = cam.post(st, self.load(), "fanuc")
        self.assertTrue(out["programs"][0]["filename"].endswith("_fanuc.nc"))
        self.assertEqual(cam.status(st, self.load())["state"], "current")
        # the design changes: the plan was made for another solid
        head = self.load()["head"]
        st.commit(self.load(), {"depth": 5.0}, "deeper pocket")
        p = self.load()
        self.assertEqual(p["head"], head + 1)
        s = cam.status(st, p)
        self.assertEqual(s["state"], "stale")
        self.assertIn("changed since", " ".join(s["why"]))
        self.assertTrue(any("no current simulation" in r for r in st.gate(p)["reasons"]))
        with self.assertRaises(StudioError):
            cam.simulate(st, p)
        self.assertIsNone(s.get("physical"))                                  # the old result does not speak for a stale program
        out = cam.post(st, p, "grbl")
        self.assertEqual(out["rev"], p["head"])
        self.assertEqual(cam.status(st, self.load())["state"], "current")
        self.assertEqual(cam.status(st, self.load())["physical"], [])         # nor for the new one
        self.assertEqual(out["status"]["label"], "simulated, not proven on a machine")
        # the pocket is a millimetre deeper, and the simulation measured that solid
        corner = 9 * (1 - math.pi / 4)
        want = 40 * 30 * 1 + (20 * 14 - 4 * corner) * 5
        self.assertAlmostEqual(out["simulation"]["summary"]["removed_mm3"], want, delta=0.01 * want)

    def test_6_cli_and_mcp(self):
        # the Studio's own data folder: another test module may have set FORM_DATA before this one was imported
        env = {**os.environ, "FORM_DATA": str(self.st.root), "PYTHONPATH": str(ROOT)}
        r = subprocess.run([sys.executable, "-m", "form", "cam", "status", self.p["id"]], capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(json.loads(r.stdout)["state"], ("current", "stale", "planned", "posted"))
        r = subprocess.run([sys.executable, "-m", "form", "cam", "materials"], capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertIn("aluminum_wrought", r.stdout)
        r = subprocess.run([sys.executable, "-m", "form", "cam", "posts"], capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(set(json.loads(r.stdout)), {"grbl", "linuxcnc", "fanuc", "haas", "marlin"})
        from form import mcp_server
        names = {t.name for t in asyncio.run(mcp_server.build().list_tools())}
        self.assertTrue({"cam_plan", "cam_post", "cam_simulate"} <= names)
        o = cam.options_from_cli(["6mm-flat", json.dumps(BALL)], "aluminum", ["machine.rapid=5000", "setups=auto", "stock.margin_xy=6"])
        self.assertEqual(o["tools"][0], "6mm-flat")
        self.assertEqual(o["tools"][1]["kind"], "ball")
        self.assertEqual(o["machine"], {"rapid": 5000})
        self.assertEqual(o["setups"], "auto")
        self.assertEqual(o["stock"], {"margin_xy": 6})


if __name__ == "__main__":
    unittest.main()
