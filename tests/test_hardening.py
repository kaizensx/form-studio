"""Engine hardening found by code scanning: download headers, other websites calling the engine, design source ids,
provider host matching. No kernel work: the server answers these before any geometry is touched."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-hard-")

from form import config  # noqa: E402
from form.agents.custom import _host_is  # noqa: E402
from form.recipes import SCAD_PREFIX, SOURCE_PREFIX, RecipeBook, source_path  # noqa: E402
from form.server import _attachment, make_handler  # noqa: E402
from form.studio import Studio  # noqa: E402


class Headers(unittest.TestCase):
    def test_attachment_never_breaks_the_header(self):
        v = _attachment('evil"\r\nSet-Cookie: x=1.stl')
        self.assertNotIn("\r", v)
        self.assertNotIn("\n", v)
        self.assertTrue(v.startswith('attachment; filename="evil_Set-Cookie_ x_1.stl"'))
        self.assertIn("filename*=UTF-8''", v)

    def test_attachment_keeps_plain_names(self):
        self.assertEqual(_attachment("bracket.3mf"), "attachment; filename=\"bracket.3mf\"; filename*=UTF-8''bracket.3mf")


class Sources(unittest.TestCase):
    def test_source_ids_are_hashes(self):
        store = Path(TMP) / ".sources"
        self.assertEqual(source_path(store, SOURCE_PREFIX + "0123abcd"), store / "0123abcd.py")
        self.assertEqual(source_path(store, SCAD_PREFIX + "0123abcd"), store / "0123abcd.scad")
        for bad in ("../../etc/passwd", "abc/def", "", "ABC"):
            with self.assertRaises(KeyError):
                source_path(store, SOURCE_PREFIX + bad)
        book = RecipeBook(store)
        self.assertNotIn(SCAD_PREFIX + "../x", book)
        with self.assertRaises(KeyError):
            book[SOURCE_PREFIX + "../x"]


class Hosts(unittest.TestCase):
    def test_host_is_exact_or_subdomain(self):
        self.assertTrue(_host_is("https://api.anthropic.com/v1", "anthropic.com"))
        self.assertTrue(_host_is("https://anthropic.com", "anthropic.com"))
        self.assertFalse(_host_is("https://anthropic.com.evil.example/v1", "anthropic.com"))
        self.assertFalse(_host_is("https://evil.example/anthropic.com", "anthropic.com"))
        self.assertFalse(_host_is("https://notanthropic.com", "anthropic.com"))


class OtherWebsites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.st))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.st.kernel.stop()

    def _get(self, origin=None):
        h = {"Origin": origin} if origin else {}
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + "/api/activity", headers=h)) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_own_pages_and_native_app_are_answered(self):
        self.assertEqual(self._get()[0], 200)
        self.assertEqual(self._get(self.base)[0], 200)
        self.assertEqual(self._get("http://localhost:1234")[0], 200)

    def test_other_websites_are_refused(self):
        code, body = self._get("https://example.com")
        self.assertEqual(code, 403)
        self.assertIn("other websites", body["error"]["message"])
        self.assertEqual(self._get("http://127.0.0.1.example.com")[0], 403)


if __name__ == "__main__":
    unittest.main()
