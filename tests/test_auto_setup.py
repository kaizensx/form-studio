"""Hands-free setup (form/installer.py AutoJob): installs what is needed without questions, pauses only where the
person must act, notices when that is done and continues; Skip and Cancel. Nothing is installed: the commands are
Python one-liners and "detection" is a marker file."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from form import installer, setup_app
from form.installer import Found, Method
from test_installer import PY, cfg_for, fake


def wait(pred, secs=10):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred():
            return True
        time.sleep(0.05)
    return False


class Auto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="form-auto-")
        self.cfg = cfg_for(self.tmp)
        for k in ("FORM_INSTALL_FAKE", "FORM_SETUP_PRETEND_MISSING"):
            p = mock.patch.dict(os.environ, {}, clear=False)
            p.start()
            self.addCleanup(p.stop)
            os.environ.pop(k, None)

    def registry(self, *entries):
        p = mock.patch.object(installer, "REGISTRY", list(entries))
        p.start()
        self.addCleanup(p.stop)
        return installer.Installer(self.cfg)

    def test_auto_ids_takes_what_form_needs_and_never_other_agents(self):
        rows = [{"id": "kernel", "level": "required", "status": "missing", "group": "engine", "one_of": ""},
                {"id": "parts", "level": "recommended", "status": "ok", "group": "engine", "one_of": ""},
                {"id": "slicer.bambu", "level": "recommended", "status": "missing", "group": "slicer", "one_of": "slicer"},
                {"id": "claude", "level": "recommended", "status": "missing", "group": "ai", "one_of": ""},
                {"id": "agent.codex", "level": "recommended", "status": "missing", "group": "agents", "one_of": ""},
                {"id": "openscad", "level": "optional", "status": "missing", "group": "cad", "one_of": ""}]
        self.assertEqual(installer.auto_ids(rows), ["kernel", "slicer.bambu", "claude"])
        rows.append({"id": "slicer.orca", "level": "optional", "status": "ok", "group": "slicer", "one_of": "slicer"})
        self.assertEqual(installer.auto_ids(rows), ["kernel", "claude"])             # one slicer is enough

    def test_installs_without_asking_and_skips_what_is_there(self):
        marker = Path(self.tmp) / "a.txt"
        inst = self.registry(fake("a", [f"{PY} -c \"open(r'{marker}', 'w').close()\""], marker=marker, level="recommended", group="engine"),
                             fake("b", found=[Found("ok", "here")], level="recommended", group="engine"))
        job = inst.auto(["a", "b"], start=False)
        job.run()
        p = job.public()
        self.assertEqual(p["state"], "done")
        self.assertEqual([(s["id"], s["state"]) for s in p["steps"]], [("a", "done"), ("b", "done")])
        self.assertEqual(p["steps"][1]["message"], "already there")
        self.assertEqual(p["steps"][0]["commands"][0][:len(PY)], PY)                # the command is shown with the step
        self.assertEqual(p["log"][0]["kind"], "cmd")
        self.assertTrue(marker.exists())

    def test_pauses_for_a_download_then_continues_when_it_appears(self):
        marker = Path(self.tmp) / "app-installed"
        page = [Method("download", "Open the official download page", kind="open", url="https://example.invalid/get")]
        inst = self.registry(fake("app", methods=page, marker=marker, label="Some App", group="slicer"))
        job = inst.auto(["app"], start=False, poll_s=0.05)
        threading.Thread(target=job.run, daemon=True).start()
        self.assertTrue(wait(lambda: job.public()["waiting_for_you"] is not None), "it waits for the person")
        w = job.public()["waiting_for_you"]
        self.assertEqual((w["id"], w["action"]["kind"], w["action"]["url"]), ("app", "download", "https://example.invalid/get"))
        self.assertEqual(job.state, "running")
        marker.write_text("x")                                                       # the person installed it
        self.assertTrue(wait(lambda: job.state != "running"))
        self.assertEqual((job.state, job.steps[0]["state"]), ("done", "done"))
        self.assertIsNone(job.public()["waiting_for_you"])

    def test_a_failed_command_falls_back_to_waiting_for_the_page(self):
        marker = Path(self.tmp) / "x"
        ms = [Method("cmd", "Test", commands=[f"{PY} -c \"import sys; sys.exit(3)\""]),
              Method("download", "Page", kind="open", url="https://example.invalid/x")]
        inst = self.registry(fake("x", methods=ms, marker=marker, group="slicer"))
        job = inst.auto(["x"], start=False, poll_s=0.05)
        threading.Thread(target=job.run, daemon=True).start()
        self.assertTrue(wait(lambda: job.public()["waiting_for_you"] is not None))
        self.assertIn("did not work", job.public()["waiting_for_you"]["action"]["text"])
        job.skip("x")
        self.assertTrue(wait(lambda: job.state != "running"))
        self.assertEqual(job.steps[0]["state"], "skipped")
        self.assertEqual(job.state, "done")                                          # skipping is not a failure

    def test_cancel_while_waiting(self):
        page = [Method("download", "Page", kind="open", url="https://example.invalid/y")]
        inst = self.registry(fake("y", methods=page, group="slicer"), fake("z", group="slicer"))
        job = inst.auto(["y", "z"], start=False, poll_s=0.05)
        threading.Thread(target=job.run, daemon=True).start()
        self.assertTrue(wait(lambda: job.public()["waiting_for_you"] is not None))
        job.cancel()
        self.assertTrue(wait(lambda: job.state != "running"))
        self.assertEqual(job.state, "cancelled")
        self.assertEqual([s["state"] for s in job.steps], ["cancelled", "cancelled"])

    def test_signin_waits_for_the_login_job(self):
        sw = installer.Software("claude.signin", "Claude sign-in", "x", "recommended", "ai",
                                lambda cfg, ctx: Found("missing", "no"), lambda platform, ctx: [Method("login", "Sign in", kind="login")])
        inst = self.registry(sw)

        class FakeLogin:
            id, url, state, message = "abcdef0123", "https://claude.ai/oauth?x", "running", ""
            def cancel(self):
                self.state = "cancelled"
        lj = FakeLogin()
        inst.login = lambda start=True: lj
        job = inst.auto(["claude.signin"], start=False, poll_s=0.05)
        threading.Thread(target=job.run, daemon=True).start()
        self.assertTrue(wait(lambda: job.public()["waiting_for_you"] is not None))
        a = job.public()["waiting_for_you"]["action"]
        self.assertEqual((a["kind"], a["url"], a["login"]), ("signin", "https://claude.ai/oauth?x", "abcdef0123"))
        lj.state, lj.message = "failed", "Sign-in was not finished in time."
        self.assertTrue(wait(lambda: job.state != "running"))
        self.assertEqual((job.state, job.steps[0]["message"]), ("failed", "Sign-in was not finished in time."))

    def test_routes(self):
        inst = self.registry(fake("q", found=[Found("ok", "here")], level="required", group="engine"))

        class St:
            cfg = self.cfg
            def activity(self, *a, **k):
                pass
        st = St()
        st.setup_app = mock.Mock(installer=inst)
        with mock.patch.dict(os.environ, {"FORM_NO_AUTO_SETUP": "1"}):
            self.assertFalse(setup_app.route_get(st, "/api/install/auto", {})["enabled"])
        j = setup_app.route_post(st, "/api/install/auto", {"ids": ["q"]})
        self.assertEqual(j["kind"], "auto")
        self.assertTrue(wait(lambda: inst.job(j["id"]).state != "running"))
        self.assertEqual(setup_app.route_post(st, f"/api/install/job/{j['id']}/skip", {"id": "q"})["state"], "done")

    def test_headless_run_auto_skips_what_needs_the_person(self):
        page = [Method("download", "Page", kind="open", url="https://example.invalid/w")]
        self.registry(fake("w", methods=page, group="slicer", level="recommended"))
        lines = []
        job = installer.run_auto(self.cfg, echo=lines.append, wait=False, poll_s=0.05)
        self.assertEqual((job.state, job.steps[0]["state"]), ("done", "skipped"))
        self.assertTrue(any("Waiting for you" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
