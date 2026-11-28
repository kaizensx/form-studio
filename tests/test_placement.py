"""Standard parts placed on a design (form/placement.py) and the parts list (form/bom.py), on the kernel.

Placing cuts the right hole: the hole the snap finds afterwards has the ISO 273 diameter, and the material removed
equals the clearance hole plus the counterbore computed here by hand. The fit check passes for a part in its cut and
fails for one placed without it. The parts list groups by designation, carries mass with its evidence, takes
supplier numbers only from the person or a link, and leaves the catalogue service off."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = tempfile.mkdtemp(prefix="form-parts-")

from form import bom, catalog, config, engrave, placement as pl  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

from test_maker_tools import ARM, BLOCK  # noqa: E402


class Source(unittest.TestCase):
    def test_block_round_trips_next_to_text(self):
        q = {"id": "std_1", "spec": catalog.resolve({"family": "iso4762", "size": "M3", "length": 10}), "at": (0.0, 0.0, 10.0),
             "normal": (0.0, 0.0, 1.0), "depth": 10.0, "qty": 1, "cut": True, "snap": "face"}
        src = pl.join(BLOCK, [q])
        mk = engrave.mark("HI", (0, -15, 5), (0, -1, 0))
        mk["id"] = "text_1"
        src = engrave.join(src, [mk])
        self.assertEqual(pl.split(src)[1], [q])
        self.assertEqual(engrave.split(src)[1], [mk])
        self.assertEqual(pl.join(engrave.join(src, []), []).strip(), BLOCK.strip())

    def test_gaps_from_the_tables(self):
        g = {x["name"]: x for x in pl.gaps({"family": "iso4762", "size": "M3", "length": 10}, 10)}
        self.assertAlmostEqual(g["shank"]["per_side_mm"], (3.4 - 3.0) / 2)      # ISO 273 normal series
        self.assertLess(pl.gaps({"family": "heat_insert", "size": "M3"}, 10)[0]["per_side_mm"], 0)


class OnTheKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Block", BLOCK)["id"]

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def _vol(self, p):
        from form import massprops
        return massprops.geometry(self.st, p)["parts"][0]["volume_mm3"]

    def test_1_screw_cuts_its_hole_and_fits(self):
        st = self.st
        p = st.load(self.pid)
        v0 = self._vol(p)
        r = pl.place(st, p, {"family": "iso4762", "size": "M3", "grade": "A2-70"}, (15, 0, 10), expect_head=p["head"])
        self.assertEqual(r["snapped"]["kind"], "face")
        self.assertAlmostEqual(r["snapped"]["thickness"], 10.0, delta=0.01)
        self.assertEqual(r["placement"]["spec"]["length"], 10.0)        # shortest stock length through 10 mm + 1 d
        self.assertEqual(r["designation"], "ISO 4762 M3×10 A2-70")
        p = st.load(self.pid)
        # the material removed is the ISO 273 hole plus the counterbore (dk 5.68 + 0.3, k 3 + 0.2), by hand
        cb_r, cb_h, hole_r = (5.68 + 0.3) / 2, 3.2, 3.4 / 2
        want = math.pi * hole_r ** 2 * (10 - cb_h) + math.pi * cb_r ** 2 * cb_h
        self.assertAlmostEqual(v0 - self._vol(p), want, delta=0.05)
        hole = pl.snap(st, p, (15 + 1.7, 0, 3))
        self.assertEqual(hole["kind"], "hole")
        self.assertAlmostEqual(hole["hole_d"], 3.4, places=3)
        f = r["fit"]["rows"][0]
        self.assertEqual(f["status"], "PASS")
        self.assertLess(f["interference_mm3"], 1e-3)
        self.assertIn("std_1", [x.id for x in st.recipe(p).features])

    def test_2_insert_is_a_press_fit_and_bearing_clears(self):
        st = self.st
        p = st.load(self.pid)
        r = pl.place(st, p, {"family": "heat_insert", "size": "M3"}, (-15, 0, 10), expect_head=p["head"])
        row = r["fit"]["rows"][0]
        od, L, hole, _ = catalog.INSERTS["M3"]
        self.assertEqual((row["mate"], row["status"]), ("press", "PASS"))
        ring = math.pi / 4 * (od ** 2 - hole ** 2)                      # the plastic the insert displaces, per mm
        self.assertTrue(ring * (L - 0.4) <= row["interference_mm3"] <= ring * L, row)   # less the 0.4 mm lead-in
        p = st.load(self.pid)
        r = pl.place(st, p, {"family": "bearing", "size": "608"}, (0, 0, 10), expect_head=p["head"])
        self.assertEqual(r["fit"]["rows"][0]["status"], "PASS")

    def test_3_a_part_without_its_cut_fails_the_fit(self):
        st = self.st
        p = st.load(self.pid)
        r = pl.place(st, p, {"family": "iso4762", "size": "M3", "length": 6}, (22, 10, 10), cut=False, expect_head=p["head"])
        self.assertEqual(r["fit"]["rows"][0]["status"], "FAIL")
        self.assertGreater(r["fit"]["rows"][0]["interference_mm3"], 10)
        p = st.load(self.pid)
        pl.remove(st, p, r["placement"]["id"])

    def test_4_off_the_part_is_refused(self):
        st = self.st
        p = st.load(self.pid)
        with self.assertRaises(StudioError):
            pl.place(st, p, {"family": "iso4762", "size": "M3"}, (300, 0, 10))
        self.assertEqual(st.load(self.pid)["head"], p["head"])

    def test_5_parts_list(self):
        st = self.st
        p = st.load(self.pid)
        pl.place(st, p, {"family": "iso4762", "size": "M3", "grade": "A2-70"}, (-22, 10, 10), expect_head=p["head"])
        p = st.load(self.pid)
        b = bom.build(st, p, made=False)
        by = {g["designation"]: g for g in b["purchased"]}
        self.assertEqual(by["ISO 4762 M3×10 A2-70"]["quantity"], 2)          # grouped by designation
        self.assertEqual(by["Deep-groove ball bearing 608-2Z (8×22×7)"]["unit"]["evidence"], "specified")
        scr = by["ISO 4762 M3×10 A2-70"]["unit"]
        self.assertEqual(scr["evidence"], "computed")
        self.assertIn("8000", scr["source"])                                  # stainless 304's sourced density
        with self.assertRaises(StudioError):                                  # the agent needs a link the person gave
            bom.add_supplier(st, p, "ISO 4762 M3×10 A2-70", "Shop", "123", by="agent")
        bom.add_supplier(st, p, "ISO 4762 M3×10 A2-70", "Shop", "SHCS-M3-10-A2", by="person")
        b = bom.build(st, p, made=False)
        text = bom.csv_text(b)
        self.assertIn("ISO 4762 M3×10 A2-70", text)
        self.assertIn("SHCS-M3-10-A2", text)
        self.assertIn("the person", text)
        f = bom.pdf(st, p, b)
        self.assertEqual(f.read_bytes()[:4], b"%PDF")
        self.assertEqual(b["catalogue"]["state"], "off")
        on = dict(st.cfg, parts={"catalogue": True, "catalogue_provider": ""})
        self.assertEqual(bom.catalogue_search(on, "ISO 4762 M3×10")["state"], "no provider configured")

    def test_6_bench_entries(self):
        from form import studies
        st = self.st
        p = st.load(self.pid)
        ids = {e["id"]: e for e in studies.listing(st, p)["entries"]}
        self.assertEqual(ids["parts.standard"]["label"], "Standard parts")
        self.assertEqual(ids["doc.bom"]["label"], "Parts list")


class Assembled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Lid box", ARM)["id"]

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_placed_part_enters_the_assembly_as_purchased(self):
        st = self.st
        p = st.load(self.pid)
        pl.place(st, p, {"family": "magnet", "d": 6, "h": 2}, (0, 0, 10), expect_head=p["head"])
        p = st.load(self.pid)
        a = st.recipe(p).assembly(st.rev(p)["values"])
        names = [h.name for h in a.hardware]
        self.assertIn("NdFeB disc magnet Ø6×2 N42, axially magnetised", names)
        self.assertEqual(len(a.parts), 2)


if __name__ == "__main__":
    unittest.main()
