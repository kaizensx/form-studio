"""The boolean engine (form/craft/boolean.py), on the boolean failures of the owner's helmet conversation
(tests/fixtures/build_failures.py BOOLEAN): each is classified right, the error text carries measured facts and a hint
for that cause, a valid-looking wrong result is caught by the mesh oracle, and booleans that already worked still do,
at about the same speed."""
import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")

from form.craft._common import ok  # noqa: E402
from form.recipes import RecipeError  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_failures", ROOT / "tests" / "fixtures" / "build_failures.py")
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)

OLD_LADDER = "fuzzy fuse 1e-4: invalid result"


def _no_false_overlap_claim(test, text: str, facts: dict):
    if facts.get("overlaps"):
        test.assertNotIn("does not overlap", text)
        test.assertNotIn("do not overlap", text)


class Classification(unittest.TestCase):
    def test_each_fixture_gets_its_class(self):
        from form.craft import boolean
        for name, (op, make, kw, want) in bf.BOOLEAN.items():
            with self.subTest(name):
                a, b = make()
                d = boolean.diagnose(a, b, op, **kw)
                self.assertEqual(d["class"], want, (name, d))
                _no_false_overlap_claim(self, d["fact"] + " " + d["hint"], d["facts"])

    def test_measured_facts(self):
        from form.craft import boolean
        a, b = bf.coincident_band()
        d = boolean.diagnose(a, b, "fuse")
        self.assertTrue(d["facts"]["overlaps"])
        self.assertGreater(d["facts"]["overlap_mm3"], 50)                  # the band's root is sunk into the wall
        self.assertGreater(d["facts"]["coincident_mm2"], 1)                # the side faces the two bands share
        self.assertIn("mm³", d["fact"])
        a, b = bf.touching_halves()
        d = boolean.diagnose(a, b, "fuse", min_solids=2, max_solids=2)
        self.assertFalse(d["facts"]["overlaps"])
        self.assertLessEqual(d["facts"]["gap_mm"], 1e-6)
        self.assertGreater(d["facts"]["coincident_mm2"], 10)               # the split plane's ring
        a, b = bf.invalid_operand()
        d = boolean.diagnose(a, b, "cut")
        self.assertFalse(d["facts"]["valid_a"])
        self.assertIn("free edge", d["fact"])


class Engine(unittest.TestCase):
    def test_touching_halves_fail_fast_with_the_right_hint(self):
        from form import craft
        from form.craft import boolean
        a, b = bf.touching_halves()
        t = time.perf_counter()
        with self.assertRaises(boolean.BooleanError) as cm:
            craft.fuse(a, b, max_solids=2, min_solids=2)
        dt = time.perf_counter() - t
        e = cm.exception
        self.assertEqual(e.report["class"], "parts_touch")
        self.assertIn("touch", str(e))
        self.assertIn("Compound", e.hint)
        self.assertNotIn(OLD_LADDER, str(e))
        self.assertEqual(len(e.report["attempts"]), 1)                     # no blind ladder: the geometry says no
        self.assertLess(dt, 30)
        self.assertIsInstance(e, RecipeError)
        pub = e.public()
        self.assertEqual(pub["boolean"]["class"], "parts_touch")

    def test_grazing_cut_is_caught_and_repaired(self):
        from form import craft
        from form.craft import boolean
        body, tool = bf.grazing_cut()
        plain = bf._fresh(body) - bf._fresh(tool)
        lost = boolean._volume(body, True) - boolean._volume(plain, True)
        self.assertTrue(plain.is_valid)
        self.assertLess(lost, 50)                    # OCCT's own cut silently removes (almost) nothing
        craft.notes()
        out = craft.cut(body, tool)
        rep = boolean.last()
        self.assertEqual(rep["class"], "grazing")
        self.assertIn("wrong", rep["attempts"][0]["outcome"])              # the oracle refused the plain result
        removed = boolean._volume(body, True) - boolean._volume(out, True)
        self.assertGreater(removed, 1000)                                  # the 30 mm crown patch really went
        self.assertTrue(out.is_valid)
        self.assertTrue(any(n.startswith("cut:") for n in craft.notes()))

    def test_invalid_operand_names_the_culprit(self):
        from form import craft
        from form.craft import boolean
        a, b = bf.invalid_operand()
        with self.assertRaises(boolean.BooleanError) as cm:
            craft.cut(a, b)
        e = cm.exception
        self.assertEqual(e.report["class"], "invalid_operand")
        self.assertIn("not a valid solid", str(e))
        self.assertIn("culprit", e.hint)

    def test_coincident_band_builds_or_says_why(self):
        from form import craft
        from form.craft import boolean
        a, b = bf.coincident_band()
        try:
            out = craft.fuse(a, b)
        except boolean.BooleanError as e:
            self.assertEqual(e.report["class"], "coincident_faces")
            _no_false_overlap_claim(self, str(e) + " " + e.hint, e.report["facts"])
            return
        self.assertTrue(out.is_valid)
        self.assertEqual(len(out.solids()), 1)
        o = boolean.oracle(a, b, "fuse")
        o["op"] = "fuse"
        self.assertTrue(boolean._agrees(out, a, o)[0])

    def test_a_part_that_is_apart_says_so(self):
        from build123d import Box, Pos
        from form import craft
        from form.craft import boolean
        with self.assertRaises(boolean.BooleanError) as cm:
            craft.fuse(Box(10, 10, 1), Pos(13, 0, 0) * Box(10, 10, 1))
        self.assertEqual(cm.exception.report["class"], "apart")
        self.assertIn("3 mm apart", str(cm.exception))

    def test_mesh_fallback_only_when_asked_and_labelled(self):
        from form.craft import boolean
        body, tool = bf.grazing_cut()
        with self.assertRaises(boolean.BooleanError) as cm:                # no time for a rewrite: it says so
            boolean.run(body, tool, "cut", budget=1.0)
        self.assertIn("time bound", str(cm.exception))
        r = boolean.run(body, tool, "cut", budget=1.0, mesh_fallback=True)
        self.assertIn("mesh fallback", r.label)
        self.assertTrue(boolean.last().get("mesh_fallback"))

    def test_the_plain_boolean_counts_against_the_bound(self):
        """A plain boolean that alone uses the time bound is not followed by a pre-flight or rewrites."""
        from form.craft import boolean
        body, tool = bf.grazing_cut()
        t0 = time.perf_counter()
        with self.assertRaises(boolean.BooleanError) as cm:
            boolean.run(body, tool, "cut", budget=0.001)
        self.assertEqual(cm.exception.report["class"], "slow")
        self.assertIn("time bound", str(cm.exception))
        self.assertEqual(cm.exception.report["skipped"], ["pre-flight", "class rewrites"])
        plain = cm.exception.report["attempts"][0]["seconds"]
        self.assertLess(time.perf_counter() - t0, plain + 2.0)

    def test_a_feature_budget_caps_the_ladder(self):
        from form import featureprog
        from form.craft import boolean
        featureprog._DEADLINE.append(time.monotonic() + 3.0)
        try:
            body, tool = bf.grazing_cut()
            t0 = time.perf_counter()
            try:
                boolean.run(body, tool, "cut")
            except boolean.BooleanError as e:
                self.assertIn("time bound", str(e)) if e.report.get("skipped") else None
            # never far past the feature's budget: one OCCT call in flight cannot be stopped, and slow CI runners (x86-64
            # macOS) take a few seconds for it
            self.assertLessEqual(time.perf_counter() - t0, 3.0 + 4.0)
        finally:
            featureprog._DEADLINE.clear()


class Diagnosis(unittest.TestCase):
    def test_a_build_that_fails_in_the_engine_carries_its_measurements(self):
        """The recorded line 127: Stage("split", craft.fuse(back, face, min_solids=2, max_solids=2))."""
        from form import craft, kernel
        from form.recipes.base import Feature, Param, Recipe, Stage

        class Split(Recipe):
            title, summary = "Split fixture", "Two halves fused as if they were separate parts."
            params = [Param("h", "Height", 3.0, 1.0, 6.0, 0.1, "mm", "form", "base")]
            features = [Feature("shell", "Shell", "form"), Feature("split", "Split", "form")]

            def build(self, v):
                back, face = bf.touching_halves()
                stages = [Stage("shell", back)]
                stages.append(Stage("split", craft.fuse(back, face, min_solids=2, max_solids=2)))
                return stages

        r = Split()
        r.id = "bf:split"
        old = kernel.resolve
        kernel.resolve = lambda rid: r
        kernel._cache.clear()
        try:
            with self.assertRaises(RecipeError) as cm:
                kernel._build(r.id, r.defaults(), 0.2)
        finally:
            kernel.resolve = old
            kernel._cache.clear()
        pub = cm.exception.public()
        d = pub["diagnosis"]
        self.assertEqual(d["boolean"]["class"], "parts_touch")
        self.assertEqual(d["operation"], "fuse")
        self.assertTrue(any("overlap 0" in x for x in d["facts"]), d["facts"])
        self.assertIn("Compound", pub["hint"])
        self.assertNotIn("does not overlap", pub["hint"])
        self.assertIsInstance(d["line"], int)


class StillWorks(unittest.TestCase):
    """Booleans that succeeded before give the same solid, and the engine costs only a small margin over the old fast
    path (the plain boolean plus the validity check craft.fuse / craft.cut always ran on its result)."""

    CASES = None

    @classmethod
    def cases(cls):
        from build123d import Box, Cylinder, Pos, Sphere
        out = [("box - cylinder", "cut", lambda: (Box(20, 20, 10), Cylinder(3, 30))),
               ("box + box", "fuse", lambda: (Box(20, 20, 10), Pos(5, 0, 6) * Box(8, 8, 8))),
               ("box + touching box", "fuse", lambda: (Box(10, 10, 10), Pos(10, 0, 0) * Box(10, 10, 10))),
               ("box - half-overlapping box", "cut", lambda: (Box(20, 20, 10), Pos(0, 0, 5) * Box(5, 5, 4))),
               ("sphere - box", "cut", lambda: (Sphere(10), Pos(0, 0, 8) * Box(30, 30, 6))),
               ("box & sphere", "common", lambda: (Box(15, 15, 15), Sphere(10)))]
        _s, _t, _o, shell = bf.helmet_shell()
        out.append(("shell - box (free-form)", "cut", lambda: (bf._fresh(shell), Pos(0, 0, 30) * Box(20, 20, 30))))
        out.append(("shell + pad (free-form)", "fuse", lambda: (bf._fresh(shell), Pos(30, 0, 8) * Box(16, 12, 8))))
        return out

    def test_same_result_and_small_margin(self):
        from form.craft import boolean
        plain_t = eng_t = 0.0
        rows = []
        for name, op, make in self.cases():
            with self.subTest(name):
                tp = te = 0.0
                for _ in range(3):
                    a, b = make()
                    t = time.perf_counter()
                    p = a + b if op == "fuse" else a - b if op == "cut" else a & b
                    ok(p)
                    tp += time.perf_counter() - t
                    a, b = make()
                    t = time.perf_counter()
                    r = boolean.run(a, b, op)
                    te += time.perf_counter() - t
                    self.assertEqual(boolean.last()["class"], "ok", name)
                    self.assertEqual(len(r.solids()), len(p.solids()))
                    self.assertAlmostEqual(boolean._volume(r, True), boolean._volume(p, True),
                                           delta=1e-6 * boolean._volume(p, True) + 1e-6)
                rows.append((name, tp / 3, te / 3))
                plain_t += tp / 3
                eng_t += te / 3
        for name, tp, te in rows:
            print(f"  {name:30s} old {tp * 1000:8.1f} ms  engine {te * 1000:8.1f} ms")
        print(f"  total old fast path {plain_t:.3f} s, engine {eng_t:.3f} s (+{(eng_t / plain_t - 1) * 100:.0f} %)")
        self.assertLess(eng_t, plain_t * 1.25 + 0.02)                     # the pristine copies are the margin

    def test_a_chain_of_features_on_one_shell(self):
        """The way a design uses them: one body, feature after feature."""
        from build123d import Box, Cylinder, Pos, Rot
        from form.craft import boolean
        _s, _t, _o, shell = bf.helmet_shell()
        tools = [("cut", Pos(0, 0, 30) * Box(20, 20, 30)), ("fuse", Pos(30, 0, 8) * Box(16, 12, 8)),
                 ("cut", Pos(-20, 0, 15) * Rot(0, 90, 0) * Cylinder(4, 40)), ("fuse", Pos(-30, 0, 8) * Box(16, 12, 8)),
                 ("cut", Pos(0, 25, 10) * Rot(90, 0, 0) * Cylinder(5, 20))]

        def chain(engine):
            body = bf._fresh(shell)
            t = time.perf_counter()
            for op, tool in tools:
                tool = bf._fresh(tool)
                if engine:
                    body = boolean.run(body, tool, op)
                else:
                    body = body + tool if op == "fuse" else body - tool
                    ok(body)
            return body, time.perf_counter() - t
        runs = [chain(e) for e in (True, False, True, False)]           # alternate, keep the faster of each
        r, te = min((x for i, x in enumerate(runs) if i % 2 == 0), key=lambda x: x[1])
        p, tp = min((x for i, x in enumerate(runs) if i % 2 == 1), key=lambda x: x[1])
        print(f"  chain of {len(tools)}: old fast path {tp:.3f} s, engine {te:.3f} s (+{(te / tp - 1) * 100:.0f} %)")
        self.assertAlmostEqual(boolean._volume(r, True), boolean._volume(p, True), delta=1e-6 * boolean._volume(p))
        self.assertLess(te, tp * 1.25 + 0.05)


if __name__ == "__main__":
    unittest.main()
