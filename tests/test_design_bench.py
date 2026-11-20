"""The design bench (tests/design_bench): every exemplar builds in the kernel as a valid B-rep, has the features its
brief asks for, and clears the bar; the staged workflow triggers on exactly the complex briefs."""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("design_bench", HERE / "design_bench" / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


class DesignBench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {r["id"]: r for r in bench.run()}

    def test_about_twenty_briefs(self):
        self.assertGreaterEqual(len(bench.briefs()), 20)
        self.assertGreaterEqual(sum(1 for b in bench.briefs() if b.get("exemplar")), 12)

    def test_staging_triggers_on_complex_briefs_only(self):
        for r in self.res.values():
            self.assertEqual(r["points"]["staging"], 15, (r["id"], r["notes"]))

    def test_exemplars_build_and_clear_the_bar(self):
        for b in bench.briefs():
            if not b.get("exemplar"):
                continue
            r = self.res[b["id"]]
            self.assertEqual(r["points"]["builds"], 30, (b["id"], r["notes"]))
            self.assertEqual(r["points"]["features"], 25, (b["id"], r["notes"]))
            self.assertEqual(r["status"], "pass", (b["id"], r["total"], r["notes"]))

    def test_unsolved_briefs_are_reported_not_faked(self):
        r = self.res["mouse_shell"]
        self.assertEqual(r["status"], "no solution")
        self.assertEqual(r["total"], 15)


if __name__ == "__main__":
    unittest.main()
