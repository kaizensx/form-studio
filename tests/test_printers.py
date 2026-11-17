"""Every printer in every installed slicer (form/printers.py), the per-design and default choice, and the conditions
presets use (form/adapters/condition.py).

The slicer folders are fixtures written here or in tests/fixtures/slicers (layouts from the programs' source, see
SOURCES.txt there). "Installed" means the adapter is pointed at this Python, which exists; nothing is sliced.
"""
import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from form import printers, slicer
from form.adapters import condition
from test_slicers import FIX, NOWHERE, base_cfg


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def bambu_dir(root: Path) -> Path:
    """A Bambu Studio config folder: two models enabled (A1 mini with 0.4 and 0.6, X1C with 0.4), a user copy."""
    d = root / "BambuStudio"
    conf = {"presets": {"machine": "Bambu Lab A1 mini 0.4 nozzle", "process": "0.20mm Standard @BBL A1M",
                        "filaments": ["Bambu PLA Basic @BBL A1M"]},
            "models": [{"model": "Bambu Lab A1 mini", "nozzle_diameter": "0.4;0.6", "vendor": "BBL"},
                       {"model": "Bambu Lab X1 Carbon", "nozzle_diameter": "0.4", "vendor": "BBL"}],
            "filaments": ["Bambu PLA Basic @BBL A1M", "Bambu PLA Basic @BBL X1C", "Generic PETG @BBL A1M"]}
    write(d / "BambuStudio.conf", json.dumps(conf, indent=1) + "\n# MD5 checksum 0\n")
    m = d / "system" / "BBL" / "machine"
    write(m / "fdm_bbl_common.json", {"name": "fdm_bbl_common", "instantiation": "false", "printable_height": "250"})
    for name, model, nz, area, h in (("Bambu Lab A1 mini 0.4 nozzle", "Bambu Lab A1 mini", "0.4", 180, "180"),
                                     ("Bambu Lab A1 mini 0.6 nozzle", "Bambu Lab A1 mini", "0.6", 180, "180"),
                                     ("Bambu Lab A1 mini 0.8 nozzle", "Bambu Lab A1 mini", "0.8", 180, "180"),
                                     ("Bambu Lab X1 Carbon 0.4 nozzle", "Bambu Lab X1 Carbon", "0.4", 256, "250"),
                                     ("Bambu Lab P1S 0.4 nozzle", "Bambu Lab P1S", "0.4", 256, "250")):
        write(m / f"{name}.json", {"name": name, "inherits": "fdm_bbl_common", "instantiation": "true",
                                   "printer_model": model, "printer_variant": nz, "nozzle_diameter": [nz],
                                   "printable_area": ["0x0", f"{area}x0", f"{area}x{area}", f"0x{area}"], "printable_height": h,
                                   "default_print_profile": "0.20mm Standard @BBL " + ("A1M" if "mini" in name else "X1C"),
                                   "default_filament_profile": ["Bambu PLA Basic @BBL " + ("A1M" if "mini" in name else "X1C")]})
    p = d / "system" / "BBL" / "process"
    write(p / "fdm_process_common.json", {"name": "fdm_process_common", "instantiation": "false", "layer_height": "0.2"})
    write(p / "0.20mm Standard @BBL A1M.json", {"name": "0.20mm Standard @BBL A1M", "inherits": "fdm_process_common",
                                                "compatible_printers": ["Bambu Lab A1 mini 0.4 nozzle", "Bambu Lab A1 mini 0.6 nozzle"]})
    write(p / "0.20mm Standard @BBL X1C.json", {"name": "0.20mm Standard @BBL X1C", "inherits": "fdm_process_common",
                                                "compatible_printers": ["Bambu Lab X1 Carbon 0.4 nozzle"]})
    f = d / "system" / "BBL" / "filament"
    write(f / "fdm_filament_pla.json", {"name": "fdm_filament_pla", "instantiation": "false", "filament_type": ["PLA"]})
    for name, compat in (("Bambu PLA Basic @BBL A1M", ["Bambu Lab A1 mini 0.4 nozzle", "Bambu Lab A1 mini 0.6 nozzle"]),
                         ("Bambu PLA Basic @BBL X1C", ["Bambu Lab X1 Carbon 0.4 nozzle"]),
                         ("Generic PETG @BBL A1M", ["Bambu Lab A1 mini 0.4 nozzle"]),
                         ("Hidden PLA @BBL A1M", ["Bambu Lab A1 mini 0.4 nozzle"])):     # not enabled in the conf
        write(f / f"{name}.json", {"name": name, "inherits": "fdm_filament_pla", "instantiation": "true",
                                   "compatible_printers": compat})
    u = d / "user" / "123"
    write(u / "machine" / "My mini.json", {"name": "My mini", "inherits": "Bambu Lab A1 mini 0.4 nozzle", "from": "User"})
    write(u / "process" / "Strong.json", {"name": "Strong", "inherits": "0.20mm Standard @BBL A1M", "from": "User", "wall_loops": "4"})
    write(u / "filament" / "My PLA.json", {"name": "My PLA", "inherits": "Bambu PLA Basic @BBL A1M", "from": "User"})
    return d


class Conditions(unittest.TestCase):
    cfg = {"printer_notes": r"Keep.\nPRINTER_VENDOR_PRUSA3D\nPRINTER_MODEL_MK4S", "printer_model": "MK4S",
           "nozzle_diameter": "0.4,0.4", "printer_technology": "FFF", "is_cool": "1"}

    def test_the_forms_presets_use(self):
        ok = condition.evaluate
        self.assertTrue(ok('printer_notes=~/.*PRINTER_VENDOR_PRUSA3D.*/ and printer_model=="MK4S" and nozzle_diameter[0]==0.4', self.cfg))
        self.assertFalse(ok("nozzle_diameter[0]!=0.4", self.cfg))
        self.assertTrue(ok('! (printer_model=="MINI") and (nozzle_diameter[1]>=0.4 or false)', self.cfg))
        self.assertTrue(ok("printer_notes!~/.*PRINTER_VENDOR_QIDI.*/", self.cfg))
        self.assertTrue(ok("not (printer_model==\"XL\")", self.cfg))
        self.assertTrue(ok("", self.cfg))
        self.assertTrue(ok("nozzle_diameter[0]==0.4", {"nozzle_diameter": ["0.4"]}))       # JSON vectors (OrcaSlicer)

    def test_what_it_cannot_tell_is_unknown_not_a_guess(self):
        for bad in ("unknown_option==1", "printer_model==", "nozzle_diameter[3]==0.4", "printer_model=~\"x\"", "a ? b : c"):
            with self.assertRaises(condition.Unknown, msg=bad):
                condition.evaluate(bad, self.cfg)


class Inventory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-printers-"))
        printers.clear_cache()

    def cfg(self, **tables):
        return base_cfg(**tables)

    def test_bambu_user_and_enabled_system_printers(self):
        d = bambu_dir(self.tmp)
        cfg = self.cfg(bambu={"app": sys.executable, "config_dir": str(d)})
        s = printers.slicer_printers(cfg, "bambu")
        names = [p["name"] for p in s["printers"]]
        self.assertEqual(sorted(names), ["Bambu Lab A1 mini 0.4 nozzle", "Bambu Lab A1 mini 0.6 nozzle",
                                         "Bambu Lab X1 Carbon 0.4 nozzle", "My mini"])     # 0.8 and P1S are not enabled
        by = {p["name"]: p for p in s["printers"]}
        self.assertEqual(by["My mini"]["source"], "user")
        self.assertEqual(by["My mini"]["envelope_mm"], [180.0, 180.0, 180.0])            # inherited from the system printer
        self.assertEqual(by["Bambu Lab X1 Carbon 0.4 nozzle"]["envelope_mm"], [256.0, 256.0, 250.0])
        self.assertTrue(by["Bambu Lab A1 mini 0.4 nozzle"]["selected"])
        self.assertEqual(by["Bambu Lab A1 mini 0.6 nozzle"]["nozzle_mm"], 0.6)
        self.assertEqual(by["Bambu Lab X1 Carbon 0.4 nozzle"]["process"], "0.20mm Standard @BBL X1C")

    def test_bambu_options_follow_compatibility_and_enabled_filaments(self):
        d = bambu_dir(self.tmp)
        cfg = self.cfg(bambu={"app": sys.executable, "config_dir": str(d)})
        o = printers.options(cfg, "bambu", "My mini")         # a user printer: compatible through its system parent
        self.assertEqual([r["name"] for r in o["processes"]], ["Strong", "0.20mm Standard @BBL A1M"])
        fil = [r["name"] for r in o["filaments"]]
        self.assertEqual(fil, ["My PLA", "Bambu PLA Basic @BBL A1M", "Generic PETG @BBL A1M"])   # not Hidden PLA, not X1C
        self.assertEqual((o["default_process"], o["default_filament"]), ("0.20mm Standard @BBL A1M", "Bambu PLA Basic @BBL A1M"))
        x = printers.options(cfg, "bambu", "Bambu Lab X1 Carbon 0.4 nozzle")
        self.assertEqual([r["name"] for r in x["processes"]], ["0.20mm Standard @BBL X1C"])
        with self.assertRaises(printers.PrinterError):
            printers.options(cfg, "bambu", "No such printer")

    def test_orca_fixture(self):
        cfg = self.cfg(orca={"app": sys.executable, "config_dir": str(FIX / "orca" / "config")})
        s = printers.slicer_printers(cfg, "orca")
        self.assertEqual([p["name"] for p in s["printers"]], ["Voron 2.4 350 0.4 nozzle"])    # the selected one (no models list)
        o = printers.options(cfg, "orca", "Voron 2.4 350 0.4 nozzle")
        self.assertIn("0.20mm Standard @Voron (FORM test)", [r["name"] for r in o["processes"]])
        self.assertIn("Generic PLA @System", [r["name"] for r in o["filaments"]])

    def test_prusa_enabled_vendor_models_and_conditions(self):
        cfg = self.cfg(prusa={"app": sys.executable, "config_dir": str(FIX / "prusa" / "config")})
        s = printers.slicer_printers(cfg, "prusa")
        self.assertEqual([p["name"] for p in s["printers"]], ["Original Prusa MK4S 0.4 nozzle"])
        p = s["printers"][0]
        self.assertEqual((p["envelope_mm"], p["nozzle_mm"], p["selected"]), ([250.0, 214.0, 220.0], 0.4, True))
        o = printers.options(cfg, "prusa", "Original Prusa MK4S 0.4 nozzle")
        self.assertEqual([r["name"] for r in o["filaments"]], ["Prusament PLA"])        # "Other Printer PLA" is for the MINI
        procs = {r["name"]: r for r in o["processes"]}
        self.assertTrue(procs["0.20mm QUALITY @MK4S 0.4"]["checked"])                    # its condition was evaluated

    def test_inventory_lists_only_installed_slicers_and_the_default(self):
        d = bambu_dir(self.tmp)
        cfg = self.cfg(bambu={"app": sys.executable, "config_dir": str(d)})
        cfg["printer"].update(slicer="bambu", machine="My mini", process="Strong", filament="My PLA")
        inv = printers.inventory(cfg)
        self.assertEqual({p["kind"] for p in inv["printers"]}, {"bambu"})
        self.assertIn("bambu:My mini", [p["id"] for p in inv["printers"]])
        self.assertEqual(inv["default"], {"kind": "bambu", "machine": "My mini", "process": "Strong", "filament": "My PLA"})
        installed = {s["kind"]: s["installed"] for s in inv["slicers"]}
        self.assertTrue(installed["bambu"])
        self.assertFalse(any(v for k, v in installed.items() if k != "bambu"))


class Choice(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-printers-"))
        self.d = bambu_dir(self.tmp)
        printers.clear_cache()

    def test_apply_selects_presets_in_the_right_table(self):
        cfg = base_cfg()
        c = printers.apply(cfg, {"kind": "prusa", "machine": "M", "process": "", "filament": "F"})
        self.assertEqual(c["slicer"]["kind"], "prusa")
        self.assertEqual((c["slicer"]["prusa"]["machine"], c["slicer"]["prusa"]["process"], c["slicer"]["prusa"]["filament"]),
                         ("M", "auto", "F"))
        self.assertEqual(c["slicer"]["prusa"]["app"], NOWHERE)                           # the rest of the table stays
        self.assertNotEqual(cfg["slicer"]["kind"], "prusa")                               # the original is untouched
        b = printers.apply(cfg, {"kind": "bambu", "machine": "M", "process": "P", "filament": "F"})
        self.assertEqual((b["slicer"]["machine"], b["slicer"]["process"]), ("M", "P"))

    def test_validate_fills_in_the_slicers_defaults_and_resolves(self):
        cfg = base_cfg(bambu={"app": sys.executable, "config_dir": str(self.d)})
        c = printers.validate(cfg, {"kind": "bambu", "machine": "Bambu Lab X1 Carbon 0.4 nozzle"})
        self.assertEqual(c, {"kind": "bambu", "machine": "Bambu Lab X1 Carbon 0.4 nozzle",
                             "process": "0.20mm Standard @BBL X1C", "filament": "Bambu PLA Basic @BBL X1C"})
        r = printers.resolve(cfg, c)
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual(r["envelope_mm"], [256.0, 256.0, 250.0])
        with self.assertRaises(printers.PrinterError):                                   # a process for another printer
            printers.validate(cfg, {"kind": "bambu", "machine": "Bambu Lab X1 Carbon 0.4 nozzle", "process": "0.20mm Standard @BBL A1M"})
        with self.assertRaises(printers.PrinterError):
            printers.validate(cfg, {"kind": "nope", "machine": "x"})

    def test_a_users_own_printer_is_handed_to_the_cli_as_a_user_preset(self):
        # Bambu Studio's CLI checks the process against the system printer a user printer inherits from, and only
        # reads "inherits" for a preset "from" "User" (found by slicing with Bambu Studio 02.09.01.70)
        cfg = base_cfg(bambu={"app": sys.executable, "config_dir": str(self.d)})
        r = printers.resolve(cfg, printers.validate(cfg, {"kind": "bambu", "machine": "My mini"}))
        m = r["presets"]["machine"]["data"]
        self.assertEqual((m["from"], m["inherits"], m["printer_settings_id"]), ("User", "Bambu Lab A1 mini 0.4 nozzle", "My mini"))
        s = printers.resolve(cfg, printers.validate(cfg, {"kind": "bambu", "machine": "Bambu Lab A1 mini 0.4 nozzle"}))
        self.assertEqual(s["presets"]["machine"]["data"]["from"], "system")
        self.assertNotIn("inherits", s["presets"]["machine"]["data"])

    def test_set_default_writes_only_printer_keys_after_a_backup(self):
        toml = self.tmp / "studio.toml"
        toml.write_text('# mine\n[printer]\nname = "Old"   # keep\n\n[chat]\nmodel = "opus"\n', encoding="utf-8")
        old = os.environ.get("FORM_CONFIG")
        os.environ["FORM_CONFIG"] = str(toml)
        try:
            cfg = base_cfg(bambu={"app": sys.executable, "config_dir": str(self.d)})
            cfg["_path"] = str(toml)
            done = printers.set_default(cfg, {"kind": "bambu", "machine": "My mini"})
            data = tomllib.loads(toml.read_text(encoding="utf-8"))
            self.assertEqual(data["printer"]["machine"], "My mini")
            self.assertEqual(data["printer"]["slicer"], "bambu")
            self.assertEqual(data["printer"]["process"], "0.20mm Standard @BBL A1M")
            self.assertEqual(data["chat"], {"model": "opus"})
            self.assertIn('name = "Old"   # keep', toml.read_text(encoding="utf-8"))
            self.assertTrue(done["backup"] and Path(done["backup"]).exists())
            self.assertEqual(printers.default_choice(cfg)["machine"], "My mini")
            printers.set_default(cfg, None)
            self.assertIsNone(printers.default_choice(cfg))
        finally:
            if old is None:
                os.environ.pop("FORM_CONFIG", None)
            else:
                os.environ["FORM_CONFIG"] = old


class StudioFollowsTheChoice(unittest.TestCase):
    """The project's printer decides the slice presets, the bed size and the nozzle of the checks (keys only: no kernel)."""

    def test_project_choice_then_default_then_slicer(self):
        from form.studio import Studio
        tmp = Path(tempfile.mkdtemp(prefix="form-printers-st-"))
        d = bambu_dir(tmp)
        cfg = base_cfg(bambu={"app": sys.executable, "config_dir": str(d)})
        cfg["data"]["dir"] = str(tmp / "data")
        st = Studio(cfg)
        p = {"id": "x"}
        self.assertEqual(st.printer_choice(p), (None, ""))
        self.assertEqual(st.printer_env(p)["envelope"], list(cfg["printer"]["envelope_mm"]))
        self.assertEqual(st.slicer_info(p=p)["presets"]["machine"]["name"], "Bambu Lab A1 mini 0.4 nozzle")
        cfg["printer"].update(slicer="bambu", machine="Bambu Lab X1 Carbon 0.4 nozzle",
                              process="0.20mm Standard @BBL X1C", filament="Bambu PLA Basic @BBL X1C")
        self.assertEqual(st.printer_choice(p)[1], "default")
        self.assertEqual(st.printer_env(p)["envelope"], [256.0, 256.0, 250.0])
        p["printer"] = {"kind": "bambu", "machine": "Bambu Lab A1 mini 0.6 nozzle", "process": "0.20mm Standard @BBL A1M",
                        "filament": "Bambu PLA Basic @BBL A1M"}
        s = st.slicer_info(p=p)
        self.assertEqual((st.printer_choice(p)[1], s["nozzle_mm"]), ("project", 0.6))
        self.assertEqual(s["source"]["machine"], "this design's printer in Form Studio")
        self.assertEqual(st.printer_env(p)["name"], "Bambu Lab A1 mini 0.6 nozzle")
        self.assertEqual(st.profile(p), "Bambu Lab A1 mini 0.6 nozzle · Bambu PLA Basic @BBL A1M")


class CLI(unittest.TestCase):
    def test_form_printers_prints_json(self):
        import contextlib
        import io
        tmp = Path(tempfile.mkdtemp(prefix="form-printers-cli-"))
        d = bambu_dir(tmp)
        toml = tmp / "studio.toml"
        toml.write_text(f'[slicer]\nkind = "bambu"\napp = {json.dumps(sys.executable)}\nconfig_dir = {json.dumps(str(d))}\n'
                        + "".join(f'[slicer.{k}]\napp = {json.dumps(str(NOWHERE))}\n' for k in slicer.SLICERS if k != "bambu"), encoding="utf-8")
        old = os.environ.get("FORM_CONFIG")
        os.environ["FORM_CONFIG"] = str(toml)
        printers.clear_cache()
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = printers.main([])
            self.assertEqual(rc, 0)
            self.assertIn("bambu:My mini", [p["id"] for p in json.loads(out.getvalue())["printers"]])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = printers.main(["options", "bambu", "My mini"])
            self.assertEqual((rc, json.loads(out.getvalue())["default_process"]), (0, "0.20mm Standard @BBL A1M"))
        finally:
            if old is None:
                os.environ.pop("FORM_CONFIG", None)
            else:
                os.environ["FORM_CONFIG"] = old


if __name__ == "__main__":
    unittest.main()
