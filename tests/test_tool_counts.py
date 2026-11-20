"""Every place that states how many MCP tools Form Studio has says the number the server registers.

The README (its text, its diagram and its pictures), docs/ARCHITECTURE.md, docs/FEATURES.md, docs/MCP.md
(scripts/gen_mcp_docs.py writes it) and the website's home page (site/tools/check_site.py also compares it with
docs/MCP.md). When a tool is added or removed, this fails until every count is updated."""
import asyncio
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# file -> patterns whose first group is a stated count of MCP tools
STATED = {
    "README.md": [r"(\d+) MCP tools"],
    "docs/ARCHITECTURE.md": [r"\| (\d+) tools over stdio \|"],
    "docs/FEATURES.md": [r"The full engine over (\d+) tools"],
    "docs/MCP.md": [r"^(\d+) tools\. Read-only"],
    "site/index.html": [r'data-count="(\d+)" id="why-tools"', r'id="why-tools">(\d+)<'],
    "docs/readme/numbers-1-light.svg": [r"(\d+) MCP tools for any agent", r'class="k10">(\d+)<'],
    "docs/readme/numbers-1-dark.svg": [r"(\d+) MCP tools for any agent", r'class="k10">(\d+)<'],
    "docs/readme/feature-headless-light.svg": [r"one of (\d+) MCP"],
    "docs/readme/feature-headless-dark.svg": [r"one of (\d+) MCP"],
}


def registered() -> int:
    from form import mcp_server
    m = mcp_server.build()
    return len(asyncio.run(m.list_tools()))


class ToolCounts(unittest.TestCase):
    def test_every_stated_count_matches_the_server(self):
        n = registered()
        seen = 0
        for rel, pats in STATED.items():
            text = (ROOT / rel).read_text(encoding="utf-8")
            for pat in pats:
                found = re.findall(pat, text, re.M)
                self.assertTrue(found, f"{rel}: no tool count matching {pat!r} (update STATED if the wording moved)")
                for v in found:
                    seen += 1
                    self.assertEqual(int(v), n, f"{rel} says {v} MCP tools; the server registers {n}")
        self.assertGreaterEqual(seen, 12)


if __name__ == "__main__":
    unittest.main()
