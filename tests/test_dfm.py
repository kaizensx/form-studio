"""Manufacturability (form/dfm): every rule passes and fails at its threshold on synthetic parts, and every fix is
proved by checking again.

Rules (in process, on build123d solids, no worker): each rule of each process with a part on each side of its
limit, built so the measured value is known in advance (a wall of 0.7 mm against 0.8, a corner of r 2.5 against a
3 mm tool radius, an overhang of 40° against 45°). The rule tables themselves: every limit names a source with a
title, publisher, URL and the dates; "not checked" (a missing tool, resin or machine) is never a pass.

Fixes (through a Studio on a temporary FORM_DATA, with the kernel worker): draft on a cup for moulding, corners of a
pocket for a 6 mm cutter (a plain Recipe, lifted into features), escape holes in a hollow block for SLS, a thin
wall raised by its parameter, a hole set to the drill series; each is previewed, applied as a revision through
edit_design and checked again on the new head, and is claimed fixed only by that check. A preview saves nothing; a
fix that cannot pass is not applied. The overlay has the format the viewport reads, and the CLI prints JSON."""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-dfm-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build123d import Axis, Box, Cylinder, Plane, Polyline, Pos, extrude, make_face  # noqa: E402

from form import config, dfm, thickness  # noqa: E402
from form.dfm import measure, ops, rules  # noqa: E402
from form.studio import Studio  # noqa: E402


def run(proc, shape, opts=None):
    opts = dict(opts or {})
    m = thickness.model_of_shape(shape)
    out = measure.measure_model(m, proc, rules.spec(proc, opts), opts)
    dfm._tonnage(out, proc, opts)
    ev = rules.evaluate(proc, out, opts)
    return {r["id"]: r for r in ev["rows"]}, ev, out


def status(proc, shape, rule, opts=None):
    rows, _ev, _out = run(proc, shape, opts)
    return rows[rule]["status"], rows[rule].get("value")


def cup(t, w=30, d=20, h=10):
    """An open box with walls and floor t thick."""
    return Box(w, d, h) - Pos(0, 0, t) * Box(w - 2 * t, d - 2 * t, h)


def shelf(alpha):
    """A column with a shelf whose underside is alpha degrees from level, well above the plate."""
    L = 12
    h = 10 + L * math.tan(math.radians(alpha))
    pts = [(0, 0), (10, 0), (10, 10), (10 + L, h), (10 + L, h + 3), (0, h + 3), (0, 0)]
    return extrude(make_face(Plane.XZ * Polyline(*pts)), amount=10)


def pocket(depth=11, r=None, w=20, d=12):
    body = Box(40, 30, 20) - Pos(0, 0, 10 - depth / 2) * Box(w, d, depth)
    if r:
        edges = [e for e in body.edges() if abs(e.tangent_at(0.5).Z) > 0.999 and abs(e.center().X) < w / 2 + 0.01
                 and abs(e.center().Y) < d / 2 + 0.01]
        body = body.fillet(r, edges)
    return body


def block_with_hole(dia, depth=20):
    return Box(20, 20, depth) - Cylinder(dia / 2, depth * 2)


class RuleTables(unittest.TestCase):
    def test_every_limit_names_its_source(self):
        for pid in rules.processes():
            t = rules.table(pid)
            for s in t["sources"].values():
                for k in ("title", "publisher", "url", "published", "read"):
                    self.assertTrue(s.get(k), f"{pid}: source {s.get('id')} has no {k}")
            for r in t["rules"]:
                src = r.get("source")
                self.assertTrue(src in t["sources"] or src in ("computed", "unsourced"), f"{r['id']}: source {src}")
                if src in t["sources"]:
                    self.assertTrue(r.get("quote"), f"{r['id']}: a sourced rule quotes its source")
                if r["op"] not in ("info", "fits"):
                    self.assertTrue("fail" in r or "warn" in r, f"{r['id']} has no limit")
                if r.get("hole_source"):
                    self.assertIn(r["hole_source"], t["sources"])

    def test_the_five_printing_technologies_and_the_two_processes_exist(self):
        self.assertEqual(set(rules.processes()), {"cnc", "injection", "fdm", "sla", "sls", "mjf", "lpbf", "sheet_metal"})

    def test_aliases(self):
        self.assertEqual(dfm.process_id("Moulding"), "injection")
        self.assertEqual(dfm.process_id("DMLS"), "lpbf")
        with self.assertRaises(Exception):
            dfm.process_id("knitting")


class CNC(unittest.TestCase):
    T6 = {"tool_d": 6, "material": "metal"}

    def test_sharp_internal_corner_fails_against_the_tool(self):
        self.assertEqual(status("cnc", pocket(), "cnc.corner_tool", self.T6), ("fail", 0.0))
        self.assertEqual(status("cnc", pocket(), "cnc.access", self.T6)[0], "fail")       # material left in the corners

    def test_corner_radius_at_the_tool_radius(self):
        self.assertEqual(status("cnc", pocket(r=2.5), "cnc.corner_tool", self.T6)[0], "fail")
        st, v = status("cnc", pocket(r=3.2), "cnc.corner_tool", self.T6)
        self.assertEqual(st, "pass")
        self.assertAlmostEqual(v, 3.2, places=6)

    def test_corner_radius_against_a_third_of_the_depth(self):
        self.assertEqual(status("cnc", pocket(depth=9, r=3.2), "cnc.corner_depth", self.T6)[0], "pass")   # 3.2/9 = 0.356
        self.assertEqual(status("cnc", pocket(depth=12, r=3.2), "cnc.corner_depth", self.T6)[0], "warn")  # 0.267

    def test_tool_reach_by_diameter(self):
        deep = Box(30, 20, 32) - Pos(0, 0, 1) * Box(8.5, 8.5, 30)
        st, v = status("cnc", deep, "cnc.reach", self.T6)
        self.assertEqual(st, "warn")
        self.assertGreater(v, 4.0)
        self.assertEqual(status("cnc", pocket(depth=6, r=3.5), "cnc.reach", self.T6)[0], "pass")

    def test_thin_walls_by_material(self):
        self.assertEqual(status("cnc", cup(0.45), "cnc.wall", self.T6)[0], "fail")
        self.assertEqual(status("cnc", cup(0.6), "cnc.wall", self.T6)[0], "warn")
        self.assertEqual(status("cnc", cup(0.9), "cnc.wall", self.T6)[0], "pass")
        self.assertEqual(status("cnc", cup(1.2), "cnc.wall", {"tool_d": 6, "material": "plastic"})[0], "warn")

    def test_holes(self):
        self.assertEqual(status("cnc", block_with_hole(3, 20), "cnc.hole_depth", self.T6)[0], "warn")   # 6.7 d
        self.assertEqual(status("cnc", block_with_hole(5, 10), "cnc.hole_depth", self.T6)[0], "pass")
        self.assertEqual(status("cnc", block_with_hole(0.9, 4), "cnc.hole_min", self.T6)[0], "fail")
        self.assertEqual(status("cnc", block_with_hole(2.0, 4), "cnc.hole_min", self.T6)[0], "warn")
        self.assertEqual(status("cnc", block_with_hole(3.0, 4), "cnc.hole_min", self.T6)[0], "pass")
        self.assertEqual(status("cnc", block_with_hole(4.05, 8), "cnc.hole_drill", self.T6)[0], "warn")
        self.assertEqual(status("cnc", block_with_hole(4.0, 8), "cnc.hole_drill", self.T6)[0], "pass")
        self.assertEqual(status("cnc", Box(10, 10, 10), "cnc.hole_min", self.T6)[0], "n/a")

    def test_more_axes_fewer_setups(self):
        tilted = Box(30, 30, 20) - Pos(0, 0, 10) * Box(60, 60, 20).rotate(Axis.Y, 35)
        n = {}
        for ax in (3, 4, 5):
            rows, _e, _o = run("cnc", tilted, {**self.T6, "tool_d": 4, "axes": ax})
            self.assertEqual(rows["cnc.access"]["status"], "pass")
            n[ax] = rows["cnc.setups"]["value"]
        self.assertGreaterEqual(n[3], n[4])
        self.assertGreaterEqual(n[4], n[5])
        self.assertGreater(n[3], n[5])                                  # the slope and the base: 2 setups on 3 axes, 1 on 5

    def test_outer_walls_are_cut_from_above(self):
        rows, _e, out = run("cnc", Box(40, 30, 20), self.T6)
        self.assertEqual(rows["cnc.access"]["status"], "pass")
        self.assertEqual(rows["cnc.setups"]["value"], 2)                 # top with the flanks, then the base

    def test_undercut_slot_is_unreachable(self):
        # a T-slot: its overhanging lips hide the slot's sides from every axis direction
        t = Box(40, 30, 20) - Pos(0, 0, 8) * Box(40, 4, 4) - Pos(0, 0, 4) * Box(40, 12, 4)
        self.assertEqual(status("cnc", t, "cnc.access", {"tool_d": 3, "material": "metal"})[0], "fail")

    def test_without_a_tool_it_is_not_checked_never_passed(self):
        rows, ev, _o = run("cnc", Box(10, 10, 10), {"material": "metal"})
        self.assertEqual(rows["cnc.access"]["status"], "not_checked")
        self.assertIn("tool_d", rows["cnc.access"]["reason"])
        self.assertEqual(ev["verdict"], "not proven")

    def test_a_shop_override_is_specified(self):
        rows, _e, _o = run("cnc", cup(0.9), {**self.T6, "overrides": {"cnc.wall": {"warn": 1.0}}})
        self.assertEqual(rows["cnc.wall"]["status"], "warn")
        self.assertEqual(rows["cnc.wall"]["evidence"], "specified (your override)")


class Moulding(unittest.TestCase):
    ABS = {"resin": "abs"}

    def test_draft_threshold(self):
        c = cup(2.0)
        self.assertEqual(status("injection", c, "injection.draft", self.ABS), ("fail", 0.0))
        st, v = status("injection", ops.draft(c, (0, 0, 1), 1.0, -5.0), "injection.draft", self.ABS)
        self.assertEqual(st, "warn")
        self.assertAlmostEqual(v, 1.0, places=4)
        self.assertEqual(status("injection", ops.draft(c, (0, 0, 1), 2.5, -5.0), "injection.draft", self.ABS)[0], "pass")
        self.assertEqual(status("injection", ops.draft(c, (0, 0, 1), 2.5, -5.0), "injection.draft_textured",
                                {**self.ABS, "textured": True})[0], "fail")

    def test_undercut_found_and_its_side_action(self):
        g = cup(3.0, 40, 30, 20) - Pos(-20, 0, 0) * Box(4, 10, 4)
        rows, ev, out = run("injection", g, self.ABS)
        self.assertEqual(rows["injection.undercut"]["status"], "fail")
        self.assertAlmostEqual(rows["injection.undercut"]["value"], 96.0, delta=1.0)    # 20 + 20 + 40 + 2 × 8 mm²
        sa = out["data"]["side_actions"]
        self.assertEqual(len(sa), 1)
        self.assertEqual(sa[0]["action"], "side action")
        self.assertAlmostEqual(sa[0]["direction"][0], -1.0, places=3)
        self.assertEqual(status("injection", cup(3.0, 40, 30, 20), "injection.undercut", self.ABS)[0], "pass")

    def test_an_undercut_inside_the_part_needs_a_lifter(self):
        g = cup(2.0, 40, 30, 20) - Pos(-18.5, 0, 4) * Box(1, 8, 3)       # a 1 mm groove in the inner wall
        _rows, _e, out = run("injection", g, {**self.ABS, "pull": [0, 0, 1]})
        sa = out["data"]["side_actions"]
        self.assertEqual([s["action"] for s in sa], ["lifter"])
        self.assertAlmostEqual(sa[0]["direction"][0], 1.0, places=3)      # inward, away from the wall
        self.assertLess(sa[0]["stroke_mm"], 2.0)

    def test_pull_direction_and_parting_line_are_proposed(self):
        lying = cup(2.0).rotate(Axis.Y, 90)                         # its opening faces +X
        _rows, _e, out = run("injection", lying, self.ABS)
        self.assertGreater(abs(out["data"]["pull"][0]), 0.999)
        pl = out["data"]["parting_line"]
        self.assertGreater(pl["segments"], 3)
        self.assertIn("two-plate", pl["note"])

    def test_wall_range_by_resin(self):
        self.assertEqual(status("injection", cup(1.0), "injection.wall_min", self.ABS)[0], "warn")      # ABS 1.143
        self.assertEqual(status("injection", cup(1.5), "injection.wall_min", self.ABS)[0], "pass")
        self.assertEqual(status("injection", cup(1.0), "injection.wall_min", {"resin": "nylon"})[0], "pass")  # 0.762
        rows, ev, _o = run("injection", cup(1.5), {})
        self.assertEqual(rows["injection.wall_min"]["status"], "not_checked")
        self.assertEqual(ev["verdict"], "fail")                       # the zero draft still fails

    def test_clamp_tonnage_from_projected_area(self):
        rows, _e, out = run("injection", Box(40, 30, 10), self.ABS)
        t = out["measures"]["tonnage_t"]["items"][0]
        a_in2 = 1200 / 645.16
        self.assertAlmostEqual(t["projected_in2"], a_in2, delta=0.02)
        self.assertAlmostEqual(t["value"], 3 * a_in2, delta=0.06)
        self.assertAlmostEqual(t["range_t"][1], 10 * a_in2, delta=0.2)
        self.assertEqual(rows["injection.tonnage"]["status"], "info")
        self.assertIn("RJG", rows["injection.tonnage"]["evidence"])


class Printing(unittest.TestCase):
    def test_walls_per_technology(self):
        self.assertEqual(status("fdm", cup(0.7), "fdm.wall")[0], "fail")
        self.assertEqual(status("fdm", cup(0.9), "fdm.wall")[0], "pass")
        self.assertEqual(status("sla", cup(0.15), "sla.wall")[0], "fail")
        self.assertEqual(status("sla", cup(0.3), "sla.wall")[0], "pass")
        self.assertEqual(status("sls", cup(0.5), "sls.wall")[0], "fail")
        self.assertEqual(status("sls", cup(0.7), "sls.wall")[0], "pass")
        self.assertEqual(status("mjf", cup(0.9), "mjf.wall")[0], "fail")
        self.assertEqual(status("mjf", cup(1.1), "mjf.wall")[0], "pass")
        self.assertEqual(status("lpbf", cup(0.3), "lpbf.wall")[0], "fail")
        self.assertEqual(status("lpbf", cup(0.8), "lpbf.wall")[0], "warn")
        self.assertEqual(status("lpbf", cup(1.2), "lpbf.wall")[0], "pass")

    def test_overhangs_from_level(self):
        self.assertEqual(status("fdm", shelf(40), "fdm.overhang"), ("warn", 40.0))
        self.assertEqual(status("fdm", shelf(50), "fdm.overhang")[0], "pass")
        self.assertEqual(status("sla", shelf(5), "sla.overhang")[0], "warn")
        self.assertEqual(status("sla", shelf(15), "sla.overhang")[0], "pass")
        self.assertEqual(status("lpbf", shelf(40), "lpbf.overhang")[0], "fail")
        self.assertEqual(status("lpbf", shelf(50), "lpbf.overhang")[0], "pass")
        self.assertEqual(status("lpbf", shelf(50), "lpbf.overhang", {"alloy": "316L"})[0], "fail")
        self.assertEqual(status("fdm", Box(10, 10, 10), "fdm.overhang")[0], "pass")      # the plate is not an overhang
        rows, _e, _o = run("sls", shelf(5))
        self.assertNotIn("sls.overhang", rows)                         # a powder bed carries it

    def test_holes(self):
        self.assertEqual(status("sla", block_with_hole(0.4, 4), "sla.hole")[0], "fail")
        self.assertEqual(status("sla", block_with_hole(0.6, 4), "sla.hole")[0], "pass")
        self.assertEqual(status("mjf", block_with_hole(0.8, 4), "mjf.hole")[0], "fail")
        self.assertEqual(status("mjf", block_with_hole(1.5, 4), "mjf.hole")[0], "warn")
        self.assertEqual(status("sls", block_with_hole(0.9, 4), "sls.hole")[0], "fail")
        self.assertEqual(status("sls", block_with_hole(1.2, 4), "sls.hole")[0], "pass")

    def test_enclosed_voids(self):
        hollow = Box(20, 20, 20) - Box(10, 10, 10)
        for pid in ("sla", "sls", "mjf", "lpbf"):
            self.assertEqual(status(pid, hollow, f"{pid}.trapped"), ("fail", 1))
            self.assertEqual(status(pid, Box(20, 20, 20), f"{pid}.trapped"), ("pass", 0))
        self.assertEqual(status("sls", ops.escape_holes(hollow, 3.5, 2), "sls.trapped"), ("pass", 0))

    def test_machine_size(self):
        self.assertEqual(status("sls", Box(170, 20, 20), "sls.size")[0], "fail")       # Fuse: 159.8 mm
        self.assertEqual(status("sls", Box(150, 20, 20), "sls.size")[0], "pass")
        rows, ev, _o = run("fdm", Box(20, 20, 20))
        self.assertEqual(rows["fdm.size"]["status"], "not_checked")    # no machine: never a pass
        self.assertEqual(ev["verdict"], "not proven")
        self.assertEqual(status("fdm", Box(20, 20, 20), "fdm.size", {"machine": [180, 180, 180]})[0], "pass")
        self.assertEqual(status("fdm", Box(20, 20, 200), "fdm.size", {"machine": [180, 180, 180]})[0], "fail")

    def test_build_direction(self):
        # turned on its side the shelf's underside is a wall: no overhang
        self.assertEqual(status("fdm", shelf(30), "fdm.overhang", {"up": [0, -1, 0]})[0], "pass")


class Fixes(unittest.TestCase):
    """Preview, apply as a revision, check again: the fix is proved by the second check."""

    @classmethod
    def setUpClass(cls):
        cls.data = os.environ["FORM_DATA"]            # the data folder this Studio uses (another module may set it)
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    CUP = '''
from build123d import Box, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Cup"
    params = [Param("wall", "Wall", 2.0, 0.4, 6, 0.1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        w = v["wall"]
        return Box(40, 30, 20) - Pos(0, 0, w) * Box(40 - 2 * w, 30 - 2 * w, 20)
'''
    POCKET = '''
from build123d import Box, Pos
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Pocket block"
    params = [Param("depth", "Pocket depth", 11, 4, 18, 1, "mm", "form", "pocket")]
    features = [Feature("body", "Body", "structure"), Feature("pocket", "Pocket", "structure")]

    def build(self, v):
        body = Box(40, 30, 20)
        stages = [Stage("body", body)]
        body = body - Pos(0, 0, 10 - v["depth"] / 2) * Box(20, 12, v["depth"])
        stages.append(Stage("pocket", body))
        return stages
'''
    HOLLOW = '''
from build123d import Box, Cylinder
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Hollow"
    params = [Param("hole_d", "Bore", 4.05, 1, 10, 0.05, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        return Box(24, 24, 24) - Box(12, 12, 12)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        from build123d import Pos
        return body - Pos(8.5, 8.5, 0) * Cylinder(v["hole_d"] / 2, 40)
'''

    def _new(self, name, src):
        return self.st.create_design(name, src, purpose="model")

    def test_draft_on_a_cup(self):
        st = self.st
        p = self._new("Cup", self.CUP)
        before = dfm.check(st, p, "injection", {"resin": "abs"})
        self.assertEqual({r["id"]: r["status"] for r in before["rows"]}["injection.draft"], "fail")
        out = dfm.apply_fix(st, p, "injection", "draft", {"resin": "abs"})
        self.assertTrue(out["applied"] and out["fixed"], out)
        self.assertEqual(out["head"], 2)
        proof = {x["rule"]: x for x in out["proof"]}["injection.draft"]
        self.assertEqual((proof["before"], proof["after"]), ("fail", "pass"))
        self.assertAlmostEqual(proof["value_after"], 2.0, places=4)
        src = st.source_text(st.load(p["id"]))
        self.assertIn("def dfm_draft(self, v, body):", src)
        self.assertIn("dfm_draft_deg", src)
        # the proof is a fresh check of the new head, stored under the head's own key
        after = dfm.check(st, st.load(p["id"]), "injection", {"resin": "abs"})
        self.assertEqual(after["rev"], 2)
        self.assertNotEqual(after["key"], before["key"])
        self.assertTrue(all(Path(x).is_file() for x in out["pictures"].values()))

    def test_corners_of_a_plain_recipe_for_a_cutter(self):
        st = self.st
        p = self._new("Pocket", self.POCKET)
        opts = {"tool_d": 6, "material": "metal"}
        out = dfm.apply_fix(st, p, "cnc", "cnc.corner_tool", opts)
        self.assertTrue(out["fixed"], out)
        rows = {x["rule"]: x for x in out["proof"]}
        self.assertEqual(rows["cnc.corner_tool"]["after"], "pass")
        self.assertGreaterEqual(rows["cnc.corner_tool"]["value_after"], 3.0)
        self.assertIn("def dfm_corners(self, v, body):", st.source_text(st.load(p["id"])))
        # the fix is a parameter like any other: the corner radius can be changed and stays checked
        after = {r["id"]: r["status"] for r in dfm.check(st, st.load(p["id"]), "cnc", opts)["rows"]}
        self.assertEqual(after["cnc.corner_tool"], "pass")

    def test_preview_saves_nothing(self):
        st = self.st
        p = self._new("Preview", self.CUP)
        out = dfm.apply_fix(st, p, "injection", "draft", {"resin": "abs"}, apply=False)
        self.assertTrue(out["previewed"])
        self.assertFalse(out["applied"])
        self.assertEqual({x["rule"]: x for x in out["preview"]}["injection.draft"]["after"], "pass")
        self.assertEqual(st.load(p["id"])["head"], 1)

    def test_escape_holes_and_a_hole_to_the_drill_series(self):
        st = self.st
        p = self._new("Hollow", self.HOLLOW)
        out = dfm.apply_fix(st, p, "sls", "sls.trapped", {})
        self.assertTrue(out["fixed"], out)
        self.assertIn("def dfm_escape(self, v, body):", st.source_text(st.load(p["id"])))
        p = st.load(p["id"])
        opts = {"tool_d": 6, "material": "metal"}
        res = dfm.check(st, p, "cnc", opts)
        self.assertEqual({r["id"]: r["status"] for r in res["rows"]}["cnc.hole_drill"], "warn")
        out = dfm.apply_fix(st, p, "cnc", "cnc.hole_drill", opts)
        self.assertTrue(out["fixed"], out)
        self.assertEqual(out["ops"], [{"op": "set_param", "param": "hole_d", "value": 4.0}])

    def test_a_thin_wall_raised_by_its_parameter(self):
        st = self.st
        p = self._new("Thin cup", self.CUP)
        st.commit(p, {"wall": 0.7}, "thin", "agent", expect_head=1)
        p = st.load(p["id"])
        out = dfm.apply_fix(st, p, "fdm", "fdm.wall", {})
        self.assertTrue(out["fixed"], out)
        self.assertEqual(out["ops"], [{"op": "set_param", "param": "wall", "value": 0.8}])
        self.assertEqual(st.rev(st.load(p["id"]))["values"]["wall"], 0.8)

    def test_a_fix_that_cannot_pass_is_not_applied(self):
        st = self.st
        p = self._new("Narrow", self.POCKET.replace("Box(20, 12, v[\"depth\"])", "Box(5, 12, v[\"depth\"])"))
        out = dfm.apply_fix(st, p, "cnc", "cnc.corner_tool", {"tool_d": 6, "material": "metal"})
        # a 5 mm slot cannot take two corners of the 6 mm cutter's 3 mm radius: no candidate builds, nothing is saved
        self.assertFalse(out["applied"])
        self.assertFalse(out["fixed"])
        self.assertTrue(out["tried"])
        self.assertTrue(all(not x["built"] or not x["passes"] for x in out["tried"]))
        self.assertEqual(st.load(p["id"])["head"], 1)

    def test_overlay_format(self):
        st = self.st
        p = self._new("Overlay", self.CUP)
        res = dfm.check(st, p, "injection", {"resin": "abs"})
        ov = json.loads(Path(res["overlay_file"]).read_text())
        self.assertEqual(ov["format"], "form-dfm-overlay/1")
        import base64
        n = len(base64.b64decode(ov["positions"])) // 12
        self.assertEqual(len(base64.b64decode(ov["colors"])) // 4, n)
        self.assertEqual(len(base64.b64decode(ov["status"])), n)
        self.assertEqual(len(base64.b64decode(ov["values"])) // 4, n)
        self.assertEqual(ov["map"], "draft")
        self.assertTrue(any(f["status"] == "fail" for f in ov["faces"]))
        self.assertTrue(ov["lines"])
        self.assertTrue(all(set(m) >= {"at", "status", "rule", "label"} for m in ov["markers"]))

    def test_sheet_metal_is_measured_by_the_sheet_tool(self):
        # a moulded cup with sharp inside corners is not one sheet with bends: the unfold says so and the verdict
        # fails, never a pass (form/sheet, wave H)
        res = dfm.check(self.st, self._new("Sheet", self.CUP), "sheet_metal")
        rows = {r["id"]: r for r in res["rows"]}
        self.assertEqual(rows["sheet.unfold"]["status"], "fail")
        self.assertEqual(res["verdict"], "fail")

    def test_cli_prints_json(self):
        p = self._new("Cli", self.CUP)
        env = {**os.environ, "FORM_DATA": self.data, "PYTHONPATH": str(ROOT)}
        r = subprocess.run([sys.executable, "-m", "form", "dfm", p["id"], "--process", "injection", "--set", "resin=abs"],
                           capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = json.loads(r.stdout)
        self.assertEqual(out["process"], "injection")
        self.assertEqual(out["verdict"], "fail")
        self.assertTrue(out["fixes"])
        r = subprocess.run([sys.executable, "-m", "form", "dfm", "rules", "sls"], capture_output=True, text=True,
                           env=env, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("Fuse Series SLS Design Guide", r.stdout)


class Bench(unittest.TestCase):
    def test_register_studies_adds_one_entry_per_process(self):
        import types
        got = []
        fake = types.ModuleType("form.studies")

        class Study:
            def __init__(self, id, group, label, doc, evidence, **kw):
                self.id, self.group, self.kw = id, group, kw
        fake.Study = Study
        saved = sys.modules.get("form.studies")
        sys.modules["form.studies"] = fake
        try:
            dfm.register_studies(got.append)
        finally:
            if saved is None:
                sys.modules.pop("form.studies", None)
            else:
                sys.modules["form.studies"] = saved
        ids = {s.id for s in got}
        self.assertEqual(ids, {f"dfm_{p}" for p in ("cnc", "injection", "fdm", "sla", "sls", "mjf", "lpbf")})
        self.assertTrue(all(s.group == "study" and callable(s.kw["run"]) and callable(s.kw["key"]) for s in got))


if __name__ == "__main__":
    unittest.main()
