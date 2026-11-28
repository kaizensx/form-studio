"""The test plan and the results report (wave L, form/reports.py).

The plan has a test for every fit (an ISO 286 hole, an ISO 286 pair in the code, the fit window of a design with a
mating part, an assembly's mates) and every critical dimension; a report with anything unchecked is never a pass; a
measured failure is FAIL; a reading is judged against the limits it was recorded under, with provenance "measured".
Against the real kernel, in a scratch data folder."""
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from form import contract, reports, staged  # noqa: E402
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe  # noqa: E402
from test_studio import make_studio  # noqa: E402

BRACKET = '''
from build123d import Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Sensor bracket"
    params = [Param("w", "Width", 60, 30, 110, 1, "mm", "form", "body"),
              Param("t", "Plate thickness", 10, 4, 20, 0.5, "mm", "form", "body"),
              Param("sensor_w", "Sensor width", 24.6, 10, 40, 0.05, "mm", "brief", "pocket", "across the sensor's flats"),
              Param("bore", "Bearing bore Ø", 8.0075, 2, 20, 0.0001, "mm", "interface", "bore",
                    "ISO 286-1:2010 / ISO 286-2:2010 tables: H7 on Ø8, modelled at mid-tolerance"),
              Param("lip", "Lip height", 3, 1, 6, 0.1, "mm", "form", "pocket"),
              Param("slot_w", "Slot width", 6.4, 3, 12, 0.1, "mm", "form", "slots")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], 40, v["t"])

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Cylinder(v["bore"] / 2, 30)

    @feature("Pocket", role="interface")
    def pocket(self, v, body):
        from form.craft import fits
        fits.iso_fit("H7/g6", 6)
        return body - Pos(18, 0, 3) * Box(v["sensor_w"] / 2, 20, v["lip"] * 2)

    @feature("Slots")
    def slots(self, v, body):
        return body - Pos(-20, 0, 0) * Box(v["slot_w"], 12, 30)
'''


def wait(st, pid):
    jid = st.run(pid)
    while st.jobs[jid]["state"] == "running":
        time.sleep(0.2)
    return st.jobs[jid]["state"]


class Plan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.st = make_studio(Path(cls.tmp.name))
        assert Path(cls.st.root).resolve().is_relative_to(Path(cls.tmp.name).resolve())
        cls.pid = cls.st.create_design("Sensor bracket", BRACKET, purpose="model")["id"]
        staged.save_brief(cls.st, "Sensor bracket", "A sensor bracket 60 x 40 x 10 mm with a Ø8 bore",
                          requirements=["outer size 60 x 40 x 10 mm", "1 x Ø8 bore"], project=cls.pid)
        wait(cls.st, cls.pid)
        contract.prove(cls.st, cls.st.load(cls.pid))

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()
        cls.tmp.cleanup()

    def p(self):
        return self.st.load(self.pid)

    def test_1_every_fit_and_every_critical_dimension_has_a_test(self):
        pl = reports.plan(self.st, self.p())
        ids = {t["id"]: t for t in pl["tests"]}
        # fits: the ISO 286 hole made by picking, and both halves of the pair written in the code
        self.assertIn("fit.bore", ids)
        self.assertEqual((ids["fit.bore"]["lo"], ids["fit.bore"]["hi"]), (8.0, 8.015))
        self.assertEqual(ids["fit.bore"]["limits"], "8.000 to 8.015 mm")
        self.assertIn("fit.iso.H7-g6.6.hole", ids)
        self.assertEqual((ids["fit.iso.H7-g6.6.shaft"]["lo"], ids["fit.iso.H7-g6.6.shaft"]["hi"]), (5.988, 5.996))
        # every critical dimension: the brief's, the interface's, the interface feature's
        crit = reports.critical_params(self.st.recipe(self.p()), self.st.rev(self.p()))
        self.assertEqual({sp.key for sp in crit}, {"sensor_w", "bore", "lip"})
        for sp in crit:
            self.assertTrue(f"dim.{sp.key}" in ids or f"fit.{sp.key}" in ids, sp.key)
        self.assertNotIn("dim.slot_w", ids)                          # a form dimension is not critical
        # untoleranced: ISO 2768-1 m, and an instrument that meets 10:1
        t = ids["dim.sensor_w"]
        self.assertEqual((t["lo"], t["hi"]), (24.4, 24.8))
        self.assertIn("ISO 2768-1 m", t["tolerance"])
        self.assertEqual(t["instrument"], "Digital calipers")
        self.assertEqual(t["samples"], 3)
        # the brief's requirements, one test each
        self.assertIn("req.c1.x", ids)
        self.assertIn("req.c2", ids)
        self.assertIn("inspect.visual", ids)
        self.assertTrue(all(x["criterion"] and x["instrument"] for x in pl["tests"]))

    def test_2_a_measured_or_specified_value_is_critical(self):
        p = self.p()
        self.st.commit(p, {"slot_w": 6.4}, provenance={"slot_w": {"source": "measured", "instrument": "calipers"}})
        ids = {t["id"] for t in reports.plan(self.st, self.p())["tests"]}
        self.assertIn("dim.slot_w", ids)

    def test_3_the_fit_window_and_mates_are_tests(self):
        st = self.st
        pid = st.create("Stand", "device_stand", purpose="print")["id"]
        p = st.load(pid)
        ids = {t["id"]: t for t in reports.plan(st, p)["tests"]}
        self.assertIn("fit.model", ids)
        fa = st.fit(p)
        self.assertEqual((ids["fit.model"]["lo"], ids["fit.model"]["hi"]), tuple(fa["window"]))
        # mates of an assembly (a stub recipe: only its declaration is read)
        class Pinned(Recipe):
            params = [Param("d", "Pin Ø", 5, 2, 10, 0.1, "mm", "form", "pin")]
            features = [Feature("pin", "Pin", "structure")]
            fit = None

            def assembly(self, v):
                return Assembly([Part("a", "A", 0), Part("b", "B", 1)],
                                mates=[Mate("a", "b", "pin", clearance=0.15), Mate("a", "b", "press", clearance=-0.05)])
        fake = SimpleNamespace(fit=lambda p: None, _declares_assembly=lambda r: True, rid=lambda p: "pinned",
                               sources=Path(self.tmp.name) / ".sources")
        tests = reports._fit_tests(fake, {"id": "x"}, {"values": {"d": 5}, "provenance": {}}, Pinned(), set())
        mates = [t for t in tests if t["id"].startswith("fit.mate.")]
        self.assertEqual(len(mates), 2)
        self.assertIn("0.15 mm per side", mates[0]["criterion"])
        self.assertIn("interference", mates[1]["criterion"])
        self.assertEqual(mates[0]["input"], "result")

    def test_4_a_report_with_anything_unchecked_is_not_a_pass(self):
        r = reports.results(self.st, self.p())
        self.assertEqual(r["verdict"], "NOT A PASS")
        self.assertEqual(r["counts"]["measured"], 0)
        reports.record(self.st, self.pid, "fit.bore", values=[8.004, 8.009, 8.011], instrument="bore gauge", by="QA")
        r = reports.results(self.st, self.p())
        self.assertEqual(r["verdict"], "NOT A PASS")                 # one measured, the rest open
        self.assertGreater(r["counts"]["open"], 0)
        row = next(t for t in r["tests"] if t["id"] == "fit.bore")
        self.assertEqual((row["status"], row["evidence"], row["median"]), ("pass", "measured", 8.009))
        for t in r["tests"]:                                         # no number in the physical section nobody measured
            if t["status"] == "not measured":
                self.assertIsNone(t.get("values"))
                self.assertIsNone(t.get("median"))

    def test_5_all_measured_within_limits_and_nothing_open_is_a_pass_and_one_bad_reading_fails(self):
        p = self.p()
        # the brief's dimension is measured on the object (no assumed world dimension stays open)
        self.st.commit(p, {"sensor_w": 24.6}, provenance={"sensor_w": {"source": "measured", "instrument": "calipers"}})
        self.assertEqual(wait(self.st, self.pid), "done")
        contract.prove(self.st, self.p())
        pl = reports.plan(self.st, self.p())
        rows = []
        for t in pl["tests"]:
            if not t["required"]:
                continue
            if t["input"] == "number":
                mid = t["nominal"] if t["lo"] is None or t["hi"] is None else (t["lo"] + t["hi"]) / 2
                rows.append({"test_id": t["id"], **{f"reading_{i + 1}": f"{mid:.4f}" for i in range(t["samples"])},
                             "instrument_used": t["instrument"], "by": "QA"})
            else:
                rows.append({"test_id": t["id"], "result": "pass", "by": "QA"})
        # the checklist the plan writes is the form the results come back in
        csv_text = reports.checklist_csv(pl)
        import csv
        head = next(csv.reader(io.StringIO(csv_text)))
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=head)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in head})
        out = reports.record_csv(self.st, self.pid, buf.getvalue())
        self.assertEqual(len(out["recorded"]), len(rows))
        r = reports.results(self.st, self.p())
        self.assertEqual(r["open"], [], r["open"])
        self.assertEqual(r["verdict"], "PASS", r["verdict_line"])
        # one reading outside the limits is a measured failure
        reports.record(self.st, self.pid, "dim.sensor_w", values=[24.6, 24.9, 24.6], instrument="calipers")
        r = reports.results(self.st, self.p())
        self.assertEqual(r["verdict"], "FAIL")
        self.assertIn("dim.sensor_w", [f.get("id") for f in r["failures"]])
        ev = [e for e in self.p()["evidence"] if e["kind"] == "test"]
        self.assertTrue(all(e["source"] == "measured" and e["test_record"]["source"] == "measured" for e in ev))
        self.assertEqual(ev[-1]["test_record"]["limits"], {"lo": 24.4, "hi": 24.8})

    def test_6_results_are_checked_before_they_are_recorded(self):
        with self.assertRaises(Exception):
            reports.record(self.st, self.pid, "no.such.test", values=[1])
        with self.assertRaises(Exception):
            reports.record(self.st, self.pid, "inspect.visual", values=[1.0])        # a pass/fail test
        with self.assertRaises(Exception):
            reports.record(self.st, self.pid, "fit.bore")                            # nothing measured
        with self.assertRaises(Exception):
            reports.record(self.st, self.pid, "fit.bore", values=["wide"])

    def test_7_the_documents_are_real_pdf_text_in_geist(self):
        w = reports.write_plan(self.st, self.p())
        r = reports.write_report(self.st, self.p())
        import pypdfium2 as pdfium
        for f, want in ((w["files"]["TEST_PLAN.pdf"], "Checklist"), (r["files"]["RESULTS_REPORT.pdf"], r["report"]["verdict"])):
            data = Path(f).read_bytes()
            self.assertTrue(data.startswith(b"%PDF-1.7"))
            self.assertIn(b"Geist-Regular", data)
            doc = pdfium.PdfDocument(f)
            text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
            self.assertIn(want, text)
            self.assertIn("Sensor bracket", text)
        md = Path(r["files"]["RESULTS_REPORT.md"]).read_text(encoding="utf-8")
        self.assertIn(r["report"]["verdict"], md)
        self.assertIn(r["report"]["hashes"]["geometry_key"], md)
        # the Bench lists both documents and finds them made
        from form import studies
        e = {x["id"]: x for x in studies.listing(self.st, self.p(), "document")["entries"]}
        self.assertEqual(e["testplan"]["state"], "current")
        self.assertEqual(e["report"]["state"], "current")
        self.assertEqual(e["report"]["tool"], "results_report")

    def test_8_the_drawing_sets_the_limits_and_the_strength_study_the_prediction(self):
        """A fit or a general class stated on the drawing (form/drawing) replaces ISO 2768-1 m; a load test quotes the
        strength study's converged displacement with its stated error, and none from a study that did not converge."""
        from unittest import mock

        from form import drawing
        before = reports.plan_key(self.st, self.p())
        drawing.set_spec(self.st, self.pid, {"general": "f", "fits": [{"class": "g6", "at": {"param": "sensor_w"}}]})
        self.assertNotEqual(reports.plan_key(self.st, self.p()), before)           # the plan is made again
        ids = {t["id"]: t for t in reports.plan(self.st, self.p())["tests"]}
        t = ids["dim.sensor_w"]
        self.assertEqual((t["lo"], t["hi"]), (24.58, 24.593))                       # g6 at 24.6: -20 / -7 µm
        self.assertIn("ISO 286 stated on the drawing", t["tolerance"])
        self.assertIn("the drawing", t["source"])
        lip = ids["dim.lip"]
        self.assertEqual((lip["lo"], lip["hi"]), (2.95, 3.05))                      # ISO 2768-1 f at 3 mm: ±0.05
        self.assertIn("ISO 2768-1 f stated on the drawing", lip["tolerance"])
        study = {"id": "s1", "name": "Hook load", "kind": "static",
                 "loads": [{"type": "force", "faces": [[0, 0, 5]], "vector": [0, 0, -200]}]}
        solved = {"converged": True, "max_displacement_mm": 0.1234, "discretisation_error": {"displacement": 0.021},
                  "evidence": "simulated (FEA, converged)", "headline": "safety factor 4.1"}
        with mock.patch.object(reports, "_strength_defs", return_value=[study]), \
                mock.patch.object(reports, "_strength_result", return_value=solved):
            lt = [x for x in reports._load_tests(self.st, self.p()) if x["id"] == "load.s1.1"][0]
        self.assertIn("Predicted largest displacement 0.123 mm ± 2.1 %", lt["method"])
        self.assertIn("Hook load", lt["title"])
        self.assertEqual(lt["model"]["predicted_displacement_mm"], 0.1234)
        with mock.patch.object(reports, "_strength_defs", return_value=[study]), \
                mock.patch.object(reports, "_strength_result", return_value={**solved, "converged": False}):
            lt = reports._load_tests(self.st, self.p())[0]
        self.assertIn("without a prediction", lt["method"])
        self.assertNotIn("predicted_displacement_mm", lt["model"])
        drawing.set_spec(self.st, self.pid, {}, replace=True)



class Instruments(unittest.TestCase):
    def test_the_ten_to_one_rule_picks_the_instrument(self):
        self.assertEqual(reports.instrument(24.6, 24.4, 24.8)["name"], "Digital calipers")
        self.assertEqual(reports.instrument(8, 7.99, 8.0)["name"], "Outside micrometer")
        self.assertEqual(reports.instrument(8, 8.0, 8.015, inside=True)["name"], "Bore gauge or a set of pin gauges")
        self.assertEqual(reports.instrument(250, 249.5, 250.5)["name"], "Digital calipers, 300 mm")
        self.assertFalse(reports.instrument(250, 249.999, 250.001)["meets_10_to_1"])
        self.assertEqual(reports.general_tol(24.6), 0.2)
        self.assertEqual(reports.general_tol(60), 0.3)
        self.assertEqual(reports.general_tol(2), 0.1)

    def test_iso_fits_are_read_from_the_code(self):
        src = 'from form.craft import fits\nf = fits.iso_fit("H7/p6", 10)\ng = iso_fit("H8/f7", 20.0)\nh = fits.iso_fit(code, 5)\n'
        self.assertEqual([(c, d) for c, d, _ in reports.iso_fits_in_source(src)], [("H7/p6", 10.0), ("H8/f7", 20.0)])

    def test_judge_uses_the_limits_recorded(self):
        t = {"lo": 1.0, "hi": 2.0}
        self.assertEqual(reports.judge(t, {"values": [1.0, 2.0]}), "pass")
        self.assertEqual(reports.judge(t, {"values": [1.0, 2.01]}), "fail")
        self.assertEqual(reports.judge(t, {"values": []}), "fail")
        self.assertEqual(reports.judge(t, {"result": "good"}), "pass")
        self.assertEqual(reports.judge(t, {"result": "too_tight"}), "fail")
        self.assertEqual(reports.judge(t, {"values": [5], "limits": {"lo": 4, "hi": 6}}), "pass")


if __name__ == "__main__":
    unittest.main()
