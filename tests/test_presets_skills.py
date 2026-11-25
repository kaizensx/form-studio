"""Brief templates (form/presets) and the Claude Code plugin (plugins/form): structure, completeness, tool names."""
import ast
import json
import re
import tempfile
import unittest
from pathlib import Path

from form import presets

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "form"
SKILLS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))


def mcp_tools() -> set[str]:
    """Tool names registered in form/mcp_server.py: async functions decorated with @mcp.tool."""
    tree = ast.parse((ROOT / "form" / "mcp_server.py").read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for d in node.decorator_list:
                f = d.func if isinstance(d, ast.Call) else d
                if isinstance(f, ast.Attribute) and f.attr == "tool":
                    out.add(node.name)
    return out


def frontmatter(text: str) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


class Presets(unittest.TestCase):
    def test_six_presets_valid_and_complete(self):
        ps = presets.all_presets()
        self.assertEqual({p["id"] for p in ps}, {"automotive-accessory", "bathroom-mount", "desk-accessory", "enclosure",
                                                 "organizer", "remote-holder"})
        for p in ps:
            self.assertEqual(presets.problems(p), [], p["id"])
            self.assertTrue((presets.HERE / f"{p['id']}.json").exists())

    def test_json_files_parse(self):
        for f in presets.HERE.glob("*.json"):
            json.loads(f.read_text(encoding="utf-8"))

    def test_closest_recipe_exists(self):
        names = {f.stem for f in (ROOT / "form" / "recipes").glob("*.py")} - {"__init__", "base"}
        for p in presets.all_presets():
            if p.get("closest_recipe"):
                self.assertIn(p["closest_recipe"], names, p["id"])

    def test_problems_catches_gaps(self):
        p = presets.get("remote-holder")
        bad = json.loads(json.dumps(p))
        bad["questions"][0]["unit"] = ""
        bad["environment"]["uv"] = "lots"
        del bad["checks"]
        self.assertIn("missing checks", presets.problems(bad))
        bad["checks"] = p["checks"]
        probs = presets.problems(bad)
        self.assertTrue(any("needs a unit" in x for x in probs))
        self.assertTrue(any("uv" in x for x in probs))

    def test_normalize(self):
        p = presets.get("remote-holder")
        with self.assertRaises(ValueError):
            presets.normalize(p, {"width": "48"}, False)           # thickness is required
        with self.assertRaises(ValueError):
            presets.normalize(p, {"width": "wide", "thickness": "18"}, False)
        with self.assertRaises(ValueError):
            presets.normalize(p, {"width": "48", "thickness": "18", "mounting": "Glue gun"}, False)
        rows = presets.normalize(p, {"width": "48,5", "thickness": "18", "mounting": "Screws"}, True)
        self.assertEqual(rows[0], {"key": "width", "label": "Remote width", "kind": "number", "value": 48.5,
                                   "unit": "mm", "source": "measured"})
        self.assertEqual(rows[2]["value"], "Screws")
        self.assertEqual(presets.normalize(p, {"width": "48", "thickness": "18"}, False)[0]["source"], "assumed")

    def test_brief_round_trip_into_project(self):
        from form import config
        from form.studio import Studio
        with tempfile.TemporaryDirectory() as d:
            cfg = config.load()
            cfg["data"]["dir"] = d
            st = Studio(cfg)
            r = presets.start_brief(st.root, "remote-holder", {"width": "48", "thickness": "18"}, measured=False)
            self.assertRegex(r["id"], r"^b-[0-9a-f]{8}$")
            self.assertIn(r["brief"], r["prompt"])
            self.assertIn("Remote width: 48 mm (assumed)", r["prompt"])
            self.assertIn("Not answered yet", r["prompt"])
            self.assertIn("Do not start a print", r["prompt"])
            self.assertTrue((Path(d) / ".briefs" / f"{r['id']}.json").exists())
            p = st.create("TV remote holder", "dock", r["brief"])
            b = st.load(p["id"])["brief"]
            self.assertEqual(b["preset"], "remote-holder")
            self.assertEqual([a["key"] for a in b["answers"]], ["width", "thickness"])
            self.assertEqual(b["text"], r["brief"])
            self.assertFalse((Path(d) / ".briefs" / f"{r['id']}.json").exists())   # consumed
            self.assertNotIn(".briefs", [q["id"] for q in st.list()])
            p2 = st.create("Plain", "dock", "no token here")
            self.assertNotIn("answers", st.load(p2["id"])["brief"])
            with self.assertRaises(ValueError):
                presets.start_brief(st.root, "nope", {}, False)


    def test_http_routes(self):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer

        from form import config
        from form.server import make_handler
        from form.studio import Studio
        with tempfile.TemporaryDirectory() as d:
            cfg = config.load()
            cfg["data"]["dir"] = d
            st = Studio(cfg)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            u = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                got = json.load(urllib.request.urlopen(u + "/api/presets"))
                self.assertEqual(len(got["presets"]), 6)

                def post(body):
                    return urllib.request.urlopen(urllib.request.Request(
                        u + "/api/briefs", json.dumps(body).encode(), {"Content-Type": "application/json"}))
                with self.assertRaises(urllib.error.HTTPError) as e:
                    post({"preset": "organizer", "answers": {"drawer_w": "300"}})
                self.assertEqual(e.exception.code, 400)
                r = json.load(post({"preset": "organizer", "answers": {"drawer_w": "300", "drawer_d": "420"}}))
                self.assertIn("Drawer inner width: 300 mm", r["brief"])
            finally:
                httpd.shutdown()
                httpd.server_close()


class Plugin(unittest.TestCase):
    def test_manifests(self):
        m = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(m["name"], "form")
        mk = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        entry = [e for e in mk["plugins"] if e["name"] == "form"][0]
        self.assertEqual((ROOT / entry["source"]).resolve(), PLUGIN.resolve())
        self.assertTrue(mk["owner"]["name"])
        mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(mcp["mcpServers"]["form"]["command"], "form-mcp")

    def test_skills_frontmatter_unique(self):
        self.assertGreaterEqual(len(SKILLS), 10)
        self.assertLessEqual(len(SKILLS), 24)
        names = []
        for f in SKILLS:
            fm = frontmatter(f.read_text(encoding="utf-8"))
            self.assertTrue(fm.get("name"), f)
            self.assertTrue(fm.get("description"), f)
            self.assertEqual(fm["name"], f.parent.name)
            self.assertRegex(fm["name"], r"^[a-z0-9-]+$")
            self.assertIn("Use when", fm["description"], f)
            names.append(fm["name"])
        self.assertEqual(len(names), len(set(names)))

    def test_skill_tools_exist(self):
        tools = mcp_tools()
        self.assertIn("brief_presets", tools)
        self.assertGreaterEqual(len(tools), 28)
        for f in SKILLS:
            text = f.read_text(encoding="utf-8")
            line = re.search(r"^FORM tools: (.+?)(?:\n\n|\Z)", text, re.M | re.S)
            self.assertTrue(line, f"{f.parent.name}: no 'FORM tools:' line")
            listed = re.findall(r"`([a-z_]+)\(\)`", line.group(1))
            self.assertTrue(listed, f.parent.name)
            # every `name(...)` in backticks is a tool call and must exist
            called = set(re.findall(r"`([a-z_]+)\(", text))
            for t in set(listed) | called:
                self.assertIn(t, tools, f"{f.parent.name} mentions unknown MCP tool {t}")
            # and no stale references to the old offline scripts
            self.assertNotRegex(text, r"studio\.py|mesh_audit\.py|scripts/|review\.json|templates/")

    def test_agents_md_points_to_skills(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("plugins/form/skills", text)
        for f in SKILLS:
            self.assertIn(f.parent.name, text)


if __name__ == "__main__":
    unittest.main()
