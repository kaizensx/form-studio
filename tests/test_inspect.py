"""Inspection on the solid: measuring on multi-part designs, selections and annotations, colours and materials.

Rules first (no kernel), then the real kernel on a temp data folder: the hinged box (two parts, a hinge) and a
design with two bodies and no assembly declaration."""
import asyncio
import io
import json
import os
import tempfile
import unittest
import zipfile

TMP = tempfile.mkdtemp(prefix="form-inspect-")

from form import config, kernel, materials, selection  # noqa: E402
from form.design_guide import EXAMPLE  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402
from printing_cfg import with_printing  # noqa: E402

NO_ASSEMBLY = EXAMPLE.split("    def assembly(self, v):")[0]          # the example box, two bodies, nothing declared


def row(contact=400.0, footprint=(60.0, 40.0), steep=0.0, ceiling=0.0):
    return {"orientation_table": [{"id": "as_modelled", "footprint_mm": list(footprint), "contact_mm2": contact,
                                   "steep_mm2": steep, "ceiling_mm2": ceiling}]}


CTX = {"orientation": "as_modelled"}


class MaterialRules(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(materials.clean_color("#A1B2C3"), "#a1b2c3")
        self.assertIsNone(materials.clean_color(""))
        with self.assertRaises(ValueError):
            materials.clean_color("red")
        self.assertEqual(materials.clean_material("petg"), "PETG")
        self.assertEqual(materials.clean_material("Nylon"), "PA")
        with self.assertRaises(ValueError):
            materials.clean_material("unobtainium")

    def test_a_part_wins_over_the_design_and_a_material_gives_a_colour(self):
        p = {"color": None, "material": "PLA", "parts": {"lid": {"color": "#ff0000", "plate": 2}}}     # the slicer's fields
        self.assertEqual(materials.resolved(p, "lid"), {"color": "#ff0000", "material": "PLA"})
        self.assertEqual(materials.resolved(p, "body"), {"color": materials.MATERIALS["PLA"]["color"], "material": "PLA"})
        self.assertEqual(materials.resolved({"material": "petg"}, "")["material"], "PETG")       # another tool wrote it lower case
        self.assertEqual(materials.resolved({}, ""), {"color": None, "material": None})

    def test_no_material_no_notes_and_no_key_change(self):
        self.assertEqual(materials.check_items({"name": "x"}, row(), CTX), [])
        self.assertIsNone(materials.fingerprint({"color": "#112233"}))

    def test_heat_sun_warp_flex_and_resin(self):
        shower = {"name": "Shower holder", "brief": {"text": "hand shower holder"}, "material": "PLA"}
        c = materials.check_items(shower, row(), CTX)[0]
        self.assertEqual((c["status"], c["evidence"], c["id"]), ("WARN", "heuristic", "material_pla"))
        self.assertIn("hot water", c["detail"])
        self.assertEqual(materials.check_items({**shower, "material": "ASA"}, row(), CTX)[0]["status"], "PASS")
        car = {"name": "Phone mount", "brief": {"text": "on the car dashboard"}, "material": "PETG"}
        self.assertEqual(materials.check_items(car, row(), CTX)[0]["status"], "WARN")
        sun = {"name": "Planter", "brief": {"text": "outdoor balcony"}, "material": "PLA"}
        self.assertIn("sunlight", materials.check_items(sun, row(), CTX)[0]["detail"])
        big = {"name": "Tray", "material": "ABS"}
        self.assertEqual(materials.check_items(big, row(footprint=(180, 90)), CTX)[0]["status"], "WARN")
        self.assertEqual(materials.check_items(big, row(footprint=(60, 40)), CTX)[0]["status"], "PASS")
        flex = {"name": "Grip", "material": "TPU"}
        self.assertEqual(materials.check_items(flex, row(steep=40), CTX)[0]["status"], "WARN")
        self.assertIn("hardened", materials.check_items({"name": "Arm", "material": "PA-CF"}, row(), CTX)[0]["detail"])

    def test_one_row_per_material_naming_the_parts(self):
        p = {"name": "Box", "material": "PLA", "parts": {"lid": {"material": "TPU"}}}
        rows = {r["id"]: r for r in materials.check_items(p, row(), CTX)}
        self.assertEqual(set(rows), {"material_pla", "material_tpu"})
        self.assertIn("(lid)", rows["material_tpu"]["label"])
        self.assertIn("other parts", rows["material_pla"]["label"])

    def test_mass(self):
        self.assertEqual(materials.mass_g(10000, "PLA"), 12.4)
        self.assertIsNone(materials.mass_g(10000, None))

    def test_engineering_materials(self):
        eng = materials.engineering()
        for k in ("AL-6061", "AL-7075", "STEEL", "STAINLESS", "BRASS", "TITANIUM", "OAK", "WALNUT", "POM"):
            self.assertIn(k, eng)
        self.assertEqual(eng["AL-6061"]["density_g_cm3"], 2.7)            # bd_materials typical value
        self.assertEqual(eng["BRASS"]["finish"], "metal")
        self.assertEqual(materials.clean_material("aluminium 7075"), "AL-7075")
        self.assertEqual(materials.clean_material("delrin"), "POM")
        self.assertEqual(materials.clean_material("petg"), "PETG")             # filaments unchanged
        self.assertNotIn("AL-6061", materials.MATERIALS)
        self.assertEqual(materials.mass_g(10000, "AL-6061"), 27.0)              # 10 cm³ x 2.7 g/cm³
        p = {"purpose": "model", "material": "BRASS"}
        m = materials.mass(p, 10000)
        self.assertEqual((m["grams"], m["evidence"]), (85.0, "computed"))
        self.assertEqual(materials.resolved(p)["color"], eng["BRASS"]["color"])
        self.assertEqual(materials.check_items(p, {}, {}), [])                  # no filament notes for brass
        kinds = {x["id"]: x["kind"] for x in materials.catalogue()["materials"]}
        self.assertEqual((kinds["PLA"], kinds["TITANIUM"]), ("filament", "engineering"))
        # a design's appearance() zone can name one: its finish and colour, and its density
        from form import appearance
        z = appearance.validate([{"features": ["body"], "material": "aluminium"}], {"body"}, ["matte", "metal"])[0]
        self.assertEqual((z["finish"], z["material"], z["density_g_cm3"]), ("metal", "aluminum", 2.7))
        with self.assertRaises(ValueError):
            appearance.validate([{"features": ["body"], "material": "cheese"}], {"body"}, ["matte", "metal"])


class SelectionRules(unittest.TestCase):
    def test_clean_items(self):
        out = selection.clean_items([{"kind": "face", "at": [1, 2, 3], "part": "lid"},
                                     {"kind": "region", "points": [[0, 0, 0], [1, 0, 0]], "radius": 999}])
        self.assertEqual(out[0], {"kind": "face", "part": "lid", "at": [1.0, 2.0, 3.0]})
        self.assertEqual(out[1]["radius"], 50.0)
        for bad in ([], [{"kind": "blob", "at": [0, 0, 0]}], [{"kind": "point", "at": [0, 0]}],
                    [{"kind": "region", "points": []}], [{"kind": "point", "at": [0, 0, float("nan")]}]):
            with self.assertRaises(ValueError):
                selection.clean_items(bad)

    def test_summary_and_description(self):
        items = [{"kind": "point", "on": [0, 0, 0], "feature": "body", "face": {"type": "plane", "area_mm2": 10.0},
                  "tilt_deg": 90.0, "tilt": "vertical wall", "wall_thickness_mm": 2.0, "height_above_bed_mm": 5.0, "part": "a"},
                 {"kind": "point", "on": [3, 4, 0], "feature": "lid", "face": {"type": "plane", "area_mm2": 10.0},
                  "tilt_deg": 0.0, "tilt": "faces up", "wall_thickness_mm": 1.2, "height_above_bed_mm": 5.0, "part": "b"}]
        sm = selection.summary(items)
        self.assertEqual(sm["distance_mm"], 5.0)
        self.assertEqual(sm["thinnest_wall_mm"], 1.2)
        self.assertIn("distance_note", sm)
        txt = selection.describe({"items": items, "summary": sm, "rev": 3}, {"body": "Box"}, "Two walls", "why so thin?")
        self.assertIn("Selection “Two walls” on r03: why so thin?", txt)
        self.assertIn("Box (body)", txt)
        self.assertIn("thinnest wall 1.20 mm", txt)

    def test_probe_reuses_the_model_the_viewer_built(self):
        saved = dict(kernel._cache)
        try:
            kernel._cache.clear()
            kernel._cache[("geo-1", 0.03)] = m = {"tol": 0.03}
            self.assertIs(kernel._get_near("geo-1", "unused", {}, 0.05), m)
        finally:
            kernel._cache.clear()
            kernel._cache.update(saved)


class OnTheSolid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(with_printing(config.load()))
        cls.box = cls.st.create("Hinged", "hinged_box")
        cls.v = cls.st.view(cls.st.load(cls.box["id"]))

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_selection_on_a_part(self):
        p = self.st.load(self.box["id"])
        bb = self.v["bbox"]
        cy, cz = (bb[0][1] + bb[1][1]) / 2, (bb[0][2] + bb[1][2]) / 2
        side = [bb[0][0], cy, cz]                        # the outer wall of the body (left on the plate)
        r = selection.analyze(self.st, p, [{"kind": "point", "at": side}, {"kind": "face", "at": side},
                                           {"kind": "edge", "at": [bb[0][0], cy, bb[0][2]]},
                                           {"kind": "region", "points": [[side[0], cy - 4 + k, cz] for k in range(9)], "radius": 3}])
        pt, face, edge, reg = r["items"]
        self.assertEqual(r["evidence"], "computed")
        self.assertAlmostEqual(pt["tilt_deg"], 90.0, places=3)
        self.assertGreater(pt["wall_thickness_mm"], 0.8)
        self.assertLess(pt["wall_thickness_mm"], 6)
        self.assertGreater(face["face"]["area_mm2"], 100)
        self.assertIn("positions", face["mesh"])
        self.assertGreater(edge["edge"]["length_mm"], 1)
        self.assertIn("segments", edge["edge"])
        # a 8 mm stroke 3 mm wide on one flat side: 8 × 6 + π × 3² ≈ 76 mm², never the far side of the wall
        self.assertAlmostEqual(reg["area_mm2"], 8 * 6 + 3.14159 * 9, delta=6)
        self.assertEqual(reg["faces"], 1)
        self.assertEqual(reg["overhang_share"], 0.0)
        self.assertIn("Totals:", r["text"])

    def test_annotations_are_kept_with_the_revision(self):
        pid = self.box["id"]
        bb = self.v["bbox"]
        a = selection.add(self.st, pid, [{"kind": "face", "at": [bb[0][0], 0, 5]}], "Left wall", "Is it thick enough?")
        self.assertEqual(a["rev"], self.st.load(pid)["head"])
        self.assertTrue(a["id"].startswith("a"))
        self.assertNotIn("mesh", a["analysis"]["items"][0])          # drawings are recomputed, not stored
        kept = json.loads((self.st.dir(pid) / "project.json").read_text())["annotations"]
        self.assertEqual([x["name"] for x in kept], ["Left wall"])
        self.assertEqual(selection.update(self.st, pid, a["id"], note="Checked")["note"], "Checked")
        again = selection.reanalyze(self.st, pid, a["id"])
        self.assertIn("mesh", again["items"][0])
        selection.delete(self.st, pid, a["id"])
        self.assertEqual(selection.listing(self.st, pid), [])
        with self.assertRaises(StudioError):
            selection.delete(self.st, pid, a["id"])

    def test_measure_takes_the_distance_where_shown_and_the_surface_as_printed(self):
        from form import analysis
        p = self.st.load(self.box["id"])
        bb = self.v["bbox"]
        on = [bb[0][0], 0, 5]
        r = analysis.measure(self.st, p, [0, 0, 0], [10, 0, 0], a_on=on, b_on=on)
        self.assertAlmostEqual(r["distance_mm"], 10.0)
        self.assertLess(r["from_on"]["off_surface_mm"], 0.01)          # looked up at a_on, not at [0, 0, 0]

    def test_a_colour_does_not_wait_for_a_running_pipeline(self):
        import threading
        import time
        pid = self.box["id"]
        started, release = threading.Event(), threading.Event()
        real = self.st._make_checks

        def slow(p, rev, keys, name):                     # a long step, like a slice
            started.set()
            release.wait(30)
            return real(p, rev, keys, name)
        self.st._make_checks = slow
        try:
            job = self.st.run(pid, nodes=["geometry", "exports", "checks"], force=True)
            self.assertTrue(started.wait(60), "the pipeline reached the slow step")
            t0 = time.perf_counter()
            materials.set_appearance(self.st, pid, "", color="#22aa66")
            self.assertLess(time.perf_counter() - t0, 2.0)                 # the edit did not wait for the step
            release.set()
            for _ in range(600):
                if self.st.jobs[job]["state"] != "running":
                    break
                time.sleep(0.1)
        finally:
            release.set()
            self.st._make_checks = real
        self.assertEqual(self.st.jobs[job]["state"], "done")
        p = self.st.load(pid)
        self.assertEqual(p["color"], "#22aa66")                            # the edit survived the run's save
        self.assertTrue(p["produced"]["checks"][-1]["ok"])                 # and the run's result was recorded

    def test_colours_materials_checks_and_3mf(self):
        pid = self.box["id"]
        k0 = self.st.keys(self.st.load(pid))
        materials.set_appearance(self.st, pid, "", color="#3f7fbf")
        self.assertEqual(self.st.keys(self.st.load(pid)), k0)           # a colour does not stale anything
        materials.set_appearance(self.st, pid, "lid", color="#e08a2c", material="tpu")
        materials.set_appearance(self.st, pid, "", material="PETG")
        p = self.st.load(pid)
        k1 = self.st.keys(p)
        self.assertEqual((k1["geometry"], k1["exports"]), (k0["geometry"], k0["exports"]))
        self.assertNotEqual(k1["checks"], k0["checks"])                  # a material re-runs the checks
        self.assertNotEqual(k1["slice"], k0["slice"])                    # and the slice: it picks the filament per plate
        self.assertEqual(p["parts"]["lid"], {"color": "#e08a2c", "material": "TPU"})     # where the slicer reads it
        self.assertEqual((p["material"], p["color"]), ("PETG", "#3f7fbf"))
        self.assertEqual(self.st.run_sync(pid, ["geometry", "exports", "checks"])["state"], "done")
        ids = {c["id"] for c in self.st.read(p, "checks", k1["checks"])["checks"]}
        self.assertTrue({"material_petg", "material_tpu"} <= ids)
        z = zipfile.ZipFile(io.BytesIO(materials.threemf(self.st, p)))
        model = z.read("3D/3dmodel.model").decode()
        self.assertEqual(model.count("<object "), 2)
        self.assertIn('displaycolor="#3F7FBFFF"', model)
        self.assertIn('displaycolor="#E08A2CFF"', model)
        self.assertIn("TPU · Lid", model)
        with self.assertRaises(StudioError):
            materials.set_appearance(self.st, pid, "", material="cheese")
        materials.set_appearance(self.st, pid, "lid", color=None, material=None)
        self.assertNotIn("lid", self.st.load(pid).get("parts") or {})
        with self.assertRaises(StudioError):                    # a print design takes a filament, not aluminium
            materials.set_appearance(self.st, pid, "", material="aluminium")

    def test_a_model_in_aluminium_reports_its_mass(self):
        from form.digest import digest
        d = self.st.create("Machined box", "hinged_box", purpose="model")
        materials.set_appearance(self.st, d["id"], "", material="AL-7075")
        p = self.st.load(d["id"])
        self.assertEqual(p["material"], "AL-7075")
        vol = self.st.head_summary(p)["volume_mm3"]
        self.assertIn(f"{round(vol / 1000 * 2.81, 2):g} g in Aluminium 7075-T6", digest(self.st, d["id"])["mass"])

    def test_a_design_with_two_bodies_and_no_declaration(self):
        d = self.st.create_design("Two bodies", NO_ASSEMBLY)
        p = self.st.load(d["id"])
        v = self.st.view(p)
        self.assertTrue(v["assembly"]["derived"])
        self.assertEqual([x["label"] for x in v["assembly"]["parts"]], ["Body", "Lid"])     # named after their features
        self.assertEqual([x["id"] for x in v["assembly"]["parts"]], ["part1", "part2"])     # ids stay what tools store
        a = v["assembly"]["parts"][1]
        c = [(a["bbox"][0][i] + a["bbox"][1][i]) / 2 for i in range(3)]
        c[2] = a["bbox"][1][2]
        r = selection.analyze(self.st, p, [{"kind": "face", "at": c, "part": a["id"]}])
        self.assertEqual(r["items"][0]["solid"], 1)
        self.assertEqual(r["items"][0]["part"], a["id"])
        self.assertEqual(r["items"][0]["tilt"], "faces up, parallel to the bed")


class Tools(unittest.TestCase):
    def test_mcp_lists_the_new_tools(self):
        from form.mcp_server import build
        names = {t.name for t in asyncio.run(build().list_tools())}
        self.assertTrue({"analyze_selection", "list_annotations", "annotate", "set_appearance"} <= names)

    def test_cli_parses_select_annotations_appearance(self):
        import contextlib
        from form import __main__ as cli
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["select", "--help"])
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["appearance", "--help"])


if __name__ == "__main__":
    unittest.main()
