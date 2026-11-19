"""Assemblies: contract, geometry checks (interference, clearance, motion, tool access), view payload, maker documents.

Real kernel (build123d) and a temp data folder. The direct tests build tiny solids in this process; the studio tests
run the worker and the pipeline end to end.
"""
import csv
import io
import math
import json
import os
import tempfile
import unittest
import zipfile

TMP = tempfile.mkdtemp(prefix="form-asm-")

from build123d import Align, Box, Pos  # noqa: E402

from form import assembly as asm, config  # noqa: E402
from form.design_guide import EXAMPLE  # noqa: E402
from form.recipes.base import Access, Assembly, Feature, Hardware, Param, Part, Recipe, hinge, slide  # noqa: E402
from form.studio import Studio  # noqa: E402
from printing_cfg import with_printing  # noqa: E402

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Two(Recipe):
    """A 20 mm block and a 10 mm cube printed beside it; the cube is placed on (or into) the block."""
    solids = 2
    params = [Param("sink", "Sink", 0, -5, 5, 0.1)]
    features = [Feature("f", "F", "structure")]

    def __init__(self, spec):
        self.spec_ = spec

    def assembly(self, v):
        return self.spec_


def model(spec, sink=0.0):
    shape = Box(20, 20, 20, align=A) + Pos(40, 0, 0) * Box(10, 10, 10, align=A)
    return {"recipe": Two(spec), "values": {"sink": sink}, "shape": shape, "faces": []}


def on_top(z=20, **kw):
    return Part("cube", "Cube", 1, move=(-40, 0, z), explode=(0, 0, 15), **kw)


class Contract(unittest.TestCase):
    def test_default_is_none_and_validate_names_problems(self):
        self.assertIsNone(Recipe().assembly({}))
        bad = Assembly(parts=[Part("a", "A", 0), Part("a", "B", 5)], joints=[hinge("zz", (0, 0, 0), (0, 0, 0), (0, 90))],
                       hardware=[Hardware("screw", after="nope")])
        msg = " ".join(bad.validate(2))
        for word in ("unique", "solid 5", "unknown part", "axis is zero", "fitted after unknown"):
            self.assertIn(word, msg)
        self.assertEqual(slide("p", (1, 0, 0), (0, 10)).kind, "slide")

    def test_invalid_assembly_becomes_a_failed_check_not_a_crash(self):
        rows = asm.analyse(model(Assembly(parts=[Part("x", "X", 7)])))
        self.assertEqual([(r["id"], r["status"]) for r in rows], [("asm_valid", "FAIL")])

    def test_no_assembly_no_checks(self):
        self.assertEqual(asm.analyse(model(None)), [])


class GeometryChecks(unittest.TestCase):
    def test_resting_parts_pass_and_sunk_parts_fail_with_a_marker(self):
        ok = asm.analyse(model(Assembly(parts=[Part("block", "Block", 0), on_top()])))
        by = {r["id"]: r for r in ok}
        self.assertEqual(by["asm_interference"]["status"], "PASS")
        self.assertEqual(by["asm_clearance"]["value"], "contact only")
        bad = {r["id"]: r for r in asm.analyse(model(Assembly(parts=[Part("block", "Block", 0), on_top(z=17)])))}
        r = bad["asm_interference"]
        self.assertEqual((r["status"], r["evidence"], r["frame"]), ("FAIL", "computed", "assembled"))
        self.assertAlmostEqual(float(r["value"].split()[0]), 300.0, delta=0.5)          # 10 x 10 x 3 mm overlap
        self.assertAlmostEqual(r["at"][2], 17, places=3)
        self.assertAlmostEqual(r["to"][2], 20, places=3)

    def test_small_gap_warns(self):
        r = {x["id"]: x for x in asm.analyse(model(Assembly(parts=[Part("block", "Block", 0), on_top(z=20.05)])))}
        self.assertEqual(r["asm_clearance"]["status"], "WARN")
        self.assertIn("0.05", r["asm_clearance"]["value"])

    def test_motion_sweep_reports_worst_angle_and_its_limits(self):
        # the cube sits beside the block, 1 mm away, and swings about the block's top edge into it
        spec = Assembly(parts=[Part("block", "Block", 0), Part("cube", "Cube", 1, move=(-24, 0, 0))],
                        joints=[hinge("cube", (0, 1, 0), (10, 0, 20), (0, 90), samples=10, label="Swing")])
        r = next(x for x in asm.analyse(model(spec)) if x["id"].startswith("asm_motion"))
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("(10 declared, ", r["detail"])
        self.assertIn("does not prove continuous freedom", r["detail"])
        self.assertEqual(r["pose"]["joint"], "cube_hinge")
        self.assertGreaterEqual(len(r["samples"]), 10)
        self.assertEqual(r["samples"][0]["state"], "clear")                         # assembled position is clear
        self.assertGreater(r["samples"][0]["clearance_mm"], 0.9)                     # 1 mm gap at rest
        # the cube's inner face (1 mm out from the pivot line, 10..20 mm below it) first reaches the block where
        # cos θ = 20 sin θ - sin² θ ... i.e. sin θ = 1/20: 2.87°
        self.assertAlmostEqual(r["first_contact"], math.degrees(math.asin(1 / 20)), delta=0.6)
        self.assertGreater(float(r["value"].split()[0]), 1)                          # overlap volume on the B-rep, mm³
        free = Assembly(parts=spec.parts, joints=[slide("cube", (1, 0, 0), (0, 30), samples=4, label="Pull")])
        r2 = next(x for x in asm.analyse(model(free)) if x["id"].startswith("asm_motion"))
        self.assertEqual(r2["status"], "PASS")

    def test_tool_access_respects_assembly_order(self):
        # a screw on top of the block, driven down; the cube sits right over it
        screw = Hardware("Screw", "M3", 1, access=(Access(at=(0, 0, 20), axis=(0, 0, -1), tool_d=6, length=50),))
        parts = [Part("block", "Block", 0), on_top()]
        blocked = [x for x in asm.analyse(model(Assembly(parts=parts, hardware=[screw]))) if x["id"].startswith("asm_access")]
        self.assertEqual((blocked[0]["status"], blocked[0]["value"]), ("FAIL", "blocked by Cube"))
        early = Hardware("Screw", "M3", 1, after="block", access=screw.access)
        clear = [x for x in asm.analyse(model(Assembly(parts=parts, hardware=[early]))) if x["id"].startswith("asm_access")]
        self.assertEqual(clear[0]["status"], "PASS")


def three(spec):
    """A 20 mm block, a 10 mm cube and a 4 mm tip printed in a row."""
    shape = Box(20, 20, 20, align=A) + Pos(40, 0, 0) * Box(10, 10, 10, align=A) + Pos(70, 0, 0) * Box(4, 4, 4, align=A)
    return {"recipe": Two(spec), "values": {"sink": 0}, "shape": shape, "faces": []}


class Chains(unittest.TestCase):
    """The cube slides toward the block; the tip, attached to the cube's front face, gets there first."""

    def spec(self, attach="arm", hi=17.0, budget=None):
        return Assembly(parts=[Part("block", "Block", 0), Part("arm", "Arm", 1, move=(-5, 0, 0)),      # x 30..40
                               Part("tip", "Tip", 2, move=(-42, 0, 0), attach=attach)],               # x 26..30, on its front
                        joints=[slide("arm", (-1, 0, 0), (0, hi), samples=5, label="Push")], budget_s=budget)

    def motion(self, rows):
        return next(x for x in rows if x["id"].startswith("asm_motion"))

    def test_a_part_attached_to_a_moving_part_moves_and_collides_with_it(self):
        r = self.motion(asm.analyse(three(self.spec())))
        self.assertEqual(r["status"], "FAIL", r["detail"])
        self.assertIn("Tip hits Block", r["detail"])
        self.assertIn("carrying Tip", r["detail"])
        self.assertEqual(r["moves"], ["arm", "tip"])
        self.assertAlmostEqual(r["first_contact"], 16.0, delta=0.2)                   # tip front 26 -> block face 10
        self.assertGreater(r["pose"]["value"], 16.0)
        # not attached, the tip stays put and the arm drives into it at once: the false collision a chain avoids
        loose = self.motion(asm.analyse(three(self.spec(attach=""))))
        self.assertEqual(loose["status"], "FAIL")
        self.assertIn("Arm hits Tip", loose["detail"])
        self.assertNotIn("carrying", loose["detail"])
        self.assertLess(loose["first_contact"], 0.5)

    def test_a_proven_free_slide_says_so(self):
        r = self.motion(asm.analyse(three(self.spec(hi=12.0))))
        self.assertEqual(r["status"], "PASS", r["detail"])
        self.assertIn("free over the whole range", r["detail"])
        self.assertEqual(r["unproven"], [])

    def test_a_tiny_budget_reports_partial_not_clear(self):
        rows = asm.analyse(three(self.spec(budget=1)), progress=None)
        b = {x["id"]: x for x in rows}["asm_budget"]
        self.assertIn(b["status"], ("PASS", "WARN"))
        rows = asm.analyse(three(self.spec()), budget_s=1e-6)            # the studio's budget, no design override
        by = {x["id"]: x for x in rows}
        self.assertEqual(by["asm_budget"]["status"], "WARN")
        self.assertTrue(by["asm_budget"]["partial"])
        self.assertEqual(by["asm_interference"]["status"], "WARN")
        self.assertIn("Not checked in the time budget", by["asm_interference"]["detail"])
        self.assertNotEqual(self.motion(rows)["status"], "PASS")

    def test_progress_is_reported(self):
        seen = []
        asm.analyse(three(self.spec()), progress=seen.append)
        phases = [x["phase"] for x in seen]
        self.assertIn("rest", phases)
        self.assertIn("joint", phases)
        self.assertEqual(phases[-1], "done")

    def test_joined_pairs_are_measured_not_booleaned(self):
        from form.recipes.base import Mate
        # the tip sunk 1 mm into the arm's front face, declared a press fit: no interference failure, a fit row instead
        spec = Assembly(parts=[Part("block", "Block", 0), Part("arm", "Arm", 1, move=(-5, 0, 0)),
                               Part("tip", "Tip", 2, move=(-41, 0, 0), attach="arm")],
                        mates=[Mate("tip", "arm", "press", label="Tip in the arm")])
        by = {x["id"]: x for x in asm.analyse(three(spec))}
        self.assertEqual(by["asm_interference"]["status"], "PASS")
        self.assertIn("joined by design", by["asm_interference"]["detail"])
        self.assertEqual(by["asm_fit_tip_arm"]["status"], "PASS")
        undeclared = {x["id"]: x for x in asm.analyse(three(Assembly(parts=spec.parts)))}
        self.assertEqual(undeclared["asm_interference"]["status"], "FAIL")
        self.assertAlmostEqual(float(undeclared["asm_interference"]["value"].split()[0]), 16.0, delta=0.1)   # 4 x 4 x 1


class StudioAssembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(with_printing(config.load()))

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def checks(self, p):
        return {c["id"]: c for c in self.st.read(p, "checks", self.st.keys(p)["checks"])["checks"]}

    def test_example_box_is_an_assembly(self):
        p = self.st.create_design("Asm box", EXAMPLE)
        self.assertEqual(self.st.run_sync(p["id"], ["geometry", "exports", "checks"])["state"], "done")
        c = self.checks(self.st.load(p["id"]))
        self.assertEqual(c["asm_interference"]["status"], "PASS")
        v = self.st.view(self.st.load(p["id"]))
        a = v["assembly"]
        self.assertEqual([x["id"] for x in a["parts"]], ["box", "lid"])
        self.assertTrue(all(m["part"] in ("box", "lid") for m in v["mesh"]))
        self.assertAlmostEqual(abs(a["parts"][1]["placement"]["q"][1]), 1.0, places=6)     # flipped about X
        self.assertLess(a["bbox"][1][0] - a["bbox"][0][0], v["bbox"][1][0] - v["bbox"][0][0])  # assembled is narrower

    def test_unusable_declarations_are_refused_with_the_reason(self):
        from form.studio import StudioError
        bad = EXAMPLE.replace('note="Press the lid on, plug first."', 'attach="nope", note="Press the lid on, plug first."')
        with self.assertRaises(StudioError) as e:
            self.st.create_design("Bad asm", bad)
        self.assertIn("attached to unknown part “nope”", str(e.exception))
        self.assertIn("assembly()", e.exception.hint)

    def test_single_part_designs_are_unchanged(self):
        p = self.st.create("Hook", "hook")
        v = self.st.view(p)
        self.assertNotIn("assembly", v)
        self.assertTrue(all("part" not in m for m in v["mesh"]))
        self.assertEqual(self.st.state(p["id"])["documents"], ["BOM.csv", "PRINT_REPORT.md", "MEASUREMENT_PLAN.md"])

    def test_hinged_box_release_writes_documents_and_bad_relief_fails_motion(self):
        p = self.st.create("Hinged", "hinged_box")
        job = self.st.run_sync(p["id"])                                 # the slice step is blocked where no slicer is installed
        self.assertIn(job["state"], ("done", "blocked"), job)
        sliced = any(s["node"] == "slice" and s["state"] == "done" for s in job["steps"])   # Design only drops the step
        p = self.st.load(p["id"])
        c = self.checks(p)
        for k in ("asm_interference", "asm_motion_lid_hinge", "asm_access_1", "asm_access_3"):
            self.assertEqual(c[k]["status"], "PASS", c[k])

        # working documents, without a slice: honest blanks
        bom = self.st.dir(p["id"])
        from form import maker_docs
        f = maker_docs.working(self.st, p, "BOM.csv")
        rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))))
        self.assertEqual([r["kind"] for r in rows], ["printed", "printed", "purchased", "purchased"])
        rep = maker_docs.working(self.st, p, "PRINT_REPORT.md").read_text(encoding="utf-8")
        if sliced:
            self.assertIn("simulated plate total", rows[0]["grams_evidence"])
            self.assertGreater(float(rows[0]["grams"]), 1)
        else:
            self.assertEqual(rows[0]["grams_evidence"], "not sliced")
            self.assertIn("| Slice and layer inspection | NOT RUN |", rep)
        self.assertIn("does not prove continuous freedom", rep)
        z = zipfile.ZipFile(maker_docs.working(self.st, p, "docs.zip"))
        self.assertIn("assembly-03.png", z.namelist())
        plan = maker_docs.working(self.st, p, "MEASUREMENT_PLAN.md").read_text(encoding="utf-8")
        self.assertIn("## To measure (3)", plan)                       # pin diameter is specified, the box size assumed
        self.assertTrue(bom.exists())

        # a release copies and hashes them (slice may be unavailable on CI: release only if the gate allows)
        g = self.st.gate(p)
        if g["ready"]:
            r = self.st.approve(p, [w["id"] for w in g["warnings"]])
            self.assertIn("ASSEMBLY.md", r["manifest"]["documents"])
            self.assertTrue(self.st.verify_release(self.st.load(p["id"]), r["release"])["intact"])
            self.assertIn("ASSEMBLY.md", zipfile.ZipFile(maker_docs.release_zip(self.st, p, r["release"])).namelist())
            every = zipfile.ZipFile(maker_docs.release_files_zip(self.st, p, r["release"])).namelist()
            for ext in (".step", ".stl", "MANIFEST.json", "REPORT.md", "ASSEMBLY.md"):            # the whole release, models too
                self.assertTrue(any(n.endswith(ext) for n in every), ext)

        self.st.commit(self.st.load(p["id"]), {"front_relief": 0.15}, "less relief")
        self.st.run_sync(p["id"], ["geometry", "exports", "checks"])
        m = self.checks(self.st.load(p["id"]))["asm_motion_lid_hinge"]
        self.assertEqual(m["status"], "FAIL")
        self.assertIn(m["pose"]["value"], [x["value"] for x in m["samples"]])        # the worst position checked
        self.assertLessEqual(m["first_contact"], 5.0)                                  # the old 5° sample already hit
        self.assertTrue(m["at"] and m["to"])
        self.assertIn("Check failed: Lid hinge moves freely", " ".join(self.st.gate(self.st.load(p["id"]))["reasons"]))


if __name__ == "__main__":
    unittest.main()
