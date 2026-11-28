"""Modelling by hand (form/modelling.py, form/handfeat.py): the feature tree and picked features, as source.

The tree's ops (suppress, restore, move, rename) are text edits that round-trip exactly and are refused with the
reason; the rollback view builds up to a feature from its checkpoints; every picked kind (fillet, chamfer, hole,
pattern, shell) builds, is one named method plus its parameters in the source, round-trips through the canonical
source, survives a sweep of the design's main parameter, and leaves the features before it loading from their
checkpoints. A move that makes a feature do nothing is refused by the build, and nothing is saved."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-modelling-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import config, edits, featureprog, modelling  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

PLATE = '''
from build123d import Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Plate"
    params = [Param("w", "Width", 60, 30, 110, 1, "mm", "form", "body"),
              Param("hole_d", "Hole", 5, 2, 10, 0.1, "mm", "form", "holes")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], 40, 10)

    @feature("Holes", role="interface")
    def holes(self, v, body):
        return body - Pos(v["w"] / 4, 0, 0) * Cylinder(v["hole_d"] / 2, 20)

    @feature("Rib")
    def rib(self, v, body):
        return body + Pos(0, 0, 8) * Box(v["w"], 4, 6)

    @feature("Rib slot")
    def rib_slot(self, v, body):
        return body - Pos(0, 0, 9) * Box(8, 10, 2)
'''


def _ops(source, ops):
    return edits.apply(source, ops)[0]


class TreeOpsOnSource(unittest.TestCase):
    """No kernel: the ops are text edits of the design's source."""

    def test_suppress_and_restore_round_trip_exactly(self):
        s = _ops(PLATE, [{"op": "suppress", "feature": "holes"}])
        self.assertIn('@feature("Holes", role="interface", suppressed=True)', s)
        self.assertEqual(_ops(s, [{"op": "restore", "feature": "holes"}]), PLATE)
        self.assertEqual([r["suppressed"] for r in modelling.tree_of(s)], [False, True, False, False])

    def test_move_changes_the_build_order_only(self):
        s = _ops(PLATE, [{"op": "move", "feature": "rib", "before": "holes"}])
        self.assertEqual(featureprog.feature_ids(s), ["body", "rib", "holes", "rib_slot"])
        self.assertEqual(sorted(s.split()), sorted(PLATE.split()))         # the same text, in another order
        self.assertTrue(edits.diff(PLATE, s)["order_changed"])

    def test_rename_carries_the_new_id_to_every_reference(self):
        s = _ops(PLATE, [{"op": "rename", "feature": "holes", "label": "Mount holes", "id": "mount_holes"}])
        self.assertEqual(featureprog.feature_ids(s), ["body", "mount_holes", "rib", "rib_slot"])
        self.assertIn('Param("hole_d", "Hole", 5, 2, 10, 0.1, "mm", "form", "mount_holes")', s)
        self.assertIn('@feature("Mount holes", role="interface")', s)
        self.assertNotIn('"holes"', s)

    def test_refusals_say_why(self):
        cases = {"first feature": [{"op": "suppress", "feature": "body"}],
                 "stays first": [{"op": "move", "feature": "body", "after": "rib"}],
                 "nothing goes before": [{"op": "move", "feature": "rib", "before": "body"}],
                 "already built": [{"op": "restore", "feature": "rib"}],
                 "no feature": [{"op": "suppress", "feature": "nope"}],
                 "cannot be a feature id": [{"op": "rename", "feature": "rib", "id": "Bad Id"}]}
        for want, ops in cases.items():
            with self.assertRaises(StudioError) as e:
                edits.apply(PLATE, ops)
            self.assertIn(want, str(e.exception), ops)

    def test_a_feature_that_reads_another_keeps_it_built_and_after_it(self):
        reader = PLATE + '''
    @feature("Pattern 1")
    def pattern_1(self, v, body):
        from form import handfeat
        return handfeat.pattern(body, self._form_trail, "holes", "linear", 2, 10, [1, 0, 0])
'''
        with self.assertRaises(StudioError) as e:
            edits.apply(reader, [{"op": "suppress", "feature": "holes"}])
        self.assertIn("pattern_1 reads what holes makes", str(e.exception))
        with self.assertRaises(StudioError) as e:
            edits.apply(reader, [{"op": "move", "feature": "pattern_1", "before": "holes"}])
        self.assertIn("cannot come before holes", str(e.exception))
        rows = {r["id"]: r for r in modelling.tree_of(reader)}
        self.assertEqual(rows["pattern_1"]["reads"]["features"], ["holes"])
        self.assertEqual(rows["holes"]["used_by"], ["pattern_1"])
        self.assertEqual(rows["holes"]["reads"]["params"], ["hole_d", "w"])
        # suppressing both in one edit, the reader first, is allowed
        s = _ops(reader, [{"op": "suppress", "feature": "pattern_1"}, {"op": "suppress", "feature": "holes"}])
        self.assertEqual([r["suppressed"] for r in modelling.tree_of(s)], [False, True, False, False, True])

    def test_the_rollback_block_is_not_part_of_any_checkpoint_key(self):
        s = modelling.upto_source(PLATE, "holes")
        self.assertIn("rollback(Design, upto=\"holes\")", s)
        self.assertEqual(modelling.strip_rollback(s).strip(), PLATE.strip())
        self.assertNotIn("rollback(", featureprog._BLOCK.sub("", s))


def main_studio():
    return Studio(config.load())


class Kernel(unittest.TestCase):
    """The kernel builds: one project, every op in turn."""

    @classmethod
    def setUpClass(cls):
        cls.st = main_studio()
        cls.p = cls.st.create_design("Plate", PLATE, purpose="model")

    def load(self):
        return self.st.load(self.p["id"])

    def log(self, p=None):
        p = p or self.load()
        return {e["feature"]: e["status"] for e in self.st.rev(p)["build_log"]}

    def test_1_rollback_from_checkpoints(self):
        p = self.load()
        v = modelling.view_upto(self.st, p, "holes")
        self.assertEqual(v["upto"]["built"], ["body", "holes"])
        self.assertEqual(v["upto"]["after"], ["rib", "rib_slot"])
        self.assertAlmostEqual(v["volume_mm3"], 60 * 40 * 10 - 3.14159265 * 2.5 ** 2 * 10, delta=1.0)
        self.assertEqual({e["feature"]: e["status"] for e in v.get("build_log", [])},
                         {"body": "checkpoint", "holes": "checkpoint"})
        again = modelling.view_upto(self.st, p, "holes")
        self.assertLess(again["upto"]["ms"], 100.0)                       # the acceptance bar
        self.assertEqual(modelling.view_upto(self.st, p, "body")["volume_mm3"], 24000.0)
        with self.assertRaises(StudioError):
            modelling.view_upto(self.st, p, "nope")
        self.assertEqual(p["head"], self.load()["head"])                  # nothing saved

    def test_1b_tree_says_where_and_who(self):
        """The tree returns the code it read, each feature's lines in it, and the first revision that built it."""
        t = modelling.tree(self.st, self.load())
        lines = t["source"].split("\n")
        for r in t["features"]:
            a, b = r["lines"]
            self.assertTrue(lines[a - 1].lstrip().startswith("@feature"), (r["id"], lines[a - 1]))
            self.assertIn(f"def {r['id']}(", "\n".join(lines[a - 1:b]))
            self.assertEqual(r["made"], {"rev": 1, "origin": self.st.rev(self.load(), 1).get("origin") or "user"})

    def test_2_suppress_restore(self):
        p = self.load()
        before = self.st.head_summary(p)["volume_mm3"]
        r = modelling.commit(self.st, p, [{"op": "suppress", "feature": "rib"}])
        self.assertEqual(r["said"], "Suppressed rib")
        p = self.load()
        self.assertEqual(self.log(p)["rib"], "suppressed")
        self.assertEqual(self.log(p)["holes"], "checkpoint")
        self.assertEqual([f["suppressed"] for f in self.st.recipe(p).public()["features"]], [False, False, True, False])
        self.assertLess(self.st.head_summary(p)["volume_mm3"], before)
        modelling.commit(self.st, p, [{"op": "restore", "feature": "rib"}])
        self.assertAlmostEqual(self.st.head_summary(self.load())["volume_mm3"], before, places=3)

    def test_3_a_move_that_empties_a_feature_is_refused_by_the_build(self):
        p = self.load()
        head = p["head"]
        pv = modelling.preview(self.st, p, [{"op": "move", "feature": "rib_slot", "before": "rib"}])
        self.assertFalse(pv["ok"])
        self.assertIn("rib_slot would do nothing", pv["refused"])
        with self.assertRaises(StudioError) as e:
            modelling.commit(self.st, p, [{"op": "move", "feature": "rib_slot", "before": "rib"}])
        self.assertIn("Refused", str(e.exception))
        self.assertEqual(self.load()["head"], head)
        ok = modelling.preview(self.st, p, [{"op": "move", "feature": "holes", "after": "rib"}])
        self.assertTrue(ok["ok"], ok)

    def test_4_rename_keeps_the_solid(self):
        p = self.load()
        before = self.st.head_summary(p)["volume_mm3"]
        modelling.commit(self.st, p, [{"op": "rename", "feature": "rib_slot", "label": "Cable slot", "id": "cable_slot"}])
        p = self.load()
        self.assertIn("cable_slot", self.log(p))
        self.assertAlmostEqual(self.st.head_summary(p)["volume_mm3"], before, places=3)
        self.assertEqual(self.log(p)["rib"], "checkpoint")

    def _add(self, kind, picks=None, **o):
        p = self.load()
        pl = modelling.plan(self.st, p, kind, picks or [], **o)
        pv = modelling.preview(self.st, p, pl["ops"])
        self.assertTrue(pv["ok"], pv)
        r = modelling.commit(self.st, p, pl["ops"], p["head"], planned=pl)
        p = self.load()
        fid = pl["feature"]
        log = self.log(p)
        self.assertEqual(log[fid], "built")
        self.assertEqual({k for k, s in log.items() if k != fid and s != "suppressed"},
                         {k for k, s in log.items() if s == "checkpoint"})  # everything before it from checkpoints
        c = edits.canonical(self.st, p)
        self.assertIn(fid, featureprog.feature_ids(c["source"]))
        self.assertEqual(sum(1 for ln in c["source"].splitlines() if ln.strip().startswith(f"def {fid}(")), 1)
        for prm in pl["params"]:
            self.assertIn(prm["key"], self.st.rev(p)["values"])
        # the source round-trips through the edit protocol: the ops that make it from the one before are exact
        prev = self.st.source_text(p, p["head"] - 1)
        self.assertEqual(edits.apply(prev, edits.delta(prev, c["source"]))[0], c["source"])
        for w in (30, 110):                                       # the editability measure: both ends of w
            s = self.st.preview(p, {"w": w})
            self.assertFalse(s.get("skipped"), (kind, w, s.get("skipped")))
        return r, pl, pv

    def test_5_fillet(self):
        r, pl, pv = self._add("fillet", [{"at": [0, 20, 5]}, {"at": [0, -20, 5]}], radius=2)
        self.assertEqual(pl["summary"], "Fillet 1: 2 edges, r2 mm")
        self.assertEqual(r["said"], "Added Fillet 1: 2 edges, r2 mm")
        self.assertLess(pv["volume_mm3"]["change"], 0)
        self.assertEqual([e["query"]["owners"] for e in pl["picked"]["edges"]], [["body", "body"]] * 2)

    def test_6_hole_counterbore_and_iso286(self):
        _r, pl, pv = self._add("hole", [{"at": [-15, 10, 5]}], standard="clearance", size="M4", style="counterbore")
        d = {x["key"]: x for x in pl["params"]}
        self.assertEqual(d["hole_1_d"]["default"], 4.5)
        self.assertIn("ISO 273", d["hole_1_d"]["doc"])
        self.assertEqual(d["hole_1_d"]["provenance"], "specified")
        self.assertAlmostEqual(d["hole_1_head_d"]["default"], 7.22 + 0.3, places=3)   # ISO 4762 dk + clearance
        p = self.load()
        fit = modelling.plan(self.st, p, "hole", [{"at": [-15, -10, 5]}], standard="iso286", nominal=8, fit="H7")
        self.assertAlmostEqual(fit["params"][0]["default"], 8.0075, places=4)         # H7 on 8: 0 to +0.015
        self.assertIn("H7", fit["label"])
        tap = modelling.plan(self.st, p, "hole", [{"at": [-15, -10, 5]}], standard="tapped", size="M3")
        self.assertEqual(tap["params"][0]["default"], 2.5)
        self.assertIn("thread is not modelled", tap["summary"])
        with self.assertRaises(StudioError):
            modelling.plan(self.st, p, "hole", [{"at": [0, 0, 50]}], standard="clearance", size="M3")

    def test_7_pattern_linear_and_polar(self):
        _r, pl, _pv = self._add("pattern", of="hole_1", mode="linear", axis="x", count=3, pitch=12)
        self.assertEqual(pl["summary"], "Pattern 1: 3 × hole_1, 12 mm apart")
        p = self.load()
        polar = modelling.plan(self.st, p, "pattern", of="holes", mode="polar", axis="z", count=4)
        self.assertEqual(polar["params"][1]["default"], 90.0)
        with self.assertRaises(StudioError):
            modelling.plan(self.st, p, "pattern", of="body", count=2, pitch=5)

    def test_8_chamfer_and_shell(self):
        self._add("chamfer", [{"at": [30, 0, -5]}], length=1)
        p = self.load()
        pl = modelling.plan(self.st, p, "shell", [{"at": [0, 0, -5]}], thickness=1.5)
        pv = modelling.preview(self.st, p, pl["ops"])
        self.assertTrue(pv["ok"], pv)
        self.assertLess(pv["volume_mm3"]["after"], 0.6 * pv["volume_mm3"]["before"])
        self.assertEqual(self.load()["head"], p["head"])                  # a preview saves nothing

    def test_9_a_lost_edge_leaves_the_feature_out_and_says_which(self):
        p = self.load()
        src = edits.canonical(self.st, p)["source"]
        bad = src.replace('"pos": [0.5, 1.0', '"pos": [0.5, 0.5', 1)       # the picked edge's place moved far
        self.assertNotEqual(bad, src)
        rid = self.st._load_design(bad, "python")
        s = self.st._k("summary", key="t-" + rid, recipe_id=rid, values=self.st.rev(p)["values"], p=p)
        sk = {x["feature"]: x["message"] for x in s.get("skipped") or []}
        self.assertIn("fillet_1", sk)
        self.assertIn("edge 1 of 2", sk["fillet_1"])
        self.assertIn("is not on the part now", sk["fillet_1"])


class Mcp(unittest.TestCase):
    """The same through MCP: add_feature kinds with preview, render(upto=), get_design_source's tree."""

    def test_tools(self):
        from form import mcp_server
        st = main_studio()
        p = st.create_design("Plate mcp", PLATE, purpose="model")
        srv = mcp_server.build()

        def call(name, args):
            out = asyncio.run(srv.call_tool(name, args))
            blocks = out if isinstance(out, (list, tuple)) else getattr(out, "content", out)
            if isinstance(blocks, tuple):
                blocks = blocks[0]
            texts = [getattr(b, "text", None) for b in blocks]
            return [t for t in texts if t], [b for b in blocks if getattr(b, "type", "") == "image"]
        texts, _ = call("add_feature", {"project": p["id"], "kind": "fillet", "picks": [{"at": [0, 20, 5]}],
                                        "radius": 1.5, "preview": True})
        out = json.loads(texts[0])
        self.assertFalse(out["saved"])
        self.assertTrue(out["preview"]["ok"])
        self.assertEqual(st.load(p["id"])["head"], p["head"])
        texts, imgs = call("render", {"project": p["id"], "upto": "holes"})
        self.assertTrue(imgs)
        self.assertTrue(any("up to Holes (rollback, not saved)" in t for t in texts))
        texts, _ = call("get_design_source", {"project": p["id"]})
        src = json.loads(texts[0])
        self.assertEqual([r["id"] for r in src["tree"]], ["body", "holes", "rib", "rib_slot"])
        texts, _ = call("edit_design", {"project": p["id"], "ops": [{"op": "suppress", "feature": "rib_slot"}],
                                        "run": False, "look": False})
        self.assertEqual(json.loads(texts[0])["head"], p["head"] + 1)
        # B3 headless: a design from a sketch, then its sketch read and changed by ops
        b = modelling.start_from_sketch(st, "Bracket mcp", bracket_sketch(), "extrude", depth=40)
        out = json.loads(call("get_sketch", {"project": b["id"], "feature": "extrude_1"})[0][0])
        self.assertEqual(out["solved"]["dof"], 0)
        self.assertEqual(sorted(d["name"] for d in out["solved"]["dims"]), ["base", "height", "t", "t2"])
        out = json.loads(call("edit_sketch", {"project": b["id"], "feature": "extrude_1", "preview": True,
                                              "ops": [{"op": "set", "name": "base", "value": 90}]})[0][0])
        self.assertFalse(out["saved"])
        self.assertAlmostEqual(out["preview"]["bbox_mm"]["after"][1][0], 90.0, places=4)
        with self.assertRaises(Exception) as e:
            call("edit_sketch", {"project": b["id"], "feature": "extrude_1",
                                 "ops": [{"op": "dimension", "kind": "length", "entities": [2], "value": 30, "name": "clash"}]})
        self.assertIn("would not solve", str(e.exception))
        self.assertEqual(st.load(b["id"])["head"], b["head"])


def bracket_sketch():
    """An L-shaped bracket profile on XZ: base 60, upright 40, both 5 thick, fully constrained."""
    from form import handsketch
    d, _ = handsketch.apply_ops(
        {"plane": {"datum": "XZ", "offset": 0}, "points": [[0, 0], [60, 0], [60, 5], [5, 5], [5, 40], [0, 40]],
         "fixed": [0], "entities": [], "constraints": []},
        [{"op": "add_polyline", "points": [0, 1, 2, 3, 4, 5], "close": True},
         {"op": "dimension", "kind": "length", "entities": [0], "value": 60, "name": "base"},
         {"op": "dimension", "kind": "length", "entities": [5], "value": 40, "name": "height"},
         {"op": "dimension", "kind": "length", "entities": [1], "value": 5, "name": "t"},
         {"op": "dimension", "kind": "hdist", "points": [0, 3], "value": 5, "name": "t2"}])
    return d


class SketchData(unittest.TestCase):
    """No kernel: sketches as data, solved by form.sketch2d; ops and their refusals."""

    def test_solve_and_dof(self):
        from form import handsketch
        s = handsketch.solve(bracket_sketch())
        self.assertTrue(s["ok"] and s["closed"])
        self.assertEqual(s["dof"], 0)
        d = bracket_sketch()
        d["constraints"] = [c for c in d["constraints"] if c.get("name") != "t2"]
        self.assertEqual(handsketch.solve(d)["dof"], 1)                     # one dimension less, one freedom
        moved = handsketch.solve(bracket_sketch(), {"x_base": 80}, "x_")
        self.assertAlmostEqual(max(p[0] for p in moved["points"]), 80.0, places=6)

    def test_ops_and_refusals(self):
        from form import handsketch
        d, made = handsketch.apply_ops(handsketch.empty(), [{"op": "add_rect", "at": [0, 0], "size": [30, 20]},
                                                             {"op": "add_circle", "center": [15, 10], "r": 4}])
        self.assertEqual(len(d["entities"]), 5)
        self.assertEqual([c["k"] for c in d["constraints"]], ["horizontal", "vertical", "horizontal", "vertical"])
        s = handsketch.solve(d)
        self.assertTrue(s["ok"] and s["closed"])
        self.assertEqual(s["loops"], 2)
        for bad, why in (([{"op": "add_line", "from": 0, "to": 99}], "no point 99"),
                         ([{"op": "explode"}], "unknown sketch op"),
                         ([{"op": "constrain", "kind": "glue", "entities": [0]}], "unknown constraint"),
                         ([{"op": "delete"}], "delete needs")):
            with self.assertRaises(handsketch.SketchError) as e:
                handsketch.apply_ops(d, bad)
            self.assertIn(why, str(e.exception))
        over = bracket_sketch()
        over["constraints"].append({"k": "length", "e": [2], "value": 30})     # base minus t2 is 55, not 30
        self.assertFalse(handsketch.solve(over)["ok"])
        self.assertIn("does not solve", handsketch.solve(over)["error"])

    def test_the_literal_round_trips(self):
        import ast as _ast
        from form import handsketch
        d = bracket_sketch()
        self.assertEqual(_ast.literal_eval(handsketch.literal(d)), handsketch.check(d))


class Sketches(unittest.TestCase):
    """The kernel builds: a design from a sketch, a sketch edited, a cut on a picked face, a revolve, a pattern along
    a picked edge; each survives a sweep of the sketch's own dimension."""

    @classmethod
    def setUpClass(cls):
        cls.st = main_studio()
        cls.p = modelling.start_from_sketch(cls.st, "Bracket", bracket_sketch(), "extrude", depth=40)

    def load(self):
        return self.st.load(self.p["id"])

    def test_1_design_from_a_sketch(self):
        p = self.load()
        s = self.st.head_summary(p)
        self.assertAlmostEqual(s["volume_mm3"], (60 * 5 + 35 * 5) * 40, places=3)
        self.assertEqual([round(x, 6) for x in s["bbox"][1]], [60.0, 0.0, 40.0])
        src = self.st.source_text(p)
        self.assertIn("handsketch.extrude", src)
        self.assertIn('"name": "base"', src)
        for k in ("extrude_1_base", "extrude_1_height", "extrude_1_t", "extrude_1_t2", "extrude_1_depth"):
            self.assertIn(k, self.st.rev(p)["values"])

    def test_2_edit_the_sketch(self):
        p = self.load()
        ops, _new = modelling.sketch_edit_ops(self.st, p, "extrude_1", [{"op": "set", "name": "base", "value": 80}])
        modelling.commit(self.st, p, ops)
        p = self.load()
        self.assertAlmostEqual(self.st.head_summary(p)["bbox"][1][0], 80.0, places=4)
        self.assertEqual(self.st.rev(p)["values"]["extrude_1_base"], 80.0)
        with self.assertRaises(StudioError) as e:
            modelling.sketch_edit_ops(self.st, p, "extrude_1", [{"op": "delete", "entity": 0}])
        self.assertIn("no closed profile", str(e.exception))

    def test_3_cut_on_a_picked_face_and_a_pattern_along_an_edge(self):
        from form import handsketch
        p = self.load()
        pl = modelling.sketch_plane(self.st, p, [40, -20, 5])
        self.assertEqual(pl["plane"]["face"]["owner"], "extrude_1")
        self.assertTrue(pl["outline"])
        sk, _ = handsketch.apply_ops(handsketch.empty(pl["plane"]),
                                     [{"op": "add_circle", "center": [0, 0], "r": 3},
                                      {"op": "dimension", "kind": "diameter", "entities": [0], "value": 6, "name": "d"}])
        plan = modelling.plan(self.st, p, "cut", None, sketch=sk, depth=0)
        v0 = self.st.head_summary(p)["volume_mm3"]
        modelling.commit(self.st, p, plan["ops"], planned=plan)
        p = self.load()
        self.assertAlmostEqual(v0 - self.st.head_summary(p)["volume_mm3"], 3.14159265 * 9 * 5, delta=0.5)
        self.assertEqual({e["feature"]: e["status"] for e in self.st.rev(p)["build_log"]}["extrude_1"], "checkpoint")
        for base in (50, 110):
            self.assertFalse(self.st.preview(p, {"extrude_1_base": base}).get("skipped"), base)
        # the bracket's long bottom edge gives the direction
        pat = modelling.plan(self.st, p, "pattern", [{"at": [30, -40, 0]}], of="cut_1", count=3, pitch=15)
        self.assertEqual(pat["picked"]["axis"], [1.0, 0.0, 0.0])
        pv = modelling.preview(self.st, p, pat["ops"])
        self.assertTrue(pv["ok"], pv)
        self.assertAlmostEqual(-pv["volume_mm3"]["change"], 2 * 3.14159265 * 9 * 5, delta=1.0)

    def test_4_revolve(self):
        from form import handsketch
        sk, _ = handsketch.apply_ops({"plane": {"datum": "XZ", "offset": 0}, "points": [[0, 0], [0, 10], [4, 10], [4, 0]],
                                      "fixed": [0], "entities": [], "constraints": []},
                                     [{"op": "add_polyline", "points": [0, 1, 2, 3], "close": True}])
        src, _summary = modelling.sketch_design_source("Peg", sk, "revolve", axis_entity=0, angle=360)
        p = self.st.create_design("Peg", src, purpose="model")
        self.assertAlmostEqual(self.st.head_summary(p)["volume_mm3"], 3.14159265 * 16 * 10, delta=0.5)


if __name__ == "__main__":
    unittest.main()
