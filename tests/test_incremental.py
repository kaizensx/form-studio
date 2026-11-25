"""Skeleton first, one validated feature at a time (form/featureprog.py, form/kernel.py op_try_build).

A design whose third feature raises still becomes a project with the two stages that built (a partial revision,
flagged, release blocked); its source can be read; a FeatureDesign skips a failing feature and keeps building; a
fixed feature is rebuilt alone while the features before it load from their checkpoints; stage meshes are reported
while the build runs; and the four failure shapes of the helmet transcript (a fused band, a grazing cut, a fused
crest and two touching halves fused into one) each leave a saved project with a visible shell. A feature that hangs
or crashes the kernel keeps the features before it; a multi-part design starts from a one-solid skeleton and gets a
revision per part; a checkpoint follows only its feature's code, the values it reads and its upstream."""
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
        # where each stage is in the design, for the app's "Building Bore (2 of 3)"
        self.assertEqual([(e["at"], e["of"], e["label"]) for e in ev], [(1, 3, "Body"), (2, 3, "Bore")])
        self.assertEqual((d["at"], d["of"], d["label"]), (2, 3, "Bore"))
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

    def test_2b_left_out_features_read_for_the_conversation(self):
        """The conversation shows a feature a partial build left out as one line with the measured reason
        (form/chat.py left_out), read from the design tool's result."""
        import json
        from form.chat import left_out
        st = self.st
        p = st.create_design("Left out", FEATURES, partial=True)
        part = st.rev(p)["partial"]
        rows = left_out(json.dumps({"id": p["id"], "partial": part}) + " [image]")
        self.assertEqual([r["feature"] for r in rows], ["band"])
        self.assertTrue(rows[0]["reason"])
        self.assertLessEqual(len(rows[0]["reason"]), 240)
        self.assertEqual(left_out(json.dumps({"partial": {"failed": "rim", "message": "the loft sections have 6 and 14 edges"}})),
                         [{"feature": "rim", "reason": "the loft sections have 6 and 14 edges"}])
        self.assertEqual(left_out(json.dumps({"id": p["id"], "head": 1})), [])
        self.assertEqual(left_out("not json"), [])

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


# per-feature checkpoint keys: each feature is keyed on its own code, the values it reads and its upstream
KEYS = '''
from build123d import Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


def bore_tool(r):
    return Cylinder(r, 40)


class Design(FeatureDesign):
    title = "Keyed block"
    solids = 1
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body"),
              Param("bore_r", "Bore radius", 5, 2, 8, 0.5, "mm", "form", "bore"),
              Param("lip_h", "Lip height", 4, 2, 8, 0.5, "mm", "form", "lip"),
              Param("spare", "Read by no feature", 1, 0, 9, 1, "mm", "form", "")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], v["w"], 20)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - bore_tool(v["bore_r"])

    @feature("Lip")
    def lip(self, v, body):
        return body + Pos(0, 0, -10 - v["lip_h"] / 2) * Box(10, 10, v["lip_h"])
'''

# a feature that hangs where no alarm reaches it (SIGALRM blocked, as in a long OCCT call): the kernel is stopped
HANGS = '''
from build123d import Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Hangs at the texture"
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], v["w"], 20)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Cylinder(5, 40)

    @feature("Texture", budget=2)
    def texture(self, v, body):
        import signal
        import time
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        time.sleep(120)
        return body

    @feature("Cap")
    def cap(self, v, body):
        return body + Pos(0, 0, 12) * Box(10, 10, 4)
'''

SPINS = HANGS.replace('''        import signal
        import time
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        time.sleep(120)
        return body''', '''        n = 0
        while True:                                   # Python-level: the feature's alarm stops it
            n += 1''').replace("budget=2", "budget=1")

CRASHES = HANGS.replace('''        import signal
        import time
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        time.sleep(120)
        return body''', '''        import os
        os._exit(3)                                   # the kernel process dies, as on a segfault''')

SEGFAULTS = HANGS.replace('''        import signal
        import time
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        time.sleep(120)
        return body''', '''        import ctypes
        ctypes.string_at(0)                           # a real segfault, as OCCT's C++ ends the process
        return body''')

PLAIN_HANGS = '''
from build123d import Box, Cylinder
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Plain recipe that hangs"
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure"), Feature("bore", "Bore", "interface"),
                Feature("band", "Band", "structure")]

    def build(self, v):
        import time
        body = Box(v["w"], v["w"], 20)
        stages = [Stage("body", body)]
        body = body - Cylinder(5, 40)
        stages.append(Stage("bore", body))
        time.sleep(120)
        return stages
'''

# skeleton first with several parts: one solid first, each part added as its own feature
PARTS = '''
from build123d import Box, Cylinder, Pos
from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Pod in three parts"
    solids = 3
    params = [Param("w", "Width", 40, 20, 80, 1, "mm", "form", "shell")]

    @feature("Shell", parts=1)
    def shell(self, v, body):
        return Box(v["w"], v["w"], 20)
'''
LID = '''@feature("Lid", parts=1)
def lid(self, v, body):
    return craft.parts(shell=body, lid=Pos(v["w"] + 10, 0, 0) * Box(v["w"], v["w"], 3), clearance=0.2)
'''
LENS_FUSED = '''@feature("Lens", parts=1)
def lens(self, v, body):
    return body + Pos(0, 0, 11) * Box(6, 6, 4)
'''
LENS = '''@feature("Lens", parts=1)
def lens(self, v, body):
    return craft.parts(**craft.named_parts(body), lens=Pos(0, v["w"] + 10, 0) * Cylinder(8, 3), clearance=0.2)
'''


def _log(st, p):
    return {e["feature"]: e["status"] for e in st.rev(p)["build_log"]}


class Keys(unittest.TestCase):
    """Must-fix 3: a feature's checkpoint follows its own code, the values it reads and its upstream only."""

    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_only_affected_features_rebuild(self):
        st = self.st
        p = st.create_design("Keys", KEYS)
        self.assertEqual(_log(st, p), {"body": "built", "bore": "built", "lip": "built"})
        rows = {e["feature"]: e for e in st.rev(p)["build_log"]}
        self.assertEqual(rows["lip"]["solids"], 1)                     # per feature: solid count and volume change
        self.assertLess(rows["bore"]["dvol"], 0)
        self.assertGreater(rows["lip"]["dvol"], 0)
        # `solids` changes: no feature reads it, nothing rebuilds (2 declared, 1 built: saved, flagged)
        p = st.update_design(st.load(p["id"]), KEYS.replace("solids = 1", "solids = 2"))
        self.assertEqual(_log(st, p), {"body": "checkpoint", "bore": "checkpoint", "lip": "checkpoint"})
        self.assertEqual(st.rev(p)["partial"]["parts"], {"built": 1, "declared": 2})
        p = st.update_design(st.load(p["id"]), KEYS)
        self.assertNotIn("partial", st.rev(p))
        # a parameter no feature reads
        p = st.update_design(st.load(p["id"]), KEYS, values={"spare": 5})
        self.assertEqual(_log(st, p), {"body": "checkpoint", "bore": "checkpoint", "lip": "checkpoint"})
        # a parameter only the last feature reads
        p = st.update_design(st.load(p["id"]), KEYS, values={"lip_h": 6})
        self.assertEqual(_log(st, p), {"body": "checkpoint", "bore": "checkpoint", "lip": "built"})
        # a parameter the middle feature reads: it and the feature on top of it
        p = st.update_design(st.load(p["id"]), KEYS, values={"bore_r": 6})
        self.assertEqual(_log(st, p), {"body": "checkpoint", "bore": "built", "lip": "built"})
        # a helper only the bore calls
        p = st.update_design(st.load(p["id"]), KEYS.replace("Cylinder(r, 40)", "Cylinder(r, 42)"))
        self.assertEqual(_log(st, p), {"body": "checkpoint", "bore": "built", "lip": "built"})
        # a new parameter in the list and another feature's code: the body is untouched by both
        src = KEYS.replace('Param("spare"', 'Param("extra", "Extra", 2, 0, 9, 1, "mm", "form", ""),\n              Param("spare"')
        p = st.update_design(st.load(p["id"]), src.replace("Box(10, 10, v", "Box(12, 12, v"))
        self.assertEqual(_log(st, p), {"body": "checkpoint", "bore": "checkpoint", "lip": "built"})


class Hangs(unittest.TestCase):
    """Must-fix 1: a feature that hangs or crashes the kernel never loses the features built before it."""

    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_a_hang_keeps_the_features_before_it(self):
        import time
        st = self.st
        t0 = time.monotonic()
        p = st.create_design("Hangs", HANGS)                     # no partial: a hang still saves what built
        took = time.monotonic() - t0
        part = st.rev(p)["partial"]
        self.assertEqual(part["built"], ["body", "bore"])
        self.assertEqual(part["failed"], "texture")
        self.assertEqual(part["left_out"], ["texture", "cap"])
        self.assertEqual(part["hang"]["feature"], "texture")
        self.assertGreaterEqual(part["hang"]["s"], 2.0)          # measured: past the 2 s budget, then stopped
        self.assertLess(took, 60)
        self.assertIn("did not finish", part["message"])
        rows = {x["feature"]: x for x in part["skipped"]}
        self.assertTrue(rows["cap"]["not_tried"])
        self.assertIn("texture", rows)
        self.assertFalse(st.gate(p)["ready"])
        v = st.view(p)
        self.assertEqual(sorted({m["feature"] for m in v["mesh"]}), ["body", "bore"])
        self.assertIn("upto=2", st.source_text(p))
        # the next build leaves the hung feature out at once (it is written down) and builds the one after it
        t0 = time.monotonic()
        p = st.update_design(st.load(p["id"]), featureprog.strip_partial(st.source_text(p)))
        self.assertLess(time.monotonic() - t0, 30)
        log = _log(st, p)
        self.assertEqual(log, {"body": "checkpoint", "bore": "checkpoint", "texture": "skipped", "cap": "built"})
        sk = st.rev(p)["partial"]["skipped"][0]
        self.assertIn("without building it again", sk["message"])

    def test_an_alarm_stops_a_python_loop(self):
        st = self.st
        p = st.create_design("Spins", SPINS, partial=True)
        sk = st.rev(p)["partial"]["skipped"]
        self.assertEqual([x["feature"] for x in sk], ["texture"])
        # the 1 s budget stretches with the kernel call's timeout under load (featureprog.STRETCH): the message names
        # the budget that was applied, which is never less than the 1 s the feature asked for
        import re
        m = re.search(r"within its ([0-9.]+) s budget", sk[0]["message"])
        self.assertIsNotNone(m, sk[0]["message"])
        self.assertGreaterEqual(float(m.group(1)), 1.0)
        hung = sk[0].get("hung") or {}
        if "budget" in hung:
            self.assertAlmostEqual(float(hung["budget"]), float(m.group(1)), places=3)
        self.assertIn(_log(st, p)["cap"], ("built", "checkpoint"))      # cap sits on bore, as in the hang test

    def test_a_crash_keeps_the_features_before_it(self):
        st = self.st
        p = st.create_design("Crashes", CRASHES)
        part = st.rev(p)["partial"]
        self.assertEqual(part["built"], ["body", "bore"])
        self.assertEqual(part["hang"]["kind"], "crash")
        self.assertIn("crashed", part["message"])

    def test_a_segfault_names_the_call_and_the_source_line(self):
        st = self.st
        p = st.create_design("Segfaults", SEGFAULTS)
        part = st.rev(p)["partial"]
        self.assertEqual(part["built"], ["body", "bore"])
        self.assertEqual(part["hang"]["kind"], "crash")
        self.assertIn("It crashed in string_at", part["message"])
        self.assertRegex(part["message"], r"at line \d+ of the design source: `ctypes.string_at\(0\)")

    def test_a_plain_recipe_that_hangs_keeps_its_stages(self):
        from form import studio as studio_mod
        st = self.st
        old = studio_mod.BUILD_TIMEOUT
        studio_mod.BUILD_TIMEOUT = 6
        try:
            p = st.create_design("Plain hangs", PLAIN_HANGS)
        finally:
            studio_mod.BUILD_TIMEOUT = old
        part = st.rev(p)["partial"]
        self.assertEqual(part["built"], ["body", "bore"])
        self.assertEqual(part["hang"]["kind"], "timeout")
        self.assertGreater(st.view(p)["volume_mm3"], 1000)


class Parts(unittest.TestCase):
    """Must-fix 2: a design whose final form has several parts starts from a one-solid skeleton; each part is a
    feature, every one makes a revision, and the count is checked feature by feature."""

    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_skeleton_first_with_three_parts(self):
        st = self.st
        p = st.create_design("Pod", PARTS)                       # no partial needed: 1 of 3 parts is not a failure
        self.assertEqual(st.rev(p)["partial"]["parts"], {"built": 1, "declared": 3})
        self.assertFalse(st.gate(p)["ready"])
        p = featureprog.add_code_feature(st, st.load(p["id"]), "lid", LID)
        self.assertEqual(p["head"], 2)
        self.assertEqual(st.rev(p)["partial"]["parts"], {"built": 2, "declared": 3})
        self.assertEqual(_log(st, p), {"shell": "checkpoint", "lid": "built"})
        with self.assertRaises(StudioError) as cm:               # a "part" that fuses into the shell: counted
            featureprog.add_code_feature(st, st.load(p["id"]), "lens", LENS_FUSED)
        self.assertIn("2 solid(s) where 3 are expected", str(cm.exception))
        self.assertIn("craft.parts", cm.exception.hint)
        p = featureprog.add_code_feature(st, st.load(p["id"]), "lens", LENS)
        self.assertEqual(p["head"], 3)
        self.assertNotIn("partial", st.rev(p))
        self.assertEqual(_log(st, p), {"shell": "checkpoint", "lid": "checkpoint", "lens": "built"})
        self.assertEqual(len(st.view(p)["mesh"]) > 0, True)


class HeroHelmet(unittest.TestCase):
    """The hero helmet exemplar (a FeatureDesign with an assembly and a mesh texture): its parts keep their texture
    in the view, a change to mesh_texture() or appearance() rebuilds no feature, and its checkpoints load from disk
    in a fresh kernel worker."""

    def test_texture_on_parts_and_keys_outside_features(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / "form" / "exemplars" / "hero_helmet.py").read_text(encoding="utf-8")
        st = Studio(config.load())
        try:
            p = st.create_design("Hero helmet", src)
            v = st.view(p)
            self.assertIn("mesh_texture", v)
            self.assertFalse(v["assembly"]["error"])
            self.assertTrue({"shell", "faceplate", "lens_l", "lens_r"} <= {m.get("part") for m in v["mesh"]})
            textured = {m["feature"] for m in v["mesh"] if m.get("part") == "shell"}
            self.assertIn("shell", textured)
            import base64
            tris = sum(len(base64.b64decode(m["indices"])) // 12 for m in v["mesh"])
            # the per-part meshes are the textured ones (the texture adds triangles to the plain tessellation)
            self.assertGreaterEqual(tris, 0.5 * v["mesh_texture"]["triangles"], (tris, v["mesh_texture"]))
            plain = st._k("summary", key=st.keys(p)["geometry"], recipe_id=st.rid(p), values=st.rev(p)["values"],
                          tol=0.03, p=p, timeout=300)["triangles"]
            self.assertGreater(tris, plain)                     # more than the untextured tessellation
            print(f"\nhero helmet view: {tris} triangles on parts (plain tessellation {plain}, textured "
                  f"{v['mesh_texture']['triangles']})")
            st.kernel.stop()                                     # fresh workers: every checkpoint comes from disk
            src2 = src.replace("scale=18.0", "scale=16.0").replace('"color": "#3f7f86"', '"color": "#3f7f90"')
            self.assertNotEqual(src2, src)
            p = st.update_design(st.load(p["id"]), src2)
            self.assertEqual(set(_log(st, p).values()), {"checkpoint"}, _log(st, p))
            self.assertNotIn("partial", st.rev(p))
        finally:
            st.kernel.stop()


class CheckpointNames(unittest.TestCase):
    def test_part_names_survive_the_disk(self):
        from build123d import Box, Pos
        from form import craft
        d = tempfile.mkdtemp(prefix="form-ckpt-")
        old = os.environ.get("FORM_CHECKPOINTS")
        os.environ["FORM_CHECKPOINTS"] = d
        try:
            out = craft.parts(shell=Box(10, 10, 10), lid=Pos(20, 0, 0) * Box(10, 10, 2), clearance=0.2)
            featureprog.checkpoint_put("names-test", out)
            featureprog._mem.clear()
            back = featureprog.checkpoint_get("names-test")
            self.assertEqual(list(craft.named_parts(back)), ["shell", "lid"])
            self.assertEqual(back.part_gaps, out.part_gaps)
        finally:
            if old is None:
                os.environ.pop("FORM_CHECKPOINTS", None)
            else:
                os.environ["FORM_CHECKPOINTS"] = old


class FirstFeatureHint(unittest.TestCase):
    def test_hint_follows_the_measured_cause(self):
        from form.featureprog import _problem
        self.assertIn("Return the body", _problem("not a shape", False, i=0)[1])
        self.assertIn("craft.parts", _problem(_Fake(1, 10.0), False, i=2, n0=2, v0=10.0, want=2, declared=3, adds=0)[1])
        self.assertIn("@feature(..., parts=N)", _problem(_Fake(3, 10.0), False, i=1, n0=1, v0=10.0, declared=1)[1])
        self.assertIn("volume before it", _problem(_Fake(1, 0.01), False, i=1, n0=1, v0=100.0, declared=1)[0])
        self.assertEqual(_problem(_Fake(1, 10.0), False, i=0, declared=1), ("", ""))


class _Fake:
    is_valid = True

    def __init__(self, n, vol):
        self._n, self.volume = n, vol

    def solids(self):
        return [object()] * self._n


class Drafts(unittest.TestCase):
    def test_old_drafts_are_cleaned(self):
        import time
        from pathlib import Path
        from form import studio as studio_mod
        d = Path(tempfile.mkdtemp(prefix="form-drafts-"))
        for i in range(studio_mod.DRAFT_KEEP + 5):
            (d / f"draft-{i}.json").write_text("{}")
        old = d / "draft-old.json"
        old.write_text("{}")
        t = time.time() - studio_mod.DRAFT_AGE_S - 60
        os.utime(old, (t, t))
        studio_mod.Studio._prune_drafts(d)
        left = list(d.glob("*.json"))
        self.assertEqual(len(left), studio_mod.DRAFT_KEEP)
        self.assertFalse(old.exists())


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
                good = await c.call_tool("add_feature", {"project": pid, "kind": "code", "feature": "lip",
                                                         "code": "def lip(self, v, body):\n    return body + Pos(0, 0, -12) * Box(10, 10, 4)\n"})
                self.assertFalse(good.is_error, good.content[0].text)
                gb = json.loads(good.content[0].text)
                self.assertEqual(gb["build_log"][-1]["status"], "built")
                self.assertTrue(any(x.type == "image" for x in good.content))      # the sheet, like create_design


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
