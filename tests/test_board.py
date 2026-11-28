"""Circuit boards and their enclosures (form/board, wave K).

A synthetic KiCad 8 board written here (form.board.kicad.write_fixture: an 80 x 50 mm outline, four M3 mounting holes,
a USB-C receptacle on the front edge, a 10 mm capacitor, a pin header) is read without KiCad; an IDF pair written here
reads the same way. On the kernel: the enclosure made around the board builds and fits it on the solids, the
USB-C opening is where the connector is, a connector that moved fails its plug sweep until the enclosure is made
again, and a part without a height is "not checked", never a pass. The fab limits carry their page and date.
Paths that run KiCad's kicad-cli are skipped when it is not installed."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = tempfile.mkdtemp(prefix="form-board-")

from form.board import fabs, kicad, kicad_cli, model, sexpr  # noqa: E402
from form.board import api  # noqa: E402


def fixture(name="b.kicad_pcb", **kw) -> Path:
    d = Path(TMP) / "boards"
    d.mkdir(exist_ok=True)
    return kicad.write_fixture(d / name, **kw)


class Sexpr(unittest.TestCase):
    def test_strings_symbols_and_escapes(self):
        t = sexpr.parse('(a (b "x \\"y\\"" 1.5) (c "") d)')
        self.assertEqual(sexpr.head(t), "a")
        self.assertEqual(sexpr.atoms(sexpr.first(t, "b")), ['x "y"', "1.5"])
        self.assertEqual(sexpr.value(t, "c"), "")
        self.assertIsInstance(t[-1], sexpr.Sym)

    def test_errors_name_the_problem(self):
        with self.assertRaises(sexpr.SexprError):
            sexpr.parse('(a (b "open)')
        with self.assertRaises(sexpr.SexprError):
            sexpr.parse("(a (b)")

    def test_arc_through_its_mid_point(self):
        pts = model.arc3((1, 0), (0, 1), (-1, 0))              # counter-clockwise over the top
        self.assertTrue(all(y >= -1e-9 for _x, y in pts))
        pts = model.arc3((1, 0), (0, -1), (-1, 0))             # clockwise under the bottom
        self.assertTrue(all(y <= 1e-9 for _x, y in pts))


class ReadKiCad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = kicad.read(fixture())

    def test_outline_thickness_and_frame(self):
        b = self.b
        self.assertEqual(b["size"], [80.0, 50.0])
        self.assertEqual(b["thickness"]["value"], 1.6)
        self.assertEqual(b["thickness"]["provenance"], "specified")
        xs = [p[0] for p in b["outline"]]
        self.assertAlmostEqual(min(xs), -40.0)
        self.assertAlmostEqual(max(xs), 40.0)
        self.assertEqual(b["origin"], [140.0, 125.0])

    def test_mounting_holes_take_the_screw_that_fits(self):
        mh = self.b["mounting_holes"]
        self.assertEqual(len(mh), 4)
        self.assertEqual({h["screw"] for h in mh}, {"M3"})
        # KiCad's y points down: the hole at the file's top-left (3.5, 3.5) is at the back left here
        h1 = next(h for h in mh if h["ref"] == "H1")
        self.assertEqual((h1["x"], h1["y"]), (-36.5, 21.5))
        self.assertNotIn("H1", [c["ref"] for c in self.b["components"]])

    def test_connectors_and_their_mating_side(self):
        k = {c["ref"]: c for c in self.b["connectors"]}
        self.assertEqual(k["J1"]["side"], "-y")                 # the USB-C at the file's bottom edge is the front
        self.assertLess(k["J1"]["face"], -24.9)
        self.assertEqual(k["J1"]["plug"]["provenance"], "specified")
        self.assertEqual((k["J1"]["plug"]["w"], k["J1"]["plug"]["h"]), (12.35, 6.5))
        self.assertEqual(k["J2"]["side"], "up")                 # a header in the middle mates from above
        self.assertEqual(k["J2"]["plug"]["provenance"], "assumed")

    def test_heights_come_only_from_the_file(self):
        c = {x["ref"]: x for x in self.b["components"]}
        self.assertEqual(c["C1"]["height"]["value"], 10.0)
        self.assertIn("property", c["C1"]["height"]["source"])
        b = kicad.read(fixture("noh.kicad_pcb", cap_height=None))
        self.assertIn("C1", model.missing_heights(b))

    def test_copper_sizes_and_keepouts(self):
        cu = self.b["copper"]
        self.assertEqual(cu["layers"], 2)
        self.assertEqual(cu["min_track_width"], 0.25)
        self.assertEqual(cu["min_via_drill"], 0.3)
        self.assertAlmostEqual(cu["min_via_annular"], 0.15)
        self.assertAlmostEqual(cu["track_spacing"]["gap"], 0.75)     # two parallel 0.25 mm tracks 1 mm apart
        self.assertEqual(len(self.b["keepouts"]), 1)
        self.assertEqual(self.b["keepouts"][0]["rules"]["tracks"], "not_allowed")

    def test_project_rules_from_the_kicad_pro(self):
        p = fixture("rules.kicad_pcb")
        p.with_suffix(".kicad_pro").write_text(json.dumps({"board": {"design_settings": {"rules": {
            "min_clearance": 0.2, "min_track_width": 0.2}}}, "net_settings": {"classes": [
                {"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_drill": 0.3}]}}), encoding="utf-8")
        b = kicad.read(p)
        self.assertEqual(b["rules"]["min_clearance"], 0.2)
        self.assertEqual(b["rules"]["netclass_min_clearance"], 0.2)

    def test_not_a_board(self):
        p = Path(TMP) / "x.kicad_pcb"
        p.write_text('(kicad_sch (version 1))', encoding="utf-8")
        with self.assertRaises(ValueError):
            kicad.read(p)


EMN = """.HEADER
BOARD_FILE 3.0 "test" 2026/11/28.12:00:00 1
"demo" MM
.END_HEADER
.BOARD_OUTLINE ECAD
1.6
0 0 0 0
0 60 0 0
0 60 40 0
0 0 40 0
0 0 0 0
.END_BOARD_OUTLINE
.DRILLED_HOLES
3.2 4 4 NPTH BOARD MTG ECAD
3.2 56 36 NPTH BOARD MTG ECAD
.END_DRILLED_HOLES
.PLACEMENT
"USB_C" "USB4105" J1
30 2 0 0 TOP PLACED
"CAP" "470u" C1
15 20 0 0 TOP PLACED
.END_PLACEMENT
"""
EMP = """.HEADER
LIBRARY_FILE 3.0 "test" 2026/11/28.12:00:00 1
.END_HEADER
.ELECTRICAL
"USB_C" "USB4105" MM 3.26
0 -4.5 -3 0
0 4.5 -3 0
0 4.5 4 0
0 -4.5 4 0
0 -4.5 -3 0
.END_ELECTRICAL
.ELECTRICAL
"CAP" "470u" MM 10
0 -4 -4 0
0 4 -4 0
0 4 4 0
0 -4 4 0
0 -4 -4 0
.END_ELECTRICAL
"""


class ReadIDF(unittest.TestCase):
    def test_outline_holes_parts_and_heights(self):
        d = Path(TMP) / "idf"
        d.mkdir(exist_ok=True)
        (d / "demo.emn").write_text(EMN, encoding="utf-8")
        (d / "demo.emp").write_text(EMP, encoding="utf-8")
        b = api.read(d / "demo.emn")
        self.assertEqual(b["format"], "idf")
        self.assertEqual(b["size"], [60.0, 40.0])
        self.assertEqual(len(b["mounting_holes"]), 2)
        c = {x["ref"]: x for x in b["components"]}
        self.assertEqual(c["C1"]["height"]["value"], 10.0)
        k = {x["ref"]: x for x in b["connectors"]}
        self.assertEqual(k["J1"]["side"], "-y")                 # IDF's y already points back: J1 sits at the front


class FabLimits(unittest.TestCase):
    def test_every_limit_is_quoted_with_its_page_and_date(self):
        for fid, f in fabs.FABS.items():
            self.assertTrue(f["url"].startswith("https://"), fid)
            self.assertEqual(f["read"], fabs.READ)
            for pr in f["process"].values():
                for k in ("trace", "space", "drill", "annular", "board_min", "board_max"):
                    v, quote = pr[k]
                    self.assertTrue(quote, (fid, k))

    def test_the_fixture_against_three_fabs(self):
        b = kicad.read(fixture())
        r = {f["id"]: f for f in fabs.check(b)["fabs"]}
        row = lambda fid, k: next(x for x in r[fid]["rows"] if x["check"] == k)
        # 0.6 mm via on a 0.3 mm drill: a 0.15 mm ring, under JLCPCB's stated 2-layer minimum (0.18 mm)
        self.assertEqual(row("jlcpcb", "annular")["status"], "FAIL")
        self.assertEqual(row("pcbway", "annular")["status"], "PASS")
        self.assertEqual(row("oshpark", "annular")["status"], "PASS")
        self.assertEqual(row("oshpark", "trace")["status"], "PASS")
        self.assertIn("read 2026-11-28", row("oshpark", "trace")["evidence"])
        self.assertIn("docs.oshpark.com", row("oshpark", "trace")["evidence"])
        self.assertEqual(row("jlcpcb", "board_size")["status"], "PASS")

    def test_what_the_board_does_not_say_is_not_checked(self):
        b = kicad.read(fixture())
        b["copper"] = {"layers": 2}
        rows = fabs.check(b, ["jlcpcb"])["fabs"][0]["rows"]
        self.assertIn("NOT CHECKED", {x["status"] for x in rows})
        self.assertNotEqual(fabs.check(b, ["jlcpcb"])["fabs"][0]["status"], "PASS")


class KiCadCli(unittest.TestCase):
    def test_absent_says_so_and_offers_the_install(self):
        old = os.environ.get("FORM_KICAD_CLI")
        os.environ["FORM_KICAD_CLI"] = str(Path(TMP) / "no-such-kicad-cli")
        try:
            s = kicad_cli.status({})
            self.assertFalse(s["available"])
            self.assertEqual(s["install"]["id"], "kicad")
        finally:
            if old is None:
                os.environ.pop("FORM_KICAD_CLI", None)
            else:
                os.environ["FORM_KICAD_CLI"] = old

    def test_the_report_is_read_as_kicad_wrote_it(self):
        rep = {"kicad_version": "9.0.0", "coordinate_units": "mm", "violations": [
            {"type": "clearance", "severity": "error", "description": "Clearance violation",
             "items": [{"description": "Track [GND]", "pos": {"x": 1.0, "y": 2.0}, "uuid": "u1"}]}],
            "unconnected_items": [], "schematic_parity": []}
        r = kicad_cli.parse_drc(rep)
        self.assertEqual(r["by"], "KiCad DRC")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["rows"][0]["items"][0]["x"], 1.0)
        self.assertEqual(kicad_cli.parse_drc({})["total"], 0)

    def test_the_installer_knows_kicad(self):
        from form import installer
        s = installer.get("kicad")
        self.assertEqual(s.level, "optional")
        ms = installer.methods_for(s, "darwin", which=lambda n: "/x/" + n)
        self.assertIn("brew install --cask kicad", ms[0].commands[0])

    @unittest.skipUnless(kicad_cli.find(), "KiCad's kicad-cli is not installed")
    def test_real_kicad_runs_drc_on_the_fixture(self):
        exe = kicad_cli.find()
        r = kicad_cli.drc(exe, fixture("drc.kicad_pcb"), Path(TMP) / "drc")
        self.assertTrue(r["ran"], r)
        self.assertEqual(r["by"], "KiCad DRC")
        self.assertTrue(Path(r["report"]).is_file())


class OnTheKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        os.environ["FORM_KICAD_CLI"] = str(Path(TMP) / "no-such-kicad-cli")    # these tests never run KiCad
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())
        cls.imp = api.import_board(cls.st, str(fixture()), name="Board box")
        cls.pid = cls.imp["project"]

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("FORM_KICAD_CLI", None)
        cls.st.kernel.stop()

    def test_1_the_enclosure_builds_and_fits(self):
        p = self.st.load(self.pid)
        self.assertTrue(self.imp["created"])
        self.assertFalse(p["revisions"][-1].get("partial"))
        self.assertEqual(p["board"]["file"], "b.kicad_pcb")
        r = api.fit(self.st, p)
        st = {x["id"]: x["status"] for x in r["rows"]}
        self.assertTrue(r["ok"], r["rows"])
        self.assertEqual(st["board.walls"], "PASS")
        self.assertEqual(sum(1 for k, v in st.items() if k.startswith("board.standoff.") and v == "PASS"), 4)
        self.assertEqual(st["board.connector.J1"], "PASS")
        self.assertEqual(st["board.connector.J2"], "INFO")
        self.assertEqual(st["board.headroom"], "PASS")
        self.assertEqual(sum(1 for k, v in st.items() if k.startswith("board.access.") and v == "PASS"), 4)
        self.assertTrue(all("computed" in x["evidence"] for x in r["rows"] if x["status"] in ("PASS", "FAIL")))

    def test_2_the_usb_opening_is_on_the_connector(self):
        r = api.fit(self.st, self.st.load(self.pid))
        row = next(x for x in r["rows"] if x["id"] == "board.connector.J1")
        op = row["measured"]["opening"]
        self.assertTrue(op["centre_open"])                     # open on the connector's axis, mid-wall
        self.assertEqual(op["wall_beside"], [True, True])      # and wall just beyond the plug and its clearance
        self.assertEqual(row["measured"]["plug_mm"], [12.35, 6.5])

    def test_3_the_parts_list_has_the_inserts_and_screws(self):
        from form import bom
        b = bom.build(self.st, self.st.load(self.pid), made=False)
        got = {x["designation"]: x["quantity"] for x in b["purchased"]}
        self.assertEqual(got.get("Heat-set insert M3×5.7 (CNC Kitchen), brass"), 8)
        self.assertEqual(sum(q for d, q in got.items() if d.startswith("ISO 7380")), 8)

    def test_4_a_moved_connector_fails_until_the_enclosure_is_made_again(self):
        st = self.st
        imp = api.import_board(st, str(fixture("moved.kicad_pcb", usb_x=55.0)), project=self.pid)
        self.assertIn("J1 moved +15.00, +0.00 mm.", [c["text"] for c in imp["changes"]])
        r = api.fit(st, st.load(self.pid))
        row = next(x for x in r["rows"] if x["id"] == "board.connector.J1")
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("made_for_other_board"))
        api.import_board(st, str(fixture("moved.kicad_pcb", usb_x=55.0)), project=self.pid, regenerate=True)
        r = api.fit(st, st.load(self.pid))
        self.assertTrue(r["ok"], [x for x in r["rows"] if x["status"] == "FAIL"])

    def test_5_a_part_without_a_height_is_not_checked(self):
        st = self.st
        api.import_board(st, str(fixture("noh.kicad_pcb", usb_x=55.0, cap_height=None)), project=self.pid)
        r = api.fit(st, st.load(self.pid))
        row = next(x for x in r["rows"] if x["id"] == "board.heights")
        self.assertEqual(row["status"], "NOT CHECKED")
        self.assertIn("C1", row["detail"])
        imp = api.import_board(st, str(fixture("noh.kicad_pcb", usb_x=55.0, cap_height=None)), project=self.pid,
                               heights={"C1": 30.0})
        self.assertEqual(imp["missing_heights"], [])
        r = api.fit(st, st.load(self.pid))
        bad = next(x for x in r["rows"] if x["id"] == "board.part.C1")
        self.assertEqual(bad["status"], "FAIL")                 # a 30 mm part does not fit under this lid

    def test_6_checks_without_kicad_run_nothing_in_its_place(self):
        r = api.checks(self.st, self.st.load(self.pid))
        self.assertFalse(r["drc"]["ran"])
        self.assertIn("not installed", r["drc"]["why"])
        self.assertNotIn("rows", r["drc"])
        self.assertEqual(len(r["fab"]["fabs"]), 3)
        f = api.fab_files(self.st, self.st.load(self.pid))
        self.assertFalse(f["files"]["gerbers"]["ok"])
        self.assertTrue(f["files"]["step"]["ok"])
        self.assertEqual(f["files"]["step"]["by"], "Form Studio")
        self.assertTrue(Path(f["files"]["step"]["files"][0]).is_file())

    def test_7_bench_entries(self):
        from form import studies
        st = self.st
        p = st.load(self.pid)
        rows = {e["id"]: e for e in studies.listing(st, p)["entries"]}
        for sid in ("board.fit", "board.checks", "doc.board_fab"):
            self.assertIn(sid, rows)
            self.assertNotEqual(rows[sid]["state"], "n/a")
        r = studies.start(st, self.pid, "board.fit", wait=True)
        self.assertEqual(r["entry"]["state"], "current")
        from test_maker_tools import BLOCK
        other = st.create_design("Plain", BLOCK)                # a design without a board: the entries do not apply
        rows = {e["id"]: e for e in studies.listing(st, other)["entries"]}
        self.assertEqual(rows["board.fit"]["state"], "n/a")


