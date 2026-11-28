"""Inverse design (form/inverse): the search against analytic problems with known fronts, budgets, what may be on a
front, and, when the FEA engine's Python is there, a real search on a real design in which every reported variant
was built by the kernel and solved by the strength study.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-inverse-")
os.environ["FORM_DATA"] = TMP                      # never the owner's data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from form import config, fea  # noqa: E402
from form.inverse import bench, design, nsga2, search, tools, verify  # noqa: E402
from form.inverse.surrogate import GP, latin_hypercube  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

ENGINE = fea.python(config.load())
NEEDS_ENGINE = unittest.skipUnless(ENGINE, "the FEA engine is not installed here (set FORM_FEA_PYTHON to its Python)")

PLATE = '''"""Cantilever plate: a flat arm held at one end, loaded at the other."""
from build123d import Align, Box
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param

M = (Align.MIN, Align.MIN, Align.MIN)


class Design(FeatureDesign):
    title = "Cantilever plate"
    summary = "A flat arm held at one end and loaded at the other."
    params = [Param("length", "Length", 80, 40, 160, 1, "mm", "interface", "plate"),
              Param("height", "Height", 30, 10, 60, 1, "mm", "form", "plate"),
              Param("t", "Thickness", 5, 2, 12, 0.5, "mm", "form", "plate")]

    @feature("Plate", role="structure")
    def plate(self, v, body):
        return Box(v["length"], v["height"], v["t"], align=M)
'''
PETG = {"name": "PETG (test values)", "E_GPa": 2.0, "poisson": 0.38, "yield_MPa": 45, "density_kg_m3": 1270,
        "source": "test fixture"}
STATIC = {"kind": "static", "material": PETG, "fixtures": [{"type": "fixed", "faces": [[0, 15, 2.5]]}],
          "loads": [{"type": "force", "faces": [[80, 15, 2.5]], "vector": [0, -60, 0]}], "mesh": {"budget_s": 45}}


class KnownFronts(unittest.TestCase):
    """ZDT1 and ZDT2: the found front against the analytic one (form/inverse/verify.py states the limits)."""

    def test_the_verification_table_passes(self):
        r = verify.run()
        for c in r["cases"]:
            self.assertTrue(c["ok"], c)
            self.assertLessEqual(c["igd"], c["limit"], c)
        by = {c["case"]: c for c in r["cases"]}
        for name in ("zdt1", "zdt2"):                     # the model earns its keep: far nearer than no model
            s = by[f"{name} surrogate"]
            self.assertEqual(s["evaluations"], 80)
            self.assertGreater(s["nsga2_alone_same_evaluations_igd"], 10 * s["igd"])
        self.assertFalse(by["zdt1 constraint x1 >= 0.3"]["front_violates_constraint"])

    def test_the_found_points_lie_on_the_known_curve(self):
        fn, _front = nsga2.zdt("zdt1")
        _X, F, _G = nsga2.minimise(fn, 30, pop=100, generations=600, seed=5)
        self.assertLess(np.abs(F[:, 1] - (1 - np.sqrt(F[:, 0]))).max(), 0.03)
        self.assertLess(F[:, 0].min(), 0.02)
        self.assertGreater(F[:, 0].max(), 0.95)


class Measures(unittest.TestCase):
    def test_hypervolume_is_exact_in_two_and_three_objectives(self):
        self.assertAlmostEqual(nsga2.hypervolume(np.array([[0.0, 0.0]]), [1, 1]), 1.0)
        self.assertAlmostEqual(nsga2.hypervolume(np.array([[0.2, 0.6], [0.6, 0.2], [0.7, 0.7]]), [1, 1]), 0.48)
        self.assertAlmostEqual(nsga2.hypervolume(np.array([[0, .5, .5], [.5, 0, .5], [.5, .5, 0]]), [1, 1, 1]), 0.5)
        self.assertEqual(nsga2.hypervolume(np.array([[2.0, 2.0]]), [1, 1]), 0.0)
        with self.assertRaises(ValueError):
            nsga2.hypervolume(np.zeros((1, 4)), [1, 1, 1, 1])

    def test_a_feasible_point_dominates_an_infeasible_one(self):
        F = np.array([[1.0, 1.0], [0.1, 0.1], [0.5, 2.0]])
        self.assertEqual(nsga2.pareto_mask(F).tolist(), [False, True, False])
        self.assertEqual(nsga2.pareto_mask(F, np.array([0.0, 3.0, 0.0])).tolist(), [True, False, True])

    def test_the_surrogate_interpolates_and_knows_where_it_is_unsure(self):
        rng = np.random.default_rng(0)
        X = latin_hypercube(30, 2, rng)
        y = np.sin(4 * X[:, 0]) + X[:, 1] ** 2
        gp = GP().fit(X, y)
        m, s = gp.predict(X)
        self.assertLess(np.abs(m - y).max(), 1e-3)
        Z = rng.random((200, 2))
        mz, sz = gp.predict(Z)
        self.assertLess(np.abs(mz - (np.sin(4 * Z[:, 0]) + Z[:, 1] ** 2)).mean(), 0.05)
        self.assertGreater(gp.predict(np.array([[3.0, 3.0]]))[1][0], 5 * s.max())      # far from every point


class Budgets(unittest.TestCase):
    def _problem(self):
        fn, _ = nsga2.zdt("zdt1")
        calls = []

        def ev(X):
            calls.append(len(X))
            F, _ = fn(X)
            return [{"x": x, "f": f.tolist(), "g": []} for x, f in zip(X, F)]
        return ev, calls

    def test_the_evaluation_limit_is_never_passed(self):
        for n in (7, 20, 33):
            ev, calls = self._problem()
            out = search.run(ev, 3, 2, evals=n, batch=4, seed=1)
            self.assertLessEqual(sum(calls), n)
            self.assertEqual(out["evaluations"], len(out["rows"]))
            self.assertLessEqual(out["evaluations"], n)
            self.assertEqual(out["history"][-1]["evaluations"], out["evaluations"])

    def test_stop_ends_the_search_and_what_was_evaluated_is_kept(self):
        ev, calls = self._problem()
        out = search.run(ev, 3, 2, evals=200, batch=4, seed=1, stop=lambda: sum(calls) >= 16)
        self.assertLess(out["evaluations"], 40)
        self.assertGreaterEqual(out["evaluations"], 8)
        self.assertTrue(out["front"].any())

    def test_an_evaluator_that_runs_out_stops_the_search(self):
        fn, _ = nsga2.zdt("zdt1")
        left = [10]

        def ev(X):
            rows = []
            for x in X:
                if left[0] <= 0:
                    break
                left[0] -= 1
                rows.append({"x": x, "f": fn(x[None, :])[0][0].tolist(), "g": []})
            return rows
        out = search.run(ev, 3, 2, evals=60, seed=1)
        self.assertEqual(out["evaluations"], 10)

    def test_failed_and_infeasible_evaluations_are_kept_and_never_on_the_front(self):
        fn, _ = nsga2.zdt("zdt1")

        def ev(X):
            F, _ = fn(X)
            return [{"x": x, "f": None if x[1] > 0.8 else f.tolist(), "g": [x[0] - 0.6]} for x, f in zip(X, F)]
        out = search.run(ev, 3, 2, n_con=1, evals=40, seed=3)
        self.assertTrue((~out["ok"]).any())
        self.assertTrue((out["ok"] & ~out["feasible"]).any())
        self.assertTrue(out["front"].any())
        self.assertTrue((out["X"][out["front"]][:, 0] <= 0.6 + 1e-9).all())
        self.assertTrue((out["X"][out["front"]][:, 1] <= 0.8).all())
        self.assertFalse((out["front"] & ~out["feasible"]).any())


class Requests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Request plate", PLATE, "", purpose="model")["id"]

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()

    def test_a_request_is_checked_against_the_design(self):
        st, p = self.st, self.st.load(self.pid)
        o = design.clean(st, p, {"minimize": ["mass_g", "overhang_mm2"]})
        self.assertEqual([a["key"] for a in o["vary"]], ["height", "t"])              # the interface length is left alone
        self.assertIn("the search", o["vary_chosen_by"])
        self.assertEqual(o["budget"]["evaluations"], design.KERNEL_ONLY_EVALS)
        for body, word in (({}, "one to three objectives"),
                           ({"minimize": ["a", "b", "c", "d"]}, "one to three objectives"),
                           ({"minimize": ["mass_g"], "vary": [{"key": "nope"}]}, "Unknown parameter"),
                           ({"minimize": ["mass_g"], "vary": [{"key": "t", "min": 9, "max": 3}]}, "range is empty"),
                           ({"minimize": ["mass_g"], "require": ["mass_g about 3"]}, "Cannot read constraint"),
                           ({"minimize": ["mass_g"], "speed": 3}, "Unknown field"),
                           ({"minimize": ["fea.safety_factor"]}, "no static strength study"),
                           ({"minimize": ["fea.stiffness"]}, "Unknown strength metric"),
                           ({"minimize": ["cost"]}, "No rate is made up")):
            with self.assertRaises(StudioError, msg=str(body)) as cm:
                design.clean(st, p, body)
            self.assertIn(word, str(cm.exception) + " " + cm.exception.hint)
        o = design.clean(st, p, {"minimize": ["cost"], "rates": {"per_kg": 25}})
        self.assertIn("assumed", o["rates"]["evidence"])

    def test_a_search_on_kernel_metrics_reports_only_built_points(self):
        st = self.st
        rec = design.run(st, self.pid, {"minimize": ["mass_g"],
                                        "require": ["volume_cm3 >= 4"], "budget": {"evaluations": 14, "seconds": 120}})
        self.assertLessEqual(rec["budget"]["evaluations"], 14)
        self.assertEqual(rec["budget"]["builds_failed"], 0)
        self.assertIsNone(rec["budget"]["strength_solves_limit"])
        self.assertIn("assumed", rec["density"]["source"])                            # no material: said, not hidden
        self.assertEqual(len(rec["front"]), 1)                                        # one objective: one best
        best = rec["points"][rec["front"][0]]
        self.assertGreaterEqual(best["metrics"]["volume_cm3"], 4)
        self.assertLess(best["metrics"]["volume_cm3"], 5.5)                           # near the bound, from above
        self.assertTrue(all(pt["ok"] and pt["metrics"]["mass_g"] > 0 for pt in rec["points"]))
        self.assertIn("approximate", rec["approximate"])
        ch = rec["chart"]
        self.assertEqual(len(ch["points"]), len(rec["points"]))
        self.assertEqual({q["state"] for q in ch["points"]} - {"front", "feasible", "misses"}, set())
        self.assertEqual(ch["axes"][0], {"metric": "mass_g", "label": "Mass", "unit": "g", "better": "lower"})
        self.assertEqual(rec["points"][rec["current"]]["values"], {"height": 30.0, "t": 5.0})
        # stored, read back, and its Bench entry
        p = st.load(self.pid)
        self.assertEqual(design.get(st, p)["id"], rec["id"])
        d = tools.digest(design.get(st, p))
        self.assertEqual(len(d["front"]), 1)
        self.assertIn("save_variant", d["front"][0]["keep"])
        from form import studies
        e = studies.show(st, p, bench.INVERSE)
        self.assertEqual((e["state"], e["chapter"]), ("current", "design"))
        self.assertIn("1 variant on the front", e["headline"])
        v = design.save_point(st, self.pid, rec["id"], rec["front"][0], "Lightest")
        self.assertEqual(v["name"], "Lightest")
        self.assertEqual(st.load(self.pid)["variants"][0]["values"]["t"], best["values"]["t"])
        # the terminal reads the same stored search, as JSON
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        out = subprocess.run([sys.executable, "-m", "form", "optimize", "pareto", self.pid, "--show", "--full"],
                             capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        shown = json.loads(out.stdout)
        self.assertEqual((shown["state"], shown["result"]["id"]), ("current", rec["id"]))
        self.assertEqual(len(shown["result"]["chart"]["points"]), len(rec["points"]))

    def test_cost_per_part_is_an_objective_labelled_as_its_rates_are(self):
        """form/costing's models on each candidate: computed from its own volume and box, never the head's slice."""
        from form import costing
        st, p = self.st, self.st.load(self.pid)
        for body, word in (({"minimize": ["cost.per_part"], "costing": {"process": "injection"}}, "cannot be costed per candidate"),
                           ({"minimize": ["cost.total"]}, "cost.per_part"),
                           ({"minimize": ["mass_g"], "costing": {"quantity": 10}}, "no objective or requirement"),
                           ({"minimize": ["cost.per_part"], "costing": {"speed": 1}}, "Unknown costing field")):
            with self.assertRaises(StudioError, msg=str(body)) as cm:
                design.clean(st, p, body)
            self.assertIn(word, str(cm.exception) + " " + cm.exception.hint)
        # the candidate's numbers, not the head's: a candidate twice the volume costs more by FDM
        small = costing.point(st, p, "fdm", 10, candidate={"volume_mm3": 5000, "size": [40, 30, 5]})
        big = costing.point(st, p, "fdm", 10, candidate={"volume_mm3": 10000, "size": [40, 30, 10]})
        self.assertGreater(big["value"], small["value"])
        self.assertIn("assumed", small["evidence"])
        with self.assertRaises(StudioError):
            costing.estimate(st, p, "sheet_metal", [10], candidate={"volume_mm3": 5000, "size": [40, 30, 5]})
        f = costing.objective("fdm", 10)
        self.assertEqual(f(st, p, {"volume_mm3": 5000, "size": [40, 30, 5]}), small["value"])
        rec = design.run(st, self.pid, {"minimize": ["mass_g", "cost.per_part"], "costing": {"process": "fdm", "quantity": 10},
                                        "budget": {"evaluations": 8, "seconds": 120}})
        ax = rec["chart"]["axes"][1]
        self.assertEqual(ax["metric"], "cost.per_part")
        self.assertTrue(ax["unit"].endswith("/part"))
        cost_ax = rec["objectives"][1]
        self.assertIn("assumed", cost_ax["evidence"])                                  # the rates' own classes
        self.assertIn("computed volume and bounding box", cost_ax["evidence"])
        for pt in rec["points"]:
            if pt["ok"]:
                self.assertGreater(pt["metrics"]["cost.per_part"], 0)
                self.assertEqual(pt["cost"]["process"], "fdm")
        self.assertEqual(rec["costing"]["quantity"], 10)

    def test_the_tools_are_registered_and_the_listing_names_what_can_vary(self):
        from form import mcp_server
        by = {t.name: t for t in asyncio.run(mcp_server.build().list_tools())}
        for name in ("inverse_design", "get_inverse_design"):
            self.assertIn(name, by)
        text = " ".join(by["inverse_design"].description.split())
        for word in ("Pareto front", "every reported point was built", "approximate", "budget"):
            self.assertIn(word, text)
        out = tools.search_call(self.st, self.pid, None)
        self.assertEqual([k["key"] for k in out["knobs"]], ["height", "t"])
        chk = tools.search_call(self.st, self.pid, {"minimize": ["mass_g"]}, run_now=False)
        self.assertEqual(chk["note"], "Checked, not run.")

    def test_the_terminal_runs_the_verification_and_says_how_it_is_used(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        out = subprocess.run([sys.executable, "-m", "form", "optimize", "pareto", "--verify"], capture_output=True, text=True,
                             cwd=ROOT, env=env)
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        self.assertTrue(json.loads(out.stdout)["passed"])
        out = subprocess.run([sys.executable, "-m", "form", "optimize", "pareto", "no-such-design", "--minimize", "mass_g"],
                             capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(out.returncode, 1)
        self.assertIn("error", json.loads(out.stdout))


class OverMCP(unittest.TestCase):
    """The five tools called through a real MCP session over stdio (a search on kernel metrics needs no engine)."""

    def test_the_tools_answer_over_stdio(self):
        st = Studio(config.load())
        try:
            pid = st.create_design("MCP plate", PLATE, "", purpose="model")["id"]
        finally:
            st.kernel.shutdown()
        asyncio.run(self._session(pid))

    async def _session(self, pid):
        from mcp import Client, StdioServerParameters

        def data(res):
            sc = res.structured_content
            if isinstance(sc, dict):
                return sc.get("result", sc)
            return json.loads(next(x.text for x in res.content if x.type == "text"))
        # the folder this process is using now (another test module may have pointed FORM_DATA at its own)
        env = {**os.environ, "FORM_DATA": str(config.load()["data"]["dir"]), "PYTHONPATH": str(ROOT)}
        params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env, cwd=str(ROOT))
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            self.assertTrue({"inverse_design", "get_inverse_design", "topology_optimise", "get_topology", "apply_topology"} <= names)
            listing = data(await c.call_tool("inverse_design", {"project": pid}))
            self.assertEqual((listing["runs"], [k["key"] for k in listing["knobs"]]), ([], ["height", "t"]))
            started = data(await c.call_tool("inverse_design", {"project": pid, "minimize": ["mass_g"],
                                                               "require": ["volume_cm3 >= 4"], "budget": {"evaluations": 8}}))
            self.assertEqual(started["state"], "running")
            got = {}
            for _ in range(20):
                got = data(await c.call_tool("get_inverse_design", {"project": pid, "wait_s": 30}))
                if got.get("state") != "running":
                    break
            self.assertEqual(got["state"], "current", got)
            self.assertEqual(len(got["result"]["front"]), 1)
            self.assertLessEqual(got["result"]["budget"]["evaluations"], 8)
            idx = got["result"]["front"][0]["index"]
            kept = data(await c.call_tool("inverse_design", {"project": pid, "save_point": idx, "name": "Kept"}))
            self.assertEqual(kept["name"], "Kept")
            self.assertEqual(data(await c.call_tool("get_inverse_design", {"project": pid, "run": got["result"]["id"],
                                                                         "wait_s": 0, "full": True}))["result"]["chart"]["front"], [idx])
            topo = data(await c.call_tool("topology_optimise", {"project": pid}))
            self.assertEqual((topo["runs"], topo["settings"]["volfrac"]["default"]), ([], 0.5))
            self.assertEqual(data(await c.call_tool("get_topology", {"project": pid, "wait_s": 0}))["state"], "never")
            refused = await c.call_tool("topology_optimise", {"project": pid, "volfrac": 0.5})
            self.assertTrue(refused.is_error)                                 # no strength study: said, nothing run
            self.assertIn("no static strength study", refused.content[0].text)
            self.assertTrue((await c.call_tool("apply_topology", {"project": pid})).is_error)


@NEEDS_ENGINE
class RealSearch(unittest.TestCase):
    """Survive 60 N with a safety factor of 3, as light and as stiff as possible: every variant built and solved."""

    @classmethod
    def setUpClass(cls):
        from form.fea import study
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Search plate", PLATE, "", purpose="model")["id"]
        cls.sid = study.define(cls.st, cls.st.load(cls.pid), STATIC)["id"]
        cls.rec = design.run(cls.st, cls.pid, {
            "minimize": ["mass_g", "fea.max_displacement_mm"], "require": ["fea.safety_factor >= 3"],
            "vary": [{"key": "height", "min": 12, "max": 40}, {"key": "t", "min": 2, "max": 10}],
            "budget": {"solves": 10, "seconds": 400}})

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()

    def test_the_budget_is_kept_and_stated(self):
        b = self.rec["budget"]
        self.assertLessEqual(b["strength_solves"], 10)
        self.assertEqual(b["strength_solves_limit"], 10)
        self.assertLessEqual(b["evaluations"], b["strength_solves"])
        self.assertLess(b["wall_seconds"], 400 + 60)
        self.assertTrue(b["stopped"])

    def test_every_variant_on_the_front_was_built_and_solved_and_meets_the_requirement(self):
        rec = self.rec
        self.assertGreaterEqual(len(rec["front"]), 2)
        for i in rec["front"]:
            pt = rec["points"][i]
            self.assertTrue(pt["ok"] and pt["feasible"] and not pt["violations"], pt)
            self.assertIn("simulated (FEA, linear static, converged", pt["fea"]["evidence"])
            self.assertGreaterEqual(pt["metrics"]["fea.safety_factor"], 3.0)
            self.assertLessEqual(pt["fea"]["safety_factor"]["low"], pt["fea"]["safety_factor"]["value"])
            self.assertAlmostEqual(pt["metrics"]["mass_g"], pt["metrics"]["volume_cm3"] * 1.27, places=4)
        self.assertIn("PETG", rec["density"]["source"])

    def test_the_front_is_a_trade_off_and_nothing_dominated_is_on_it(self):
        rec = self.rec
        fr = [rec["points"][i]["metrics"] for i in rec["front"]]
        mass = [m["mass_g"] for m in fr]
        disp = [m["fea.max_displacement_mm"] for m in fr]
        self.assertEqual(mass, sorted(mass))
        self.assertEqual(disp, sorted(disp, reverse=True))                            # lighter is less stiff
        for pt in rec["points"]:
            if pt["feasible"] and not pt["on_front"]:
                m = pt["metrics"]
                self.assertTrue(any(a <= m["mass_g"] and b <= m["fea.max_displacement_mm"] for a, b in zip(mass, disp)), pt)

    def test_points_that_miss_say_why_and_are_shown(self):
        rec = self.rec
        miss = [pt for pt in rec["points"] if pt["ok"] and not pt["feasible"]]
        for pt in miss:
            self.assertTrue(pt["violations"], pt)
            self.assertFalse(pt["on_front"])
        states = {q["index"]: q["state"] for q in rec["chart"]["points"]}
        self.assertEqual(len(states), len(rec["points"]))
        for pt in miss:
            self.assertIn(states[pt["index"]], ("misses", "close"))


if __name__ == "__main__":
    unittest.main()
