"""Designing without a 3D printer: printing is an opt-in capability (form/capabilities.py), a design's purpose (print
or model), the checks and release of a 3D model with no slicer installed, OBJ and GLB exports, settings that apply at
once, and the one-time migration that keeps people who already print on printing.

Every slicer points at a program that does not exist (tests/test_slicers.py base_cfg), so nothing here can slice.
"""
import copy
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from form import capabilities, checks as checks_mod, config_edit, installer, meshio, purpose
from form.digest import digest
from form.studio import Studio, StudioError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_slicers import base_cfg  # noqa: E402


def cfg_for(tmp: Path, printing=None) -> dict:
    cfg = copy.deepcopy(base_cfg())
    cfg["data"]["dir"] = str(tmp / "data")
    cfg["printer"]["envelope_mm"] = [180, 180, 180]
    cfg["general"] = {} if printing is None else {"printing": printing}     # nothing chosen yet, or the older answer
    return cfg


class Purposes(unittest.TestCase):
    def test_names_and_defaults(self):
        self.assertEqual(purpose.normalise("3D model"), "model")
        self.assertEqual(purpose.normalise("For 3D printing"), "print")
        self.assertIsNone(purpose.normalise("banana"))
        self.assertEqual(purpose.normalise_process("CNC machining"), "cnc")
        self.assertEqual(purpose.normalise_process("molding"), "injection")
        self.assertIsNone(purpose.normalise_process("knitting"))
        self.assertEqual(purpose.of({}), "print", "a design saved before purposes existed was a print")
        self.assertFalse(purpose.printing({}), "printing is opt-in: unset is off")
        self.assertEqual(purpose.default({}), "model", "a new design is a 3D model unless printing is on")
        self.assertEqual(purpose.default({"general": {"printing": False}}), "model")
        self.assertTrue(purpose.printing({"general": {"printing": True}}), "the older answer still reads as it did")
        self.assertEqual(purpose.default({"general": {"capabilities": ["core", "print"]}}), "print")
        self.assertFalse(purpose.printing({"general": {"capabilities": ["parts"], "printing": True}}),
                         "capabilities win over the older answer")
        d = purpose.describe({"purpose": "model", "process": "cnc"})
        self.assertEqual((d["process"], d["min_feature_mm"]), ("cnc", 0.8))
        self.assertIn("Plate contact", d["not_applicable"])

    def test_model_checks_skip_everything_about_a_printer(self):
        a = {"brep": {"valid": True, "solids": 1, "volume_mm3": 1000.0}, "interface_audit": [],
             "mesh": {"status": "PASS", "failures": [], "triangles": 12, "volume_mm3": 1000.0},
             "thin": {"t": 0.5}, "thickness_samples": 100,
             "orientation_table": [{"id": "as_modelled", "footprint_mm": [10, 10], "height_mm": 10, "steep_mm2": 50,
                                    "ceiling_mm2": 20, "contact_mm2": 5}]}
        summary = {"bbox": [[0, 0, 0], [10, 20, 30]], "derived": []}
        rec = type("R", (), {"fit": None, "features": [], "mesh": False})()
        items = checks_mod.build(rec, summary, a, {"orientation": "as_modelled", "purpose": "model", "process": "cnc"}, None)
        ids = [c["id"] for c in items]
        for gone in ("envelope", "wall", "overhang", "bridge", "adhesion", "fit"):
            self.assertNotIn(gone, ids)
        self.assertEqual(next(c for c in items if c["id"] == "size")["value"], "10.0 × 20.0 × 30.0 mm")
        feat = next(c for c in items if c["id"] == "feature")
        self.assertEqual((feat["status"], feat["evidence"]), ("WARN", "heuristic"), "0.5 mm against CNC's 0.8 mm")
        items = checks_mod.build(rec, summary, a, {"orientation": "as_modelled", "purpose": "model", "process": ""}, None)
        self.assertEqual(next(c for c in items if c["id"] == "feature")["status"], checks_mod.NA,
                         "no process stated: reported, never counted as a pass")


class MeshFormats(unittest.TestCase):
    def test_obj_and_glb_from_a_binary_stl(self):
        tmp = Path(tempfile.mkdtemp(prefix="form-mesh-"))
        try:
            tris = [((0, 0, 0), (10, 0, 0), (0, 10, 0)), ((0, 0, 0), (0, 10, 0), (0, 0, 10)),
                    ((0, 0, 0), (0, 0, 10), (10, 0, 0)), ((10, 0, 0), (0, 0, 10), (0, 10, 0))]
            b = bytearray(b"\0" * 80) + struct.pack("<I", len(tris))
            for t in tris:
                b += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v) for v in t) + b"\0\0"
            stl = tmp / "t.stl"
            stl.write_bytes(bytes(b))
            v, f = meshio.read_stl(stl)
            self.assertEqual((len(v), len(f)), (4, 4), "shared corners are welded")
            obj = meshio.obj_bytes(stl, "Tetra").decode()
            self.assertEqual(obj.count("\nv "), 4)
            self.assertEqual(obj.count("\nf "), 4)
            glb = meshio.glb_bytes(stl, "Tetra")
            magic, ver, length = struct.unpack_from("<III", glb, 0)
            self.assertEqual((magic, ver, length), (0x46546C67, 2, len(glb)))
            jlen, jtype = struct.unpack_from("<II", glb, 12)
            self.assertEqual(jtype, 0x4E4F534A)
            g = json.loads(glb[20:20 + jlen])
            self.assertEqual(g["accessors"][0]["count"], 4)
            self.assertAlmostEqual(max(g["accessors"][0]["max"]), 0.01, msg="metres, as glTF requires")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class JustDesigning(unittest.TestCase):
    """Someone with no printer and no slicer: a 3D model is designed, checked, exported and released."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-noprinter-"))
        cls.st = Studio(cfg_for(cls.tmp, printing=False))

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_model_from_start_to_release(self):
        st = self.st
        p = st.create("Bracket", "shelf_bracket")
        self.assertEqual(p["purpose"], "model", "someone who only designs gets a 3D model by default")
        self.assertEqual(st.slice_mode(p)["why"], "purpose")
        job = st.run_sync(p["id"])
        self.assertEqual(job["state"], "done")
        self.assertEqual([s["node"] for s in job["steps"]], ["geometry", "exports", "checks"], "nothing is sliced")
        s = st.state(p["id"])
        self.assertEqual(s["status"]["slice"]["off"]["why"], "purpose")
        ids = [c["id"] for c in s["checks"]["checks"]]
        self.assertIn("size", ids)
        self.assertFalse({"envelope", "overhang", "adhesion", "wall", "fit"} & set(ids), ids)
        self.assertIn("Plate contact", s["checks"]["not_applicable"])
        self.assertIsNone(s["fit"])
        self.assertEqual(s["purpose"]["purpose"], "model")
        self.assertEqual(sorted(s["exports"]["files"]), ["glb", "obj", "step", "stl"])
        g = s["gate"]
        self.assertTrue(g["ready"], g["reasons"])
        self.assertNotIn("slice", (g["evidence_level"] + " ".join(g["reasons"])).lower())
        self.assertNotIn("not_covered", g, "nothing is missing from a model: it is not a print")
        r = st.approve(st.load(p["id"]), [w["id"] for w in g["warnings"]])
        files = r["manifest"]["files"]
        for ext in (".step", ".stl", ".obj", ".glb", ".3mf", "_views.png", "_iso.png"):
            self.assertTrue(any(f.endswith(ext) for f in files), (ext, sorted(files)))
        self.assertFalse(any(f.endswith(".gcode") for f in files))
        self.assertNotIn("PRINT_REPORT.md", files)
        self.assertTrue(r["manifest"]["slicer"]["not_for_printing"])
        report = (st.dir(p["id"]) / "releases" / r["release"] / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("A 3D model, not made for 3D printing", report)
        self.assertNotIn("Print orientation", report)
        self.assertTrue(st.verify_release(st.load(p["id"]), r["release"])["intact"])
        d = digest(st, p["id"])
        self.assertEqual(d["purpose"]["purpose"], "model")
        self.assertIn("Do not ask the person about a printer", d["purpose"]["note"])

    def test_purpose_switch_and_process(self):
        st = self.st
        p = st.create("Plate", "storage_box", purpose="model", process="cnc")
        k_model = st.keys(p)["checks"]
        self.assertEqual(p["process"], "cnc")
        p = st.settings(p, {"purpose": "print"})
        self.assertEqual(p["purpose"], "print")
        self.assertNotIn("process", p, "a process belongs to a model")
        self.assertEqual(st.slice_mode(p)["why"], "no_slicer", "a print with no slicer is Design only, as before")
        self.assertNotEqual(st.keys(p)["checks"], k_model, "the print checks are other checks")
        p = st.settings(p, {"purpose": "model", "process": "laser"})
        self.assertEqual((p["purpose"], p["process"]), ("model", "laser"))
        self.assertIn("purpose", [d["kind"] for d in p["decisions"]])
        with self.assertRaises(StudioError):
            st.settings(p, {"purpose": "banana"})
        with self.assertRaises(StudioError):
            st.create("x", "storage_box", purpose="model", process="knitting")

    def test_a_models_checks_ignore_the_printer(self):
        st = self.st
        p = st.create("Cube", "storage_box", purpose="model")
        k = st.keys(p)["checks"]
        st.cfg["printer"]["envelope_mm"] = [99, 99, 99]
        try:
            self.assertEqual(st.keys(p)["checks"], k, "changing the printer does not stale a model's checks")
        finally:
            st.cfg["printer"]["envelope_mm"] = [180, 180, 180]

    def test_print_designs_keep_their_keys(self):
        st = self.st
        p = st.create("Old", "storage_box", purpose="print")
        k = st.keys(p)["checks"]
        q = dict(p)
        q.pop("purpose")
        self.assertEqual(st.keys(q)["checks"], k, "a design saved before purposes existed keeps its outputs")


class SetupRespectsTheChoice(unittest.TestCase):
    def test_no_slicer_is_installed_or_asked_for(self):
        rows = [{"id": "kernel", "level": "required", "status": "missing", "group": "engine", "one_of": "", "needs": []},
                {"id": "slicer.bambu", "level": "recommended", "status": "missing", "group": "slicer", "one_of": "slicer", "needs": []}]
        with mock.patch.object(purpose, "decided", return_value=True):
            self.assertEqual(installer.auto_ids(rows, {"general": {"printing": False}}), ["kernel"])
            self.assertEqual(installer.auto_ids(rows, {"general": {"printing": True}}), ["kernel", "slicer.bambu"])
        with mock.patch.object(purpose, "decided", return_value=False):
            self.assertEqual(installer.auto_ids(rows, {"general": {"printing": True}}), ["kernel"],
                             "a slicer waits until the person says they have a printer")

    def test_survey_makes_slicers_optional_for_someone_who_only_designs(self):
        rows = installer.survey({**copy.deepcopy(base_cfg()), "general": {"printing": False}}, only=["slicer.bambu", "slicer.orca"])
        self.assertTrue(rows and all(r["level"] == "optional" and not r["default"] for r in rows), rows)


class SettingsApply(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-settings-"))
        self.toml = self.tmp / "studio.toml"
        self.toml.write_text("# mine\n[printer]\nname = \"X\"\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"FORM_CONFIG": str(self.toml)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_printing_answer_is_written_applied_and_read_back(self):
        cfg = cfg_for(self.tmp)
        cfg["_path"] = str(self.toml)
        self.assertFalse(purpose.decided(cfg))
        done = config_edit.set_values(cfg, {"general.printing": "true"})      # the older key sets the capability
        self.assertEqual(done["changed"], {"general.capabilities": ["core", "parts", "mesh", "print"]})
        self.assertTrue(purpose.printing(cfg), "applied to the running configuration at once")
        self.assertTrue(purpose.decided(cfg))
        text = self.toml.read_text(encoding="utf-8")
        self.assertIn("# mine", text)
        self.assertIn('[general]\ncapabilities = ["core", "parts", "mesh", "print"]', text)
        from form import config
        self.assertTrue(purpose.printing(config.load()), "survives a restart")
        config_edit.set_values(cfg, {"general.capabilities": "parts, render"})
        self.assertEqual(capabilities.of(cfg), ["core", "parts", "render"], "core is always on")
        self.assertFalse(purpose.printing(cfg))
        with self.assertRaises(config_edit.ConfigError):
            config_edit.set_values(cfg, {"general.capabilities": ["banana"]})

    def test_capability_plan_names_what_turning_one_on_downloads(self):
        rows = [{"id": "kernel", "level": "required", "status": "ok", "group": "engine", "one_of": "", "needs": [],
                 "capability": "core", "size": "about 250 MB", "installable": False},
                {"id": "blender", "level": "optional", "status": "missing", "group": "cad", "one_of": "", "needs": [],
                 "capability": "render", "size": "about 400 MB", "installable": True},
                {"id": "slicer.bambu", "level": "recommended", "status": "missing", "group": "slicer", "one_of": "slicer",
                 "needs": [], "capability": "print", "size": "about 200 MB", "installable": True},
                {"id": "slicer.orca", "level": "optional", "status": "missing", "group": "slicer", "one_of": "slicer",
                 "needs": [], "capability": "print", "size": "about 150 MB", "installable": True}]
        plan = {c["id"]: c for c in capabilities.plan(rows, ["core", "render"])["capabilities"]}
        self.assertEqual((plan["core"]["size_mb"], plan["core"]["ready"]), (0, True))
        self.assertEqual((plan["render"]["install"], plan["render"]["size_mb"], plan["render"]["on"]), (["blender"], 400, True))
        self.assertEqual(plan["print"]["install"], ["slicer.bambu"], "one slicer is enough")
        self.assertEqual([c["id"] for c in capabilities.CATALOGUE][-1], "print", "3D printing is the last card")
        cfg = {"general": {"capabilities": ["core", "render"]}}
        with mock.patch.object(purpose, "decided", return_value=True):
            self.assertEqual(capabilities.install_ids(cfg, rows), ["blender"], "only what was chosen is installed")

    def test_migration_keeps_people_who_print_on_printing_once(self):
        cfg = cfg_for(self.tmp)
        cfg["_path"] = str(self.toml)
        root = self.tmp / "data"
        (root / "old-dock").mkdir(parents=True)
        (root / "old-dock" / "project.json").write_text(json.dumps({"id": "old-dock", "name": "Dock"}), encoding="utf-8")
        out = capabilities.migrate(cfg, root)
        self.assertTrue(out["migrated"], out)
        self.assertIn("old-dock", out["why"])
        self.assertTrue(purpose.printing(cfg))
        self.assertIn("print", self.toml.read_text(encoding="utf-8"))
        config_edit.set_values(cfg, {"general.capabilities": ["core"]})
        self.assertEqual(capabilities.migrate(cfg, root)["why"], "already done", "it runs once")
        self.assertFalse(purpose.printing(cfg), "the person's later answer stands")

    def test_migration_leaves_a_new_person_creating(self):
        cfg = cfg_for(self.tmp)
        cfg["_path"] = str(self.toml)
        root = self.tmp / "data"
        root.mkdir(parents=True, exist_ok=True)
        out = capabilities.migrate(cfg, root)
        self.assertFalse(out["migrated"])
        self.assertFalse(purpose.printing(cfg))
        self.assertNotIn("capabilities", self.toml.read_text(encoding="utf-8"))

    def test_migration_reads_a_configured_slicer(self):
        self.toml.write_text('[slicer]\nkind = "orca"\n', encoding="utf-8")
        cfg = cfg_for(self.tmp)
        cfg["_path"] = str(self.toml)
        out = capabilities.migrate(cfg, self.tmp / "data2")
        self.assertTrue(out["migrated"] and "orca" in out["why"], out)

    def test_settings_name_what_is_installed(self):
        cfg = cfg_for(self.tmp)
        d = config_edit.describe(cfg)
        rows = {r["key"]: r for r in d["settings"]}
        self.assertIn("detected", rows["slicer.kind"])
        self.assertIsInstance(rows["slicer.kind"]["detected"], list)
        self.assertEqual(rows["chat.model"]["type"], "model", "the model is picked, not typed")
        self.assertTrue(rows["slicer.machine"].get("hidden"), "preset names are chosen in the printer picker")
        self.assertEqual({r["tab"] for r in d["settings"]} - {"general", "printer", "chat", "apps", "updates", "advanced"}, set())
        self.assertEqual(config_edit.coerce("chat.model", ""), "default")


if __name__ == "__main__":
    unittest.main()
