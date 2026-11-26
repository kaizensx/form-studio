"""“Use in Form Studio” (form/use.py): one switch per optional engine or app, separate from whether it is installed.
Installed but switched off, an engine is never called; switched on, it is offered. Nothing here runs a real engine:
each one is replaced by a stand-in that records whether it was reached."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from form import config, config_edit, installer, use


def cfg_for(tmp: Path) -> dict:
    c = {k: dict(v) for k, v in config.DEFAULTS.items()}
    c["data"]["dir"] = str(tmp / "data")
    c["_path"] = str(tmp / "studio.toml")
    return c


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-use-"))
        self.cfg = cfg_for(self.tmp)
        self.env = mock.patch.dict(os.environ, {"FORM_CONFIG": str(self.tmp / "studio.toml"),
                                                "FORM_DATA": str(self.tmp / "data"),
                                                "FORM_ENGINES_DIR": str(self.tmp / "engines")})
        self.env.start()
        for k in list(os.environ):
            if k.startswith("FORM_USE_") or k == "FORM_RECON_CADFIT":
                os.environ.pop(k)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text: str):
        (self.tmp / "studio.toml").write_text(text, encoding="utf-8")


class Switches(Base):
    def test_defaults_keep_what_form_studio_did_before(self):
        self.assertTrue(use.on("recon.learned", self.cfg))          # CAD-Recode: used whenever it is installed
        self.assertFalse(use.on("recon.cadfit", self.cfg))          # CADFit: off until asked for
        for eid in ("game.coacd", "exemplars.cadevolve", "blender", "freecad", "openscad", "slicer.bambu", "slicer.orca",
                    "slicer.prusa"):
            self.assertTrue(use.on(eid, self.cfg), eid)
        self.assertTrue(use.on("kernel", self.cfg))                 # nothing to switch: always used

    def test_every_switch_has_a_default_and_a_settings_key(self):
        d = use.defaults()
        for eid, sw in use.SWITCHES.items():
            sec, name = sw["key"].split(".", 1)
            self.assertEqual(config.DEFAULTS[sec][name], sw["default"], eid)
            self.assertEqual(config_edit.SCHEMA[sw["key"]]["type"], "bool", eid)
            self.assertEqual(d[sec][name], sw["default"])
            self.assertTrue(sw["effect"].startswith("On: "), eid)   # one concrete line next to the switch
        ids = {s.id for s in installer.REGISTRY}
        self.assertFalse(set(use.SWITCHES) - ids, "a switch for something the installer does not list")

    def test_the_file_decides_and_an_environment_variable_wins_for_one_run(self):
        self.write("[use]\nblender = false\n[recon]\nlearned = false\ncadfit = true\n")
        self.assertFalse(use.on("blender"))                         # cfg None: read from the file
        self.assertFalse(use.on("recon.learned"))
        self.assertTrue(use.on("recon.cadfit"))
        with mock.patch.dict(os.environ, {"FORM_USE_BLENDER": "1", "FORM_RECON_CADFIT": "0"}):
            self.assertTrue(use.on("blender"))
            self.assertFalse(use.on("recon.cadfit"))
            self.assertEqual(use.describe("blender")["locked_by"], "FORM_USE_BLENDER")
        self.assertEqual(use.describe("blender")["locked_by"], "")

    def test_settings_writes_the_switch_and_it_applies_at_once(self):
        done = config_edit.set_values(self.cfg, {"use.freecad": False, "recon.learned": False})
        self.assertEqual(set(done["changed"]), {"use.freecad", "recon.learned"})
        text = (self.tmp / "studio.toml").read_text(encoding="utf-8")
        self.assertIn("freecad = false", text)
        self.assertIn("learned = false", text)
        self.assertFalse(use.on("freecad", self.cfg))               # the running configuration
        self.assertFalse(use.on("freecad"))                         # and a child process reading the file
        config_edit.set_values(self.cfg, {"use.freecad": True})
        self.assertTrue(use.on("freecad"))

    def test_the_software_list_says_installed_and_used_separately(self):
        rows = {r["id"]: r for r in installer.survey(self.cfg, only=["recon.learned", "recon.cadfit", "game.coacd",
                                                                     "kernel", "claude"])}
        self.assertIsNone(rows["kernel"]["use"])
        self.assertIsNone(rows["claude"]["use"])                    # an agent is picked per conversation
        self.assertEqual(rows["recon.learned"]["use"]["on"], True)
        self.assertEqual(rows["recon.cadfit"]["use"], {**rows["recon.cadfit"]["use"], "key": "recon.cadfit", "on": False,
                                                       "default": False})
        self.assertTrue(rows["recon.cadfit"]["noncommercial"])      # the licence stays on the card, next to the switch
        self.assertIn("CC BY-NC 4.0", rows["recon.cadfit"]["licence"])
        self.assertIn("CC BY-NC 4.0", rows["recon.learned"]["licence"])

    def test_cadfit_installed_is_ok_whether_it_is_used_or_not(self):
        with mock.patch.object(installer, "_cadfit_ready", lambda cfg: "its own Python (test)"):
            row = installer.survey(self.cfg, only=["recon.cadfit"])[0]
            self.assertEqual((row["status"], row["use"]["on"]), ("ok", False))
            self.cfg["recon"]["cadfit"] = True
            row = installer.survey(self.cfg, only=["recon.cadfit"])[0]
            self.assertEqual((row["status"], row["use"]["on"]), ("ok", True))


def _ctx(calls=None):
    return {"rep": {}, "say": lambda d: None, "hard": time.perf_counter() + 60, "fin": 0.0, "tol": 0.1, "name": "part",
            "V": np.zeros((3, 3)), "F": np.zeros((1, 3), int), "budget_s": 60.0, "better": lambda a, b: True}


class MeshToCad(Base):
    """CAD-Recode and CADFit, as form/recon/pipeline.py offers them."""

    def candidate(self):
        return {"verified": True, "report": {"engine": "stand-in", "verified": True, "hausdorff_mm": 0.01}}

    def test_cad_recode_installed_but_off_is_not_asked(self):
        from form.recon import learned, pipeline
        asked = mock.Mock(return_value=self.candidate())
        prog = {"report": {"method": "sketches and extrusions"}}
        with mock.patch.object(learned, "status", lambda *a, **k: {"installed": True}), \
             mock.patch.object(learned, "candidate", asked):
            self.write("[recon]\nlearned = false\n")
            ctx = _ctx()
            self.assertIs(pipeline._offer_learned(prog, ctx), prog)
            self.assertIsNone(pipeline._learned(ctx["V"], ctx["F"], 0.1, "part", ctx["say"]))
            asked.assert_not_called()
            self.assertNotIn("learned", ctx["rep"])

    def test_cad_recode_installed_and_on_is_offered(self):
        from form.recon import learned, pipeline
        asked = mock.Mock(return_value=self.candidate())
        prog = {"report": {"method": "sketches and extrusions"}}
        with mock.patch.object(learned, "status", lambda *a, **k: {"installed": True}), \
             mock.patch.object(learned, "candidate", asked):
            ctx = _ctx()                                            # no file: the default, on
            got = pipeline._offer_learned(prog, ctx)
            asked.assert_called_once()
            self.assertIsNot(got, prog)
            self.assertTrue(ctx["rep"]["learned"]["chosen"])

    def test_cad_recode_on_but_not_installed_is_not_asked(self):
        from form.recon import learned, pipeline
        asked = mock.Mock()
        with mock.patch.object(learned, "status", lambda *a, **k: {"installed": False}), \
             mock.patch.object(learned, "candidate", asked):
            prog = {"report": {}}
            self.assertIs(pipeline._offer_learned(prog, _ctx()), prog)
            asked.assert_not_called()

    def test_cadfit_installed_but_off_is_not_started(self):
        from form.recon import cadfit
        search = mock.Mock(return_value=self.candidate())
        prog = {"report": {}}
        with mock.patch.object(cadfit, "candidate", search):
            rep = {}
            self.assertIs(cadfit.offer(prog, None, None, 0.1, "part", lambda d: None, 60.0, rep, lambda a, b: True), prog)
            search.assert_not_called()
            self.assertEqual(rep, {})

    def test_cadfit_on_is_offered(self):
        from form.recon import cadfit
        search = mock.Mock(return_value=self.candidate())
        prog = {"report": {}}
        self.write("[recon]\ncadfit = true\n")
        with mock.patch.object(cadfit, "candidate", search):
            rep = {}
            got = cadfit.offer(prog, None, None, 0.1, "part", lambda d: None, 60.0, rep, lambda a, b: True)
            search.assert_called_once()
            self.assertIsNot(got, prog)
            self.assertEqual(rep["cadfit"]["status"], "enabled")


class OtherEngines(Base):
    def test_coacd_installed_but_off_is_not_started(self):
        from form import engines
        from form.game import lod
        self.cfg["use"]["coacd"] = False
        with mock.patch.object(engines, "python", lambda *a, **k: Path("/usr/bin/true")), \
             mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as e:
                lod.coacd_parts(np.zeros((3, 3)), np.zeros((1, 3), int), self.cfg)
            self.assertIn("switched off", str(e.exception))
            run.assert_not_called()

    def test_coacd_on_reaches_its_engine(self):
        from form import engines
        from form.game import lod
        done = mock.Mock(returncode=1, stderr="stand-in", stdout="")
        with mock.patch.object(engines, "python", lambda *a, **k: Path("/usr/bin/true")), \
             mock.patch("subprocess.run", return_value=done) as run:
            with self.assertRaises(RuntimeError) as e:
                lod.coacd_parts(np.zeros((3, 3)), np.zeros((1, 3), int), self.cfg, work=self.tmp)
            run.assert_called_once()
            self.assertIn("CoACD failed", str(e.exception))

    def test_the_corpus_is_not_read_when_it_is_off(self):
        from form import exemplars
        self.assertIsNotNone(exemplars._corpus())
        self.write("[use]\ncorpus = false\n")
        self.assertIsNone(exemplars._corpus())
        self.assertEqual(exemplars.reference_hits("bracket", 2), [])

    def test_blender_off_is_never_run(self):
        from form.adapters import blender
        self.cfg["use"]["blender"] = False
        with mock.patch.object(blender, "probe") as probe, mock.patch.object(blender, "version") as version:
            r = blender.resolve(self.cfg)
            probe.assert_not_called()
            version.assert_not_called()
        self.assertFalse(r["available"])
        self.assertIn("switched off", r["reason"])
        self.cfg["use"]["blender"] = True
        found = {"available": True, "app": "/x/blender", "version": "5.0.0", "reason": ""}
        with mock.patch.object(blender, "probe", return_value=found):
            self.assertEqual(blender.resolve(self.cfg), found)

    def test_blender_off_still_shows_as_installed_in_settings(self):
        from form.adapters import blender
        self.cfg["use"]["blender"] = False
        found = {"available": True, "app": "/x/blender", "version": "5.0.0", "reason": ""}
        with mock.patch.object(blender, "probe", return_value=found):
            row = installer.survey(self.cfg, only=["blender"])[0]
        self.assertEqual((row["status"], row["use"]["on"]), ("ok", False))

    def test_freecad_and_openscad_off_are_not_found_for_use(self):
        from form import cad_bridges
        with mock.patch.object(cad_bridges, "find_freecad", lambda cfg=None: "/x/FreeCADCmd"), \
             mock.patch.object(cad_bridges, "find_openscad", lambda cfg=None: "/x/openscad"):
            self.assertEqual(cad_bridges.freecad(self.cfg), "/x/FreeCADCmd")
            self.assertEqual(cad_bridges.openscad(self.cfg), "/x/openscad")
            self.cfg["use"].update(freecad=False, openscad=False)
            self.assertIsNone(cad_bridges.freecad(self.cfg))
            self.assertIsNone(cad_bridges.openscad(self.cfg))
            st = cad_bridges.status(self.cfg)
            self.assertEqual((st["freecad"]["available"], st["freecad"]["use"], st["freecad"]["gui"]), (False, False, None))
            self.assertIn("switched off", st["openscad"]["reason"])


class Slicers(Base):
    def fake(self, installed):
        """Adapters that are installed or not, and say when they are asked to resolve."""
        from form import slicer
        asked = []

        class A:
            def __init__(self, kind):
                self.kind, self.LABEL = kind, kind.title()

            def find_app(self, cfg):
                return f"/apps/{self.kind}" if self.kind in installed else None

            def resolve(self, cfg):
                asked.append(self.kind)
                return {"available": True, "presets": {}, "app": f"/apps/{self.kind}"}
        return mock.patch.object(slicer, "adapter", lambda kind: A(kind)), asked

    def test_automatic_skips_a_slicer_that_is_off(self):
        from form import slicer
        patch, asked = self.fake({"bambu", "orca"})
        with patch:
            self.assertEqual(slicer.auto_kind(self.cfg), "bambu")
            self.cfg["use"]["bambu"] = False
            self.assertEqual(slicer.auto_kind(self.cfg), "orca")
            r = slicer.resolve(self.cfg)
            self.assertEqual((r["kind"], r["available"], asked), ("orca", True, ["orca"]))

    def test_a_chosen_slicer_that_is_off_is_never_run(self):
        from form import slicer
        patch, asked = self.fake({"bambu"})
        self.cfg["slicer"]["kind"] = "bambu"
        self.cfg["use"]["bambu"] = False
        with patch:
            r = slicer.resolve(self.cfg)
        self.assertEqual((r["available"], asked), (False, []))
        self.assertIn("switched off", r["reason"])

    def test_every_installed_slicer_off_says_so(self):
        from form import slicer
        patch, asked = self.fake({"bambu"})
        self.cfg["use"]["bambu"] = False
        with patch:
            r = slicer.resolve(self.cfg)
        self.assertEqual((r["available"], asked), (False, []))
        self.assertIn("installed but switched off", r["reason"])


if __name__ == "__main__":
    unittest.main()
