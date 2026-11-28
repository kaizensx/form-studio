"""Strength studies (form/fea): definitions, materials with sources, keys and staleness, honesty when the engine is
missing, and, when the FEA engine's Python is there, real studies on real designs through the kernel.

The solver libraries are an optional engine. The classes marked "needs the engine" run when form.fea.python() finds
one ($FORM_FEA_PYTHON, an installed engine, or this Python with Netgen, scikit-fem and PyAMG) and are skipped
otherwise, with the reason. tests/test_fea_verification.py holds the verification suite.
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix="form-fea-")
os.environ["FORM_DATA"] = TMP                      # never the owner's data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from form import config, fea  # noqa: E402
from form import material_library as ml  # noqa: E402
from form.design_guide import EXAMPLE  # noqa: E402
from form.fea import bench, material, study, tools  # noqa: E402
from form.fea import cli as fea_cli  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

ENGINE = fea.python(config.load())
LIMIT_S = float(os.environ.get("FORM_FEA_BRACKET_S", 60))      # a bracket converges within this (60 s on the Mac it is built on)
NEEDS_ENGINE = unittest.skipUnless(ENGINE, "the FEA engine is not installed here (set FORM_FEA_PYTHON to its Python)")

BRACKET = '''
from build123d import Align, Box, Cylinder, Pos, Rot, fillet
from form.recipes.base import Feature, Param, Recipe, Stage

M = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Bracket"
    summary = "An L bracket with a filleted inside corner and three holes."
    params = [Param("t", "Thickness", 6, 3, 12, 0.5, "mm", "form", "body"),
              Param("r", "Fillet", 6, 0, 10, 0.5, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        t = v["t"]
        s = Box(80, 40, t, align=M) + Box(t, 40, 60, align=M)
        if v["r"] > 0:
            e = [e for e in s.edges() if abs(e.center().X - t) < 1e-6 and abs(e.center().Z - t) < 1e-6]
            s = fillet(e, v["r"])
        s -= Pos(30, 20, 0) * Cylinder(3, 3 * t)
        s -= Pos(62, 20, 0) * Cylinder(3, 3 * t)
        s -= Pos(0, 20, 42) * Rot(0, 90, 0) * Cylinder(3, 3 * t)
        return [Stage("body", s)]
'''
ALU = {"name": "6061-T6 (test)", "E_GPa": 68.9, "poisson": 0.33, "yield_MPa": 276, "density_kg_m3": 2700,
       "source": "test fixture"}
STATIC = {"kind": "static", "material": ALU,
          "fixtures": [{"type": "fixed", "faces": [[33, 20, 3], [65, 20, 3]]}],
          "loads": [{"type": "force", "faces": [[3, 20, 45]], "vector": [300, 0, -200]}],
          "mesh": {"budget_s": LIMIT_S}}


def decode(field, name):
    f = field["fields"][name]
    a = np.frombuffer(base64.b64decode(f["data"]), dtype="<f4" if f["type"] == "f4" else "u1")
    return a.reshape(-1, f["components"]) if f["components"] > 1 else a


class Definitions(unittest.TestCase):
    def test_a_definition_is_normalised(self):
        d = study.clean({"fixtures": [{"faces": [0, 1, 2]}],
                         "loads": [{"type": "force", "at": [5, 5, 5], "magnitude": 10, "direction": [0, 0, -2]},
                                   {"type": "gravity"}, {"type": "pressure", "faces": [[1, 1, 1]], "value_MPa": 2}]})
        self.assertEqual(d["kind"], "static")
        self.assertEqual(d["fixtures"], [{"type": "fixed", "faces": [{"at": [0.0, 1.0, 2.0]}]}])
        self.assertEqual(d["loads"][0]["vector"], [0.0, 0.0, -10.0])
        self.assertAlmostEqual(d["loads"][1]["vector"][2], -9806.65)
        self.assertEqual(d["loads"][2]["value"], 2.0)

    def test_what_is_wrong_is_said(self):
        for body, word in (({"kind": "fatigue"}, "Unknown study kind"),
                           ({"loads": [{"type": "force", "faces": [[0, 0, 0]], "vector": [1, 0, 0]}]}, "at least one support"),
                           ({"fixtures": [{"faces": [[0, 0, 0]]}]}, "at least one load"),
                           ({"fixtures": [{"type": "glued", "faces": [[0, 0, 0]]}], "loads": []}, "unknown type"),
                           ({"fixtures": [{"faces": [[0, 0]]}], "loads": []}, "three numbers"),
                           ({"fixtures": [{"faces": [[0, 0, 0]]}], "loads": [{"type": "force", "faces": [[1, 1, 1]]}]}, "newtons"),
                           ({"kind": "modal", "mesh": {"speed": 3}}, "Unknown mesh option"),
                           ({"kind": "modal", "mesh": {"tol_stress": 5}}, "outside")):
            with self.assertRaises(StudioError, msg=str(body)) as cm:
                study.clean(body)
            self.assertIn(word, str(cm.exception))

    def test_a_hold_names_the_directions_that_may_not_move(self):
        d = study.clean({"fixtures": [{"type": "hold", "faces": [[0, 0, 0]], "directions": [0, 0, 1]}],
                         "loads": [{"type": "gravity"}]})
        self.assertEqual(d["fixtures"][0]["directions"], [[0.0, 0.0, 1.0]])
        with self.assertRaises(StudioError) as cm:
            study.clean({"fixtures": [{"type": "hold", "faces": [[0, 0, 0]]}], "loads": [{"type": "gravity"}]})
        self.assertIn("directions", str(cm.exception))

    def test_a_heat_study_takes_thermal_conditions_and_needs_a_temperature_level(self):
        d = study.clean({"kind": "thermal", "thermal": [{"type": "temperature", "faces": [[0, 0, 0]], "value_C": 80},
                                                        {"type": "convection", "at": [1, 1, 1], "h_W_m2K": 10, "ambient_C": 20},
                                                        {"type": "heat", "faces": [[2, 2, 2]], "value_W": 5}]})
        self.assertEqual([c["type"] for c in d["thermal"]], ["temperature", "convection", "heat"])
        self.assertEqual((d["thermal"][1]["h"], d["thermal"][1]["ambient"], d["reference_C"], d["fixtures"]), (10.0, 20.0, 20.0, []))
        for body, word in (({"kind": "thermal", "thermal": [{"type": "heat", "faces": [[0, 0, 0]], "value_W": 5}]}, "held at a temperature"),
                           ({"kind": "thermal_stress", "thermal": [{"type": "temperature", "faces": [[0, 0, 0]], "value_C": 80}]},
                            "needs supports"),
                           ({"kind": "modal", "thermal": [{"type": "temperature", "faces": [[0, 0, 0]], "value_C": 80}]}, "belong to"),
                           ({"kind": "thermal", "thermal": [{"type": "radiation", "faces": [[0, 0, 0]]}]}, "unknown type"),
                           ({"kind": "thermal", "thermal": [{"type": "convection", "faces": [[0, 0, 0]], "h_W_m2K": 10}]}, "ambient_C")):
            with self.assertRaises(StudioError, msg=str(body)) as cm:
                study.clean(body)
            self.assertIn(word, str(cm.exception))
        body, _ = fea_cli.parse("thermal", ["--temperature", "0,0,0:80", "--convection", "1,1,1:10:20", "--heat", "2,2,2:5"])
        self.assertEqual(study.clean(body)["thermal"], d["thermal"])

    def test_a_modal_study_needs_no_load_and_ignores_one(self):
        d = study.clean({"kind": "modal", "loads": [{"type": "gravity"}]})
        self.assertEqual((d["loads"], d["fixtures"], d["modes"]), ([], [], 6))
        self.assertIn("ignored", d["ignored"])

    def test_cli_arguments_become_a_definition(self):
        body, opt = fea_cli.parse("static", ["--fix", "0,1,2", "--roller", "3,4,5", "--force", "9,9,9:0,0,-50", "--pressure",
                                             "1,1,1:0.5", "--preload", "1,2,3:4,5,6:800", "--gravity", "--material", "AL-6061",
                                             "--mesh", '{"h0": 3}', "--again"])
        d = study.clean(body)
        self.assertEqual([f["type"] for f in d["fixtures"]], ["fixed", "roller"])
        self.assertEqual([x["type"] for x in d["loads"]], ["force", "pressure", "preload", "gravity"])
        self.assertEqual(d["loads"][2]["force"], 800.0)
        self.assertEqual((d["material"], d["mesh"], opt["again"]), ("AL-6061", {"h0": 3.0}, True))
        with self.assertRaises(ValueError):
            fea_cli.parse("static", ["--fix", "1,2"])


class StrengthAsAConstraint(unittest.TestCase):
    """fea.safety_factor in a search: solved on real candidates best first, within a stated number of solves; a
    candidate that was not solved is never called feasible (form/fea/constraint.py)."""

    def _ranked(self, n):
        return [{"values": {"t": float(i)}, "changes": {"t": float(i)}} for i in range(n)]

    def _solver(self, passes_from, calls):
        def solve(st, p, sid, values, cons, ops):
            calls.append(values["t"])
            ok = values["t"] >= passes_from
            return {"ok": ok, "metrics": {"fea.safety_factor": 1.0 + values["t"]}, "violations": [] if ok else ["too weak"],
                    "evidence": "simulated (FEA, linear static, converged to 1.0 %)", "seconds": 0.0}
        return solve

    def test_the_best_candidate_wins_when_it_meets_the_constraint(self):
        from form.fea import constraint
        calls = []
        with mock.patch.object(constraint, "solve", self._solver(0, calls)):
            r = constraint.verify_ranked(None, {}, "s", self._ranked(9), [("fea.safety_factor", ">=", 2.0)], {})
        self.assertEqual((r["winner"], calls, r["runs"]), (0, [0.0], 1))

    def test_halving_finds_the_best_candidate_that_passes_and_only_solved_ones_count(self):
        from form.fea import constraint
        calls = []
        with mock.patch.object(constraint, "solve", self._solver(5, calls)):
            r = constraint.verify_ranked(None, {}, "s", self._ranked(12), [("fea.safety_factor", ">=", 2.0)], {})
        self.assertEqual(r["winner"], 5)
        self.assertLessEqual(r["runs"], 6)
        self.assertEqual(sorted(x["index"] for x in r["solved"]), sorted({int(c) for c in calls}))
        self.assertTrue(all(x["ok"] == (x["index"] >= 5) for x in r["solved"]))

    def test_the_number_of_solves_is_bounded_and_said(self):
        from form.fea import constraint
        calls = []
        with mock.patch.object(constraint, "solve", self._solver(100, calls)):
            r = constraint.verify_ranked(None, {}, "s", self._ranked(64), [("fea.safety_factor", ">=", 2.0)], {}, runs=4)
        self.assertEqual((r["winner"], r["runs"]), (None, 3))            # best, worst, middle: none passes
        calls.clear()
        with mock.patch.object(constraint, "solve", self._solver(37, calls)):
            r = constraint.verify_ranked(None, {}, "s", self._ranked(64), [("fea.safety_factor", ">=", 2.0)], {}, runs=4)
        self.assertEqual(r["runs"], 4)
        self.assertIn("limit of 4 solves", r["stopped"])
        self.assertTrue(r["winner"] is not None and r["winner"] >= 37)   # a solved, passing one: not claimed better

    def test_a_study_that_did_not_converge_has_no_safety_factor(self):
        from form.fea import constraint
        m = constraint.metrics({"converged": False, "safety_factor": None, "peak_von_mises_MPa": 50.0})
        self.assertEqual(set(m.values()), {None})
        m = constraint.metrics({"converged": True, "safety_factor": {"value": 3.0, "low": 2.8}, "peak_von_mises_MPa": 50.0,
                                "max_displacement_mm": 0.2})
        self.assertEqual(m["fea.safety_factor"], 2.8)                    # the lower value, error applied

    def test_a_strength_metric_is_not_an_objective_and_unknown_ones_are_named(self):
        from form import optimize as opt
        from form.fea import constraint

        class St:
            def recipe(self, p): return None
            def rev(self, p): return {"values": {}}
        with self.assertRaises(opt.OptimizeError) as cm:
            opt.run(St(), {}, [{"key": "t"}], {"minimize": "fea.peak_von_mises_MPa"}, [])
        self.assertIn("not the objective", str(cm.exception))
        with self.assertRaises(StudioError) as cm:
            constraint.check_names([("fea.fatigue_life", ">=", 1.0)])
        self.assertIn("fea.safety_factor", cm.exception.hint)


class Materials(unittest.TestCase):
    """Every number a study uses says where it is from; nothing is defaulted."""

    def test_given_values_carry_their_source_or_are_marked_assumed(self):
        m = material.resolve(ALU)
        self.assertEqual((m["E"], m["nu"], m["yield"], m["density"]), (68900.0, 0.33, 276.0, 2700.0))
        self.assertEqual(m["sources"]["E"]["evidence"], material.SPECIFIED)
        self.assertEqual(m["sources"]["yield"]["source"], "test fixture")
        bare = material.resolve({"E_GPa": 200, "poisson": 0.3})
        self.assertEqual(bare["sources"]["E"]["evidence"], material.ASSUMED)
        self.assertIsNone(bare["yield"])
        self.assertIn("no safety factor", " ".join(bare["notes"]))

    def test_nothing_is_assumed_when_a_value_is_missing(self):
        for bad, word in (({"E_GPa": 200}, "Poisson"), ({"poisson": 0.3}, "Young"), (None, "needs a material"),
                          ({"E_GPa": 200, "poisson": 0.5}, "outside")):
            with self.assertRaises(StudioError) as cm:
                material.resolve(bad)
            self.assertIn(word, str(cm.exception))

    def test_a_heat_study_needs_the_conductivity_and_thermal_stress_the_expansion_too(self):
        m = material.resolve({"k_W_mK": 167, "source": "datasheet"}, need=("k",))
        self.assertEqual((m["k"], m["E"], m["sources"]["k"]["unit"]), (167.0, None, "W/(m K)"))
        with self.assertRaises(StudioError) as cm:
            material.resolve(ALU, need=("E", "poisson", "k", "cte"))
        self.assertIn("thermal conductivity", str(cm.exception))
        self.assertIn("expansion", str(cm.exception))
        self.assertIn("k_W_mK", cm.exception.hint)
        m = material.resolve({**ALU, "k_W_mK": 167, "cte_per_K": 23.6e-6}, need=("E", "poisson", "k", "cte"))
        self.assertEqual((m["k"], m["cte"]), (167.0, 23.6e-6))
        self.assertEqual(study.NEED["thermal"], ("k",))

    def _library(self, props, kind="engineering", density=2700.0, knock=None):
        def prop(key, name, direction=""):
            n = name + ("_" + direction if direction else "")
            if n in props:
                return {"name": n, "value": props[n], "unit": "x", "source": f"sheet for {key}", "url": "https://example.test/ds",
                        "evidence": "specified (datasheet)"}
            return {"name": n, "status": "unsourced"}
        return mock.patch.multiple(ml, create=True, prop=prop,
                                   density=lambda key: {"value": density, "source": "sheet", "evidence": "specified (datasheet)"},
                                   record=lambda key: {"id": key, "label": key, "kind": kind},
                                   knockdown_z=lambda key: knock or {})

    def test_the_materials_library_supplies_values_with_their_documents(self):
        with self._library({"E": 68.9, "poisson": 0.33, "yield": 276.0}):
            m = material.resolve("AL-6061")
        self.assertEqual((m["E"], m["nu"], m["yield"], m["density"]), (68900.0, 0.33, 276.0, 2700.0))
        self.assertEqual(m["sources"]["yield"]["source"], "sheet for AL-6061")
        self.assertEqual(m["sources"]["yield"]["url"], "https://example.test/ds")
        self.assertEqual(m["strength_basis"], "yield strength")

    def test_a_filament_is_judged_against_its_weakest_sourced_strength(self):
        knock = {"uts": {"ratio": 0.62, "xy": 50, "z": 31, "unit": "MPa", "evidence": "modelled"}}
        with self._library({"E": 2.6, "poisson": 0.35, "uts_z": 31.0}, kind="filament", density=1240.0, knock=knock):
            m = material.resolve("PLA")
        self.assertEqual(m["yield"], 31.0)
        self.assertIn("across the layers", m["strength_basis"])
        self.assertEqual(m["knockdown"]["ratio"], 0.62)
        self.assertIn("not simulated", " ".join(m["notes"]))

    def test_an_unsourced_poisson_ratio_stops_the_study_and_can_be_given(self):
        with self._library({"E": 2.6, "uts_z": 31.0}, kind="filament"):
            with self.assertRaises(StudioError) as cm:
                material.resolve("PLA")
            self.assertIn("Poisson's ratio", str(cm.exception))
            self.assertIn("Nothing is assumed", str(cm.exception))
            m = material.resolve({"key": "PLA", "poisson": 0.35})
        self.assertEqual(m["sources"]["nu"]["evidence"], material.ASSUMED)
        self.assertEqual(m["sources"]["E"]["evidence"], "specified (datasheet)")

    def test_a_name_needs_a_library_with_mechanical_properties(self):
        if material.library_ready():
            self.skipTest("this build's materials library has sourced mechanical properties")
        with self.assertRaises(StudioError) as cm:
            material.resolve("AL-6061")
        self.assertIn("no sourced mechanical properties", str(cm.exception))


class EngineRegistration(unittest.TestCase):
    def test_the_engine_is_an_opt_in_with_pins_a_licence_and_a_card(self):
        from form import engines, installer
        spec = engines.SPECS["fea"]
        self.assertEqual({p.split("==")[0] for p in spec["pins"]},
                         {"netgen-mesher", "netgen-occt", "scikit-fem", "scipy", "pyamg", "numpy"})
        row = {r["id"]: r for r in installer.survey(config.load(), only=["fea"])}["fea"]
        self.assertEqual(row["level"], "optional")
        self.assertIn("LGPL-2.1", row["licence"])
        self.assertIn("stops changing", row["about"])
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for word in ("LGPL-2.1-only", "scikit-fem", "PyAMG", "Gmsh", "CalculiX"):
            self.assertIn(word, notices)

    def test_the_app_keeps_the_solver_modules_out_and_ships_them_for_the_engine(self):
        spec = (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8")
        self.assertIn('"engine_src/form/fea"', spec)
        self.assertIn("FEA_ONLY", spec)

    def test_nothing_outside_the_engine_imports_the_solver_libraries(self):
        """form.fea, its study, material, tools, cli and bench modules load without Netgen, scikit-fem or PyAMG."""
        code = ("import sys\n"
                "for m in ('netgen', 'skfem', 'pyamg'):\n    sys.modules[m] = None\n"
                "import form.fea, form.fea.study, form.fea.material, form.fea.tools, form.fea.cli, form.fea.bench\n"
                "import form.mcp_server\nprint('ok')")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT),
                           env={**os.environ, "PYTHONPATH": str(ROOT)})
        self.assertEqual(r.stdout.strip(), "ok", r.stderr[-800:])

    def test_the_tools_are_registered(self):
        from form import mcp_server
        names = {t.name for t in asyncio.run(mcp_server.build().list_tools())}
        self.assertTrue({"strength_study", "get_strength_study"} <= names)


class WithStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.p = cls.st.create_design("Bracket", BRACKET, purpose="model")

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()

    def load(self):
        return self.st.load(self.p["id"])


class WithoutTheEngine(WithStudio):
    """No solver, no number: a study is saved, says it cannot run and how to get the engine, and stores nothing."""

    def test_a_study_without_the_engine_is_refused_and_nothing_is_stored(self):
        d = study.define(self.st, self.load(), STATIC)
        with mock.patch.object(study, "python", lambda cfg=None: None):
            s = study.state(self.st, self.load(), d["id"])
            self.assertEqual(s["state"], "never")
            self.assertIn("optional engine", s["unavailable"])
            for call in (lambda: study.start(self.st, self.p["id"], d["id"]), lambda: study.run(self.st, self.p["id"], d["id"])):
                with self.assertRaises(StudioError) as cm:
                    call()
                self.assertEqual(cm.exception.extra.get("kind"), "unavailable")
                self.assertIn("No result was made up", str(cm.exception))
            self.assertEqual(bench.summary(self.st, self.load())["state"], "never")
        self.assertFalse(list(study._dir(self.st, self.load(), d["id"]).glob("*.json")))
        study.remove(self.st, self.load(), d["id"])
        self.assertEqual(study.definitions(self.load()), [])

    def test_a_study_needs_a_material_and_says_where_to_set_one(self):
        d = study.define(self.st, self.load(), {**STATIC, "material": None})
        s = study.state(self.st, self.load(), d["id"])
        self.assertEqual(s["state"], "unavailable")
        self.assertIn("No material is set", s["why"])
        study.remove(self.st, self.load(), d["id"])

    def test_the_key_follows_the_material_numbers_the_loads_and_the_geometry(self):
        p = self.load()
        d = study.define(self.st, p, STATIC)
        k = study.key(self.st, self.load(), d)
        self.assertEqual(k, study.key(self.st, self.load(), {**d, "name": "another name"}))
        softer = {**d, "material": {**ALU, "E_GPa": 60}}
        heavier = {**d, "loads": [{**d["loads"][0], "vector": [300.0, 0.0, -250.0]}]}
        self.assertEqual(len({k, study.key(self.st, self.load(), softer), study.key(self.st, self.load(), heavier)}), 3)
        study.remove(self.st, self.load(), d["id"])


@NEEDS_ENGINE
class RealStudies(WithStudio):
    """Needs the engine. One bracket, solved once and read many ways."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.d = study.define(cls.st, cls.st.load(cls.p["id"]), STATIC)
        job = study.start(cls.st, cls.p["id"], cls.d["id"])
        cls.progress = []
        t0 = time.time()
        while cls.st.jobs[job["id"]]["state"] == "running" and time.time() - t0 < 240:
            pr = cls.st.jobs[job["id"]]["steps"][0].get("progress")
            if pr and pr.get("label"):
                cls.progress.append(pr["label"])
            time.sleep(0.2)
        cls.job = cls.st.jobs[job["id"]]
        cls.r = study.result(cls.st, cls.st.load(cls.p["id"]), cls.d["id"])

    def test_1_a_bracket_converges_in_under_a_minute_with_a_stated_error(self):
        self.assertEqual(self.job["state"], "done", self.job.get("error"))
        self.assertTrue(any("Solving refinement" in x for x in self.progress))
        self.assertEqual(self.job["result"]["state"], "current")
        res = self.r["result"]
        self.assertTrue(res["converged"], res.get("not_converged_because"))
        self.assertLess(res["wall_seconds"], LIMIT_S)
        self.assertGreaterEqual(len(res["convergence"]["levels"]), 3)
        unknowns = [lv["unknowns"] for lv in res["convergence"]["levels"]]
        self.assertTrue(all(b > 1.3 * a for a, b in zip(unknowns, unknowns[1:])), unknowns)   # each one really finer
        err = res["discretisation_error"]["stress"]
        self.assertTrue(0 < err <= 0.05)
        self.assertRegex(res["evidence"], r"^simulated \(FEA, linear static, converged to \d+\.\d %\)$")
        self.assertIn("Not a test of the made part", res["how_known"])
        self.assertIn("linear elastic", " ".join(res["assumptions"]))

    def test_2_the_safety_factor_names_its_strength_and_its_lower_value(self):
        res = self.r["result"]
        sf = res["safety_factor"]
        self.assertAlmostEqual(sf["value"], 276.0 / res["peak_von_mises_MPa"], places=6)
        self.assertLess(sf["low"], sf["value"])
        self.assertEqual(sf["against"], "yield strength")
        self.assertEqual(sf["strength_source"]["design"]["source"], "test fixture")
        self.assertEqual(res["materials"]["design"]["sources"]["E"]["evidence"], material.SPECIFIED)
        self.assertIn("safety factor", res["headline"])

    def test_3_equilibrium_is_checked_and_the_fixture_edge_is_named(self):
        res = self.r["result"]
        eq = res["equilibrium"]
        self.assertTrue(eq["balanced"])
        np.testing.assert_allclose(eq["applied_N"], [300, 0, -200], atol=1e-6)
        np.testing.assert_allclose(eq["reaction_N"], [-300, 0, 200], atol=1e-3)
        kinds = {s["kind"] for s in res["singularities"]}
        self.assertNotIn("corner", kinds)                           # the inside corner is filleted
        for s in res["singularities"]:
            self.assertGreater(s["stress_there_MPa_by_refinement"][-1], res["peak_von_mises_MPa"])
            self.assertTrue(s["why"] and s["left_out_within_mm"] > 0)
        self.assertEqual([f["type"] for f in res["faces"]], ["cylinder"] * 3)
        self.assertFalse(res["hand_estimate"]["applies"])              # an L-bracket is not a prismatic bar, and says so
        self.assertIn("not slender", res["hand_estimate"]["why"])
        self.assertIn("isoparametric", res["mesh"]["element"])

    def test_4_the_field_is_what_a_viewport_can_colour(self):
        f = study.field(self.st, self.load(), self.d["id"])
        self.assertEqual(f["format"], "form.fea.field/1")
        n, t = f["vertices"], f["triangles"]
        pos = np.frombuffer(base64.b64decode(f["positions"]), "<f4").reshape(-1, 3)
        idx = np.frombuffer(base64.b64decode(f["indices"]), "<u4").reshape(-1, 3)
        self.assertEqual((len(pos), len(idx)), (n, t))
        self.assertLess(idx.max(), n)
        np.testing.assert_allclose(pos.min(axis=0), [0, 0, 0], atol=1e-3)
        np.testing.assert_allclose(pos.max(axis=0), [80, 40, 60], atol=1e-3)
        vm, disp, sf, sing = (decode(f, k) for k in ("von_mises", "displacement", "safety_factor", "singular"))
        self.assertEqual((vm.shape, disp.shape, sf.shape, sing.shape), ((n,), (n, 3), (n,), (n,)))
        res = self.r["result"]
        self.assertAlmostEqual(float(np.linalg.norm(disp, axis=1).max()), res["max_displacement_mm"], delta=0.02 * res["max_displacement_mm"])
        self.assertAlmostEqual(float(vm[sing == 0].max()), res["peak_von_mises_MPa"], delta=0.03 * res["peak_von_mises_MPa"])
        self.assertTrue(np.all(sf[vm > 1e-6] > 0))
        self.assertEqual((f["rev"], f["study"], f["frame"]), (1, self.d["id"], "as built"))

    def test_5_tools_and_cli_read_the_same_record(self):
        out = tools.read_call(self.st, self.p["id"], self.d["id"])
        self.assertEqual(out["state"]["state"], "current")
        self.assertEqual(out["result"]["headline"], self.r["result"]["headline"])
        self.assertTrue(Path(out["field_file"]).is_file())
        self.assertNotIn("field", out)
        again = tools.study_call(self.st, self.p["id"], None, self.d["id"])
        self.assertNotIn("job", again)                               # current: not solved again
        self.assertIn("force=True", again["note"])
        listing = tools.study_call(self.st, self.p["id"], None)
        self.assertEqual([s["state"] for s in listing["studies"]], ["current"])
        env = {**os.environ, "FORM_DATA": TMP, "PYTHONPATH": str(ROOT)}
        for argv in (["strength", "list", self.p["id"]], ["study", "strength", "show", self.p["id"], self.d["id"]]):
            r = subprocess.run([sys.executable, "-m", "form", *argv], capture_output=True, text=True, env=env, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stderr[-600:])
            self.assertIn(self.d["id"], json.dumps(json.loads(r.stdout)))
        b = bench.summary(self.st, self.load())
        self.assertEqual(b["state"], "current")
        self.assertIn("safety factor", b["headline"])

    def test_6_a_new_revision_makes_it_stale_and_a_rerun_makes_it_current(self):
        p = self.load()
        self.st.commit(p, {"t": 7.0}, note="thicker")
        s = study.state(self.st, self.load(), self.d["id"])
        self.assertEqual((s["state"], s["last_rev"]), ("stale", 1))
        self.assertIn("revision 1", s["why"])
        old = study.result(self.st, self.load(), self.d["id"])["result"]
        self.assertTrue(old["stale"])
        self.assertIn("stale: describes revision 1", old["evidence"])
        with self.assertRaises(StudioError):
            study.field(self.st, self.load(), self.d["id"])           # a stale field is never drawn
        self.assertEqual(bench.summary(self.st, self.load())["state"], "stale")
        new = study.run(self.st, self.p["id"], self.d["id"])
        self.assertEqual((new["state"]["state"], new["result"]["rev"]), ("current", 2))
        self.assertLess(new["result"]["max_displacement_mm"], old["max_displacement_mm"])    # thicker is stiffer
        self.assertTrue(study.run(self.st, self.p["id"], self.d["id"])["cached"])

    def test_7_a_sharp_inside_corner_is_named_and_left_out(self):
        self.st.commit(self.load(), {"r": 0.0}, note="no fillet")
        r = study.run(self.st, self.p["id"], self.d["id"])["result"]
        corner = [s for s in r["singularities"] if s["kind"] == "corner"]
        self.assertEqual(len(corner), 1)
        grow = corner[0]["stress_there_MPa_by_refinement"]
        self.assertGreater(grow[-1], 1.2 * grow[0])                  # it grows with refinement: not a number to report
        self.assertLess(r["peak_von_mises_MPa"], grow[-1])
        self.assertIn("fillet", corner[0]["why"])
        if r["converged"]:
            self.assertAlmostEqual(r["safety_factor"]["value"], 276.0 / r["peak_von_mises_MPa"], places=6)
        else:
            self.assertIsNone(r["safety_factor"])

    def test_8_a_part_that_is_not_held_is_refused_and_recorded_as_failed(self):
        d = study.define(self.st, self.load(), {**STATIC, "fixtures": [{"type": "roller", "faces": [[40, 20, 0]]}]})
        with self.assertRaises(StudioError) as cm:
            study.run(self.st, self.p["id"], d["id"])
        self.assertIn("rigid motion", str(cm.exception))
        s = study.state(self.st, self.load(), d["id"])
        self.assertEqual(s["state"], "failed")
        self.assertIn("rigid motion", s["error"]["message"])
        pin = study.define(self.st, self.load(), {**STATIC, "fixtures": [{"type": "pin", "faces": [[40, 20, 0]]}]})
        with self.assertRaises(StudioError) as cm:
            study.run(self.st, self.p["id"], pin["id"])
        self.assertIn("cylindrical face", str(cm.exception))
        off = study.define(self.st, self.load(), {**STATIC, "fixtures": [{"type": "fixed", "faces": [[40, 20, 30]]}]})
        with self.assertRaises(StudioError) as cm:
            study.run(self.st, self.p["id"], off["id"])
        self.assertIn("off the part's surface", str(cm.exception))
        for x in (d, pin, off):
            study.remove(self.st, self.load(), x["id"])

    def test_85_a_search_keeps_the_strength_constraint_on_solved_candidates(self):
        """Thickness 3 to 10 mm, lightest with a safety factor of at least 3: every feasible candidate was solved."""
        from form import lighten, optimize as opt
        self.st.commit(self.load(), {"r": 6.0, "t": 6.0}, note="fillet back")
        r = opt.run(self.st, self.load(), [{"key": "t", "min": 3, "max": 10}], {"minimize": "volume_cm3"},
                    ["fea.safety_factor >= 3"], budget=10, study=self.d["id"])
        st_ = r["strength"]
        self.assertTrue(1 <= st_["solves"] <= 8)
        self.assertIn("not steered", st_["how"])
        solved = {json.dumps(x["values"], sort_keys=True): x for x in st_["solved"]}
        self.assertFalse(solved[json.dumps({"t": 3.0})]["ok"])                 # the lightest is too weak
        if r["best"] is not None:
            win = solved[json.dumps(r["best"]["values"], sort_keys=True)]
            self.assertTrue(win["ok"])
            self.assertGreaterEqual(win["metrics"]["fea.safety_factor"], 3.0)
            self.assertGreater(r["best"]["values"]["t"], 3.0)
            self.assertRegex(win["evidence"], r"converged to")
            self.assertEqual(r["feasible"], sum(1 for x in st_["solved"] if x["ok"]))
        else:
            self.assertIn("No candidate that was solved", st_["none_why"])
        lt = lighten.search(self.st, self.load(), builds=1, require=["fea.safety_factor >= 50"], study=self.d["id"])
        self.assertEqual(lt["candidates"], [])                                   # nothing lighter is that strong
        self.assertTrue(any("fea.safety_factor >= 50" in x["why"] for x in lt["rejected"]), lt["rejected"])
        self.assertEqual(lt["require"], ["fea.safety_factor >= 50"])

    def test_87_heat_and_thermal_stress(self):
        hot = {**ALU, "k_W_mK": 167, "cte_per_K": 23.6e-6}
        th = [{"type": "temperature", "faces": [[33, 20, 3], [65, 20, 3]], "value_C": 90},
              {"type": "convection", "faces": [[3, 20, 60]], "h_W_m2K": 50, "ambient_C": 20}]
        d = study.define(self.st, self.load(), {"kind": "thermal", "material": hot, "thermal": th, "mesh": {"budget_s": LIMIT_S}})
        r = study.run(self.st, self.p["id"], d["id"])["result"]
        self.assertTrue(r["converged"], r.get("not_converged_because"))
        self.assertRegex(r["evidence"], r"^simulated \(FEA, steady heat, converged to")
        self.assertTrue(20 < r["t_min_C"] < r["t_max_C"] <= 90.0 + 1e-6)
        self.assertTrue(r["heat_balance"]["balanced"])
        by = {c["type"]: c for c in r["conditions"]}
        self.assertAlmostEqual(by["temperature"]["heat_W"], -by["convection"]["heat_W"], delta=1e-6 * abs(by["temperature"]["heat_W"]))
        self.assertGreater(by["temperature"]["heat_W"], 0)                 # heat goes in at the hot holes, out by convection
        self.assertIn("°C", r["headline"])
        f = study.field(self.st, self.load(), d["id"])
        T = decode(f, "temperature")
        self.assertAlmostEqual(float(T.max()), r["t_max_C"], delta=0.5)
        self.assertEqual(f["units"]["temperature"], "degC")
        self.assertEqual(r["materials"]["design"]["sources"]["k"]["source"], "test fixture")
        with self.assertRaises(StudioError) as cm:                       # no conductivity: refused, nothing assumed
            study.run(self.st, self.p["id"], study.define(self.st, self.load(), {"kind": "thermal", "material": ALU, "thermal": th})["id"])
        self.assertIn("thermal conductivity", str(cm.exception))
        ts = study.define(self.st, self.load(), {"kind": "thermal_stress", "material": hot, "thermal": th, "reference_C": 20,
                                                 "fixtures": STATIC["fixtures"], "mesh": {"budget_s": LIMIT_S}})
        rs = study.run(self.st, self.p["id"], ts["id"])["result"]
        self.assertEqual(rs["thermal"]["reference_C"], 20.0)
        self.assertIn("thermal stress", rs["evidence"])
        self.assertGreater(rs["peak_von_mises_MPa"], 1.0)                 # held holes fight the expansion
        self.assertIn("steady state", " ".join(rs["assumptions"]))
        self.assertIn("temperature", study.field(self.st, self.load(), ts["id"])["fields"])

    def test_9_modal_buckling_and_cancel(self):
        m = study.define(self.st, self.load(), {"kind": "modal", "material": ALU, "modes": 3,
                                                "fixtures": STATIC["fixtures"], "mesh": {"budget_s": LIMIT_S}})
        r = study.run(self.st, self.p["id"], m["id"])["result"]
        self.assertTrue(r["converged"], r.get("not_converged_because"))
        f = r["frequencies_Hz"]
        self.assertEqual(len(f), 3)
        self.assertTrue(200 < f[0] < f[1] < f[2] < 30000)
        self.assertRegex(r["evidence"], r"^simulated \(FEA, modal, converged to")
        vol = self.st._k("summary", key=self.st.keys(self.load())["geometry"], recipe_id=self.st.rid(self.load()),
                         values=self.st.rev(self.load())["values"], p=self.load())["volume_mm3"]
        self.assertAlmostEqual(r["mass_g"], 2700e-6 * vol, delta=0.01 * r["mass_g"])       # the mesh's mass is the solid's
        fld = study.field(self.st, self.load(), m["id"])
        self.assertEqual(fld["fields"]["modes"]["count"], 3)
        b = study.define(self.st, self.load(), {"kind": "buckling", "material": ALU, "modes": 2, "fixtures": STATIC["fixtures"],
                                                "loads": [{"type": "force", "faces": [[3, 20, 60]], "vector": [0, 0, -500]}],
                                                "mesh": {"budget_s": LIMIT_S}})
        rb = study.run(self.st, self.p["id"], b["id"])["result"]
        self.assertGreater(rb["load_factor"], 1.0)
        self.assertIn("buckles at", rb["headline"])
        self.assertIn("A real part buckles earlier", rb["meaning"])
        slow = study.define(self.st, self.load(), {**STATIC, "mesh": {"tol_stress": 0.001, "tol_disp": 0.0001, "budget_s": 600,
                                                                      "levels_max": 10}})
        job = study.start(self.st, self.p["id"], slow["id"])
        time.sleep(1.5)
        out = tools.read_call(self.st, self.p["id"], slow["id"], cancel=True, wait_s=20)
        self.assertTrue(out["cancelled"], out)
        self.assertEqual(self.st.jobs[job["id"]]["state"], "cancelled")
        self.assertEqual(study.state(self.st, self.load(), slow["id"])["state"], "never")     # nothing stored


@NEEDS_ENGINE
class BondedAssembly(unittest.TestCase):
    """Needs the engine. The guide's two-part box, solved assembled: the lid is bonded to the box where they touch."""

    def test_two_parts_are_solved_assembled_with_a_material_each(self):
        os.environ["FORM_DATA"] = TMP
        st = Studio(config.load())
        try:
            p = st.create_design("Asm box", EXAMPLE, purpose="model")
            # box: outer 64 x 44, height 32, floor at z = 0; the lid, flipped and placed, has its top at z = 34
            steel = {"name": "steel (test)", "E_GPa": 210, "poisson": 0.3, "yield_MPa": 250, "density_kg_m3": 7850, "source": "test"}
            d = study.define(st, p, {"kind": "static", "materials": {"box": ALU, "lid": steel},
                                     "fixtures": [{"type": "fixed", "faces": [[0, 0, 0]]}],
                                     # picked on the lid as printed: its outer face lies on the bed beside the box
                                     "loads": [{"type": "force", "faces": [[72, 0, 0]], "vector": [0, 0, -100]}],
                                     "mesh": {"budget_s": LIMIT_S, "levels_max": 4}})
            r = study.run(st, p["id"], d["id"])["result"]
            self.assertEqual(r["frame"], "assembled")
            self.assertEqual((r["mesh"]["solids"], r["mesh"]["bonded"]), (2, True))
            self.assertEqual(set(r["materials"]), {"box", "lid"})
            self.assertEqual([f["part"] for f in r["faces"]], ["box", "lid"])
            self.assertTrue(r["equilibrium"]["balanced"])
            np.testing.assert_allclose(r["equilibrium"]["reaction_N"], [0, 0, 100], atol=1e-2)
            self.assertGreater(r["max_displacement_mm"], 0)
            self.assertIn("bonded where they touch", " ".join(r["assumptions"]))
        finally:
            st.kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
