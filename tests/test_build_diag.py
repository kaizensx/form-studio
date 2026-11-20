"""Build diagnosis (form/build_diag.py) and the craft.safe_* fallbacks, on the failure classes of one owner conversation
(tests/fixtures/build_failures.py): every failure names its feature, its line, a cause and a repair, and the
repairable ones build once the failing call is its craft.safe_* counterpart."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")

from form import build_diag, kernel  # noqa: E402
from form.recipes import RecipeError  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_failures", ROOT / "tests" / "fixtures" / "build_failures.py")
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


def build(name: str, safe: bool):
    bf.SAFE = safe
    r = bf.ALL[name]()
    r.id = f"bf:{name}"
    old = kernel.resolve
    kernel.resolve = lambda rid: r
    kernel._cache.clear()
    try:
        return kernel._build(r.id, r.defaults(), 0.2)
    finally:
        kernel.resolve = old
        kernel._cache.clear()
        bf.SAFE = False


class Diagnosis(unittest.TestCase):
    def test_every_recorded_failure_is_diagnosed(self):
        for name in bf.ALL:
            with self.subTest(name), self.assertRaises(RecipeError) as cm:
                build(name, False)
            pub = cm.exception.public()
            d = pub.get("diagnosis") or {}
            self.assertTrue(pub["feature"], (name, pub))                         # the failing stage
            self.assertIn(pub["feature"], {f.id for f in bf.ALL[name].features})
            self.assertTrue(d.get("fixes"), (name, pub))                         # at least one repair
            self.assertNotIn("BRep_API", pub["message"], name)                    # plain words lead, not OCCT text
            if d.get("operation") != "solid count":
                self.assertIsInstance(d.get("line"), int, name)
                self.assertIn(f"line {d['line']}", pub["message"])

    def test_causes_are_specific(self):
        def diag(name):
            with self.assertRaises(RecipeError) as cm:
                build(name, False)
            return cm.exception.public()
        f8 = diag("F8")
        self.assertEqual(f8["diagnosis"]["operation"], "fillet")
        self.assertIn("1.5 mm", " ".join(f8["diagnosis"]["fixes"]))             # half the 3 mm plate's shortest edge
        self.assertIn("safe_fillet", f8["hint"])
        f2 = diag("F2")
        self.assertIn("0.01 mm apart", f2["message"])
        self.assertIn("safe_union", " ".join(f2["diagnosis"]["fixes"]))
        f5 = diag("F5")
        self.assertIn("3 mm apart", f5["message"])
        f6 = diag("F6")
        self.assertEqual(f6["diagnosis"]["operation"], "loft")
        self.assertIn("6, 14 edges", f6["message"])
        f4 = diag("F4")
        self.assertEqual(f4["diagnosis"]["operation"], "solid count")
        self.assertEqual([s["solids"] for s in f4["diagnosis"]["stages"]], [1, 5, 5])

    def test_repairable_failures_build_through_safe_helpers(self):
        built = 0
        for name in bf.REPAIRABLE:
            with self.subTest(name):
                m = build(name, True)
                self.assertTrue(m["shape"].is_valid)
                self.assertEqual(len(m["shape"].solids()), 1)
                self.assertTrue(any(n.startswith("safe_") for n in m["craft_notes"]), (name, m["craft_notes"]))
                built += 1
        self.assertGreaterEqual(built, 5)

    def test_a_part_that_is_really_apart_is_not_forced_together(self):
        with self.assertRaises(RecipeError) as cm:
            build("F5", True)
        self.assertIn("3 mm apart", str(cm.exception))

    def test_python_errors_name_the_code(self):
        try:
            {}["wall"]
        except KeyError as e:
            d = build_diag.diagnose(e, None)
        self.assertEqual(d["operation"], "python")
        self.assertIn("KeyError", d["summary"])


class SafeHelpers(unittest.TestCase):
    def test_safe_cut_refuses_a_cut_that_removes_nothing_silently(self):
        from build123d import Box, Pos
        from form import craft
        body = Box(20, 20, 10)
        out = craft.safe_cut(body, Pos(0, 0, 5) * Box(5, 5, 4))
        self.assertAlmostEqual(out.volume, body.volume - 50, 3)

    def test_safe_loft_keeps_holes_honest(self):
        from build123d import Circle, Pos, Rectangle
        from form import craft
        ring = (Rectangle(20, 20) - Circle(3)).faces()[0]
        with self.assertRaises(RecipeError):
            craft.safe_loft([ring, Pos(0, 0, 10) * Circle(6).face()], ruled=True)    # a hole is never filled silently

    def test_safe_shell_and_inspect(self):
        from build123d import Box
        from form import craft
        b = Box(30, 20, 10)
        cup = craft.safe_shell(b, 2.0, craft.faces_at(b, "top"))
        self.assertLess(cup.volume, b.volume)
        info = craft.inspect(cup)
        self.assertTrue(info["valid"])
        self.assertEqual(info["solids"], 1)


if __name__ == "__main__":
    unittest.main()
