"""Engineering drawings (form/drawing): ISO 286 against the published tables, ISO 2768, GD&T rules, hidden-line views
against analytic solids, sections, dimension placement without overlaps, the AP242 PMI round trip, and the check of a
synthetic drawing with planted errors. Tests use a temporary FORM_DATA."""
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form.craft import fits as published  # noqa: E402  (ISO 286-2 table values as printed, kept since wave A)
from form.drawing import check, dims, gdt, iso286, pmi, render, scene, sheet, standards, views  # noqa: E402

MIDS = (2, 4, 8, 14, 24, 40, 65, 100, 150, 200, 280, 350, 450)     # one size inside each main step


class ISO286(unittest.TestCase):
    def test_tolerance_grades_match_the_published_table(self):
        for k, d in enumerate(MIDS):
            for g in range(5, 12):
                self.assertEqual(iso286.it(g, d)["um"], published.IT[g][k], f"IT{g} at {d} mm")

    def test_most_cells_come_from_the_formula(self):
        n = sum(iso286.it(g, d)["how"] == "formula" for d in MIDS for g in range(5, 12))
        self.assertGreaterEqual(n, 65)                       # of 91: the rest are the table's own cells

    def test_fundamental_deviations_match_the_published_table(self):
        for k, d in enumerate(MIDS):
            for L in "efgh":
                self.assertEqual(iso286.deviation(L, d)["um"], published.SHAFT_ES[L][k], f"{L} at {d}")
            for L in "kmnp":
                self.assertEqual(iso286.deviation(L, d, 6)["um"], published.SHAFT_EI[L][k], f"{L} at {d}")
        d_es = (-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230)
        for d, v in zip(MIDS, d_es):
            self.assertEqual(iso286.deviation("d", d)["um"], v, d)
        r_ei = {2: 10, 4: 15, 8: 19, 12: 23, 16: 23, 20: 28, 28: 28, 35: 34, 45: 34, 60: 41, 70: 43, 90: 51, 110: 54,
                130: 63, 150: 65, 170: 68}
        s_ei = {2: 14, 4: 19, 8: 23, 12: 28, 20: 35, 35: 43, 60: 53, 70: 59, 90: 71, 110: 79, 130: 92, 150: 100, 170: 108}
        t_ei = {28: 41, 35: 48, 45: 54, 60: 66, 70: 75, 90: 91, 110: 104}
        u_ei = {2: 18, 4: 23, 8: 28, 12: 33, 20: 41, 28: 48, 35: 60, 45: 70, 60: 87, 70: 102, 90: 124, 110: 144}
        for L, tab in (("r", r_ei), ("s", s_ei), ("t", t_ei), ("u", u_ei)):
            for d, v in tab.items():
                self.assertEqual(iso286.deviation(L, d, 6)["um"], v, f"{L} at {d}")

    def test_the_named_examples(self):
        self.assertEqual((iso286.limits("H7", 25)["lower_um"], iso286.limits("H7", 25)["upper_um"]), (0, 21))
        self.assertEqual((iso286.limits("g6", 25)["upper_um"], iso286.limits("g6", 25)["lower_um"]), (-7, -20))
        # holes by the delta rule at 25 mm (ISO 286-2): K7 +6/-15, M7 0/-21, N7 -7/-28, P7 -14/-35, S7 -27/-48
        for c, (up, lo) in {"K7": (6, -15), "M7": (0, -21), "N7": (-7, -28), "P7": (-14, -35), "S7": (-27, -48)}.items():
            lim = iso286.limits(c, 25)
            self.assertEqual((lim["upper_um"], lim["lower_um"]), (up, lo), c)
        self.assertEqual(iso286.limits("P7", 100)["upper_um"], -24)
        f = iso286.fit("H7/g6", 25)
        self.assertEqual(f["kind"], "clearance")
        self.assertEqual(f["clearance"], (0.007, 0.041))
        self.assertEqual(iso286.fit("H7/p6", 25)["kind"], "interference")
        self.assertEqual(iso286.fit("H7/k6", 25)["kind"], "transition")
        self.assertEqual(iso286.callout("H7", 25), "Ø25 H7 (+0.021/0)")

    def test_published_cells_are_where_the_table_differs_from_its_formula(self):
        # every listed cell outside the 0-3 mm step is listed because the bare formula would give another value
        for (what, g, hi), v in iso286.PUBLISHED.items():
            if hi == 3 or (what == "dev" and g in ("p", "s") and hi <= 50):
                continue
            d = hi - 0.5
            raw = iso286.it_formula(g, d) if what == "IT" else iso286._dev_formula(g, d, 6)
            rnd = iso286._rnd(raw, iso286.ROUND_IT) if what == "IT" else iso286.dev_round(g, raw)
            self.assertNotEqual(rnd, v, f"{what} {g} up to {hi} mm is listed but the formula gives the table value")
        # p is IT7 + 0 to 5 µm, and the table's choice lies in that range
        for d in MIDS[1:]:
            p = iso286.deviation("p", d, 6)["um"]
            self.assertTrue(iso286.it(7, d)["um"] <= p <= iso286.it(7, d)["um"] + 5, d)

    def test_refuses_what_it_does_not_cover(self):
        with self.assertRaises(iso286.FitError):
            iso286.limits("H7", 600)
        with self.assertRaises(iso286.FitError):
            iso286.limits("s6", 250)          # r..u verified up to 180 mm only
        with self.assertRaises(iso286.FitError):
            iso286.parse("H")


class GeneralAndGDT(unittest.TestCase):
    def test_iso2768(self):
        self.assertEqual(standards.general_linear(56, "m"), 0.3)
        self.assertEqual(standards.general_linear(7, "m"), 0.2)
        self.assertEqual(standards.general_linear(2, "f"), 0.05)
        self.assertEqual(standards.general_linear(500, "c"), 2.0)
        self.assertEqual(standards.general_break(6, "m"), 0.5)
        self.assertEqual(standards.general_break(10, "m"), 1.0)
        self.assertEqual(standards.general_flatness(56, "K"), 0.2)
        with self.assertRaises(standards.StandardError):
            standards.general_linear(0.2, "m")

    def test_frames_follow_iso_1101(self):
        self.assertEqual(gdt.validate({"type": "flatness", "value": 0.05}), [])
        self.assertTrue(gdt.validate({"type": "flatness", "value": 0.05, "datums": ["A"]}))
        self.assertTrue(gdt.validate({"type": "perpendicularity", "value": 0.02}))
        self.assertTrue(gdt.validate({"type": "position", "value": -1}))
        self.assertTrue(gdt.validate({"type": "position", "value": 0.1, "datums": ["I"]}))
        self.assertEqual(gdt.validate({"type": "position", "value": 0.1, "diameter": True, "modifier": "M",
                                       "datums": ["A", "B", "C"]}), [])
        g = gdt.frame({"type": "position", "value": 0.1, "diameter": True, "datums": ["A", "B"]}, (0, 0))
        texts = [c["s"] for c in g["children"] if c["kind"] == "text"]
        self.assertEqual(texts, ["Ø0.1", "A", "B"])


class Views(unittest.TestCase):
    def test_box_with_a_hole_front_and_top(self):
        from build123d import Box, Cylinder, Pos
        s = Box(40, 30, 10) - Pos(10, 0, 0) * Cylinder(5, 20)
        front = views.project(s, "front")
        vis = [e for e in front["edges"] if e["layer"] == "visible"]
        hid = [e for e in front["edges"] if e["layer"] == "hidden"]
        self.assertEqual(len(vis), 4)
        self.assertEqual(front["box"], [-20.0, -5.0, 20.0, 5.0])
        xs = sorted(round(e["a"][0], 6) for e in hid)       # the hole's two silhouettes, x = 10 -+ 5, dashed
        self.assertEqual(xs, [5.0, 15.0])
        self.assertTrue(all(abs(e["a"][0] - e["b"][0]) < 1e-9 for e in hid))
        top = views.project(s, "top")
        circles = [e for e in top["edges"] if e["kind"] == "circle"]
        self.assertEqual(len(circles), 1)
        self.assertEqual((circles[0]["c"], circles[0]["r"]), ([10.0, 0.0], 5.0))
        self.assertFalse([e for e in top["edges"] if e["layer"] == "hidden"])   # under the visible circle: dropped

    def test_cube_isometric(self):
        from build123d import Box
        iso = views.project(Box(10, 10, 10), "iso")
        vis = [e for e in iso["edges"] if e["layer"] == "visible"]
        hid = [e for e in iso["edges"] if e["layer"] == "hidden"]
        self.assertEqual((len(vis), len(hid)), (9, 3))
        L = sorted(round(math.dist(e["a"], e["b"]), 4) for e in vis)
        self.assertTrue(all(abs(x - 10 * math.sqrt(2 / 3)) < 1e-3 for x in L))    # every edge foreshortened alike

    def test_sphere_outline_and_cylinder_side(self):
        from build123d import Cylinder, Sphere
        sp = views.project(Sphere(7), "front")
        out = [e for e in sp["edges"] if e["layer"] == "visible"]
        self.assertTrue(out)
        import numpy as np
        P = np.vstack([views._samples(e, 33) for e in out])
        self.assertLess(abs(np.hypot(P[:, 0], P[:, 1]) - 7).max(), 1e-3)
        cy = views.project(Cylinder(4, 12), "front")
        self.assertEqual([round(x, 6) for x in cy["box"]], [-4.0, -6.0, 4.0, 6.0])

    def test_section_cut_faces(self):
        from build123d import Box, Cylinder, Pos
        s = Box(40, 30, 10) - Pos(10, 0, 0) * Cylinder(5, 20)
        sec = views.section(s, (0, 0, 0), (0, -1, 0), (1, 0, 0))
        areas = []
        for L in sec["cut_loops"]:
            a = 0.0
            for (x0, y0), (x1, y1) in zip(L, L[1:] + L[:1]):
                a += x0 * y1 - x1 * y0
            areas.append(round(abs(a) / 2, 6))
        self.assertEqual(sorted(areas), [50.0, 250.0])                   # 40x10 less the 10 mm wide hole
        self.assertFalse([e for e in sec["edges"] if e["layer"] == "hidden"])
        hatch = sheet.hatch([[list(p) for p in L] for L in sec["cut_loops"]])
        self.assertTrue(hatch)
        for h in hatch:                                                   # no hatch line inside the hole
            mx = (h["a"][0] + h["b"][0]) / 2
            self.assertFalse(5.0 + 1e-6 < mx < 15.0 - 1e-6)


def _raw(shape, sections=()):
    out = {"views": {v: views.project(shape, v, hidden=(v != "iso")) for v in ("front", "top", "right", "iso")},
           "sections": [], "measure": views.measure(shape)}
    for s in sections:
        sec = views.section(shape, s["origin"], s["normal"], s["right"])
        sec["id"] = s["id"]
        out["sections"].append(sec)
    return out


class Placement(unittest.TestCase):
    def check(self, shape, params, values, spec=None, sheets=(("A3", "first"), ("A4", "third"), ("ANSI B", "third"))):
        from form import drawing
        raw = _raw(shape, drawing.auto_section(views.measure(shape)))
        for sh, proj in sheets:
            made = drawing.make(raw, params, values, spec or {}, {"title": "Test"}, sh, proj)
            rep = made["report"]
            self.assertEqual(rep["overlaps"], [], f"{sh} {proj}")
            self.assertEqual(rep["unplaced"], [], f"{sh} {proj}")
            self.assertTrue(rep["fits_sheet"], f"{sh} {proj}")
            boxes = [scene.text_box(c) for g in scene.groups(made["sheet"], "dimension") for c in g["children"]
                     if c["kind"] == "text"]
            fr = made["sheet"]["frame"]
            for b in boxes:                                       # every text inside the frame
                self.assertTrue(fr[0] <= b[0] and b[2] <= fr[2] and fr[1] <= b[1] and b[3] <= fr[3])
        return made

    def test_plate_with_holes_baseline_and_chain(self):
        from build123d import Box, Cylinder, Pos
        s = Box(120, 50, 8)
        for x in (-45, -20, 5, 30, 48):
            s = s - Pos(x, 8, 0) * Cylinder(3, 20)
        for mode in ("baseline", "chain"):
            made = self.check(s, [], {}, {"holes": mode})
            locs = [d for d in made["plan"] if d["kind"] == "location"]
            self.assertTrue(locs)
            if mode == "chain":
                self.assertTrue(all(abs(d["to"] - d["from"]) < 30 for d in locs if d["axis"] == "x"))

    def test_bound_parameters_are_dimensioned_once(self):
        from build123d import Box, Cylinder, Pos
        s = Box(80, 40, 12) - Pos(0, 0, 0) * Cylinder(9, 30)
        params = [{"key": "w", "label": "Width", "unit": "mm", "feature": ""},
                  {"key": "t", "label": "Thickness", "unit": "mm", "feature": ""},
                  {"key": "bore", "label": "Bore", "unit": "mm", "feature": ""},
                  {"key": "n", "label": "Count", "unit": "", "feature": ""}]
        made = self.check(s, params, {"w": 80, "t": 12, "bore": 18, "n": 3})
        comp = made["report"]["completeness"]
        self.assertEqual((comp["size_params"], comp["dimensioned"], comp["twice"]), (3, 3, 0))
        shown = [d["param"] for d in made["report"]["dimensions"] if d["param"]]
        self.assertEqual(sorted(shown), ["bore", "t", "w"])

    def test_dense_part_still_clear(self):
        from build123d import Box, Cylinder, Pos
        s = Box(60, 60, 20)
        for i, (x, y) in enumerate(((-20, -20), (20, -20), (-20, 20), (20, 20), (0, 0), (0, 22))):
            s = s - Pos(x, y, 0) * Cylinder(2 + i * 0.75, 40)
        s = s - Pos(0, 0, 10) * Box(30, 8, 8)
        self.check(s, [], {})

    def test_title_block_says_nothing_it_does_not_know(self):
        from build123d import Box
        made = self.check(Box(30, 20, 10), [], {}, sheets=(("A4", "first"),))
        tb = scene.groups(made["sheet"], "title")[0]
        self.assertEqual(tb["meta"]["fields"].get("material", ""), "")
        self.assertIn("ISO 2768-mK", tb["meta"]["fields"]["tolerance"])


class PMIRoundTrip(unittest.TestCase):
    def test_write_and_read_back(self):
        from build123d import Box, Cylinder, Pos
        s = Box(40, 30, 10) - Pos(10, 0, 0) * Cylinder(5, 20)
        m = views.measure(s)
        cyl = m["cylinders"][0]["face"]
        z = {p["sense"]: p["face"] for p in m["planes"] if p["axis"] == "z"}
        x = {p["sense"]: p["face"] for p in m["planes"] if p["axis"] == "x"}
        g6 = iso286.limits("g6", 10)
        ann = [{"kind": "datum", "letter": "A", "faces": [z[-1]]},
               {"kind": "dimension", "type": "diameter", "value": 10, "upper": g6["upper_um"] / 1000,
                "lower": g6["lower_um"] / 1000, "fit": "g6", "faces": [cyl]},
               {"kind": "dimension", "type": "linear", "value": 40, "upper": 0.3, "lower": -0.3, "faces": [x[-1]],
                "faces2": [x[1]]},
               {"kind": "gdt", "type": "flatness", "value": 0.05, "faces": [z[1]]},
               {"kind": "gdt", "type": "position", "value": 0.1, "diameter": True, "modifier": "M", "datums": ["A"],
                "faces": [cyl]}]
        d = Path(tempfile.mkdtemp())
        try:
            f = d / "part.step"
            written = pmi.write(s, str(f), ann)
            back = pmi.read(str(f))
            self.assertTrue(back["schema"].startswith("AP242"))
            rows = pmi.compare(written, back)
            self.assertEqual([r["status"] for r in rows], ["PASS"] * len(ann), rows)
            dia = next(r for r in back["dimensions"] if r["type"] == "diameter")
            self.assertEqual((dia["min"], dia["max"]), (g6["min"], g6["max"]))      # the sign of g6 survives
            # a wrong expectation fails: the same file, compared with a 0.06 flatness
            bad = [dict(w) for w in written]
            bad[3]["value"] = 0.06
            self.assertEqual(pmi.compare(bad, back)[3]["status"], "FAIL")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class CheckParsing(unittest.TestCase):
    def test_dimension_texts(self):
        self.assertEqual(check.parse("4× Ø5.5")["count"], 4)
        p = check.parse("Ø26.15 H7 (+0.021/0)")
        self.assertEqual((p["kind"], p["value"], p["class"], p["upper"], p["lower"]), ("diameter", 26.15, "H7", 0.021, 0.0))
        self.assertEqual(check.parse("R6")["kind"], "radius")
        self.assertEqual(check.parse("12,5 ±0,1")["upper"], 0.1)
        for not_dim in ("Ra 1.6", "1:1", "2026-11-28", "r01", "A–A", "M6"):
            self.assertIsNone(check.parse(not_dim), not_dim)

    def test_judging(self):
        cands = [{"id": "a", "kind": "linear", "value": 56.0, "features": ["plate"]},
                 {"id": "b", "kind": "diameter", "value": 26.15, "count": 1, "features": ["seat"]},
                 {"id": "c", "kind": "diameter", "value": 5.5, "count": 4, "features": ["screws"]}]
        rows = [check.parse("56"), check.parse("58"), check.parse("Ø26.15 H7"), check.parse("4× Ø5.5"),
                check.parse("2× Ø5.5")]
        for r in rows:
            r["read"] = "pdf text"
        rows.append({"text": "5?", "read": "agent", "value": None, "kind": "linear", "unparsed": True})
        rows.append({**check.parse("56"), "read": "agent", "agent_unsure": True, "box_frac": [0, 0, 1, 1]})
        res = check.judge(rows, cands, "m")
        self.assertEqual([r["status"] for r in res], ["PASS", "FAIL", "PASS", "PASS", "FAIL", "UNSURE", "UNSURE"])


TMP = tempfile.mkdtemp(prefix="form-drawing-")


class StudioDrawing(unittest.TestCase):
    """The bearing flange exemplar end to end: the drawing, its bindings, PMI, and a check of a drawing with
    planted errors. Real kernel, temporary FORM_DATA."""
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())
        src = (ROOT / "form" / "exemplars" / "bearing_flange.py").read_text(encoding="utf-8")
        cls.p = cls.st.create_design("Bearing flange", src, purpose="model")

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        shutil.rmtree(TMP, ignore_errors=True)

    def build(self):
        from form import drawing
        return drawing.build(self.st, self.st.load(self.p["id"]))

    def test_drawing(self):
        d = self.build()
        rep = d["report"]
        self.assertEqual(rep["overlaps"], [])
        self.assertEqual(rep["unplaced"], [])
        comp = rep["completeness"]
        self.assertEqual(comp["twice"], 0)
        b = {r["param"]: r for r in rep["bindings"]}
        for k in ("side", "t", "screw_sq", "r"):
            self.assertEqual(b[k]["status"], "proved", k)
        self.assertEqual(b["bearing"]["status"], "not a size")
        self.assertIn("boss_wall", [x["param"] for x in comp["not_shown"]])
        fit = rep["fits"][0]
        self.assertEqual((fit["class"], fit["upper_um"], fit["lower_um"]), ("H7", 21, 0))
        self.assertEqual(rep["annotations"], {"datums": 2, "gdt": 3, "surface": 1})
        for k in ("pdf", "svg", "dxf", "png", "scene"):
            self.assertTrue(Path(d["paths"][k]).is_file(), k)
        self.assertTrue(Path(d["paths"]["pdf"]).read_bytes().startswith(b"%PDF"))
        sc = json.loads(Path(d["paths"]["scene"]).read_text())
        roles = {g["role"] for g in scene.groups(sc)}
        self.assertTrue({"view", "section", "detail", "dimension", "gdt", "datum", "surface", "title",
                         "cutting_plane"} <= roles, roles)
        import ezdxf
        doc = ezdxf.readfile(d["paths"]["dxf"])
        self.assertIn("HIDDEN", [L.dxf.name for L in doc.layers])
        dxf_texts = {e.dxf.text for e in doc.modelspace().query("TEXT")}
        self.assertIn("Ø26.15 H7 (+0.021/0)", dxf_texts)

    def test_pmi(self):
        from form import drawing
        out = drawing.export_pmi(self.st, self.st.load(self.p["id"]))
        self.assertTrue(out["schema"].startswith("AP242"))
        self.assertEqual(out["passed"], out["written"])
        self.assertGreaterEqual(out["written"], 10)

    def test_check_a_drawing_with_planted_errors(self):
        d = self.build()
        sc = json.loads(Path(d["paths"]["scene"]).read_text())
        planted = {"56": "58", "4× Ø5.5": "4× Ø6"}
        done = set()

        def edit(n, depth, parent):
            if n["kind"] == "text" and n["s"] in planted and n["s"] not in done:
                done.add(n["s"])
                n["s"] = planted[n["s"]]
        scene.walk(sc, edit)
        out_dir = Path(TMP) / "theirs"
        out_dir.mkdir(exist_ok=True)
        pdf = out_dir / "theirs.pdf"
        render.qt(render.themed(sc, "paper"), pdf=str(pdf))
        res = check.run(self.st, self.st.load(self.p["id"]), str(pdf))
        fails = sorted(r["text"] for r in res["rows"] if r["status"] == "FAIL")
        self.assertEqual(fails, ["4× Ø6", "58"])
        self.assertGreaterEqual(res["counts"]["PASS"], 10)
        for r in res["rows"]:
            self.assertTrue(r.get("crop") and Path(r["crop"]).is_file(), r["text"])
            if r["status"] == "UNSURE":
                self.assertIsNone(r.get("model"))
        self.assertTrue(any(r.get("lit") for r in res["rows"]))
        # the same sheet as DXF reads exactly
        dx = check.run(self.st, self.st.load(self.p["id"]), d["paths"]["dxf"])
        self.assertEqual(dx["counts"]["FAIL"], 0)
        # an image: nothing is read without the agent's rows, and a row the reader is unsure of stays UNSURE
        png = d["paths"]["png"]
        none = check.run(self.st, self.st.load(self.p["id"]), png)
        self.assertEqual(none["rows"], [])
        self.assertIn("OCR", none["note"])
        rows = [{"text": "Ø26.15 H7", "box": [0.5, 0.45, 0.62, 0.49]}, {"text": "5?", "box": [0.1, 0.1, 0.2, 0.2]},
                {"text": "40", "box": [0.4, 0.47, 0.45, 0.5], "unsure": True}, {"text": "56"}]
        ag = check.run(self.st, self.st.load(self.p["id"]), png, rows)
        self.assertEqual([r["status"] for r in ag["rows"]], ["PASS", "UNSURE", "UNSURE", "UNSURE"])

    def test_spec_and_editing_a_dimension(self):
        from form import drawing
        with self.assertRaises(drawing.DrawingError):
            drawing.set_spec(self.st, self.p["id"], {"gdt": [{"type": "flatness", "value": 0.1, "datums": ["A"],
                                                              "at": {"face": 0}}]})
        d = self.build()
        side = next(x for x in d["report"]["dimensions"] if x["param"] == "side")
        out = drawing.set_dimension(self.st, self.st.load(self.p["id"]), side["id"], 60)
        self.assertEqual(out["param"], "side")
        p = self.st.load(self.p["id"])
        self.assertEqual(self.st.rev(p)["values"]["side"], 60)
        model = next(x for x in d["report"]["dimensions"] if not x["param"])
        with self.assertRaises(drawing.DrawingError):
            drawing.set_dimension(self.st, p, model["id"], 1)


if __name__ == "__main__":
    unittest.main()
