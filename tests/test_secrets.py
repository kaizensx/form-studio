"""Agent keys kept by FORM (form/secrets.py) and Gemini CLI's sign-in, found by a real run of Gemini CLI 0.68.0 that
stopped with "Please set an Auth method ... GEMINI_API_KEY"."""
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from form import installer, secrets
from form.agents import ADAPTERS

ROOT = Path(__file__).resolve().parents[1]
KEY = "AIzaTestKeyNotReal0123456789"


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="form-secrets-"))
        self.env = mock.patch.dict(os.environ, {"FORM_SECRETS": str(self.dir / "secrets.json")})
        self.env.start()
        os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        self.env.stop()

    def test_set_status_clear_never_return_the_value(self):
        self.assertFalse(secrets.status()["gemini_api_key"]["set"])
        row = secrets.set_value("gemini_api_key", "  " + KEY + "\n")
        self.assertTrue(row["set"])
        self.assertNotIn(KEY, json.dumps(secrets.status()))
        self.assertEqual(json.loads((self.dir / "secrets.json").read_text(encoding="utf-8"))["gemini_api_key"], KEY)
        self.assertFalse(secrets.clear("gemini_api_key")["set"])
        self.assertEqual(secrets.agent_env("gemini"), {})

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX permission bits")
    def test_file_is_private(self):
        secrets.set_value("gemini_api_key", KEY)
        mode = stat.S_IMODE((self.dir / "secrets.json").stat().st_mode)
        self.assertEqual(mode & 0o077, 0, oct(mode))

    def test_key_goes_to_its_own_agent_only_and_never_over_the_environment(self):
        secrets.set_value("gemini_api_key", KEY)
        self.assertEqual(secrets.agent_env("gemini"), {"GEMINI_API_KEY": KEY})
        self.assertEqual(secrets.agent_env("claude"), {})
        self.assertEqual(secrets.agent_env("codex"), {})
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "from-the-shell"}):
            self.assertEqual(secrets.agent_env("gemini"), {})

    def test_rejects_what_is_not_a_key(self):
        for bad in ("", "two words", "a\nb", "x" * 401):
            with self.assertRaises(secrets.SecretError):
                secrets.set_value("gemini_api_key", bad)
        with self.assertRaises(secrets.SecretError):
            secrets.set_value("openai", KEY)

    def test_cli_reads_the_value_from_stdin_not_the_command_line(self):
        env = dict(os.environ)
        r = subprocess.run([sys.executable, "-m", "form", "secrets", "set", "gemini_api_key"], input=KEY + "\n",
                           capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["set"])
        self.assertNotIn(KEY, r.stdout)
        r = subprocess.run([sys.executable, "-m", "form", "secrets", "set", "gemini_api_key", KEY],
                           capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
        self.assertNotEqual(r.returncode, 0, "a value on the command line must be refused")


class GeminiSignIn(unittest.TestCase):
    ERR = ("Please set an Auth method in your /Users/x/.gemini/settings.json or specify one of the following environment "
           "variables before running: GEMINI_API_KEY, GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_GENAI_USE_GCA")

    def test_the_real_error_is_explained_with_the_fix_inside_form(self):
        x = ADAPTERS["gemini"].explain(self.ERR)
        self.assertIn("not signed in", x["message"])
        self.assertIn("Settings", x["hint"])
        self.assertIsNone(ADAPTERS["gemini"].explain("network unreachable"))
        self.assertIsNone(ADAPTERS["claude"].explain(self.ERR))

    def test_signed_in_detection(self):
        home = Path(tempfile.mkdtemp(prefix="form-gemini-home-"))
        clean = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI",
                                                                   "GOOGLE_GENAI_USE_GCA")}
        clean.update(GEMINI_CLI_HOME=str(home), FORM_SECRETS=str(home / "secrets.json"))
        with mock.patch.dict(os.environ, clean, clear=True):
            self.assertFalse(installer.gemini_signed_in()[0])
            (home / ".gemini").mkdir()
            (home / ".gemini" / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}),
                                                            encoding="utf-8")
            self.assertTrue(installer.gemini_signed_in()[0])
            (home / ".gemini" / "settings.json").unlink()
            secrets.set_value("gemini_api_key", KEY)
            ok, why = installer.gemini_signed_in()
            self.assertTrue(ok and "FORM" in why)

    def test_registry_offers_every_agent_and_slicer_form_can_drive(self):
        ids = {s.id for s in installer.REGISTRY}
        for need in ("gemini", "gemini.signin", "codex", "slicer.superslicer", "slicer.qidi"):
            self.assertIn(need, ids)
        g = next(s for s in installer.REGISTRY if s.id == "gemini")
        cmds = [c for m in g.methods("linux", {}) for c in m.commands]
        self.assertIn("npm install -g @google/gemini-cli", cmds)


if __name__ == "__main__":
    unittest.main()
