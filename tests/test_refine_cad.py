"""The CAD refinement operators (form/refine/ops_cad.py): the operator contract (names the styles weigh, no kernel
at import, preconditions, one method of code per patch), the kernel-side geometry on plain build123d solids (three
radius tiers, edges near frozen features left alone, a rounding never dropped after a failure, a groove that
follows the surface, part names kept), and one real refinement through the engine and the kernel."""
import ast
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FORM_SKIP_UI", "1")
TMP = tempfile.mkdtemp(prefix="form-refine-cad-")
os.environ["FORM_DATA"] = TMP

from form.refine import DEFICITS, Analysis, Design, ops_cad, styles  # noqa: E402

DEFICITS0 = {k: 0.5 for k in DEFICITS if k != "wear"}


def design(**kw):
    kw.setdefault("source", "")
    kw.setdefault("purpose", "model")
    return Design(**kw)


def analysis(**over):
    d = {**DEFICITS0, **{k: v for k, v in over.items() if k in DEFICITS}}
    return Analysis(deficits=d, measures=over.get("measures", {}), total=0.5)


def op(name):
    return next(o for o in ops_cad.OPERATORS if o.name == name)


class Contract(unittest.TestCase):
    def test_names_targets_and_styles(self):
        names = [o.name for o in ops_cad.OPERATORS]
        self.assertEqual(len(names), len(set(names)))
        weighed = set(styles.STYLES["clean_consumer"]["weights"])
        for n in ("fillet_hierarchy", "parting_line", "edge_break", "knurl_zone", "recessed_panel", "button_pads",
                  "rib_lightening"):
            self.assertIn(n, names)
            self.assertIn(n, weighed, f"{n} is a name the style tables weigh")
        for o in ops_cad.OPERATORS:
            self.assertEqual(o.domain, "cad")
            self.assertTrue(set(o.targets) <= set(DEFICITS), o.name)
            self.assertGreater(o.cost, 0)

    def test_module_imports_without_a_kernel(self):
        code = ("import sys; import form.refine.ops_cad, form.refine; form.refine.operators(); "
                "print(any(m.split('.')[0] in ('OCP', 'build123d') for m in sys.modules))")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.stdout.strip(), "False", r.stderr[-800:])

    def test_registered_with_the_engine(self):
        from form import refine
        got = {o.name for o in refine.operators("cad")}
        self.assertTrue({o.name for o in ops_cad.OPERATORS} <= got)

    def test_patches_are_one_method_with_the_frozen_boxes(self):
        d = design(brief="a handheld remote with a textured grip, injection moulded",
                   frozen_boxes={"bore": ((-4, -4, 0), (4, 4, 25))}, bbox=((-40, -25, 0), (40, 25, 30)))
        a = analysis(measures={"surface_breaks": {"largest_share": 0.5},
                               "edge_hierarchy": {"tiers": 0, "sharp_fraction": 0.2}})
        for o in ops_cad.OPERATORS:
            p = o.apply(d, a, styles.params("clean_consumer", o))
            tree = ast.parse(p.code)
            self.assertEqual(len(tree.body), 1, o.name)
            fn = tree.body[0]
            self.assertIsInstance(fn, ast.FunctionDef)
            self.assertEqual([x.arg for x in fn.args.args], ["self", "v", "body"])
            self.assertFalse(fn.decorator_list)
            self.assertIn("((-4.0, -4.0, 0.0), (4.0, 4.0, 25.0))", p.code)
            self.assertIn(f"ops_cad.{o.name}(body", p.code)
            self.assertTrue(p.reason)
            self.assertEqual(p.code, o.apply(d, a, styles.params("clean_consumer", o)).code, "deterministic")

    def test_style_parameters_reach_the_code(self):
        d = design()
        p = op("fillet_hierarchy").apply(d, analysis(), styles.params("rugged_tool", op("fillet_hierarchy")))
        self.assertIn("tiers=(0.6, 2.0, 6.0)", p.code)
        p = op("parting_line").apply(d, analysis(), {"width": 2.0, "depth": 0.1})
        self.assertIn("width=0.6, depth=0.3", p.code, "the groove stays a 0.4-0.6 mm shadow line")


class Preconditions(unittest.TestCase):
    def test_no_cad_operator_on_a_game_asset(self):
        for o in ops_cad.OPERATORS:
            self.assertFalse(o.check(design(purpose="game", brief="a knurled remote, moulded"), analysis())[0])

    def test_edge_break_follows_the_hierarchy(self):
        eb = op("edge_break")
        a = analysis(measures={"edge_hierarchy": {"tiers": 0, "sharp_fraction": 0.9}})
        ok, why = eb.check(design(), a)
        self.assertFalse(ok)
        self.assertIn("hierarchy", why)
        src = ("from form.featureprog import FeatureDesign, feature\nclass D(FeatureDesign):\n"
               "    @feature('Body')\n    def body(self, v, body):\n        return body\n"
               "    @feature('Fillet hierarchy', role='refine')\n    def refine_fillet_hierarchy(self, v, body):\n"
               "        return body\n")
        self.assertTrue(eb.check(Design.from_source(src), a)[0])
        self.assertFalse(op("fillet_hierarchy").check(Design.from_source(src), a)[0], "not twice")

    def test_context_operators_need_their_context(self):
        a = analysis(measures={"surface_breaks": {"largest_share": 0.6}})
        self.assertFalse(op("draft").check(design(brief="a shaft coupler"), a)[0])
        self.assertTrue(op("draft").check(design(brief="an injection moulded lid"), a)[0])
        self.assertFalse(op("knurl_zone").check(design(brief="a shaft coupler"), a)[0])
        self.assertTrue(op("knurl_zone").check(design(brief="a camera knob"), a)[0])
        self.assertTrue(op("knurl_zone").check(design(brief="a shell", product_class="bottle"), a)[0])
        src = ("from form.featureprog import FeatureDesign, feature\nclass D(FeatureDesign):\n"
               "    @feature('Body')\n    def body(self, v, body):\n        return body\n"
               "    @feature('Knurl')\n    def knurl(self, v, body):\n        return body\n")
        self.assertFalse(op("knurl_zone").check(Design.from_source(src, brief="a knob"), a)[0])
        self.assertFalse(op("button_pads").check(design(brief="a pillow block"), a)[0])
        self.assertTrue(op("button_pads").check(design(brief="a slim TV remote"), a)[0])
        self.assertTrue(op("parting_line").check(design(brief="a remote"), a)[0])
        self.assertFalse(op("parting_line").check(design(brief="a horn", style="organic"), a)[0])
        self.assertFalse(op("recessed_panel").check(design(), analysis(measures={"surface_breaks": {"largest_share": 0.1}}))[0])


class Kernel(unittest.TestCase):
    """The kernel-side functions on plain solids (build123d in this process)."""

    @classmethod
    def setUpClass(cls):
        from build123d import Align, Box, Cylinder, Pos
        cls.A = (Align.CENTER, Align.CENTER, Align.MIN)
        cls.block = (Box(80, 50, 30, align=cls.A) - Pos(0, 0, -1) * Cylinder(5, 40, align=cls.A)).solids()[0]
        cls.frozen = [((-5.0, -5.0, 0.0), (5.0, 5.0, 30.0))]

    def bore(self, s):
        return sorted(round(f.area, 3) for f in s.faces() if f.geom_type.name == "CYLINDER" and
                      abs(f.center().X) < 1e-6 and abs(f.center().Y) < 1e-6 and f.area > 900)

    def test_three_tiers_and_the_bore_untouched(self):
        from form.critique import radius_tiers
        from build123d import GeomType
        out = ops_cad.fillet_hierarchy(self.block, self.frozen, (0.4, 1.5, 5.0))
        radii = []
        for f in out.faces():
            if f.geom_type == GeomType.CYLINDER and abs(f.center().X) + abs(f.center().Y) > 1:
                from OCP.BRepAdaptor import BRepAdaptor_Surface
                radii.append(BRepAdaptor_Surface(f.wrapped).Cylinder().Radius())
        self.assertEqual(radius_tiers(radii), 3, sorted(set(round(r, 2) for r in radii)))
        self.assertEqual(self.bore(out), self.bore(self.block))
        sharp = ops_cad.sharp_edges(out)
        self.assertTrue(all(abs(math.hypot(e.position_at(0.5).X, e.position_at(0.5).Y) - 5) < 1e-6
                            for e, *_ in sharp), "only the frozen bore's edges stay sharp")

    def test_a_round_never_runs_on_into_a_frozen_slot(self):
        """OCCT carries a fillet along tangent edges: the ear's bottom edge joins the slot through the rounded
        vertical corners, so rounding it would also round the slot (a frozen split). The operator checks the faces
        inside the frozen boxes after every round and keeps only rounds that leave them alone."""
        from build123d import Axis, Box, Pos
        from form import craft
        ear = Box(40, 20, 12, align=self.A)
        ear = craft.safe_fillet(ear, ear.edges().filter_by(Axis.Z), 1.0)
        ear = (ear - Pos(5, 0, -1) * Box(32, 1.5, 14, align=self.A)).solids()[0]
        slot = [((-11.0, -0.75, 0.0), (20.0, 0.75, 12.0))]
        before = ops_cad.frozen_signature(ear, slot)
        self.assertTrue(before)
        out = ops_cad.fillet_hierarchy(ear, slot, (0.6, 2.0, 6.0))
        self.assertEqual(ops_cad.frozen_signature(out, slot), before)

    def test_tier_radii_scale_to_the_part(self):
        self.assertEqual(ops_cad.tier_radii((0.4, 1.5, 5.0), 100, 100), [0.4, 1.5, 5.0])
        small, mid, big = ops_cad.tier_radii((0.4, 1.5, 5.0), 10, 20)
        self.assertLessEqual(big, 2.4 + 1e-9)
        self.assertGreaterEqual(big / mid, ops_cad.TIER_RATIO - 0.01)
        self.assertGreaterEqual(small, ops_cad.R_FLOOR)

    def test_a_failed_radius_gets_a_smaller_one_not_none(self):
        from build123d import Box
        plate = Box(40, 30, 1.2).solids()[0]                      # 5 mm cannot round a 1.2 mm plate
        out = ops_cad.fillet_hierarchy(plate, (), (0.4, 1.5, 5.0))
        self.assertIsNot(out, plate)
        self.assertEqual(len(ops_cad.sharp_edges(out)), 0)

    def test_edge_break_rounds_what_is_left(self):
        out = ops_cad.edge_break(self.block, self.frozen, 0.3)
        self.assertEqual(len(ops_cad.sharp_edges(out, self.frozen)), 0)
        self.assertEqual(self.bore(out), self.bore(self.block))

    def test_the_exported_stl_of_a_rounded_corner_is_closed(self):
        """Where three rounds meet, OCCT's mesher leaves zero-area triangles (a, a, b) in the vertex blend: the mesh
        audit read the solid's STL as open and the final check took the rounds out. write_stl drops them."""
        import tempfile
        from pathlib import Path
        from form import kernel
        for out in (ops_cad.edge_break(self.block, self.frozen, 0.3),
                    ops_cad.edge_break(ops_cad.parting_line(self.block, self.frozen, 0.5, 0.4), self.frozen, 0.3)):
            f = Path(tempfile.mkdtemp()) / "r.stl"
            r = kernel.write_stl(out, f, 0.01, 0.1)
            self.assertEqual(r["open_edges"], 0, r)
            self.assertEqual(kernel._open_edges(f), 0)
            _rec, ids = kernel._stl_ids(f)
            self.assertFalse(((ids[:, 0] == ids[:, 1]) | (ids[:, 1] == ids[:, 2]) | (ids[:, 0] == ids[:, 2])).any())

    def test_drop_degenerate_keeps_every_real_triangle(self):
        import tempfile
        import numpy as np
        from pathlib import Path
        from form import kernel
        from form.craft import meshtex
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
        F = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2], [1, 1, 3]])      # a tetrahedron and a sliver
        f = Path(tempfile.mkdtemp()) / "t.stl"
        meshtex.write_stl(f, V, F)
        self.assertEqual(kernel.drop_degenerate(f), 1)
        self.assertEqual(len(kernel._stl_ids(f)[1]), 4)
        self.assertEqual(kernel._open_edges(f), 0)

    def test_edge_break_leaves_slivers_alone(self):
        """The guard: no break on an edge shorter than 3 r or along a face narrower than 2.2 r (a parting line's
        groove walls); the result is one valid solid."""
        grooved = ops_cad.parting_line(self.block, self.frozen, 0.5, 0.4)
        out = ops_cad.edge_break(grooved, self.frozen, 0.3)
        self.assertTrue(out.is_valid)
        self.assertEqual(len(out.solids()), 1)
        narrow = [x for x in ops_cad.sharp_edges(grooved, self.frozen) if x[4] / max(x[2], 1e-6) < 0.66]
        self.assertTrue(narrow)                                   # the groove walls are there to skip
        left = {ops_cad._pt(x[0]) for x in ops_cad.sharp_edges(out, self.frozen)}
        self.assertTrue(left)                                     # and they stayed sharp

    def test_nothing_to_do_returns_the_body(self):
        from build123d import Box
        b = Box(20, 20, 20).solids()[0]
        everything = [((-20.0, -20.0, -20.0), (20.0, 20.0, 20.0))]
        for fn in (ops_cad.fillet_hierarchy, ops_cad.edge_break, ops_cad.parting_line, ops_cad.recessed_panel,
                   ops_cad.knurl_zone):
            self.assertIs(fn(b, everything), b, fn.__name__)

    def test_parting_line_is_a_groove_not_a_shelf(self):
        out = ops_cad.parting_line(self.block, self.frozen, 0.5, 0.4)
        removed = self.block.volume - out.volume
        self.assertAlmostEqual(removed, 2 * (80 + 50) * 0.5 * 0.4, delta=1.0)
        self.assertEqual(self.bore(out), self.bore(self.block))
        band = [((-41.0, -26.0, 0.0), (41.0, 26.0, 30.0))]        # a frozen feature all round: no groove
        self.assertIs(ops_cad.parting_line(self.block, band), self.block)

    def test_knurl_band_on_a_cylinder(self):
        from build123d import Cylinder
        c = Cylinder(12, 40, align=self.A).solids()[0]
        out = ops_cad.knurl_zone(c, (), pitch=2.0, depth=0.5)
        self.assertGreater(len(out.faces()), 200)
        lo, hi = ops_cad._bb(out)
        self.assertLessEqual(hi[0], 12.0 + 1e-3, "the teeth stay inside the grip's diameter")

    def test_panel_pads_and_ribs(self):
        out = ops_cad.recessed_panel(self.block, self.frozen, 0.6)
        self.assertLess(out.volume, self.block.volume)
        self.assertEqual(self.bore(out), self.bore(self.block))
        from build123d import Box
        slab = Box(80, 50, 20, align=self.A).solids()[0]
        pads = ops_cad.button_pads(slab, (), 0.6, 3)
        self.assertAlmostEqual(ops_cad._bb(pads)[1][2], 20.6, places=3)
        ribs = ops_cad.rib_lightening(slab, (), pitch=10, t=1.6, skin=1.6)
        self.assertLess(ribs.volume, slab.volume)
        self.assertGreaterEqual(ribs.volume, 0.7 * slab.volume - 1e-6, "at most 30 % taken")

    def test_parts_keep_their_names(self):
        from build123d import Box, Pos
        from form import craft
        p = craft.parts(lid=Box(20, 20, 6, align=self.A), base=Pos(40, 0, 0) * Box(20, 20, 10, align=self.A))
        out = ops_cad.fillet_hierarchy(p, ())
        self.assertEqual(out.part_names, ["lid", "base"])
        self.assertEqual(len(out.solids()), 2)
        self.assertLess(out.volume, p.volume)


class Engine(unittest.TestCase):
    """One real refinement: the kernel builds the candidates, the engine keeps what passes its gates."""
    SRC = '''
from build123d import Align, Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(FeatureDesign):
    title, summary = "Block", "A block with a bore."
    params = [Param("w", "Width", 70, 40, 120, 1, "mm", "form", "body")]

    @feature("Body", role="structure")
    def body(self, v, body):
        return Box(v["w"], 44, 26, align=A)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Pos(0, 0, -1) * Cylinder(6, 40, align=A)
'''

    @classmethod
    def setUpClass(cls):
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_refine_keeps_the_hierarchy_and_the_interface(self):
        from form.refine import engine
        from form.refine.ledger import Ledger
        p = self.st.create_design("Block", self.SRC, brief="a desk block", purpose="model")
        r = engine.refine(self.st, p["id"], ops=list(ops_cad.OPERATORS), ledger=Ledger.memory(), budget_s=60)
        self.assertTrue(r["changed"], r.get("rounds"))
        ops = [a["operator"] for a in r["applied"]]
        self.assertEqual(ops[0], "fillet_hierarchy", r.get("rounds"))
        self.assertLess(r["final"]["total"], r["base"]["total"])
        q = self.st.load(p["id"])
        self.assertEqual(q["head"], 2)
        src = self.st.source_text(q)
        self.assertIn('role=\'refine\'', src.replace('"', "'"))
        d, ev, _ = engine.prepare(self.st, p["id"])
        b, n = ev.evaluate([self.st.source_text(q, 1), src])
        self.assertEqual(b.extra["signature"]["bore"]["faces"], n.extra["signature"]["bore"]["faces"])
        self.assertAlmostEqual(b.extra["signature"]["bore"]["area"], n.extra["signature"]["bore"]["area"], places=2)
        self.assertEqual([c["status"] for c in b.checks], [c["status"] for c in n.checks])

    def test_an_edit_during_refine_is_never_overwritten(self):
        """prepare() reads the source at head N; an edit lands (N+1) before refine commits: the refined revision is
        refused (409) and the edit stays the head, untouched."""
        from unittest import mock
        from form.refine import engine
        from form.refine.ledger import Ledger
        p = self.st.create_design("Block edit", self.SRC, brief="a desk block", purpose="model")
        edited = self.SRC.replace('"A block with a bore."', '"A block with a bore, edited."')
        real = engine.prepare
        seen = {}

        def prepare_then_edit(st, pid, *a, **kw):
            out = real(st, pid, *a, **kw)
            q = st.update_design(st.load(pid), edited, "a person's edit", None, "user", None, "python")
            seen["head"] = q["head"]
            return out

        with mock.patch.object(engine, "prepare", prepare_then_edit):
            r = engine.refine(self.st, p["id"], ops=list(ops_cad.OPERATORS), ledger=Ledger.memory(), budget_s=60)
        self.assertEqual(r["from_rev"], 1)
        self.assertTrue(r["changed"], r.get("rounds"))
        self.assertEqual((r.get("commit_error") or {}).get("status"), 409, r.get("commit_error"))
        self.assertNotIn("head", r)
        q = self.st.load(p["id"])
        self.assertEqual(q["head"], seen["head"])
        self.assertEqual(self.st.source_text(q), edited)
        self.assertNotIn("refine", self.st.rev(q))


if __name__ == "__main__":
    unittest.main()
