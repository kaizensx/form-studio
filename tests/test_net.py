"""Found in the installed app: every https read failed with CERTIFICATE_VERIFY_FAILED, http links were refused,
and the agent's "bathroom mount" did not find the "bathroom-mount" preset."""
import unittest
import urllib.error
from unittest import mock

from form import documents, net, presets


class Certificates(unittest.TestCase):
    def test_https_uses_the_shipped_ca_bundle(self):
        ca = net.ca_file()
        self.assertTrue(ca, "certifi's CA bundle must be available (it is shipped in the app)")
        with mock.patch("urllib.request.urlopen") as uo:
            net.urlopen("https://example.org/x.pdf")
        self.assertIs(uo.call_args.kwargs["context"], net.ssl_context())


class Download(unittest.TestCase):
    def test_http_links_try_https_first_then_plain(self):
        seen = []

        def fake(req, timeout=30):
            seen.append(req.full_url)
            if req.full_url.startswith("https://"):
                raise urllib.error.URLError("no https here")

            class R:
                def __enter__(s): return s
                def __exit__(s, *a): return False
                def read(s, n): return b"%PDF-1.4 x"
            return R()
        with mock.patch.object(net, "urlopen", fake):
            self.assertTrue(documents._download("http://example.org/a.pdf").startswith(b"%PDF"))
        self.assertEqual(seen, ["https://example.org/a.pdf", "http://example.org/a.pdf"])

    def test_a_site_that_serves_only_browsers_is_explained(self):
        err = urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None)
        with mock.patch.object(net, "urlopen", side_effect=err):
            with self.assertRaises(ValueError) as c:
                documents._download("https://example.org/a.pdf")
        self.assertIn("attach it to the conversation", str(c.exception))


class PresetNames(unittest.TestCase):
    def test_the_words_an_agent_uses_find_the_preset(self):
        for q in ("bathroom mount", "Bathroom Mount", "bathroom_mount", "bathroom-mount"):
            self.assertEqual(presets.get(q)["id"], "bathroom-mount", q)
        self.assertEqual(presets.get("car accessory")["id"], "automotive-accessory")
        with self.assertRaises(KeyError):
            presets.get("spaceship")


if __name__ == "__main__":
    unittest.main()


class PackagedMcp(unittest.TestCase):
    """Found in the installed app: its chats used a form-mcp from PATH (an old command-line install)."""

    def test_the_packaged_app_hands_agents_itself(self):
        import sys
        from pathlib import Path
        from form import setup
        from form.chat import Chat
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", "/Applications/FORM.app/Contents/MacOS/FORM"), \
             mock.patch("shutil.which", return_value="/Users/x/.local/bin/form-mcp"):
            self.assertEqual(setup.mcp_command(), "/Applications/FORM.app/Contents/MacOS/FORM")
            self.assertEqual(setup.mcp_args(), ["-m", "form.mcp_server"])
            c = Chat({"chat": {}, "_path": "(none)"}, Path("/tmp/x"), "/Users/x/.local/bin/form-mcp", adapters={})
            m = c._mcp()
        self.assertEqual(m["command"], "/Applications/FORM.app/Contents/MacOS/FORM")
        self.assertEqual(m["args"][:2], ["-m", "form.mcp_server"])
