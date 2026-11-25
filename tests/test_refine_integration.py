"""Design refinement wired into Form Studio (WP5): a plain Recipe is wrapped so refine features can follow it, the
opt-outs hold, recorded edits undo alone, frozen faces are compared on the B-rep, the analysis does not count fillets
or grip grooves against a design, geomdiff leaves the kernel's shapes alone, and the background job lands one
revision "Refined: N changes" whose changes undo one by one. Kernel tests use a real Studio in a temporary folder."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")
os.environ.setdefault("FORM_DATA", tempfile.mkdtemp(prefix="form-refine-int-"))   # another module's, when one set it
os.environ["FORM_REFINE_LOCAL"] = "1"          # never hand the job to an app that happens to be running

from form.refine import Patch, adapter, engine, jobs, parse_features  # noqa: E402
from form.refine.ledger import Ledger  # noqa: E402

RECIPE = '''"""A block with a bore. Plain Recipe."""
from build123d import Box, Cylinder, Pos
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title, summary = "Bored block", "A block with a bore."
    solids = 1
    params = [Param("w", "Width", 60, 30, 90, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure"), Feature("bore", "Bore", "interface")]

    def build(self, v):
        body = Box(v["w"], 40, 20)
        stages = [Stage("body", body)]
        body = body - Pos(0, 0, 0) * Cylinder(5, 30)
        stages.append(Stage("bore", body))
        return stages
'''

FEATURES = '''from build123d import Box, Cylinder
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title, summary = "Block", "A block with a bore."
    params = [Param("w", "Width", 60, 30, 90, 1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], 40, 20)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Cylinder(5, 30)
'''


class Adapter(unittest.TestCase):
    def test_wrap_keeps_the_declared_features_and_unwraps(self):
        w = adapter.wrap(RECIPE)
        self.assertIsNotNone(w)
        self.assertIn("class Design(FeatureDesign)", w)
        self.assertIn("def recipe_build(self, v)", w)
        self.assertIn("stages=True", w)
        f = parse_features(w)
        self.assertEqual(f["bore"]["role"], "interface")
        self.assertEqual(f["body"]["role"], "structure")
        self.assertNotIn("recipe_stages", f)
        self.assertEqual(adapter.unwrap(w), RECIPE)
        self.assertEqual(engine.kind_of(RECIPE)[0], "recipe")
        self.assertEqual(engine.kind_of(w)[0], "feature")
        self.assertEqual(engine.kind_of(FEATURES)[0], "feature")

    def test_what_is_not_wrapped(self):
        self.assertTrue(adapter.why_not("CAGES = []\nclass Design(Recipe):\n    def build(self, v): pass\n"))
        self.assertTrue(adapter.why_not(RECIPE.replace("    def build(self, v):", "    def make(self, v):")))
        self.assertTrue(adapter.why_not(RECIPE.replace("    solids = 1", "    solids = 1\n    mesh = True")))
        self.assertEqual(engine.kind_of("CAGES = []\n")[0], "cage")


class OptOuts(unittest.TestCase):
    def test_every_level(self):
        self.assertTrue(engine.enabled({}, FEATURES)[0])
        self.assertFalse(engine.enabled({}, FEATURES, "off")[0])
        self.assertFalse(engine.enabled({"refine": {"enabled": False}}, FEATURES)[0])
        self.assertFalse(engine.enabled({}, FEATURES.replace('    title, summary', '    refine = False\n    title, summary'))[0])
        old = os.environ.get("FORM_REFINE")
        os.environ["FORM_REFINE"] = "off"
        try:
            self.assertFalse(engine.enabled({}, FEATURES)[0])
        finally:
            if old is None:
                os.environ.pop("FORM_REFINE")
            else:
                os.environ["FORM_REFINE"] = old
        self.assertFalse(engine.enabled({}, "")[0])

    def test_game_assets_only_when_asked(self):
        # a game asset (purpose "game" or a cage source) is not refined unless asked; CAD designs are
        off = engine.enabled({}, FEATURES, None, True)
        self.assertFalse(off[0])
        self.assertIn("Refine game assets", off[1])
        self.assertFalse(engine.enabled({}, "CAGES = []\n")[0])                    # a cage source is a game asset
        self.assertFalse(engine.enabled({}, FEATURES, "auto", True)[0])
        self.assertTrue(engine.enabled({}, FEATURES, "on", True)[0])               # refine_design on / rerun
        self.assertTrue(engine.enabled({"refine": {"game": True}}, FEATURES, None, True)[0])   # Settings
        self.assertFalse(engine.enabled({"refine": {"game": True, "enabled": False}}, FEATURES, None, True)[0])
        self.assertTrue(engine.enabled({}, FEATURES, None, False)[0])              # CAD stays on
        from form import config
        self.assertIs(config.DEFAULTS["refine"]["game"], False)
        self.assertTrue(engine.is_game({"purpose": "game"}))
        self.assertFalse(engine.is_game({"purpose": "model"}, FEATURES))
        self.assertEqual(engine.asked({"refine": "on"}), "on")
        self.assertEqual(engine.asked({"refine": "on"}, "off"), "off")


class Edits(unittest.TestCase):
    def test_text_edit_undoes_alone(self):
        a = "x = 1\ndef appearance(self, v):\n    return [1]\ny = 2\n"
        b = "x = 1\ndef appearance(self, v):\n    return [1, 2]\ny = 2\n"
        e = engine.edit_record(a, b, "material")
        self.assertEqual(e["before"], "    return [1]")
        self.assertEqual(engine.undo_edit(b, e), a)
        with self.assertRaises(ValueError):
            engine.undo_edit(a, e)

    def test_cage_ops_undo_alone(self):
        from form.refine import ops_cage
        base = "CAGES = [CAGE_0]\n"
        one = ops_cage.with_refine_ops(base, [{"op": "crease", "edges": [[0, 1]], "value": 1.0}])
        two = ops_cage.with_refine_ops(one, ops_cage.refine_ops_of(one) + [{"op": "inset", "faces": {"region": "top"}}])
        e1 = engine.edit_record(base, one, "cage")
        e2 = engine.edit_record(one, two, "cage")
        self.assertEqual(len(e2["ops"]), 1)
        out = engine.undo_edit(two, e1)                 # the first one out, the second stays
        self.assertEqual(ops_cage.refine_ops_of(out), [{"op": "inset", "faces": {"region": "top"}}])


class Frozen(unittest.TestCase):
    def test_brep_faces_decide_over_the_tessellation(self):
        a = {"area": 100.0, "faces": 2, "lo": [0, 0, 0], "hi": [1, 1, 1],
             "brep": [["CYLINDER", 50.0, 0.0, 0.0, 5.0], ["PLANE", 50.0, 0.0, 0.0, 0.0]]}
        b = {**a, "area": 100.04, "lo": [0, 0, -0.004]}            # the mesh moved, the faces did not
        self.assertEqual(engine.frozen_moved(a, b), "")
        c = {**a, "brep": [["CYLINDER", 50.2, 0.0, 0.0, 5.0], ["PLANE", 50.0, 0.0, 0.0, 0.0]]}
        self.assertIn("area", engine.frozen_moved(a, c))
        d = {k: v for k, v in b.items() if k != "brep"}            # no B-rep list: the tessellation, at its tolerance
        self.assertEqual(engine.frozen_moved({k: v for k, v in a.items() if k != "brep"}, d), "")


class Analysis(unittest.TestCase):
    @staticmethod
    def mesh(shape):
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from form.kernel import _tessellate
        BRepMesh_IncrementalMesh(shape.wrapped, 0.1, False, 0.25, True)
        return _tessellate(shape, 0.1)

    def test_fillets_do_not_count_against_surface_breaks(self):
        from build123d import Axis, Box
        from form.refine import analyze
        b = Box(80, 50, 30)
        plain = analyze.surface_breaks(*self.mesh(b))
        rounded = analyze.surface_breaks(*self.mesh(b.fillet(8, b.edges().filter_by(Axis.Z))))
        self.assertLessEqual(rounded["deficit"], plain["deficit"])

    def test_grip_grooves_do_not_count_as_sharp_edges(self):
        import numpy as np
        from build123d import Box, Pos
        from form.refine import analyze
        body = Box(60, 40, 20)
        grooves = body
        for x in (-20, -10, 0, 10, 20):
            grooves = grooves - Pos(x, 0, 10) * Box(1.0, 50, 1.0)
        P, T = self.mesh(grooves)
        # triangles of the grooves (inside the groove slabs) are the texture feature
        c = P[T].mean(1)
        tf = np.where((c[:, 2] > 9.4) & (np.min(np.abs(c[:, 0][:, None] - np.array([-20, -10, 0, 10, 20])), 1) <= 0.6),
                      "grip_grooves", "body")
        plain = analyze.touch_points(P, T, None, tf, None)
        felt = analyze.touch_points(P, T, None, tf, {"grip_grooves"})
        self.assertLess(felt["share"], plain["share"])
        self.assertEqual(analyze.texture_features({"grip_grooves": {"label": "Grip grooves"}, "body": {}}),
                         {"grip_grooves"})


class GeomDiffCopies(unittest.TestCase):
    def test_the_kernel_shapes_are_not_touched(self):
        from build123d import Box, Pos
        from OCP.BRep import BRep_Tool
        from OCP.TopLoc import TopLoc_Location
        from form import geomdiff, kernel
        A, B = Box(20, 20, 20), Pos(5, 0, 0) * Box(20, 20, 20)
        shapes = {"a": A, "b": B}
        old = kernel._get
        kernel._get = lambda key, rid, values, tol: {"shape": shapes[key]}
        try:
            out = geomdiff.op_geomdiff("a", "r", {}, "b", "r", {})
        finally:
            kernel._get = old
        self.assertGreater(out["added"]["volume_mm3"], 0)
        for s in (A, B):                          # no triangulation written into the kernel's own shapes
            for f in s.faces():
                self.assertIsNone(BRep_Tool.Triangulation_s(f.wrapped, TopLoc_Location()))
        c = geomdiff.own_copy(A)
        self.assertFalse(c.wrapped.IsSame(A.wrapped))
        self.assertAlmostEqual(c.volume, A.volume, 6)


class StudioRefine(unittest.TestCase):
    """A real Studio: the job after a build, its record, the revision it lands, undo per change, a wrapped Recipe."""

    @classmethod
    def setUpClass(cls):
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_job_lands_one_revision_and_undoes_per_change(self):
        from form.refine import ops_cad
        st = self.st
        p = st.create_design("Block", FEATURES, brief="a desk block with a bore", purpose="model")
        pid = p["id"]
        jid = jobs.start(st, pid, ops=list(ops_cad.OPERATORS), budget_s=120, ledger=Ledger.memory())
        self.assertTrue(jid)
        rec = jobs.wait(st, pid, 300)
        self.assertEqual(rec["state"], "done", rec)
        p = st.load(pid)
        self.assertEqual(p["head"], 2, rec)
        last = p["revisions"][-1]
        self.assertEqual(last["origin"], "refine")
        self.assertTrue(last["note"].startswith("Refined: "))
        self.assertTrue(last.get("refine", {}).get("steps"))
        ids = [c["id"] for c in rec["changes"]]
        self.assertTrue(ids)
        src = st.source_text(p)
        self.assertTrue(all(i in parse_features(src) for i in ids if not i.startswith("refine_material")))
        # one change out, as a new revision; the bore is still the interface feature it was
        q = engine.undo(st, pid, ids[0])
        self.assertEqual(q["head"], 3)
        self.assertNotIn(ids[0], [c["id"] for c in engine.changes(st, q)])
        self.assertEqual(parse_features(st.source_text(q))["bore"]["role"], "interface")
        # the undo revision does not start a refinement of its own
        self.assertIsNone(jobs.after_design(st, pid, "refine"))

    def test_off_for_a_design(self):
        st = self.st
        p = st.create_design("Block", FEATURES, purpose="model")
        jobs.set_project(st, p["id"], "off")
        self.assertIsNone(jobs.start(st, p["id"]))
        self.assertEqual(jobs.status(st, p["id"])["state"], "off")
        self.assertEqual(st.load(p["id"])["head"], 1)

    def test_a_game_asset_waits_until_turned_on(self):
        st = self.st
        p = st.create_design("Block", FEATURES, purpose="game")
        self.assertIsNone(jobs.start(st, p["id"]))
        rec = jobs.status(st, p["id"])
        self.assertEqual(rec["state"], "off")
        self.assertFalse(rec["enabled"]["on"])
        self.assertIn("game assets", rec["why"])
        jobs.set_project(st, p["id"], "on")                    # refine_design(action="on")
        self.assertEqual(st.load(p["id"])["refine"], "on")
        self.assertTrue(jobs.status(st, p["id"])["enabled"]["on"])
        jobs.set_project(st, p["id"], "off")
        self.assertFalse(jobs.status(st, p["id"])["enabled"]["on"])

    def test_a_plain_recipe_is_wrapped_and_refined(self):
        from form.refine import ops_cad
        st = self.st
        p = st.create_design("Bored block", RECIPE, brief="a desk block with a bore", purpose="model")
        base = st.view(p)
        r = engine.refine(st, p["id"], ops=list(ops_cad.OPERATORS), budget_s=120, ledger=Ledger.memory())
        self.assertTrue(r.get("wrapped"), r)
        self.assertTrue(r.get("changed"), r.get("rejected"))
        q = st.load(p["id"])
        src = st.source_text(q)
        self.assertTrue(adapter.is_wrapped(src))
        self.assertEqual(parse_features(src)["bore"]["role"], "interface")
        v = st.view(q)
        self.assertEqual(v["signature"]["bore"]["brep"], base["signature"]["bore"]["brep"])   # the bore is untouched
        # every refine change out again: the plain Recipe comes back
        u = engine.undo(st, p["id"])
        self.assertEqual(st.source_text(u).strip(), RECIPE.strip())


if __name__ == "__main__":
    unittest.main()
