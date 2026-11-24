"""The game asset in the app, loaded offscreen (QT_QPA_PLATFORM=offscreen): the Game asset sheet, its LOD switcher,
view modes, engine presets and Export, and Game asset as a purpose on Home and in the brief. The window is the real
interface (python -m form.app --check) over a real engine and data folder; a script run inside it looks the new
objectNames up and throws (a QML warning, so --check fails) when one is missing or does not behave.

Qt Quick 3D draws nothing offscreen, so this checks the interface, not pixels; the journey
tests/journeys/game_asset.py drives the visible window. Skipped without PySide6, or with FORM_SKIP_UI=1. With Blender
installed the asset is really built (a small cage, 1k, the fast bake); without it the install card must show."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "form" / "app" / "qml" / "Form"

PREP = textwrap.dedent("""
    import json, sys
    import numpy as np
    from form import config, meshsource
    from form.studio import Studio
    from form.game import pipeline


    def box(lo, hi, n=3):
        lo, hi = np.array(lo, float), np.array(hi, float)
        V, F, ids = [], [], {}
        def pid(i, j, k):
            if (i, j, k) not in ids:
                ids[(i, j, k)] = len(V); V.append(lo + (hi - lo) * np.array([i, j, k]) / n)
            return ids[(i, j, k)]
        for a in range(n):
            for b in range(n):
                F += [[pid(a, b, 0), pid(a, b + 1, 0), pid(a + 1, b + 1, 0), pid(a + 1, b, 0)],
                      [pid(a, b, n), pid(a + 1, b, n), pid(a + 1, b + 1, n), pid(a, b + 1, n)],
                      [pid(a, 0, b), pid(a + 1, 0, b), pid(a + 1, 0, b + 1), pid(a, 0, b + 1)],
                      [pid(a, n, b), pid(a, n, b + 1), pid(a + 1, n, b + 1), pid(a + 1, n, b)],
                      [pid(0, a, b), pid(0, a, b + 1), pid(0, a + 1, b + 1), pid(0, a + 1, b)],
                      [pid(n, a, b), pid(n, a + 1, b), pid(n, a + 1, b + 1), pid(n, a, b + 1)]]
        return meshsource.cage(np.array(V), F, [], {})


    if __name__ == "__main__":
        st = Studio(config.load())
        p = st.create_design("Crate", pipeline.cage_design_source(box((0, 0, 0), (40, 30, 20)), "Crate"), purpose="game")
        from form.game import app
        built = False
        if app.software(st.cfg)["blender"]:
            app.build(st, p["id"], {"preset": "gltf", "texture_px": 1024, "bake": "fast", "budgets": [800, 400, 200, 60]})
            built = True
        st.kernel.stop()
        print(json.dumps({"id": p["id"], "built": built}))
""")

# runs in Main.qml (its scope is the window): opens the sheet, then checks after the engine answered
CHECK = textwrap.dedent("""
    (function () {
        var win = this
        function find(it, n) {
            if (!it) return null
            if (it.objectName === n) return it
            var ch = it.children || []
            for (var i = 0; i < ch.length; i++) { var r = find(ch[i], n); if (r) return r }
            if (it.contentItem && it.contentItem !== it) return find(it.contentItem, n)
            return null
        }
        function need(names) {
            var miss = names.filter(function (n) { return !find(win.contentItem, n) })
            if (miss.length) throw new Error("GAMEUI missing objectNames: " + miss.join(", "))
        }
        function later(ms, fn) {
            var t = Qt.createQmlObject("import QtQuick; Timer { interval: " + ms + " }", win)
            t.triggered.connect(function () { try { fn() } catch (e) { console.warn("GAMEUI " + e); throw e } })
            t.start()
        }
        Store.setNewPurpose("game")
        if (Store.newPurpose !== "game") throw new Error("GAMEUI Home cannot pick Game asset")
        Store.setNewPurpose("any")
        Store.openSheet("game")
        later(2500, function () {
            need(["gameSheet", "gamePreset", "gameTexture", "gameViewport", "gameBuild", "gameExport"])
            if (BUILT) {
                need(["lodBar", "lod0", "lod1", "lod2", "lod3", "gameView", "gameWire", "gameStatus"])
                if (!Store.gameAsset || Store.gameAsset.lods.length !== 4) throw new Error("GAMEUI the last asset was not loaded")
                if (!Store.gameAsset.validation.ok) throw new Error("GAMEUI the built asset failed a check")
                var sheet = find(win.contentItem, "gameSheet")
                sheet.mode = "channel"; sheet.wire = true
                Store.showGameLod(2)
            } else {
                need(["gameInstall"])
                if (!find(win.contentItem, "gameInstall").visible) throw new Error("GAMEUI no install card without Blender")
            }
        })
        later(5000, function () {
            if (!BUILT) { console.warn("GAMEUI done"); return }
            need(["gameChannel"])
            if (Store.gameLod !== 2 || !Store.gameLods[Store.gameAsset.key + ":2"]) throw new Error("GAMEUI LOD2 was not loaded")
            var m = Store.gameLods[Store.gameAsset.key + ":2"]
            if (!(m.triangles <= 200 * 1.02) || !m.wire || !m.uvs) throw new Error("GAMEUI LOD2 payload " + JSON.stringify(Object.keys(m)))
            var vp = find(win.contentItem, "gameViewport")
            if (!vp.game || vp.game.lod !== 2 || vp.gameMode !== "channel" || !vp.model.edges) throw new Error("GAMEUI the viewport did not follow")
            console.warn("GAMEUI done")
        })
    }).call(this)
""")


def _why_not() -> str:
    if os.environ.get("FORM_SKIP_UI") == "1":
        return "FORM_SKIP_UI=1"
    if importlib.util.find_spec("PySide6") is None:
        return "PySide6 is not installed"
    return ""


class GameUiStatic(unittest.TestCase):
    """Without Qt: the files exist, are registered and keep to the theme."""

    def test_files_are_registered(self):
        qmldir = (QML / "qmldir").read_text(encoding="utf-8")
        for c in ("GameSheet", "LodBar"):
            self.assertTrue((QML / f"{c}.qml").is_file(), c)
            self.assertIn(f"{c} 1.0 {c}.qml", qmldir)
        self.assertIn('game: "GameSheet.qml"', (QML / "SheetHost.qml").read_text(encoding="utf-8"))
        self.assertTrue((QML / "shaders" / "game.frag").is_file())

    def test_no_hard_coded_colours(self):
        import re
        for f in ("GameSheet.qml", "LodBar.qml"):
            text = (QML / f).read_text(encoding="utf-8")
            self.assertFalse(re.findall(r'"#[0-9a-fA-F]{3,8}"', text), f"{f}: colours come from Theme (light and dark)")

    def test_purpose_is_offered_everywhere(self):
        home, brief, store = ((QML / f).read_text(encoding="utf-8") for f in ("Home.qml", "Brief.qml", "Store.qml"))
        self.assertIn('value: "game", text: "Game asset"', home)
        self.assertIn('value: "game", text: "Game asset"', brief)
        self.assertIn('p === "game"', store)


@unittest.skipIf(_why_not(), _why_not())
class GameUiOffscreen(unittest.TestCase):
    def test_game_sheet_offscreen(self):
        with tempfile.TemporaryDirectory(prefix="form-gameui-") as tmp:
            env = dict(os.environ, FORM_DATA=str(Path(tmp) / "data"), FORM_CONFIG=str(Path(tmp) / "studio.toml"),
                       FORM_NO_UPDATE_CHECK="1", FORM_NO_AUTO_SETUP="1", FORM_PROVIDERS_OFFLINE="1",
                       FORM_SECRETS=str(Path(tmp) / "secrets.json"), PYTHONPATH=str(ROOT), QT_QPA_PLATFORM="offscreen")
            (Path(tmp) / "data").mkdir()
            (Path(tmp) / "data" / ".form-setup.json").write_text(json.dumps({"ts": 1, "version": "test", "how": "done"}))
            prep = Path(tmp) / "prep.py"
            prep.write_text(PREP, encoding="utf-8")
            r = subprocess.run([sys.executable, str(prep)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
            self.assertEqual(r.returncode, 0, r.stderr[-3000:])
            info = json.loads(r.stdout.strip().splitlines()[-1])
            js = CHECK.replace("BUILT", "true" if info["built"] else "false")
            r = subprocess.run([sys.executable, "-m", "form.app", "--check", "--project", info["id"], "--wait", "4000",
                                "--eval", js, "--after", "7000"], cwd=ROOT, env=env, capture_output=True, text=True,
                               timeout=600)
            out = r.stdout + r.stderr
            self.assertIn("GAMEUI done", out, out[-4000:])
            self.assertNotIn("GAMEUI missing", out, out[-4000:])
            self.assertEqual(r.returncode, 0, out[-4000:])


if __name__ == "__main__":
    unittest.main()
