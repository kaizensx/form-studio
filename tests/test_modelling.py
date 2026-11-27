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


if __name__ == "__main__":
    unittest.main()
