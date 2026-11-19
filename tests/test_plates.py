"""Several plates, Design only, materials and version ranges of the programs Form Studio drives.

Stand-in programs (small scripts) play the slicer where the point is Form Studio's side of the contract; the
real-slicer tests run only where Bambu Studio or OrcaSlicer is installed and say so when skipped.
"""
import copy
import json
import os
import shutil
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from form import checks as checks_mod, compat, filaments as materials, plates, slicer
from form.adapters import common
from form.studio import Studio, StudioError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_slicers import FIX, base_cfg  # noqa: E402

WIDE = {"inner_w": 110, "inner_d": 80}          # hinged box: base and lid side by side are 236 mm wide as modelled


def stand_in(folder: Path, body: str) -> str:
    """A POSIX script that runs `body` (Python, with `args`) as the slicer."""
    py = folder / f"stand_in_{len(list(folder.glob('stand_in_*')))}.py"
    py.write_text("import sys, shutil, json, os\nargs = sys.argv[1:]\n" + textwrap.dedent(body), encoding="utf-8")
    p = folder / f"slicer_{py.stem[-1]}"
    p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


# ---- version ranges ------------------------------------------------------------------------------------------

class VersionRanges(unittest.TestCase):
    def test_every_adapter_and_bridge_has_a_range(self):
        for kind in list(slicer.SLICERS) + ["blender", "freecad", "openscad"]:
            self.assertIn(kind, compat.RANGES, kind)
            label, lo, hi, url = compat.RANGES[kind]
            self.assertLessEqual(compat.parse(lo), compat.parse(hi))
            self.assertTrue(url.startswith("https://"))

    def test_versions_as_programs_print_them(self):
        self.assertEqual(compat.parse("02.09.01.70"), (2, 9, 1, 70))
        self.assertEqual(compat.parse("OpenSCAD version 2021.01"), (2021, 1))
        self.assertEqual(compat.parse("Blender 5.2.3 LTS"), (5, 2, 3))
        self.assertIsNone(compat.parse("unknown"))

    def test_status_inside_outside_unknown(self):
        self.assertTrue(compat.status("orca", "2.5.1")["supported"])
        self.assertTrue(compat.status("bambu", "02.09.01.70")["supported"])
        s = compat.status("orca", "2.6.0")
        self.assertEqual((s["supported"], s["newer"]), (False, True))
        self.assertEqual(compat.status("orca", "1.9.0")["newer"], False)
        self.assertIsNone(compat.status("orca", "unavailable")["supported"])

    def test_only_a_version_change_is_blamed_on_the_version(self):
        msg = compat.explain("orca", "2.6.0", "OrcaSlicer refused to slice: Unknown option --load-filaments")
        self.assertEqual(msg, "Form Studio works with OrcaSlicer 2.0–2.5; you have 2.6.0. Update Form Studio, or install "
                              "OrcaSlicer 2.5 (https://github.com/SoftFever/OrcaSlicer/releases).")
        self.assertIn("Update OrcaSlicer to 2.5", compat.explain("orca", "1.8", "Invalid parameters to the slicer. (exit code -2)"))
        self.assertIsNone(compat.explain("orca", "2.5.1", "Unknown option --load-filaments"))        # supported: not the cause
        self.assertIsNone(compat.explain("orca", "2.6.0", "Some objects are located over the boundary"))   # another kind
        self.assertIsNone(compat.explain("orca", "unknown", "Unknown option --x"))                   # cannot tell
        self.assertIn("Blender 4.2–5.2", compat.explain("blender", "6.0.1", "AttributeError: 'Scene' has no attribute 'eevee'"))
        self.assertIn("OpenSCAD 2021.1–2026.10", compat.explain("openscad", "2027.01.1", "Unknown export format: binstl"))


@unittest.skipIf(sys.platform.startswith("win"), "stand-in programs are POSIX scripts")
class VersionErrorsFromAFakeSlicer(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="form-compat-"))
        self.stl = self.d / "part.stl"
        self.stl.write_text("solid x\nendsolid x\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_orca(self, version, refusal):
        app = stand_in(self.d, f"""\
            if args == ["--help"]:
                print("OrcaSlicer-{version}:"); sys.exit(0)
            print({refusal!r}); sys.exit(254)
            """)
        cfg = base_cfg(orca={"app": app, "config_dir": str(FIX / "orca" / "config")})
        cfg["slicer"]["kind"] = "orca"
        r = slicer.resolve(cfg)
        self.assertTrue(r["available"], r.get("reason"))
        with self.assertRaises(common.SlicerFailed) as cm:
            slicer.slice_stl(r, self.stl, self.d / f"out-{version}", timeout=60)
        return cm.exception

    def test_newer_version_with_a_removed_option_names_the_range(self):
        e = self.run_orca("2.9.0", "Unknown option: --load-filaments")
        self.assertTrue(str(e).startswith("Form Studio works with OrcaSlicer 2.0–2.5; you have 2.9.0. Update Form Studio"), str(e))
        self.assertIn("Unknown option", e.hint)                  # the slicer's own words are kept

    def test_same_failure_on_a_supported_version_keeps_the_slicers_words(self):
        e = self.run_orca("2.5.1", "Unknown option: --load-filaments")
        self.assertNotIn("Form Studio works with", str(e))
        self.assertIn("Invalid parameters to the slicer", str(e))

    def test_detect_all_reports_the_range(self):
        app = stand_in(self.d, 'print("OrcaSlicer-2.9.0:")\n')
        cfg = base_cfg(orca={"app": app, "config_dir": str(FIX / "orca" / "config")})
        row = next(x for x in slicer.detect_all(cfg) if x["kind"] == "orca")
        self.assertEqual((row["compat"]["supported"], row["compat"]["range"]), (False, "OrcaSlicer 2.0–2.5"))


# ---- materials ----------------------------------------------------------------------------------------------

class Materials(unittest.TestCase):
    def test_names(self):
        self.assertEqual([materials.normalise(x) for x in ("petg", "PLA+", "Nylon", "tpu 95a", "wood", "")],
                         ["PETG", "PLA", "PA", "TPU", None, None])

    def test_the_generic_preset_wins_and_fibre_or_support_presets_never_stand_in(self):
        offered = [("Bambu PLA Basic @BBL A1M", "system"), ("Generic PLA @BBL A1M", "system"), ("Generic PLA-CF @BBL A1M", "system"),
                   ("Bambu Support For PLA @BBL A1M", "system"), ("My PLA", "user"), ("Generic PETG HF @BBL A1M", "system"),
                   ("Bambu PETG Basic @BBL A1M", "system"), ("Generic TPU @BBL A1M", "system")]
        def best(key):
            ranked = sorted((materials.rank(n, s, key), n) for n, s in offered if materials.rank(n, s, key) is not None)
            return ranked[0][1] if ranked else None
        self.assertEqual(best("PLA"), "Generic PLA @BBL A1M")
        self.assertEqual(best("PLA-CF"), "Generic PLA-CF @BBL A1M")
        self.assertEqual(best("PETG"), "Bambu PETG Basic @BBL A1M")
        self.assertEqual(best("TPU"), "Generic TPU @BBL A1M")
        self.assertIsNone(best("ASA"))
        self.assertEqual(materials.material_of_preset("Generic PLA-CF @System"), "PLA-CF")
        self.assertEqual(materials.material_of_preset("Whatever", "PETG"), "PETG")

    def test_where_a_material_comes_from(self):
        p = {"material": "pla", "parts": {"lid": {"material": "TPU", "color": "#ff0000"}}}
        m = materials.of_project(p, [{"id": "body", "material": "PETG"}, {"id": "lid"}, {"id": "pin", "material": ""}])
        self.assertEqual({k: (v["material"], v["source"]) for k, v in m["parts"].items()},
                         {"body": ("PLA", "design"), "lid": ("TPU", "part"), "pin": ("PLA", "design")})
        m = materials.of_project({}, [{"id": "body", "material": "PETG"}])
        self.assertEqual(m["parts"]["body"]["source"], "recipe")
        self.assertEqual(materials.stated({"parts": {"lid": {"material": "TPU"}}}), None)   # one part never speaks for all


# ---- the plan ------------------------------------------------------------------------------------------------

class Plan(unittest.TestCase):
    BED = [180, 180, 180]

    def parts(self, *sizes, material=""):
        return [{"id": f"p{i}", "label": f"Part {i}", "size": list(s), "material": material} for i, s in enumerate(sizes)]

    def test_parts_that_do_not_share_a_plate_get_their_own(self):
        pl = plates.plan(self.parts((150, 150, 20), (150, 150, 10), (20, 20, 5)), self.BED, 6, 2)   # 150 + 6 + 20 = 176 usable
        self.assertEqual(pl["count"], 2)
        self.assertEqual(sorted(len(x["parts"]) for x in pl["plates"]), [1, 2])
        for plate in pl["plates"]:
            for q in plate["parts"]:                                  # inside the bed, margin kept
                self.assertGreaterEqual(min(q["x"], q["y"]), 2 - 1e-6)
                self.assertLessEqual(q["x"] + q["w"], 178 + 1e-6)
                self.assertLessEqual(q["y"] + q["h"], 178 + 1e-6)

    def test_one_material_per_plate(self):
        ps = self.parts((40, 40, 5), (40, 40, 5)) + [dict(self.parts((40, 40, 5))[0], id="t", material="TPU")]
        pl = plates.plan(ps, self.BED, 6, 2)
        self.assertEqual(sorted(x["material"] for x in pl["plates"]), ["", "TPU"])
        self.assertTrue(plates.needed(ps, [100, 40, 5], self.BED, 2))

    def test_too_big_whichever_way_it_lies(self):
        pl = plates.plan(self.parts((200, 30, 5), (170, 20, 5), (40, 30, 300)), self.BED, 6, 2)
        self.assertEqual([x["id"] for x in pl["too_big"]], ["p0", "p2"])        # 170 fits (176 usable); 300 tall does not
        self.assertEqual(pl["count"], 1)

    def test_fits_as_modelled_needs_no_plan(self):
        ps = self.parts((60, 60, 5), (60, 60, 5))
        self.assertFalse(plates.needed(ps, [130, 60, 5], self.BED, 2))
        self.assertTrue(plates.needed(ps, [190, 60, 5], self.BED, 2))
        self.assertFalse(plates.needed(ps[:1], [190, 60, 5], self.BED, 2))

    def test_a_plate_as_one_stl(self):
        d = Path(tempfile.mkdtemp(prefix="form-plate-"))
        try:
            cube = d / "a.stl"           # a 10 × 20 × 5 box, two triangles per face are enough for its extent
            pts = [(0, 0, 0), (10, 0, 0), (10, 20, 0), (0, 20, 0), (0, 0, 5), (10, 0, 5), (10, 20, 5), (0, 20, 5)]
            faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7),
                     (2, 7, 6), (3, 0, 4), (3, 4, 7)]
            cube.write_text("solid c\n" + "".join("facet normal 0 0 0\nouter loop\n" + "".join(
                f"vertex {pts[i][0]} {pts[i][1]} {pts[i][2]}\n" for i in f) + "endloop\nendfacet\n" for f in faces)
                + "endsolid c\n", encoding="ascii")
            placed = [{"id": "a", "x": 2, "y": 2, "rotated": False}, {"id": "b", "x": 30, "y": 2, "rotated": True}]
            out = plates.write_plate_stl(d / "plate.stl", placed, {"a": cube, "b": cube})
            self.assertEqual(out["triangles"], 24)
            self.assertEqual(out["bbox"], [[2.0, 2.0, 0.0], [50.0, 22.0, 5.0]])     # the turned copy is 20 × 10
            self.assertEqual(len(plates.read_triangles(d / "plate.stl")), 24)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_check_says_n_plates_or_names_the_part_too_big(self):
        ctx = {"orientation": "as_modelled", "envelope": self.BED, "margin": 2, "printer": "Test", "nozzle": 0.4}
        analysis = {"brep": {"valid": True, "solids": 2, "expected_solids": 2, "volume_mm3": 1.0}, "interface_audit": [],
                    "orientation_table": [{"id": "as_modelled", "label": "Base down", "footprint_mm": [250, 120],
                                           "height_mm": 30, "steep_mm2": 0, "ceiling_mm2": 0, "contact_mm2": 500}]}

        class R:
            fit = None
            features = []
        summary = {"derived": []}
        parts = self.parts((120, 120, 30), (120, 120, 8))
        ctx2 = dict(ctx, parts=parts, plates=dict(plates.plan(parts, self.BED, 6, 2), needed=True))
        env = next(c for c in checks_mod.build(R, summary, analysis, ctx2, None) if c["id"] == "envelope")
        self.assertEqual((env["status"], env["value"]), ("PASS", "2 plates"))
        big = self.parts((200, 120, 30), (120, 120, 8))
        ctx3 = dict(ctx, parts=big, plates=dict(plates.plan(big, self.BED, 6, 2), needed=True))
        env = next(c for c in checks_mod.build(R, summary, analysis, ctx3, None) if c["id"] == "envelope")
        self.assertEqual(env["status"], "FAIL")
        self.assertTrue(env["value"].startswith("Part 0: 200.0 × 120.0 × 30.0"), env["value"])
        env = next(c for c in checks_mod.build(R, summary, analysis, ctx, None) if c["id"] == "envelope")
        self.assertEqual(env["status"], "FAIL")                    # one solid, too big: as before


# ---- the studio: Design only, and several plates sliced ---------------------------------------------------

def studio_cfg(tmp: Path, **tables) -> dict:
    cfg = copy.deepcopy(base_cfg(**tables))
    cfg["data"]["dir"] = str(tmp)
    cfg["printer"]["envelope_mm"] = [180, 180, 180]
    return cfg


class DesignOnly(unittest.TestCase):
    """No slicer installed at all, and slicing turned off: design, checks, exports and a release still work."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-design-only-"))
        cls.st = Studio(studio_cfg(cls.tmp))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_slicer_installed_still_releases(self):
        st = self.st
        p = st.create("Shelf hook", "hook")
        self.assertEqual(st.slice_mode(p)["why"], "no_slicer")
        job = st.run_sync(p["id"])
        self.assertEqual([s["node"] for s in job["steps"]], ["geometry", "exports", "checks"])
        self.assertEqual(job["state"], "done")
        s = st.state(p["id"])
        self.assertEqual(s["status"]["slice"]["state"], "off")
        g = s["gate"]
        self.assertFalse(any("Slice" in r for r in g["reasons"]), g["reasons"])
        self.assertEqual(g["not_covered"], [x for x in g["not_covered"] if x])
        self.assertIn("not sliced (Design only)", g["evidence_level"])
        if g["failures"]:
            self.skipTest("the default hook fails a check here: " + str(g["failures"]))
        r = st.approve(st.load(p["id"]), [w["id"] for w in g["warnings"]])
        m = r["manifest"]
        self.assertTrue(m["slicer"]["design_only"])
        self.assertFalse([f for f in m["files"] if f.endswith((".gcode", ".3mf"))])
        self.assertTrue([f for f in m["files"] if f.endswith(".step")])
        report = (st.dir(p["id"]) / "releases" / r["release"] / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("Not part of this release: Design only.", report)
        self.assertEqual(st.approval_state(st.load(p["id"]))["state"], "approved")

    def test_turned_off_in_settings_and_per_design(self):
        st = self.st
        p = st.create("Knob", "knob")
        st.cfg["slicer"]["enabled"] = False
        try:
            self.assertEqual(st.slice_mode(p)["why"], "settings")
        finally:
            st.cfg["slicer"]["enabled"] = True
        p = st.settings(p, {"design_only": True})
        self.assertEqual(st.slice_mode(p)["why"], "project")
        self.assertIn("design_only", [d["kind"] for d in p["decisions"]])


@unittest.skipIf(sys.platform.startswith("win"), "stand-in programs are POSIX scripts")
class SeveralPlatesWithAStandIn(unittest.TestCase):
    """A hinged box too wide for a 180 mm plate, sliced by a stand-in OrcaSlicer that records what it was given."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-plates-"))
        app = stand_in(cls.tmp, f"""\
            if args == ["--help"]:
                print("OrcaSlicer-2.5.1:"); sys.exit(0)
            out = args[args.index("--outputdir") + 1]
            json.dump(args, open(os.path.join(out, "args.json"), "w"))
            shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
            """)
        cls.st = Studio(studio_cfg(cls.tmp / "data", orca={"app": app, "config_dir": str(FIX / "orca" / "config")}))
        cls.st.cfg["slicer"]["kind"] = "orca"
        cls.p = cls.st.create("Wide box", "hinged_box", values=WIDE)
        cls.job = cls.st.run_sync(cls.p["id"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_two_plates_sliced_and_added_up(self):
        self.assertEqual(self.job["state"], "done", self.job)
        s = self.st.state(self.p["id"])
        env = next(c for c in s["checks"]["checks"] if c["id"] == "envelope")
        self.assertEqual((env["status"], env["value"]), ("PASS", "2 plates"))
        sl = s["slice"]
        self.assertEqual(sl["plate_count"], 2)
        self.assertEqual([[q["id"] for q in x["parts"]] for x in sl["plates"]], [["body"], ["lid"]])
        self.assertEqual(sl["time_s"], sum(x["time_s"] for x in sl["plates"]))
        self.assertAlmostEqual(sl["filament_g"], sum(x["filament_g"] for x in sl["plates"]))
        folder = self.st.apath(self.st.load(self.p["id"]), "slice", s["status"]["slice"]["key"])
        for x in sl["plates"]:
            self.assertTrue((folder / x["gcode"]).is_file())
            tris = plates.read_triangles(folder / x["stl"]).reshape(-1, 3)
            size = tris.max(axis=0) - tris.min(axis=0)
            self.assertLessEqual(max(size[0], size[1]), 176 + 1e-3)            # each plate fits the 180 mm bed with its margin
        self.assertFalse(list(folder.glob(".plate_*")))                        # work folders cleaned up

    def test_each_plate_can_be_inspected(self):
        p = self.st.load(self.p["id"])
        self.assertEqual(len(self.st.layers(p, 2)), 3)
        from form import toolpath
        self.assertEqual(toolpath.for_project(self.st, p, 2).layers, 3)
        with self.assertRaises(StudioError):
            self.st.plate_meta(p, 3)
        plan = plates.for_project(self.st, p)
        self.assertEqual(plan["plan"]["count"], 2)
        self.assertEqual(len(plan["sliced"]["plates"]), 2)

    def test_release_carries_every_plate(self):
        g = self.st.gate(self.st.load(self.p["id"]))
        if not g["ready"]:
            self.skipTest("not releasable here: " + "; ".join(g["reasons"]))
        r = self.st.approve(self.st.load(self.p["id"]), [w["id"] for w in g["warnings"]])
        names = sorted(r["manifest"]["files"])
        self.assertIn("wide-box_r01_plate1.gcode", names)
        self.assertIn("wide-box_r01_plate2.gcode", names)
        self.assertEqual([x["parts"] for x in r["manifest"]["slicer"]["plates"]], [["Box"], ["Lid"]])

    def test_a_part_setting_goes_into_the_keys(self):
        p = self.st.load(self.p["id"])
        before = self.st.keys(p)
        self.st.set_part(p["id"], "lid", orientation="inverted", material="petg", color="#3366ff")
        p = self.st.load(p["id"])
        after = self.st.keys(p)
        self.assertEqual(before["exports"], after["exports"])
        self.assertNotEqual(before["checks"], after["checks"])
        self.assertNotEqual(before["slice"], after["slice"])
        self.assertEqual(p["parts"]["lid"], {"orientation": "inverted", "material": "PETG", "color": "#3366ff"})
        with self.assertRaises(StudioError):
            self.st.set_part(p["id"], "lid", material="unobtainium")
        self.st.set_part(p["id"], "lid", orientation="", material="", color="")
        self.assertEqual(self.st.keys(self.st.load(p["id"])), before)          # cleared: the earlier outputs are current again


def _real_slicer():
    from form import config
    old = os.environ.get("FORM_CONFIG")
    os.environ["FORM_CONFIG"] = str(Path(tempfile.gettempdir()) / "form-no-such-config.toml")
    try:
        cfg = config.load()
    finally:
        if old is None:
            os.environ.pop("FORM_CONFIG", None)
        else:
            os.environ["FORM_CONFIG"] = old
    cfg["general"]["capabilities"] = ["core", "parts", "mesh", "print"]   # a real slice: printing is opt-in
    r = slicer.resolve(cfg)
    return cfg if r.get("available") and r["kind"] in ("bambu", "orca") else None


REAL = _real_slicer()


@unittest.skipUnless(REAL, "needs Bambu Studio or OrcaSlicer installed with a printer selected")
class SeveralPlatesWithTheRealSlicer(unittest.TestCase):
    def test_wide_box_on_two_plates(self):
        tmp = Path(tempfile.mkdtemp(prefix="form-plates-real-"))
        try:
            cfg = copy.deepcopy(REAL)
            cfg["data"]["dir"] = str(tmp)
            cfg["printer"]["envelope_mm"] = [180, 180, 180]
            st = Studio(cfg)
            p = st.create("Wide box", "hinged_box", values=WIDE)
            job = st.run_sync(p["id"])
            self.assertEqual(job["state"], "done", json.dumps(job["steps"]))
            sl = st.state(p["id"])["slice"]
            self.assertEqual(sl["plate_count"], 2)
            for x in sl["plates"]:
                self.assertGreater(x["layers"], 0)
                self.assertGreater(x["filament_g"], 0)
                self.assertTrue(x["threemf"])
            self.assertEqual(sl["slicer_kind"], slicer.resolve(cfg)["kind"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
