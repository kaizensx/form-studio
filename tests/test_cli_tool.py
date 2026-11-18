"""form tool: every MCP tool from the command line, with the same arguments and refusals."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


class ToolBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-tool-"))
        (self.tmp / "data").mkdir()
        self.env = mock.patch.dict(os.environ, {"FORM_DATA": str(self.tmp / "data"), "FORM_CONFIG": str(self.tmp / "none.toml")})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def run_cli(self, *argv):
        from form.__main__ import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(list(argv))
        return rc, json.loads(buf.getvalue())

    def test_lists_every_tool_documented(self):
        rc, out = self.run_cli("tool")
        self.assertEqual(rc, 0)
        names = {t["name"] for t in out["tools"]}
        doc = (Path(__file__).resolve().parents[1] / "docs" / "MCP.md").read_text(encoding="utf-8")
        self.assertIn(f"{len(names)} tools.", doc)                       # the same set the MCP reference counts
        self.assertTrue({"form_overview", "create_design", "checkout_revision", "record_physical_result"} <= names)

    def test_calls_a_tool_and_reports_refusals(self):
        rc, out = self.run_cli("tool", "form_overview")
        self.assertEqual(rc, 0)
        self.assertIn("kernel", out)
        rc, out = self.run_cli("tool", "get_project", '{"project": "nope"}')
        self.assertEqual(rc, 1)
        self.assertIn("Unknown project", out["error"]["message"])
        rc, out = self.run_cli("tool", "get_project", "[1]")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
