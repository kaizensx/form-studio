"""Standard hardware from bd_warehouse through form.parts, checked by fit in the real kernel: every hole fits its
fastener within ISO clearances, threads are valid solids that mate, bearings sit in their seats, gears mesh at the
standard centre distance, pipes slide into their sockets, and the hardware carries a mass for the BOM."""
import importlib.util
import math
import unittest

from build123d import Align, Axis, Box, Cylinder, Pos

from form import material_library as ml
from form import parts
from form.recipes import RecipeError

HAVE_BD = importlib.util.find_spec("bd_warehouse") is not None
HAVE_GEARS = importlib.util.find_spec("py_gearworks") is not None
TOP = (Align.CENTER, Align.CENTER, Align.MAX)
EPS = 1e-3          # mm3: "no overlap" (boolean noise on curved faces)


def overlap(a, b) -> float:
    r = a & b
    return 0.0 if r is None else float(r.volume)


def block(w, h, z_top=0.0):
    return Pos(0, 0, z_top) * Box(w, w, h, align=TOP)


@unittest.skipUnless(HAVE_BD, "bd_warehouse not installed")
class Fasteners(unittest.TestCase):
    def test_clearance_holes_fit_their_screws_within_iso_273(self):
        for size in ("M2.5", "M3", "M4", "M5"):
            d = float(size[1:])
            for fit, col in (("close", 0), ("normal", 1), ("loose", 2)):
                hole = parts.screw_clearance(size, 6, head="socket", fit=fit)
                self.assertEqual(hole["hole_d"], parts.CLEARANCE[size][col])
                self.assertGreater(hole["hole_d"], d, (size, fit))
                plate = block(20, 6) - hole.shape
                sc = parts.screw(size, 10)
                seated = Pos(0, 0, -hole["recess_depth"]) * sc.shape        # head on the counterbore floor
                self.assertLess(overlap(plate, seated), EPS, (size, fit))
                self.assertGreater(hole["counterbore_d"], sc["head_d"])

    def test_countersunk_head_sits_flush(self):
        hole = parts.screw_clearance("M4", 6, head="countersunk")
        sc = parts.screw("M4", 12, "countersunk")
        self.assertAlmostEqual(sc.shape.bounding_box().max.Z, 0.0, places=3)
        self.assertLess(overlap(block(20, 6) - hole.shape, sc.shape), EPS)

    def test_nut_washer_and_insert_dimensions(self):
        n = parts.nut("M3")
        self.assertEqual((n["across_flats"], n["thickness"]), (5.5, 2.4))
        trap = parts.nut_trap("M3")
        self.assertLess(overlap(block(20, 5) - trap.shape, Pos(0, 0, -trap["depth"]) * n.shape), EPS)
        w = parts.washer("M3")
        self.assertEqual((w["inner_d"], w["outer_d"]), (3.2, 7.0))
        ins = parts.heat_insert("M3")
        pocket = parts.heat_insert_pocket("M3")
        # the insert is meant to be bigger than its hole (it melts in); CNC Kitchen: 4.6 mm insert, 4.0 mm hole
        self.assertAlmostEqual(ins["interference"], 0.6)
        self.assertEqual(ins["hole_d"], pocket["hole_d"])
        self.assertLessEqual(-ins.shape.bounding_box().min.Z, pocket["depth"])     # it never bottoms out

    def test_tap_holes_are_iso_tap_drills(self):
        for size in ("M3", "M4", "M5", "M6"):
            h = parts.tap_hole(size, 8)
            d = float(size[1:])
            # a tap drill is a little over the basic minor diameter and well under the major
            self.assertGreater(h["hole_d"], h["basic_minor_d"] - 0.05, size)
            self.assertLess(h["hole_d"], d - 0.5 * h["pitch"], size)
            self.assertGreater(parts.tap_hole(size, 8, "hard")["hole_d"], h["hole_d"])
        self.assertEqual(parts.tap_hole("M8", 10)["hole_d"], 6.8)                      # from bd_warehouse

    def test_stock_lengths(self):
        self.assertIn(10.0, parts.nominal_lengths("M3", "socket"))
        pan = parts.nominal_lengths("M3", "pan")
        self.assertEqual(pan, sorted(pan))
        self.assertEqual(parts.screw_length("M3", 7.1, 12), 8.0)
        with self.assertRaises(RecipeError):
            parts.screw_length("M3", 8.5, 9.5)
        self.assertEqual(parts.screw("M3", 10)["standard_length"], 1)
        self.assertEqual(parts.screw("M3", 11)["standard_length"], 0)

    def test_bolted_joints_fit_and_engage(self):
        clamp = 4.0
        for into in ("insert", "nut", "tap", "self_tap"):
            j = parts.bolted_joint("M3", clamp, into)
            lid = block(24, clamp) - j.top.shape
            base_h = j.base_min + (0 if into == "nut" else 1.0)
            base = block(24, base_h, -clamp) - j.bottom.shape
            self.assertTrue(lid.is_valid and base.is_valid, into)
            self.assertLess(overlap(lid, j.screw.shape), EPS, into)                # passes the clamped part freely
            end = j.screw.shape.bounding_box().min.Z
            if into == "nut":                                                       # passes the nut by 1-3 pitches
                self.assertGreaterEqual(end, -clamp - base_h - 3 * parts.PITCH["M3"] - 1e-6)
            else:
                self.assertGreater(end, -clamp - base_h + 0.5, into)                # never through the floor
            self.assertIn(j.length, parts.nominal_lengths("M3"), into)
            if into in ("insert", "nut"):
                self.assertLess(overlap(base, j.screw.shape), EPS, into)          # threads only in the insert or nut
            else:
                # the screw cuts its own thread: the hole is between the thread's minor and major diameters, and
                # the modelled shank (at the minor diameter, bd_warehouse's plain screw) clears it
                hole_d = j.bottom["hole_d"]
                self.assertTrue(3.0 - 1.0825 * 0.5 - 0.05 < hole_d < 3.0, (into, hole_d))
                self.assertLess(overlap(base, j.screw.shape), EPS, into)
            if into == "nut":
                self.assertLess(overlap(base, j.parts[1].shape), EPS)
                self.assertGreaterEqual(j.dims["protrusion"]["value"], parts.PITCH["M3"] - 1e-6)
            if into == "insert":
                self.assertGreaterEqual(j.dims["engagement"]["value"], 0.6 * 5.7 - 1e-6)
        rows = parts.bolted_joint("M3", clamp, "insert").hardware(4, after="lid")
        self.assertEqual([r.qty for r in rows], [4, 4])
        self.assertTrue(all(r.grams and r.grams > 0 for r in rows))
        with self.assertRaises(RecipeError):
            parts.bolted_joint("M3", clamp, "insert", base=3.0)


@unittest.skipUnless(HAVE_BD, "bd_warehouse not installed")
class Threads(unittest.TestCase):
    def test_lead_screw_and_nut_mate(self):
        rod = parts.trapezoidal_thread(8, 2, 16, starts=4)
        nut_cut = parts.trapezoidal_thread(8, 2, 10, starts=4, external=False)
        self.assertEqual((rod.kind, nut_cut.kind), ("add", "cut"))
        self.assertTrue(rod.shape.is_valid and nut_cut.shape.is_valid)
        self.assertEqual(len(rod.shape.solids()), 1)
        self.assertAlmostEqual(rod["lead"], 8.0)
        nut_body = Pos(0, 0, 13) * Cylinder(8, 10, align=TOP) - Pos(0, 0, 13) * nut_cut.shape
        self.assertTrue(nut_body.is_valid)
        self.assertLess(overlap(nut_body, rod.shape), 0.05)                          # 0.3 mm play each: free
        self.assertTrue(parts.trapezoidal_thread(12, 3, 12, acme=True).shape.is_valid)

    def test_bottle_neck_and_cap_mate(self):
        neck = parts.bottle_thread("PCO1881", external=True)
        cap = parts.bottle_thread("PCO1881", external=False)
        self.assertTrue(neck.shape.is_valid and cap.shape.is_valid)
        L = cap["thread_length"]
        cap_body = Pos(0, 0, L) * Cylinder(17, L, align=TOP) - Pos(0, 0, L) * cap.shape
        self.assertTrue(cap_body.is_valid)
        # a cap meets the neck at whatever angle it is screwed to: some turn of it must clear the neck's thread
        best = min(overlap(cap_body.rotate(Axis.Z, a), neck.shape) for a in range(0, 360, 15))
        self.assertLess(best, 0.05)
        self.assertAlmostEqual(neck["major_d"], 27.4, places=1)                    # PCO 1881 neck
        with self.assertRaises(RecipeError):
            parts.bottle_thread("not-a-finish")


@unittest.skipUnless(HAVE_BD, "bd_warehouse not installed")
class Bearings(unittest.TestCase):
    def test_bearing_sits_in_its_seat(self):
        for key in ("623", "608", "6000"):
            seat = parts.bearing_seat(key, fit=0.05)
            b = parts.bearing(key)
            self.assertAlmostEqual(seat["seat_d"] - b["outer_d"], 0.05)
            housing = block(40, b["width"] + 4) - seat.shape
            self.assertLess(overlap(housing, Pos(0, 0, -b["width"]) * b.shape), EPS, key)
            self.assertGreater(b.grams, 0)
        self.assertAlmostEqual(parts.bearing("608").grams, 12, delta=2.5)          # a 608 weighs about 12 g


@unittest.skipUnless(HAVE_GEARS, "py_gearworks not installed")
class Gears(unittest.TestCase):
    def test_pair_meshes_only_at_the_standard_centre_distance(self):
        gp = parts.gear_pair(2.0, 14, 28, 6, 5, 5, backlash=0.2)
        self.assertAlmostEqual(gp.centre_distance, 42.0)
        self.assertLess(overlap(gp.a.shape, gp.b.shape), 1e-6)
        closer = Pos(-0.5, 0, 0) * gp.b.shape                    # 0.5 mm too close: the teeth collide
        self.assertGreater(overlap(gp.a.shape, closer), 0.1)


@unittest.skipUnless(HAVE_BD, "bd_warehouse not installed")
class ChainAndPipe(unittest.TestCase):
    def test_sprocket_geometry(self):
        s = parts.sprocket(18, "08B", bore=10)
        self.assertTrue(s.shape.is_valid)
        self.assertAlmostEqual(s["pitch_d"], 12.7 / math.sin(math.pi / 18), places=3)
        self.assertAlmostEqual(s["thickness"], round(0.93 * 7.75, 2))
        self.assertLess(s["pitch_d"], s["tip_d"])
        self.assertEqual(parts.chain_spec("ANSI 40")[3], "08A")

    def test_chain_length(self):
        # equal sprockets: L = 2C/p + z exactly
        self.assertAlmostEqual(parts.chain_links(12.7, 20, 20, 254.0), 60.0)
        d = parts.chain_drive("08B", 12, 24, 150)
        self.assertEqual(d["links"] % 2, 0)
        self.assertGreaterEqual(d["centre_distance"], 150 - 1e-6)
        self.assertAlmostEqual(parts.chain_links(12.7, 12, 24, d["centre_distance"]), d["links"], places=3)

    def test_pipe_fits_socket_and_flange(self):
        od, t = parts.pipe_size("3/4", "40", "pvc")
        self.assertAlmostEqual(od, 26.67, places=2)                          # 1.050 in, ASTM D1785
        sock = parts.pipe_socket("3/4", 20)
        fitting = block(40, 25) - sock.shape
        p = Pos(0, 0, -20) * parts.pipe("3/4", 30).shape
        self.assertLess(overlap(fitting, p), EPS)
        self.assertGreater(parts.pipe("3/4", 100).grams, 10)
        fl = parts.pipe_flange("1", 150, "slip_on")
        self.assertGreater(fl["bore"], parts.pipe_size("1", "40", "steel")[0])     # a slip-on flange slides over its pipe
        with self.assertRaises(RecipeError):
            parts.pipe_size("3/4", "999", "pvc")


class Materials(unittest.TestCase):
    def test_densities_and_mass(self):
        self.assertAlmostEqual(ml.get("aluminium")["density_kg_m3"], 2700)
        self.assertAlmostEqual(ml.get("steel")["density_kg_m3"], 7800)
        self.assertAlmostEqual(ml.mass_g(1000, "brass"), 8.5)
        self.assertEqual(ml.get("brass")["finish"], "metal")
        z = ml.zone("stainless", ["shaft"])
        self.assertEqual((z["features"], z["finish"]), (["shaft"], "metal"))
        with self.assertRaises(KeyError):
            ml.get("unobtanium")

    @unittest.skipUnless(HAVE_BD, "bd_warehouse not installed")
    def test_hardware_mass_is_volume_times_density(self):
        sc = parts.screw("M3", 10)
        self.assertAlmostEqual(sc.grams, sc.shape.volume * 7800e-6, places=2)
        self.assertEqual(sc.material, "mild_steel")
        self.assertEqual(sc.bom(4).grams, sc.grams)

    def test_bom_lists_hardware_mass(self):
        from form import maker_docs
        d = {"slice": None, "p": {"id": "x", "name": "x"}, "rev": {"n": 1},
             "asm": {"parts": [{"label": "Box", "id": "box", "solid": 0, "volume_mm3": 1000.0,
                                "print_bbox": [[0, 0, 0], [10, 10, 10]], "material": ""}],
                     "hardware": [{"name": "M3 x 10 socket screw", "size": "M3 x 10", "qty": 4, "source": "ISO 4762",
                                   "note": "", "grams": 0.9, "material": "mild_steel"}]},
             "view": {"volume_mm3": 1000.0, "bbox": [[0, 0, 0], [10, 10, 10]]}}
        text = maker_docs.bom(d)
        row = text.strip().splitlines()[-1]
        self.assertIn("3.60", row)
        self.assertIn("mild_steel", row)


class WithoutTheLibraries(unittest.TestCase):
    def test_common_hardware_falls_back_to_tables(self):
        import builtins
        from unittest import mock
        real = builtins.__import__

        def fake(name, *a, **k):
            if name.split(".")[0] in ("bd_warehouse", "bd_materials", "py_gearworks"):
                raise ImportError(f"No module named '{name}'")
            return real(name, *a, **k)
        with mock.patch("builtins.__import__", fake):
            sc = parts.screw("M3", 10)
            self.assertTrue(sc.shape.is_valid and sc.grams > 0)
            self.assertEqual(parts.nut("M3")["across_flats"], 5.5)
            self.assertEqual(parts.washer("M3")["outer_d"], 7)
            self.assertTrue(parts.heat_insert("M3").shape.is_valid)
            self.assertGreater(parts.bearing("608").grams, 0)
            self.assertEqual(parts.bolted_joint("M3", 4, "insert").length, 5.0)
            self.assertAlmostEqual(ml.FALLBACK["mild_steel"][2], 7800)
            with self.assertRaises(RecipeError) as cm:
                parts.trapezoidal_thread(8, 2, 10)
            self.assertIn("form-studio[parts]", cm.exception.hint)


@unittest.skipUnless(HAVE_BD and HAVE_GEARS, "parts libraries not installed")
class ExemplarsInTheStudio(unittest.TestCase):
    """The standard-hardware exemplars as designs: they build, their assemblies pass, the BOM carries masses."""

    @classmethod
    def setUpClass(cls):
        import os
        import tempfile
        from form import config
        from form.studio import Studio
        cls._old = os.environ.get("FORM_DATA")
        os.environ["FORM_DATA"] = tempfile.mkdtemp(prefix="form-hw-")
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        import os
        cls.st.kernel.stop()
        if cls._old is None:
            os.environ.pop("FORM_DATA", None)
        else:
            os.environ["FORM_DATA"] = cls._old

    def test_exemplars_build_and_list_their_hardware(self):
        import csv
        import io
        from form import exemplars, maker_docs
        for name, solids in (("lead_screw_axis", 2), ("chain_drive", 3), ("bottle_pipe_adapter", 1)):
            p = self.st.create_design(name, exemplars.get(name)["source"], purpose="model")
            self.assertEqual(self.st.recipe(self.st.load(p["id"])).solids, solids, name)
            if solids == 1:
                continue
            self.st.run_sync(p["id"], ["geometry", "checks"])
            p = self.st.load(p["id"])
            rows = list(csv.DictReader(io.StringIO(maker_docs.working(self.st, p, "BOM.csv").read_text(encoding="utf-8"))))
            bought = {r["item"]: r for r in rows if r["kind"] == "purchased"}
            self.assertIn("608 bearing", bought, name)
            self.assertGreater(float(bought["608 bearing"]["grams"]), 10, name)
            self.assertIn("computed", bought["608 bearing"]["grams_evidence"])
            screws = [r for k, r in bought.items() if "screw" in k and r["grams"]]
            self.assertTrue(screws, name)


if __name__ == "__main__":
    unittest.main()
