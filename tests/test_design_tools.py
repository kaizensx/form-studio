"""Design tools: text and marks, patterns, variants, share card, revision history.

Real kernel (build123d) and a temp data folder. Nothing here uses a slicer: the share card must say "not sliced".
"""
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-tools-")

from build123d import Align, Box, Cylinder, Pos  # noqa: E402
from PIL import Image  # noqa: E402

from form import config, marks, patterns, share, variants  # noqa: E402
from form.recipes import registry  # noqa: E402
from form.recipes.base import RecipeError  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Marks(unittest.TestCase):
    def setUp(self):
        marks.set_context(None)

    def test_font_ships_with_the_package(self):
        self.assertTrue(marks.FONT.is_file())
        self.assertTrue((marks.FONT.parent / "FormMark-LICENSE.txt").is_file())
        self.assertAlmostEqual(marks.sketch("H", 6).bounding_box().size.Y, 6.0, places=2)      # height is the cap height

    def test_emboss_and_deboss_build_valid_solids(self):
        b = Box(60, 30, 10, align=A)
        up = marks.emboss_text(b, "FORM 01", on=(0, 0, 10), normal=(0, 0, 1), height=6, depth=0.8)
        self.assertTrue(up.is_valid)
        self.assertEqual(len(up.solids()), 1)
        self.assertGreater(up.volume, b.volume)
        self.assertAlmostEqual(up.bounding_box().max.Z, 10.8, places=3)
        down = marks.deboss_text(b, "FORM 01", on=(0, -15, 5), normal=(0, -1, 0), height=5, depth=0.6)
        self.assertTrue(down.is_valid)
        self.assertEqual(len(down.solids()), 1)
        self.assertLess(down.volume, b.volume)
        self.assertAlmostEqual(down.bounding_box().min.Y, -15, places=3)                      # nothing sticks out
        # the same text raised and sunk moves the same amount of material per mm (within the 0.05 mm overlap)
        self.assertAlmostEqual((up.volume - b.volume) / 0.8, (b.volume - down.volume) / 0.6 * (6 / 5) ** 2, delta=1.5)
        face = b.faces().sort_by()[-1]                                                         # a Face works as the target too
        self.assertTrue(marks.emboss_text(b, "A", on=face, height=5).is_valid)

    def test_text_off_the_part_or_on_a_curved_face_is_refused(self):
        b = Box(20, 20, 10, align=A)
        with self.assertRaises(RecipeError):
            marks.emboss_text(b, "FAR", on=(200, 0, 10), normal=(0, 0, 1))
        with self.assertRaises(RecipeError):
            marks.emboss_text(b, "", on=(0, 0, 10), normal=(0, 0, 1))
        cyl = Cylinder(10, 20, align=A)
        curved = next(f for f in cyl.faces() if f.geom_type.name != "PLANE")
        with self.assertRaises(RecipeError):
            marks.deboss_text(cyl, "X", on=curved)

    def test_stroke_check_fires_for_tiny_text(self):
        tiny = marks.analyse("serial 0042", 1.5)
        rows = {c["id"]: c for c in marks.checks(tiny, nozzle=0.4)}
        self.assertLess(tiny["stroke_mm"], 0.4)
        self.assertEqual(rows["mark_stroke"]["status"], "FAIL")
        self.assertEqual(rows["mark_height"]["status"], "FAIL")
        self.assertEqual(rows["mark_stroke"]["evidence"], "computed")
        big = {c["id"]: c for c in marks.checks(marks.analyse("FORM", 8), nozzle=0.4)}
        self.assertEqual((big["mark_stroke"]["status"], big["mark_height"]["status"]), ("PASS", "PASS"))
        self.assertIn("assumed", marks.checks(tiny)[0]["detail"])                              # no nozzle known: said so
        # the estimate scales with the height, and a wider nozzle fails sooner
        self.assertAlmostEqual(marks.analyse("FORM", 8)["stroke_mm"] / marks.analyse("FORM", 4)["stroke_mm"], 2.0, places=3)
        self.assertEqual(marks.checks(marks.analyse("FORM", 4), nozzle=0.8)[0]["status"], "FAIL")

    def test_revision_stamp_content_and_placement(self):
        self.assertEqual(marks.stamp_text(4, "a3f1"), "r04 a3f1")
        h = marks.short_hash("dock", {"a": 1.0, "b": 2.0})
        self.assertRegex(h, r"^[0-9a-f]{4}$")
        self.assertEqual(h, marks.short_hash("dock", {"b": 2, "a": 1}))                        # order and int/float do not matter
        self.assertNotEqual(h, marks.short_hash("dock", {"a": 1.0, "b": 2.5}))
        marks.set_context({"rev": 7, "hash": "beef", "text": "X"})
        self.assertEqual(marks.stamp_text(), "r07 beef")
        b = Pos(0, 0, 3) * Box(60, 30, 10, align=A)
        s = marks.revision_stamp(b)
        self.assertTrue(s.is_valid)
        removed = b.volume - s.volume
        want = sum(f.area for f in marks.sketch("r07 beef", 6).faces()) * 0.4
        self.assertAlmostEqual(removed, want, delta=want * 0.02)                                # exactly the stamp text, 0.4 mm deep
        bb = s.bounding_box()
        self.assertAlmostEqual(bb.min.Z, 3.0, places=4)                                         # sunk into the underside, nothing added
        top = Pos(0, 0, 3 + 0.4 + 0.01) * Box(60, 30, 9.5, align=A)
        self.assertAlmostEqual((s & top).volume, top.volume, places=2)                          # untouched above the stamp depth

    def test_clean_drops_what_the_font_cannot_draw(self):
        self.assertEqual(marks.clean("  Dock\n №1 ✓  "), "Dock 1")
        self.assertEqual(marks.analyse("Dock ✓", 6)["dropped"], 2)


class Patterns(unittest.TestCase):
    def test_hex_open_area_matches_the_cut(self):
        p = patterns.hex_vents(60, 40, cell=5, web=1.2, depth=2.2)
        n = p["count"]
        self.assertGreater(n, 30)
        self.assertAlmostEqual(p["open_area_mm2"], n * math.sqrt(3) / 2 * 25, places=6)
        self.assertAlmostEqual(p["open_area_ratio"], p["open_area_mm2"] / 2400, places=9)
        plate = Box(60, 40, 2, align=A)
        cut = plate - Pos(0, 0, 2) * p.shape
        self.assertTrue(cut.is_valid)
        self.assertAlmostEqual((plate.volume - cut.volume) / 2, p["open_area_mm2"], delta=p["open_area_mm2"] * 1e-4)
        self.assertEqual(p["min_web_mm"], 1.2)
        for x, y in p.centres:                                                                # every cell is inside the region
            self.assertLessEqual(abs(x) + 2.5, 30 + 1e-9)
            self.assertLessEqual(abs(y) + 5 / math.sqrt(3), 20 + 1e-9)
        d = sorted(math.hypot(x - p.centres[0][0], y - p.centres[0][1]) for x, y in p.centres[1:])[0]
        self.assertAlmostEqual(d, 6.2, places=6)                                               # neighbours are cell + web apart

    def test_grid_and_slots(self):
        g = patterns.perforation_grid(30, 20, hole_d=3, web=1.5, depth=2.2)
        cols = len({round(x, 6) for x, _ in g.centres}); rows = len({round(y, 6) for _, y in g.centres})
        self.assertEqual((cols, rows, g["count"]), (7, 4, 28))                                 # floor((30 - 3) / 4.5) + 1, floor((20 - 3) / 4.5) + 1
        self.assertAlmostEqual(g["open_area_ratio"], 28 * math.pi * 9 / 4 / 600, places=9)
        self.assertAlmostEqual(sum(x for x, _ in g.centres), 0, places=9)                      # centred
        st = patterns.perforation_grid(30, 20, hole_d=3, web=1.5, stagger=True)
        self.assertGreater(st["count"], 28)                                                    # staggered rows pack tighter
        s = patterns.slot_array(2, 40, count=8, web=2.4, depth=2.2)
        one = (40 - 2) * 2 + math.pi
        self.assertAlmostEqual(s["open_area_mm2"], 8 * one, places=9)
        self.assertEqual(s["region_mm"], [8 * 2 + 7 * 2.4, 40])
        plate = Box(40, 44, 2, align=A)
        self.assertAlmostEqual((plate.volume - (plate - Pos(0, 0, 2) * s.shape).volume) / 2, 8 * one, delta=0.01)
        self.assertEqual(patterns.slot_array(2, 40, w=33, web=2.4)["count"], 8)                # fills a width

    def test_web_check_wants_two_perimeters(self):
        ok = patterns.hex_vents(40, 40, cell=5, web=1.2).check(nozzle=0.4)
        self.assertEqual((ok["status"], ok["evidence"]), ("PASS", "computed"))
        self.assertEqual(patterns.hex_vents(40, 40, cell=5, web=0.6).check(nozzle=0.4)["status"], "WARN")
        self.assertEqual(patterns.hex_vents(40, 40, cell=5, web=0.3).check(nozzle=0.4)["status"], "FAIL")
        self.assertEqual(patterns.hex_vents(40, 40, cell=5, web=1.2).check(nozzle=0.8)["status"], "WARN")
        rows = patterns.hex_vents(40, 40, cell=5, web=1.2).derived("vents", "vent.")
        self.assertEqual([r["key"] for r in rows], ["vent.open_area", "vent.min_web"])

    def test_knurl_and_ribs(self):
        k = patterns.knurl(20, 12, pitch=2, depth=0.5)
        self.assertEqual(k["count"], round(math.pi * 20 / 2))
        self.assertAlmostEqual(k["min_web_mm"], math.pi * 20 / k["count"] - 1.0, places=9)
        cyl = Cylinder(10, 12, align=A)
        cut = cyl - k.shape
        self.assertTrue(cut.is_valid)
        self.assertEqual(len(cut.solids()), 1)
        self.assertLess(cut.volume, cyl.volume)
        r = patterns.grip_ribs(30, 20, rib_w=1.2, pitch=3, height=0.8)
        self.assertEqual((r.kind, r["count"]), ("add", 10))
        plate = Box(30, 20, 2, align=A)
        ribbed = r.apply(plate, on=(0, 0, 2), normal=(0, 0, 1))
        self.assertAlmostEqual(ribbed.volume - plate.volume, 10 * 1.2 * 20 * 0.8, delta=0.01)
        with self.assertRaises(RecipeError):
            patterns.hex_vents(3, 3, cell=5).shape                                             # no room for one cell

    def test_enclosure_vent_styles(self):
        r = registry()["enclosure"]
        base = r.defaults()
        vols = {}
        for style in (0, 1, 2):
            v = r.validate({**base, "vent_style": style})
            stages = r.build(v)
            self.assertTrue(stages[-1].shape.is_valid)
            self.assertEqual(len(stages[-1].shape.solids()), 2)
            lid_before = next(s for s in stages if s.feature == "lid_screws").shape.volume
            vols[style] = lid_before - next(s for s in stages if s.feature == "vents").shape.volume
            vent = r._vent(v)
            self.assertAlmostEqual(vols[style], vent["open_area_mm2"] * v["lid_t"], delta=vols[style] * 1e-3)
            keys = [d["key"] for d in r.derived(v)]
            self.assertIn("vent.open_area", keys)
            self.assertIn("vent_webs", [c["id"] for c in r.statics(v, 0, (0, 0, 0))["checks"]])
        self.assertEqual(r._vent(r.validate(base)).name, "slot")
        self.assertEqual(len({round(x, 1) for x in vols.values()}), 3)                         # three different patterns


class StudioTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.pid = cls.st.create("Tools dock", "dock")["id"]
        cls.st.settings(cls.st.load(cls.pid), {"mark_text": "TOOLS"})

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def load(self):
        return self.st.load(self.pid)

    def test_01_marks_follow_the_project_and_the_revision(self):
        st, p = self.st, self.load()
        key0 = st.keys(p)["geometry"]
        self.assertIsNone(st.mark_context(p, "dock", st.rev(p)["values"]))                     # off: keys are what they always were
        pv = st.preview(p, {"label": 1, "stamp": 1})
        self.assertIn("mark", pv["signature"])
        ids = {c["id"]: c for c in pv["statics"]["checks"]}
        self.assertIn("“TOOLS”", ids["mark_stroke"]["detail"])
        self.assertIn("“r02 ", ids["stamp_stroke"]["detail"])                                  # a draft is the next revision
        self.assertEqual(ids["mark_stroke"]["status"], "PASS")
        p = st.commit(p, {"label": 1, "stamp": 1}, "marks on")
        ctx = st.mark_context(p, "dock", st.rev(p)["values"], 2)
        self.assertEqual((ctx["rev"], ctx["text"]), (2, "TOOLS"))
        self.assertEqual(ctx["hash"], marks.short_hash("dock", st.rev(p)["values"]))
        self.assertNotEqual(st.keys(p)["geometry"], key0)
        k_text = st.keys(p)["geometry"]
        p = st.settings(p, {"mark_text": "OTHER"})
        self.assertNotEqual(st.keys(p)["geometry"], k_text)                                    # the label text is an input of the solid
        self.assertEqual(st.run_sync(self.pid, ["geometry", "exports", "checks"])["state"], "done")
        ch = {c["id"]: c for c in st.read(p, "checks", st.keys(p)["checks"])["checks"]}
        self.assertEqual(ch["solid"]["status"], "PASS")
        self.assertIn("mark_stroke", ch)
        self.assertNotEqual(ch["wall"]["feature"], "mark")                                     # letter corners are not walls
        self.assertGreater(float(ch["wall"]["value"].split()[0]), 1.0)
        too_long = st.settings(p, {"mark_text": "A label far too long to fit here"})
        with self.assertRaises(StudioError) as e:
            st.view(too_long)
        self.assertIn("Lower the label height", e.exception.hint)
        st.settings(p, {"mark_text": "TOOLS"})

    def test_02_old_projects_gain_new_parameters(self):
        f = Path(TMP) / self.pid / "project.json"
        raw = json.loads(f.read_text(encoding="utf-8"))
        for r in raw["revisions"]:
            for k in ("label", "label_h", "stamp"):
                r["values"].pop(k, None)
                r["provenance"].pop(k, None)
        f.write_text(json.dumps(raw), encoding="utf-8")
        p = self.load()
        self.assertEqual(self.st.rev(p, 1)["values"]["label"], 0.0)
        self.assertEqual(self.st.rev(p, 1)["provenance"]["stamp"]["source"], "assumed")
        self.st.preview(p, {"stamp": 1})                                                       # and it is editable

    def test_03_variants_persist_and_promote(self):
        st, p = self.st, self.load()
        head = p["head"]
        a = variants.save(st, p, "Thick walls", {"side_wall": 9, "lip": 8}, note="sturdier")
        self.assertEqual((a["id"], a["rev"], a["source"]), ("thick-walls", None, "draft"))
        self.assertEqual({d["key"] for d in a["differences"]}, {"side_wall", "lip"})
        b = variants.save(st, self.load(), "As it is")
        self.assertEqual((b["rev"], b["is_head"]), (head, True))
        with self.assertRaises(StudioError):
            variants.save(st, self.load(), "Broken", {"side_wall": 0.1})                       # must build
        with self.assertRaises(StudioError):
            variants.save(st, self.load(), "  ")
        st2 = Studio(config.load())                                                            # a second process sees them
        try:
            saved = st2.load(self.pid)["variants"]
            self.assertEqual([v["name"] for v in saved], ["Thick walls", "As it is"])
            self.assertEqual(saved[0]["values"]["side_wall"], 9.0)
        finally:
            st2.kernel.stop()
        board = variants.board(st, self.load())
        self.assertEqual([c["id"] for c in board["cards"]], ["@head", "thick-walls", "as-it-is"])
        thick = board["cards"][1]["metrics"]
        self.assertGreater(thick["volume_cm3"], board["cards"][0]["metrics"]["volume_cm3"])
        self.assertEqual(thick["evidence"]["volume_cm3"], "computed")
        self.assertIsNone(thick["slice"])                                                      # never sliced: no time, no grams
        self.assertEqual(thick["fit"]["evidence"], "modelled")
        self.assertIn("volume", board["differs"])
        self.assertTrue(variants.view(st, self.load(), "thick-walls")["mesh"])
        self.assertEqual(variants.save(st, self.load(), "Thick walls", {"side_wall": 10})["differences"][0]["to"], 10.0)   # replaced
        self.assertEqual(len(self.load()["variants"]), 2)
        res = variants.promote(st, self.load(), "Thick walls")
        p = self.load()
        self.assertEqual((res["head"], p["head"]), (head + 1, head + 1))
        self.assertEqual(st.rev(p)["values"]["side_wall"], 10.0)
        self.assertIn("Thick walls", st.rev(p)["note"])
        self.assertEqual(variants.promote(st, p, "As it is")["how"], f"checked out r{head:02d}")
        self.assertEqual(self.load()["head"], head)
        variants.delete(st, self.load(), "as-it-is")
        self.assertEqual([v["id"] for v in self.load()["variants"]], ["thick-walls"])
        with self.assertRaises(StudioError):
            variants.find(self.load(), "nope")

    def test_04_share_card_is_produced_and_honest(self):
        st, p = self.st, self.load()
        out = Path(TMP) / "card.png"
        c = share.card(st, p, out)
        self.assertTrue(out.is_file())
        with Image.open(out) as im:
            self.assertEqual((im.size, im.format), ((1600, 900), "PNG"))
            self.assertGreater(len(set(im.convert("L").resize((64, 36)).tobytes())), 12)       # a picture, not a blank
        rows = {r["k"]: r for r in c["facts"]["rows"]}
        self.assertEqual(rows["Size"]["tag"], "computed")
        self.assertEqual((rows["Print time"]["v"], rows["Print time"]["tag"]), ("not sliced", ""))
        self.assertNotIn("Filament", rows)
        self.assertEqual(rows["Fit yield"]["tag"], "modelled")
        self.assertIn("not physically validated", c["facts"]["evidence_level"])
        self.assertEqual(c["facts"]["stamp"], marks.stamp_text(p["head"], marks.short_hash("dock", st.rev(p)["values"])))
        self.assertTrue(share.card(st, p)["cached"])
        with self.assertRaises(StudioError):
            share.card(st, p, picture="photo")                                                 # no Blender render exists: say so

    def test_05_history_lists_and_animates_revisions(self):
        st, p = self.st, self.load()
        revs = share.revisions(st, p)
        self.assertEqual([r["n"] for r in revs], sorted(r["n"] for r in p["revisions"]))
        self.assertEqual(sum(r["head"] for r in revs), 1)
        self.assertEqual(revs[0]["by"], "you")
        self.assertRegex(revs[-1]["stamp"], r"^r\d\d [0-9a-f]{4}$")
        self.assertEqual(share.who("agent:claude-code"), "claude-code")
        for name in ("h.gif", "h.webp"):
            info = share.history(st, p, Path(TMP) / name, size=(240, 180), fade=1)
            with Image.open(info["file"]) as im:
                self.assertEqual(im.size, (240, 180))
                self.assertEqual(im.n_frames, info["frames"])
            self.assertEqual(info["revisions"], [r["n"] for r in revs])
            self.assertEqual(info["skipped"], [])
        with self.assertRaises(StudioError):
            share.history(st, p, Path(TMP) / "h.mp4")

    def test_06_server_and_cli_parity(self):
        import io
        import threading
        import urllib.request
        from contextlib import redirect_stdout
        from http.server import ThreadingHTTPServer
        from form.__main__ import main
        from form.server import make_handler
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api/projects/{self.pid}"

        def call(path, body=None):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                return json.loads(data) if r.headers["Content-Type"].startswith("application/json") else data
        try:
            self.assertEqual(call("/revisions")["head"], self.load()["head"])
            v = call("/variant_save", {"name": "Low back", "values": {"back_height": 30}})["variant"]
            self.assertEqual(v["id"], "low-back")
            self.assertIn("low-back", [c["id"] for c in call("/variants")["cards"]])
            self.assertTrue(call("/variants/low-back/view")["mesh"])
            self.assertTrue(call("/variants/@head/view")["mesh"])
            png = call("/share.png")
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            name = call("/history_export", {"format": "gif"})["name"]
            self.assertEqual(call("/file/share/" + name)[:6], b"GIF89a")
            self.assertEqual(call("/variant_delete", {"id": "low-back"})["deleted"], "low-back")
        finally:
            httpd.shutdown()
        self.st.kernel.stop()                       # the CLI starts its own studio on the same folder

        def cli(*argv):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(list(argv))
            return rc, json.loads(buf.getvalue())
        rc, out = cli("variants", "save", self.pid, "CLI one", "depth=90")
        self.assertEqual((rc, out["id"]), (0, "cli-one"))
        rc, out = cli("variants", "list", self.pid)
        self.assertIn("cli-one", [c["id"] for c in out["cards"]])
        card = str(Path(TMP) / "cli-card.png")
        rc, out = cli("share", self.pid, "--out", card)
        self.assertEqual(rc, 0)
        self.assertTrue(Path(card).is_file())
        gif = str(Path(TMP) / "cli.gif")
        rc, out = cli("history", self.pid, "--gif", gif)
        self.assertEqual(out["animation"]["file"], gif)
        self.assertTrue(Path(gif).is_file())
        rc, out = cli("mark", self.pid, "--text", "CLI")
        self.assertEqual(out["label_text"], "CLI")
        rc, out = cli("variants", "promote", self.pid, "nope")
        self.assertEqual(rc, 2)
        self.assertIn("No variant", out["error"]["message"])


class McpTools(unittest.TestCase):
    def test_tools_are_registered(self):
        import anyio
        from form import mcp_server

        async def names():
            return {t.name for t in await mcp_server.build().list_tools()}
        got = anyio.run(names)
        for t in ("save_variant", "list_variants", "share_card"):
            self.assertIn(t, got)


if __name__ == "__main__":
    unittest.main()
