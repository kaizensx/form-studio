"""First-run setup over the engine API, and the GitHub update check. No real network, no real installs, no kernel."""
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from form import setup, setup_app, updates
from form.setup import Fix, Item
from form.studio import StudioError


def fake_items(log=None, cfg_file=None):
    """A mix of states, like a real machine. Commands are harmless Python one-liners."""
    py = f'"{sys.executable}" -c "print(42)"'
    def edit():
        if log is not None:
            log.append("edited")
        return "edited a file"
    return [
        Item("kernel", "CAD kernel", "ok", "build123d 0.13"),
        Item("data", "Project folder", "ok", "/tmp/x"),
        Item("slicer", "Slicer (Bambu Studio)", "ok", "02.09 · A1 mini"),
        Item("slicer.orca", "OrcaSlicer", "missing", "Not found", Fix("Install OrcaSlicer", [], recommended=False, note="Download it")),
        Item("cad.freecad", "FreeCAD", "ok", "1.0"),
        Item("agent.claude", "Claude Code", "missing", "not registered", Fix("Register FORM", [py])),
        Item("agent.gemini", "Gemini CLI", "missing", "not in settings.json", Fix("Add FORM", action=edit)),
        Item("agent.codex", "Codex", "warn", "elsewhere", Fix("Point Codex here", [f'"{sys.executable}" -c "import sys; sys.exit(3)"'],
                                                              recommended=False)),
        Item("weird", "Something new", "info", "fyi"),
    ]


class SetupApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="form-setup-app-")
        self.cfg = {"data": {"dir": self.tmp}, "updates": {"check": True}}

    def test_report_shape_groups_and_defaults(self):
        with mock.patch.object(setup, "check", lambda cfg=None, studio=None: fake_items()):
            r = setup_app.report(self.cfg)
        self.assertTrue(r["first_run"])
        self.assertTrue(r["required_ok"])
        ids = {i["id"]: i for i in r["items"]}
        for i in r["items"]:
            for k in ("id", "label", "status", "detail", "group", "required", "runnable", "default"):
                self.assertIn(k, i)
            self.assertIn(i["status"], ("ok", "warn", "missing", "info"))
        self.assertEqual(ids["slicer.orca"]["group"], "slicer")
        self.assertEqual(ids["cad.freecad"]["group"], "cad")
        self.assertEqual(ids["agent.claude"]["group"], "chat")
        self.assertEqual(ids["agent.codex"]["group"], "agents")
        self.assertEqual(ids["weird"]["group"], "other")
        self.assertEqual(ids["agent.claude"]["fix"]["commands"][0][-14:], '-c "print(42)"')
        self.assertFalse(ids["slicer.orca"]["runnable"])          # a note, nothing to run
        self.assertTrue(ids["agent.gemini"]["edits_file"])
        self.assertFalse(any(i["default"] for i in r["items"]))   # optional items never start ticked
        self.assertEqual({d["id"] for d in r["detected"]}, {"slicer", "cad.freecad"})
        self.assertEqual(r["attention"], ["agent.claude", "agent.gemini"])  # missing/warn with a recommended fix
        self.assertEqual([g["id"] for g in r["groups"]], ["engine", "slicer", "cad", "chat", "agents", "other"])

    def test_required_missing_is_ticked_and_flags_report(self):
        its = fake_items()
        its[0] = Item("kernel", "CAD kernel", "missing", "OCP did not start", Fix("Reinstall", ['echo reinstall']))
        with mock.patch.object(setup, "check", lambda cfg=None, studio=None: its):
            r = setup_app.report(self.cfg)
        k = next(i for i in r["items"] if i["id"] == "kernel")
        self.assertTrue(k["default"])
        self.assertFalse(r["required_ok"])
        self.assertIn("kernel", r["attention"])

    def _apply(self, s, ids, shown):
        return s.apply(ids, shown, start=False)

    def test_apply_refuses_unknown_ok_and_unrunnable_ids(self):
        s = setup_app.Setup(self.cfg)
        with mock.patch.object(setup, "check", lambda cfg=None, studio=None: fake_items()):
            for bad in (["nope"], ["kernel"], ["slicer.orca"], [], "agent.claude", [3]):
                with self.assertRaises(StudioError, msg=bad):
                    self._apply(s, bad, {})
            with self.assertRaises(StudioError):                      # commands must be exactly the ones shown
                self._apply(s, ["agent.claude"], {"agent.claude": ["rm -rf /"]})
            with self.assertRaises(StudioError):
                self._apply(s, ["agent.claude"], None)
        self.assertEqual(s.jobs, {})
        self.assertTrue(setup_app.first_run(self.cfg))                # nothing applied, nothing marked

    def test_apply_runs_only_chosen_and_rechecks(self):
        log = []
        s = setup_app.Setup(self.cfg)
        with mock.patch.object(setup, "check", lambda cfg=None, studio=None: fake_items(log)):
            items = {i.id: i for i in fake_items()}
            shown = {k: items[k].fix.commands for k in ("agent.claude", "agent.codex")}
            job = self._apply(s, ["agent.claude", "agent.codex"], shown)
            job.run()
        self.assertEqual(log, [])                                     # the unticked file edit did not run
        st = {x["id"]: x for x in job.steps}
        self.assertEqual(st["agent.claude"]["state"], "done")
        self.assertIn("42", st["agent.claude"]["output"])
        self.assertEqual(st["agent.codex"]["state"], "failed")
        self.assertIn("3", st["agent.codex"]["message"])
        self.assertEqual(job.state, "failed")
        self.assertEqual(set(job.after), {"agent.claude", "agent.codex"})
        self.assertFalse(setup_app.first_run(self.cfg))

    def test_file_edit_fix(self):
        log = []
        s = setup_app.Setup(self.cfg)
        with mock.patch.object(setup, "check", lambda cfg=None, studio=None: fake_items(log)):
            job = self._apply(s, ["agent.gemini"], {"agent.gemini": []})
            job.run()
        self.assertEqual(log, ["edited"])
        self.assertEqual(job.state, "done")

    def test_one_job_at_a_time(self):
        s = setup_app.Setup(self.cfg)
        with mock.patch.object(setup, "check", lambda cfg=None, studio=None: fake_items()):
            items = {i.id: i for i in fake_items()}
            self._apply(s, ["agent.claude"], {"agent.claude": items["agent.claude"].fix.commands})
            with self.assertRaises(StudioError) as cm:
                self._apply(s, ["agent.claude"], {"agent.claude": items["agent.claude"].fix.commands})
        self.assertEqual(cm.exception.status, 409)

    def test_marker(self):
        self.assertTrue(setup_app.first_run(self.cfg))
        setup_app.mark_seen(self.cfg, "skipped")
        self.assertFalse(setup_app.first_run(self.cfg))
        rec = json.loads((Path(self.tmp) / setup_app.MARKER).read_text(encoding="utf-8"))
        self.assertEqual(rec["how"], "skipped")

    def test_packaged_points_at_download(self):
        f = Fix("Reinstall", ["uv tool upgrade --reinstall form-studio"])
        with mock.patch.object(sys, "frozen", True, create=True):
            g = setup_app._packaged_fix(f)
        self.assertEqual(g.commands, [])
        self.assertIn("releases", g.note)
        self.assertIs(setup_app._packaged_fix(f), f)


class HttpRoutes(unittest.TestCase):
    """The routes the app calls, through the real handler."""

    @classmethod
    def setUpClass(cls):
        from form.server import make_handler
        cls.tmp = tempfile.mkdtemp(prefix="form-setup-http-")
        cfg = {"data": {"dir": cls.tmp}, "updates": {"check": True}}
        st = SimpleNamespace(cfg=cfg, root=Path(cls.tmp), chat=object())
        st.setup_app = setup_app.Setup(cfg)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.patch = mock.patch.object(setup, "check", lambda cfg=None, studio=None: fake_items())
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.httpd.shutdown()

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=30)
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse()
        out = r.status, json.loads(r.read())
        c.close()
        return out

    def test_routes(self):
        code, st = self.call("GET", "/api/setup/state")
        self.assertEqual(code, 200)
        self.assertIn("first_run", st)
        code, r = self.call("GET", "/api/setup")
        self.assertEqual(code, 200)
        self.assertIn("groups", r)
        code, e = self.call("POST", "/api/setup/apply", {"ids": ["nope"], "shown": {}})
        self.assertEqual(code, 400)
        self.assertIn("Unknown", e["error"]["message"])
        cmds = {i["id"]: i for i in r["items"]}["agent.claude"]["fix"]["commands"]
        code, j = self.call("POST", "/api/setup/apply", {"ids": ["agent.claude"], "shown": {"agent.claude": cmds}})
        self.assertEqual(code, 200)
        for _ in range(100):
            code, j = self.call("GET", f"/api/setup/job/{j['id']}")
            if j["state"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(j["state"], "done")
        code, _ = self.call("POST", "/api/setup/seen", {"how": "done"})
        self.assertEqual(code, 200)
        with mock.patch.dict(os.environ, {"FORM_FAKE_LATEST": "99.0.0"}):
            code, u = self.call("GET", "/api/updates")
        self.assertTrue(u["available"])


class Versions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updates.newer("10.1.0", "9.0.0"))
        self.assertTrue(updates.newer("v10.1", "10.0.9"))
        self.assertFalse(updates.newer("10.0.0", "10.0.0"))
        self.assertFalse(updates.newer("9.9.9", "10.0.0"))
        self.assertTrue(updates.newer("10.0.10", "10.0.9"))         # numeric, not lexical
        # the development builds (5.0.0 to 12.3.0) came before the public 1.0.0
        self.assertTrue(updates.newer("1.0.0", "12.3.0"))
        self.assertTrue(updates.newer("v1.1.0", "11.1.1"))
        self.assertFalse(updates.newer("12.3.0", "1.0.0"))
        self.assertTrue(updates.newer("1.0.1", "1.0.0"))
        self.assertFalse(updates.newer("1.0.0", "1.1.0"))

    def test_prereleases(self):
        self.assertTrue(updates.newer("10.1.0", "10.1.0rc1"))       # final beats its pre-release
        self.assertFalse(updates.newer("10.1.0rc1", "10.1.0"))
        self.assertTrue(updates.newer("10.1.0rc2", "10.1.0rc1"))
        self.assertTrue(updates.newer("10.1.0-beta.2", "10.1.0a5"))
        self.assertTrue(updates.newer("10.1.0rc1", "10.0.0"))
        self.assertFalse(updates.newer("garbage", "1.0.0"))
        self.assertFalse(updates.newer("1.0.0", "garbage"))
        self.assertIsNone(updates.parse("10.1.0-weird"))


def _release(tag="v10.1.0", assets=("FORM-macos-arm64.zip", "FORM-windows-x64.zip", "FORM-linux-x64.tar.gz", "FORM-macos-x64.zip")):
    body = {"tag_name": tag, "name": f"FORM {tag}", "body": "## Notes\n- one", "html_url": "https://github.com/kaizensx/form-studio/releases/tag/" + tag,
            "published_at": "2026-11-20T10:00:00Z", "prerelease": False,
            "assets": [{"name": a, "browser_download_url": "https://github.com/x/" + a, "size": 1} for a in assets]}

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return R(json.dumps(body).encode())


class UpdateCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="form-updates-")
        self.cfg = {"data": {"dir": self.tmp}, "updates": {"check": True}}
        self.env = mock.patch.dict(os.environ, {"FORM_NO_UPDATE_CHECK": "", "FORM_FAKE_LATEST": ""})
        self.env.start()
        self.ver = mock.patch.object(updates, "__version__", "10.0.0")     # the tests below are written against 10.0.0
        self.ver.start()

    def tearDown(self):
        self.ver.stop()
        self.env.stop()

    def test_available_and_asset_for_this_machine(self):
        with mock.patch("urllib.request.urlopen", return_value=_release()) as op:
            u = updates.check(self.cfg)
        self.assertEqual(op.call_count, 1)
        req = op.call_args[0][0]
        self.assertEqual(req.full_url, updates.API)
        self.assertEqual(op.call_args[1]["timeout"], 5.0)
        self.assertNotIn("Authorization", req.headers)
        self.assertTrue(u["available"])
        self.assertEqual(u["latest"], "10.1.0")
        self.assertEqual(u["download"]["name"], updates.asset_name())
        self.assertIn("Notes", u["release"]["notes"])

    def test_cached_for_a_day(self):
        with mock.patch("urllib.request.urlopen", return_value=_release()) as op:
            updates.check(self.cfg)
            u = updates.check(self.cfg)
        self.assertEqual(op.call_count, 1)
        self.assertTrue(u["available"])
        cache = Path(self.tmp) / updates.CACHE
        data = json.loads(cache.read_text(encoding="utf-8"))
        data["checked"] -= 2 * updates.DAY
        cache.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch("urllib.request.urlopen", return_value=_release("v10.2.0")) as op:
            u = updates.check(self.cfg)
        self.assertEqual(op.call_count, 1)
        self.assertEqual(u["latest"], "10.2.0")

    def test_offline_is_silent(self):
        for err in (urllib.error.URLError("offline"), TimeoutError(), OSError("dns"), ValueError("bad json")):
            Path(self.tmp, updates.CACHE).unlink(missing_ok=True)
            with mock.patch("urllib.request.urlopen", side_effect=err):
                u = updates.check(self.cfg)
            self.assertFalse(u["available"])
            self.assertNotIn("latest", u)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("must not retry today")):
            self.assertFalse(updates.check(self.cfg)["available"])   # a failed check is not repeated within a day

    def test_offline_keeps_what_was_known(self):
        with mock.patch("urllib.request.urlopen", return_value=_release()):
            updates.check(self.cfg)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            u = updates.check(self.cfg, force=True)
        self.assertTrue(u["available"])

    def test_not_newer(self):
        with mock.patch("urllib.request.urlopen", return_value=_release("v9.0.0")):
            u = updates.check(self.cfg)
        self.assertFalse(u["available"])
        self.assertEqual(u["latest"], "9.0.0")

    def test_off_switches(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network when off")):
            u = updates.check({"data": {"dir": self.tmp}, "updates": {"check": False}})
            self.assertFalse(u["enabled"])
            with mock.patch.dict(os.environ, {"FORM_NO_UPDATE_CHECK": "1"}):
                self.assertFalse(updates.check(self.cfg)["enabled"])
            with mock.patch.dict(os.environ, {"FORM_FAKE_LATEST": "10.1.0"}):
                f = updates.check(self.cfg)
        self.assertTrue(f["available"] and f["release"]["fake"])

    def test_install_kind_and_command(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(updates.install_kind(), "packaged")
        with mock.patch.object(updates.shutil, "which", lambda n: "/usr/bin/" + n):
            self.assertIn("uv tool install --force --refresh-package form-studio", updates.upgrade_command("tool"))
        self.assertEqual(updates.upgrade_command("packaged"), "")

    def test_config_default(self):
        from form import config
        self.assertEqual(config.DEFAULTS["updates"], {"check": True, "channel": "stable"})


if __name__ == "__main__":
    unittest.main()
