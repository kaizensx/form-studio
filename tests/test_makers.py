"""Wave S: every makers' generator makes a real design that builds in the kernel and passes the print checks.

Each generator is made once with its default preset (and the lithophane from a picture written here) in a scratch
data folder with printing on, then geometry, exports and checks run: no check may FAIL, the part count is the
recipe's, and the design keeps its parameters and (for source generators) the MAKE record of what it was made from.
The templates also build as they are, so each one is a working design file."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from form import makers  # noqa: E402
from test_studio import make_studio  # noqa: E402


def picture(path: Path) -> Path:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), "white")
    d = ImageDraw.Draw(im)
    for k in range(8):
        d.ellipse([20 + k * 12, 10 + k * 9, 300 - k * 12, 230 - k * 9], outline=(k * 30, k * 30, k * 30), width=5)
    im.save(path)
    return path


class Catalogue(unittest.TestCase):
    def test_every_generator_is_described(self):
        cat = makers.catalogue()
        self.assertEqual({g["id"] for g in cat}, set(makers.GENERATORS))
        self.assertGreaterEqual(len(cat), 11)
        for g in cat:
            self.assertTrue(g["title"] and g["line"] and g["summary"] and g["presets"], g["id"])
            self.assertIn(g["default"], [p["id"] for p in g["presets"]])
            self.assertEqual(g["tool"], "make_" + g["id"])

    def test_source_templates_carry_make_and_params(self):
        for g in makers.GENERATORS.values():
            if g.kind != "source":
                continue
            src = makers.template_text(g.target)
            self.assertEqual(makers.read_make(src)["generator"], g.id)
            keys = makers.param_keys(src)
            for p in g.presets.values():
                self.assertLessEqual(set(p.get("values", {})), keys, f"{g.id}: preset names an unknown parameter")

    def test_text_and_picture_are_written_into_the_source(self):
        src, made = makers.source_for("name_tag", text="Ánna  K!")
        self.assertEqual(made["text"], "Ánna K!")
        self.assertEqual(makers.read_make(src)["text"], "Ánna K!")
        with self.assertRaises(makers.MakeError):
            makers.source_for("name_tag", text="   ")
        with self.assertRaises(makers.MakeError):
            makers.source_for("lithophane")
        with tempfile.TemporaryDirectory() as d:
            src, made = makers.source_for("lithophane", image=picture(Path(d) / "rings.png"))
        nx, ny, data = makers.decode_grid(makers.read_make(src))
        self.assertEqual((nx, ny), (makers.GRID, 105))
        self.assertEqual(len(data), nx * ny)
        self.assertEqual(made["picture"], "rings.png")
        self.assertEqual(len(made["sha256"]), 64)

    def test_unknown_generator_preset_and_parameter_are_refused(self):
        with self.assertRaises(makers.MakeError):
            makers.get("teapot")
        with self.assertRaises(makers.MakeError):
            makers._values(makers.get("knob"), "huge", None)


class MakeEveryGenerator(unittest.TestCase):
    """The real kernel and the real checks, one design per generator."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.st = make_studio(Path(cls.tmp.name))
        cls.pic = picture(Path(cls.tmp.name) / "rings.png")

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()
        cls.tmp.cleanup()

    def made(self, gid, **kw):
        r = makers.make(self.st, gid, purpose="print", **kw)
        p = self.st.load(r["project"])
        job = self.st.run_sync(p["id"], ["geometry", "exports", "checks"])
        self.assertEqual(job["state"], "done", f"{gid}: {job}")
        p = self.st.load(p["id"])
        checks = self.st.read(p, "checks", self.st.keys(p)["checks"])["checks"]
        fails = [(c["id"], c["value"], c.get("detail", "")[:160]) for c in checks if c["status"] == "FAIL"]
        self.assertEqual(fails, [], f"{gid}: failed print checks")
        return r, p, {c["id"]: c for c in checks}

    def test_name_tag_keychain(self):
        r, p, c = self.made("name_tag", text="MAYA", preset="keychain")
        self.assertEqual(r["make"]["text"], "MAYA")
        self.assertIn("MAYA", p["name"])
        self.assertIn("ring_d", r["parameters"])

    def test_name_tag_engraved(self):
        self.made("name_tag", text="Desk 4", preset="engraved")

    def test_lithophane_from_a_picture(self):
        r, p, c = self.made("lithophane", image=self.pic)
        self.assertEqual(r["make"]["picture"], "rings.png")
        self.assertNotIn("pixels", r["make"])

    def test_relief(self):
        self.made("lithophane", image=self.pic, preset="relief", values={"width": 80})

    def test_gridfinity_tray(self):
        r, p, c = self.made("gridfinity", preset="tray")
        self.assertEqual(p["recipe"], "gridfinity_bin")

    def test_gridfinity_baseplate(self):
        r, p, c = self.made("gridfinity", preset="baseplate")
        self.assertEqual(p["recipe"], "gridfinity_baseplate")

    def test_knob(self):
        self.made("knob", values={"shaft_d": 6.35, "flat": 0})

    def test_cable_clip(self):
        self.made("cable_clip", preset="double")

    def test_hook(self):
        self.made("hook")

    def test_phone_and_tablet_stands(self):
        self.made("stand")
        self.made("stand", preset="tablet")

    def test_drawer_divider(self):
        self.made("drawer_divider", preset="desk")

    def test_hinge_box_takes_its_clearance_from_the_fit_model(self):
        r, p, c = self.made("hinge_box")
        rev = self.st.rev(p)
        self.assertAlmostEqual(rev["values"]["clearance"], makers.hinge_clearance(self.st)[0])
        self.assertIn(rev["provenance"]["clearance"]["source"], ("assumed", "calibrated"))
        self.assertTrue(c["solid"]["status"] == "PASS")

    def test_threaded_jar_printing_and_iso(self):
        self.made("threaded_jar")
        self.made("threaded_jar", preset="iso")

    def test_spur_gears_reuse_the_gear_calculator(self):
        r, p, c = self.made("spur_gears")
        self.assertIn("CALC = ", self.st.source_text(p))


if __name__ == "__main__":
    unittest.main()
