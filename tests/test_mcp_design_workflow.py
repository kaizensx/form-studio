"""The staged design workflow over real MCP stdio: guide topics, examples, brief, plan, a refused unplanned complex
design, create_design with its sheet and section, critique, and the release gate."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


def texts(res):
    return [c.text for c in res.content if getattr(c, "type", "") == "text"]


def images(res):
    return [c for c in res.content if getattr(c, "type", "") == "image"]


def data(res):
    if res.structured_content is not None:
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(texts(res)[0])


class StagedWorkflow(unittest.TestCase):
    def test_session(self):
        asyncio.run(self._session())

    async def _session(self):
        sys.path.insert(0, str(ROOT))
        from form import exemplars
        src = exemplars.get("knurled_knob")["source"]
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(ROOT)}
            params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"],
                                           env=env, cwd=str(ROOT))
            async with Client(params) as c:
                tools = {t.name for t in (await c.list_tools()).tools}
                self.assertTrue({"design_brief", "plan_design", "design_examples", "critique"} <= tools)
                g = data(await c.call_tool("design_guide", {}))
                self.assertIn("example_source", g)
                self.assertIn("mechanisms", g["topics"])
                t = data(await c.call_tool("design_guide", {"topic": "texture"}))
                self.assertIn("MeshTexture", t["guide"])
                ex = data(await c.call_tool("design_examples", {"query": "helmet texture"}))
                self.assertEqual(ex["examples"][0]["name"], "helmet")
                one = data(await c.call_tool("design_examples", {"name": "planetary_gearbox"}))
                self.assertIn("craft.planetary", one["source"])

                refused = await c.call_tool("create_design", {"name": "Knurled knob", "source": src,
                                                              "brief": "a knurled knob", "run": False})
                self.assertTrue(refused.is_error)
                self.assertIn("design_brief", texts(refused)[0])

                b = data(await c.call_tool("design_brief", {"name": "Knurled knob", "goal": "A knurled knob for a 6 mm "
                                                            "D-shaft", "unknowns": ["panel thickness"]}))
                self.assertTrue(b["complex"])
                self.assertIn("knurled_knob", [e["name"] for e in b["examples"]])
                feats = [{"id": f, "label": f, "how": "see exemplar"} for f in ("skirt", "grip", "cap", "pointer", "bore")]
                pl = data(await c.call_tool("plan_design", {"brief": b["brief"], "features": feats,
                                                            "risks": ["knurl too fine"]}))
                self.assertEqual(len(pl["plan"]["features"]), 5)
                res = await c.call_tool("create_design", {"name": "Knurled knob", "source": src, "brief": "a knurled knob",
                                                          "plan": b["brief"], "run": False})
                self.assertFalse(res.is_error, texts(res))
                self.assertGreaterEqual(len(images(res)), 2)            # six-view sheet + section
                pid = json.loads(texts(res)[0])["project"]
                gate = data(await c.call_tool("request_release", {"project": pid}))
                self.assertIn("No design critique", " ".join(gate.get("reasons", [])) + json.dumps(gate))
                cr = await c.call_tool("critique", {"project": pid, "notes": "cap and grip look right"})
                self.assertFalse(cr.is_error, texts(cr))
                self.assertEqual(len(images(cr)), 1)
                body = json.loads(texts(cr)[-1])
                self.assertEqual(body["evidence"], "heuristic")
                self.assertEqual(body["metrics"]["planned_missing"], [])


if __name__ == "__main__":
    unittest.main()
