"""The standard-parts library (form/catalog.py): dimensions against the standards' tables.

Two kinds of test: spot-checks of values read from independent sources (the standard's own table, a second maker's
catalogue) against what the library gives, and one assertion per size of every family: the part is built as real CAD
and its solid measures what its table says (diameters, lengths, widths), so no size can drift from its row."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from form import catalog as c  # noqa: E402
from form.studio import StudioError  # noqa: E402


def d(it, k):
    return c.dims(it)[k]["value"]


class SpotChecks(unittest.TestCase):
    """Values from a second source (named on each line) agree with the library's table."""

    def test_iso4032_widths_across_flats(self):
        # Würth DINO technical chapter §3.5 (ISO 4032 against DIN 934)
        for size, s in {"M10": 16, "M12": 18, "M14": 21, "M22": 34, "M3": 5.5, "M5": 8, "M8": 13}.items():
            self.assertEqual(d({"family": "iso4032", "size": size}, "across_flats"), s, size)
        self.assertFalse(c.din("DIN 934")["same"])           # not the same nut: never substituted
        self.assertTrue(c.din("DIN 912")["same"])

    def test_iso4762_heads(self):
        # ISO 4762: k = d for every size; hexagon socket s 2.5 (M3), 4 (M5), 6 (M8), 8 (M10)
        for size in c.family("iso4762").sizes():
            it = {"family": "iso4762", "size": size}
            self.assertEqual(d(it, "head_h"), d(it, "d"), size)
        for size, s in {"M3": 2.5, "M5": 4, "M8": 6, "M10": 8}.items():
            self.assertEqual(d({"family": "iso4762", "size": size}, "drive"), s)

    def test_iso7380_and_iso10642(self):
        self.assertEqual((d({"family": "iso7380", "size": "M5"}, "head_d"), d({"family": "iso7380", "size": "M5"}, "head_h")), (9.5, 2.75))
        self.assertEqual(d({"family": "iso10642", "size": "M5"}, "head_h"), 2.8)

    def test_iso7089(self):
        it = {"family": "iso7089", "size": "M5"}
        self.assertEqual((d(it, "inner_d"), d(it, "outer_d")), (5.3, 10))
        self.assertTrue(1.0 <= d(it, "thickness") <= 1.1)

    def test_bearings_match_skf(self):
        # igus table (ISO 15 / DIN 625) against SKF's catalogue values that bd_warehouse ships, for every size both have
        skf = c._bd_csv("single_row_deep_groove_ball_bearing_parameters.csv", "SKT")
        both = 0
        for v in skf.values():
            name = str(v.get("Designation", "")).replace("*", "").strip().split(".")[0]
            if name in c.BEARINGS:
                self.assertEqual(c.BEARINGS[name], (v["d"], v["D"], v["B"]), name)
                both += 1
        self.assertGreaterEqual(both, 12)
        self.assertEqual(c.BEARINGS["608"], (8, 22, 7))
        self.assertEqual(c.BEARINGS["6205"], (25, 52, 15))

    def test_lm8uu_thk(self):
        it = {"family": "lm_uu", "size": "LM8UU"}
        self.assertEqual([d(it, k) for k in ("bore", "outer_d", "length", "groove_spacing", "groove_width", "groove_d")],
                         [8, 15, 24, 17.5, 1.1, 14.3])

    def test_din705_ganter(self):
        it = {"family": "shaft_collar", "size": "8"}
        self.assertEqual((d(it, "outer_d"), d(it, "width"), d(it, "set_screw")), (16, 8, 4))

    def test_iso8734(self):
        self.assertEqual(d({"family": "dowel", "size": "6"}, "chamfer"), 1.2)
        with self.assertRaises(StudioError):                  # 6 × 70 is past the table's range for d 6
            c.resolve({"family": "dowel", "size": "6", "length": 70})
        self.assertEqual(c.designation({"family": "dowel", "size": "6", "length": 20}), "Parallel pin ISO 8734 - 6 × 20 - A - St")

    def test_magnet_grades(self):
        it = c.resolve({"family": "magnet", "d": 10, "h": 2, "grade": "N42"})
        self.assertEqual((d(it, "Br_min"), d(it, "Br_max")), (1.29, 1.32))
        self.assertEqual(c.MAGNET_DENSITY[0], 7600.0)

    def test_nema(self):
        n17 = {"family": "nema", "size": "17"}
        self.assertEqual((d(n17, "hole_spacing"), d(n17, "pilot_d"), d(n17, "shaft_d")), (31.0, 22.0, 5.0))
        n23 = {"family": "nema", "size": "23"}
        self.assertEqual((d(n23, "hole_spacing"), d(n23, "pilot_d"), d(n23, "shaft_d")), (47.14, 38.1, 6.35))
        self.assertEqual(c.dims(n17)["frame"]["provenance"], "assumed")    # 'about 42 mm': never claimed as the standard

    def test_gt2(self):
        it = {"family": "gt2_pulley", "size": "20"}
        self.assertAlmostEqual(d(it, "pitch_d"), 40 / math.pi, places=3)
        self.assertEqual(c.dims(it)["outer_d"]["provenance"], "assumed")   # the pitch-line differential is not verified
        self.assertEqual(c.belt_teeth(20, 20, 100)["teeth"], 120)          # 2C + π·PD = 200 + 40 mm

    def test_oring_iso3601(self):
        it = {"family": "oring", "size": "010"}
        self.assertEqual((d(it, "inner_d"), d(it, "section")), (6.07, 1.78))


class Designations(unittest.TestCase):
    def test_strings(self):
        self.assertEqual(c.designation({"family": "iso4762", "size": "M5", "length": 12, "grade": "A2-70"}), "ISO 4762 M5×12 A2-70")
        self.assertEqual(c.designation({"family": "iso4032", "size": "M5", "grade": "8"}), "ISO 4032 M5 8")
        self.assertEqual(c.designation({"family": "iso7089", "size": "M5"}), "ISO 7089 - 5 - 200 HV")
        self.assertEqual(c.designation({"family": "bearing", "size": "608", "seal": "2RS"}),
                         "Deep-groove ball bearing 608-2RS (8×22×7)")
        self.assertIn("replaced by ISO 4762", c.designation({"family": "din912", "size": "M3", "length": 10}))

    def test_lengths_come_from_the_series(self):
        with self.assertRaises(StudioError):
            c.resolve({"family": "iso4762", "size": "M3", "length": 11})
        self.assertEqual(c.family("iso4762").choose_length(c.resolve({"family": "iso4762", "size": "M3"}), 10), 10.0)

    def test_unknown_sizes_are_refused(self):
        for it in ({"family": "iso4762", "size": "M7"}, {"family": "bearing", "size": "6206"}, {"family": "nema", "size": "34"},
                   {"family": "teapot", "size": "1"}):
            with self.assertRaises(StudioError):
                c.resolve(it)

    def test_search(self):
        top = lambda q: c.search(q)[0]
        self.assertEqual(top("608")["spec"]["family"], "bearing")
        self.assertEqual(top("lm8uu")["spec"]["size"], "LM8UU")
        self.assertEqual(top("nema 17")["spec"]["size"], "17")
        r = top("iso 4762 m3x10")
        self.assertEqual((r["spec"]["family"], r["spec"]["size"], r["spec"]["length"]), ("iso4762", "M3", 10.0))
        r = top("m5 socket 12")
        self.assertEqual((r["spec"]["family"], r["spec"]["length"]), ("iso4762", 12.0))

    def test_every_table_cites_a_source(self):
        for f in c.FAMILIES.values():
            src = f.source()
            self.assertTrue(len(src) > 20 and any(w in src for w in ("ISO", "DIN", "THK", "NEMA", "OpenBuilds", "CNC Kitchen",
                                                                       "Pfeifer", "supermagnete", "Ganter", "igus")), f.id)
            for k, v in c.describe({"family": f.id, "size": f.sizes()[0], **({"length": f.lengths({"size": f.sizes()[0]})[0]}
                                                                               if isinstance(f, c._Screw) else {})})["dims"].items():
                self.assertIn(v["provenance"], ("specified", "computed", "assumed"), (f.id, k))
                self.assertTrue(v["source"], (f.id, k))

    def test_importable_without_occt(self):
        import subprocess
        code = "import sys, form.catalog as c; c.search('608'); c.describe({'family':'heat_insert','size':'M3'}); print('build123d' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class EverySizeIsRealCAD(unittest.TestCase):
    """One assertion per size: the built solid measures its table row."""

    def size(self, it):
        p = c.build(it)
        self.assertTrue(p.shape.is_valid, it)
        bb = p.shape.bounding_box()
        return p, bb.size.X, bb.size.Y, bb.size.Z

    def test_screws(self):
        for fid in ("iso4762", "iso7380", "iso10642"):
            f = c.family(fid)
            for s in f.sizes():
                L = f.lengths({"size": s})
                it = c.resolve({"family": fid, "size": s, "length": L[len(L) // 2]})
                _p, x, y, z = self.size(it)
                with self.subTest(fid=fid, size=s):
                    if fid == "iso10642":     # the table's dk is the theoretical sharp-cone diameter; the head is smaller
                        self.assertTrue(0.85 * d(it, "head_d") <= max(x, y) <= d(it, "head_d") + 0.01)
                    else:
                        self.assertAlmostEqual(max(x, y), d(it, "head_d"), delta=0.02)
                    want = it["length"] + (0 if fid == "iso10642" else d(it, "head_h"))
                    self.assertAlmostEqual(z, want, delta=0.02)

    def test_nuts_and_washers(self):
        for s in c.family("iso4032").sizes():
            it = c.resolve({"family": "iso4032", "size": s})
            _p, x, y, z = self.size(it)
            with self.subTest(nut=s):
                self.assertAlmostEqual(min(x, y), d(it, "across_flats"), delta=0.02)
                self.assertAlmostEqual(z, d(it, "thickness"), delta=0.02)
        for s in c.family("iso7089").sizes():
            it = c.resolve({"family": "iso7089", "size": s})
            _p, x, y, z = self.size(it)
            with self.subTest(washer=s):
                self.assertAlmostEqual(x, d(it, "outer_d"), delta=0.01)
                self.assertAlmostEqual(z, d(it, "thickness"), delta=0.01)

    def test_inserts_bearings_bushings(self):
        for s in c.family("heat_insert").sizes():
            it = c.resolve({"family": "heat_insert", "size": s})
            _p, x, y, z = self.size(it)
            with self.subTest(insert=s):
                self.assertAlmostEqual(z, d(it, "length"), delta=0.05)
                self.assertAlmostEqual(max(x, y), d(it, "outer_d"), delta=0.01)
        for s in c.family("bearing").sizes():
            it = c.resolve({"family": "bearing", "size": s})
            p, x, y, z = self.size(it)
            with self.subTest(bearing=s):
                self.assertAlmostEqual(x, c.BEARINGS[s][1], delta=0.01)
                self.assertAlmostEqual(z, c.BEARINGS[s][2], delta=0.01)
                inner = min(f.radius for f in p.shape.faces() if f.geom_type.name == "CYLINDER")
                self.assertAlmostEqual(2 * inner, c.BEARINGS[s][0], delta=0.01)
        for s in c.family("lm_uu").sizes():
            it = c.resolve({"family": "lm_uu", "size": s})
            _p, x, y, z = self.size(it)
            with self.subTest(lm=s):
                self.assertAlmostEqual(x, d(it, "outer_d"), delta=0.01)
                self.assertAlmostEqual(z, d(it, "length"), delta=0.01)

    def test_motion_and_frame(self):
        for s in c.family("dowel").sizes():
            it = c.resolve({"family": "dowel", "size": s})
            _p, x, y, z = self.size(it)
            with self.subTest(dowel=s):
                self.assertAlmostEqual(x, float(s), delta=0.01)
                self.assertAlmostEqual(z, it["length"], delta=0.01)
        for s in c.family("shaft_collar").sizes():
            it = c.resolve({"family": "shaft_collar", "size": s})
            _p, x, y, z = self.size(it)
            with self.subTest(collar=s):
                self.assertAlmostEqual(x, d(it, "outer_d"), delta=0.01)
                self.assertAlmostEqual(z, d(it, "width"), delta=0.01)
        for s in c.family("linear_rod").sizes():
            it = c.resolve({"family": "linear_rod", "size": s, "length": 250})
            _p, x, y, z = self.size(it)
            self.assertAlmostEqual(x, float(s), delta=0.01)
            self.assertAlmostEqual(z, 250.0, delta=0.01)
        for s in c.family("nema").sizes():
            it = c.resolve({"family": "nema", "size": s})
            _p, x, y, z = self.size(it)
            self.assertAlmostEqual(x, c.NEMA[s][0], delta=0.01)
            self.assertAlmostEqual(z, it["body_length"] + c.NEMA[s][4] + it["shaft_length"], delta=0.01)
        for s, (a, b) in c.VSLOTS.items():
            _p, x, y, z = self.size(c.resolve({"family": "extrusion", "size": s, "length": 100}))
            self.assertAlmostEqual(min(x, y), min(a, b), delta=0.05)
            self.assertAlmostEqual(max(x, y), max(a, b), delta=0.05)
            self.assertAlmostEqual(z, 100, delta=0.01)
        _p, x, y, z = self.size(c.resolve({"family": "tnut", "size": "M5"}))
        self.assertAlmostEqual(x, 10, delta=0.01)
        self.assertAlmostEqual(y, 5.9, delta=0.01)
        for s in c.family("gt2_pulley").sizes():
            it = c.resolve({"family": "gt2_pulley", "size": s})
            p, x, y, z = self.size(it)
            band = max(f.radius for f in p.shape.faces() if f.geom_type.name == "CYLINDER" and abs(f.radius - d(it, "outer_d") / 2) < 0.01)
            self.assertAlmostEqual(2 * band, d(it, "outer_d"), delta=0.01)
        m = c.resolve({"family": "magnet", "d": 8, "h": 3})
        p, x, y, z = self.size(m)
        self.assertAlmostEqual(x, 8, delta=0.01)
        self.assertAlmostEqual(z, 3, delta=0.01)
        self.assertAlmostEqual(c.mass(m, float(p.shape.volume))["grams"], math.pi * 16 * 3 * 7.6e-3, delta=1e-3)

    def test_orings(self):
        for s in c.family("oring").sizes()[::7]:
            it = c.resolve({"family": "oring", "size": s})
            _p, x, y, z = self.size(it)
            with self.subTest(oring=s):
                self.assertAlmostEqual(x, d(it, "inner_d") + 2 * d(it, "section"), delta=0.01)
                self.assertAlmostEqual(z, d(it, "section"), delta=0.01)

    def test_threads_are_cosmetic_and_said_so(self):
        p = c.build(c.resolve({"family": "iso4762", "size": "M6", "length": 20}))
        self.assertFalse(any(f.geom_type.name == "BSPLINE" for f in p.shape.faces()))    # no helix
        self.assertIn("cosmetic", c.describe({"family": "iso4762", "size": "M6", "length": 20})["thread"])

    def test_mass_evidence(self):
        b = c.resolve({"family": "bearing", "size": "608"})
        self.assertEqual(c.mass(b, 1.0)["evidence"], "specified")             # SKF catalogue: 12 g
        self.assertAlmostEqual(c.mass(b, 1.0)["grams"], 12.0)
        s = c.resolve({"family": "iso4762", "size": "M3", "length": 10, "grade": "A2-70"})
        m = c.mass(s, 100.0)
        self.assertEqual((m["evidence"], m["grams"]), ("computed", 0.8))        # 100 mm³ × 8000 kg/m³ (304)
        self.assertIsNone(c.mass(c.resolve({"family": "oring", "size": "010"}), 50.0)["grams"])


if __name__ == "__main__":
    unittest.main()
