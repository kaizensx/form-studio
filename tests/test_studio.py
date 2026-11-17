"""Behavioural tests against the real kernel (and the real slicer when installed)."""
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from form import advisor, config, fit as fit_mod, slicer
from form.recipes import RecipeError, registry
from form.studio import NODES, Studio, StudioError
from form.worker import KernelFailure


def make_studio(tmp, **over):
    os.environ["FORM_DATA"] = str(tmp)
    cfg = config.load()
    for section, values in over.items():
        cfg[section].update(values)
    return Studio(cfg)


def states(st, p):
    return {n: st.status(st.load(p["id"]))[n]["state"] for n in NODES}


class Recipes(unittest.TestCase):
    def test_defaults_validate_and_declare_features(self):
        for r in registry().values():
            v = r.validate(r.defaults())
            self.assertEqual(set(v), {p.key for p in r.params})
            for p in r.params:
                self.assertTrue(p.feature == "" or p.feature in {f.id for f in r.features}, p.key)

    def test_constraint_names_feature_params_and_hint(self):
        r = registry()["dock"]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "cable_diameter": 9})
        e = cm.exception
        self.assertEqual(e.feature, "cable")
        self.assertIn("floor", e.params)
        self.assertTrue(e.hint)

    def test_out_of_range_is_rejected(self):
        r = registry()["dock"]
        with self.assertRaises(RecipeError):
            r.validate({**r.defaults(), "lean": 80})
        with self.assertRaises(RecipeError):
            r.validate({**r.defaults(), "lean": float("nan")})


class Fit(unittest.TestCase):
    def test_yield_bounds_and_centering(self):
        self.assertAlmostEqual(fit_mod.window_yield(0.45, 0, 0.1, 0.8), 1.0)
        self.assertEqual(fit_mod.window_yield(2.0, 0, 0.1, 0.8), 0.0)
        self.assertGreater(fit_mod.window_yield(0.45, 0.2, 0.1, 0.8), fit_mod.window_yield(0.2, 0.2, 0.1, 0.8))

    def test_calibration_learns_bias_and_spread(self):
        with tempfile.TemporaryDirectory() as d:
            c = fit_mod.Calibration(Path(d) / "cal.json")
            self.assertEqual(c.correction("P")["source"], "assumed")
            c.add("P", [{"nominal": 10.0, "measured": 9.88}], "coupon")
            self.assertEqual(c.correction("P")["source"], "partly calibrated")
            c.add("P", [{"nominal": 10.1, "measured": 9.97}, {"nominal": 10.2, "measured": 10.09}], "coupon")
            k = c.correction("P")
            self.assertEqual((k["source"], k["n"]), ("calibrated", 3))
            self.assertAlmostEqual(k["bias"], -0.12, places=2)
            self.assertLess(k["sigma"], fit_mod.PRIOR_SIGMA)
            self.assertEqual(c.correction("other")["n"], 0)      # profiles do not leak into each other
            with self.assertRaises(ValueError):
                c.add("P", [{"nominal": 10, "measured": 99}], "coupon")

    def test_measuring_ranks_before_printing(self):
        r = registry()["dock"]
        v = r.defaults()
        f = fit_mod.analyse(r, v, {}, {"gap_min": 0.1, "gap_max": 0.8}, fit_mod.Calibration(Path("/nonexistent")).correction("x"))
        acts = fit_mod.next_actions(f, {})
        self.assertEqual(acts[0]["id"], "measure")
        self.assertEqual(acts[-1]["id"], "print")
        self.assertGreater(acts[0]["after"], f["yield"])


class Intent(unittest.TestCase):
    def setUp(self):
        self.r = registry()["dock"]
        self.v = self.r.defaults()

    def test_amount_and_direction(self):
        p = advisor.parse_intent(self.r, self.v, "increase the lean angle by 3", "pocket")
        self.assertEqual((p["changes"][0]["key"], p["changes"][0]["to"]), ("lean", 18.0))
        p = advisor.parse_intent(self.r, self.v, "set clearance to 0.4", None)
        self.assertEqual((p["changes"][0]["key"], p["changes"][0]["to"]), ("clearance", 0.4))

    def test_vague_request_is_not_guessed(self):
        self.assertIsNone(advisor.parse_intent(self.r, self.v, "make it nicer", None))

    def test_clamped_to_range(self):
        p = advisor.parse_intent(self.r, self.v, "set lean angle to 75", "pocket")
        self.assertEqual(p["changes"][0]["to"], 30.0)


class SlicerParsing(unittest.TestCase):
    def test_preset_inheritance_is_flattened(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "system" / "BBL" / "process"
            base.mkdir(parents=True)
            (base / "root.json").write_text(json.dumps({"name": "root", "layer_height": "0.2", "wall_loops": "2"}), encoding="utf-8")
            (base / "child.json").write_text(json.dumps({"name": "child", "inherits": "root", "layer_height": "0.28"}), encoding="utf-8")
            flat = slicer.flatten(Path(d), "process", "child")
            self.assertEqual((flat["layer_height"], flat["wall_loops"]), ("0.28", "2"))
            self.assertNotIn("inherits", flat)
            with self.assertRaises(slicer.SlicerBlocked):
                slicer.flatten(Path(d), "process", "missing")

    def test_layers_from_gcode(self):
        g = "\n".join(["M83", "; CHANGE_LAYER", "; Z_HEIGHT: 0.2", "G1 Z0.2", "G1 X0 Y0", "; FEATURE: Outer wall",
                       "G1 X10 Y0 E0.5", "G1 X10 Y10 E0.5", "G1 X20 Y20", "; FEATURE: Bridge", "G1 X30 Y20 E0.4",
                       "; CHANGE_LAYER", "; Z_HEIGHT: 0.4", "G1 X0 Y0", "; FEATURE: Sparse infill", "G3 X10 Y10 I5 J5 E1"])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.gcode"
            f.write_text(g, encoding="utf-8")
            L = slicer.parse_layers(f)
        self.assertEqual([l["z"] for l in L], [0.2, 0.4])
        self.assertEqual([p["t"] for p in L[0]["paths"]], ["Outer wall", "Bridge"])
        self.assertEqual(L[0]["paths"][0]["p"], [0, 0, 10, 0, 10, 10])
        self.assertGreater(len(L[1]["paths"][0]["p"]), 6)      # arc was interpolated


class Pipeline(unittest.TestCase):
    """One studio for the class: starting the kernel takes a couple of seconds."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-test-"))
        cls.st = make_studio(cls.tmp)
        cls.has_slicer = cls.st.slicer_info().get("available", False)
        cls.p = cls.st.create("Test dock", "dock")
        cls.job = cls.st.run_sync(cls.p["id"])

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def load(self):
        return self.st.load(self.p["id"])

    def expect(self, **want):
        got = states(self.st, self.p)
        if not self.has_slicer:
            got.pop("slice"), want.pop("slice", None)
        self.assertEqual(got, {**got, **want})

    def test_01_first_run_makes_everything_current(self):
        self.assertEqual([s["state"] for s in self.job["steps"]][:3], ["done"] * 3)
        self.expect(geometry="current", exports="current", checks="current", slice="current")
        ch = self.st.state(self.p["id"])["checks"]
        byid = {c["id"]: c for c in ch["checks"]}
        self.assertEqual(byid["solid"]["status"], "PASS")
        self.assertEqual(byid["interfaces"]["status"], "PASS")
        self.assertEqual(byid["mesh"]["status"], "PASS")
        self.assertEqual(byid["conversion"]["status"], "PASS")
        self.assertEqual({c["evidence"] for c in ch["checks"]} - {"computed", "heuristic", "model"}, set())

    def test_02_every_face_is_attributed_to_a_declared_feature(self):
        v = self.st.view(self.load())
        self.assertEqual({m["feature"] for m in v["mesh"]}, {f.id for f in registry()["dock"].features} - {"mark"})   # marks are off by default
        audit = {a["key"]: a for a in v["interface_audit"]}
        self.assertAlmostEqual(audit["pocket_width"]["modelled"], audit["pocket_width"]["intended"], places=6)

    def test_03_critical_dimension_invalidates_and_regenerates(self):
        before = self.st.keys(self.load())
        stl_before = self.st.read(self.load(), "exports", before["exports"])["files"]["stl"]["sha256"]
        p = self.st.commit(self.load(), {"clearance": 0.35}, "looser")
        after = self.st.keys(p)
        self.assertTrue(all(before[n] != after[n] for n in NODES))
        self.expect(geometry="stale", exports="stale", checks="stale", slice="stale")
        self.assertFalse(self.st.gate(p)["ready"])
        with self.assertRaises(StudioError):                       # stale outputs cannot be released
            self.st.approve(p, [])
        self.st.run_sync(p["id"])
        self.expect(geometry="current", exports="current", checks="current", slice="current")
        stl_after = self.st.read(self.load(), "exports", after["exports"])["files"]["stl"]["sha256"]
        self.assertNotEqual(stl_before, stl_after)
        ex = self.st.read(self.load(), "exports", after["exports"])
        self.assertIn(f"_r{p['head']:02d}", ex["files"]["stl"]["name"])
        audit = self.st.view(self.load())["interface_audit"][0]
        self.assertAlmostEqual(audit["modelled"], 71.5 + 0.7, places=6)

    def test_04_orientation_keeps_the_solid_but_restales_downstream(self):
        k0 = self.st.keys(self.load())
        self.st.settings(self.load(), {"orientation": "on_back"})
        k1 = self.st.keys(self.load())
        self.assertEqual(k0["geometry"], k1["geometry"])
        self.assertNotEqual(k0["exports"], k1["exports"])
        self.expect(geometry="current", exports="stale", checks="stale", slice="stale")
        self.st.settings(self.load(), {"orientation": "as_modelled"})
        self.expect(geometry="current", exports="current", checks="current", slice="current")   # keys return, so do the artifacts

    def test_05_fit_window_and_calibration_touch_only_checks(self):
        k0 = self.st.keys(self.load())
        self.st.settings(self.load(), {"fit": {"gap_min": 0.2, "gap_max": 0.9}})
        k1 = self.st.keys(self.load())
        self.assertEqual([n for n in NODES if k0[n] != k1[n]], ["checks"])
        self.st.settings(self.load(), {"fit": {"gap_min": 0.1, "gap_max": 0.8}})
        self.st.add_evidence(self.load(), {"kind": "widths", "source": "coupon",
                                           "pairs": [{"nominal": 10, "measured": 9.9}, {"nominal": 10.1, "measured": 9.98}, {"nominal": 10.2, "measured": 10.11}]})
        k2 = self.st.keys(self.load())
        self.assertEqual([n for n in NODES if k0[n] != k2[n]], ["checks"])
        f = self.st.fit(self.load())
        self.assertEqual(f["sources"]["printer"]["source"], "calibrated")
        self.assertLess(f["sources"]["printer"]["bias"], 0)
        self.st.run_sync(self.p["id"])

    def test_06_infeasible_change_is_refused_and_nothing_is_saved(self):
        head = self.load()["head"]
        with self.assertRaises(StudioError) as cm:
            self.st.commit(self.load(), {"edge_r": 6, "corner_r": 3})
        self.assertEqual(cm.exception.extra.get("feature"), "soften")
        self.assertTrue(cm.exception.hint)
        self.assertEqual(self.load()["head"], head)
        with self.assertRaises(StudioError):
            self.st.preview(self.load(), {"plug_width": 80})
        self.assertGreater(self.st.preview(self.load(), {"lean": 12})["triangles"], 100)   # kernel still serves

    def test_07_kernel_timeout_restarts_cleanly(self):
        r0 = self.st.kernel.restarts
        with self.assertRaises(KernelFailure) as cm:
            self.st.kernel.call("variants", timeout=0.01, recipe_id="dock", base=self.st.rev(self.load())["values"],
                                grid=[{"depth": d} for d in (70, 75, 80, 85, 90)])
        self.assertEqual(cm.exception.info["kind"], "timeout")
        self.assertEqual(self.st.kernel.restarts, r0 + 1)
        self.assertGreater(self.st.view(self.load())["triangles"], 100)
        self.assertEqual(self.load()["head"], self.st.load(self.p["id"])["head"])

    def test_08_release_then_supersede_then_tamper(self):
        if not self.has_slicer:
            self.skipTest("release needs a slice")
        p = self.load()
        g = self.st.gate(p)
        self.assertTrue(g["ready"], g)
        with self.assertRaises(StudioError):                       # warnings must be acknowledged one by one
            self.st.approve(p, [])
        rel = self.st.approve(p, [w["id"] for w in g["warnings"]])["release"]
        self.assertEqual(self.st.approval_state(self.load())["state"], "approved")
        self.assertTrue(self.st.verify_release(self.load(), rel)["intact"])
        # the coupon measurements from test_05 calibrate the printer; they are not validation of this part
        self.assertIn("not physically validated", (self.st.dir(p["id"]) / "releases" / rel / "REPORT.md").read_text(encoding="utf-8"))
        p = self.st.commit(self.load(), {"relief_depth": 5})
        ap = self.st.approval_state(p)
        self.assertEqual(ap["state"], "superseded")
        v = self.st.verify_release(p, rel)
        self.assertTrue(v["intact"])
        self.assertFalse(v["matches_head"])
        stl = next((self.st.dir(p["id"]) / "releases" / rel).glob("*.stl"))
        stl.write_bytes(stl.read_bytes() + b"x")
        self.assertFalse(self.st.verify_release(p, rel)["intact"])
        self.st.run_sync(p["id"])

    def test_08b_release_over_a_failed_check_needs_each_one_and_a_reason(self):
        if not self.has_slicer:
            self.skipTest("release needs a slice")
        import copy
        from unittest import mock
        real = self.st.read

        def failing(p, kind, key):                                  # the same revision, with one check failed
            r = real(p, kind, key)
            if kind == "checks":
                r = copy.deepcopy(r)
                c = next(c for c in r["checks"] if c["status"] == "PASS")
                c["status"], c["value"] = "FAIL", "0.24 mm"
            return r
        with mock.patch.object(self.st, "read", side_effect=failing):
            p = self.load()
            g = self.st.gate(p)
            self.assertFalse(g["ready"])
            self.assertTrue(g["can_override"], g)
            self.assertEqual(len(g["failures"]), 1)
            warns = [w["id"] for w in g["warnings"]]
            with self.assertRaises(StudioError):                   # not without acknowledging the failure
                self.st.approve(p, warns, "fine")
            with self.assertRaises(StudioError):                   # not without a reason
                self.st.approve(p, warns, "", override_failures=[g["failures"][0]["id"]])
            r = self.st.approve(p, warns, "Printed one already; the thin spot is cosmetic.",
                                override_failures=[g["failures"][0]["id"]])
        m = r["manifest"]
        self.assertEqual([f["id"] for f in m["released_with_failed_checks"]], [g["failures"][0]["id"]])
        self.assertIn("released with failed checks", m["evidence_level"])
        report = (self.st.dir(p["id"]) / "releases" / r["release"] / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("Released with failed checks", report)
        self.assertIn("thin spot is cosmetic", report)

    def test_09_save_restore_round_trip(self):
        p = self.load()
        archive = self.st.export_archive(p).read_bytes()
        q = self.st.import_archive(archive)
        self.assertNotEqual(q["id"], p["id"])
        self.assertEqual(q["head"], p["head"])
        self.assertEqual([r["values"] for r in q["revisions"]], [r["values"] for r in p["revisions"]])
        self.assertEqual(self.st.keys(q), self.st.keys(p))
        got = {n: self.st.status(q)[n]["state"] for n in NODES}
        if not self.has_slicer:
            got.pop("slice")
        self.assertEqual(set(got.values()), {"current"})          # restored artifacts are recognised, not rebuilt

    def test_10_corrupt_state_recovers_from_backup(self):
        p = self.load()
        self.st.settings(p, {"name": "Renamed"})                   # guarantees a .bak exists
        path = self.st.dir(p["id"]) / "project.json"
        path.write_text("{ not json", encoding="utf-8")
        q = self.st.load(p["id"])
        self.assertTrue(q["_recovered"])
        self.assertEqual(q["head"], p["head"])

    def test_11_unsafe_archive_is_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("project.json", json.dumps({"schema": "form-project/1", "id": "evil", "recipe": "dock"}))
            z.writestr("../../escape.txt", "x")
        with self.assertRaises(StudioError):
            self.st.import_archive(buf.getvalue())
        self.assertFalse((self.tmp.parent / "escape.txt").exists())
        with self.assertRaises(StudioError):
            self.st.import_archive(b"not a zip")
        with self.assertRaises(StudioError):
            self.st.dir("../etc")

    def test_12_alternatives_are_really_built(self):
        r = advisor.alternatives(self.st, self.load(), [{"key": "depth", "values": [70, 100]}, {"key": "cable_diameter", "values": [4.5, 12]}],
                                 {"material": 1, "stability": 1})
        ok = [x for x in r["rows"] if x["ok"]]
        self.assertEqual(len(ok), 2)                               # a 12 mm channel leaves no roof under the pocket: reported, not hidden
        self.assertEqual(len([x for x in r["rows"] if not x["ok"]]), 2)
        self.assertLess(ok[0]["metrics"]["material"], ok[1]["metrics"]["material"])
        self.assertLess(ok[0]["metrics"]["stability"], ok[1]["metrics"]["stability"])

    def test_13_test_piece_is_cut_from_the_real_solid(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.load()
            r = self.st._k("test_piece", key=self.st.keys(p)["geometry"], recipe_id="dock", values=self.st.rev(p)["values"], out_dir=d, name="ring")
            self.assertAlmostEqual(r["bbox"][2], 6.0, places=3)
            self.assertLess(r["volume_mm3"], 0.05 * self.st.head_summary(p)["volume_mm3"])


class SlicerBlockedIsHonest(unittest.TestCase):
    def test_missing_slicer_blocks_only_the_slice(self):
        tmp = Path(tempfile.mkdtemp(prefix="form-test-"))
        st = make_studio(tmp, slicer={"app": "/nonexistent/BambuStudio"})
        try:
            p = st.create("No slicer", "coupon")
            job = st.run_sync(p["id"])
            by = {s["node"]: s for s in job["steps"]}
            self.assertEqual([by[n]["state"] for n in ("geometry", "exports", "checks")], ["done"] * 3)
            self.assertEqual(by["slice"]["state"], "blocked")
            self.assertIn("not found", by["slice"]["error"]["message"])
            g = st.gate(st.load(p["id"]))
            self.assertFalse(g["ready"])
            self.assertTrue(any("blocked" in r for r in g["reasons"]))
        finally:
            st.kernel.stop()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
