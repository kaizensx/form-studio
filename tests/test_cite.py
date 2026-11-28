"""Sources are read from the tool log (form/cite.py): which calls are sources, their evidence class, the figures."""
import json
import unittest

from form import cite
from form.app.markdown import to_html


class Cite(unittest.TestCase):
    def test_class_comes_from_the_result(self):
        s = cite.source_of("strength_study", "project=p load_n=250", json.dumps({"study": "Strength, static", "rev": 7,
                           "headline": "Peak stress 14.2 MPa", "evidence": "simulated; linear static"}), True)
        self.assertEqual((s["title"], s["how"], s["figures"]), ("Strength, static on r07", "simulated", ["14.2"]))

    def test_class_by_nature(self):
        s = cite.source_of("read_document", "path=/x/ab12cd-nema ics16.pdf page=4", "{}", True)
        self.assertEqual((s["title"], s["how"]), ("nema ics16.pdf, page 4", "opened"))
        self.assertEqual(cite.source_of("fetch_link", "url=https://example.org/a.pdf", "ok", True)["title"], "example.org")

    def test_nothing_is_invented(self):
        self.assertIsNone(cite.source_of("design_guide", "topic=core", '{"text": "computed things"}', True))      # not a source tool
        self.assertIsNone(cite.source_of("strength_study", "", "{}", True))                                       # names no class
        self.assertIsNone(cite.source_of("strength_study", "", '{"evidence": "simulated"}', False))               # failed
        self.assertIsNone(cite.source_of("ask_measurement", "", '{"answered": false}', True))                     # nobody measured

    def test_a_measurement_needs_a_value(self):
        s = cite.source_of("ask_measurement", "param=width", '{"answered": true, "value": 71.4}', True)
        self.assertEqual((s["how"], s["figures"]), ("measured", ["71.4"]))

    def test_another_word_is_kept_as_it_is(self):
        self.assertEqual(cite.source_of("get_project", "", '{"evidence": "heuristic"}', True)["how"], "heuristic")

    def test_figures(self):
        self.assertEqual(cite.figures("6061-T6 yields 276.0 MPa at 20 C, r07, 1200 rpm, 3 of 4"), ["276.0", "1200"])

    def test_marks_only_numbers_that_stand_in_a_result(self):
        h = to_html("Peak 14.2 MPa against 276.0 MPa at 250 N; 14.2 again.", {"cites": [[1, ["14.2"]], [2, ["276.0"]]]})
        self.assertEqual(h.count("<sup>"), 2)
        self.assertIn("14.2 MPa<sup>", h)
        self.assertIn("276.0 MPa<sup>", h)
        self.assertNotIn("250 N<sup>", h)
        self.assertNotIn("<sup>", to_html("Peak 14.2 MPa"))

    def test_plan_and_hand_edits(self):
        self.assertEqual(cite.plan_steps(json.dumps({"steps": [{"label": "Base  plate"}, "Upright", {"x": 1}]})), ["Base plate", "Upright"])
        self.assertEqual(cite.plan_steps("not json"), [])
        ev = [{"t": "act", "by": "You", "text": "old", "change": {"to": 2}}, {"t": "end"},
              {"t": "act", "by": "You", "text": "Added Fillet 1: 2 edges", "change": {"to": 3}}, {"t": "act", "by": "codex", "text": "x"}]
        self.assertEqual(cite.hand_edits(ev), [{"text": "Added Fillet 1: 2 edges", "to": 3}])
        self.assertIn("- Added Fillet 1: 2 edges (r03)", cite.hand_note(ev))
        self.assertEqual(cite.hand_note([{"t": "end"}]), "")


if __name__ == "__main__":
    unittest.main()
