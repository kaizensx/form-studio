"""Sheet metal and cut parts (form/sheet): unfold against analytic flat lengths, the fold-back proof, DXF round trips
with ezdxf, the cut-file checker's rules each on both sides of its limit, bend order on a box with a stated brake
model, the service preflight, flat profiles with kerf, and the Studio, CLI and manufacturability wiring.

In process (build123d solids, no worker): the L-bracket and U-channel flats equal Σ flats + Σ θ·(r + K·t) to 1e-6
mm with K from each method; every part folds back onto itself within 1e-9 mm; what cannot be unfolded says why.
Through a Studio on a temporary FORM_DATA (with the kernel worker): a tray designed with form.sheet.build is
unfolded, its DXF written and checked, its bends ordered, preflighted, and judged as manufacturability's
sheet_metal process."""
import datetime as dt
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-sheet-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ezdxf  # noqa: E402
import numpy as np  # noqa: E402

from form.dfm import rules  # noqa: E402
from form.sheet import analysis, brake, cutcheck, dxf, geom2d, ops, preflight, tables, unfold  # noqa: E402
from form.sheet.build import Sheet, SheetError  # noqa: E402


def kf(material="steel_mild", method=None, k=None):
    return ops.kfactor_fn({"material": material, "method": method, "k": k})


def rect(s, w, d):
    return s.base([(0, 0), (w, 0), (w, d), (0, d)])


def L_bracket(t=2.0, r=3.0, a=50.0, b=30.0, width=40.0, up=True):
    s = Sheet(t=t, r=r)
    base = rect(s, a, width)
    s.flange(base.edge(1), length=b, angle=90, up=up)
    return s


def U_channel(t=1.5, r=2.0, web=40.0, leg=25.0, width=60.0):
    s = Sheet(t=t, r=r)
    base = s.base([(0, 0), (web, 0), (web, width), (0, width)])
    s.flange(base.edge(1), leg, 90)
    s.flange(base.edge(3), leg, 90)
    return s


def box(t=1.0, r=1.0, w=60.0, d=40.0, h=15.0):
    s = Sheet(t=t, r=r)
    b = rect(s, w, d)
    for i in range(4):
        s.flange(b.edge(i), h, 90)
    return s


class Tables(unittest.TestCase):
    def test_every_source_is_complete(self):
        for src in tables.bend_table()["sources"].values():
            for k in ("title", "publisher", "url", "published", "read"):
                self.assertTrue(src.get(k), f"{src['id']} has no {k}")
        for sid in tables.services():
            for src in tables.service(sid)["sources"].values():
                for k in ("title", "publisher", "url", "published", "read"):
                    self.assertTrue(src.get(k), f"{sid}: {src['id']} has no {k}")

    def test_generic_table_by_class_and_band(self):
        self.assertEqual(tables.kfactor(1.0, 1.0, "steel_mild")["K"], 0.38)      # r/t = 1: first band, medium
        self.assertEqual(tables.kfactor(2.0, 1.0, "steel_mild")["K"], 0.43)
        self.assertEqual(tables.kfactor(4.0, 1.0, "steel_mild")["K"], 0.50)
        self.assertEqual(tables.kfactor(1.0, 1.0, "al_5052_h32")["K"], 0.33)     # soft
        self.assertEqual(tables.kfactor(1.0, 1.0, "steel_304", forming="bottoming")["K"], 0.46)
        r = tables.kfactor(1.0, 1.0, "steel_mild")
        self.assertEqual(r["class_evidence"], "assumed")
        self.assertIn("Wikipedia", r["source"])
        self.assertIn("medium column", tables.kfactor(1.0, 1.0)["note"])

    def test_din6935_and_a_shops_value(self):
        self.assertAlmostEqual(tables.kfactor(1.0, 1.0, method="din6935")["K"], 0.325, places=9)
        self.assertAlmostEqual(tables.kfactor(2.0, 1.0, method="din6935")["K"],
                               (0.65 + 0.5 * math.log10(2)) / 2, places=5)
        hi = tables.kfactor(50.0, 1.0, method="din6935")
        self.assertEqual(hi["K"], 0.5)
        self.assertIn("unsourced", hi["note"])
        v = tables.kfactor(1.0, 1.0, k=0.41)
        self.assertEqual((v["K"], v["evidence"]), (0.41, "specified"))

    def test_rule_tables_cite_their_sources(self):
        for pid in ("sheet_metal", "cut_laser", "cut_waterjet", "cut_router"):
            t = rules.table(pid)
            for r in t["rules"]:
                src = r.get("source")
                self.assertTrue(src in t["sources"] or src in ("computed", "unsourced"), f"{r['id']}: {src}")
                if src in t["sources"]:
                    self.assertTrue(r.get("quote"), f"{r['id']} quotes its source")
            self.assertNotIn(pid if pid.startswith("cut_") else "x", rules.processes())


class Builder(unittest.TestCase):
    def test_features_build_one_valid_solid(self):
        s = Sheet(t=1.0, r=1.0)
        b = rect(s, 60, 40)
        f = s.flange(b.edge(0), 15, 90, start=10, end=10, relief="obround")
        s.hem(f.far(), 6)
        s.jog(b.edge(2), offset=6, length=20, up=False)
        s.flange(b.edge(1), 12, 60, relief="rect", start=5)
        so = s.solid()
        self.assertTrue(so.is_valid)
        self.assertEqual(len(so.solids()), 1)
        self.assertEqual(s.describe()["reliefs"], 3)

    def test_impossible_features_say_why(self):
        s = Sheet(t=1.0, r=1.0)
        b = rect(s, 60, 40)
        with self.assertRaises(SheetError):
            s.jog(b.edge(0), offset=1.0, length=10)          # two bends need at least (2r + t)(1 - cos θ) = 3 mm
        with self.assertRaises(SheetError):
            s.flange(b.edge(0), 10, 200)
        s.flange(b.edge(0), 10)
        with self.assertRaises(SheetError):
            s.flange(b.edge(0), 10)


class Unfold(unittest.TestCase):
    def test_L_bracket_against_its_analytic_flat_length(self):
        for method, k in ((None, None), ("din6935", None), (None, 0.5)):
            res = unfold.unfold(L_bracket().solid(), kf(method=method, k=k))
            K = tables.kfactor(3.0, 2.0, "steel_mild", method, k=k)["K"]
            want = 50 + 30 + math.pi / 2 * (3.0 + K * 2.0)
            self.assertTrue(res["ok"], res["reasons"])
            self.assertAlmostEqual(res["size_mm"][0], want, places=6)
            self.assertAlmostEqual(res["size_mm"][1], 40.0, places=6)
            self.assertAlmostEqual(res["area_mm2"], want * 40.0, places=4)
            b = res["bends"][0]
            self.assertAlmostEqual(b["angle"], 90.0, places=6)
            self.assertEqual((b["direction"], b["r"], b["K"]), ("up", 3.0, K))
            self.assertAlmostEqual(b["allowance"], math.pi / 2 * (3.0 + K * 2.0), places=9)

    def test_down_bend_reads_the_inside_radius_from_the_partner(self):
        res = unfold.unfold(L_bracket(up=False).solid(), kf())
        b = res["bends"][0]
        self.assertTrue(res["ok"], res["reasons"])
        self.assertAlmostEqual(b["r"], 3.0, places=9)
        K = tables.kfactor(3.0, 2.0, "steel_mild")["K"]
        self.assertAlmostEqual(res["size_mm"][0], 80 + math.pi / 2 * (3 + 2 * K), places=6)

    def test_U_channel(self):
        res = unfold.unfold(U_channel().solid(), kf(method="din6935"))
        K = (0.65 + 0.5 * math.log10(2.0 / 1.5)) / 2
        want = 25 + 40 + 25 + 2 * math.pi / 2 * (2.0 + K * 1.5)
        self.assertTrue(res["ok"], res["reasons"])
        self.assertAlmostEqual(max(res["size_mm"]), want, places=6)
        self.assertEqual(len(res["bends"]), 2)
        self.assertEqual({b["direction"] for b in res["bends"]}, {"up"})

    def test_every_part_folds_back_onto_itself(self):
        parts = {"L": L_bracket(), "U": U_channel(), "box": box()}
        s = Sheet(t=1.0, r=1.0)
        b = rect(s, 60, 40)
        f = s.flange(b.edge(0), 15, 90, start=10, end=10, relief="obround")
        s.hem(f.far(), 6)
        s.jog(b.edge(2), offset=6, length=20, up=False)
        s.flange(b.edge(1), 12, 60, start=5)
        parts["mixed"] = s
        for name, part in parts.items():
            res = unfold.unfold(part.solid(), kf())
            self.assertTrue(res["ok"], f"{name}: {res['reasons']}")
            self.assertLess(res["verify"]["max_mm"], 1e-9, name)
            self.assertGreater(res["verify"]["samples"], 50, name)
            self.assertLess(res["volume_rel_err"], 1e-6, name)
            self.assertEqual([lp["depth"] for lp in res["loops"]].count(0), 1, name)
            self.assertFalse(res["open_ends"], name)
            # no slivers: the builder's reliefs meet the sheet cleanly (a cut checker found one once)
            self.assertGreater(min(geom2d.length(e) for e in res["entities"]), 0.01, name)

    def test_fold_detects_a_wrong_flat(self):
        # the check is not circular: a flat with a wrong K folds back off the part
        res = unfold.unfold(L_bracket().solid(), kf())
        bends = {b["id"]: dict(b) for b in res["bends"]}
        bid = next(iter(bends))
        good = bends[bid]
        P = np.array([[good["q"][0] + good["d"][0] * (good["w"] + 10), good["q"][1] + 5]])
        from form.sheet import fold
        X0 = fold.fold(P, 0.0, [bid], None, bends)
        X2 = fold.fold(P, 0.0, [bid], None, {bid: dict(good, w=good["w"] + 0.2)})
        self.assertAlmostEqual(float(np.linalg.norm(X0 - X2)), 0.2, places=9)

    def test_what_cannot_be_unfolded_says_why(self):
        s = Sheet(t=1.0, r=1.0)
        b = rect(s, 60, 40)
        s.flange(b.edge(1), 15)
        s.louvre(b, (30, 20), 20, 5, 2)
        res = unfold.unfold(s.solid(), kf())
        self.assertFalse(res["ok"])
        self.assertTrue(any("formed feature" in r["why"] for r in res["reasons"]))
        self.assertTrue(unfold.unfold(s.solid(forms=False), kf())["ok"])
        self.assertEqual(s.marks()[0]["kind"], "louvre")
        from build123d import Box, Pos
        step = Box(40, 30, 2) + Pos(10, 0, 1.5) * Box(20, 30, 1)          # two thicknesses
        res = unfold.unfold(step, kf())
        self.assertFalse(res["ok"])
        self.assertTrue(res["reasons"])
        plate = Pos(0, 0, 1) * Box(40, 30, 2)
        edge = [e for e in plate.edges() if abs(e.center().Z - 2) < 1e-6 and abs(e.center().X - 20) < 1e-6]
        res = unfold.unfold(plate.fillet(0.5, edge), kf())
        self.assertFalse(res["ok"])
        self.assertTrue(any("edge round" in r["why"] for r in res["reasons"]))

    def test_flat_measures_for_the_rules(self):
        s = Sheet(t=1.5, r=1.5)
        b = rect(s, 80, 50)
        s.flange(b.edge(1), 4.0)                                  # under 4 t = 6 mm
        f = s.flange(b.edge(3), 20.0)
        s.hem(f.far(), 9.0, gap=0.75)                             # inside diameter 0.75 < t
        from build123d import Cylinder, Pos
        solid = s.solid() - Pos(75, 25, 0) * Cylinder(1.0, 10)   # d 2 mm, 5 mm from the bend
        res = unfold.unfold(solid, kf())
        m, _d = analysis.measures(res)
        ev = rules.evaluate("sheet_metal", {"measures": m}, {"t": res["t"], "t_band": "thick"})
        rows = {r["id"]: r for r in ev["rows"]}
        self.assertEqual(rows["sheet.unfold"]["status"], "pass")
        self.assertEqual(rows["sheet.flange"]["status"], "fail")
        self.assertAlmostEqual(rows["sheet.flange"]["value"], 4.0, places=6)
        self.assertEqual(rows["sheet.hem"]["status"], "fail")
        self.assertEqual(rows["sheet.hole"]["status"], "pass")                  # 2 ≥ 1.5
        self.assertEqual(rows["sheet.hole_bend"]["status"], "warn")             # 4 mm < 6 mm
        self.assertEqual(rows["sheet.bend_r"]["status"], "info")


def _doc(lines=(), circles=(), arcs=(), units=4, layer="CUT"):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = units
    msp = doc.modelspace()
    for a, b, *lay in lines:
        msp.add_line(a, b, dxfattribs={"layer": lay[0] if lay else layer})
    for c, r, *lay in circles:
        msp.add_circle(c, r, dxfattribs={"layer": lay[0] if lay else layer})
    for c, r, a0, a1 in arcs:
        msp.add_arc(c, r, a0, a1, dxfattribs={"layer": layer})
    return doc


def _square(x0=0, y0=0, w=100, h=60, layer="CUT"):
    p = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    return [(p[i], p[(i + 1) % 4], layer) for i in range(4)]


class CutCheck(unittest.TestCase):
    def check(self, doc, process="cut_laser", opts=None):
        path = Path(TMP) / f"cut-{id(doc)}.dxf"
        doc.saveas(str(path))
        res = cutcheck.check_file(path, process, opts if opts is not None else {"t": 2.0})
        return {r["id"]: r for r in res["rows"]}, res

    def test_a_clean_file_passes(self):
        rows, res = self.check(_doc(_square(), circles=[((30, 30), 3.0)]))
        self.assertEqual(res["verdict"], "pass", [r for r in rows.values() if r["status"] != "pass"])
        self.assertEqual(rows["laser.hole"]["value"], 6.0)

    def test_open_contour(self):
        sq = _square()[:3]
        rows, _ = self.check(_doc(sq))
        self.assertEqual(rows["cut.closed"]["status"], "fail")
        self.assertAlmostEqual(rows["cut.closed"]["value"], 60.0, places=6)

    def test_duplicate_and_overlapping_lines(self):
        rows, _ = self.check(_doc(_square() + [((10, 0), (40, 0))]))
        self.assertEqual(rows["cut.duplicates"]["status"], "fail")
        self.assertAlmostEqual(rows["cut.duplicates"]["value"], 30.0, places=6)
        rows, _ = self.check(_doc(_square(), circles=[((30, 30), 3.0), ((30, 30), 3.0)]))
        self.assertEqual(rows["cut.duplicates"]["status"], "fail")

    def test_crossing_contours(self):
        rows, _ = self.check(_doc(_square() + _square(80, 20, 40, 20)))
        self.assertEqual(rows["cut.crossing"]["status"], "fail")

    def test_tiny_segment(self):
        p = _square()
        p[0] = ((0, 0), (99.98, 0), "CUT")
        p.insert(1, ((99.98, 0), (100, 0), "CUT"))
        rows, _ = self.check(_doc(p))
        self.assertEqual(rows["cut.tiny"]["status"], "warn")
        self.assertEqual(rows["cut.tiny"]["source"], "unsourced")

    def test_text_must_be_outlines(self):
        doc = _doc(_square())
        doc.modelspace().add_text("PART 7", dxfattribs={"layer": "CUT", "height": 5}).set_placement((20, 20))
        rows, _ = self.check(doc)
        self.assertEqual(rows["cut.text"]["status"], "fail")
        doc = _doc(_square())
        doc.modelspace().add_text("note", dxfattribs={"layer": "NOTES", "height": 5}).set_placement((20, 20))
        rows, _ = self.check(doc)
        self.assertEqual(rows["cut.text"]["status"], "pass")

    def test_cut_layers_and_units(self):
        rows, res = self.check(_doc(_square(), circles=[((30, 30), 3.0, "HOLES")]))
        self.assertEqual(rows["cut.layers"]["status"], "warn")
        self.assertIn("HOLES", res["layers_assumed_cut"])
        rows, _ = self.check(_doc(_square(), units=5))                     # centimetres
        self.assertEqual(rows["cut.units"]["status"], "fail")
        rows, res = self.check(_doc(_square(0, 0, 4, 2.4), units=1))        # inches: read in mm
        self.assertEqual(res["units"]["units"], "in")
        self.assertAlmostEqual(res["data"]["part_sizes_mm"][0][1], 101.6, places=6)

    def test_holes_against_thickness_edge_and_bend(self):
        rows, _ = self.check(_doc(_square(), circles=[((30, 30), 0.7)]), opts={"t": 3.0})   # 1.4 < 1.5
        self.assertEqual(rows["laser.hole"]["status"], "fail")
        rows, _ = self.check(_doc(_square(), circles=[((30, 30), 0.7)]), opts={})
        self.assertEqual(rows["laser.hole"]["status"], "not_checked")
        rows, res = self.check(_doc(_square(), circles=[((30, 30), 0.7)]), opts={})
        self.assertEqual(res["verdict"], "not proven")
        rows, _ = self.check(_doc(_square(), circles=[((3, 30), 1.5)]), opts={"t": 2.0})    # 1.5 mm to the edge
        self.assertEqual(rows["laser.hole_edge"]["status"], "warn")
        rows, _ = self.check(_doc(_square() + [((50, 0), (50, 60), "BEND_UP")], circles=[((55, 30), 1.5)]),
                             opts={"t": 2.0})                                                 # 3.5 mm < 8 mm
        self.assertEqual(rows["laser.hole_bend"]["status"], "warn")
        self.assertAlmostEqual(rows["laser.hole_bend"]["value"], 3.5, places=6)

    def test_router_and_waterjet_corners_and_holes(self):
        rows, _ = self.check(_doc(_square()), "cut_router", {})
        self.assertEqual(rows["router.corner"]["status"], "n/a")           # outer corners are not inside corners
        notch = [((0, 0), (100, 0)), ((100, 0), (100, 60)), ((100, 60), (60, 60)), ((60, 60), (60, 30)),
                 ((60, 30), (40, 30)), ((40, 30), (40, 60)), ((40, 60), (0, 60)), ((0, 60), (0, 0))]
        rows, _ = self.check(_doc([(a, b, "CUT") for a, b in notch]), "cut_router", {})
        self.assertEqual(rows["router.corner"]["status"], "fail")
        self.assertEqual(rows["router.corner"]["value"], 0.0)
        r = 2.0
        filleted = [((0, 0), (100, 0)), ((100, 0), (100, 60)), ((100, 60), (60, 60)), ((60, 60), (60, 30 + r)),
                    ((60 - r, 30), (40 + r, 30)), ((40, 30 + r), (40, 60)), ((40, 60), (0, 60)), ((0, 60), (0, 0))]
        doc = _doc([(a, b, "CUT") for a, b in filleted], arcs=[((60 - r, 30 + r), r, 270, 360), ((40 + r, 30 + r), r, 180, 270)])
        rows, _ = self.check(doc, "cut_router", {})
        self.assertEqual(rows["router.corner"]["status"], "pass", rows["router.corner"])
        self.assertAlmostEqual(rows["router.corner"]["value"], 2.0, places=9)
        rows, _ = self.check(_doc(_square(), circles=[((30, 30), 0.8)]), "cut_waterjet", {})
        self.assertEqual(rows["waterjet.hole"]["status"], "fail")
        rows, _ = self.check(_doc(_square(0, 0, 20, 10)), "cut_router", {})
        self.assertEqual(rows["router.size_min"]["status"], "fail")


class DxfRoundTrip(unittest.TestCase):
    def test_flat_pattern_written_and_read_back(self):
        from build123d import Cylinder, Pos
        part = box().solid() - Pos(30, 20, 0) * Cylinder(3, 10)
        res = unfold.unfold(part, kf())
        path = Path(TMP) / "box.dxf"
        dxf.write(path, res["entities"], res["bends"], ops.text_outlines("B1", 4, [30, 10]))
        doc = ezdxf.readfile(str(path))
        self.assertEqual(doc.header["$INSUNITS"], 4)
        got = dxf.read(path)
        cut = [e for e in got["entities"] if e["intent"] == "cut"]
        loops, opens = dxf.loops_of(cut)
        self.assertFalse(opens)
        outer = max(loops, key=lambda lp: abs(lp["area"]))
        a = abs(geom2d.exact_area(outer, cut)) - sum(abs(geom2d.exact_area(lp, cut)) for lp in loops if lp is not outer)
        self.assertAlmostEqual(a, res["area_mm2"], places=6)
        bends = [e for e in got["entities"] if e["intent"] == "bend"]
        self.assertEqual(len(bends), 4)
        self.assertEqual({e["layer"] for e in bends}, {"BEND_UP"})
        notes = [t for t in got["texts"] if t["layer"] == "NOTES"]
        self.assertEqual(len(notes), 4)
        self.assertTrue(all(n["text"].startswith("UP 90.0° R1") for n in notes))
        self.assertTrue([e for e in got["entities"] if e["layer"] == "ETCH"])
        self.assertFalse([t for t in got["texts"] if t["intent"] != "ignore"])  # the label is outlines, not text
        chk = cutcheck.check_file(path, "cut_laser", {"t": 1.0})
        self.assertEqual(chk["verdict"], "pass", [r for r in chk["rows"] if r["status"] != "pass"])

    def test_arcs_survive_including_a_flipped_extrusion(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 4
        msp = doc.modelspace()
        msp.add_arc((10, 0), 5, 0, 90, dxfattribs={"extrusion": (0, 0, -1)})
        path = Path(TMP) / "flip.dxf"
        doc.saveas(str(path))
        e = dxf.read(path)["entities"][0]
        A, B = geom2d.ends(e)
        pts = {tuple(np.round(A, 6)), tuple(np.round(B, 6))}
        self.assertEqual(pts, {(-15.0, 0.0), (-10.0, 5.0)})


class BendOrder(unittest.TestCase):
    def test_a_box_has_an_order(self):
        res = unfold.unfold(box().solid(), kf())
        o = brake.bend_order(res)
        self.assertTrue(o["feasible"], o["per_bend"])
        self.assertEqual(len(o["sequence"]), 4)
        self.assertEqual(o["model"]["die"]["v_mm"], 8.0)
        self.assertIn("Bystronic", o["model"]["die"]["v_source"])
        self.assertTrue(o["model"]["limits"])

    def test_a_short_jog_hits_the_die(self):
        s = Sheet(t=1.0, r=1.0)
        b = rect(s, 60, 40)
        s.jog(b.edge(1), offset=4, length=30)
        o = brake.bend_order(unfold.unfold(s.solid(), kf()))
        self.assertFalse(o["feasible"])
        self.assertTrue(any(h["with"] == "die" for p in o["per_bend"].values() for h in p["hits"]))

    def test_a_hem_needs_other_tools(self):
        s = Sheet(t=1.0, r=1.0)
        b = rect(s, 60, 40)
        s.hem(b.edge(1), 10)
        o = brake.bend_order(unfold.unfold(s.solid(), kf()))
        self.assertFalse(o["feasible"])


class Profiles(unittest.TestCase):
    def test_kerf_offsets_away_from_the_material(self):
        from build123d import Box, Cylinder, Pos
        plate = Pos(30, 20, 1.5) * Box(60, 40, 3) - Pos(15, 20, 0) * Cylinder(4, 10)
        exact = ops.profile(plate)
        self.assertTrue(exact["ok"], exact["reasons"])
        self.assertEqual(exact["size_mm"], [60.0, 40.0])
        self.assertEqual(exact["t"], 3.0)
        cut = ops.profile(plate, kerf=0.4)
        circles = [e for e in cut["entities"] if e["t"] == "circle"]
        self.assertAlmostEqual(circles[0]["r"], 3.8, places=6)
        loops, _ = geom2d.chain(cut["entities"], 1e-4)
        mn, mx = geom2d.bbox(cut["entities"])
        self.assertAlmostEqual(float(mx[0] - mn[0]), 60.4, places=6)

    def test_a_chamfered_plate_is_not_a_2d_cut(self):
        from build123d import Box
        b = Box(40, 30, 3)
        e = [x for x in b.edges() if abs(x.center().Z - 1.5) < 1e-6][:1]
        self.assertFalse(ops.profile(b.chamfer(1.0, None, e))["ok"])


class Preflight(unittest.TestCase):
    def test_against_the_service_table(self):
        flat = {"t": 3.175, "bends": [{"angle": 90}], "size_mm": [100, 200], "holes": [3.0]}
        r = preflight.preflight(flat, "sendcutsend", "5052", today=dt.date(2026, 11, 28))
        st = {x["id"]: x["status"] for x in r["rows"]}
        self.assertEqual(r["verdict"], "pass", r["rows"])
        self.assertEqual(st["svc.thickness"], "pass")
        self.assertFalse(r["sent"] or r["ordered"])
        self.assertFalse(r["stale"])
        bad = preflight.preflight({**flat, "t": 3.0, "bends": [{"angle": 135}], "holes": [1.0]}, "sendcutsend",
                                  "al_5052_h32", today=dt.date(2026, 11, 28))
        st = {x["id"]: x["status"] for x in bad["rows"]}
        self.assertEqual((st["svc.thickness"], st["svc.bend_angle"], st["svc.hole"]), ("fail", "fail", "fail"))
        thick = preflight.preflight({**flat, "t": 9.525}, "sendcutsend", "al_5052_h32", today=dt.date(2026, 11, 28))
        self.assertEqual({x["id"]: x["status"] for x in thick["rows"]}["svc.bend_thickness"], "fail")
        old = preflight.preflight(flat, "sendcutsend", "al_5052_h32", today=dt.date(2027, 6, 1))
        self.assertTrue(old["stale"])
        self.assertIn("days ago", old["headline"])
        none = preflight.preflight(flat, "sendcutsend", None, today=dt.date(2026, 11, 28))
        self.assertEqual(none["verdict"], "not proven")


DESIGN = '''
from build123d import Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param
from form.sheet.build import Sheet


class Design(FeatureDesign):
    params = [Param("t", "Thickness", 1.5, 0.5, 6), Param("w", "Width", 80, 20, 300), Param("d", "Depth", 50, 20, 300),
              Param("h", "Flange", 20, 3, 100)]

    @feature("Sheet")
    def body(self, v, body):
        s = Sheet(t=v["t"], r=v["t"], material="steel_mild")
        b = s.base([(0, 0), (v["w"], 0), (v["w"], v["d"]), (0, v["d"])])
        for i in range(4):
            s.flange(b.edge(i), v["h"], 90)
        return s.solid()

    @feature("Hole")
    def hole(self, v, body):
        return body - Pos(v["w"] / 2, v["d"] / 2, 0) * Cylinder(3, 20)
'''


class Studio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from form import config
        from form.studio import Studio as S
        cls.data = os.environ["FORM_DATA"]            # the data folder this Studio uses (another module may set it)
        cls.st = S(config.load())
        cls.p = cls.st.create_design("Tray", DESIGN, purpose="model")

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_flat_pattern_dxf_and_checks(self):
        from form import dfm, sheet
        st, p = self.st, self.st.load(self.p["id"])
        res = sheet.flat_pattern(st, p, {"material": "steel_mild", "label": "T-1"})
        self.assertTrue(res["ok"], res["reasons"])
        self.assertLess(res["verify"]["max_mm"], 0.01)
        K = tables.kfactor(1.5, 1.5, "steel_mild")["K"]
        self.assertAlmostEqual(res["size_mm"][0], 80 + 40 + 2 * math.pi / 2 * (1.5 + K * 1.5), places=6)
        self.assertTrue(Path(res["dxf"]).is_file() and Path(res["png"]).is_file())
        again = sheet.flat_pattern(st, p, {"material": "steel_mild", "label": "T-1"})
        self.assertTrue(again.get("cached"))
        d = dfm.check(st, p, "sheet_metal", {"material": "steel_mild"})
        self.assertEqual(d["verdict"], "pass", [r for r in d["rows"] if r["status"] not in ("pass", "info", "n/a")])
        c = sheet.cut_check(None, "cut_laser", {}, st, p)
        self.assertEqual(c["verdict"], "pass")
        o = sheet.bend_order(st, p)
        self.assertTrue(o["feasible"])
        f = sheet.service_preflight(st, p, "sendcutsend", "steel_mild")
        self.assertEqual(f["verdict"], "pass", f["rows"])
        self.assertFalse(f["sent"])

    def test_cli_prints_json(self):
        env = {**os.environ, "FORM_DATA": self.data, "PYTHONPATH": str(ROOT)}
        r = subprocess.run([sys.executable, "-m", "form", "sheet", "flat", self.p["id"], "--set", "material=steel_mild"],
                           capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:] + r.stdout[-2000:])
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["bends"]), 4)
        r = subprocess.run([sys.executable, "-m", "form", "sheet", "check", out["dxf"], "--set", "t=1.5"],
                           capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:] + r.stdout[-2000:])
        self.assertEqual(json.loads(r.stdout)["verdict"], "pass")

    def test_bench_entries(self):
        try:
            from form import studies  # noqa: F401
        except ImportError:
            self.skipTest("The Bench (form/studies.py) is not on this branch yet.")
        from form import sheet
        got = []
        sheet.register_studies(got.append)
        self.assertEqual([s.label for s in got], ["Flat pattern, DXF", "Cut-file check", "Bend order"])


if __name__ == "__main__":
    unittest.main()
