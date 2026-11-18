"""12.1 maker tools on the real kernel: text on a picked face, the geometric diff between revisions, and assembly
instructions as a PDF. Every number asserted here is compared with an independent build123d computation."""
import json
import os
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-maker-")

from build123d import Align, Box  # noqa: E402
from PIL import Image  # noqa: E402

from form import config, engrave, geomdiff, instructions, marks  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

A = (Align.CENTER, Align.CENTER, Align.MIN)

BLOCK = '''
"""A block."""
from build123d import Align, Box
from form.recipes.base import Feature, Param, Recipe, Stage


class Block(Recipe):
    title, summary = "Block", "A plain block."
    params = [Param("w", "Width", 60, 20, 120, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["w"], 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)))]
'''

ARM = '''
"""Two parts."""
from build123d import Align, Box, Pos
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage, hinge

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Lid box", "A base and a lid."
    solids = 2
    params = [Param("w", "Width", 40, 40, 40, 1, "mm", "form", "base")]
    features = [Feature("base", "Base", "structure"), Feature("lid", "Lid", "structure")]

    def build(self, v):
        s = Box(40, 40, 10, align=A)
        st = [Stage("base", s)]
        s = s + Pos(60, 0, 0) * Box(40, 40, 3, align=A)
        st.append(Stage("lid", s))
        return st

    def assembly(self, v):
        return Assembly(parts=[Part("base", "Base", 0),
                               Part("lid", "Lid", 1, move=(-60, 0, 10), explode=(0, 0, 25), attach="base", note="Press the lid on.")])
'''


class Source(unittest.TestCase):
    def test_block_round_trips(self):
        mk = engrave.mark("HI", (0, 0, 10), (0, 0, 1), 6, 0.6)
        mk["id"] = "text_1"
        src = engrave.join(BLOCK, [mk])
        self.assertIn(engrave.START, src)
        base, got = engrave.split(src)
        self.assertEqual(got, [mk])
        self.assertEqual(base.strip(), BLOCK.strip())
        self.assertEqual(engrave.join(src, []).strip(), BLOCK.strip())      # removing the last text removes the block

    def test_refuses_bad_input(self):
        with self.assertRaises(StudioError):
            engrave.mark("", (0, 0, 0), (0, 0, 1))
        with self.assertRaises(StudioError):
            engrave.mark("A", (0, 0, 0), (0, 0, 0))
        with self.assertRaises(StudioError):
            engrave.mark("A", (0, 0, 0), (0, 0, 1), depth=0)

    def test_printability_is_computed(self):
        info = engrave.printability("FORM", 6, 0.6, False, 0.4)
        self.assertGreater(info["stroke_mm"], 0)
        self.assertTrue(info["checks"])

    def test_instruction_order_follows_parents(self):
        parts = [{"id": "c", "parent": "b"}, {"id": "a", "parent": ""}, {"id": "b", "parent": "a"}]
        self.assertEqual([p["id"] for p in instructions.order(parts)], ["a", "b", "c"])


class OnTheKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Block", BLOCK)["id"]

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_1_text_is_a_feature_and_the_diff_measures_it(self):
        st = self.st
        p = st.load(self.pid)
        r = engrave.add(st, p, "FORM", at=(0, -15, 5), normal=(0, -1, 0), height=5, depth=0.8, sunk=False, expect_head=p["head"])
        p = st.load(self.pid)
        self.assertEqual(r["head"], p["head"])
        self.assertEqual([m["id"] for m in engrave.list_marks(st, p)], ["text_1"])
        self.assertIn("text_1", [f.id for f in st.recipe(p).features])
        v = st.view(p)
        self.assertIn("text_1", {m["feature"] for m in v["mesh"]})
        # independent: the same text on the same box, built here
        b = Box(60, 30, 10, align=A)
        ref = marks.emboss_text(b, "FORM", on=(0, -15, 5), normal=(0, -1, 0), height=5, depth=0.8)
        d = geomdiff.compute(st, p, 1, p["head"])
        self.assertFalse(d["same"])
        self.assertAlmostEqual(d["added"]["volume_mm3"], ref.volume - b.volume, delta=0.05)
        self.assertEqual(d["removed"]["regions"], 0)
        self.assertEqual(d["added"]["regions"], 4)                     # four separate letters stand on the face
        self.assertLess(d["added"]["bbox"][0][1], -15)                 # it stands out of the front face
        png = geomdiff.png_path(st, p, d)
        self.assertTrue(png.is_file())
        with Image.open(png) as im:
            self.assertGreater(im.width, 1000)
        self.assertEqual(geomdiff.compute(st, p, 1, p["head"]), d)     # cached

    def test_2_sunk_text_and_removal(self):
        st = self.st
        p = st.load(self.pid)
        engrave.add(st, p, "V2", at=(0, 0, 10), normal=(0, 0, 1), height=6, depth=0.5, sunk=True)
        p = st.load(self.pid)
        self.assertEqual(len(engrave.list_marks(st, p)), 2)
        d = geomdiff.compute(st, p, p["head"] - 1, p["head"])
        self.assertEqual(d["added"]["regions"], 0)
        self.assertGreater(d["removed"]["volume_mm3"], 0)
        engrave.remove(st, p, "text_1")
        p = st.load(self.pid)
        self.assertEqual([m["text"] for m in engrave.list_marks(st, p)], ["V2"])

    def test_3_text_off_the_part_is_refused(self):
        st = self.st
        p = st.load(self.pid)
        head = p["head"]
        with self.assertRaises(StudioError):
            engrave.add(st, p, "AIR", at=(0, 0, 50), normal=(0, 0, 1), height=5, depth=1)
        self.assertEqual(st.load(self.pid)["head"], head)               # nothing was saved

    def test_4_builtin_recipe_is_refused(self):
        p = self.st.create("Bin", "gridfinity_bin")
        with self.assertRaises(StudioError):
            engrave.add(self.st, p, "A", (0, 0, 0), (0, 0, 1))

    def test_5_instructions_pdf(self):
        st = self.st
        p = st.create_design("Lid box", ARM)
        out = instructions.build(st, p)
        self.assertEqual([s["part"] for s in out["steps"]], ["base", "lid"])
        self.assertEqual(out["steps"][1]["text"], "Press the lid on.")
        self.assertTrue(out["steps"][1]["from_design"])
        pdf = Path(out["pdf_path"])
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertEqual(len(out["pages"]), 3)                         # parts page + two steps
        meta = json.loads((pdf.parent / "instructions.json").read_text())
        self.assertEqual(meta["parts"], 2)

    def test_6_no_assembly_no_instructions(self):
        with self.assertRaises(StudioError):
            instructions.build(self.st, self.st.load(self.pid))


if __name__ == "__main__":
    unittest.main()
