"""Open in <Slicer> (form/slicer_open.py): the settings chooser, the slicer's keys, the project 3MF, and the whole path
with a stand-in OrcaSlicer that writes a project 3MF the way the real CLI does. Nothing is opened: FORM_FAKE_LAUNCH
records what would have been."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from form import slicer_open as so
from form.studio import Studio, StudioError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_plates import stand_in, studio_cfg  # noqa: E402
from test_slicers import FIX  # noqa: E402

BBL_PRESET = {"layer_height": "0.2", "wall_loops": "2", "top_shell_layers": "4", "bottom_shell_layers": "3",
              "sparse_infill_density": "15%", "sparse_infill_pattern": "grid", "enable_support": "0",
              "support_type": "normal(auto)", "brim_type": "auto_brim", "brim_width": "5", "seam_position": "aligned"}
PRUSA_PRESET = {"layer_height": "0.2", "perimeters": "2", "top_solid_layers": "5", "bottom_solid_layers": "4",
                "fill_density": "15%", "fill_pattern": "grid", "support_material": "0", "support_material_auto": "1",
                "support_material_style": "grid", "brim_type": "outer_only", "brim_width": "0", "seam_position": "aligned"}


def inputs(**over):
    """A plain part: 40 × 30 × 20 mm block, flat on the plate, nothing steep, PLA, no load."""
    i = {"nozzle_mm": 0.4, "layer_options": [0.12, 0.16, 0.2, 0.24, 0.28], "min_layer_mm": 0.08, "max_layer_mm": 0.28,
         "height_mm": 20.0, "footprint_mm": [40.0, 30.0], "contact_mm2": 1200.0, "steep_mm2": 0.0, "ceiling_mm2": 0.0,
         "support_mm3": 0.0, "sloped_share": 0.05, "thin_wall_mm": 3.0, "load": {"bearing": False, "why": ""},
         "cosmetic": {"is": False, "why": ""}, "material": {"key": "PLA", "warp": "low", "flexible": False},
         "preset": so.preset_summary("bambu", BBL_PRESET)}
    i.update(over)
    return i


def by_id(d):
    return {x["id"]: x for x in d["decisions"]}


class Chooser(unittest.TestCase):
    def test_every_decision_says_why_and_how_it_is_known(self):
        d = so.choose(inputs())
        ids = [x["id"] for x in d["decisions"]]
        self.assertEqual(ids, ["layer", "walls", "top", "bottom", "infill", "support", "brim", "seam"])
        for x in d["decisions"]:
            self.assertIn(x["evidence"], ("computed", "heuristic"), x)
            self.assertTrue(x["why"].strip(), x)
        self.assertEqual(so.choose(inputs()), d)                       # deterministic

    def test_a_plain_part_keeps_the_preset(self):
        d = so.choose(inputs())
        self.assertEqual(d["want"], {"layer": 0.2, "support": False})   # 0.8 mm skin at 0.2 mm = 4 top layers: the preset has 4
        b = by_id(d)
        self.assertFalse(b["walls"]["changed"])
        self.assertFalse(b["infill"]["changed"])
        self.assertFalse(b["brim"]["changed"])
        self.assertIn("half the 0.4 mm nozzle", b["layer"]["why"])

    def test_a_loaded_part(self):
        d = so.choose(inputs(load={"bearing": True, "why": "its “Arm bending safety factor” check models a load"}))
        w = d["want"]
        self.assertEqual((w["walls"], w["infill"], w["pattern"]), (4, 40, "gyroid"))
        self.assertEqual((w["top"], w["bottom"]), (6, 5))               # 1.2 and 1.0 mm of skin at 0.2 mm layers
        self.assertIn("load-bearing", by_id(d)["walls"]["why"])
        self.assertEqual(by_id(d)["top"]["evidence"], "computed")

    def test_curved_surface_gets_finer_layers_from_the_presets(self):
        d = so.choose(inputs(sloped_share=0.6, cosmetic={"is": True, "why": "“vase” in the design's name or brief"}))
        self.assertEqual(d["want"]["layer"], 0.16)
        self.assertIn("60% of the surface", by_id(d)["layer"]["why"])
        self.assertEqual(d["want"]["seam"], "back")

    def test_layer_is_one_the_printer_offers(self):
        d = so.choose(inputs(sloped_share=0.6, layer_options=[0.1, 0.2, 0.3]))
        self.assertEqual(d["want"]["layer"], 0.2)                       # 0.16 wanted; 0.2 is the nearest preset (0.1 is as near: the coarser wins)
        self.assertIn("nearest of this printer's presets", by_id(d)["layer"]["why"])
        tall = so.choose(inputs(height_mm=150, sloped_share=0.05))
        self.assertEqual(tall["want"]["layer"], 0.24)

    def test_supports_only_where_overhangs_need_them(self):
        none = so.choose(inputs(steep_mm2=5.0))
        self.assertFalse(none["want"]["support"])
        self.assertEqual(by_id(none)["support"]["evidence"], "computed")
        high = so.choose(inputs(steep_mm2=300.0, support_mm3=6000.0))  # 20 mm average height under the overhang
        self.assertEqual((high["want"]["support"], high["want"]["support_style"]), (True, "tree"))
        low = so.choose(inputs(steep_mm2=300.0, support_mm3=600.0))    # 2 mm: low and broad
        self.assertEqual(low["want"]["support_style"], "normal")

    def test_brim_for_tall_narrow_small_contact_or_warping(self):
        self.assertNotIn("brim", so.choose(inputs())["want"])
        tall = so.choose(inputs(height_mm=90, footprint_mm=[20, 25]))
        self.assertEqual((tall["want"]["brim"], tall["want"]["brim_width"]), (True, 5))
        self.assertIn("tall for its base", by_id(tall)["brim"]["why"])
        abs_ = so.choose(inputs(footprint_mm=[120, 40], material={"key": "ABS", "warp": "high", "flexible": False}))
        self.assertEqual(abs_["want"]["brim_width"], 8)
        small = so.choose(inputs(contact_mm2=40))
        self.assertTrue(small["want"]["brim"])

    def test_flexible_material(self):
        d = so.choose(inputs(material={"key": "TPU", "warp": "low", "flexible": True}))
        self.assertEqual((d["want"]["infill"], d["want"]["pattern"]), (20, "gyroid"))

    def test_layer_follows_the_nozzle(self):
        d = so.choose(inputs(nozzle_mm=0.6, layer_options=[0.18, 0.24, 0.3, 0.36, 0.42], min_layer_mm=0.12, max_layer_mm=0.42))
        self.assertEqual(d["want"]["layer"], 0.3)


class SlicerKeys(unittest.TestCase):
    def test_bambu_family_keys(self):
        want = {"layer": 0.16, "walls": 4, "top": 6, "bottom": 5, "infill": 40, "pattern": "gyroid", "support": True,
                "support_style": "tree", "brim": True, "brim_width": 8, "seam": "back"}
        out, skipped = so.overrides("orca", want, BBL_PRESET)
        self.assertEqual(out, {"layer_height": "0.16", "wall_loops": "4", "top_shell_layers": "6", "bottom_shell_layers": "5",
                               "sparse_infill_density": "40%", "sparse_infill_pattern": "gyroid", "enable_support": "1",
                               "support_type": "tree(auto)", "brim_type": "outer_only", "brim_width": "8",
                               "seam_position": "back"})
        self.assertEqual(skipped, [])

    def test_prusa_family_keys(self):
        want = {"walls": 4, "infill": 40, "pattern": "gyroid", "support": True, "support_style": "tree", "brim": True,
                "brim_width": 5, "seam": "back"}
        out, _ = so.overrides("prusa", want, PRUSA_PRESET)
        self.assertEqual(out, {"perimeters": "4", "fill_density": "40%", "fill_pattern": "gyroid", "support_material": "1",
                               "support_material_style": "organic", "brim_width": "5", "seam_position": "rear"})

    def test_only_keys_the_preset_has_and_values_it_speaks(self):
        out, skipped = so.overrides("bambu", {"walls": 4, "pattern": "gyroid"}, {"wall_loops": ["2"], "sparse_infill_pattern": "made-up"})
        self.assertEqual(out, {"wall_loops": ["4"]})                    # same shape as the preset (a list here)
        self.assertEqual([s["setting"] for s in skipped], ["pattern"])
        out, skipped = so.overrides("bambu", {"top": 6}, {})
        self.assertEqual(out, {})
        self.assertEqual(skipped[0]["why"], "the preset has no such key")

    def test_nothing_written_that_equals_the_preset(self):
        out, _ = so.overrides("bambu", {"walls": 2, "layer": 0.2}, BBL_PRESET)
        self.assertEqual(out, {})


def project_3mf(path: Path, settings: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("Metadata/project_settings.config", json.dumps(settings))
        z.writestr("Metadata/plate_1.gcode", "; gcode\n")
    return path


class ProjectFile(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="form-so-"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_settings_are_read_back_and_marked_as_edits(self):
        f = project_3mf(self.d / "p.3mf", dict(BBL_PRESET, wall_loops="4", sparse_infill_density="40%",
                                               different_settings_to_system=["", "", ""]))
        changes = {"wall_loops": "4", "sparse_infill_density": "40%"}
        self.assertTrue(so.mark_changed(f, list(changes)))
        got = so.read_project_settings(f)
        self.assertEqual(got["different_settings_to_system"][0], "sparse_infill_density;wall_loops")
        v = so.verify(f, changes)
        self.assertTrue(all(x["ok"] for x in v.values()), v)
        with zipfile.ZipFile(f) as z:                                    # everything else is kept
            self.assertEqual(z.read("Metadata/plate_1.gcode"), b"; gcode\n")

    def test_a_missing_setting_is_reported(self):
        f = project_3mf(self.d / "p.3mf", BBL_PRESET)
        v = so.verify(f, {"wall_loops": "4"})
        self.assertEqual(v["wall_loops"], {"want": "4", "found": "2", "ok": False})

    def test_prusa_project(self):
        f = self.d / "q.3mf"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("Metadata/Slic3r_PE.config", "; generated by PrusaSlicer\n; perimeters = 4\n; fill_density = 40%\n")
        self.assertEqual(so.verify(f, {"perimeters": "4", "fill_density": "40%"})["perimeters"]["ok"], True)

    def test_the_app_bundle(self):
        if sys.platform == "darwin":
            self.assertEqual(so.app_bundle("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"), "/Applications/OrcaSlicer.app")
        self.assertEqual(so.app_bundle("/usr/bin/orca-slicer"), "/usr/bin/orca-slicer")


# The stand-in writes what OrcaSlicer's CLI writes: plate_1.gcode and plate.3mf with the settings it was given.
STAND_IN = f"""\
    if args == ["--help"]:
        print("OrcaSlicer-2.5.1:"); sys.exit(0)
    out = args[args.index("--outputdir") + 1]
    merged = {{}}
    for f in args[args.index("--load-settings") + 1].split(";") + [args[args.index("--load-filaments") + 1]]:
        merged.update(json.load(open(f)))
    merged["different_settings_to_system"] = ["", "", ""]
    shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
    import zipfile
    with zipfile.ZipFile(os.path.join(out, "plate.3mf"), "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps(merged))
        z.writestr("Metadata/slice_info.config", '<config><plate><metadata key="prediction" value="600"/>'
                                                 '<metadata key="weight" value="3.5"/></plate></config>')
    """


@unittest.skipIf(sys.platform.startswith("win"), "stand-in programs are POSIX scripts")
class OpenInSlicer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-so-run-"))
        app = stand_in(cls.tmp, STAND_IN)
        cls.st = Studio(studio_cfg(cls.tmp / "data", orca={"app": app, "config_dir": str(FIX / "orca" / "config")}))
        cls.st.cfg["slicer"]["kind"] = "orca"
        cls.p = cls.st.create("Shelf bracket", "shelf_bracket", purpose="print")
        cls.job = cls.st.run_sync(cls.p["id"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_choose_slice_write_check_and_open(self):
        self.assertEqual(self.job["state"], "done", self.job)
        log = self.tmp / "launch.jsonl"
        with mock.patch.dict(os.environ, {"FORM_FAKE_LAUNCH": str(log)}):
            r = so.run(self.st, self.st.load(self.p["id"]))
        self.assertEqual(r["slicer"], "OrcaSlicer")
        self.assertEqual(r["evidence"], "simulated")
        self.assertEqual((r["time_s"], r["filament_g"]), (600.0, 3.5))   # the slicer's own estimate, read from its project
        ids = [d["id"] for d in r["decisions"]]
        for want in ("orientation", "layer", "walls", "infill", "support", "brim", "seam", "filament", "profile"):
            self.assertIn(want, ids)
        self.assertIn("load-bearing", next(d for d in r["decisions"] if d["id"] == "walls")["why"])
        # the fixture's process has no infill-pattern or shell keys: those are left out and said so, never invented
        self.assertEqual(r["overrides"], {"wall_loops": "4", "sparse_infill_density": "40%"})
        self.assertIn("sparse_infill_pattern", [s["key"] for s in r["not_written"]])
        self.assertTrue(r["settings_in_file"])
        f = Path(r["file"])
        self.assertTrue(f.is_file() and f.suffix == ".3mf")
        got = so.read_project_settings(f)
        self.assertEqual((got["wall_loops"], got["sparse_infill_density"]), ("4", "40%"))
        self.assertEqual(got["different_settings_to_system"][0], "sparse_infill_density;wall_loops")
        opened = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual(opened, [{"opened": str(f), "with": so.app_bundle(self.st.slicer_info(p=self.p)["app"])}])
        self.assertTrue(r["opened"]["fake"])
        again = so.run(self.st, self.st.load(self.p["id"]), open_app=False)  # cached: same file, not opened
        self.assertEqual(again["file"], r["file"])
        self.assertNotIn("opened", again)

    def test_a_3d_model_is_not_opened_in_a_slicer(self):
        p = self.st.settings(self.st.load(self.p["id"]), {"purpose": "model"})
        try:
            with self.assertRaises(StudioError) as e:
                so.run(self.st, p, open_app=False)
            self.assertIn("Make it printable", e.exception.hint)
        finally:
            self.st.settings(self.st.load(self.p["id"]), {"purpose": "print"})
            self.st.run_sync(self.p["id"])

    def test_printing_off(self):
        caps = self.st.cfg["general"]["capabilities"]
        self.st.cfg["general"]["capabilities"] = ["core"]
        try:
            with self.assertRaises(StudioError):
                so.run(self.st, self.st.load(self.p["id"]), open_app=False)
        finally:
            self.st.cfg["general"]["capabilities"] = caps


if __name__ == "__main__":
    unittest.main()
