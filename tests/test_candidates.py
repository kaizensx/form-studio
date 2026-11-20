"""The kernel pool runs builds in parallel; build_candidates scores and keeps the best; propose_concepts keeps the
concepts that built and diagnoses the others."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")
TMP = tempfile.mkdtemp(prefix="form-candidates-")
os.environ["FORM_DATA"] = TMP

from form import candidates, concepts, config  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402
from form.worker import KernelPool, default_workers  # noqa: E402

PLATE = '''
from build123d import Align, Box, Cylinder, Pos
from form import craft
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title, summary = "Plate", "A plate with a hole."
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "plate"),
              Param("r", "Corner radius", 3, 0.5, 6, 0.5, "mm", "form", "plate")]
    features = [Feature("plate", "Plate", "form"), Feature("hole", "Hole", "interface")]

    def build(self, v):
        p = Box(v["w"], 30, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
        p = craft.safe_fillet(p, p.edges().filter_by(lambda e: abs(e.tangent_at(0).Z) > 0.9), v["r"])
        return [Stage("plate", p), Stage("hole", p - Cylinder(3, 20))]
'''
BROKEN = PLATE.replace('return [Stage("plate", p), Stage("hole", p - Cylinder(3, 20))]',
                       'return [Stage("plate", p), Stage("hole", p.fillet(9.0, p.edges()))]')


class Pool(unittest.TestCase):
    def test_default_size_and_affinity(self):
        self.assertGreaterEqual(default_workers({}), 1)
        self.assertEqual(default_workers({"kernel": {"workers": 3}}), 3)
        pool = KernelPool(size=2)
        try:
            self.assertEqual(pool.warm(), 2)
            first = pool._pick("a")                  # a call for key "a" lands on a worker...
            other = pool._pick(None)                 # ...while it is busy another call takes the other worker
            self.assertNotEqual(first, other)
            pool._done(first)
            pool._done(other)
            again = pool._pick("a")                  # the worker that built "a" gets it again
            pool._done(again)
            self.assertEqual(again, first)
            outs = pool.map("ping", [{}, {}, {}])
            self.assertTrue(all(isinstance(o, dict) for o in outs))
            self.assertEqual(pool.status()["started"], 2)
        finally:
            pool.stop()


class Candidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        shutil.rmtree(TMP, ignore_errors=True)

    def test_best_candidate_is_kept_and_a_failure_does_not_sink_the_others(self):
        r = candidates.run(self.st, [{"label": "plate", "source": PLATE},
                                     {"label": "wide", "values": {"w": 70}},
                                     {"label": "broken", "source": BROKEN}],
                           name="Candidate plate", targets={"size_mm": [70, 30, 5], "tolerance_mm": 1})
        rank = {x["label"]: x for x in r["ranking"]}
        self.assertEqual(r["best"], "wide")                       # it matches the target size
        self.assertFalse(rank["broken"]["ok"])
        self.assertEqual(rank["broken"]["diagnosis"]["operation"], "fillet")
        self.assertEqual(rank["plate"]["parts"]["editable"], 1.0)
        self.assertLess(rank["plate"]["parts"]["brief"], 1.0)
        p = self.st.load(r["project"])
        self.assertEqual(self.st.rev(p)["values"]["w"], 70)

    def test_four_candidates_build_in_parallel(self):
        pool = self.st.kernel
        pool.warm()
        srcs = [PLATE + f"\n# variant {i}\n" for i in range(5)]
        t = time.time()
        candidates.run(self.st, [{"label": "one", "source": srcs[0]}], keep="none", sweep=False)
        one = time.time() - t
        t = time.time()
        r = candidates.run(self.st, [{"label": f"c{i}", "source": s} for i, s in enumerate(srcs[1:])], keep="none",
                           sweep=False)
        four = time.time() - t
        self.assertEqual(r["built"], 4)
        if pool.size >= 4:                                         # on a busy CI runner give it room; 1.5x on a Mac
            self.assertLess(four, 3.0 * one + 2.0, (one, four))

    def test_all_failing_raises_with_the_ranking(self):
        with self.assertRaises(StudioError) as cm:
            candidates.run(self.st, [{"label": "a", "source": BROKEN}, {"label": "b", "source": BROKEN + "\n#b\n"}],
                           keep="none", sweep=False)
        self.assertEqual(len(cm.exception.extra["ranking"]), 2)


class Concepts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_one_failing_concept_returns_the_others(self):
        r = concepts.create(self.st, "Bracket idea", [
            {"title": "Flat", "rationale": "simplest", "source": PLATE},
            {"title": "Broken", "rationale": "fillet too big", "source": BROKEN},
            {"title": "Wide", "rationale": "more area", "source": PLATE + "\n# wide\n", "values": {"w": 60}}])
        self.assertEqual(len(r["members"]), 2)
        self.assertEqual([f["title"] for f in r["failed"]], ["Broken"])
        self.assertIn("diagnosis", r["failed"][0]["error"])
        self.assertIn("propose_concepts(group=", r["next"])


if __name__ == "__main__":
    unittest.main()
