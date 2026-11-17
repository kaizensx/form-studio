"""The workspace redesign: static checks on the QML that do not need a display."""
import os
import re
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "form" / "app" / "qml" / "Form"


def read(name):
    return (FORM / name).read_text(encoding="utf-8")


class WorkspaceUi(unittest.TestCase):
    def test_singletons_are_registered(self):
        qmldir = read("qmldir")
        for name in ("Motion", "Ws"):
            self.assertIn(f"singleton {name} 1.0 {name}.qml", qmldir)
            self.assertTrue((FORM / f"{name}.qml").exists())

    def test_local_components_exist(self):
        for name in ("RailBtn", "HudBar", "HudSlider", "Tick", "Fold"):
            self.assertTrue((FORM / f"{name}.qml").exists(), name)
        for shader in ("clay.frag", "ground.frag"):
            self.assertTrue((FORM / "shaders" / shader).exists(), shader)

    def test_store_calls_made_by_the_workspace_exist(self):
        store = read("Store.qml")
        defined = set(re.findall(r"^\s*function (\w+)\(", store, re.M)) | set(re.findall(r"^\s*signal (\w+)\(", store, re.M))
        used = set()
        for f in ("Workspace.qml", "Timeline.qml", "Pipeline.qml", "ContextMenu.qml", "MeasurePanel.qml", "Prove.qml", "Release.qml", "Brief.qml"):
            used |= set(re.findall(r"Store\.(\w+)\(", read(f)))
        self.assertFalse(used - defined, sorted(used - defined))

    def test_every_clay_material_declares_the_shader_uniforms(self):
        vp = read("Viewport.qml")
        self.assertEqual(vp.count('fragmentShader: "shaders/clay.frag"'), vp.count("property color uRim"))

    def test_motion_stays_within_the_budget(self):
        theme, motion = read("Theme.qml"), read("Motion.qml")           # one token set: Theme; Motion only renames it
        for name, limit in (("press", 320), ("ui", 320), ("cross", 320), ("part", 320), ("camera", 450)):
            m = re.search(rf"readonly property int {name}: (\d+)", theme)
            self.assertIsNotNone(m, name)
            self.assertLessEqual(int(m.group(1)), limit, name)
        self.assertNotRegex(motion, r"readonly property int \w+: \d", "Motion.qml must not define durations of its own")
        self.assertIn("readonly property bool reduced: Theme.reduced", motion)

    def test_reduced_motion_reads_the_environment(self):
        from form.app import main
        with mock.patch.dict(os.environ, {"FORM_REDUCED_MOTION": "1"}):
            self.assertTrue(main._reduced_motion())
        with mock.patch.dict(os.environ, {"FORM_REDUCED_MOTION": "0"}):
            self.assertFalse(main._reduced_motion())

    def test_honesty_labels_survive_the_reorganisation(self):
        prove, release = read("Prove.qml"), read("Release.qml")
        self.assertIn('tag: "simulated"', prove)
        self.assertIn("It is not a print", prove)
        self.assertIn("cr.modelData.evidence", prove)
        self.assertIn("pr.modelData.evidence", prove)
        self.assertEqual(release.count('note: "not a release"'), 2)
        self.assertIn("evidence_level", release)
        self.assertIn("Not a strength analysis", "Not a strength analysis" if "legend.not" in read("AnalysisLegend.qml") else "")


if __name__ == "__main__":
    unittest.main()
