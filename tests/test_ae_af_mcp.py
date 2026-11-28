"""Waves AE and AF over MCP (stdio, the server an agent launches) and from the terminal: the four tools answer with the
same JSON the modules compute, and what they build is a design.

    lattice_properties   a cell's numbers, nothing saved
    lattice_fill         a lattice in a design: a revision, read back, removed
    linkage_synthesis    three poses to a four-bar, checked and simulated
    photo_profile        a synthetic photo with a card to a dimensioned sketch

Tests use their own FORM_DATA, never the owner's data."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

BLOCK = '''from build123d import Box
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Block"
    summary = "A block to fill."
    params = [Param("w", "Width", 18, 10, 80, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["w"], 18, 18))]
'''
POSES = [{"at": [0, 0], "angle": 0}, {"at": [30, 20], "angle": 20}, {"at": [60, 15], "angle": 45}]


def body(res) -> dict:
    sc = res.structured_content
    if isinstance(sc, dict):
        return sc.get("result", sc)
    return json.loads(next(x.text for x in res.content if x.type == "text"))


class OverMCP(unittest.TestCase):
    def test_tools(self):
        asyncio.run(self._session())

    async def _session(self):
        from mcp import Client, StdioServerParameters
        import test_phototrace as photos
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(ROOT)}
            params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env, cwd=str(ROOT))
            async with Client(params) as c:
                tools = {t.name: t for t in (await c.list_tools()).tools}
                self.assertTrue({"lattice_properties", "lattice_fill", "linkage_synthesis", "photo_profile"} <= set(tools))
                self.assertTrue(tools["lattice_properties"].annotations.read_only_hint)

                r = body(await c.call_tool("lattice_properties", {"kind": "gyroid", "cell": 8, "density": 0.2, "process": "sla", "skin": 1.0}))
                self.assertAlmostEqual(r["relative_density"]["value"], 0.2, delta=0.004)
                self.assertEqual(r["stiffness"]["evidence"], "computed (scaling law)")
                self.assertEqual(r["printability"]["process"], "sla")
                self.assertIn("gyroid", [x["kind"] for x in body(await c.call_tool("lattice_properties", {}))["tpms"]])
                bad = await c.call_tool("lattice_properties", {"kind": "gyroid", "cell": 8})
                self.assertTrue(bad.is_error)

                made = body(await c.call_tool("create_design", {"name": "Block", "source": BLOCK, "purpose": "model", "refine": "off"}))
                pid = made["project"]["id"] if isinstance(made.get("project"), dict) else made["project"]
                f = body(await c.call_tool("lattice_fill", {"project": pid, "kind": "bcc", "cell": 8, "strut_d": 1.2, "skin": 1.0, "process": "sls"}))
                self.assertEqual(f["plan"]["output"], "brep")
                self.assertIn("exact B-rep", f["built"]["representation"])
                self.assertEqual(f["built"]["trapped_voids"], 1)
                self.assertAlmostEqual(f["built"]["relative_density_measured"], f["relative_density"]["value"], delta=0.01)
                again = body(await c.call_tool("lattice_fill", {"project": pid}))
                self.assertEqual(again["spec"]["kind"], "bcc")
                studies = body(await c.call_tool("list_studies", {"project": pid}))
                entry = next(e for e in studies["entries"] if e["id"] == "lattice")
                self.assertEqual(entry["state"], "current")
                gone = body(await c.call_tool("lattice_fill", {"project": pid, "remove": True}))
                self.assertEqual(gone["removed"]["kind"], "bcc")

                k = body(await c.call_tool("linkage_synthesis", {"mode": "motion", "poses": POSES, "require_crank": True}))
                self.assertEqual(k["verification"]["status"], "PASS")
                self.assertLess(k["verification"]["max_point_error_mm"], 1e-4)
                self.assertTrue(k["checks"]["crank_turns_fully"])
                self.assertNotIn("link", k)
                self.assertIn("motion", body(await c.call_tool("linkage_synthesis", {}))["modes"])

                photo = photos.save("mcp_card")
                ph = body(await c.call_tool("photo_profile", {"photo": photo}))
                self.assertEqual(ph["evidence"], "estimated from the photo")
                self.assertEqual(ph["sketch_solves"], {"ok": True, "closed": True, "loops": 2, "degrees_of_freedom": 0})
                w = next(x for x in ph["dimensions"] if x["kind"] == "overall width")
                self.assertLessEqual(abs(w["value_mm"] - 60.0), w["uncertainty_mm"])
                self.assertNotIn("outline_mm", ph)
                none = await c.call_tool("photo_profile", {"photo": str(Path(d) / "missing.png")})
                self.assertTrue(none.is_error)


class Terminal(unittest.TestCase):
    def run_cli(self, *args):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(ROOT)}
            p = subprocess.run([sys.executable, "-m", "form", *args], capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=300)
        return p.returncode, json.loads(p.stdout) if p.stdout.strip() else {}

    def test_lattice_linkage_photo(self):
        import test_phototrace as photos
        rc, out = self.run_cli("lattice", "props", "octet", "cell=8", "strut_d=1.0", "material=AL-6061", "process=sls", "--verify")
        self.assertEqual(rc, 0)
        self.assertEqual(out["stiffness"]["class"], "octet")
        self.assertTrue(out["verification"]["available"])
        rc, out = self.run_cli("lattice", "props", "honeycomb", "cell=8", "density=0.2")
        self.assertEqual(rc, 2)
        self.assertIn("error", out)
        rc, out = self.run_cli("linkage", "function", "--pairs", "[[40, 70], [60, 85], [85, 110]]", "--ground", "100")
        self.assertEqual(rc, 0)
        self.assertEqual(out["verification"]["status"], "PASS")
        rc, out = self.run_cli("linkage", "motion", "--poses", "[]")
        self.assertEqual(rc, 2)
        rc, out = self.run_cli("photo-profile", photos.save("cli_coin", ref="coin", s=7.0), "--coin", "eur_1")
        self.assertEqual(rc, 0)
        self.assertEqual(out["scale"]["kind"], "coin")
        self.assertEqual(out["sketch_solves"]["degrees_of_freedom"], 0)


if __name__ == "__main__":
    unittest.main()
