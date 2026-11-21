"""Skeleton first, one validated feature at a time (form/featureprog.py, form/kernel.py op_try_build).

A design whose third feature raises still becomes a project with the two stages that built (a partial revision,
flagged, release blocked); its source can be read; a FeatureDesign skips a failing feature and keeps building; a
fixed feature is rebuilt alone while the features before it load from their checkpoints; stage meshes are reported
while the build runs; and the four failure shapes of the helmet transcript (a fused band, a grazing cut, a fused
crest and two touching halves fused into one) each leave a saved project with a visible shell."""
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="form-incremental-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")

from form import config, featureprog  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

# a plain Recipe whose third feature raises (the shape of every failure in the helmet transcript)
THIRD_RAISES = '''
from build123d import Box, Cylinder, Pos
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Third raises"
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure"), Feature("bore", "Bore", "interface"),
                Feature("band", "Band", "structure")]

    def build(self, v):
        body = Box(v["w"], v["w"], 20)
        stages = [Stage("body", body)]
        body = body - Cylinder(5, 40)
        stages.append(Stage("bore", body))
        raise ValueError("BRep_API: command not done")      # the band's boolean
'''

FEATURES = '''
from build123d import Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Block by features"
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]

    def setup(self, v):
        return {"r": v["w"] / 8}

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], v["w"], 20)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Cylinder(self.ctx["r"], 40)

    @feature("Band")
    def band(self, v, body):
        raise ValueError("BRep_API: command not done")
'''

BAND_FIXED = '''def band(self, v, body):
    return body + Pos(0, 0, 12) * Box(v["w"] + 4, v["w"] + 4, 4)
'''

# representative replays of the transcript's four failures: a shell, its edge trim, then the failing step
SHELL = '''
from build123d import Align, Box, Plane, Pos, Sphere
from form import craft
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Hero shell"
    solids = {solids}
    params = [Param("r", "Radius", 100, 80, 120, 1, "mm", "form", "shell")]
    features = [Feature("shell", "Shell", "structure"), Feature("lower_edge", "Lower edge", "structure"),
                Feature("step", "Failing step", "structure")]

    def build(self, v):
        r = v["r"]
        body = Sphere(r) - Sphere(r - 3)
        stages = [Stage("shell", body)]
        body = body - Pos(0, 0, -r) * Box(3 * r, 3 * r, r)
        stages.append(Stage("lower_edge", body))
{step}
        return stages
'''
STEPS = {
    "fused band": '''        body = craft.fuse(body, Pos(500, 0, 0) * Box(5, 5, 5))           # does not reach the body
        stages.append(Stage("step", body))''',
    "grazing cut": '''        raise ValueError("cut could not be built (cut: invalid result; nudged cut: invalid result)")''',
    "fused crest": '''        crest = Pos(0, 0, 400) * Box(16, 200, 6)                          # a strip that misses the crown
        body = craft.fuse(body, crest)
        stages.append(Stage("step", body))''',
    "touching halves": '''        face = body & (Pos(0, 0, 0) * Box(1000, 1000, 1000, align=(Align.MIN, Align.CENTER, Align.CENTER)))
        back = body & (Pos(0, 0, 0) * Box(1000, 1000, 1000, align=(Align.MAX, Align.CENTER, Align.CENTER)))
        stages.append(Stage("step", back + face))                        # two parts declared, fused into one''',
}


class Incremental(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_1_third_feature_raises_still_makes_a_project(self):
        st = self.st
        with self.assertRaises(StudioError):                     # without partial: refused, as before
            st.create_design("Strict", THIRD_RAISES)
        p = st.create_design("Third raises", THIRD_RAISES, partial=True, draft="d-third")
        r = st.rev(p)
        self.assertEqual(r["partial"]["built"], ["body", "bore"])
        self.assertEqual(r["partial"]["failed"], "band")
        v = st.view(p)
        self.assertEqual(sorted({m["feature"] for m in v["mesh"]}), ["body", "bore"])
        self.assertGreater(v["volume_mm3"], 0)
        src = st.source_text(p)                                     # get_design_source works on it
        self.assertIn(featureprog.P_START, src)
        self.assertIn("raise ValueError", src)
        g = st.gate(p)
        self.assertFalse(g["ready"])
        self.assertTrue(any("partial build" in x for x in g["blocking"]))
        d = st.draft("d-third")                                     # the stages went out while it built
        self.assertEqual(d["feature"], "bore")
        self.assertTrue(d["mesh"][0]["positions"])
        ev = [e for e in st.activity_since(0) if e.get("draft") == "d-third"]
        self.assertEqual([e["stage"] for e in ev], ["body", "bore"])         # once each: the partial build loads them
        fixed = THIRD_RAISES.replace('        raise ValueError("BRep_API: command not done")      # the band\'s boolean',
                                     '        stages.append(Stage("band", body + Pos(0, 0, 12) * Box(44, 44, 4)))\n'
                                     '        return stages')
        p = st.update_design(st.load(p["id"]), src.replace(THIRD_RAISES.strip(), fixed.strip()))
        self.assertNotIn("partial", st.rev(p))
        self.assertNotIn(featureprog.P_START, st.source_text(p))   # the block went with the fix
        self.assertTrue(st.gate(p)["reasons"] is not None)

    def test_2_feature_design_skips_then_rebuilds_only_the_fixed_feature(self):
        st = self.st
        with self.assertRaises(StudioError) as cm:
            st.create_design("Strict features", FEATURES)
        self.assertEqual(cm.exception.extra.get("feature"), "band")
        p = st.create_design("Features", FEATURES, partial=True)
        r = st.rev(p)
        self.assertEqual([x["feature"] for x in r["partial"]["skipped"]], ["band"])
        self.assertEqual(r["partial"]["built"], ["body", "bore"])
        self.assertFalse(st.gate(p)["ready"])
        self.assertEqual(featureprog.feature_ids(st.source_text(p)), ["body", "bore", "band"])
        p = featureprog.update_feature(st, st.load(p["id"]), "band", BAND_FIXED)
        self.assertNotIn("partial", st.rev(p))
        log = {e["feature"]: e["status"] for e in st.rev(p)["build_log"]}
        self.assertEqual(log, {"body": "checkpoint", "bore": "checkpoint", "band": "built"})
        self.assertIn("@feature(\"Band\")", st.source_text(p))     # the old decorator stays
        # a failing new feature makes no revision without partial; the head is kept
        head = p["head"]
        with self.assertRaises(StudioError):
            featureprog.add_code_feature(st, st.load(p["id"]), "lip", "def lip(self, v, body):\n    return None.x\n")
        self.assertEqual(st.load(p["id"])["head"], head)
        p = featureprog.add_code_feature(st, st.load(p["id"]), "lip",
                                         "def lip(self, v, body):\n    return body + Pos(0, 0, -12) * Box(10, 10, 4)\n",
                                         label="Lip")
        log = {e["feature"]: e["status"] for e in st.rev(p)["build_log"]}
        self.assertEqual(log, {"body": "checkpoint", "bore": "checkpoint", "band": "checkpoint", "lip": "built"})
        p = featureprog.remove_code_feature(st, st.load(p["id"]), "bore")
        self.assertEqual(featureprog.feature_ids(st.source_text(p)), ["body", "band", "lip"])

    def test_3_transcript_failures_leave_a_visible_shell(self):
        st = self.st
        for i, (what, step) in enumerate(STEPS.items()):
            src = SHELL.replace("{solids}", "2" if what == "touching halves" else "1").replace("{step}", step)
            with self.subTest(what):
                with self.assertRaises(StudioError):
                    st.create_design(f"Strict {i}", src)
                p = st.create_design(f"Hero {i}", src, partial=True)
                self.assertTrue(st.rev(p)["partial"]["built"][:2] == ["shell", "lower_edge"], st.rev(p)["partial"])
                v = st.view(p)
                self.assertGreater(len(v["mesh"]), 0)
                self.assertGreater(v["volume_mm3"], 1000)
                self.assertFalse(st.gate(p)["ready"])


class OverMcp(unittest.TestCase):
    """create_design(partial) over real MCP stdio: the failed design is a project, get_design_source reads it, and
    one feature is fixed with update_design(feature=, code=)."""

    def test_session(self):
        import asyncio
        asyncio.run(self._session())

    async def _session(self):
        import json
        import sys
        from pathlib import Path
        from mcp import Client, StdioServerParameters
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(root)}
            params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"],
                                           env=env, cwd=str(root))
            async with Client(params) as c:
                res = await c.call_tool("create_design", {"name": "Block", "source": FEATURES, "run": False})
                self.assertFalse(res.is_error, res.content[0].text)
                body = json.loads(res.content[0].text)
                pid = body["project"]
                self.assertEqual(body["partial"]["failed"], "band")
                self.assertIn("update_design", body["next"])
                src = await c.call_tool("get_design_source", {"project": pid})
                self.assertFalse(src.is_error)
                up = await c.call_tool("update_design", {"project": pid, "feature": "band", "code": BAND_FIXED,
                                                         "run": False})
                self.assertFalse(up.is_error, up.content[0].text)
                ub = json.loads(up.content[0].text)
                self.assertNotIn("partial", ub)
                self.assertEqual([e["status"] for e in ub["build_log"]], ["checkpoint", "checkpoint", "built"])
                rm = await c.call_tool("remove_feature", {"project": pid, "feature_id": "bore"})
                self.assertFalse(rm.is_error, rm.content[0].text)
                bad = await c.call_tool("add_feature", {"project": pid, "kind": "code", "feature": "lip",
                                                        "code": "def lip(self, v, body):\n    return 1 / 0\n"})
                self.assertTrue(bad.is_error)
                self.assertIn("lip", bad.content[0].text)


class SourceEdits(unittest.TestCase):
    def test_replace_insert_delete(self):
        src = featureprog.replace_feature(FEATURES, "band", BAND_FIXED)
        self.assertIn("Pos(0, 0, 12)", src)
        self.assertEqual(featureprog.feature_ids(src), ["body", "bore", "band"])
        src = featureprog.insert_feature(src, "lip", "def lip(self, v, body):\n    return body\n", after="body")
        self.assertEqual(featureprog.feature_ids(src), ["body", "lip", "bore", "band"])
        src = featureprog.delete_feature(src, "lip")
        self.assertEqual(featureprog.feature_ids(src), ["body", "bore", "band"])
        for bad in ("def other(self, v, body):\n    return body\n", "x = 1", "def band(self):\n    pass\n"):
            with self.assertRaises(StudioError):
                featureprog.replace_feature(FEATURES, "band", bad)
        with self.assertRaises(StudioError):
            featureprog.replace_feature(THIRD_RAISES, "band", BAND_FIXED)
        with self.assertRaises(StudioError):
            featureprog.insert_feature(FEATURES, "build", "def build(self, v, body):\n    return body\n")

    def test_partial_block_round_trips(self):
        s = featureprog.partial_source(THIRD_RAISES, 2, 1, "src:abc", ["body", "bore"], "band")
        self.assertEqual(featureprog.partial_info(s), {"keep": 2, "origin": "src:abc"})
        self.assertEqual(featureprog.strip_partial(s).strip(), THIRD_RAISES.strip())


if __name__ == "__main__":
    unittest.main()
