"""Slicers other than Bambu Studio: OrcaSlicer and PrusaSlicer (plus SuperSlicer/QIDISlicer), auto-detection, the picker.

OrcaSlicer and PrusaSlicer are not installed where these were written. Preset folders and G-code are fixtures
that follow the programs' source (tests/fixtures/slicers/SOURCES.txt). The slice runs use small stand-in
programs that only copy a fixture; they check FORM's command line and result handling, not the slicers.
"""
import copy
import os
import shutil
import stat
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

from form import config, slicer, studio
from form.adapters import AUTO_ORDER, common, orca, prusa

FIX = Path(__file__).resolve().parent / "fixtures" / "slicers"
NOWHERE = str(Path(tempfile.gettempdir()) / "form-no-such-slicer" / "app")


def base_cfg(**tables):
    """Defaults, with every slicer pointed at a program that does not exist unless given."""
    old = os.environ.get("FORM_CONFIG")
    os.environ["FORM_CONFIG"] = NOWHERE + ".toml"
    try:
        cfg = config.load()
    finally:
        if old is None:
            os.environ.pop("FORM_CONFIG", None)
        else:
            os.environ["FORM_CONFIG"] = old
    cfg = copy.deepcopy(cfg)
    cfg["slicer"]["app"] = NOWHERE
    for kind in ("orca", "prusa", "superslicer", "qidi"):
        cfg["slicer"][kind] = {"app": NOWHERE}
    for kind, t in tables.items():
        if kind == "bambu":
            cfg["slicer"].update(t)
        else:
            cfg["slicer"][kind] = t
    return cfg


def orca_cfg(app=sys.executable):
    return base_cfg(orca={"app": app, "config_dir": str(FIX / "orca" / "config")})


def prusa_cfg(app=sys.executable, **extra):
    return base_cfg(prusa={"app": app, "config_dir": str(FIX / "prusa" / "config"), **extra})


class OrcaPresets(unittest.TestCase):
    def test_resolves_selection_and_inheritance(self):
        r = orca.resolve(orca_cfg())
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual({k: v["name"] for k, v in r["presets"].items()},
                         {"machine": "Voron 2.4 350 0.4 nozzle", "process": "0.20mm Standard @Voron (FORM test)",
                          "filament": "Generic PLA @System"})
        self.assertEqual(r["envelope_mm"], [350.0, 350.0, 340.0])     # child overrides the common parent
        self.assertEqual(r["summary"]["walls"], "3")                    # from the system process
        self.assertEqual(r["summary"]["infill"], "25%")                 # from the user preset on top of it
        self.assertEqual(r["summary"]["filament_type"], "PLA")          # from OrcaFilamentLibrary/filament/base
        self.assertEqual(r["source"]["machine"], "OrcaSlicer current selection")
        self.assertEqual(r["label"], "OrcaSlicer")

    def test_pinned_preset_and_missing_preset(self):
        cfg = orca_cfg()
        cfg["slicer"]["orca"]["process"] = "0.20mm Standard @Voron"
        r = orca.resolve(cfg)
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual(r["summary"]["infill"], "15%")
        self.assertEqual(r["source"]["process"], "studio.toml")
        cfg["slicer"]["orca"]["process"] = "No such process"
        r = orca.resolve(cfg)
        self.assertFalse(r["available"])
        self.assertIn("No such process", r["reason"])
        self.assertIn("[slicer.orca].process", r["reason"])

    def test_hash_changes_with_content(self):
        a = orca.resolve(orca_cfg())["presets"]["process"]["sha"]
        cfg = orca_cfg()
        cfg["slicer"]["orca"]["process"] = "0.20mm Standard @Voron"
        self.assertNotEqual(a, orca.resolve(cfg)["presets"]["process"]["sha"])

    def test_gcode_generic_printer(self):
        g = orca.parse_gcode_header(FIX / "orca" / "generic_printer.gcode")
        self.assertEqual(g["layers"], 3)
        self.assertEqual(g["time_s"], 14 * 60 + 7)                     # "; estimated printing time (normal mode) = 14m 7s"
        self.assertAlmostEqual(g["filament_g"], 1.83)                  # "; total filament used [g] = 1.83"
        self.assertAlmostEqual(g["max_z_mm"], 0.6)
        L = orca.parse_layers(FIX / "orca" / "generic_printer.gcode")
        self.assertEqual([l["z"] for l in L], [0.2, 0.4, 0.6])
        self.assertEqual({p["t"] for l in L for p in l["paths"]}, {"Outer wall", "Inner wall", "Sparse infill", "Support"})

    def test_gcode_bambu_printer(self):
        g = orca.parse_gcode_header(FIX / "orca" / "bambu_printer.gcode")
        self.assertEqual(g["layers"], 3)
        self.assertEqual(g["time_s"], 14 * 60 + 7)                     # "; model printing time: …; total estimated time: 14m 7s"
        self.assertAlmostEqual(g["filament_g"], 1.83)                  # "; filament used [g] = 1.83"
        L = orca.parse_layers(FIX / "orca" / "bambu_printer.gcode")
        self.assertEqual(len(L), 3)
        self.assertIn("Outer wall", {p["t"] for p in L[0]["paths"]})


class PrusaPresets(unittest.TestCase):
    def test_resolves_bundle_and_user_preset(self):
        r = prusa.resolve(prusa_cfg())
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual({k: v["name"] for k, v in r["presets"].items()},
                         {"machine": "Original Prusa MK4S 0.4 nozzle", "process": "0.20mm QUALITY @MK4S 0.4 (FORM test)",
                          "filament": "Prusament PLA"})
        self.assertEqual(r["envelope_mm"], [250.0, 214.0, 220.0])      # bed_shape 0x-4,250x-4,250x210,0x210
        self.assertEqual(r["nozzle_mm"], 0.4)
        self.assertEqual(r["summary"]["walls"], "3")                    # user preset
        self.assertEqual(r["summary"]["filament_type"], "PLA")          # *PLA* parent
        self.assertIn("compatible_printers_condition", r["unchecked"])

    def test_inherits_list_later_parent_wins(self):
        b = prusa.Bundle(FIX / "prusa" / "config")
        flat = b.flatten("PrusaSlicer", "print", "0.20mm QUALITY @MK4S 0.4")
        self.assertEqual(flat["layer_height"], "0.2")                   # *0.20mm* over its parent *common*
        self.assertEqual(flat["perimeters"], "2")                       # *MK4S* is listed last, so it wins over *0.20mm*
        self.assertIn("printer_model==\"MK4S\"", flat["compatible_printers_condition"])   # from *MK4S*
        self.assertNotIn("inherits", flat)
        with self.assertRaises(common.SlicerBlocked):
            b.flatten("PrusaSlicer", "print", "*missing*")

    def test_incompatible_filament_blocks(self):
        r = prusa.resolve(prusa_cfg(filament="Other Printer PLA"))
        self.assertFalse(r["available"])
        self.assertIn("not compatible", r["reason"])

    def test_merged_ini_is_text_gcode_and_drops_bookkeeping(self):
        r = prusa.resolve(prusa_cfg())
        ini = prusa._A.merged_ini(r)
        keys = dict(ln.split(" = ", 1) for ln in ini.splitlines() if " = " in ln and not ln.startswith("#"))
        self.assertEqual(keys["binary_gcode"], "0")
        self.assertEqual(keys["print_settings_id"], "0.20mm QUALITY @MK4S 0.4 (FORM test)")
        self.assertEqual(keys["printer_model"], "MK4S")
        for k in ("inherits", "compatible_printers", "compatible_printers_condition"):
            self.assertNotIn(k, keys)

    def test_split_list(self):
        self.assertEqual(prusa.split_list('*0.20mm*; *MK4S*'), ["*0.20mm*", "*MK4S*"])
        self.assertEqual(prusa.split_list('"Original Prusa MK4S 0.4 nozzle";"A \\"B\\""'),
                         ["Original Prusa MK4S 0.4 nozzle", 'A "B"'])
        self.assertEqual(prusa.split_list(""), [])

    def test_gcode(self):
        g = prusa.parse_gcode(FIX / "prusa" / "plate_1.gcode")
        self.assertEqual(g["time_s"], 12 * 60 + 31)                    # "; estimated printing time (normal mode) = 12m 31s"
        self.assertAlmostEqual(g["filament_g"], 1.56)                  # "; total filament used [g] = 1.56"
        self.assertAlmostEqual(g["filament_mm"], 523.41)
        self.assertEqual(g["layers"], 3)                               # counted ;LAYER_CHANGE markers
        self.assertAlmostEqual(g["max_z_mm"], 0.6)
        self.assertTrue(g["support_used"])
        L = prusa.parse_layers(FIX / "prusa" / "plate_1.gcode")
        self.assertEqual([l["z"] for l in L], [0.2, 0.4, 0.6])
        self.assertEqual({p["t"] for l in L for p in l["paths"]},     # PrusaSlicer role names, mapped for the viewer
                         {"Outer wall", "Inner wall", "Sparse infill", "Support"})

    def test_dur(self):
        self.assertEqual(common.dur("1d 2h 3m 4s"), 93784)
        self.assertEqual(common.dur("45s"), 45)


class Missing(unittest.TestCase):
    def test_missing_app_is_unavailable_with_reason_and_hint(self):
        cfg = base_cfg()
        for d in slicer.detect_all(cfg):
            self.assertFalse(d["installed"], d["kind"])
            self.assertFalse(d["available"], d["kind"])
            self.assertIn("not found", d["reason"], d["kind"])
            self.assertTrue(d["install"]["url"].startswith("https://"), d["kind"])
        r = orca.resolve(cfg)
        self.assertFalse(r["available"])
        self.assertIn("[slicer.orca].app", r["reason"])

    def test_auto_with_nothing_installed_names_every_slicer(self):
        r = slicer.resolve(base_cfg())
        self.assertEqual(r["kind"], "bambu")
        self.assertFalse(r["available"])
        for name in ("Bambu Studio", "OrcaSlicer", "PrusaSlicer"):
            self.assertIn(name, r["reason"])
        self.assertIn("not found", r["reason"])

    def test_unknown_kind(self):
        cfg = base_cfg()
        cfg["slicer"]["kind"] = "cura"
        r = slicer.resolve(cfg)
        self.assertFalse(r["available"])
        self.assertIn("Unknown slicer kind", r["reason"])


class Auto(unittest.TestCase):
    def test_order_keeps_bambu_first(self):
        self.assertEqual(AUTO_ORDER[:3], ["bambu", "orca", "prusa"])
        self.assertEqual(config.DEFAULTS["slicer"]["kind"], "auto")

    def test_picks_first_installed(self):
        cfg = orca_cfg()
        cfg["slicer"]["prusa"] = {"app": sys.executable, "config_dir": str(FIX / "prusa" / "config")}
        self.assertEqual(slicer.resolve(cfg)["kind"], "orca")
        cfg["slicer"]["app"] = sys.executable                         # "Bambu Studio" present: it wins
        self.assertEqual(slicer.auto_kind(cfg), "bambu")
        cfg["slicer"]["orca"]["app"] = NOWHERE
        cfg["slicer"]["app"] = NOWHERE
        self.assertEqual(slicer.resolve(cfg)["kind"], "prusa")

    def test_explicit_kind_is_respected(self):
        cfg = orca_cfg()
        cfg["slicer"]["app"] = sys.executable
        cfg["slicer"]["kind"] = "orca"
        r = slicer.resolve(cfg)
        self.assertEqual((r["kind"], r["chosen"]), ("orca", "orca"))

    def test_detect_all_reports_presets(self):
        cfg = orca_cfg()
        by = {d["kind"]: d for d in slicer.detect_all(cfg)}
        self.assertTrue(by["orca"]["installed"] and by["orca"]["available"] and by["orca"]["active"])
        self.assertEqual(by["orca"]["presets"]["machine"], "Voron 2.4 350 0.4 nozzle")
        self.assertIsNone(by["orca"]["install"])
        self.assertFalse(by["prusa"]["installed"])

    def test_slice_key_names_the_slicer_except_bambu(self):
        self.assertEqual(studio._slicer_tag({"kind": "bambu"}), [])
        self.assertEqual(studio._slicer_tag({}), [])
        self.assertEqual(studio._slicer_tag({"kind": "orca"}), ["orca"])
        self.assertNotEqual(studio.H("slice", "e", {"a": 1}, "2.3", *studio._slicer_tag({"kind": "orca"})),
                            studio.H("slice", "e", {"a": 1}, "2.3", *studio._slicer_tag({"kind": "prusa"})))


class KindInToml(unittest.TestCase):
    def test_text_edit_changes_only_kind(self):
        src = textwrap.dedent("""\
            # mine
            [printer]
            name = "X"   # keep

            [slicer]
            kind = "bambu"           # adapter
            machine = "auto"

            [apps]
            kind = "not this one"
            """)
        out = slicer.set_kind_text(src, "orca")
        self.assertEqual(out, src.replace('kind = "bambu"           # adapter', 'kind = "orca"           # adapter'))
        self.assertEqual(tomllib.loads(out)["apps"]["kind"], "not this one")

    def test_text_edit_inserts_and_appends(self):
        out = slicer.set_kind_text('[slicer]\nmachine = "auto"\n', "prusa")
        self.assertEqual(tomllib.loads(out)["slicer"], {"kind": "prusa", "machine": "auto"})
        out = slicer.set_kind_text('[printer]\nname = "X"\n', "auto")
        self.assertEqual(tomllib.loads(out), {"printer": {"name": "X"}, "slicer": {"kind": "auto"}})

    def test_set_kind_backs_up_and_keeps_everything_else(self):
        d = Path(tempfile.mkdtemp(prefix="form-slicer-"))
        try:
            p = d / "studio.toml"
            p.write_text((config.ROOT / "studio.toml").read_text(encoding="utf-8"), encoding="utf-8")
            old = os.environ.get("FORM_CONFIG")
            os.environ["FORM_CONFIG"] = str(p)
            try:
                cfg = config.load()
                before = tomllib.loads(p.read_text(encoding="utf-8"))
                done = slicer.set_kind(cfg, "prusa")
                with self.assertRaises(common.SlicerBlocked):
                    slicer.set_kind(cfg, "cura")
                self.assertEqual(config.load()["slicer"]["kind"], "prusa")
            finally:
                if old is None:
                    os.environ.pop("FORM_CONFIG", None)
                else:
                    os.environ["FORM_CONFIG"] = old
            after = tomllib.loads(p.read_text(encoding="utf-8"))
            before["slicer"]["kind"] = "prusa"
            self.assertEqual(after, before)
            self.assertTrue(Path(done["backup"]).exists())
            self.assertEqual(cfg["slicer"]["kind"], "prusa")
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipIf(sys.platform.startswith("win"), "stand-in programs are POSIX scripts")
class StandInSlices(unittest.TestCase):
    """Run slice_stl against tiny scripts that copy a fixture, to check FORM's side of the CLI contract."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="form-standin-"))
        self.stl = self.d / "part.stl"
        self.stl.write_text("solid x\nendsolid x\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def script(self, body):
        py = self.d / f"stand_in_{len(list(self.d.glob('stand_in_*')))}.py"
        py.write_text("import sys, shutil, json, os\nargs = sys.argv[1:]\n" + body, encoding="utf-8")
        p = self.d / f"slicer{py.stem[-2:]}"
        p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")   # paths may contain spaces
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return str(p)

    def test_orca_command_line(self):
        app = self.script(textwrap.dedent(f"""\
            if args == ["--help"]:
                print("OrcaSlicer-2.3.1:"); sys.exit(0)
            json.dump(args, open("args.json", "w"))
            out = args[args.index("--outputdir") + 1]
            shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
            """))
        cfg = orca_cfg(app)
        cfg["slicer"]["kind"] = "orca"
        r = slicer.resolve(cfg)
        info = slicer.slice_stl(r, self.stl, self.d / "out", timeout=60)
        self.assertEqual((info["time_s"], info["filament_g"], info["layers"]), (847, 1.83, 3))
        self.assertEqual((info["slicer_kind"], info["slicer_name"], info["slicer_version"]), ("orca", "OrcaSlicer", "2.3.1"))
        import json
        args = json.loads((self.d / "out" / "args.json").read_text(encoding="utf-8"))
        for flag in ("--load-settings", "--load-filaments", "--slice", "--export-3mf", "--outputdir", "--arrange"):
            self.assertIn(flag, args)
        self.assertEqual(len(slicer.parse_layers(self.d / "out" / "plate_1.gcode", "orca")), 3)

    def test_prusa_command_line_and_refusal(self):
        app = self.script(textwrap.dedent(f"""\
            if args == ["--help"]:
                print("PrusaSlicer-2.9.7+arm64 based on Slic3r"); sys.exit(0)
            out = args[args.index("--output") + 1]
            ini = open(args[args.index("--load") + 1], encoding="utf-8").read()
            if "binary_gcode = 0" not in ini:
                print("error: binary G-code requested", file=sys.stderr); sys.exit(1)
            if "--export-gcode" in args:
                shutil.copyfile({str(FIX / "prusa" / "plate_1.gcode")!r}, out)
            elif "--export-3mf" in args:
                open(out, "wb").write(b"PK")
            """))
        cfg = prusa_cfg(app)
        cfg["slicer"]["kind"] = "prusa"
        r = slicer.resolve(cfg)
        self.assertTrue(r["available"], r["reason"])
        info = slicer.slice_stl(r, self.stl, self.d / "out", timeout=60)
        self.assertEqual((info["time_s"], info["filament_g"], info["layers"]), (751, 1.56, 3))
        self.assertEqual(info["slicer_version"], "2.9.7")
        self.assertIsNone(info["threemf"])                            # the project 3MF is not sliced data
        self.assertEqual(info["project_3mf"], "project.3mf")
        bad = self.script('print("Error: Objects could not fit on the bed", file=sys.stderr); sys.exit(1)\n')
        r["app"] = bad
        with self.assertRaises(common.SlicerFailed) as cm:
            slicer.slice_stl(r, self.stl, self.d / "out2", timeout=60)
        self.assertIn("could not fit", str(cm.exception))



class ShippedBundles(unittest.TestCase):
    """Found with a real PrusaSlicer 2.9.7 that had never been opened: no vendor folder yet, so no preset resolved."""

    def test_presets_resolve_from_the_bundles_inside_the_program(self):
        import tempfile
        from pathlib import Path
        from form.adapters.prusa import Bundle, shipped_profiles
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            exe = root / "PrusaSlicer.app" / "Contents" / "MacOS" / "PrusaSlicer"
            exe.parent.mkdir(parents=True); exe.write_text("", encoding="utf-8")
            prof = root / "PrusaSlicer.app" / "Contents" / "Resources" / "profiles"
            prof.mkdir(parents=True)
            (prof / "Acme.ini").write_text("[printer:Acme One]\nnozzle_diameter = 0.4\n", encoding="utf-8")
            self.assertEqual(shipped_profiles(str(exe)), prof)
            cfg = root / "config"                      # never opened: no vendor folder
            cfg.mkdir()
            self.assertIn("Acme One", Bundle(cfg, shipped_profiles(str(exe))).system["printer"])
            self.assertNotIn("Acme One", Bundle(cfg).system["printer"])
            (cfg / "vendor").mkdir()                   # an installed bundle of the same name wins
            (cfg / "vendor" / "Acme.ini").write_text("[printer:Acme One]\nnozzle_diameter = 0.6\n", encoding="utf-8")
            got = Bundle(cfg, prof).system["printer"]["Acme One"]
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0][1]["nozzle_diameter"], "0.6")

if __name__ == "__main__":
    unittest.main()
