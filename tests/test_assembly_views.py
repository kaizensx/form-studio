"""Every multi-part design gets assembled and exploded views: the enclosure and the gear pair declare how they go
together; a design that builds several bodies and declares nothing gets a view-only assembly from its solids.

Real kernel, temp data folder (the enclosure and gear pair need the [parts] extra)."""
import importlib.util
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="form-asmv-")

from form import assembly as asm, config  # noqa: E402
from form.design_guide import EXAMPLE  # noqa: E402
from form.recipes.assembly import from_solids  # noqa: E402
from form.studio import Studio  # noqa: E402
from printing_cfg import with_printing  # noqa: E402
from test_assembly import model  # noqa: E402

PARTS = importlib.util.find_spec("py_gearworks") is not None and importlib.util.find_spec("bd_warehouse") is not None
NO_ASSEMBLY = EXAMPLE.split("    def assembly(self, v):")[0]          # the example box, without its declaration


class Derived(unittest.TestCase):
    def test_from_solids_pulls_parts_away_from_the_middle_never_down(self):
        a = from_solids([[[0, 0, 0], [20, 20, 20]], [[40, 0, 0], [50, 10, 10]]])
        self.assertTrue(a.derived)
        self.assertEqual([p.solid for p in a.parts], [0, 1])
        self.assertLess(a.parts[0].explode[0], 0)                     # left part goes left
        self.assertGreater(a.parts[1].explode[0], 0)                  # right part goes right
        self.assertTrue(all(p.explode[2] >= 0 for p in a.parts))      # nothing goes through the plate
        self.assertEqual(a.parts[1].move, (0.0, 0.0, 0.0))            # "assembled" is the design as modelled
        stacked = from_solids([[[0, 0, 0], [20, 20, 10]], [[0, 0, 10], [20, 20, 14]]])
        self.assertGreater(stacked.parts[1].explode[2], 0)            # the upper part lifts
        self.assertEqual(a.public()["derived"], True)

    def test_get_derives_when_undeclared_and_checks_nothing(self):
        m = model(None)
        a = asm.get(m)
        self.assertIsNotNone(a)
        self.assertTrue(a["spec"].derived)
        self.assertEqual(len(a["spec"].parts), 2)
        self.assertEqual(asm.analyse(model(None)), [])


class Studio_(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(with_printing(config.load()))

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def checks(self, p):
        return {c["id"]: c for c in self.st.read(p, "checks", self.st.keys(p)["checks"])["checks"]}

    def test_undeclared_multi_body_design_gets_views(self):
        p = self.st.create_design("Bodies", NO_ASSEMBLY)
        v = self.st.view(self.st.load(p["id"]))
        a = v["assembly"]
        self.assertTrue(a["derived"])
        self.assertEqual([x["id"] for x in a["parts"]], ["part1", "part2"])
        self.assertTrue(all(m["part"] in ("part1", "part2") for m in v["mesh"]))
        self.assertEqual(self.st.state(p["id"])["documents"], ["BOM.csv", "PRINT_REPORT.md", "MEASUREMENT_PLAN.md"])
        self.assertEqual(self.st.run_sync(p["id"], ["geometry", "exports", "checks"])["state"], "done")
        self.assertFalse(any(k.startswith("asm_") for k in self.checks(self.st.load(p["id"]))))

    @unittest.skipUnless(PARTS, "needs the [parts] extra")
    def test_enclosure_lid_seats_on_the_box(self):
        p = self.st.create("Enclosure", "enclosure")
        v = self.st.view(p)
        self.assertEqual([x["id"] for x in v["assembly"]["parts"]], ["box", "lid"])
        self.assertFalse(v["assembly"]["derived"])
        self.assertEqual(self.st.run_sync(p["id"], ["geometry", "exports", "checks"])["state"], "done")
        c = self.checks(self.st.load(p["id"]))
        self.assertEqual(c["asm_interference"]["status"], "PASS")
        self.assertEqual(c["asm_clearance"]["value"], "contact only")     # the lid rests on the walls
        self.assertIn("ASSEMBLY.md", self.st.state(p["id"])["documents"])

    @unittest.skipUnless(PARTS, "needs the [parts] extra")
    def test_gear_pair_gears_sit_on_their_axles_in_mesh(self):
        p = self.st.create("Gears", "gear_pair")
        v = self.st.view(p)
        self.assertEqual([x["id"] for x in v["assembly"]["parts"]], ["plate", "gear_a", "gear_b"])
        self.assertEqual(self.st.run_sync(p["id"], ["geometry", "exports", "checks"])["state"], "done")
        c = self.checks(self.st.load(p["id"]))
        self.assertEqual(c["asm_interference"]["status"], "PASS")
        self.assertLess(float(c["asm_clearance"]["value"].split()[0]), 0.5)    # teeth in mesh: a small backlash gap


if __name__ == "__main__":
    unittest.main()
