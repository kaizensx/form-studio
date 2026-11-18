"""Project housekeeping for the app shell: rename, duplicate, delete (engine, HTTP, CLI, MCP).

A temp data folder. Nothing here builds geometry: these operations only touch the project store.
"""
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-shell-")

from form import config  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def new(self, name="Shelf dock"):
        return self.st.create(name, "dock", "a brief")

    def ids(self):
        return [r["id"] for r in self.st.list()]

    def approve_by_hand(self, pid):
        """A release as approve() leaves it on disk, without building anything."""
        f = Path(TMP) / pid / "project.json"
        raw = json.loads(f.read_text(encoding="utf-8"))
        raw["approvals"] = [{"rev": 1, "ts": 1.0, "keys": {}, "release": "r01-abcdef", "note": ""}]
        f.write_text(json.dumps(raw), encoding="utf-8")
        rel = Path(TMP) / pid / "releases" / "r01-abcdef"
        rel.mkdir(parents=True)
        (rel / "manifest.json").write_text("{}", encoding="utf-8")


class Engine(Base):
    def test_rename_keeps_id_and_changes_name(self):
        p = self.new("Rename me")
        row = self.st.rename_project(p["id"], "  Wall   dock ")
        self.assertEqual((row["id"], row["name"]), (p["id"], "Wall dock"))
        self.assertEqual(set(row), {"id", "name", "recipe", "head", "revisions", "updated", "approved_rev", "purpose", "concept"})
        self.assertEqual({r["id"]: r["name"] for r in self.st.list()}[p["id"]], "Wall dock")
        self.assertTrue((Path(TMP) / p["id"]).is_dir())
        self.assertEqual(self.st.rename_project(self.st.load(p["id"]), "By dict")["name"], "By dict")   # a loaded project works too

    def test_bad_names_are_rejected(self):
        p = self.new("Bad names")
        for bad in ("", "   ", None, "x" * 81):
            with self.assertRaises(StudioError) as e:
                self.st.rename_project(p["id"], bad)
            self.assertTrue(e.exception.hint)
        self.assertEqual(self.st.load(p["id"])["name"], "Bad names")
        with self.assertRaises(StudioError):
            self.st.duplicate_project(p["id"], "y" * 81)
        with self.assertRaises(StudioError) as e:
            self.st.rename_project("no-such-project", "Name")
        self.assertEqual(e.exception.status, 404)

    def test_duplicate_is_a_new_unapproved_project(self):
        p = self.new("Original")
        self.approve_by_hand(p["id"])
        self.assertEqual(self.st._summary(p["id"])["approved_rev"], 1)
        row = self.st.duplicate_project(p["id"])
        self.assertEqual((row["id"], row["name"]), ("original-copy", "Original copy"))
        self.assertIsNone(row["approved_rev"])
        q, src = self.st.load(row["id"]), self.st.load(p["id"])
        self.assertEqual(q["id"], row["id"])
        self.assertEqual(q["approvals"], [])
        self.assertFalse((Path(TMP) / row["id"] / "releases").exists())            # a release belongs to the original
        self.assertEqual(q["head"], src["head"])
        self.assertEqual(self.st.rev(q)["values"], self.st.rev(src)["values"])
        self.assertIn("not approved", q["decisions"][-1]["text"])
        self.assertEqual(len(src["approvals"]), 1)                                 # the original is untouched
        self.assertTrue((Path(TMP) / p["id"] / "releases" / "r01-abcdef" / "manifest.json").is_file())
        again = self.st.duplicate_project(p["id"])                                 # ids stay unique
        self.assertEqual(again["id"], "original-copy-2")
        named = self.st.duplicate_project(p["id"], "Travel version")
        self.assertEqual((named["id"], named["name"]), ("travel-version", "Travel version"))

    def test_delete_moves_to_trash(self):
        p = self.new("Throwaway")
        pid = p["id"]
        self.st.lock(pid)
        res = self.st.delete_project(pid)
        self.assertEqual((res["ok"], res["id"]), (True, pid))
        trash = Path(res["trash"])
        self.assertEqual(trash.parent, Path(TMP) / ".trash")
        self.assertRegex(trash.name, rf"^{pid}-\d{{8}}T\d{{6}}Z$")
        self.assertTrue((trash / "project.json").is_file())
        self.assertFalse((Path(TMP) / pid).exists())
        self.assertNotIn(pid, self.ids())
        self.assertFalse([i for i in self.ids() if i.startswith(".") or "trash" in i])   # the trash is not a project
        self.assertNotIn(pid, self.st._locks)
        with self.assertRaises(StudioError) as e:
            self.st.load(pid)
        self.assertEqual(e.exception.status, 404)
        with self.assertRaises(StudioError):
            self.st.delete_project(pid)
        q = self.new("Throwaway")                                                  # the id is free again;
        self.assertEqual(q["id"], pid)
        again = Path(self.st.delete_project(pid)["trash"])                         # a second trip never overwrites the first
        self.assertNotEqual(again, trash)
        self.assertTrue(trash.is_dir() and again.is_dir())

    def test_delete_refuses_while_building(self):
        p = self.new("Busy one")
        self.st.jobs["j1"] = {"id": "j1", "project": p["id"], "state": "running"}
        try:
            with self.assertRaises(StudioError) as e:
                self.st.delete_project(p["id"])
            self.assertEqual(e.exception.status, 409)
            self.assertIn(p["id"], self.ids())
        finally:
            self.st.jobs.pop("j1", None)


class Http(Base):
    def test_routes(self):
        from form.server import make_handler
        p = self.new("Http dock")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api/projects/"

        def call(path, body):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            code, row = call(f"{p['id']}/rename", {"name": "Http renamed"})
            self.assertEqual((code, row["id"], row["name"]), (200, p["id"], "Http renamed"))
            code, err = call(f"{p['id']}/rename", {"name": " "})
            self.assertEqual(code, 400)
            self.assertTrue(err["error"]["hint"])
            code, copy = call(f"{p['id']}/duplicate", {})
            self.assertEqual((code, copy["name"], copy["approved_rev"]), (200, "Http renamed copy", None))
            self.assertNotEqual(copy["id"], p["id"])
            code, named = call(f"{p['id']}/duplicate", {"name": "Http two"})
            self.assertEqual((code, named["id"]), (200, "http-two"))
            code, res = call(f"{copy['id']}/delete", {})
            self.assertEqual((code, res["ok"], res["id"]), (200, True, copy["id"]))
            self.assertTrue(Path(res["trash"]).is_dir())
            self.assertNotIn(copy["id"], self.ids())
            self.assertIn(p["id"], self.ids())
            self.assertEqual(call(f"{copy['id']}/delete", {})[0], 404)
            self.assertEqual(call("no-such-project/rename", {"name": "x"})[0], 404)
        finally:
            httpd.shutdown()
            httpd.server_close()


class Cli(Base):
    def cli(self, *argv):
        from form.__main__ import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(list(argv))
        return rc, json.loads(buf.getvalue())

    def test_rename_duplicate_delete(self):
        p = self.new("Cli dock")
        rc, out = self.cli("rename", p["id"], "Cli renamed")
        self.assertEqual((rc, out["id"], out["name"]), (0, p["id"], "Cli renamed"))
        rc, out = self.cli("duplicate", p["id"], "--name", "Cli second")
        self.assertEqual((rc, out["id"]), (0, "cli-second"))
        rc, out = self.cli("delete", "cli-second")                                # no --yes: nothing happens
        self.assertEqual(rc, 2)
        self.assertIn(".trash", out["error"]["message"])
        self.assertIn("--yes", out["error"]["hint"])
        self.assertIn("cli-second", self.ids())
        rc, out = self.cli("delete", "cli-second", "--yes")
        self.assertEqual((rc, out["ok"]), (0, True))
        self.assertTrue(Path(out["trash"]).is_dir())
        self.assertNotIn("cli-second", self.ids())
        rc, out = self.cli("delete", "no-such-project")
        self.assertEqual((rc, out["error"]["message"]), (2, "Unknown project."))


class McpTools(unittest.TestCase):
    def test_tools_are_registered(self):
        import anyio
        from form import mcp_server

        async def tools():
            return {t.name: t for t in await mcp_server.build().list_tools()}
        got = anyio.run(tools)
        for t in ("rename_project", "duplicate_project", "delete_project"):
            self.assertIn(t, got)
        doc = " ".join(got["delete_project"].description.split())
        self.assertIn("trash folder inside the projects folder", doc)
        self.assertIn("Ask the user first", doc)


if __name__ == "__main__":
    unittest.main()
