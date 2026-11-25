"""The residual loop of a remodel (form/remodel/residual.py, fitparams.py) and its MCP tools.

- A bracket that lacks its 4 holes: the residual lists 4 bodies at the holes' centres (within 0.2 mm), as a grid.
- Bolt holes on a circle read as one polar pattern at equal angles.
- fit_params recovers a Param perturbed by 0.3 mm and never makes the deviation worse.
- A scripted remodel (tests/fixtures/scripted_agent.py, RemodelAgent) reaches 0.1 mm in fewer MCP calls with the
  residual tools than with compare_to_reference alone; both counts are printed.
"""
import asyncio
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="form-residual-")


def _A():
    from build123d import Align
    return (Align.CENTER, Align.CENTER, Align.MIN)


def mesh(shape):
    vs, ts = shape.tessellate(0.01, 0.1)
    return np.array([[v.X, v.Y, v.Z] for v in vs]), np.array(ts, dtype=np.int64)


HOLES = [(-22.0, -12.0), (-22.0, 12.0), (22.0, -12.0), (22.0, 12.0)]


def bracket(holes=True, bosses=False):
    from build123d import Box, Cylinder, Pos
    b = Box(60, 40, 5, align=_A())
    for x, y in HOLES:
        if holes:
            b = b - Pos(x, y, -1) * Cylinder(2.5, 7, align=_A())
        if bosses:
            b = b + Pos(x, y, 5) * Cylinder(3, 4, align=_A())
    return b


def flange(n=6, start=15.0, d=5.5):
    from build123d import Cylinder, Pos, Rot
    b = Cylinder(30, 6, align=_A()) - Cylinder(6, 30)
    for i in range(n):
        b = b - Rot(0, 0, start + i * 360 / n) * Pos(22, 0, -1) * Cylinder(d / 2, 8, align=_A())
    return b


class Residual(unittest.TestCase):
    def _both(self, ref, des):
        """The residual with manifold3d's exact volumes (when installed) and with voxels only."""
        from form.remodel import residual as rr
        out = [rr.residual(*mesh(ref), *mesh(des))]
        with mock.patch.object(rr, "_exact_parts", lambda *a: None):
            out.append(rr.residual(*mesh(ref), *mesh(des)))
        self.assertEqual(out[1]["volume_method"], "voxels")
        return out

    def test_bracket_without_its_holes_lists_four_bodies_at_the_holes(self):
        for r in self._both(bracket(holes=True), bracket(holes=False)):
            self.assertEqual(r["missing"], [])
            self.assertEqual(len(r["extra"]), 4, r["work_list"])          # the design has material where the holes go
            got = sorted(tuple(b["centre"][:2]) for b in r["extra"])
            for (x, y), (gx, gy) in zip(sorted(HOLES), got):
                self.assertLess(math.hypot(gx - x, gy - y), 0.2)
            for b in r["extra"]:
                self.assertAlmostEqual(b["centre"][2], 2.5, delta=0.2)
                self.assertEqual(b["shape"], "cylinder")
                self.assertEqual(b["axis_name"], "z")
                self.assertAlmostEqual(b["diameter_mm"], 5.0, delta=0.2)
                self.assertAlmostEqual(b["volume_mm3"], math.pi * 2.5 ** 2 * 5, delta=0.06 * math.pi * 2.5 ** 2 * 5)
            pat = r["patterns"]
            self.assertEqual(len(pat), 1)
            self.assertEqual(pat[0]["type"], "grid")
            self.assertEqual(pat[0]["pitch_mm"], {"x": 44.0, "y": 24.0})
            self.assertTrue(r["work_list"][0].startswith("cut 4 x cylinder"))

    def test_bracket_without_its_bosses_lists_four_missing_bodies(self):
        for r in self._both(bracket(holes=False, bosses=True), bracket(holes=False)):
            self.assertEqual(r["extra"], [])
            self.assertEqual(len(r["missing"]), 4, r["work_list"])
            got = sorted(tuple(b["centre"]) for b in r["missing"])
            for (x, y), c in zip(sorted(HOLES), got):
                self.assertLess(np.linalg.norm(np.subtract(c, (x, y, 7.0))), 0.2)
            self.assertTrue(r["work_list"][0].startswith("add 4 x cylinder"))

    def test_polar_pattern_reads_as_equal_angles(self):
        from build123d import Cylinder
        plain = Cylinder(30, 6, align=_A()) - Cylinder(6, 30)
        for n, start in ((6, 15.0), (5, 0.0)):
            for r in self._both(flange(n, start), plain):
                self.assertEqual(len(r["extra"]), n)
                ang = sorted(b["angle_deg"] for b in r["extra"])
                gaps = np.diff(ang + [ang[0] + 360])
                self.assertLess(float(np.abs(gaps - 360 / n).max()), 0.5, ang)
                for b in r["extra"]:
                    self.assertAlmostEqual(b["radius_mm"], 22.0, delta=0.2)
                p = r["patterns"][0]
                self.assertEqual((p["type"], p["count"], p["full_circle"]), ("polar", n, True))
                self.assertAlmostEqual(p["pitch_deg"], 360 / n, delta=0.01)
                self.assertAlmostEqual(p["start_deg"], start, delta=0.5)
                self.assertAlmostEqual(p["radius_mm"], 22.0, delta=0.2)
                self.assertIn("polar pattern", r["work_list"][0])

    def test_same_solid_has_no_body(self):
        from form.remodel import residual as rr
        r = rr.residual(*mesh(bracket()), *mesh(bracket()))
        self.assertEqual(r["missing"] + r["extra"], [])
        self.assertLess(r["residual_pct"], 0.5)


class GenericFit(unittest.TestCase):
    def test_recovers_and_never_returns_worse(self):
        from form.remodel.fitparams import fit
        target = np.array([3.0, -1.0])
        f = lambda x: np.r_[x - target, 0.1 * (x[0] - target[0]) * (x[1] - target[1])]
        res = fit(f, [3.3, -0.7], [0, -5], [10, 5], [0.01, 0.01])
        self.assertLess(np.abs(res["x"] - target).max(), 1e-3)
        flat = fit(lambda x: np.array([1.0, 1.0]), [2.0], [0], [4], [0.05])  # nothing to gain: stays put
        self.assertEqual(float(flat["x"][0]), 2.0)


FLANGE_SRC = '''
from build123d import *
from form.recipes.base import Feature, Param, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Flange"
    summary = "fit_params test"
    params = [Param("t", "Thickness", 6.3, 3, 12, 0.1, "mm", "form", "disc"),
              Param("hole_d", "Bolt hole", 5.5, 2, 9, 0.1, "mm", "form", "holes")]
    features = [Feature("disc", "Disc", "structure"), Feature("holes", "Bolt holes", "interface")]

    def build(self, v):
        b = Cylinder(30, v["t"], align=A) - Cylinder(6, 30)
        out = [Stage("disc", b)]
        for i in range(6):
            b = b - Rot(0, 0, 15 + i * 60) * Pos(22, 0, -1) * Cylinder(v["hole_d"] / 2, v["t"] + 2, align=A)
        out.append(Stage("holes", b))
        return out
'''


class FitParams(unittest.TestCase):
    """fit_params through the Studio and the kernel worker."""

    @classmethod
    def setUpClass(cls):
        from build123d import export_stl
        os.environ["FORM_DATA"] = str(Path(TMP) / "data")
        os.environ["FORM_REFINE"] = "off"     # automatic refinement would move the head under fit_params
        cls.stl = Path(TMP) / "flange.stl"
        export_stl(flange(), str(cls.stl), tolerance=0.005, angular_tolerance=0.1)
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_recovers_a_perturbed_param_and_never_worsens(self):
        from form.remodel import fitparams as fp
        from form.remodel import project as rp
        from form.remodel import residual as rr
        st = self.st
        d = st.create_design("Flange fit", FLANGE_SRC, references=[str(self.stl)])
        p = st.load(d["id"])
        before = rp.compare_to_reference(st, p, "flange")["hausdorff_mm"]
        self.assertAlmostEqual(before, 0.3, delta=0.02)                    # t is 6.3, the mesh is 6.0
        res = rr.reference_residual(st, p, "flange")
        self.assertEqual(res["missing"] + res["extra"], [], res["work_list"])  # sizes, not shapes: nothing to add
        out = fp.fit_design(st, p, "flange")
        self.assertTrue(out["kept"], out)
        self.assertTrue(out["committed"])
        self.assertAlmostEqual(out["to"]["t"], 6.0, delta=0.02)
        self.assertAlmostEqual(out["to"]["hole_d"], 5.5, delta=0.05)
        self.assertLessEqual(out["deviation_after"]["max_mm"], out["deviation_before"]["max_mm"])
        p = st.load(d["id"])
        self.assertEqual(p["head"], out["rev"])
        self.assertEqual(st.rev(p)["provenance"]["t"]["source"], "mesh")
        after = rp.compare_to_reference(st, p, "flange")["hausdorff_mm"]
        self.assertLess(after, 0.05)
        self.assertLessEqual(after, before)
        # nothing left to gain: no new revision, the values stay
        again = fp.fit_design(st, p, "flange")
        self.assertFalse(again["kept"], again)
        self.assertEqual(st.load(d["id"])["head"], p["head"])
        self.assertLessEqual(again["deviation_after"]["max_mm"], again["deviation_before"]["max_mm"])
        # a shape the Params cannot reach (holes moved off the circle): never worse than it started
        st.commit(st.load(d["id"]), {"hole_d": 2.0}, origin="test")
        p = st.load(d["id"])
        worse = fp.fit_design(st, p, "flange", params=["t"], max_change=0.5)
        self.assertLessEqual(worse["deviation_after"]["max_mm"], worse["deviation_before"]["max_mm"])
        self.assertLessEqual(worse["deviation_after"]["mean_mm"], worse["deviation_before"]["mean_mm"])
        from form.studio import StudioError
        with self.assertRaises(StudioError):
            fp.fit_design(st, p, "flange", params=["no_such_param"])


class ScriptedRemodel(unittest.TestCase):
    """The flange remodel replayed over a real MCP stdio server, with and without the residual tools."""

    def test_residual_reaches_tolerance_in_fewer_calls(self):
        from build123d import export_stl
        from mcp import Client, StdioServerParameters
        from tests.fixtures.scripted_agent import REMODEL_TOL, RemodelAgent, flange_reference
        ref = Path(TMP) / "replay" / "flange.stl"
        ref.parent.mkdir(parents=True, exist_ok=True)
        export_stl(flange_reference(), str(ref), tolerance=0.005, angular_tolerance=0.1)
        env = {**os.environ, "FORM_DATA": str(Path(TMP) / "replay-data"), "FORM_REFINE": "off", "PYTHONPATH": str(ROOT), "FORM_SKIP_UI": "1"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env,
                                       cwd=str(ROOT))

        async def go():
            async with Client(params) as c:
                names = {t.name for t in (await c.list_tools()).tools}
                self.assertTrue({"reference_residual", "fit_params"} <= names)

                async def call(tool, args):
                    res = await c.call_tool(tool, args)
                    texts = [x.text for x in res.content if getattr(x, "type", "") == "text"]
                    if res.is_error:
                        return False, {"text": " ".join(texts)}
                    for t in reversed(texts):
                        try:
                            return True, json.loads(t)
                        except ValueError:
                            pass
                    return True, {"text": " ".join(texts)}
                agent = RemodelAgent(call)
                return await agent.run(str(ref), residual=False), await agent.run(str(ref), residual=True)
        without, with_res = asyncio.run(go())
        print(f"\nscripted remodel to {REMODEL_TOL} mm: compare only {without['n_calls']} calls "
              f"(Hausdorff {without['hausdorff']}), with the residual {with_res['n_calls']} calls "
              f"(Hausdorff {with_res['hausdorff']})", flush=True)
        (Path(TMP) / "replay.json").write_text(json.dumps({"without": without, "with": with_res}, indent=1))
        self.assertTrue(with_res["reached"], with_res)
        self.assertTrue(without["reached"], without)
        self.assertLess(with_res["n_calls"], without["n_calls"])


if __name__ == "__main__":
    unittest.main()
