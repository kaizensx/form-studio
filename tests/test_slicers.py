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
from form.adapters import AUTO_ORDER, SLICERS, common, orca, prusa

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
    cfg["general"]["capabilities"] = ["core", "parts", "mesh", "print"]   # these tests slice: printing is opt-in
    cfg["slicer"]["app"] = NOWHERE
    for kind in SLICERS:
        if kind != "bambu":
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

    def orca_run(self, body):
        app = self.script('if args == ["--help"]:\n    print("OrcaSlicer-2.5.1:"); sys.exit(0)\n' + textwrap.dedent(body))
        cfg = orca_cfg(app)
        cfg["slicer"]["kind"] = "orca"
        return slicer.slice_stl(slicer.resolve(cfg), self.stl, self.d / "out", timeout=60)

    def test_orca_refusal_is_explained_from_its_exit_code_and_its_own_log_file(self):
        # OrcaSlicer 2.5 logs to 00000.log in the working folder, and says why only through the exit code
        # (result.json is written on Linux alone). 154 is -102 wrapped.
        home = str(Path.home())
        with self.assertRaises(common.SlicerFailed) as cm:
            self.orca_run(f"""\
                open("00000.log", "w").write("load {home}/x.json\\nplate 1: found gcode in unprintable area\\n")
                print("run found error, exit"); sys.exit(154)
                """)
        self.assertEqual(str(cm.exception), "OrcaSlicer refused to slice: Found G-code in unprintable area after slicing. (exit code -102)")
        self.assertIn("found gcode in unprintable area", cm.exception.log)
        out = self.d / "out"
        self.assertEqual([p.name for p in out.glob("*.log")], ["slicer.log"])       # its own file is folded in and gone
        log = (out / "slicer.log").read_text(encoding="utf-8")
        self.assertIn("load ~/x.json", log)
        self.assertNotIn(home, log)

    def test_orca_refusal_carries_what_it_printed(self):
        with self.assertRaises(common.SlicerFailed) as cm:
            self.orca_run("""\
                print("run found error, exit")
                print("Param values in 3mf/config error: ")
                print("during_print_exhaust_fan_speed: 255 not in range [0, 100]"); sys.exit(238)
                """)
        self.assertIn("Invalid parameter value(s) in the presets. Param values in 3mf/config error: "
                      "during_print_exhaust_fan_speed: 255 not in range [0, 100] (exit code -18)", str(cm.exception))
        with self.assertRaises(common.SlicerFailed) as cm:
            self.orca_run("sys.exit(77)\n")
        self.assertEqual(str(cm.exception), "OrcaSlicer refused to slice: (exit code 77)")

    def test_orca_crash_is_called_a_crash(self):
        with self.assertRaises(common.SlicerFailed) as cm:
            self.orca_run("""\
                import signal
                print("libc++abi: terminating due to uncaught exception", file=sys.stderr); sys.stderr.flush()
                os.kill(os.getpid(), signal.SIGKILL)
                """)
        self.assertIn("it crashed (signal 9): libc++abi: terminating", str(cm.exception))

    def test_orca_timeout_keeps_its_log_without_the_home_path(self):
        app = self.script('if args == ["--help"]:\n    print("OrcaSlicer-2.5.1:"); sys.exit(0)\n'
                          f'import time\nopen("00000.log", "w").write("read {Path.home()}/m.stl\\n")\ntime.sleep(30)\n')
        cfg = orca_cfg(app)
        cfg["slicer"]["kind"] = "orca"
        with self.assertRaises(common.SlicerFailed) as cm:
            slicer.slice_stl(slicer.resolve(cfg), self.stl, self.d / "out", timeout=3)
        self.assertIn("did not finish within 3 s", str(cm.exception))
        self.assertEqual([p.name for p in (self.d / "out").glob("*.log")], ["slicer.log"])
        self.assertEqual((self.d / "out" / "slicer.log").read_text(encoding="utf-8"), "read ~/m.stl\n")

    def test_exit_codes_unwrap(self):
        from form.adapters import _bbl
        self.assertEqual([_bbl.exit_code(c) for c in (0, 1, 154, 238, 205, 0xFFFFFF9A, -11)], [0, 1, -102, -18, -51, -102, -11])

    def test_a_crash_after_the_gcode_is_written_keeps_the_gcode(self):
        # Snapmaker Orca on Windows (software OpenGL) writes the whole G-code, says so, then crashes drawing the thumbnail
        info = self.orca_run(f"""\
            out = args[args.index("--outputdir") + 1]
            shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
            open(os.path.join(out, "plate.3mf"), "wb").write(b"half")
            print("Slicing result exported to " + out + "/plate_1.gcode")
            print("[error] Slic3r::GUI::PartPlate::calc_exclude_triangles:Unable to create exclude triangles")
            sys.exit(3221225477)
            """)
        self.assertEqual((info["time_s"], info["filament_g"], info["layers"]), (847, 1.83, 3))
        self.assertIsNone(info["threemf"])                                        # nothing kept from a crashed 3MF write
        self.assertIn("after writing the G-code", info["warnings"][0])
        # without the slicer saying the G-code was exported, a non-zero exit is still a failed slice
        with self.assertRaises(common.SlicerFailed):
            self.orca_run(f"""\
                out = args[args.index("--outputdir") + 1]
                shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
                sys.exit(1)
                """)

    def test_orca_warnings_come_from_its_log_file(self):
        info = self.orca_run(f"""\
            out = args[args.index("--outputdir") + 1]
            open("00000.log", "w").write("got warnings: The precise wall option will be ignored.\\n")
            shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
            """)
        self.assertEqual(info["warnings"], ["The precise wall option will be ignored."])

    def test_the_cli_runs_in_a_throwaway_home_on_macos(self):
        # After any crash of the program, macOS asks "reopen windows?" in a modal window when the CLI starts
        # AppKit for the thumbnail, and the slice hangs behind it. The question is per home folder.
        self.orca_run(f"""\
            out = args[args.index("--outputdir") + 1]
            home = os.environ.get("CFFIXED_USER_HOME", "")
            json.dump([home, os.path.isdir(home)], open(os.path.join(out, "home.json"), "w"))
            shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
            """)
        import json
        home, existed = json.loads((self.d / "out" / "home.json").read_text(encoding="utf-8"))
        if sys.platform == "darwin":
            self.assertTrue(existed)
            self.assertNotEqual(Path(home), Path.home())
            self.assertFalse(Path(home).exists())                       # removed after the run
        else:
            self.assertEqual(home, os.environ.get("CFFIXED_USER_HOME", ""))

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

    # On Windows orca-slicer.exe, bambu-studio.exe and QIDISlicer.exe are window programs: run from FORM they print
    # nothing, not even for --help. The slice still names the version, read from the G-code it wrote.

    def test_orca_version_comes_from_its_gcode_when_help_is_silent(self):
        orca.FAMILY.version_cache.clear()
        app = self.script(textwrap.dedent(f"""\
            if args == ["--help"]:
                sys.exit(0)
            out = args[args.index("--outputdir") + 1]
            shutil.copyfile({str(FIX / "orca" / "generic_printer.gcode")!r}, os.path.join(out, "plate_1.gcode"))
            """))
        cfg = orca_cfg(app)
        cfg["slicer"]["kind"] = "orca"
        r = slicer.resolve(cfg)
        self.assertEqual(slicer.public(r)["version"], "unknown")        # before any slice there is nothing to read
        info = slicer.slice_stl(r, self.stl, self.d / "out", timeout=60)
        want = common.gcode_version(FIX / "orca" / "generic_printer.gcode", "OrcaSlicer")
        self.assertTrue(want)
        self.assertEqual(info["slicer_version"], want)
        self.assertEqual(slicer.public(r)["version"], want)             # and it is remembered for this program

    def test_prusa_family_version_comes_from_its_gcode_when_help_is_silent(self):
        g = self.d / "qidi.gcode"
        g.write_text("; generated by QIDISlicer 1.2.5 on 2026-11-17 at 12:36:36 UTC\n"
                     + (FIX / "prusa" / "plate_1.gcode").read_text(encoding="utf-8"), encoding="utf-8")
        app = self.script(textwrap.dedent(f"""\
            if args == ["--help"]:
                sys.exit(0)
            if "--export-gcode" in args:
                shutil.copyfile({str(g)!r}, args[args.index("--output") + 1])
            """))
        cfg = base_cfg(qidi={"app": app, "config_dir": str(FIX / "prusa" / "config"), "machine": "Original Prusa MK4S 0.4 nozzle",
                             "process": "0.20mm QUALITY @MK4S 0.4", "filament": "Prusament PLA"})
        cfg["slicer"]["kind"] = "qidi"
        r = slicer.resolve(cfg)
        self.assertTrue(r["available"], r["reason"])
        info = slicer.slice_stl(r, self.stl, self.d / "out", timeout=60)
        self.assertEqual(info["slicer_version"], "1.2.5")


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


class RealInstalls(unittest.TestCase):
    """Found by running the official builds on Windows and Linux runners (.github/workflows/slicers.yml):
    OrcaSlicer 2.5.1, Bambu Studio 02.09.01.70, SuperSlicer 2.5.59.13 and QIDISlicer 1.2.5, none ever opened.
    The folder layouts below are the ones those releases unpack to."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="form-installs-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def same(self, got, want):
        self.assertTrue(got and os.path.samefile(got, want), f"{got} is not {want}")

    def tree(self, *files):
        for f in files:
            (self.d / f).parent.mkdir(parents=True, exist_ok=True)
            (self.d / f).write_text("", encoding="utf-8")

    def test_profiles_of_an_unpacked_appimage(self):
        # OrcaSlicer, Bambu Studio, SuperSlicer: AppRun, bin/<program>, resources/profiles
        self.tree("Orca/AppRun", "Orca/bin/orca-slicer", "Orca/resources/profiles/BBL.opc")
        for app in ("AppRun", "bin/orca-slicer"):
            got = common.shipped_dirs(self.d / "Orca" / app, "OrcaSlicer")
            self.assertEqual(len(got), 1)                               # one folder, however many spellings reach it
            self.same(got[0], self.d / "Orca" / "resources" / "profiles")
        # QIDISlicer (and PrusaSlicer's AppImage): AppRun, usr/bin/qidi-slicer, usr/bin/resources/profiles
        self.tree("Qidi/AppRun", "Qidi/usr/bin/qidi-slicer", "Qidi/usr/bin/bin/qidi-slicer",
                  "Qidi/usr/bin/resources/profiles/QIDITechnology.ini")
        want = self.d / "Qidi" / "usr" / "bin" / "resources" / "profiles"
        self.same(prusa.shipped_profiles(str(self.d / "Qidi" / "AppRun"), "QIDISlicer"), want)
        self.same(prusa.shipped_profiles(str(self.d / "Qidi" / "usr" / "bin" / "qidi-slicer"), "QIDISlicer"), want)
        self.same(prusa.shipped_profiles(str(self.d / "Qidi" / "usr" / "bin" / "bin" / "qidi-slicer"), "QIDISlicer"), want)

    def test_profiles_of_windows_and_package_layouts(self):
        self.tree("Win/QIDISlicer.exe", "Win/resources/profiles/QIDITechnology.ini")
        self.same(prusa.shipped_profiles(str(self.d / "Win" / "QIDISlicer.exe"), "QIDISlicer"), self.d / "Win" / "resources" / "profiles")
        # a package: /usr/bin/superslicer with /usr/share/SuperSlicer/profiles, not PrusaSlicer's folder
        self.tree("usr/bin/superslicer", "usr/share/SuperSlicer/profiles/Prusa.ini", "usr/share/PrusaSlicer/profiles/Prusa.ini")
        self.same(prusa.shipped_profiles(str(self.d / "usr" / "bin" / "superslicer"), "SuperSlicer"), self.d / "usr" / "share" / "SuperSlicer" / "profiles")
        self.same(prusa.shipped_profiles(str(self.d / "usr" / "bin" / "superslicer")), self.d / "usr" / "share" / "PrusaSlicer" / "profiles")
        self.assertIsNone(prusa.shipped_profiles(None))

    @unittest.skipIf(sys.platform.startswith("win"), "links need a privilege on Windows")
    def test_profiles_are_found_through_a_link_to_the_program(self):
        self.tree("opt/Super/bin/superslicer", "opt/Super/resources/profiles/Prusa.ini")
        (self.d / "bin").mkdir()
        os.symlink(self.d / "opt" / "Super" / "bin" / "superslicer", self.d / "bin" / "superslicer")
        self.same(prusa.shipped_profiles(str(self.d / "bin" / "superslicer"), "SuperSlicer"), self.d / "opt" / "Super" / "resources" / "profiles")

    def bambu_install(self):
        """Bambu Studio as unpacked, with its JSON vendor presets, and a config folder that does not exist yet."""
        from form.adapters import bambu
        root = self.d / "Bambu Studio"
        shutil.copytree(FIX / "orca" / "config" / "system", root / "resources" / "profiles")
        app = root / "bambu-studio.exe"
        app.write_text("", encoding="utf-8")
        cfg = base_cfg(bambu={"app": str(app), "config_dir": str(self.d / "never-opened"), "kind": "bambu",
                              "machine": "Voron 2.4 350 0.4 nozzle", "process": "0.20mm Standard @Voron",
                              "filament": "Generic PLA @System"})
        return bambu, cfg

    def test_bambu_studio_never_opened_resolves_from_the_presets_inside_it(self):
        bambu, cfg = self.bambu_install()
        r = bambu.resolve(cfg)
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual(r["envelope_mm"], [350.0, 350.0, 340.0])       # through "inherits", inside the program
        self.assertEqual(r["summary"]["filament_type"], "PLA")          # parent in filament/base
        cfg["slicer"]["filament"] = "No Such PLA"
        self.assertIn("No Such PLA", bambu.resolve(cfg)["reason"])

    def test_bambu_studio_installed_presets_win_over_the_ones_inside_it(self):
        bambu, cfg = self.bambu_install()
        mine = self.d / "never-opened" / "system" / "Voron" / "process"
        mine.mkdir(parents=True)
        src = FIX / "orca" / "config" / "system" / "Voron" / "process" / "0.20mm Standard @Voron.json"
        import json
        d = json.loads(src.read_text(encoding="utf-8"))
        d["wall_loops"] = "7"
        (mine / src.name).write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual(bambu.resolve(cfg)["summary"]["walls"], "7")

    def test_bambu_studio_is_found_unpacked_when_the_default_place_is_empty(self):
        from unittest import mock
        from form.adapters import bambu
        self.tree("opt/BambuStudio/AppRun")
        found = str(self.d / "opt" / "BambuStudio" / "AppRun")
        cfg = base_cfg()
        cfg["slicer"]["app"] = config.DEFAULTS["slicer"]["app"]         # left at its default
        with mock.patch.object(shutil, "which", return_value=None), \
                mock.patch.dict(bambu.APPS, {common.platform(): [found]}):
            if not Path(cfg["slicer"]["app"]).exists():
                self.assertEqual(bambu.find_app(cfg), found)
            cfg["slicer"]["app"] = NOWHERE                              # a path the person set is never second-guessed
            self.assertIsNone(bambu.find_app(cfg))

    def test_program_names_the_official_builds_use(self):
        self.assertIn("/opt/BambuStudio/AppRun", __import__("form.adapters.bambu", fromlist=["APPS"]).APPS["linux"])
        self.assertIn("/opt/OrcaSlicer/AppRun", orca.APPS["linux"])
        self.assertIn("/opt/SuperSlicer/AppRun", prusa.SUPERSLICER.apps["linux"])
        self.assertIn("/opt/QIDISlicer/AppRun", prusa.QIDI.apps["linux"])
        # QIDISlicer 1.2.5 for Windows has QIDISlicer.exe and no qidi-slicer-console.exe
        self.assertIn(r"%ProgramFiles%\QIDISlicer\QIDISlicer.exe", prusa.QIDI.apps["win"])
        self.assertLess(prusa.QIDI.apps["win"].index(r"%ProgramFiles%\QIDISlicer\qidi-slicer-console.exe"),
                        prusa.QIDI.apps["win"].index(r"%ProgramFiles%\QIDISlicer\QIDISlicer.exe"))

    def test_help_text_of_each_program(self):
        # first lines of `--help` as the real programs printed them
        said = {orca.FAMILY.version_re: ("OrcaSlicer-2.5.1:\nUsage: orca-slicer [ OPTIONS ]", "2.5.1"),
                __import__("form.adapters.bambu", fromlist=["FAMILY"]).FAMILY.version_re:
                    ("BambuStudio-02.09.01.70:\nUsage: bambu-studio [ OPTIONS ]", "02.09.01.70"),
                prusa.QIDI.version_re: ("QIDISlicer-1.2.5+Win64 based on Slic3r (with GUI support)", "1.2.5"),
                prusa.PRUSA.version_re: ("PrusaSlicer-2.9.7+arm64 based on Slic3r", "2.9.7")}
        for pattern, (text, want) in said.items():
            self.assertEqual(common.version_in(text, pattern), want)
        # SuperSlicer joins name and version with "_", and the Linux build adds its date
        for text in ("[2026-11-17 12:42:56.910465] [0x00007fd66d0e2900] [trace]   Initializing StaticPrintConfigs\n"
                     "SuperSlicer_2.5.59.13_2024-07-01 based on Slic3r (with GUI support)",
                     "SuperSlicer_2.5.59.13 based on Slic3r (with GUI support)"):
            self.assertEqual(common.version_in(text, prusa.SUPERSLICER.version_re), "2.5.59.13")
        self.assertEqual(common.version_in("MESA OpenGL library was not loaded", orca.FAMILY.version_re), "")

    def test_only_flatpaks_that_exist_on_flathub_are_offered(self):
        # Checked against https://flathub.org/api/v2/appstream/<id> on 2026-11-17. SuperSlicer and QIDISlicer are
        # not on Flathub; FORM offered "com.superslicer.SuperSlicer", which does not exist.
        on_flathub = {"com.prusa3d.PrusaSlicer", "com.orcaslicer.OrcaSlicer", "com.bambulab.BambuStudio"}
        from unittest import mock
        import re
        offered = set()
        for kind in AUTO_ORDER:
            a = slicer.adapter(kind)
            with mock.patch.object(sys, "platform", "linux"), \
                    mock.patch.object(shutil, "which", side_effect=lambda c, *x, **k: "/usr/bin/flatpak" if c == "flatpak" else None):
                for cmd in a.install_hint()["cmds"]:
                    offered |= set(re.findall(r"flathub (\S+)", cmd))
        self.assertEqual(offered - on_flathub, set())
        self.assertIn("com.orcaslicer.OrcaSlicer", offered)                 # the test did reach the Linux branch
        self.assertEqual(prusa.SUPERSLICER.flatpak, "")
        self.assertEqual(prusa.QIDI.flatpak, "")
        self.assertFalse([c for c in prusa.SUPERSLICER.apps["linux"] if "flatpak" in c])

    def test_version_from_the_gcode_itself(self):
        heads = {"OrcaSlicer": ("; HEADER_BLOCK_START\n; generated by OrcaSlicer 2.5.1 on 2026-11-17 at 12:36:23\n", "2.5.1"),
                 "BambuStudio": ("; HEADER_BLOCK_START\n; BambuStudio 02.09.01.70\n; model printing time: 1h 17m 14s\n", "02.09.01.70"),
                 "SuperSlicer": ("; generated by SuperSlicer 2.5.59.13 on 2026-11-17 at 12:36:25 UTC\n", "2.5.59.13"),
                 "QIDISlicer": ("; generated by QIDISlicer 1.2.5 on 2026-11-17 at 12:36:36 UTC\n", "1.2.5"),
                 "PrusaSlicer": ("; generated by PrusaSlicer 2.9.7+arm64 on 2026-11-17 at 10:00:00 UTC\n", "2.9.7")}
        for program, (head, want) in heads.items():
            g = self.d / f"{program}.gcode"
            g.write_text(head + "G1 X1 Y1\n", encoding="utf-8")
            self.assertEqual(common.gcode_version(g, program), want)
            self.assertEqual(common.gcode_version(g, "Cura"), "")
        self.assertEqual(common.gcode_version(self.d / "missing.gcode", "OrcaSlicer"), "")
        self.assertEqual(common.windows_file_version(self.d / "missing.exe"), "")


if __name__ == "__main__":
    unittest.main()


class OrcaForks(unittest.TestCase):
    """ElegooSlicer and Snapmaker Orca: OrcaSlicer's CLI, presets and 3MF under their own names (orca_forks.py)."""

    def test_registered_with_their_own_names_and_folders(self):
        from form.adapters import elegoo, snapmaker
        self.assertEqual((elegoo.LABEL, snapmaker.LABEL), ("ElegooSlicer", "Snapmaker Orca"))
        self.assertEqual((elegoo.FAMILY.conf_name, snapmaker.FAMILY.conf_name), ("ElegooSlicer.conf", "Snapmaker_Orca.conf"))
        self.assertIn("elegoo", AUTO_ORDER)
        self.assertIn("snapmaker", AUTO_ORDER)
        self.assertTrue(snapmaker.APPS["darwin"][0].endswith("Snapmaker Orca.app/Contents/MacOS/Snapmaker_Orca"))
        self.assertTrue(elegoo.APPS["win"][0].endswith("elegoo-slicer.exe"))

    def test_resolve_reads_orca_layout_from_its_table(self):
        from form.adapters import elegoo
        cfg = base_cfg(elegoo={"app": sys.executable, "config_dir": str(FIX / "orca" / "config")})
        r = elegoo.resolve(cfg)                                   # the fixture's selection file is named for OrcaSlicer
        self.assertFalse(r["available"])
        self.assertIn("ElegooSlicer.conf", r["reason"])
        cfg["slicer"]["elegoo"].update(machine="Voron 2.4 350 0.4 nozzle", process="0.20mm Standard @Voron",
                                       filament="Generic PLA @System")
        r = elegoo.resolve(cfg)
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual(r["source"]["machine"], "studio.toml")
        self.assertEqual(r["envelope_mm"][0], 350.0)

    def test_version_from_the_app_bundle(self):
        from form.adapters import orca_forks
        d = Path(tempfile.mkdtemp(prefix="form-plist-"))
        exe = d / "ElegooSlicer.app" / "Contents" / "MacOS" / "ElegooSlicer"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        import plistlib
        with open(d / "ElegooSlicer.app" / "Contents" / "Info.plist", "wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "1.5.3.5"}, f)
        self.assertEqual(orca_forks._plist_version(str(exe)), "1.5.3.5")
        self.assertEqual(orca_forks._plist_version(sys.executable if ".app/" not in sys.executable else "/nonexistent"), "")
        shutil.rmtree(d, ignore_errors=True)


@unittest.skipIf(sys.platform.startswith("win"), "stand-in programs are POSIX scripts")
class OrcaForkStandIn(unittest.TestCase):
    setUp, tearDown, script = StandInSlices.setUp, StandInSlices.tearDown, StandInSlices.script

    def test_elegoo_command_line_and_version_from_gcode(self):
        gcode = self.d / "elegoo.gcode"
        gcode.write_text("; generated by ElegooSlicer 1.5.3.5 on 2026-11-17 at 10:00:00 UTC\n"
                         + (FIX / "orca" / "generic_printer.gcode").read_text(encoding="utf-8"), encoding="utf-8")
        app = self.script(textwrap.dedent(f"""\
            if args == ["--help"]:
                print("ElegooSlicer-2.4.2:"); sys.exit(0)
            json.dump(args, open("args.json", "w"))
            out = args[args.index("--outputdir") + 1]
            shutil.copyfile({str(gcode)!r}, os.path.join(out, "plate_1.gcode"))
            """))
        cfg = base_cfg(elegoo={"app": app, "config_dir": str(FIX / "orca" / "config"), "machine": "Voron 2.4 350 0.4 nozzle",
                               "process": "0.20mm Standard @Voron", "filament": "Generic PLA @System"})
        cfg["slicer"]["kind"] = "elegoo"
        r = slicer.resolve(cfg)
        self.assertTrue(r["available"], r["reason"])
        info = slicer.slice_stl(r, self.stl, self.d / "out", timeout=60)
        # --help names the OrcaSlicer version it is based on (2.4.2); the program's own version is in its G-code
        self.assertEqual((info["slicer_kind"], info["slicer_name"], info["slicer_version"]), ("elegoo", "ElegooSlicer", "1.5.3.5"))
        import json
        args = json.loads((self.d / "out" / "args.json").read_text(encoding="utf-8"))
        for flag in ("--load-settings", "--load-filaments", "--slice", "--export-3mf", "--outputdir", "--arrange"):
            self.assertIn(flag, args)
