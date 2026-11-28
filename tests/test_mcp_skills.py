"""Form Studio's guidance as MCP skills (io.modelcontextprotocol/skills, form/mcp_skills.py), checked through the SDK's
Client: skills/list manifests match the bytes resources/read serves, unknown URIs are -32602, design_guide(topic)
returns the skill files' text unchanged, and plugins/form/skills is an exact copy of form/guidance."""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import Client  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.shared.exceptions import MCPError  # noqa: E402
from mcp_types import Request, RequestParams  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

from form import design_guide, guidance  # noqa: E402
from form.mcp_skills import EXTENSION_ID, SkillsGetParams, SkillsListParams, skills_extension  # noqa: E402

ANY = TypeAdapter(dict[str, Any])


async def call(c: Client, method: str, params: RequestParams) -> dict:
    return await c.session.send_request(Request[type(params), str](method=method, params=params), ANY)


def server() -> MCPServer:
    return MCPServer("skills-test", extensions=[skills_extension()])


class SkillsOverMCP(unittest.TestCase):
    def test_list_get_read(self):
        asyncio.run(self._list_get_read())

    async def _list_get_read(self):
        async with Client(server()) as c:
            caps = c.server_capabilities
            self.assertIn(EXTENSION_ID, caps.extensions or {})
            self.assertIsNotNone(caps.resources)
            out = await call(c, "skills/list", SkillsListParams())
            self.assertEqual(out["resultType"], "complete")
            self.assertGreater(out["ttlMs"], 0)
            self.assertIn(out["cacheScope"], ("public", "private"))
            names = [s["frontmatter"]["name"] for s in out["skills"]]
            self.assertEqual(names, guidance.skills())
            self.assertEqual(len(names), len(set(names)))
            for want in ("cad-core", "staged-design", "surfacing-organic", "texture", "remodel-from-mesh", "intake",
                         "industrial-design", "assemblies-and-mechanisms", "release"):
                self.assertIn(want, names)
            self.assertEqual("game-asset" in names, design_guide.game_available())
            self.assertNotIn("aesthetics", names)                 # merged into industrial-design
            self.assertNotIn("mechanisms", names)                 # merged into assemblies-and-mechanisms
            files = 0
            for s in out["skills"]:
                name = s["frontmatter"]["name"]
                self.assertEqual(s["uri"], f"skill://{name}/SKILL.md")
                self.assertIn("Use when", s["frontmatter"]["description"])
                self.assertEqual(s["resources"][0]["uri"], s["uri"])
                for r in s["resources"]:
                    got = await c.read_resource(r["uri"])
                    self.assertEqual(len(got.contents), 1)
                    raw = got.contents[0].text.encode("utf-8")
                    self.assertEqual(r["digest"], "sha256:" + hashlib.sha256(raw).hexdigest(), r["uri"])
                    self.assertEqual(r["size"], len(raw), r["uri"])
                    self.assertEqual(got.contents[0].mime_type, "text/markdown")
                    files += 1
                body = (await c.read_resource(s["uri"])).contents[0].text
                self.assertEqual(guidance.frontmatter(body), s["frontmatter"])  # what a host verifies field by field
                one = await call(c, "skills/get", SkillsGetParams(uri=s["uri"]))
                self.assertEqual(one["resultType"], "complete")
                self.assertEqual(one["skill"], s)
            self.assertGreaterEqual(files, len(names) + 10)

            for bad in ("skill://no-such-skill/SKILL.md", "skill://cad-core/references/nope.md",
                        "skill://cad-core/../intake/SKILL.md"):
                with self.assertRaises(MCPError) as e:
                    await c.read_resource(bad)
                self.assertEqual(e.exception.error.code, -32602, bad)
            for bad in ("skill://no-such-skill/SKILL.md", "skill://cad-core/references/contract.md"):
                with self.assertRaises(MCPError) as e:
                    await call(c, "skills/get", SkillsGetParams(uri=bad))
                self.assertEqual(e.exception.error.code, -32602, bad)
            with self.assertRaises(MCPError) as e:
                await call(c, "skills/list", SkillsListParams(cursor="page-2"))
            self.assertEqual(e.exception.error.code, -32602)

    def test_game_asset_only_when_available(self):
        from unittest import mock
        with mock.patch.object(guidance, "game_available", return_value=False):
            ext = skills_extension()
        self.assertNotIn("game-asset", ext.names())
        self.assertFalse(any("game-asset" in r.resource.uri for r in ext.resources()))
        self.assertIn("game-asset", guidance.skills(all_=True))


class DesignGuideIsTheSkillText(unittest.TestCase):
    def test_topics_equal_skill_files(self):
        for t, (skill, rel) in guidance.TOPICS.items():
            got = design_guide.topic(t, "print")
            self.assertEqual(got["skill"], f"skill://{skill}/SKILL.md")
            self.assertEqual(got["skill_file"], f"skill://{skill}/{rel}")
            src = (ROOT / "form" / "guidance" / skill / rel).read_bytes().decode("utf-8")
            if t == "core":
                self.assertEqual(design_guide.topic(t, "model")["guide"], src)
                self.assertEqual(design_guide.topic(t)["guide"], src)          # no purpose: the model text
                self.assertNotEqual(got["guide"], src)                         # print swaps rules 5-6
                self.assertIn("Print orientation", got["guide"])
            else:
                self.assertEqual(got["guide"], src, t)
        rec = (ROOT / "form" / "guidance" / "cad-core" / "references" / "example-recipe.md").read_text(encoding="utf-8")
        self.assertEqual(rec, "```python\n" + design_guide.EXAMPLE + "```\n")
        compile(design_guide.EXAMPLE, "example", "exec")
        compile(design_guide.FEATURE_EXAMPLE, "example_features", "exec")

    def test_design_guide_tool_over_mcp(self):
        asyncio.run(self._tool())

    async def _tool(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("FORM_DATA")
            os.environ["FORM_DATA"] = d
            try:
                from form import mcp_server
                m = mcp_server.build()
                async with Client(m) as c:
                    for t, (skill, rel) in guidance.TOPICS.items():
                        if t in ("core", "dfm"):
                            continue                                   # purpose-dependent: covered above
                        res = await c.call_tool("design_guide", {"topic": t})
                        sc = res.structured_content
                        out = ((sc.get("result", sc) if set(sc) == {"result"} else sc) if sc is not None
                               else json.loads(res.content[0].text))
                        self.assertEqual(out["guide"], guidance.read(skill, rel), t)
                        self.assertEqual(out["skill"], f"skill://{skill}/SKILL.md")
                    self.assertEqual(len((await c.list_tools()).tools), 101)
            finally:
                if old is None:
                    os.environ.pop("FORM_DATA", None)
                else:
                    os.environ["FORM_DATA"] = old


class PluginCopy(unittest.TestCase):
    def test_plugin_skills_match_the_source(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_skills.py"), "--check"], capture_output=True,
                           text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, "plugins/form/skills drifted from form/guidance; run scripts/gen_skills.py\n"
                         + r.stdout)

    def test_skill_text_does_not_send_agents_to_untrusted_content(self):
        bad = ("curl ", "wget ", "pip install", "npm install", "| sh", "| bash", "eval(", "exec(", "ignore previous",
               "ignore all previous", "http://", "https://")
        for s in guidance.skills(all_=True):
            for rel in guidance.files(s):
                text = guidance.read(s, rel).lower()
                for b in bad:
                    self.assertNotIn(b, text, f"{s}/{rel}: {b!r}")


if __name__ == "__main__":
    unittest.main()
