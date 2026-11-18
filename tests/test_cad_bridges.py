"""Bridges to other CAD tools: imported reference parts, OpenSCAD designs, FreeCAD re-check and macro.

Real kernel, temp data folder. OpenSCAD runs for real when it is installed (skipped otherwise). FreeCAD is not
installed where this was written: its script generation, output parsing and check rows are tested with fixtures.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix="form-cad-")

from form import cad_bridges, checks, config  # noqa: E402
from form.design_guide import EXAMPLE, GUIDE  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

SCAD = """// Cable box with a side hole
// A FORM OpenSCAD test design.
/* [Size] */
// Inner width
width = 40; // [20:1:120]
// Inner depth
depth = 30; // [20:0.5:100]
// Wall thickness
wall = 2; // [1.2:0.1:5]
// Hole diameter
hole_d = 8; // [0:0.5:20]
// Lid angle (deg)
tilt = 0; // [0:90]
label = "box";
rounded = true;
free_number = 3;

/* [Hidden] */
$fn = 48;
secret = 5; // [1:10]

difference() {
  cube([width + 2*wall, depth + 2*wall, 20]);
  translate([wall, wall, wall]) cube([width, depth, 30]);
  if (hole_d > 0)
    translate([(width + 2*wall)/2, -1, 12]) rotate([-90,0,0]) cylinder(d=hole_d, h=wall+2);
}
"""

AROUND = '''"""A tray with a pocket cut around an imported part's bounding box."""
from build123d import Align, Box, Pos

from form.recipes.base import Feature, Param, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Tray around a part"
    params = [Param("clearance", "Clearance", 1.0, 0.2, 3, 0.1, "mm", "interface", "pocket"),
              Param("floor", "Floor", 2.0, 1.2, 5, 0.1, "mm", "form", "tray")]
    features = [Feature("tray", "Tray", "structure"), Feature("pocket", "Pocket", "interface")]

    def build(self, v):
        bb = self.reference("board.step").bounding_box()
        c, f = v["clearance"], v["floor"]
        cx, cy = (bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2
        tray = Pos(cx, cy, bb.min.Z - f) * Box(bb.size.X + 2 * c + 6, bb.size.Y + 2 * c + 6, f + 8, align=A)
        pocket = Pos(cx, cy, bb.min.Z) * Box(bb.size.X + 2 * c, bb.size.Y + 2 * c, 20, align=A)
        return [Stage("tray", tray), Stage("pocket", tray - pocket)]
'''


class ScadParams(unittest.TestCase):
    def test_customizer_comments(self):
        r = cad_bridges.parse_scad_params(SCAD)
        by = {p["key"]: p for p in r["params"]}
        self.assertEqual(list(by), ["width", "depth", "wall", "hole_d", "tilt"])
        self.assertEqual((by["width"]["min"], by["width"]["step"], by["width"]["max"], by["width"]["default"]), (20, 1, 120, 40))
        self.assertEqual(by["width"]["label"], "Inner width")
        self.assertEqual(by["width"]["group_name"], "Size")
        self.assertEqual((by["tilt"]["unit"], by["tilt"]["label"], by["tilt"]["step"]), ("°", "Lid angle", 1.0))
        fixed = {f["key"] for f in r["fixed"]}
        self.assertTrue({"label", "rounded", "free_number"} <= fixed)
        self.assertNotIn("secret", by)                       # [Hidden] ends the parameters
        self.assertNotIn("$fn", fixed)

    def test_lists_and_bad_ranges(self):
        r = cad_bridges.parse_scad_params("a = 10; // [5, 10, 20]\nb = 50; // [1:10]\ncube(a);\nc = 1; // [0:2]\n")
        by = {p["key"]: p for p in r["params"]}
        self.assertEqual((by["a"]["min"], by["a"]["max"], by["a"]["step"]), (5, 20, 5))
        self.assertIn("b", {f["key"] for f in r["fixed"]})   # default outside its range
        self.assertNotIn("c", by)                            # after the first geometry statement

    def test_title(self):
        self.assertEqual(cad_bridges.scad_title(SCAD), ("Cable box with a side hole", "A FORM OpenSCAD test design."))

    def test_value_formatting(self):
        self.assertEqual(cad_bridges._scad_value(40.0), "40")
        self.assertEqual(cad_bridges._scad_value(1.25), "1.25")


class FreeCADFixtures(unittest.TestCase):
    def test_script_is_valid_python_and_names_the_file(self):
        s = cad_bridges.freecad_check_script("/tmp/a b/part.step")
        compile(s, "form_recheck.py", "exec")
        self.assertIn("'/tmp/a b/part.step'", s)
        self.assertIn("isValid()", s)

    def test_parse_output(self):
        log = ("FreeCAD 1.0.0, Libs: 1.0.0R39109 (Git)\n(C) 2001-2024 FreeCAD contributors\n"
               'FORM_FREECAD_RESULT {"ok": true, "valid": true, "volume_mm3": 12000.5, "solids": 1, '
               '"bbox": [[0, 0, 0], [30, 20, 20]], "version": "1.0.0"}\n')
        r = cad_bridges.parse_freecad_output(log)
        self.assertTrue(r["ok"] and r["valid"])
        self.assertEqual(r["volume_mm3"], 12000.5)
        bad = cad_bridges.parse_freecad_output("Exception while processing file: foo.py\nTraceback...")
        self.assertFalse(bad["ok"])
        self.assertIn("did not report", bad["error"])

    def test_check_rows(self):
        res = {"ok": True, "valid": True, "volume_mm3": 12000.0, "solids": 1, "bbox": [[0, 0, 0], [30, 20, 20]], "version": "1.0.0"}
        row = cad_bridges.recheck_item(res, 12000.5, [[0, 0, 0], [30, 20, 20]])
        self.assertEqual((row["id"], row["status"], row["evidence"]), ("freecad", "PASS", "computed"))
        self.assertIn("not an independent proof", row["detail"])
        self.assertIn("OpenCascade", row["detail"])
        self.assertEqual(cad_bridges.recheck_item(dict(res, volume_mm3=11000), 12000, res["bbox"])["status"], "WARN")
        self.assertEqual(cad_bridges.recheck_item(dict(res, valid=False), 12000, res["bbox"])["status"], "WARN")
        self.assertEqual(cad_bridges.recheck_item({"ok": False, "error": "x"}, 1, res["bbox"])["status"], "WARN")

    def test_macro(self):
        m = cad_bridges.freecad_macro("Pi case", 3, "pi-case_r03.step", "ab" * 32,
                                      [{"key": "wall", "label": "Wall", "value": 2.0, "unit": "mm", "source": "assumed"}])
        compile(m, "x.FCMacro", "exec")
        for s in ("Spreadsheet::Sheet", "pi-case_r03.step", "Part.Shape()", "setAlias", "abab", "frozen solid"):
            self.assertIn(s, m)

    def test_missing_freecad_is_not_found_rather_than_failed(self):
        with mock.patch.object(cad_bridges, "_candidates_freecad", return_value=[]), mock.patch.object(shutil, "which", return_value=None):
            self.assertIsNone(cad_bridges.find_freecad({"cad": {"freecad": ""}}))
            self.assertFalse(cad_bridges.status({"cad": {}})["freecad"]["available"])

    def test_recheck_runs_the_script_with_a_fake_freecadcmd(self):
        """A stand-in FreeCADCmd (a Python script) proves the subprocess plumbing; real FreeCAD is not here."""
        d = Path(tempfile.mkdtemp(prefix="fc-fake-"))
        fake = d / "fake_freecadcmd.py"
        fake.write_text(
            "import json, sys\n"
            "print('FreeCAD 1.0.0 banner')\n"
            "src = open(sys.argv[1], encoding='utf-8').read()\n"
            "out = {'ok': True, 'valid': True, 'volume_mm3': 1.0, 'solids': 1, 'bbox': [[0, 0, 0], [1, 1, 1]],\n"
            "       'version': 'fake', 'script': sys.argv[1], 'reads_step': 'x.step' in src}\n"
            "print('FORM_FREECAD_RESULT ' + json.dumps(out))\n", encoding="utf-8")
        real = subprocess.run
        def run(cmd, **kw):                                  # "freecadcmd <script>" -> "python fake <script>"
            return real([sys.executable, str(fake)] + cmd[1:], **kw)
        with mock.patch.object(cad_bridges.subprocess, "run", side_effect=run):
            r = cad_bridges.freecad_recheck("freecadcmd", d / "x.step")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["script"].endswith("form_recheck.py"))
        self.assertTrue(r["reads_step"])


class Bridges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def _exported_step(self):
        p = self.st.create_design("Source box", EXAMPLE)
        job = self.st.run_sync(p["id"], ["geometry", "exports"])
        self.assertEqual(job["state"], "done", job)
        ex = self.st.read(p, "exports", self.st.keys(p)["exports"])
        step = self.st.apath(p, "exports", self.st.keys(p)["exports"]) / ex["files"]["step"]["name"]
        return p, step, self.st.head_summary(p)

    def test_step_import_roundtrip_and_companion(self):
        src, step, summ = self._exported_step()
        q = self.st.create("Holder", "hook")
        rec = self.st.import_reference(q, step, "board.step")
        self.assertEqual((rec["kind"], rec["format"], rec["evidence"]), ("part", "step", "computed"))
        for a, b in zip(sum(rec["bbox"], []), sum(summ["bbox"], [])):
            self.assertAlmostEqual(a, b, places=3)
        self.assertAlmostEqual(rec["volume_mm3"], summ["volume_mm3"], delta=summ["volume_mm3"] * 1e-6)
        q = self.st.load(q["id"])
        self.assertEqual([r["file"] for r in self.st.references(q)], ["board.step"])
        v = self.st.view(q)
        part = [c for c in v["companions"] if c.get("kind") == "part"]
        self.assertEqual(len(part), 1)
        self.assertTrue(part[0]["mesh"]["positions"] and part[0]["edges"])
        self.assertEqual(len(part[0]["size"]), 3)                # older viewers draw its box
        self.assertIn("reference", [d["kind"] for d in q["decisions"]])

    def test_design_reads_a_reference(self):
        _src, step, summ = self._exported_step()
        with self.assertRaises(StudioError) as cm:                 # not imported: a clear way forward
            self.st.create_design("Tray 3", AROUND)
        self.assertIn("Import it first", cm.exception.hint)
        shutil.copyfile(step, Path(TMP) / "board.step")
        d = self.st.create_design("Tray 4", AROUND, references=[str(Path(TMP) / "board.step")])
        job = self.st.run_sync(d["id"], ["geometry", "exports", "checks"])
        self.assertEqual(job["state"], "done", job)
        s = self.st.head_summary(self.st.load(d["id"]))
        self.assertLess(s["bbox"][0][0], summ["bbox"][0][0])       # the tray surrounds the part
        k1 = self.st.keys(self.st.load(d["id"]))["geometry"]
        # re-importing different bytes under the same name changes the geometry key
        other, _s, _ = self._exported_step()
        st2 = self.st.load(other["id"])
        st2 = self.st.commit(st2, {"inner_w": 80})
        self.st.run_sync(other["id"], ["geometry", "exports"])
        ex = self.st.read(st2, "exports", self.st.keys(st2)["exports"])
        bigger = self.st.apath(st2, "exports", self.st.keys(st2)["exports"]) / ex["files"]["step"]["name"]
        self.st.import_reference(self.st.load(d["id"]), bigger, "board.step")
        self.assertNotEqual(self.st.keys(self.st.load(d["id"]))["geometry"], k1)

    def test_stl_reference(self):
        _src, step, _summ = self._exported_step()
        stl = step.with_suffix(".stl")
        q = self.st.create("Holder STL", "hook")
        rec = self.st.import_reference(q, stl)
        self.assertEqual(rec["format"], "stl")
        self.assertGreater(rec["volume_mm3"], 0)
        self.assertGreater(rec["triangles"], 10)

    def test_rejects_other_formats(self):
        q = self.st.create("Holder bad", "hook")
        f = Path(TMP) / "thing.obj"
        f.write_text("v 0 0 0\n", encoding="utf-8")
        with self.assertRaises(StudioError):
            self.st.import_reference(q, f)
        bad = Path(TMP) / "broken.step"
        bad.write_text("not a step file", encoding="utf-8")
        with self.assertRaises(StudioError):
            self.st.import_reference(q, bad)
        self.assertFalse((self.st.dir(q["id"]) / "references" / "broken.step").exists())

    def test_freecad_macro_from_project(self):
        p, _step, _ = self._exported_step()
        name, text = self.st.freecad_macro(self.st.load(p["id"]))
        self.assertTrue(name.endswith(".FCMacro"))
        self.assertIn("inner_w", text)

    def test_no_freecad_means_no_check(self):
        with mock.patch.object(cad_bridges, "find_freecad", return_value=None):
            self.st._fc_at = 0
            p, _s, _ = self._exported_step()
            self.st.run_sync(p["id"], ["checks"])
            ch = self.st.read(p, "checks", self.st.keys(p)["checks"])
            self.assertNotIn("freecad", [c["id"] for c in ch["checks"]])

    def test_fake_freecad_adds_a_computed_check(self):
        res = {"ok": True, "valid": True, "solids": 2, "version": "fixture"}
        def fake(exe, step, timeout=120):
            self.assertTrue(Path(step).exists())
            return dict(res, volume_mm3=fake.vol, bbox=fake.bbox)
        p, _s, summ = self._exported_step()
        fake.vol, fake.bbox = summ["volume_mm3"], summ["bbox"]
        with mock.patch.object(cad_bridges, "find_freecad", return_value="/fixture/freecadcmd"), \
             mock.patch.object(cad_bridges, "freecad_recheck", side_effect=fake):
            self.st._fc_at = 0
            self.st.run_sync(p["id"], ["checks"])
            ch = self.st.read(p, "checks", self.st.keys(p)["checks"])
        self.st._fc_at = 0
        row = next(c for c in ch["checks"] if c["id"] == "freecad")
        self.assertEqual((row["status"], row["evidence"]), ("PASS", "computed"))

    @unittest.skipUnless(cad_bridges.find_openscad(), "OpenSCAD is not installed")
    def test_openscad_design_end_to_end(self):
        p = self.st.create_design("Scad box", SCAD, language="openscad", values={"width": 50})
        self.assertTrue(p["recipe"].startswith("scad:"))
        r = self.st.recipe(p)
        pub = r.public()
        self.assertTrue(pub["mesh"])
        self.assertIn("label (not a plain number)", pub["fixed_in_source"])
        job = self.st.run_sync(p["id"], ["geometry", "exports", "checks"])
        self.assertEqual(job["state"], "done", job)
        p = self.st.load(p["id"])
        s = self.st.head_summary(p)
        size = [b - a for a, b in zip(*s["bbox"])]
        self.assertAlmostEqual(size[0], 54, places=3)              # width 50 + 2 x wall 2, from -D width=50
        self.assertAlmostEqual(size[2], 20, places=3)
        ex = self.st.read(p, "exports", self.st.keys(p)["exports"])
        self.assertEqual(set(ex["files"]), {"stl", "obj", "glb"})          # no STEP; OBJ and GLB come from the mesh
        self.assertIn("mesh designs", ex["unavailable"]["step"])
        ch = {c["id"]: c for c in self.st.read(p, "checks", self.st.keys(p)["checks"])["checks"]}
        self.assertEqual(ch["solid"]["status"], "N/A")
        self.assertEqual(ch["conversion"]["status"], "N/A")
        self.assertEqual(ch["mesh"]["status"], "PASS")
        self.assertNotIn("freecad", ch)
        self.assertAlmostEqual(float(ch["wall"]["value"].split()[0]), 2.0, delta=0.05)   # ray-cast on the mesh
        v = self.st.view(p)
        self.assertTrue(v["edges"])
        with self.assertRaises(StudioError):
            self.st.freecad_macro(p)
        # parameter edit runs openscad again
        p = self.st.commit(p, {"width": 30})
        s = self.st.head_summary(p)
        self.assertAlmostEqual(s["bbox"][1][0] - s["bbox"][0][0], 34, places=3)
        # a source update keeps the language
        p = self.st.update_design(p, SCAD.replace("hole_d = 8;", "hole_d = 10;"), "bigger hole")
        self.assertTrue(p["recipe"].startswith("scad:"))
        self.assertEqual(self.st.rev(p)["values"]["width"], 30)
        self.assertIn("hole_d = 10", self.st.source_text(p))

    @unittest.skipUnless(cad_bridges.find_openscad(), "OpenSCAD is not installed")
    def test_openscad_errors_are_clear(self):
        with self.assertRaises(StudioError) as cm:
            self.st.create_design("Broken scad", "w = 10; // [1:20]\ncube(w\n", language="openscad")
        self.assertIn("OpenSCAD", str(cm.exception))
        with self.assertRaises(StudioError) as cm:
            self.st.create_design("No params", "cube(10);\n", language="openscad")
        self.assertIn("Customizer", cm.exception.hint)

    def test_openscad_missing_is_stated(self):
        with mock.patch.object(cad_bridges, "find_openscad", return_value=None):
            with self.assertRaises(StudioError) as cm:
                self.st.create_design("Scad nope", SCAD, language="openscad")
        self.assertIn("not installed", str(cm.exception))
        self.assertIn("openscad.org", cm.exception.hint)

    def test_http_routes(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from form.server import make_handler
        p, step, _ = self._exported_step()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api/projects/{p['id']}"
        try:
            req = urllib.request.Request(base + "/import_part?name=My%20Board.STEP", data=step.read_bytes(),
                                         headers={"Content-Type": "application/octet-stream"})
            rec = json.loads(urllib.request.urlopen(req).read())["reference"]
            self.assertEqual(rec["file"], "My_Board.step")
            with urllib.request.urlopen(base + "/freecad_macro") as r:
                self.assertIn("FCMacro", r.headers["Content-Disposition"])
                self.assertIn(b"Spreadsheet::Sheet", r.read())
            view = json.loads(urllib.request.urlopen(base + "/view").read())
            self.assertEqual([c["label"] for c in view["companions"] if c.get("kind") == "part"], ["My_Board.step"])
        finally:
            httpd.shutdown()

    def test_guide_documents_bridges(self):
        self.assertIn('self.reference("pi5.step")', GUIDE)
        self.assertIn('language="openscad"', GUIDE)


class ChecksNA(unittest.TestCase):
    def test_na_is_not_a_pass(self):
        items = [{"status": "N/A"}, {"status": "PASS"}]
        r = checks.rollup(items)
        self.assertEqual((r["PASS"], r["N/A"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
