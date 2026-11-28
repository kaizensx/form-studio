"""Parts that do not fit one plate go onto more plates, never off one (form/plates.py), and every plate reaches the
slicer (form/plate3mf.py, form/slicer_open.py).

Packing: fits on one plate, needs three, one part too big for any plate (said with its size and what would fit it),
turning 90° about Z, a brim's room, excluded zones, determinism. The 3MF: plates written the way each slicer family
reads them (Bambu/Orca plate entries; PrusaSlicer 2.9's bed grid) and read back. Open in slicer with stand-in slicers:
one project with every plate for an Orca-family slicer, one project per plate (each opened) for a PrusaSlicer-family
one. And, where Bambu Studio or OrcaSlicer is installed, the real CLI: it reads Form Studio's plates and slices each
(its own slice_info is the evidence)."""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

from form import plate3mf, plates, slicer
from form.adapters import _bbl
from form.studio import Studio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_plates import WIDE, stand_in, studio_cfg  # noqa: E402
from test_slicers import FIX  # noqa: E402

BED = [180.0, 180.0, 180.0]


def parts(*sizes):
    return [{"id": f"p{i}", "label": f"Part {i}", "size": list(s)} for i, s in enumerate(sizes)]


def inside(test, pl, bed=BED, margin=2.0):
    for plate in pl["plates"]:
        for q in plate["parts"]:
            test.assertGreaterEqual(min(q["x"], q["y"]), margin - 1e-6, q)
            test.assertLessEqual(q["x"] + q["w"], bed[0] - margin + 1e-6, q)
            test.assertLessEqual(q["y"] + q["h"], bed[1] - margin + 1e-6, q)
        rects = [(q["x"], q["y"], q["x"] + q["w"], q["y"] + q["h"]) for q in plate["parts"]]
        for i, a in enumerate(rects):              # no two parts overlap
            for b in rects[i + 1:]:
                test.assertTrue(a[2] <= b[0] + 1e-6 or b[2] <= a[0] + 1e-6 or a[3] <= b[1] + 1e-6 or b[3] <= a[1] + 1e-6,
                                (a, b))


class Packing(unittest.TestCase):
    def test_fits_on_one_plate(self):
        pl = plates.plan(parts((60, 50, 10), (60, 50, 10), (40, 40, 5)), BED, 6, 2)
        self.assertEqual(pl["count"], 1)
        self.assertEqual(len(pl["plates"][0]["parts"]), 3)
        self.assertEqual(pl["too_big"], [])
        inside(self, pl)

    def test_needs_three_plates(self):
        pl = plates.plan(parts(*[(120, 120, 10)] * 3), BED, 6, 2)      # 120 + 6 + 120 > 176: one per plate
        self.assertEqual(pl["count"], 3)
        self.assertEqual([len(x["parts"]) for x in pl["plates"]], [1, 1, 1])
        self.assertEqual(sorted(q["id"] for x in pl["plates"] for q in x["parts"]), ["p0", "p1", "p2"])
        inside(self, pl)

    def test_one_too_big_is_said_never_placed(self):
        pl = plates.plan(parts((60, 60, 10), (250, 40, 10)), BED, 6, 2)
        self.assertEqual(pl["count"], 1)
        self.assertEqual([q["id"] for x in pl["plates"] for q in x["parts"]], ["p0"])
        b = pl["too_big"][0]
        self.assertEqual((b["id"], b["size"], b["bed_mm"], b["usable_mm"][:2]), ("p1", [250.0, 40.0, 10.0], BED, [176.0, 176.0]))
        self.assertEqual(b["fits_on_side"], [])                     # 250 long whichever side it lies on
        self.assertAlmostEqual(b["max_scale"], 176 / 250, 3)
        text = " ".join(b["suggestions"])
        for want in ("Scale it to 70 %", "Split it", "larger bed"):
            self.assertIn(want, text)
        self.assertIn("p1", plates.summary(pl).replace("Part 1", "p1"))

    def test_too_big_as_it_lies_but_not_on_its_side(self):
        b = plates.plan(parts((40, 40, 150)), [180, 180, 100], 6, 2)["too_big"][0]   # too tall standing, fits lying down
        self.assertEqual(b["fits_on_side"], [{"footprint_mm": [40.0, 150.0], "height_mm": 40.0}])
        self.assertTrue(b["suggestions"][0].startswith("Lay it on another side"))

    def test_rotation_helps(self):
        # 160 × 60 fits a 70 × 170 bed only turned 90° about Z
        pl = plates.plan(parts((160, 60, 5)), [70, 170, 100], 6, 0)
        self.assertEqual(pl["count"], 1)
        q = pl["plates"][0]["parts"][0]
        self.assertTrue(q["rotated"])
        self.assertEqual((q["w"], q["h"]), (60.0, 160.0))

    def test_brim_room_and_its_fallback(self):
        tight = plates.plan(parts((80, 80, 5), (80, 80, 5)), BED, 6, 2)
        self.assertEqual(tight["count"], 1)                          # 80 + 6 + 80 = 166 of 176
        roomy = plates.plan(parts((80, 80, 5), (80, 80, 5)), BED, 6, 2, clearance=5)
        self.assertEqual(roomy["count"], 2)                          # 90 + 6 + 90 = 186: each brim needs its room
        self.assertEqual(roomy["clearance_mm"], 5)
        big = plates.plan(parts((172, 100, 5)), BED, 6, 2, clearance=5)  # fits only without the brim's room
        self.assertEqual(big["count"], 1)
        self.assertEqual(big["too_big"], [])

    def test_excluded_zone_is_kept_clear(self):
        zone = [[0, 0, 40, 40]]                                      # the lower-left corner
        pl = plates.plan(parts(*[(50, 50, 5)] * 6), BED, 6, 2, exclude=zone)
        for x in pl["plates"]:
            for q in x["parts"]:
                self.assertTrue(q["x"] >= 40 + 6 - 1e-6 or q["y"] >= 40 + 6 - 1e-6, q)
        inside(self, pl)

    def test_round_bed_keeps_to_the_square_inside(self):
        circle = ",".join(f"{100 + 100 * np.cos(a):.3f}x{100 + 100 * np.sin(a):.3f}" for a in np.linspace(0, 2 * np.pi, 32, False))
        zones = plates.bed_zones({"bed_shape": circle})
        self.assertEqual(len(zones), 4)
        pl = plates.plan(parts((150, 150, 5)), [200, 200, 200], 6, 0, exclude=zones)
        self.assertEqual([b["id"] for b in pl["too_big"]], ["p0"])   # the square inside the 200 mm circle is 141 mm
        ok = plates.plan(parts((128, 128, 5)), [200, 200, 200], 6, 0, exclude=zones)
        self.assertEqual(ok["too_big"], [])                         # 128 and its 6 mm gap to the zones fit in 141
        self.assertEqual(ok["count"], 1)
        self.assertEqual(plates.bed_zones({"printable_area": ["0x0", "256x0", "256x256", "0x256"],
                                           "bed_exclude_area": ["0x0", "18x0", "18x28", "0x28"]}), [[0, 0, 18, 28]])

    def test_deterministic(self):
        ps = parts((30, 90, 5), (90, 30, 8), (70, 70, 3), (120, 40, 9), (40, 40, 40), (150, 20, 2))
        self.assertEqual(plates.plan(ps, BED, 6, 2), plates.plan(copy.deepcopy(ps), BED, 6, 2))

    def test_copies_and_where_each_part_is_drawn(self):
        M = [[1, 0, 0, 0], [0, 0, -1, 5], [0, 1, 0, 0]]               # as modelled -> lying on its back, centred
        ps = [dict(p, matrix=M) for p in parts((100, 100, 10))]
        pl = plates.plan(plates.copies_of(ps, 3), BED, 6, 2)
        self.assertEqual(pl["count"], 3)
        self.assertEqual([x["parts"][0]["id"] for x in pl["plates"]], ["p0", "p0#2", "p0#3"])
        q = pl["plates"][0]["parts"][0]
        m = np.array(q["matrix"])
        self.assertTrue(np.allclose(m[:, :3], np.array(M)[:, :3]))     # the print orientation is kept
        self.assertTrue(np.allclose(m[:, 3], [q["x"] + 50, q["y"] + 50 + 5, 0]))


def cube(s, h):
    P = np.array([[x, y, z] for z in (0, h) for y in (-s / 2, s / 2) for x in (-s / 2, s / 2)], float)
    T = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                  [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    return P, T


def layout(n):
    """n plates of one 100 mm cube each, plus a 20 mm cube on plate 1."""
    out = [{"n": k + 1, "parts": [{"id": f"c{k + 1}", "label": f"Cube {k + 1}", "x": 10, "y": 10, "w": 100, "h": 100,
                                    "rotated": False}]} for k in range(n)]
    out[0]["parts"].append({"id": "small", "label": "Small", "x": 130, "y": 10, "w": 20, "h": 20, "rotated": True})
    return out


MESHES = dict({f"c{k}": cube(100, 10) for k in range(1, 13)}, small=cube(20, 30))


class ThreeMF(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-plate3mf-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_grids_as_the_slicers_lay_out_plates(self):
        self.assertEqual([plate3mf.bbl_columns(n) for n in range(1, 11)], [1, 2, 2, 2, 3, 3, 3, 3, 3, 4])
        self.assertEqual([plate3mf.prusa_grid(i) for i in range(9)],
                         [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1), (0, 2), (1, 2), (2, 2)])
        self.assertEqual(plate3mf.origin("bbl", 4, 5, BED), (216.0, -216.0))       # 3 columns: column 2, row 2, 1.2 × the bed
        g = plate3mf.prusa_gap(BED)                                                   # min(100, 0.3 × the diagonal)
        self.assertAlmostEqual(g, 0.3 * (180 ** 2 * 2) ** 0.5)
        self.assertEqual(plate3mf.origin("prusa", 3, 4, BED), (180 + g, 180 + g))
        self.assertEqual(plate3mf.dialect("orca"), "bbl")
        self.assertEqual(plate3mf.dialect("qidi"), "prusa")

    def test_bambu_and_orca_dialect_round_trip(self):
        f = self.tmp / "a.3mf"
        info = plate3mf.write(f, layout(3), MESHES, "bbl", BED, "Test")
        self.assertEqual((info["plates"], info["objects"]), (3, 4))
        r = plate3mf.read(f)
        self.assertEqual(r["dialect"], "bbl")
        self.assertEqual(r["plates"], [{"n": 1, "objects": ["Cube 1", "Small"]}, {"n": 2, "objects": ["Cube 2"]},
                                       {"n": 3, "objects": ["Cube 3"]}])
        with zipfile.ZipFile(f) as z:
            self.assertIn("Metadata/model_settings.config", z.namelist())
            model = z.read("3D/3dmodel.model").decode()
        # plate 2 sits in the program's plate grid: one column over, 1.2 × the bed width
        self.assertIn('transform="1 0 0 0 1 0 0 0 1 276.0000 60.0000 0.0000"', model)
        # the small cube was turned 90° on its plate: its mesh is, the item only moves it
        self.assertIn('transform="1 0 0 0 1 0 0 0 1 140.0000 20.0000 0.0000"', model)

    def test_prusa_dialect_round_trip_and_more_than_nine_plates(self):
        files = plate3mf.write_all(self.tmp, "b", layout(4), MESHES, "prusa", BED)
        self.assertEqual(len(files), 1)
        r = plate3mf.read(files[0])
        self.assertEqual(r["dialect"], "prusa")
        self.assertEqual([x["objects"] for x in r["plates"]], [["Cube 1", "Small"], ["Cube 2"], ["Cube 3"], ["Cube 4"]])
        self.assertEqual(r["outside"], [])
        with zipfile.ZipFile(files[0]) as z:
            self.assertIn("Metadata/Slic3r_PE_model.config", z.namelist())
            self.assertNotIn("Metadata/model_settings.config", z.namelist())
        many = plate3mf.write_all(self.tmp / "many", "c", layout(12), MESHES, "prusa", BED)
        self.assertEqual([f.name for f in many], ["c_plates1-9.3mf", "c_plates10-12.3mf"])
        self.assertEqual([len(plate3mf.read(f)["plates"]) for f in many], [9, 3])
        one = plate3mf.write_all(self.tmp / "bbl", "d", layout(12), MESHES, "bbl", BED)
        self.assertEqual(len(one), 1)
        self.assertEqual(len(plate3mf.read(one[0])["plates"]), 12)


# ---- the studio: a design too wide for its plate, exported and opened in a slicer --------------------------------

ORCA_PLATES = f"""\
    if args == ["--help"]:
        print("OrcaSlicer-2.5.1:"); sys.exit(0)
    out = args[args.index("--outputdir") + 1]
    merged = {{}}
    for f in args[args.index("--load-settings") + 1].split(";") + [args[args.index("--load-filaments") + 1]]:
        merged.update(json.load(open(f)))
    merged["different_settings_to_system"] = ["", "", ""]
    src = args[-1]
    json.dump(args, open(os.path.join(out, "args.json"), "w"))
    import zipfile
    cfg, n = None, 1
    if src.endswith(".3mf"):
        cfg = zipfile.ZipFile(src).read("Metadata/model_settings.config").decode()
        n = cfg.count("<plate>")
    info = "".join(f'<plate><metadata key="index" value="{{i}}"/><metadata key="prediction" value="{{600 * i}}"/>'
                   f'<metadata key="weight" value="{{3.5 * i}}"/><metadata key="outside" value="false"/></plate>' for i in range(1, n + 1))
    for i in range(1, n + 1):
        shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, f"plate_{{i}}.gcode"))
    with zipfile.ZipFile(os.path.join(out, "plate.3mf"), "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps(merged))
        z.writestr("Metadata/slice_info.config", "<config>" + info + "</config>")
        z.writestr("3D/3dmodel.model", zipfile.ZipFile(src).read("3D/3dmodel.model") if cfg else
                   '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build/></model>')
        if cfg:
            z.writestr("Metadata/model_settings.config", cfg)
    """

PRUSA_PLATES = f"""\
    if args == ["--help"]:
        print("PrusaSlicer-2.9.2+linux-x64"); sys.exit(0)
    out = args[args.index("--output") + 1]
    if "--export-gcode" in args:
        shutil.copyfile({str(FIX / "prusa" / "plate_1.gcode")!r}, out)
    else:
        import zipfile
        ini = open(args[args.index("--load") + 1]).read()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("Metadata/Slic3r_PE.config", "".join("; " + ln + chr(10) for ln in ini.splitlines() if "=" in ln))
    """


@unittest.skipIf(sys.platform.startswith("win"), "stand-in programs are POSIX scripts")
class OpenEveryPlate(unittest.TestCase):
    """A hinged box 236 mm wide on a 180 mm plate: two plates, each reaching the slicer."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-plates-open-"))
        orca = stand_in(cls.tmp, ORCA_PLATES)
        cls.prusa = stand_in(cls.tmp, PRUSA_PLATES)
        cls.st = Studio(studio_cfg(cls.tmp / "data", orca={"app": orca, "config_dir": str(FIX / "orca" / "config")}))
        cls.st.cfg["slicer"]["kind"] = "orca"
        cls.p = cls.st.create("Wide box", "hinged_box", values=WIDE)
        cls.job = cls.st.run_sync(cls.p["id"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def load(self):
        return self.st.load(self.p["id"])

    def test_the_plan_lays_every_part_on_a_plate(self):
        self.assertEqual(self.job["state"], "done", self.job)
        ch = self.st.state(self.p["id"])["checks"]
        pl = ch["context"]["plates"]
        self.assertTrue(pl["needed"])
        self.assertEqual(pl["count"], 2)
        inside(self, pl, BED, 2.0)
        for x in pl["plates"]:                             # where the app draws each part: on its plate, on z = 0
            for q in x["parts"]:
                self.assertEqual(len(q["matrix"]), 3)

    def test_exported_3mf_has_every_plate(self):
        from form import materials
        f = self.tmp / "export.3mf"
        f.write_bytes(materials.threemf(self.st, self.load()))
        r = plate3mf.read(f)
        self.assertEqual((r["dialect"], [x["objects"] for x in r["plates"]]), ("bbl", [["Box"], ["Lid"]]))
        out = plates.write_3mf(self.st, self.load(), self.tmp / "x3", copies=3, kind="prusa")
        self.assertEqual((out["dialect"], out["plates"], len(out["files"])), ("prusa", 6, 1))
        self.assertEqual(len(plate3mf.read(Path(out["files"][0]))["plates"]), 6)

    def test_orca_gets_one_project_with_every_plate(self):
        from form import slicer_open as so
        log = self.tmp / "launch_orca.jsonl"
        one = so.run(self.st, self.load(), open_app=False)        # the stand-in's printer (350 mm) takes both parts
        self.assertEqual((one["plate_count"], len(one["files"])), (1, 1))
        with mock.patch.dict(os.environ, {"FORM_FAKE_LAUNCH": str(log)}):
            r = so.run(self.st, self.load(), copies=8)              # 16 parts: more than one plate of it
        n = r["layout"]["count"]
        self.assertGreater(n, 1)
        self.assertEqual((r["plate_count"], r["plates_in_project"], r["plates_sliced"]), (n, n, n))
        self.assertEqual(len(r["files"]), 1)
        self.assertEqual(sum(len(x["parts"]) for x in r["plates"]), 16)
        self.assertEqual(r["time_s"], 600.0 * n * (n + 1) / 2)          # the stand-in's 600 s × plate number, added up
        self.assertNotIn("plates_warning", r)
        opened = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual([x["opened"] for x in opened], r["files"])          # one project, opened once
        self.assertFalse(opened[0].get("new_instance"))

    def test_prusa_gets_a_project_per_plate_each_opened(self):
        from form import slicer_open as so
        st = Studio(studio_cfg(self.tmp / "data_prusa", prusa={"app": self.prusa, "config_dir": str(FIX / "prusa" / "config")}))
        st.cfg["slicer"]["kind"] = "prusa"
        p = st.create("Wide box", "hinged_box", values=WIDE)
        self.assertEqual(st.run_sync(p["id"])["state"], "done")
        log = self.tmp / "launch_prusa.jsonl"
        with mock.patch.dict(os.environ, {"FORM_FAKE_LAUNCH": str(log)}):
            r = so.run(st, st.load(p["id"]), copies=6)
        self.assertEqual(r["slicer"], "PrusaSlicer")
        n = r["layout"]["count"]
        self.assertGreater(n, 1)
        self.assertEqual((r["plate_count"], len(r["files"])), (n, n))
        self.assertEqual(sum(len(x["parts"]) for x in r["plates"]), 12)
        opened = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual([x["opened"] for x in opened], r["files"])
        self.assertTrue(all(x.get("new_instance") for x in opened))           # each in its own window
        self.assertEqual(len(plate3mf.read(Path(r["all_plates_files"][0]))["plates"]), n)


def _real():
    """A Bambu Studio or OrcaSlicer resolved with presets, or None. When the selected filament is missing here, the
    printer's generic PLA is tried (Bambu Lab profiles name it "Generic PLA @BBL <model>")."""
    from test_plates import REAL
    if REAL:
        return slicer.resolve(REAL)
    from test_slicers import base_cfg
    for kind in ("bambu", "orca"):
        cfg = base_cfg()
        cfg["slicer"]["kind"] = kind
        from form import config as config_mod
        cfg["slicer"]["app"] = config_mod.DEFAULTS["slicer"]["app"]
        if kind != "bambu":
            cfg["slicer"].pop(kind, None)
        try:
            r = slicer.resolve(cfg)
        except Exception:
            continue
        if r.get("available"):
            return r
        for fil in ("Generic PLA @BBL A1M", "Generic PLA @BBL X1C", "Generic PLA @BBL P1P", "Generic PLA @BBL A1"):
            if kind == "bambu":
                cfg["slicer"]["filament"] = fil
            else:
                cfg["slicer"][kind] = {"filament": fil}
            try:
                r = slicer.resolve(cfg)
            except Exception:
                continue
            if r.get("available"):
                return r
    return None


REAL = None if os.environ.get("FORM_SKIP_REAL_SLICER") else _real()


@unittest.skipUnless(REAL, "needs Bambu Studio or OrcaSlicer installed with a printer selected")
class TheRealSlicerReadsThePlates(unittest.TestCase):
    """The slicer's own CLI loads Form Studio's plates 3MF and slices each plate; its saved project is the evidence."""

    def test_every_plate_read_and_sliced_as_laid_out(self):
        tmp = Path(tempfile.mkdtemp(prefix="form-plates-cli-"))
        try:
            f = tmp / "in.3mf"
            # three cubes that would fit one plate, laid out on two: the slicer must keep Form Studio's plates
            plate3mf.write(f, layout(2), MESHES, "bbl", REAL.get("envelope_mm") or BED)
            info = slicer.slice_plates(REAL, f, tmp / "out", timeout=900)
            got = _bbl.read_plates(tmp / "out" / "plate.3mf")
            print(f"\n  {slicer.label(REAL['kind'])} {info.get('slicer_version')}: "
                  + "; ".join(f"plate {x['n']} {x['time_s']:.0f} s {x['filament_g']} g" for x in got))
            self.assertEqual([x["n"] for x in got], [1, 2])
            self.assertTrue(all(x["time_s"] and x["filament_g"] and not x["outside"] for x in got))
            self.assertEqual([sorted(x["objects"]) for x in plate3mf.read(tmp / "out" / "plate.3mf")["plates"]],
                             [["Cube 1", "Small"], ["Cube 2"]])
            self.assertTrue((tmp / "out" / "plate_2.gcode").is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
