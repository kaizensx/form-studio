"""Claude Code's tool search in Form Studio's chat: the run lists ToolSearch and sets ENABLE_TOOL_SEARCH=auto, so
the tools that are not always loaded are found by searching and called by their mcp__form__ names. [chat]
tool_search = "false" (or FORM_TOOL_SEARCH=false) loads every tool up front as before.

The live case runs the real `claude -p` with the command Form Studio builds, against a real form-mcp, and checks that
a deferred tool (describe_recipe) is reached: only with FORM_LIVE_AGENT=1 and Claude Code installed and signed in
(it costs a few cents)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import chat, config  # noqa: E402
from form.agents.base import Run  # noqa: E402
from form.agents.claude import Claude, ClaudeParser  # noqa: E402


def _run(tmp, message="hello", **kw):
    return Run(message=message, system=chat.system_prompt({}, None, Claude(), message), cwd=Path(tmp),
               scratch=Path(tmp), mcp={"command": "form-mcp", "args": [], "env": {}}, **kw)


class ToolSearchCommand(unittest.TestCase):
    def test_on_by_default(self):
        self.assertEqual(config.DEFAULTS["chat"]["tool_search"], "auto")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FORM_TOOL_SEARCH", None)
            run = _run(tmp)
            cmd = Claude().command(run, sys.executable)
            self.assertIn("ToolSearch", cmd[cmd.index("--tools") + 1].split(","))
            self.assertIn("ToolSearch", cmd[cmd.index("--allowedTools") + 1].split(","))
            self.assertEqual(Claude().run_env(run), {"ENABLE_TOOL_SEARCH": "auto"})

    def test_the_flag_turns_it_off_for_one_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            for run, env in ((_run(tmp, tool_search="false"), {}), (_run(tmp), {"FORM_TOOL_SEARCH": "false"})):
                with mock.patch.dict(os.environ, env):
                    cmd = Claude().command(run, sys.executable)
                    self.assertNotIn("ToolSearch", cmd[cmd.index("--tools") + 1])
                    self.assertEqual(Claude().run_env(run), {"ENABLE_TOOL_SEARCH": "false"})

    def test_web_and_files_still_come_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(tmp, files=[Path(tmp) / "a.png"])
            tools = Claude().command(run, sys.executable)
            self.assertEqual(tools[tools.index("--tools") + 1].split(","), ["WebSearch", "WebFetch", "Read", "ToolSearch"])


@unittest.skipUnless(os.environ.get("FORM_LIVE_AGENT") == "1" and shutil.which("claude"),
                     "FORM_LIVE_AGENT=1 and Claude Code are needed (a real model run)")
class LiveClaudeFindsDeferredTools(unittest.TestCase):
    def test_a_deferred_tool_is_called_by_its_full_name(self):
        self._live("auto")          # what Form Studio sets: Claude Code defers when the tools outgrow its threshold

    def test_with_every_deferrable_tool_deferred(self):
        # forces deferral: describe_recipe (not always loaded) is reached by its full name, whether the model loads
        # its schema with ToolSearch first or learns the arguments from a first refused call
        self._live("true")

    def _live(self, mode: str) -> list:
        exe = shutil.which("claude")
        msg = ("Call Form Studio's describe_recipe tool for the recipe storage_box, then answer with only the number "
               "of parameters it lists. Do not call any other tool except to find that one.")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            mcp = {"command": sys.executable, "args": ["-m", "form.mcp_server", "--no-bench"],
                   "env": {"FORM_DATA": str(data), "PYTHONPATH": str(ROOT), "FORM_REFINE": "off"}}
            run = Run(message=msg, system=chat.system_prompt({}, None, Claude(), msg), cwd=Path(tmp),
                      scratch=Path(tmp), mcp=mcp, web=False, budget_usd=0.5,
                      model=os.environ.get("FORM_LIVE_MODEL", "haiku"))
            ad = Claude()
            cmd = ad.command(run, exe)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=tmp, stdin=subprocess.DEVNULL,
                               env={**os.environ, **ad.run_env(run), "ENABLE_TOOL_SEARCH": mode})
            parser, events = ClaudeParser(), []
            for line in p.stdout.splitlines():
                events += parser.feed(line)
            raw = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
            init = next((e for e in raw if e.get("type") == "system" and e.get("subtype") == "init"), {})
            names = [c.get("name") for e in raw if e.get("type") == "assistant"
                     for c in e.get("message", {}).get("content", []) if c.get("type") == "tool_use"]
            results = [e for e in events if e["t"] == "result"]
            report = json.dumps({"tools_in_init": [n for n in init.get("tools", []) if "form" in n or n == "ToolSearch"][:12],
                                 "called": names, "results": [r["text"][:120] for r in results],
                                 "stderr": p.stderr[-600:]}, indent=1)
            if os.environ.get("FORM_LIVE_VERBOSE") == "1":
                print(report, file=sys.stderr)
            self.assertIn("ToolSearch", init.get("tools", []), report)
            self.assertIn("mcp__form__describe_recipe", names, report)
            self.assertNotIn("describe_recipe", names, report)                      # never the bare name
            self.assertFalse(any("No such tool" in r["full"] for r in results), report)
            self.assertTrue(any(r["ok"] and "storage_box" in r["full"] for r in results), report)
            return names


if __name__ == "__main__":
    unittest.main()
