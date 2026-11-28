"""What the window draws of a result (form/resultview.py) and the geometry that reads the engines' files
(form/app/resultgeo.py).

The description is made only from what an engine stored: an entry that never ran says "never" and carries no number;
a manufacturability check's rows, faces and fixes are the engine's own; a fix previewed saves nothing. The geometry
is checked on a field file written here to the documented format (docs/STRENGTH.md, "Field data"), with values known
in advance. Against the real kernel, in a scratch data folder."""
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "journeys"))

from form import dfm, resultview, studies  # noqa: E402
from test_studio import make_studio  # noqa: E402
import _results as R  # noqa: E402


def b64(a, dtype):
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode()


class Describe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.st = make_studio(Path(cls.tmp.name))
        cls.pid = R.design(cls.st, "Cup", R.CUP, material=None)

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()
        cls.tmp.cleanup()

    def p(self):
        return self.st.load(self.pid)

    def test_1_nothing_is_described_before_a_run(self):
        for sid, kind in (("dfm_injection", "dfm"), ("cam_3axis", "cam"), ("drawing", "drawing"), ("strength", "field")):
            d = resultview.describe(self.st, self.p(), sid)
            self.assertEqual(d["kind"], kind)
            self.assertNotEqual(d["state"], "current", sid)
            for key in ("mesh", "rows", "lines", "peak", "setups", "sheet", "headline"):
                self.assertFalse(d.get(key), f"{sid} carries {key} before it ran")
        json.dumps(resultview.describe(self.st, self.p(), "strength"))

    def test_2_entries_that_draw_nothing_and_engines_that_are_not_here(self):
        self.assertEqual(resultview.describe(self.st, self.p(), "mass")["kind"], "none")
        d = resultview.describe(self.st, self.p(), "no.such.entry")
        self.assertEqual((d["kind"], d["state"]), ("none", "unavailable"))
        self.assertEqual(set(resultview.LATER), set())          # the stack-up and topology engines are here now
        for sid, kind in (("stack", "stack"), ("topology", "topology"), ("inverse", "front"), ("print.orient", "front")):
            try:
                d = resultview.describe(self.st, self.p(), sid)
            except Exception as e:                                # noqa: BLE001
                self.fail(f"{sid}: {e}")
            if d["kind"] != "none":                               # an entry that does not apply to this design says so
                self.assertEqual(d["kind"], kind, sid)
                self.assertNotEqual(d["state"], "current", sid)

    def test_2b_a_stack_loop_is_the_engines_own(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from stack_designs import BOX_LID_SCREW
        from form.stack import tools
        pid = self.st.create_design("Box lid screw", BOX_LID_SCREW, purpose="model")["id"]
        r = tools.call(self.st, pid, a={"at": [100, 0, 0], "part": "screw"}, b={"at": [0, 0, 8]}, save=True, name="Tip",
                       tolerances={"screw_l": 0.2, "lid_t": 0.1, "hole_depth": 0.15}, samples=2000)
        d = resultview.describe(self.st, self.st.load(pid), "stack")
        self.assertEqual((d["kind"], d["state"]), ("stack", "current"))
        self.assertEqual(d["draw"], r["draw"])
        self.assertAlmostEqual(d["gap"]["nominal"], r["gap"]["nominal"], places=12)
        self.assertEqual(d["rss"], [r["rss"]["min"], r["rss"]["max"]])
        from form import studies
        self.assertEqual(studies.show(self.st, self.st.load(pid), "stack")["row"], "gap 3.000 mm")

    def test_2c_the_row_is_the_headlines_number(self):
        from form.studies import row
        self.assertEqual(row("safety factor 2.41 (at least 2.10); peak von Mises 41.2 MPa ± 3.1 %"), "SF 2.41")
        self.assertEqual(row("gap 3.000 mm; worst case 2.550 to 3.450, RSS 2.7 to 3.2; Cpk 1.20"), "gap 3.000 mm")
        self.assertEqual(row("6 pockets, 38 % lighter, 21.3 g, safety factor 2.10 (at least 1.90)"), "38 % lighter")
        self.assertEqual(row("Injection moulding: review (2 fail, 1 warn)"), "review")
        self.assertLessEqual(len(row("a very long headline with no number in it at all, and more words after")), 28)

    def test_3_a_manufacturability_check_is_the_engines_own(self):
        R.bench(self.st, self.pid, "dfm_injection", options={"resin": "abs"})
        want = dfm.check(self.st, self.p(), "injection", {"resin": "abs"})
        d = resultview.describe(self.st, self.p(), "dfm_injection")
        self.assertEqual((d["kind"], d["state"], d["verdict"]), ("dfm", "current", want["verdict"]))
        self.assertEqual([r["id"] for r in d["rows"]], [r["id"] for r in want["rows"]])
        self.assertEqual({r["id"]: r["status"] for r in d["rows"]}, {r["id"]: r["status"] for r in want["rows"]})
        faces = sorted({fc for f in want["findings"] if f["rule"] == "injection.draft" for fc in f.get("faces") or []})
        self.assertEqual(next(r for r in d["rows"] if r["id"] == "injection.draft")["faces"], faces)
        self.assertTrue(faces)
        self.assertTrue(d["not"].startswith("Not told here: "))
        self.assertEqual(d["pull"]["dir"], want["data"]["pull"])
        self.assertTrue(any(f["can"] and "injection.draft" in f["rules"] for f in d["fixes"]))
        # the overlay names the B-rep face of every triangle, so a rule's faces can be lit
        ov = json.loads(Path(d["mesh"]["file"]).read_text(encoding="utf-8"))
        fc = np.frombuffer(base64.b64decode(ov["face"]), dtype="<u4")
        tri = np.frombuffer(base64.b64decode(ov["indices"]), dtype="<u4").reshape(-1, 3)
        self.assertEqual(len(fc), len(tri))
        self.assertTrue(set(faces) <= set(fc.tolist()))
        json.dumps(d)

    def test_4_a_fix_previewed_saves_nothing_and_carries_its_geometry(self):
        head = self.p()["head"]
        out = resultview.fix_preview(self.st, self.p(), "injection", "draft", {"resin": "abs"})
        self.assertTrue(out["previewed"])
        self.assertFalse(out["applied"])
        self.assertTrue(out["view"]["mesh"])
        self.assertEqual(self.p()["head"], head)
        self.assertEqual(studies.show(self.st, self.p(), "dfm_injection")["state"], "current")

    def test_5_a_new_revision_leaves_nothing_to_draw(self):
        p = self.st.commit(self.p(), {"wall": 2.5}, "thicker", "user", None)
        d = resultview.describe(self.st, self.st.load(p["id"]), "dfm_injection")
        self.assertEqual(d["state"], "stale")
        self.assertFalse(d.get("mesh"))


class Geometry(unittest.TestCase):
    def field(self, tmp):
        """A unit square of two triangles in the plane z = 0, stress 0, 10, 20, 30 at its corners."""
        P = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32)
        T = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
        f = {"format": "form.fea.field/1", "version": 1, "positions": b64(P, "<f4"), "indices": b64(T, "<u4"),
             "face": b64([0, 0], "<u4"),
             "fields": {"von_mises": {"type": "f4", "components": 1, "data": b64([0, 10, 20, 30], "<f4")},
                        "displacement": {"type": "f4", "components": 3, "data": b64(np.tile([0, 0, 0.5], (4, 1)), "<f4")},
                        "singular": {"type": "u1", "components": 1, "data": b64([0, 0, 0, 1], "u1")}}}
        path = Path(tmp) / "x.field.json"
        path.write_text(json.dumps(f), encoding="utf-8")
        return str(path)

    def test_a_field_is_read_from_its_file(self):
        try:
            from PySide6.QtGui import QVector3D
            from form.app.resultgeo import PathGeometry, ResultGeometry
        except ImportError:
            self.skipTest("PySide6 not installed")
        with tempfile.TemporaryDirectory() as tmp:
            g = ResultGeometry()
            g.source = {"file": self.field(tmp), "kind": "field", "field": "von_mises", "lo": 0, "hi": 20, "peak": [1, 1, 0]}
            self.assertEqual(g.triangles, 2)
            self.assertEqual(g.stride(), 4 * (3 + 3 + 2 + 2 + 3))         # position, normal, two UVs, the displacement
            buf = np.frombuffer(bytes(g.vertexData()), np.float32).reshape(4, -1)
            np.testing.assert_allclose(buf[:, 6], [0, 0.5, 1, 1])          # the value on the legend's scale, clamped at the peak
            np.testing.assert_allclose(buf[:, 7], [1, 1 / np.sqrt(2), 0, 1 / np.sqrt(2)], atol=1e-6)   # distance from the peak
            np.testing.assert_allclose(buf[:, 8], [0, 0, 0, 1])           # the singular vertex
            np.testing.assert_allclose(buf[:, 10:13], np.tile([0, 0, 0.5], (4, 1)))
            self.assertAlmostEqual(g.valueAt(QVector3D(1, 0.5, 0)), 15.0, places=5)
            self.assertAlmostEqual(g.reach, float(np.sqrt(2)), places=5)
            g.source = {"file": str(Path(tmp) / "missing.json"), "kind": "field"}
            self.assertEqual(g.triangles, 0)                               # nothing is drawn of a file that is not there
            # a CNC setup's toolpaths: sorted in time, the tool found along the segment being cut
            segs = np.array([[[0, 0, 0], [10, 0, 0]], [[10, 0, 0], [10, 10, 0]]], np.float32)
            view = {"format": "form-cam-view/1", "setups": [{"toolpaths": [
                {"kind": "feed", "color": "#8fb8de", "count": 2, "positions": b64(segs, "<f4"), "t": b64([1.0, 3.0], "<f4")}]}]}
            vf = Path(tmp) / "view.json"
            vf.write_text(json.dumps(view), encoding="utf-8")
            pg = PathGeometry()
            pg.source = {"file": str(vf), "setup": 0}
            self.assertEqual((pg.segments, pg.duration), (2, 3.0))
            at = pg.at(2.0)
            self.assertEqual((round(at.x(), 5), round(at.y(), 5)), (10.0, 5.0))


if __name__ == "__main__":
    unittest.main()
