"""The pro frame's catalogue of tools (form/app/qml/Form/ToolSet.js) against the app and the engine, without a window:
every icon is in the icon font's map, every tool is either run by Workspace.qml or waits for an engine (a feature kind
or a Bench entry that exists), and the engine says which feature kinds it builds."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "form" / "app" / "qml" / "Form"


def catalogue() -> dict:
    src = (QML / "ToolSet.js").read_text(encoding="utf-8")
    body = src[src.index("var MODES = ") + len("var MODES = "):src.index("\n// the four tools")]
    # the catalogue is written as JSON with bare keys: quote them, then read it
    js = re.sub(r"([{,]\s*)([a-z_]+):", r'\1"\2":', body)
    return json.loads(js)


class ToolSet(unittest.TestCase):
    def test_four_modes_with_captioned_groups(self):
        m = catalogue()
        self.assertEqual(sorted(m), ["document", "prove", "release", "shape"])
        for mode, groups in m.items():
            for g in groups:
                self.assertTrue(g["caption"] and g["tools"], (mode, g["id"]))

    def test_every_icon_is_in_the_font_map(self):
        names = set(re.findall(r'"([a-z0-9_]+)": "', (QML / "Icons.qml").read_text(encoding="utf-8")))
        for mode, groups in catalogue().items():
            for g in groups:
                for t in g["tools"]:
                    self.assertIn(t["icon"], names, (mode, t["id"]))

    def test_every_tool_runs_or_waits_for_its_engine(self):
        ws = (QML / "Workspace.qml").read_text(encoding="utf-8")
        from form import studies
        bench = {s.id for s in studies.registry()}
        for mode, groups in catalogue().items():
            for g in groups:
                for t in g["tools"]:
                    need = t.get("need") or {}
                    if "bench" in need:
                        self.assertTrue(set(need["bench"]) & bench, f"{t['id']}: no Bench entry {need['bench']}")
                    elif "kind" not in need:
                        self.assertIn('"%s"' % t["id"], ws, f"{t['id']} is not run by Workspace.qml")

    def test_the_engine_lists_its_feature_kinds(self):
        from form import modelling, server
        kinds = server._feature_kinds()
        self.assertEqual(kinds[:len(modelling.KINDS)], list(modelling.KINDS))
        # the tools that wait for a kind name one the engine does not have yet, or one it has: never a typo of a
        # kind it has under another name
        waiting = [k for gs in catalogue().values() for g in gs for t in g["tools"] for k in (t.get("need") or {}).get("kind", [])]
        self.assertTrue(waiting)
        for k in waiting:
            self.assertRegex(k, r"^[a-z_]+$")


if __name__ == "__main__":
    unittest.main()
