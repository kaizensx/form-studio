"""The verification suite of the strength solver: every textbook case within its stated tolerance.

Needs the FEA engine's Python (form.fea.python(): $FORM_FEA_PYTHON, an installed engine, or this Python with Netgen,
scikit-fem and PyAMG); skipped with the reason otherwise. The cases, their reference formulas and tolerances are in
form/fea/verify.py; docs/STRENGTH.md publishes the table (scripts/gen_strength_docs.py writes it from a run).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("FORM_DATA", tempfile.mkdtemp(prefix="form-fea-verify-"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import config, fea  # noqa: E402

ENGINE = fea.python(config.load())
CASES = ("cantilever", "plate_with_hole", "thick_cylinder", "self_weight", "bonded_bar", "preload_block",
         "nafems_le1", "nafems_le10",
         "modal_cantilever", "modal_free", "euler_column", "sharp_corner")


def engine(*args, timeout=900):
    r = subprocess.run([str(ENGINE), "-m", "form.fea.verify", *args], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(ROOT), env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=timeout)
    return r, (json.loads(r.stdout) if r.stdout.strip().startswith("{") else None)


@unittest.skipUnless(ENGINE, "the FEA engine is not installed here (set FORM_FEA_PYTHON to its Python)")
class Verification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc, cls.rep = engine("--json")

    def test_every_case_ran(self):
        self.assertIsNotNone(self.rep, self.proc.stderr[-1500:])
        self.assertEqual(tuple(c["case"] for c in self.rep["cases"]), CASES)

    def test_every_quantity_is_within_its_tolerance(self):
        for c in self.rep["cases"]:
            for r in c["rows"]:
                with self.subTest(case=c["case"], quantity=r["quantity"]):
                    self.assertTrue(r["pass"], f"expected {r['expected']}, got {r['got']}, error {r['error']:.4f} > {r['tolerance']}")
                    self.assertLessEqual(r["error"], r["tolerance"])
        self.assertTrue(self.rep["pass"])
        self.assertEqual(self.proc.returncode, 0)

    def test_every_case_converged_with_an_error_statement(self):
        key = {"static": "stress", "modal": "frequency", "buckling": "load_factor"}
        tol = {"static": 0.05, "modal": 0.01, "buckling": 0.02}
        for c in self.rep["cases"]:
            with self.subTest(case=c["case"]):
                self.assertTrue(c["converged"], c.get("not_converged_because"))
                self.assertGreaterEqual(c["levels"], 3)
                stated = c["stated_error"][key[c["kind"]]]
                self.assertIsNotNone(stated)
                self.assertLessEqual(stated, tol[c["kind"]])
                self.assertRegex(c["evidence"], r"^simulated \(FEA, [a-z ]+, converged to \d+\.\d %\)$")

    def test_the_stated_error_covers_the_real_one(self):
        """Where the reference is exact for the model (no beam-theory or chart approximation in it), the error
        against it is within the error the study states, or within 0.2 % where both are tiny."""
        exact = {"thick_cylinder": "peak von Mises stress (at the bore)", "bonded_bar": "elongation of two bonded solids",
                 "preload_block": "stress under a bolt preload"}
        for c in self.rep["cases"]:
            if c["case"] in exact:
                row = next(r for r in c["rows"] if r["quantity"] == exact[c["case"]])
                self.assertLessEqual(row["error"], max(c["stated_error"]["stress"], 0.002) * 1.25, c["case"])

    def test_the_solver_is_repeatable(self):
        _, again = engine("--json", "plate_with_hole")
        first = next(c for c in self.rep["cases"] if c["case"] == "plate_with_hole")
        self.assertEqual(again["cases"][0]["unknowns"], first["unknowns"])
        self.assertAlmostEqual(again["cases"][0]["rows"][0]["got"], first["rows"][0]["got"], places=6)

    def test_the_published_table_lists_every_case_quantity_and_tolerance(self):
        doc = (ROOT / "docs" / "STRENGTH.md").read_text(encoding="utf-8")
        table = doc[doc.index("<!-- verification:begin -->"):doc.index("<!-- verification:end -->")]
        for c in self.rep["cases"]:
            self.assertIn(c["title"], table)
            for r in c["rows"]:
                self.assertIn(f"| {r['quantity']} |", table)
                if not isinstance(r["expected"], bool):
                    self.assertIn(f"{100 * r['tolerance']:.1f} %", table)
        self.assertNotIn("FAIL", table)
        self.assertIn("all within tolerance", table)

    def test_a_typical_bracket_converges_in_under_a_minute(self):
        _, rep = engine("--bench")
        static = next(r for r in rep["rows"] if r["kind"] == "static")
        self.assertTrue(static["converged"])
        self.assertLess(static["seconds"], float(os.environ.get("FORM_FEA_BRACKET_S", 60)))
        for r in rep["rows"]:
            self.assertTrue(r["converged"], r)


class EngineFree(unittest.TestCase):
    """What can be checked without the engine: the cases the docs promise exist in the code."""

    def test_the_docs_name_the_cases_of_the_suite(self):
        src = (ROOT / "form" / "fea" / "verify.py").read_text(encoding="utf-8")
        doc = (ROOT / "docs" / "STRENGTH.md").read_text(encoding="utf-8")
        for cid in CASES:
            self.assertIn(f'"{cid}": {cid}', src)
        for word in ("Timoshenko", "Peterson", "Lamé", "Euler", "Kirsch", "Williams", "NAFEMS LE1", "NAFEMS LE10"):
            self.assertIn(word, doc)


if __name__ == "__main__":
    unittest.main()
