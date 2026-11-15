"""End-to-end over real MCP stdio: a client launches `python -m form.mcp_server` like an agent would."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


def text(res):
    return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")


def data(res):
    if res.structured_content is not None:
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(text(res))


class MCPEndToEnd(unittest.TestCase):
    def test_agent_session(self):
        asyncio.run(self._session())

    async def _session(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(ROOT)}
            params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"],
                                           env=env, cwd=str(ROOT))
            async with Client(params) as c:
                tools = {t.name for t in (await c.list_tools()).tools}
                self.assertIn("render", tools)
                self.assertNotIn("approve", " ".join(tools))          # approval is not an agent tool

                ov = data(await c.call_tool("form_overview", {}))
                self.assertIn("dock", [r["id"] for r in ov["recipes"]])

                p = data(await c.call_tool("create_project", {"name": "Test dock", "recipe": "dock",
                                                              "values": {"device_width": 70}, "run": True}))
                self.assertEqual(p["outputs"]["geometry"], "current")
                self.assertIn("(assumed)", p["parameters"]["device_width"])
                pid, head = p["project"], p["head"]

                pv = data(await c.call_tool("preview_change", {"project": pid, "values": {"clearance": 0.35}}))
                self.assertTrue(pv["buildable"])
                self.assertIn("Pocket", " ".join(pv["features"]))
                self.assertIn("Solid", pv["would_invalidate"])

                bad = await c.call_tool("preview_change", {"project": pid, "values": {"cable_diameter": 12}})
                self.assertTrue(bad.is_error)
                self.assertIn("Hint:", text(bad))

                img = await c.call_tool("render", {"project": pid, "view": "iso", "highlight": "pocket"})
                kinds = [c_.type for c_ in img.content]
                self.assertIn("image", kinds, text(img))

                cm = data(await c.call_tool("commit_change", {"project": pid, "values": {"clearance": 0.35},
                                                              "expect_head": head, "note": "loosen", "run": True,
                                                              "provenance": {"device_width": {"source": "measured", "sigma": 0.02,
                                                                                              "instrument": "test caliper"}}}))
                self.assertEqual(cm["head"], head + 1)
                self.assertIn("(measured)", cm["project"]["parameters"]["device_width"])
                self.assertTrue(cm["project"]["recent_revisions"][-1].split("] ")[0].endswith("agent:mcp"))

                stale = await c.call_tool("commit_change", {"project": pid, "values": {"clearance": 0.4}, "expect_head": head})
                self.assertTrue(stale.is_error)
                self.assertIn("moved on", text(stale))

                rr = data(await c.call_tool("request_release", {"project": pid}))
                self.assertIn("ready", rr)
                self.assertNotIn("approve_here", rr)                    # --no-bench: no link to hand out


if __name__ == "__main__":
    unittest.main()
