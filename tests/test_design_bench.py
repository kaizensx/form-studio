"""The design bench (tests/design_bench): every exemplar builds in the kernel as a valid B-rep, has the features its
brief asks for, and clears the bar; the staged workflow triggers on exactly the complex briefs."""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:                                                    # the [parts] extra; CI runs without it
    import py_gearworks  # noqa: F401
    HAVE_GEARS = True
except ImportError:
    HAVE_GEARS = False
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
            self.assertEqual(r["points"]["staging"], bench.MAX["staging"], (r["id"], r["notes"]))

    def test_exemplars_build_and_clear_the_bar(self):
        for b in bench.briefs():
            if not (b.get("exemplar") or b.get("solution")):
                continue
            r = self.res[b["id"]]
            if r["status"].startswith("skipped"):                 # gears without the [parts] extra (CI)
                self.assertFalse(HAVE_GEARS, (b["id"], r["notes"]))
                self.assertIn("py_gearworks", " ".join(r["notes"]))
                continue
            self.assertEqual(r["points"]["builds"], bench.MAX["builds"], (b["id"], r["notes"]))
            self.assertEqual(r["points"]["features"], bench.MAX["features"], (b["id"], r["notes"]))
            self.assertEqual(r["status"], "pass", (b["id"], r["total"], r["notes"]))

    def test_evaluation_briefs_have_reference_solutions(self):
        ids = {b["id"] for b in bench.briefs() if b.get("solution")}
        self.assertGreaterEqual(len(ids), 8)
        for b in bench.briefs():
            if b.get("solution"):
                self.assertTrue((HERE / "design_bench" / "solutions" / f"{b['solution']}.py").is_file(), b["id"])

    def test_unsolved_briefs_are_reported_not_faked(self):
        r = self.res["phone_stand"]
        self.assertEqual(r["status"], "no solution")
        self.assertEqual(r["total"], bench.MAX["staging"])

    def test_product_classes_are_scored_on_their_silhouette(self):
        for bid in ("helmet", "eval_helmet", "mouse_shell", "eval_mouse"):
            r = self.res[bid]
            self.assertIn("silhouette", r["points"], bid)
            self.assertGreaterEqual(r["metrics"]["class"]["score"], bench.CLASS_BAR, (bid, r["notes"]))

    def test_the_old_blob_helmet_is_below_the_bar(self):
        """The helmet the first design evaluation produced (a dome with a visor strip) must not pass any more."""
        old = HERE / "design_bench" / "fixtures" / "blob_helmet.py"
        m = bench.check(bench._load(old), "bench-blob-helmet", "helmet_fullface")
        b = next(x for x in bench.briefs() if x["id"] == "eval_helmet")
        r = bench.score(b, m)
        self.assertLess(r["total"], bench.PASS, r["notes"])


class GameBenchWords(unittest.TestCase):
    """Who scored the game bench is said once, as an AI model and not a person."""
    def test_scored_once_by_an_ai_model(self):
        import json
        spec = importlib.util.spec_from_file_location("game_bench", HERE.parent / "scripts" / "game_bench.py")
        gb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gb)
        for name in ("game_scores.json", "game_scores_refine.json"):
            meta = json.loads((HERE / "design_bench" / name).read_text(encoding="utf-8"))
            line = gb.scored_line(meta)
            self.assertIn("by an AI model, not a person", line)
            self.assertEqual(line.lower().count("blind passes by"), 1, line)
            self.assertNotIn("subagent", line.lower())
        dup = {"scored_by": "three blind passes by an AI model, not a person", "date": "2026-11-25",
               "method": "Three blind passes by an AI model, not a person, on 2026-11-25. Each pass saw sheets."}
        self.assertEqual(gb.scored_line(dup), "- Scored by: three blind passes by an AI model, not a person "
                                               "(2026-11-25). Each pass saw sheets.")
        doc = (HERE.parent / "docs" / "GAME_BENCH.md").read_text(encoding="utf-8")
        self.assertNotIn("subagent", doc.lower())
        self.assertEqual(doc.count("blind passes by"), 1)


if __name__ == "__main__":
    unittest.main()
