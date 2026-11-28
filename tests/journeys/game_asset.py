"""A game asset, the way a person makes one: on Home they pick "Make it for: Game asset" and describe it; the stand-in
agent (tests/fixtures/fake_agent.py, "game crate") makes a subdivision cage design through the real create_design
tool, and the design opens with the purpose "game". From the rail they open Game asset, build it (in the real
Blender, 1k textures, the fast bake), switch between the four LODs (each with its triangle count against its budget),
look at the shaded view with and without its baked normal map, the UV checker, the normal map itself and the
wireframe, pick the Unreal preset and export: the zip holds the FBX in centimetres and collision hulls named after the
LOD0 render mesh (UCX_<asset>_LOD0_NN).

Without Blender the sheet shows the one-click install card instead, and the build steps are skipped (said so).
Run in both appearances (FORM_APPEARANCE=dark, light); screenshots go to $FORM_UI_SHOTS."""
import json
import zipfile

from _lib import tool

DATA = "fresh"
S = {}


def _tag(ui):
    return "light" if ui.js("Theme.dark") is False else "dark"


def journey_pick_game_asset_and_describe_it(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.exists("startComposer"), 30, "Home and its composer")
    ui.wait_until(lambda: ui.js("Store.chatReady"), 20, "the stand-in agent")
    ui.settle(400)
    seg = ui.item("startPurpose")
    ui.click_text("Game asset", within=seg)
    ui.wait_until(lambda: ui.js("Store.newPurpose") == "game", 3, "Game asset to be picked on Home")
    ui.shot(f"game-{_tag(ui)}-1-home-purpose")
    ui.click("startText")
    ui.type("A game crate for a dungeon level")
    ui.key("Return")
    ui.wait_until(lambda: ui.js("Store.screen === 'work' && !!Store.pid && !!Store.view"), 240, "the design to open")
    ui.wait_until(lambda: ui.js("Store.purpose") == "game", 30, "the design to have the purpose game")
    ui.wait_until(lambda: ui.store.get("chatBusy") is False, 60, "the reply to end")
    ui.settle(600)
    S["pid"] = ui.store.get("pid")
    ui.shot(f"game-{_tag(ui)}-2-design")


def journey_build_switch_lods_and_look(ui):
    ui.click("stage-release")                        # Game asset is a tool of Make
    ui.wait_until(lambda: ui.js("Store.mode") == "release", 3, "Make")
    tool(ui, "game")
    ui.wait_until(lambda: ui.exists("gameSheet"), 5, "the Game asset sheet")
    ui.wait_until(lambda: ui.js("!!Store.game"), 30, "what the engine says about the game asset")
    if not ui.js("Store.game.software.blender"):
        ui.check(ui.exists("gameInstall"), "without Blender the sheet shows the one-click install card")
        ui.shot(f"game-{_tag(ui)}-3-install-card")
        print("  Blender is not installed: the build, LOD and export steps are skipped", flush=True)
        S["skip"] = True
        return
    ui.click("gameBuild")
    ui.wait_until(lambda: ui.js("!!Store.gameAsset && !Store.gameBusy"), 600, "the asset to be built in Blender")
    a = ui.js("Store.gameAsset")
    ui.check(a["validation"]["ok"], f"every check passes: {a['validation']['failed']}")
    ui.eq(len(a["lods"]), 4, "four LODs")
    for r in a["lods"]:
        ui.check(r["triangles"] <= r["budget"] * 1.02, f"LOD{r['lod']} within its budget: {r}")
    tex = ui.item("gameViewport").property("gameTex").toVariant() if hasattr(ui.item("gameViewport").property("gameTex"), "toVariant") \
        else ui.item("gameViewport").property("gameTex")
    ui.check(tex and all(str(tex.get(m, "")).startswith("file:") for m in ("base_color", "normal", "orm", "ao")),
             f"the viewport reads the four baked maps as local files: {tex}")
    ui.wait_until(lambda: ui.exists("lod3"), 10, "the LOD switcher")
    ui.wait_until(lambda: ui.js("!!Store.gameLods[Store.gameAsset.key + ':0']"), 30, "LOD0 to be drawn")
    ui.settle(900)
    ui.shot(f"game-{_tag(ui)}-3-lod0-shaded")
    # the baked normal map in the shaded view (tangent space), then without it: the LOD's own normals
    ui.check(ui.item("gameViewport").property("gameNormalMap") is True, "the shaded view applies the normal map")
    ui.click("gameNormalMap")
    ui.wait_until(lambda: ui.item("gameViewport").property("gameNormalMap") is False, 5, "the normal map to be off")
    ui.settle(700)
    ui.shot(f"game-{_tag(ui)}-3b-lod0-shaded-no-normal-map")
    ui.click("gameNormalMap")
    ui.wait_until(lambda: ui.item("gameViewport").property("gameNormalMap") is True, 5, "the normal map to be on again")
    ui.settle(300)
    for i in (1, 3):
        ui.click(f"lod{i}")
        ui.wait_until(lambda: ui.js(f"Store.gameLod === {i} && !!Store.gameLods[Store.gameAsset.key + ':{i}']"), 30, f"LOD{i}")
        ui.wait_until(lambda: ui.js(f"(function () {{ var v = Store.gameLods[Store.gameAsset.key + ':{i}']; return !!v }})()"), 5)
        ui.settle(500)
        tri = ui.js(f"Store.gameLods[Store.gameAsset.key + ':{i}'].triangles")
        ui.check(tri <= a["lods"][i]["budget"] * 1.02, f"LOD{i} drawn with {tri} triangles")
        ui.shot(f"game-{_tag(ui)}-4-lod{i}")
    ui.click("lod0")
    ui.wait_until(lambda: ui.js("Store.gameLod === 0"), 5)
    view = ui.item("gameView")
    ui.click_text("UV checker", within=view)
    ui.wait_until(lambda: ui.js("Store.sheet && Store.sheet.kind === 'game'") and ui.item("gameViewport").property("gameMode") == "checker", 5, "the UV checker")
    ui.settle(500)
    ui.shot(f"game-{_tag(ui)}-5-uv-checker")
    ui.click_text("Maps", within=view)
    ui.wait_until(lambda: ui.item("gameViewport").property("gameMode") == "channel" and ui.exists("gameChannel"), 5, "the map picker")
    ui.settle(300)                                       # laid out below the view modes before it is clicked
    ui.click_text("Normal", within=ui.item("gameChannel"))
    ui.wait_until(lambda: ui.item("gameViewport").property("gameChannel") == "normal", 5, "the normal map")
    ui.settle(700)
    ui.shot(f"game-{_tag(ui)}-6-normal-map")
    ui.click_text("Shaded", within=view)
    ui.click("gameWire")
    ui.wait_until(lambda: ui.js("(function () { var v = Store.gameLods[Store.gameAsset.key + ':0']; return !!v && !!v.wire })()"), 5)
    ui.settle(600)
    ui.shot(f"game-{_tag(ui)}-7-wireframe")


def journey_export_for_unreal(ui):
    if S.get("skip"):
        return
    ui.click_text("Unreal", within=ui.item("gamePreset"))
    ui.click("gameExport")
    zp = ui.saved(f"{S['pid']}-unreal.zip", 600)
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        rep = json.loads(z.read(next(n for n in names if n.endswith("/report.json"))))
    ui.check(any(n.endswith(".fbx") for n in names), f"the zip holds the FBX: {names}")
    ui.eq(rep["preset"]["id"], "unreal", "built with the Unreal preset")
    ui.eq(rep["preset"]["unit"], "cm", "in centimetres")
    lod0 = next(l for l in rep["lods"] if l["lod"] == 0)
    ui.check(lod0["triangles"] <= lod0["budget"] * 1.02, "LOD0 within its budget")
    asset = rep["asset"]
    hulls = rep["collision"]["names"]
    ui.check(hulls and all(h.startswith(f"UCX_{asset}_LOD0_") for h in hulls),
             f"collision hulls are named after the exported LOD0 render mesh: {hulls}")
    fbx = next(e for e in rep["exports"] if e["format"] == "fbx")
    ui.check(f"{asset}_LOD0" in fbx["reimport"]["objects"] or any(o.startswith(f"{asset}_LOD0") for o in fbx["reimport"]["objects"]),
             f"the FBX holds the render mesh the hulls name: {fbx['reimport']['objects']}")
    ui.check(rep["validation"]["ok"], "every check passes for Unreal too")
    ui.settle(600)
    ui.shot(f"game-{_tag(ui)}-8-exported-unreal")
    ui.key("Escape")
    ui.wait_until(lambda: not ui.exists("gameSheet"), 5, "the sheet to close")
    ui.no_warnings()
