"""Viewport label placement (form/app/qml/Form/Labels.js): a finding never sits on a dimension. The file is plain
JavaScript, run here in Qt's own engine; no window, no display."""
import json
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "form" / "app" / "qml" / "Form" / "Labels.js"

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

VIEW = {"l": 4, "t": 4, "r": 800, "b": 600}


def overlap(a, b, gap=0):
    return a["x"] < b["x"] + b["w"] + gap and b["x"] < a["x"] + a["w"] + gap and a["y"] < b["y"] + b["h"] + gap and b["y"] < a["y"] + a["h"] + gap


def dim(x, y, line=((0, 0), (0, 0)), w=40, h=17, prev=-1):
    """A dimension label centred on the middle of its line, with places further along it."""
    (ax, ay), (bx, by) = line
    cands = [{"x": x, "y": y}] + [{"x": ax + (bx - ax) * t - w / 2, "y": ay + (by - ay) * t - h / 2} for t in (0.3, 0.7, 0.16, 0.84)]
    return {"kind": "dim", "w": w, "h": h, "cands": cands if line != ((0, 0), (0, 0)) else cands[:1], "prev": prev}


def pin(px, py, w=150, h=19, prev=-1):
    """A marker label: right-above its point, then the other three corners (as the Viewport offers them)."""
    return {"kind": "pin", "w": w, "h": h, "prev": prev,
            "cands": [{"x": px + 9, "y": py - h - 5}, {"x": px - 9 - w, "y": py - h - 5}, {"x": px + 9, "y": py + 5}, {"x": px - 9 - w, "y": py + 5}]}


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class Labels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.js = QJSEngine()
        src = "\n".join(line for line in SRC.read_text(encoding="utf-8").splitlines() if not line.startswith(".pragma"))
        r = cls.js.evaluate(src, str(SRC))
        assert not r.isError(), r.toString()

    def place(self, items, view=VIEW):
        r = self.js.evaluate("JSON.stringify(place(%s, %s))" % (json.dumps(items), json.dumps(view)))
        self.assertFalse(r.isError(), r.toString())
        out = json.loads(r.toString())
        for o, it in zip(out, items):
            o.update(w=it["w"], h=it["h"], kind=it["kind"])
        return out

    def test_nothing_moves_when_nothing_collides(self):
        out = self.place([dim(100, 100), dim(300, 300), pin(500, 200)])
        self.assertEqual([(o["x"], o["y"], o["visible"], o["c"]) for o in out], [(100, 100, True, 0), (300, 300, True, 0), (509, 176, True, 0)])

    def test_a_marker_takes_another_corner_before_a_dimension_moves(self):
        d = dim(520, 170)                                  # right where the marker's label would go
        out = self.place([d, pin(500, 200)])
        self.assertEqual((out[0]["x"], out[0]["y"], out[0]["c"]), (520, 170, 0), "the dimension stays")
        self.assertTrue(out[1]["visible"])
        self.assertEqual(out[1]["c"], 1, "the marker's label goes to the left of its point")
        self.assertFalse(overlap(out[0], out[1], 4))

    def test_the_case_from_the_polish_pass(self):
        # "1.97 mm thinnest sample" at the dock's front-left corner sat on the 92.0 dimension: every corner of the
        # marker crosses the dimension label, so the dimension slides along its line and both read
        line = ((330, 420), (520, 640))
        d = dim(405, 521, line)
        out = self.place([d, pin(425, 530)])
        self.assertTrue(out[0]["visible"] and out[1]["visible"])
        self.assertEqual(out[1]["c"], 0, "the finding keeps its place")
        self.assertGreater(out[0]["c"], 0, "the dimension moved along its line")
        self.assertFalse(overlap(out[0], out[1], 4))

    def test_a_dimension_with_nowhere_to_go_hides_and_the_finding_stays(self):
        out = self.place([dim(405, 521), pin(425, 530)])   # a dimension with only its home place
        self.assertFalse(out[0]["visible"])
        self.assertTrue(out[1]["visible"])

    def test_findings_are_never_hidden_and_stay_in_view(self):
        items = [pin(790, 8), pin(792, 10), pin(6, 590, w=300)]
        out = self.place(items)
        for o in out:
            self.assertTrue(o["visible"])
            self.assertGreaterEqual(o["x"], VIEW["l"])
            self.assertGreaterEqual(o["y"], VIEW["t"])
            self.assertLessEqual(o["x"] + o["w"], VIEW["r"])
            self.assertLessEqual(o["y"] + o["h"], VIEW["b"])

    def test_two_findings_do_not_sit_on_each_other(self):
        out = self.place([pin(400, 300), pin(410, 304)])
        self.assertFalse(overlap(out[0], out[1], 4))

    def test_a_reference_note_gives_way_to_everything(self):
        ref = {"kind": "ref", "w": 180, "h": 19, "prev": -1, "cands": [{"x": 300, "y": 100}, {"x": 500, "y": 100}]}
        out = self.place([dim(310, 101), ref])
        self.assertEqual((out[1]["visible"], out[1]["c"]), (True, 1))
        out = self.place([dim(310, 101), dim(510, 101), ref])
        self.assertFalse(out[1 + 1]["visible"], "no free place: the note is the one that goes")
        self.assertTrue(out[0]["visible"] and out[1]["visible"])

    def test_a_label_that_moved_does_not_flicker_home(self):
        # a finding 6 px from the dimension's home: clear of it, but only just. A dimension at home stays there;
        # one that was pushed away last frame stays away until home is clear by a margin, then comes back.
        line = ((100, 108), (500, 108))
        near = {"kind": "pin", "w": 60, "h": 19, "prev": 0, "cands": [{"x": 146, "y": 100}]}
        far = {"kind": "pin", "w": 60, "h": 19, "prev": 0, "cands": [{"x": 420, "y": 300}]}
        self.assertEqual(self.place([dim(100, 100, line, prev=0), near])[0]["c"], 0)
        moved = self.place([dim(100, 100, line, prev=2), near])
        self.assertGreater(moved[0]["c"], 0)
        self.assertFalse(overlap(moved[0], moved[1], 4))
        self.assertEqual(self.place([dim(100, 100, line, prev=2), far])[0]["c"], 0)

    def test_a_point_behind_the_camera_has_no_label(self):
        out = self.place([{"kind": "pin", "w": 80, "h": 19, "cands": [], "prev": -1}, {"kind": "dim", "w": 40, "h": 17, "cands": [], "prev": -1}])
        self.assertEqual([o["visible"] for o in out], [False, False])


if __name__ == "__main__":
    unittest.main()
