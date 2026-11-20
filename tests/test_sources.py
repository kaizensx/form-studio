"""Model links (form/sources, form/start.py): Printables, Thingiverse, MakerWorld, other pages and direct files.

No test reaches the internet. Every request the engine makes is rewritten to a local server that answers with
responses recorded from the real sites (tests/fixtures/sources) or written to their documented shape, and records the
headers it received: no cookies, no credentials (except Thingiverse's app token, to its API only), a generic agent."""
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

os.environ.setdefault("FORM_SKIP_UI", "1")

from form import net, sources, start  # noqa: E402
from form.conversations import Conversations  # noqa: E402
from form.sources import makerworld, printables, thingiverse  # noqa: E402
from form.studio import StudioError  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "sources"
STL = b"solid benchy\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid\n"
SIGNED_3MF = b"PK\x03\x04 a 3mf from a signed link"

THING = {"id": 763622, "name": "Cable clip", "creator": {"name": "maker42"}, "license": "Creative Commons - Attribution",
         "thumbnail": "https://cdn.thingiverse.com/renders/clip.jpg"}
THING_FILES = [{"id": 1001, "name": "clip.stl", "size": len(STL),
                "download_url": "https://api.thingiverse.com/files/1001/download"},
               {"id": 1002, "name": "readme.txt", "size": 10, "download_url": "https://api.thingiverse.com/files/1002/download"}]
MW_PAGE = (b'<html><head><title>Desk hook | MakerWorld</title><meta property="og:title" content="Desk hook"/>'
           b'<meta property="og:image" content="https://makerworld.bblmw.com/img/hook.jpg"/></head><body>x</body></html>')
OTHER_PAGE = (b'<html><head><meta property="og:title" content="A lamp I like"/><meta name="description" content="Brass">'
              b'<meta property="og:image" content="/img/lamp.jpg"/></head><body><a href="/lamp.stl">stl</a></body></html>')


class Net(unittest.TestCase):
    """A local stand-in for the internet: /<host>/<path>."""

    @classmethod
    def setUpClass(cls):
        cls.seen = seen = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, body=b"", ctype="application/octet-stream", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _route(self, method):
                host, _, rest = self.path.lstrip("/").partition("/")
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                seen.append({"method": method, "host": host, "path": "/" + rest, "headers": dict(self.headers),
                             "body": body})
                if host == "api.printables.com":
                    q = json.loads(body)
                    if "getDownloadLink" in q["query"]:
                        return self._reply(200, (FIX / "printables_link_49068.json").read_bytes(), "application/json")
                    if q["variables"]["id"] == "404":
                        return self._reply(200, b'{"data": {"print": null}}', "application/json")
                    return self._reply(200, (FIX / "printables_print_3161.json").read_bytes(), "application/json")
                if host == "files.printables.com":
                    return self._reply(200, STL)
                if host == "api.thingiverse.com":
                    if rest == "things/763622":
                        return self._reply(200, json.dumps(THING).encode(), "application/json")
                    if rest == "things/763622/files":
                        return self._reply(200, json.dumps(THING_FILES).encode(), "application/json")
                    if rest == "files/1001/download":
                        return self._reply(302, extra={"Location": "/cdn.thingiverse.com/assets/clip.stl"})
                if host == "cdn.thingiverse.com":
                    return self._reply(200, STL)
                if host == "makerworld.com":
                    return self._reply(200, MW_PAGE, "text/html")
                if host == "makerworld.bblmw.com":
                    if "expired" in rest:
                        return self._reply(403, b"<Error>Request has expired</Error>", "application/xml")
                    return self._reply(200, SIGNED_3MF)
                if host == "progress.test":                    # half the file, then look at the engine's progress
                    import time as _t
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(4 << 20))
                    self.end_headers()
                    self.wfile.write(b"x" * (2 << 20))
                    self.wfile.flush()
                    _t.sleep(0.3)
                    Net.mid = start.progress()
                    self.wfile.write(b"x" * (2 << 20))
                    return
                if host == "once.test":                        # a signed single-use link: the second GET fails
                    if any(r["host"] == "once.test" and r["path"] == "/" + rest for r in seen[:-1]):
                        return self._reply(403, b"<Error>Already used</Error>", "application/xml")
                    return self._reply(200, SIGNED_3MF)
                if host == "example.com":
                    return self._reply(200, OTHER_PAGE, "text/html")
                return self._reply(404, b"not here", "text/plain")

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.local = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        real = urllib.request.urlopen

        def urlopen(req, timeout=30):                  # every request goes to the local server, headers kept
            u = urlparse(req.full_url)
            local = f"{cls.local}/{u.hostname}{u.path}" + (f"?{u.query}" if u.query else "")
            r2 = urllib.request.Request(local, data=req.data, method=req.get_method())
            for k, v in req.header_items():
                if (k, v) in req.unredirected_hdrs.items():
                    r2.add_unredirected_header(k, v)
                else:
                    r2.add_header(k, v)
            return real(r2, timeout=timeout)
        cls.patch = mock.patch.object(net, "urlopen", urlopen)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        del self.seen[:]
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = Conversations(self.tmp)
        self.cid = self.store.create()["id"]
        self.st = type("St", (), {"root": self.tmp, "chat": None})()

    def assert_private(self):
        """Nothing about the person or their accounts left the machine."""
        for r in self.seen:
            h = {k.lower(): v for k, v in r["headers"].items()}
            self.assertNotIn("cookie", h, r)
            self.assertTrue(h.get("user-agent", "").startswith("FormStudio/"), r)
            self.assertNotIn("@", h["user-agent"])
            if "authorization" in h:
                self.assertEqual(r["host"], "api.thingiverse.com", r)


class Classify(unittest.TestCase):
    def test_kinds_without_network(self):
        with mock.patch.object(net, "urlopen", side_effect=AssertionError("no network")):
            self.assertEqual(sources.classify("https://www.printables.com/model/3161-3d-benchy"), "printables")
            self.assertEqual(sources.classify("https://www.thingiverse.com/thing:763622"), "thingiverse")
            self.assertEqual(sources.classify("https://makerworld.com/en/models/123456-desk-hook"), "makerworld")
            self.assertEqual(sources.classify("https://makerworld.bblmw.com/a/b/hook.3mf?exp=1&key=x"), "file")
            self.assertEqual(sources.classify("https://files.printables.com/media/x/benchy.stl"), "file")
            self.assertEqual(sources.classify("https://example.com/lamp"), "page")
            self.assertEqual(sources.resolve("https://example.com/lamp", generic=False)["site"], "page")
            with self.assertRaises(sources.SourceError):
                sources.classify("file:///etc/passwd")

    def test_links_in_a_message(self):
        msg = ("Make this lighter: https://www.printables.com/model/3161-3d-benchy, and see (https://example.com/a). "
               "Again https://www.printables.com/model/3161-3d-benchy.")
        self.assertEqual(start.links_in(msg), ["https://www.printables.com/model/3161-3d-benchy", "https://example.com/a"])


class Resolvers(Net):
    def test_printables_lists_title_licence_and_files(self):
        r = sources.resolve("https://www.printables.com/model/3161-3d-benchy")
        self.assertEqual((r["site"], r["title"], r["author"]), ("printables", "3D BENCHY", "Prusa Research"))
        self.assertEqual(r["license"], "Creative Commons — Public Domain")
        self.assertEqual([f["name"] for f in r["files"]], ["3dbenchy.stl"])
        self.assertTrue(r["downloadable"])
        self.assertTrue(sources.file_url(r, r["files"][0]).startswith("https://files.printables.com/"))
        q = json.loads(self.seen[0]["body"])
        self.assertEqual(q["variables"], {"id": "3161"})
        self.assert_private()

    def test_printables_unknown_model(self):
        with self.assertRaises(sources.SourceError) as e:
            sources.resolve("https://www.printables.com/model/404-x")
        self.assertIn("no public model", str(e.exception))

    def test_thingiverse_without_a_token_explains_and_reads_nothing(self):
        with mock.patch.dict(os.environ, {thingiverse.ENV_TOKEN: ""}):
            r = sources.resolve("https://www.thingiverse.com/thing:763622")
        self.assertFalse(r["downloadable"])
        self.assertIn("turns away other programs", r["reason"])
        self.assertIn("Download All Files", r["how"])
        self.assertEqual(r["zip"], "https://www.thingiverse.com/thing:763622/zip")
        self.assertEqual(self.seen, [])

    def test_thingiverse_with_an_app_token(self):
        with mock.patch.dict(os.environ, {thingiverse.ENV_TOKEN: "app-token-1"}):
            r = sources.resolve("https://www.thingiverse.com/thing:763622")
            got = start.fetch(self.st, self.cid, "https://www.thingiverse.com/thing:763622")
        self.assertEqual((r["title"], r["author"], r["license"]), ("Cable clip", "maker42", "Creative Commons - Attribution"))
        self.assertEqual([a["name"] for a in got["attachments"]], ["clip.stl"])     # readme.txt is not a part
        api = [s for s in self.seen if s["host"] == "api.thingiverse.com"]
        self.assertTrue(api and all(s["headers"].get("Authorization") == "Bearer app-token-1" for s in api))
        cdn = [s for s in self.seen if s["host"] == "cdn.thingiverse.com"]
        self.assertEqual(len(cdn), 1)
        self.assertNotIn("Authorization", cdn[0]["headers"])                       # the token stays with the API
        self.assert_private()

    def test_makerworld_explains_and_reads_only_the_public_page(self):
        r = sources.resolve("https://makerworld.com/en/models/123456-desk-hook")
        self.assertFalse(r["downloadable"])
        self.assertIn("signed-in", r["reason"])
        self.assertIn("paste it here within a few minutes", r["how"])
        self.assertEqual(r["title"], "Desk hook")
        self.assertEqual(r["images"], ["https://makerworld.bblmw.com/img/hook.jpg"])
        self.assertEqual([(s["method"], s["host"], s["path"]) for s in self.seen],
                         [("GET", "makerworld.com", "/en/models/123456-desk-hook")])
        self.assert_private()

    def test_makerworld_refusing_the_page_still_explains(self):
        with mock.patch.object(makerworld, "NAME", "makerworld"), \
                mock.patch("form.sources.generic.read", side_effect=sources.SourceError("makerworld.com answered 403.")):
            r = sources.resolve("https://makerworld.com/en/models/1")
        self.assertIsNone(r["title"])
        self.assertIn("signed-in", r["reason"])

    def test_any_other_page_gives_a_visual_reference_only(self):
        r = sources.resolve("https://example.com/lamp")
        self.assertEqual((r["site"], r["title"], r["description"]), ("page", "A lamp I like", "Brass"))
        (img,) = r["images"]                                                      # made absolute against the page
        self.assertTrue(img.startswith("http") and img.endswith("/img/lamp.jpg"), img)
        self.assertFalse(r["downloadable"])
        self.assertEqual(len(self.seen), 1)                                      # the link on the page is not followed
        self.assert_private()


class Fetch(Net):
    def test_a_printables_page_attaches_its_files_with_source_and_licence(self):
        got = start.fetch(self.st, self.cid, "https://www.printables.com/model/3161-3d-benchy")
        (a,) = got["attachments"]
        self.assertEqual((a["name"], a["kind"]), ("3dbenchy.stl", "cad"))
        self.assertEqual(a["source"]["license"], "Creative Commons — Public Domain")
        self.assertEqual(a["source"]["url"], "https://www.printables.com/model/3161-3d-benchy")
        self.assertEqual(self.store.attachment(self.cid, a["file"]).read_bytes(), STL)
        self.assertEqual(self.store.attachments(self.cid, [a["id"]])[0]["source"]["author"], "Prusa Research")
        self.assertEqual(got["model"]["title"], "3D BENCHY")
        self.assertFalse(list((self.store.dir(self.cid) / ".incoming").iterdir()))   # nothing left half-way
        self.assert_private()

    def test_a_signed_makerworld_link_is_fetched_at_once(self):
        url = "https://makerworld.bblmw.com/makerworld/model/US1/123/hook.3mf?at=1&exp=1763650000&key=abc"
        got = start.fetch(self.st, self.cid, url)
        (a,) = got["attachments"]
        self.assertEqual((a["name"], a["kind"]), ("hook.3mf", "cad"))
        self.assertEqual(got["fetched"]["bytes"], len(SIGNED_3MF))
        self.assertEqual(a["source"]["url"], url)
        with self.assertRaises(StudioError) as e:
            start.fetch(self.st, self.cid, "https://makerworld.bblmw.com/expired/hook.3mf?exp=1")
        self.assertIn("403", str(e.exception))
        self.assertIn("expired", e.exception.hint)
        self.assert_private()

    def test_a_makerworld_page_returns_the_explanation(self):
        got = start.fetch(self.st, self.cid, "https://makerworld.com/en/models/123456-desk-hook")
        self.assertNotIn("attachments", got)
        self.assertEqual((got["link"]["site"], got["link"]["title"]), ("makerworld", "Desk hook"))
        self.assertIn("signed-in", got["link"]["reason"])

    def test_without_a_conversation_files_land_in_a_folder_with_their_source(self):
        got = start.fetch_to_folder("https://www.printables.com/model/3161-3d-benchy", self.tmp / "links")
        (a,) = got["attachments"]
        self.assertEqual(Path(a["path"]).read_bytes(), STL)
        src = json.loads((self.tmp / "links" / "3dbenchy.stl.source.json").read_text())
        self.assertEqual(src["site"], "printables")

    def test_links_in_a_chat_message_are_fetched_and_explained(self):
        msg = ("Make a lighter one of https://www.printables.com/model/3161-3d-benchy and like "
               "https://makerworld.com/en/models/123456-desk-hook, see also https://example.com/notes")
        ids, note = start.fetch_message_links(self.st, self.cid, msg)
        self.assertEqual(len(ids), 1)
        self.assertIn("downloaded by Form Studio and attached (3dbenchy.stl)", note)
        self.assertIn("licence: Creative Commons — Public Domain", note)
        self.assertIn("Desk hook: not downloaded. MakerWorld only gives files to a signed-in person", note)
        self.assertNotIn("example.com", note)                                    # a plain page is just a link
        self.assertNotIn("example.com", {s["host"] for s in self.seen})


    def test_a_link_the_app_fetched_is_not_fetched_again_when_the_message_is_sent(self):
        """The app fetches each link in a message (POST /conversations/<id>/fetch), then sends the message; the
        engine reuses that fetch: one download, one attachment, and a single-use signed link still works."""
        url = "https://once.test/signed/hook.3mf?exp=1763650000&sig=abc"
        first = start.fetch(self.st, self.cid, url)                       # what Store.sendWithLinks does first
        (a,) = first["attachments"]
        ids, note = start.fetch_message_links(self.st, self.cid, f"make this lighter {url}.")   # what send does
        self.assertEqual(ids, [a["id"]])
        self.assertIn("downloaded by Form Studio and attached (hook.3mf)", note)
        self.assertNotIn("not fetched", note)
        self.assertEqual(len([r for r in self.seen if r["host"] == "once.test"]), 1, "downloaded once")
        self.assertEqual(len(list(self.store.files_dir(self.cid).iterdir())), 1, "attached once")
        # a message whose link the app did not fetch is still fetched by the engine, once
        other = self.store.create()["id"]
        ids2, note2 = start.fetch_message_links(self.st, other, "https://once.test/signed/other.3mf?sig=2")
        self.assertEqual(len(ids2), 1)
        with self.assertRaises(StudioError):                              # proof the link really is single-use
            start.fetch(self.st, self.store.create()["id"], "https://once.test/signed/other.3mf?sig=2")
        # a link that failed a moment ago is reported, not fetched again
        bad = "https://makerworld.bblmw.com/expired/x.3mf?exp=1"
        with self.assertRaises(StudioError):
            start.fetch(self.st, self.cid, bad)
        n = len(self.seen)
        _, note3 = start.fetch_message_links(self.st, self.cid, bad)
        self.assertEqual(len(self.seen), n)
        self.assertIn("not fetched", note3)


class PlainErrors(unittest.TestCase):
    def test_no_errno_reaches_the_person(self):
        import socket
        import urllib.error
        from form import net as net_mod
        cases = [urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided, or not known")),
                 urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")),
                 urllib.error.URLError(TimeoutError("timed out")), OSError(54, "Connection reset by peer")]
        for e in cases:
            text = net_mod.plain_error(e, "files.example.com")
            self.assertNotIn("Errno", text)
            self.assertNotIn("nodename", text)
            self.assertIn("files.example.com", text)
        self.assertIn("could not find", net_mod.plain_error(cases[0], "x.test"))
        with mock.patch.object(net, "urlopen", side_effect=cases[0]):
            with self.assertRaises(StudioError) as err:
                start.download("https://files.example.com/a.stl", Path(tempfile.mkdtemp()))
        self.assertNotIn("Errno", str(err.exception))
        self.assertNotIn("FORM_THINGIVERSE_TOKEN", thingiverse.HOW)             # no environment variables to set


class Progress(Net):
    def test_progress_is_reported_while_downloading_and_cleared(self):
        got = start.fetch(self.st, self.cid, "https://progress.test/scan.stl")
        self.assertEqual(got["fetched"]["bytes"], 4 << 20)
        (p,) = Net.mid
        self.assertEqual((p["url"], p["name"], p["total"]), ("https://progress.test/scan.stl", "scan.stl", 4 << 20))
        self.assertGreater(p["bytes"], 0)
        self.assertLess(p["bytes"], 4 << 20)
        self.assertEqual(start.progress(), [])


if __name__ == "__main__":
    unittest.main()
