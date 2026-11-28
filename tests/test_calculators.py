"""The engineering calculators (form/calc): worked examples, honesty of every number, and the geometry they write.

  * Each calculator against published worked examples (the guide's, the textbook's, the standard's reference table),
    with the accepted error per row: form/calc/verify.py, which docs/CALCULATORS.md prints.
  * Every number is labelled computed, specified or assumed, a computed one names an equation that is on the sheet, a
    specified one a source that is on the sheet; nothing unsourced is filled in.
  * Every kind of solid builds in the kernel as a valid design with parameters, passes the checks, and is measured
    against the sheet that sized it; a changed parameter changes the verdict (the calculation runs again).
  * The three surfaces: `form calc` (JSON), the MCP tool `calculate`, the Bench entry "calc".
  * By finite elements, where the strength engine is installed: a snap hook's root stress and deflection.

Tests use their own FORM_DATA, never the owner's data."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="form-calc-")
os.environ["FORM_DATA"] = TMP

from form import calc, config, studies  # noqa: E402
from form.calc import design, tools, verify  # noqa: E402
from form.fea import python as fea_python  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

CASES = {
    "snap": ("snapfit", dict(material="PETG", length=15, width=6, undercut=1.0)),
    "snap_tapered": ("snapfit", dict(allow_strain=0.04, utilisation=0.5, taper="thickness_half", length=19, width=9.5,
                                     undercut=2.4, E=1815, mu=0.6, return_angle=45)),
    "snap_width": ("snapfit", dict(allow_strain=0.02, taper="width_quarter", length=20, width=8, undercut=1.2)),
    "annular": ("snapfit", dict(kind="annular", material="PA", diameter=40, wall=2)),
    "hinge": ("hinge", dict(material="PA", thickness=0.5, length=12, angle=90)),
    "hinge_moulded": ("hinge", dict(mode="moulded")),
    "compression": ("spring", dict(wire_d=1.6, mean_d=14, active=6, force=40, wire="music")),
    "compression_open": ("spring", dict(wire_d=2, mean_d=16, active=5, free_length=40, ends="open")),
    "extension": ("spring", dict(kind="extension", wire_d=1, mean_d=8, active=8, force=20, wire="music")),
    "torsion": ("spring", dict(kind="torsion", wire_d=1.5, mean_d=12, active=4, deflection=90, wire="music")),
    "joint_tapped": ("fastener", dict(axial=500, shear=300, mu_interface=0.15, plate_material="AL-6061", into="tapped")),
    "joint_nut": ("fastener", dict(size="M8", axial=2000, plate_material="STEEL")),
    "boss": ("fastener", dict(kind="boss", size="M3", material="PETG", axial=100)),
    "gear": ("gear", dict(module=2, z1=14, z2=30, x1=0.3, backlash=0.1, bore1=5, bore2=8)),
    "helical": ("gear", dict(module=2, z1=15, z2=31, helix=20, backlash=0.1, face=12)),
    "internal": ("gear", dict(kind="internal", module=2, z1=16, z2=48, backlash=0.1)),
    "rack": ("gear", dict(kind="rack", module=2, z1=18, backlash=0.1, bore1=6)),
    "cam": ("cam", dict(lift=8, rise=120, dwell=60, fall=120, roller_radius=4)),
    "fit": ("fit", dict(fit="H7/g6", diameter=25, hole_material="AL-6061", shaft_material="STAINLESS", t_min=-20, t_max=80)),
}


def V(r):
    return {x["key"]: x["value"] for x in r["values"]}


class WorkedExamples(unittest.TestCase):
    def test_every_published_example_is_met_within_its_accepted_error(self):
        rows = verify.examples()
        self.assertGreaterEqual(len(rows), 70)
        self.assertEqual({r["calculator"] for r in rows}, {"snapfit", "spring", "fastener", "gear", "cam", "fit"})
        for r in rows:
            with self.subTest(case=r["case"], quantity=r["quantity"]):
                self.assertTrue(r["pass"], f"{r['computed']} against {r['reference']} {r['unit']}: error {r['error']} > {r['accepted']} ({r['source']})")
                self.assertTrue(r["source"])

    def test_no_accepted_error_is_loose(self):
        for r in verify.examples():
            self.assertLessEqual(r["accepted"], 0.012, r["quantity"])


class Honesty(unittest.TestCase):
    def sheets(self):
        for name, (c, inp) in CASES.items():
            yield name, calc.run(c, inp)

    def test_every_number_is_labelled_and_traceable(self):
        for name, r in self.sheets():
            eqs = {e["id"] for e in r["equations"]}
            srcs = {s["id"] for s in r["sources"]}
            self.assertTrue(r["values"] and r["sources"] and r["equations"], name)
            for v in r["values"]:
                with self.subTest(sheet=name, key=v["key"]):
                    self.assertIn(v["evidence"], ("computed", "specified", "assumed"))
                    if v["evidence"] == "computed":
                        self.assertIn(v["equation"], eqs)
                    if v["evidence"] == "specified":
                        self.assertIn(v["source"], srcs)
                    if v["evidence"] == "assumed":
                        self.assertTrue(v["note"])
            for e in r["equations"]:
                self.assertTrue(e["text"])
                if e["source"]:
                    self.assertIn(e["source"], srcs)
            for c in r["checks"]:
                self.assertIn(c["status"], ("PASS", "WARN", "FAIL", "INFO"))

    def test_an_unsourced_value_is_left_out_not_guessed(self):
        r = calc.run("snapfit", dict(material="PETG", length=15, width=6, undercut=1.0))      # no friction for PETG in the guide
        self.assertNotIn("mating_force", V(r))
        self.assertIn("mating_force", [n["key"] for n in r["not_computed"]])
        r = calc.run("fit", dict(fit="H7/p6", diameter=10, hole_material="AL-6061", shaft_material="STEEL", t_min=-20, t_max=80))
        self.assertNotIn("clearance_min_span", V(r))                                         # STEEL has no sourced expansion
        self.assertIn("alpha_shaft", [n["key"] for n in r["not_computed"]])
        self.assertEqual(V(r)["clearance_min_20"], -0.024)
        r = calc.run("spring", dict(wire_d=1.6, mean_d=14, active=6, force=40))               # no wire named: no verdict on stress
        self.assertNotIn("stress_allow", V(r))
        self.assertFalse([c for c in r["checks"] if c["id"] == "stress"])
        r = calc.run("fastener", dict(kind="boss", size="M3"))                                # the datasheet gives no pull-out force
        self.assertNotIn("pullout_bound", V(r))
        self.assertIn("pullout_bound", [n["key"] for n in r["not_computed"]])

    def test_what_cannot_be_assumed_is_refused(self):
        with self.assertRaises(calc.CalcError) as cm:
            calc.run("fastener", dict(shear=500))                 # friction between the plates is never assumed
        self.assertIn("mu_interface", cm.exception.params)
        with self.assertRaises(calc.CalcError):
            calc.run("snapfit", dict(length=15, width=6, undercut=1))      # no material, no strain
        with self.assertRaises(calc.CalcError) as cm:
            calc.run("snapfit", dict(material="PETG", lenght=15))          # a typo is not ignored
        self.assertIn("lenght", cm.exception.params)
        with self.assertRaises(calc.CalcError):
            calc.run("gear", dict(module=2, z1=14, z2=30, centre_distance=40))   # tighter than the gears mesh

    def test_assumed_friction_is_said_and_the_torque_carries_it(self):
        r = calc.run("fastener", dict(size="M8", axial=2000, plate_material="STEEL"))
        rows = {v["key"]: v for v in r["values"]}
        self.assertEqual(rows["mu_thread"]["evidence"], "assumed")
        self.assertIn("μ_G = 0.12", rows["torque"]["label"])
        self.assertTrue(any("Simplified VDI 2230" in c for c in r["caveats"]))

    def test_printed_parts_carry_their_caveat(self):
        r = calc.run("spring", dict(material="PETG", wire_d=3, mean_d=20, active=5, deflection=8))
        self.assertTrue(any("Printed spring" in c for c in r["caveats"]))
        self.assertEqual({v["key"]: v for v in r["values"]}["poisson"]["evidence"], "assumed")
        r = calc.run("snapfit", dict(material="PETG", length=15, width=6, undercut=1.0))
        self.assertTrue(any("printed specimens" in c for c in r["caveats"]))
        r = calc.run("hinge", dict(mode="moulded"))
        self.assertTrue(any("injection-moulded" in c for c in r["caveats"]))

    def test_the_calculators_need_no_cad_kernel(self):
        code = ("import sys; from form import calc; calc.run('gear', dict(module=2, z1=14, z2=30)); calc.run('fit', dict(fit='H7/g6', diameter=25)); "
                "calc.run('fastener', dict(kind='boss', size='M3')); import form.calc.tools, form.calc.bench, form.calc.design; "
                "print('OCP' in sys.modules or 'build123d' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                             env={**os.environ, "PYTHONPATH": str(ROOT)})
        self.assertEqual(out.stdout.strip(), "False", out.stderr[-400:])


class Solids(unittest.TestCase):
    def test_each_solid_measures_as_its_sheet_says(self):
        rows = verify.geometry()
        self.assertGreaterEqual(len(rows), 18)
        for r in rows:
            with self.subTest(geometry=r["geometry"], what=r["measured_on_the_solid"]):
                self.assertTrue(r["pass"], f"{r['measured']} against {r['expected']} {r['unit']} (accepted {r['accepted']})")


class Designs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())
        cls.made = {}

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()

    def make(self, name):
        if name not in self.made:
            c, inp = CASES[name]
            r = calc.run(c, inp)
            self.made[name] = (r, design.create(self.st, r, name=name, purpose="model")["id"])
        return self.made[name]

    def test_every_kind_builds_as_a_design_with_parameters_and_passes_its_checks(self):
        for name in CASES:
            with self.subTest(design=name):
                r, pid = self.make(name)
                p = self.st.load(pid)
                rev = self.st.rev(p)
                self.assertFalse(rev.get("partial"))
                k = design.KINDS[r["geometry"]["kind"]]
                self.assertEqual(sorted(rev["values"]), sorted(x[0] for x in k["params"]))
                self.assertEqual([e["status"] for e in rev["build_log"]], ["built"] * len(k["features"]))
                job = self.st.run_sync(pid, ["geometry", "exports", "checks"])
                self.assertNotEqual(job["state"], "failed", job)
                checks = self.st.state(pid)["checks"]["checks"]
                bad = [c for c in checks if c["status"] == "FAIL"]
                self.assertFalse(bad, [(c["id"], c.get("value"), c.get("detail")) for c in bad])
                self.assertTrue(any(d["key"].startswith("calc_") for d in self.st.recipe(p).derived(rev["values"])))

    def test_the_calculation_travels_in_the_source_and_runs_again_on_a_change(self):
        r, pid = self.make("snap")
        p = self.st.load(pid)
        c = design.record(self.st.source_text(p))
        self.assertEqual((c["calculator"], c["inputs"]["material"]), ("snapfit", "PETG"))
        s0 = tools.sheet_of(self.st, pid)
        self.assertEqual(s0["status"], "PASS")
        self.assertAlmostEqual(V(s0)["strain"], V(r)["strain"], places=6)
        p = self.st.commit(p, {"length": 8.0}, "shorter arm", "test")          # same undercut on a shorter arm: over the strain
        s1 = tools.sheet_of(self.st, pid)
        self.assertEqual(s1["status"], "FAIL")
        self.assertGreater(V(s1)["strain"], V(s1)["strain_allow"])
        self.assertAlmostEqual(V(s1)["strain"], V(r)["strain"] * (15 / 8) ** 2, places=5)
        e = studies.show(self.st, self.st.load(pid), "calc")
        self.assertEqual((e["state"], e["rev"]), ("current", p["head"]))
        self.assertTrue(e["headline"].startswith("FAIL: Strain"))
        self.assertIn("Bayer", e["evidence"])
        self.assertEqual(e["data"]["sheet"]["status"], "FAIL")
        d = {x["key"]: x for x in self.st.recipe(self.st.load(pid)).derived(self.st.rev(self.st.load(pid))["values"])}
        self.assertIn("calc_check_strain", d)

    def test_gear_dimensions_that_follow_are_recomputed(self):
        r, pid = self.make("gear")
        p = self.st.commit(self.st.load(pid), {"z2": 40.0}, "more teeth", "test")
        s1 = tools.sheet_of(self.st, pid)
        self.assertGreater(V(s1)["centre_distance"], V(r)["centre_distance"] + 9.9)     # (40 - 30) x 2 / 2 = 10 mm of pitch radius
        self.assertFalse(self.st.rev(p).get("partial"))

    def test_bench_entry_for_a_design_no_calculator_wrote(self):
        p = self.st.create("Plain box", "storage_box", purpose="model")
        e = studies.show(self.st, p, "calc")
        self.assertEqual(e["state"], "n/a")
        self.assertIn("calculate", e["why"])
        with self.assertRaises(StudioError):
            tools.sheet_of(self.st, p["id"])

    def test_a_hook_and_an_insert_boss_go_onto_a_face_of_another_design(self):
        src = ('from build123d import Align, Box\nfrom form.recipes.base import Feature, Param, Recipe, Stage\n\n\n'
               'class Design(Recipe):\n    title = "Plate"\n    summary = "A plate."\n'
               '    params = [Param("t", "Thickness", 4, 2, 10, 0.5, "mm", "form", "body")]\n'
               '    features = [Feature("body", "Body", "structure")]\n\n    def build(self, v):\n'
               '        return [Stage("body", Box(60, 40, v["t"], align=(Align.CENTER, Align.CENTER, Align.MIN)))]\n')
        p = self.st.create_design("Plate", src, purpose="model")
        out = tools.call(self.st, "snapfit", dict(material="PETG", length=15, width=6, undercut=1.0), project=p["id"], at=[-15, 0, 4], normal=[0, 0, 1])
        self.assertEqual(out["placed"]["kind"], "snap_hook")
        self.assertAlmostEqual(out["placed"]["thickness"], V(out)["thickness"], places=2)
        out = tools.call(self.st, "fastener", dict(kind="boss", size="M3", material="PETG"), project=p["id"], at=[15, 0, 4], normal=[0, 0, 1])
        self.assertEqual((out["placed"]["kind"], out["placed"]["hole_d"], out["placed"]["outer_d"]), ("boss", 4.0, 7.2))
        self.assertEqual(self.st.load(p["id"])["head"], 3)
        with self.assertRaises(StudioError):
            tools.call(self.st, "cam", dict(lift=8), project=p["id"], at=[0, 0, 4], normal=[0, 0, 1])

    def test_mcp_tool_is_registered_and_lists_the_calculators(self):
        from form import mcp_server
        m = mcp_server.build()
        tool = next(t for t in asyncio.run(m.list_tools()) if t.name == "calculate")
        self.assertIn("specified or assumed", " ".join(tool.description.split()))
        cat = tools.call(self.st)["calculators"]
        self.assertEqual([c["id"] for c in cat], list(calc.CALCULATORS))
        for c in cat:
            self.assertTrue(c["inputs"] and c["standard"] and c["writes"])
        r = tools.call(self.st, "cam", dict(lift=8), build=True, name="A cam", purpose="model")
        self.assertEqual((r["name"], r["head"]), ("A cam", 1))
        self.assertIn("base_r", r["parameters"])

    def test_cli_prints_json(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        out = subprocess.run([sys.executable, "-m", "form", "calc", "spring", "wire_d=1.6", "mean_d=14", "active=6", "force=40", "wire=music"],
                             capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        r = json.loads(out.stdout)
        self.assertEqual((r["calculator"], r["status"]), ("spring", "PASS"))
        out = subprocess.run([sys.executable, "-m", "form", "calc", "fastener", "shear=500"], capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(out.returncode, 2)
        self.assertIn("mu_interface", json.loads(out.stdout)["error"]["params"])
        out = subprocess.run([sys.executable, "-m", "form", "calc", "list"], capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(len(json.loads(out.stdout)["calculators"]), len(calc.CALCULATORS))

    def test_fea_study_is_defined_and_says_when_the_engine_is_missing(self):
        r = tools.call(self.st, "snapfit", dict(material="POM", length=30, width=6, thickness=2.0, utilisation=0.25, mu=0.3),
                       build=True, fea=True, name="Hook for FEA", purpose="model")
        f = r["fea"]
        self.assertIn("study", f)
        self.assertAlmostEqual(f["expect"]["peak_stress_MPa"], 2900 * V(r)["strain"], places=3)
        if fea_python(self.st.cfg) is None:
            self.assertEqual(f["state"], "unavailable")
            return
        from form.fea import study
        t0 = time.time()
        while time.time() - t0 < 300:
            res = study.result(self.st, self.st.load(r["project"]), f["study"])
            if res["state"]["state"] not in ("running", "never"):
                break
            time.sleep(1)
        self.assertEqual(res["state"]["state"], "current", res["state"])
        out = res["result"]
        self.assertTrue(out["converged"])
        # beam theory (the guide) against the solid: the peak stress at the root, and the largest displacement
        self.assertLess(abs(out["peak_von_mises_MPa"] / f["expect"]["peak_stress_MPa"] - 1), f["expect"]["accepted"]["peak_stress"])
        self.assertLess(abs(out["max_displacement_mm"] / f["expect"]["max_displacement_mm"] - 1), f["expect"]["accepted"]["max_displacement"])
        self.assertLess(out["peak_at"][2], 3.0)                       # at the root


class FitsShareOneTable(unittest.TestCase):
    def test_craft_fits_and_the_calculator_read_the_same_limits(self):
        from form import iso286
        from form.craft import fits
        self.assertIs(fits.IT, iso286.IT)
        f = fits.iso_fit("H7/g6", 25)
        r = V(calc.run("fit", dict(fit="H7/g6", diameter=25)))
        self.assertEqual((f["hole"], f["shaft"]), ((r["hole_min"], r["hole_max"]), (r["shaft_min"], r["shaft_max"])))
        from form import hardware_tables, parts
        self.assertIs(parts.INSERTS, hardware_tables.INSERTS)


if __name__ == "__main__":
    unittest.main()
