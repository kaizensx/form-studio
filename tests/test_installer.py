"""The installer registry, install jobs, studio.toml write-back, capabilities, and no examples.
Nothing here installs anything or touches the network: commands are harmless Python one-liners."""
import json
import os
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from form import config, config_edit, installer, setup_app
from form.installer import Found, Method, Software

PY = f'"{sys.executable}"' if sys.platform.startswith("win") else installer.shlex.quote(sys.executable)


def cfg_for(tmp: str) -> dict:
    c = {k: dict(v) for k, v in config.DEFAULTS.items()}
    c["data"]["dir"] = tmp
    c["_path"] = str(Path(tmp) / "studio.toml")
    return c


def fake(sid="thing", commands=None, found=None, methods=None, marker=None, **kw) -> Software:
    """A registry entry whose install is a Python one-liner. Detection: `found`, or "ok once `marker` exists"."""
    def detect(cfg, ctx):
        if marker is not None:
            return Found("ok", "found it") if Path(marker).exists() else Found("missing", "not there")
        return (found or [Found("missing", "not there")])[0]

    def meths(platform, ctx):
        return methods if methods is not None else [Method("cmd", "Test command", commands=list(commands or [f"{PY} -c \"print('hello')\""]))]
    return Software(sid, kw.pop("label", "Thing"), "For tests.", kw.pop("level", "optional"), kw.pop("group", "cad"), detect, meths, **kw)


class Registry(unittest.TestCase):
    def test_every_entry_is_complete(self):
        ids = [s.id for s in installer.REGISTRY]
        self.assertEqual(len(ids), len(set(ids)))
        groups = {g for g, _ in installer.GROUPS}
        for s in installer.REGISTRY:
            self.assertTrue(s.label and s.why, s.id)
            self.assertIn(s.level, installer.LEVELS, s.id)
            self.assertIn(s.group, groups, s.id)
            self.assertTrue(callable(s.detect) and callable(s.methods), s.id)
            for n in s.needs:
                self.assertIn(n, ids)
        for want in ("kernel", "data", "parts", "claude", "claude.signin", "slicer.bambu", "slicer.orca", "slicer.prusa",
                     "openscad", "blender", "freecad", "agent.claude", "agent.codex", "agent.gemini", "agent.cursor", "agent.desktop"):
            self.assertIn(want, ids)

    def test_every_app_has_a_method_or_a_page_on_each_os(self):
        for s in installer.REGISTRY:
            if s.id.startswith("agent.") or s.id in ("data",):
                continue
            for plat in ("darwin", "win32", "linux"):
                ms = installer.methods_for(s, plat, which=lambda n: "/x/" + n)
                self.assertTrue(ms, (s.id, plat))
                for m in ms:
                    self.assertIn(m.kind, ("command", "action", "open", "bundled", "login"))
                    if m.kind == "open":
                        self.assertTrue(m.url.startswith("https://"), (s.id, m.url))
                    if m.kind == "command":
                        self.assertTrue(m.commands, (s.id, m.id))

    def test_parts_pins_match_pyproject(self):
        py = Path(__file__).resolve().parents[1] / "pyproject.toml"
        extras = tomllib.loads(py.read_text(encoding="utf-8"))["project"]["optional-dependencies"]["parts"]
        self.assertEqual(sorted(extras), sorted(installer.PARTS_PINS))

    def test_lock_pins_the_parts_and_organic_extras(self):
        root = Path(__file__).resolve().parents[1]
        extras = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
        lock = {}
        for line in (root / "requirements.lock").read_text(encoding="utf-8").splitlines():
            if "==" in line and not line.startswith("#"):
                name, version = line.split("==")
                lock[name.strip().lower().replace("_", "-")] = version.strip()
        for req in extras["parts"] + extras["organic"]:
            name = req.split("=")[0].split(">")[0].split("<")[0].strip().lower().replace("_", "-")
            self.assertIn(name, lock, req)
            if "==" in req:
                self.assertEqual(lock[name], req.split("==")[1], req)

    def test_claude_uses_the_official_commands(self):
        c = installer.get("claude")
        mac = installer.plan(c, "darwin", which=lambda n: "/x/" + n)
        self.assertEqual(mac.commands, ["curl -fsSL https://claude.ai/install.sh | bash"])
        win = installer.plan(c, "win32", which=lambda n: "/x/" + n)
        self.assertEqual(win.commands, ["curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd"])
        only_winget = installer.plan(c, "win32", which=lambda n: "w" if n == "winget" else None)
        self.assertEqual(only_winget.commands, ["winget install Anthropic.ClaudeCode"])
        self.assertIsNone(installer.plan(c, "linux", which=lambda n: None))           # nothing to run: page only
        self.assertEqual(installer.manual(c, "linux"), installer.CLAUDE_DOCS)


class MethodSelection(unittest.TestCase):
    def test_slicer_per_os(self):
        o = installer.get("slicer.orca")
        has = lambda *names: (lambda n: "/x/" + n if n in names else None)
        self.assertEqual(installer.plan(o, "darwin", has("brew")).commands, ["brew install --cask orcaslicer"])
        self.assertIsNone(installer.plan(o, "darwin", has()))                         # no brew: download page
        self.assertEqual(installer.manual(o, "darwin"), "https://github.com/SoftFever/OrcaSlicer/releases")
        self.assertIn("winget install --id SoftFever.OrcaSlicer", installer.plan(o, "win32", has("winget")).commands[0])
        self.assertIsNone(installer.plan(o, "win32", has("brew")))
        self.assertEqual(installer.plan(o, "linux", has("flatpak")).commands, ["flatpak install -y flathub com.orcaslicer.OrcaSlicer"])
        self.assertIsNone(installer.plan(o, "linux", has("brew", "winget")))
        ids = {"slicer.bambu": ("bambu-studio", "Bambulab.Bambustudio", "com.bambulab.BambuStudio"),
               "slicer.prusa": ("prusaslicer", "Prusa3D.PrusaSlicer", "com.prusa3d.PrusaSlicer"),
               "openscad": ("openscad", "OpenSCAD.OpenSCAD", "org.openscad.OpenSCAD"),
               "blender": ("blender", "BlenderFoundation.Blender", "org.blender.Blender"),
               "freecad": ("freecad", "FreeCAD.FreeCAD", "org.freecad.FreeCAD")}
        for sid, (brew, winget, flat) in ids.items():
            s = installer.get(sid)
            self.assertIn(brew, installer.plan(s, "darwin", has("brew")).commands[0])
            self.assertIn(winget, installer.plan(s, "win32", has("winget")).commands[0])
            self.assertIn(flat, installer.plan(s, "linux", has("flatpak")).commands[0])

    def test_elevation_is_skipped_and_explained(self):
        s = installer.get("openscad")
        ms = installer.methods_for(s, "linux", which=lambda n: "/usr/bin/apt-get" if n == "apt-get" else None)
        apt = next(m for m in ms if m.id == "apt")
        self.assertTrue(apt.elevation)
        self.assertFalse(apt.available)
        self.assertIn("password", apt.reason)
        self.assertIsNone(installer.plan(s, "linux", which=lambda n: "/usr/bin/apt-get" if n == "apt-get" else None))
        both = installer.plan(s, "linux", which=lambda n: "/x")                     # flatpak comes first and needs no password
        self.assertEqual(both.id, "flatpak")
        for sw in installer.REGISTRY:                                                # no method FORM would run uses sudo
            for plat in ("darwin", "win32", "linux"):
                m = installer.plan(sw, plat, which=lambda n: "/x/" + n)
                for c in (m.commands if m else []):
                    self.assertNotIn("sudo", c, (sw.id, plat))

    def test_parts_source_and_packaged(self):
        p = installer.get("parts")
        with mock.patch.object(installer, "frozen", lambda: False):
            m = installer.plan(p, "darwin", which=lambda n: "/x/uv" if n == "uv" else None)
            self.assertTrue(m.commands[0].startswith("uv pip install --python "))
            self.assertIn("bd_warehouse==0.4.0 py_gearworks==0.0.24", m.commands[0])
        with mock.patch.object(installer, "frozen", lambda: True):
            self.assertIsNone(installer.plan(p, "darwin", which=lambda n: "/x/" + n))  # bundled: nothing to run
            kinds = [m.kind for m in installer.methods_for(p, "darwin")]
            self.assertEqual(kinds[0], "bundled")
            with mock.patch.object(installer.importlib.util, "find_spec", lambda name: object()):
                self.assertIn("included in this app", installer._d_parts({}, {}).detail)

    def test_survey_defaults_and_one_slicer_is_enough(self):
        tmp = tempfile.mkdtemp(prefix="form-inst-")
        with mock.patch.object(installer, "REGISTRY", [
                fake("slicer.a", found=[Found("ok", "v1")], level="recommended", group="slicer", one_of="slicer"),
                fake("slicer.b", level="recommended", group="slicer", one_of="slicer"),
                fake("rec", level="recommended"), fake("opt", level="optional"),
                fake("nopage", level="recommended", methods=[Method("x", "Needs brew", commands=["brew x"], needs=("brew",))]),
                fake("dep", level="recommended", needs=("rec",))]):
            rows = {r["id"]: r for r in installer.survey(cfg_for(tmp), which=lambda n: None)}
        self.assertEqual(rows["slicer.b"]["level"], "optional")
        self.assertFalse(rows["slicer.b"]["default"])
        self.assertTrue(rows["rec"]["default"])                    # recommended and missing: pre-ticked
        self.assertFalse(rows["opt"]["default"])
        self.assertFalse(rows["nopage"]["installable"])
        self.assertIn("brew is not installed", rows["nopage"]["methods"][0]["reason"])
        self.assertEqual(rows["dep"]["blocked_by"], ["rec"])
        self.assertFalse(rows["dep"]["installable"])

    def test_pretend_missing_env(self):
        tmp = tempfile.mkdtemp(prefix="form-inst-")
        with mock.patch.dict(os.environ, {"FORM_SETUP_PRETEND_MISSING": "data"}):
            row = installer.survey(cfg_for(tmp), only=["data"])[0]
        self.assertEqual(row["status"], "missing")
        self.assertEqual(installer.survey(cfg_for(tmp), only=["data"])[0]["status"], "ok")


class Jobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="form-inst-")
        self.cfg = cfg_for(self.tmp)
        os.environ.pop("FORM_INSTALL_FAKE", None)

    def _installer(self, *entries):
        p = mock.patch.object(installer, "REGISTRY", list(entries))
        p.start()
        self.addCleanup(p.stop)
        return installer.Installer(self.cfg)

    def test_dry_run_never_executes(self):
        marker = Path(self.tmp) / "ran.txt"
        cmd = f"{PY} -c \"open(r'{marker}', 'w').write('x')\""
        self._installer(fake("thing", [cmd]))
        out = []
        with mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))), \
             mock.patch.object(config, "load", lambda: self.cfg):
            rc = installer.main(["thing", "--dry-run"])
        self.assertEqual(rc, 0)
        d = json.loads(out[-1])
        self.assertTrue(d["dry_run"])
        self.assertEqual(d["would_run"][0]["commands"], [cmd])
        self.assertFalse(marker.exists())
        # preparing (what the app does before showing the command) does not run it either
        installer.Installer(self.cfg).prepare(["thing"])
        self.assertFalse(marker.exists())

    def test_job_streams_log_and_rechecks(self):
        marker = Path(self.tmp) / "installed.txt"
        inst = self._installer(fake("thing", [f"{PY} -c \"print('line one'); print('line two'); open(r'{marker}', 'w').close()\""],
                                    marker=marker))
        job = inst.install(["thing"], {"thing": inst.prepare(["thing"])[0][1].commands}, start=False)
        job.run()
        p = job.public(0)
        texts = [l["text"] for l in p["log"]]
        self.assertEqual(p["state"], "done")
        self.assertIn("line one", texts)
        self.assertIn("line two", texts)
        self.assertEqual(p["log"][0]["kind"], "cmd")
        self.assertEqual(p["steps"][0]["state"], "done")
        self.assertEqual(p["after"]["thing"]["status"], "ok")
        self.assertEqual(job.public(p["next"])["log"], [])                # incremental reads
        self.assertEqual([l["n"] for l in job.public(2)["log"]][0], 2)

    def test_still_missing_after_a_clean_exit_is_a_failure(self):
        inst = self._installer(fake("thing"))
        job = inst.install(["thing"], None, start=False)
        job.run()
        self.assertEqual(job.state, "failed")
        self.assertIn("still cannot find it", job.steps[0]["message"])

    def test_nonzero_exit_fails_and_sudo_is_explained(self):
        inst = self._installer(fake("thing", [f"{PY} -c \"import sys; print('sudo: a terminal is required to read the password'); sys.exit(1)\""]))
        job = inst.install(["thing"], None, start=False)
        job.run()
        self.assertEqual(job.state, "failed")
        self.assertIn("never asks", job.steps[0]["message"])

    def test_refuses_changed_commands_unknown_and_installed(self):
        inst = self._installer(fake("thing"), fake("have", found=[Found("ok", "v")]),
                               fake("page", methods=[Method("download", "Page", kind="open", url="https://example.org")]))
        for ids, shown in ((["thing"], {"thing": ["rm -rf /"]}), (["nope"], None), (["have"], None), (["page"], None), ([], None), ("thing", None)):
            with self.assertRaises(installer.InstallError, msg=ids):
                inst.install(ids, shown, start=False)
        self.assertEqual(inst.jobs, {})

    def test_timeout_stops_the_command(self):
        inst = self._installer(fake("thing", [f"{PY} -c \"import time; print('start', flush=True); time.sleep(60)\""]))
        job = inst.install(["thing"], None, start=False, timeout_s=1.5)
        t0 = time.time()
        job.run()
        self.assertLess(time.time() - t0, 20)
        self.assertEqual(job.state, "failed")
        self.assertIn("stopped after", job.steps[0]["message"])

    def test_cancel(self):
        inst = self._installer(fake("thing", [f"{PY} -c \"import time; print('start', flush=True); time.sleep(60)\""]), fake("next"))
        job = inst.install(["thing", "next"], None, start=True)
        t0 = time.time()
        while not any(l["text"] == "start" for l in job.public(0)["log"]) and time.time() - t0 < 20:
            time.sleep(0.05)
        with self.assertRaises(installer.InstallError):                    # one install at a time
            inst.install(["next"], None, start=False)
        job.cancel()
        while job.state == "running" and time.time() - t0 < 30:
            time.sleep(0.05)
        self.assertEqual(job.state, "cancelled")
        self.assertEqual([s["state"] for s in job.steps], ["cancelled", "cancelled"])

    def test_action_method_and_fake_mode(self):
        done = []
        marker = Path(self.tmp) / "edited.txt"
        inst = self._installer(fake("edit", marker=marker,
                                    methods=[Method("edit", "Edit a file", kind="action",
                                                    action=lambda: (done.append(1), marker.write_text("x", encoding="utf-8"), "edited")[2])]),
                               fake("thing", ["this-command-does-not-exist-anywhere"]))
        job = inst.install(["edit"], {"edit": []}, start=False)
        job.run()
        self.assertEqual((job.state, done), ("done", [1]))
        with mock.patch.dict(os.environ, {"FORM_INSTALL_FAKE": "0.5"}):
            job = inst.install(["thing"], None, start=False)
            job.run()
            texts = " ".join(l["text"] for l in job.public(0)["log"])
            self.assertEqual(job.state, "done")
            self.assertIn("FORM_INSTALL_FAKE", texts)
            self.assertIn("simulated", job.steps[0]["message"])
            self.assertTrue(job.public(0)["fake"])

    def test_login_job_surfaces_the_link_and_takes_a_code(self):
        script = Path(self.tmp) / "fake_claude.py"
        script.write_text("import sys\nprint('Opening browser to sign in')\n"
                          "print('If the browser did not open, visit: https://claude.ai/oauth/authorize?code=abc.', flush=True)\n"
                          "code = sys.stdin.readline().strip()\nprint('got ' + code, flush=True)\nsys.exit(0 if code == '1234' else 3)\n",
                          encoding="utf-8")
        job = installer.LoginJob(self.cfg, argv=[sys.executable, str(script)], timeout_s=30).start()
        t0 = time.time()
        while not job.url and time.time() - t0 < 20:
            time.sleep(0.05)
        self.assertEqual(job.url, "https://claude.ai/oauth/authorize?code=abc")
        self.assertEqual(job.public()["state"], "running")
        job.send_code("1234")
        while job.state == "running" and time.time() - t0 < 30:
            time.sleep(0.05)
        self.assertEqual(job.state, "done")
        self.assertIn("got 1234", job.lines)
        bad = installer.LoginJob(self.cfg, argv=[sys.executable, str(script)], timeout_s=30).start()
        while not bad.url and time.time() - t0 < 40:
            time.sleep(0.05)
        bad.cancel()
        while bad.state == "running" and time.time() - t0 < 50:
            time.sleep(0.05)
        self.assertEqual(bad.state, "cancelled")

    def test_auth_status_hides_account_details(self):
        out = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "someone@example.org", "orgName": "Org", "subscriptionType": "pro"})
        with mock.patch.object(installer, "_run", lambda cmd, timeout=20: (0, out)):
            a = installer.claude_auth({}, exe="/x/claude")
        self.assertTrue(a["signed_in"])
        self.assertNotIn("someone", json.dumps(a))
        self.assertNotIn("Org", json.dumps(a))
        with mock.patch.object(installer, "_run", lambda cmd, timeout=20: (1, "unknown command")):
            self.assertTrue(installer.claude_auth({}, exe="/x/claude")["unknown"])
        with mock.patch.object(installer, "find_claude", lambda cfg=None: None):
            self.assertFalse(installer.claude_auth({})["installed"])


TOML = """# my settings
[server]
port = 4173   # loopback

[slicer]
kind = "bambu"           # adapter
# app = "/somewhere"
machine = "auto"

[chat]
web = true  # lookups
budget_usd_per_message = 3.0

[custom]
keep = [1, 2,
        3]
"""


class ConfigWriteBack(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-cfg-"))
        self.path = self.tmp / "studio.toml"
        self.path.write_text(TOML, encoding="utf-8")
        self.cfg = cfg_for(str(self.tmp))
        os.environ.pop("FORM_CONFIG", None)

    def test_changes_only_the_keys_and_keeps_comments(self):
        r = config_edit.set_values(self.cfg, {"chat.web": "false", "slicer.kind": "orca", "printer.envelope_mm": "256x256x256",
                                              "chat.budget_usd_per_message": 1.5})
        new = self.path.read_text(encoding="utf-8")
        self.assertEqual(set(r["changed"]), {"chat.web", "slicer.kind", "printer.envelope_mm", "chat.budget_usd_per_message"})
        self.assertIn('kind = "orca"           # adapter', new)
        self.assertIn("web = false  # lookups", new)
        self.assertIn("# my settings", new)
        self.assertIn('# app = "/somewhere"', new)
        self.assertIn("port = 4173   # loopback", new)
        self.assertIn("keep = [1, 2,\n        3]", new)
        d = tomllib.loads(new)
        self.assertEqual(d["printer"]["envelope_mm"], [256, 256, 256])
        self.assertEqual(d["chat"]["budget_usd_per_message"], 1.5)
        self.assertEqual(d["custom"]["keep"], [1, 2, 3])
        old_lines, new_lines = TOML.splitlines(), new.splitlines()
        untouched = [l for l in old_lines if l in new_lines]
        self.assertEqual(len(old_lines) - len(untouched), 3)              # three lines rewritten, the rest identical
        # a backup of the previous file
        backup = Path(r["backup"])
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), TOML)
        # the running config follows
        self.assertEqual(self.cfg["slicer"]["kind"], "orca")
        self.assertFalse(self.cfg["chat"]["web"])

    def test_no_change_writes_nothing(self):
        r = config_edit.set_values(self.cfg, {"chat.web": True})
        self.assertEqual((r["changed"], r["backup"]), ({}, None))
        self.assertEqual(self.path.read_text(encoding="utf-8"), TOML)
        self.assertEqual(len(list(self.tmp.iterdir())), 1)

    def test_rejects_bad_values_and_unknown_keys(self):
        for k, v in (("nope.key", 1), ("chat.web", "maybe"), ("printer.envelope_mm", "1,2"), ("slicer.kind", "cura"),
                     ("chat.budget_usd_per_message", -1), ("data.dir", ""), ("printer.name", "a\nb"), ("server.port", 1)):
            with self.assertRaises(config_edit.ConfigError, msg=k):
                config_edit.set_values(self.cfg, {k: v})
        self.assertEqual(self.path.read_text(encoding="utf-8"), TOML)

    def test_invalid_file_is_left_alone_and_new_file_is_created(self):
        self.path.write_text("[chat\nweb = ", encoding="utf-8")
        with self.assertRaises(config_edit.ConfigError):
            config_edit.set_values(self.cfg, {"chat.web": False})
        self.assertEqual(self.path.read_text(encoding="utf-8"), "[chat\nweb = ")
        fresh = self.tmp / "new" / "studio.toml"
        r = config_edit.set_values(self.cfg, {"chat.model": "sonnet", "data.dir": str(self.tmp / "p")}, path=fresh)
        self.assertIsNone(r["backup"])
        self.assertTrue(r["restart"])
        d = tomllib.loads(fresh.read_text(encoding="utf-8"))
        self.assertEqual((d["chat"]["model"], d["data"]["dir"]), ("sonnet", str(self.tmp / "p")))
        self.assertEqual(self.cfg["data"]["dir"], str(self.tmp))          # the running engine keeps its folder until restart

    def test_set_text_edge_cases(self):
        t = config_edit.set_text("", "chat", "web", False)
        self.assertEqual(tomllib.loads(t), {"chat": {"web": False}})
        t = config_edit.set_text("[chat]\r\nmodel = 'opus'\r\n\r\n[x]\r\na = 1\r\n", "chat", "web", True)
        self.assertEqual(t, "[chat]\r\nmodel = 'opus'\r\nweb = true\r\n\r\n[x]\r\na = 1\r\n")
        t = config_edit.set_text('[printer]\nname = "A # B"  # c\n', "printer", "name", 'Say "hi"')
        self.assertEqual(tomllib.loads(t)["printer"]["name"], 'Say "hi"')
        self.assertTrue(t.rstrip().endswith("# c"))
        with self.assertRaises(config_edit.ConfigError):
            config_edit.set_text("[custom]\nkeep = [1,\n 2]\n", "custom", "keep", [1])

    def test_cli_get_set(self):
        out = []
        with mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))), \
             mock.patch.object(config, "load", lambda: self.cfg):
            self.assertEqual(config_edit.main(["set", "updates.check", "false"]), 0)
            self.assertEqual(config_edit.main(["get", "updates.check"]), 0)
            self.assertEqual(config_edit.main(["set", "nope", "1"]), 2)
            self.assertEqual(config_edit.main(["get"]), 0)
        self.assertIs(json.loads(out[1])["value"], False)
        self.assertIn("error", json.loads(out[2]))
        self.assertIn("chat.model", json.loads(out[3])["values"])
        self.assertIn("[updates]\ncheck = false", self.path.read_text(encoding="utf-8"))

    def test_describe_lists_every_setting(self):
        d = config_edit.describe(self.cfg)
        keys = {r["key"] for r in d["settings"]}
        self.assertEqual(keys, set(config_edit.SCHEMA))
        for want in ("data.dir", "slicer.kind", "slicer.machine", "printer.envelope_mm", "chat.model", "chat.web",
                     "chat.budget_usd_per_message", "updates.check", "bench.auto_open", "blender.app", "cad.openscad", "cad.freecad"):
            self.assertIn(want, keys)
        for r in d["settings"]:
            self.assertIn(r["tab"], ("general", "printer", "chat", "apps", "updates", "advanced", "software"))


class NoSeeding(unittest.TestCase):
    def test_fresh_data_folder_stays_empty(self):
        from form import studio as studio_mod
        with tempfile.TemporaryDirectory() as d:
            st = studio_mod.Studio(cfg_for(d))
            try:
                self.assertEqual(st.list(), [])
                self.assertEqual([p.name for p in Path(d).iterdir() if (p / "project.json").exists()], [])
                self.assertFalse(hasattr(st, "seed_examples") or hasattr(studio_mod, "add_examples"),
                                 "no examples ship with Form Studio")
                self.assertFalse((Path(studio_mod.__file__).parent / "examples").exists())
            finally:
                st.kernel.stop()

    def test_onboarding_step_is_remembered(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = cfg_for(d)
            self.assertEqual(setup_app.onboarding(cfg), {"step": 0, "done": False})
            setup_app.set_step(cfg, 2)
            self.assertEqual(setup_app.onboarding(cfg), {"step": 2, "done": False})
            setup_app.mark_seen(cfg, "done")
            self.assertTrue(setup_app.onboarding(cfg)["done"])


class Routes(unittest.TestCase):
    """What the app calls, through the real HTTP handler, with a fake registry."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from types import SimpleNamespace
        from form.server import make_handler
        cls.tmp = tempfile.mkdtemp(prefix="form-inst-http-")
        cfg = cfg_for(cls.tmp)
        cls.cfg = cfg
        cls.marker = Path(cls.tmp) / "installed.txt"
        cls.reg = mock.patch.object(installer, "REGISTRY", [
            fake("thing", [f"{PY} -c \"print('working'); open(r'{cls.marker}', 'w').close()\""], marker=cls.marker, level="recommended")])
        cls.reg.start()
        st = SimpleNamespace(cfg=cfg, root=Path(cls.tmp), chat=object(), activity=lambda *a, **k: None,
                             slicer_info=lambda refresh=False: {}, list=lambda: [])
        st.setup_app = setup_app.Setup(cfg)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.reg.stop()
        cls.httpd.shutdown()

    def call(self, method, path, body=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=30)
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse()
        out = r.status, json.loads(r.read())
        c.close()
        return out

    def test_install_flow(self):
        code, r = self.call("GET", "/api/install")
        self.assertEqual(code, 200)
        row = r["software"][0]
        self.assertTrue(row["default"] and row["installable"])
        code, e = self.call("POST", "/api/install", {"ids": ["thing"], "shown": {"thing": ["something else"]}})
        self.assertEqual(code, 409)                                         # not the command that was shown
        self.assertFalse(self.marker.exists())
        code, j = self.call("POST", "/api/install", {"ids": ["thing"], "shown": {"thing": row["plan"]["commands"]}})
        self.assertEqual(code, 200)
        t0 = time.time()
        while j["state"] == "running" and time.time() - t0 < 30:
            time.sleep(0.1)
            code, j = self.call("GET", f"/api/install/job/{j['id']}?from=0")
        self.assertEqual(j["state"], "done")
        self.assertIn("working", [l["text"] for l in j["log"]])
        self.assertEqual(j["after"]["thing"]["status"], "ok")
        self.assertEqual(self.call("GET", "/api/install/job/0000000000")[0], 404)
        self.assertEqual(self.call("POST", f"/api/install/job/{j['id']}/cancel", {})[0], 200)

    def test_config_step_and_capabilities_routes(self):
        code, c = self.call("GET", "/api/config")
        self.assertEqual(code, 200)
        self.assertIn("chat.model", [r["key"] for r in c["settings"]])
        with mock.patch.dict(os.environ, {"FORM_CONFIG": str(Path(self.tmp) / "studio.toml")}):
            code, r = self.call("POST", "/api/config", {"values": {"chat.model": "sonnet"}})
            self.assertEqual((code, r["changed"]), (200, {"chat.model": "sonnet"}))
            self.assertEqual(self.call("POST", "/api/config", {"values": {"chat.web": "perhaps"}})[0], 400)
        self.assertEqual(self.cfg["chat"]["model"], "sonnet")
        self.assertEqual(self.call("POST", "/api/setup/step", {"step": 1})[1]["step"], 1)
        self.assertEqual(self.call("GET", "/api/setup/state")[1]["onboarding"]["step"], 1)
        self.assertEqual(self.call("GET", "/api/examples")[0], 404, "no examples ship with Form Studio")
        code, c = self.call("GET", "/api/capabilities")
        self.assertEqual(code, 200)
        self.assertEqual([x["id"] for x in c["capabilities"]][-1], "print")
        self.assertNotIn("print", c["chosen"], "3D printing is off until it is chosen")
        with mock.patch.dict(os.environ, {"FORM_CONFIG": str(Path(self.tmp) / "studio.toml")}):
            code, r = self.call("POST", "/api/capabilities", {"id": "print", "on": True})
            self.assertEqual(code, 200)
            self.assertIn("print", r["chosen"])
            self.assertIn("general.capabilities", r["changed"])
            self.assertEqual(self.call("POST", "/api/capabilities", {"id": "banana", "on": True})[0], 400)
            code, r = self.call("POST", "/api/capabilities", {"capabilities": ["parts"]})
            self.assertEqual(r["chosen"], ["core", "parts"])
        self.assertEqual(self.call("POST", "/api/claude/login/0000000000/cancel", {})[0], 404)


class McpInstall(unittest.TestCase):
    def test_install_software_refuses_without_confirm(self):
        import asyncio
        from mcp import Client, StdioServerParameters
        root = Path(__file__).resolve().parents[1]

        def unwrap(res):
            body = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
            self.assertFalse(res.is_error, body)
            sc = res.structured_content
            if sc is None:
                return json.loads(body)
            return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc

        async def go():
            with tempfile.TemporaryDirectory() as d:
                env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(root), "FORM_SETUP_PRETEND_MISSING": "freecad",
                       "FORM_INSTALL_FAKE": "0.5"}                          # even a confirmed call here would install nothing
                params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env, cwd=str(root))
                async with Client(params) as c:
                    self.assertIn("install_software", {t.name for t in (await c.list_tools()).tools})
                    res = await c.call_tool("install_software", {"id": "freecad"})
                    out = unwrap(res)
                    self.assertFalse(out["installed"])
                    if "would_run" in out:                                  # a method exists on this machine
                        self.assertIn("confirm", out["refused"])
                        self.assertTrue(out["would_run"]["commands"])
                    else:                                                   # no package manager: it explains instead
                        self.assertIn("cannot install", out["error"]["message"])
                    res = await c.call_tool("install_software", {"id": "no-such-thing", "confirm": True})
                    out = unwrap(res)
                    self.assertFalse(out["installed"])
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
