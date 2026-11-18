"""Sharing recipes and feedback while the engine works: a button's busy state and the activity bar during a slow
action; a recipe exported as a .formrecipe and imported again after review; the community submission (the folder,
and the pre-filled GitHub issue opened only by its button); a design turned into a recipe."""
import io
import json
import os
import time
import urllib.parse
import zipfile
from pathlib import Path

from _lib import open_sheet_wait, sheet, wait_job

DATA = "fresh"
CLIP = (Path(__file__).resolve().parents[2] / "community" / "recipes" / "cable-clip" / "recipe.py").read_text(encoding="utf-8")


def home(ui):
    ui.wait_until(lambda: ui.store.get("screen") in ("home", "work"), 30, "the window")
    if ui.store.get("screen") == "work":
        ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")


def journey_busy_feedback(ui):
    """A slow action: the button shows a spinner and its busy label, ignores more clicks, and the bar names the work."""
    home(ui)
    ui.settle(300)
    ui.run_js("""
        var b = Qt.createQmlObject('import QtQuick; import Form; Btn { objectName: "fakeSlow"; x: 520; y: 240; kind: "primary"; icon: "play"; text: "Run it"; busyText: "Running…"; property int clicks: 0 }', win.contentItem)
        b.z = 999
        b.clicked.connect(function () {
            b.clicks++
            b.run(function () { return Store.act("Running a slow test action", new Promise(function (res) {
                var t = Qt.createQmlObject('import QtQuick; Timer { interval: 1600; running: true }', b)
                t.triggered.connect(function () { res(true); t.destroy() }) })) })
        })""")
    btn = ui.item("fakeSlow")
    t0 = time.time()
    ui.click(btn)
    ui.wait_until(lambda: btn.property("showsBusy"), 1.0, "the spinner on the button")
    shown_after = time.time() - t0
    ui.check(shown_after < 0.6, f"busy within {shown_after:.2f} s of the click")
    ui.eq(btn.property("label"), "Running…")
    ui.check(ui.find(name="btnSpinner", within=btn) is not None, "a spinner replaces the icon")
    ui.click(btn)                                       # a second click while busy does nothing
    ui.eq(btn.property("clicks"), 1, "presses ignored while busy")
    ui.wait_until(lambda: ui.js("Store.activity.length") > 0, 2, "the activity bar")
    ui.wait_until(lambda: ui.item("activityLabel").property("text") == "Running a slow test action…", 2, "the work named in the bar")
    ui.shot("busy-button-and-activity-bar")
    ui.wait_until(lambda: not btn.property("showsBusy"), 4, "the button to come back")
    ui.check(time.time() - t0 >= 1.5, "busy for as long as the work ran")
    ui.wait_until(lambda: ui.js("Store.activity.length") == 0, 3, "the bar to clear")
    ui.wait_until(lambda: any("Running a slow test action" in t["msg"] for t in ui.store.get("toasts")), 2, "a toast when it finished")
    # a quick answer never flashes: the spinner waits a moment before it shows
    ui.run_js("""var q = Qt.createQmlObject('import QtQuick; import Form; Btn { objectName: "fakeQuick"; x: 520; y: 300; text: "Quick" }', win.contentItem); q.z = 999
        q.clicked.connect(function () { q.run(function () { return Promise.resolve(1) }) })""")
    quick = ui.item("fakeQuick")
    ui.click(quick)
    ui.settle(250)
    ui.check(not quick.property("showsBusy"), "an instant answer shows no spinner")
    for b in (btn, quick):
        b.setVisible(False)
        b.deleteLater()
    ui.settle(200)


def _mine(ui):
    return ui.api("/recipes/library?section=mine")["items"]


def journey_export_and_import_a_recipe(ui):
    home(ui)
    from form import recipe_lib
    m = recipe_lib.install(ui.studio.root, CLIP, "python", recipe_lib.sha256(CLIP), {"title": "Cable clip"})
    ui.click_text("New design")
    open_sheet_wait(ui, "new")
    card = ui.item("sheetCard")
    ui.click_text("Mine", within=card, exact=False)
    ui.item(text="Cable clip", within=card, timeout=10)
    ui.click_text("Cable clip", within=card)
    ui.click("recipeShareBtn")
    open_sheet_wait(ui, "shareRecipe")
    # the preview is drawn from a real build: busy feedback while the kernel works, then the picture
    ui.wait_until(lambda: ui.item("sharePreview").property("ready"), 180, "the preview from the build")
    ui.fill("shareAuthor", "maker-1")
    ui.click_text("Apply changes")
    ui.wait_until(lambda: json.loads((Path(ui.studio.root) / ".recipes" / f"{m['id']}.json").read_text())["author"] == "maker-1", 30, "the author kept")
    ui.wait_until(lambda: ui.item("sharePkgSave").property("enabled"), 30, "ready to save")
    ui.settle(400)
    ui.shot("share-as-file")
    ui.click("sharePkgSave")
    pkg = ui.saved(f"{m['id']}.formrecipe", 30)
    z = zipfile.ZipFile(pkg)
    ui.eq(sorted(z.namelist()), ["meta.json", "preview.png", "recipe.py"])
    meta = json.loads(z.read("meta.json"))
    ui.eq(meta["author"], "maker-1")
    ui.eq(meta["sha256"], recipe_lib.sha256(CLIP))

    # someone else opens it: remove ours, then install from the file after reviewing it
    ui.api("/recipes/uninstall", {"id": m["id"]})
    ui.eq(_mine(ui), [], "nothing in Mine")
    ui.run_js('Store.openSheet("new", { tab: "recipe", section: "mine" })')
    open_sheet_wait(ui, "new")
    ui.pick_file(pkg)
    ui.click("installRecipeFile")
    open_sheet_wait(ui, "recipe")
    ui.expect("matches meta.json")
    ui.expect(meta["sha256"])
    ui.wait_until(lambda: ui.item("recipePreview").property("ready"), 10, "the package's preview")
    ui.eq(_mine(ui), [], "nothing installed before Install")
    ui.settle(300)
    ui.shot("package-review")
    ui.click("recipeInstall")
    ui.wait_until(lambda: [i.get("origin") for i in _mine(ui)] == ["package"], 10, "installed from the package")
    got = _mine(ui)[0]
    ui.eq(got["author"], "maker-1")
    ui.check(str(got.get("preview", "")).startswith("/api/recipes/mine/"), "with its preview")


def journey_share_to_the_community(ui):
    home(ui)
    rid = _mine(ui)[0]["id"]
    ui.run_js('Store.openSheet("shareRecipe", { id: %r, tab: "community" })' % rid)
    open_sheet_wait(ui, "shareRecipe")
    ui.wait_until(lambda: ui.item("shareIssue").property("visible"), 60, "the community tab")
    ui.wait_until(lambda: ui.exists(text="Add a few tags people would search for."), 30, "what is missing, said first")
    ui.check(not ui.item("shareIssue").property("enabled"), "no link while something is missing")
    ui.fill("shareTags", "cable management, desk")
    ui.click_text("Apply changes")
    ui.wait_until(lambda: ui.item("shareIssue").property("enabled"), 60, "the issue button, once nothing is missing")
    ui.settle(500)                                     # the card shrinks once the note about tags is gone
    ui.check(not any(k == "link" for k, _ in ui.outside), "no browser opened before the click")
    ui.expect("What the GitHub form will show, filled in")
    ui.settle(300)
    ui.shot("share-community")
    ui.wait_until(lambda: ui.store.get("toasts") == [], 15, "the toasts over the button to leave")
    ui.click("shareIssue")
    ui.wait_until(lambda: any(k == "link" for k, _ in ui.outside), 3, "the browser asked to open the issue")
    url = [a for k, a in ui.outside if k == "link"][-1]
    u = urllib.parse.urlparse(url)
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    ui.eq(u.netloc + u.path, "github.com/kaizensx/form-studio/issues/new")
    ui.eq(q["template"], "3-recipe.yml")
    ui.eq(q["recipe_id"], "cable-clip")
    ui.check('"author": "maker-1"' in q["recipe_meta"], "meta.json in the form")
    ui.check("class Design(Recipe)" in q["recipe_code"], "the code in the form")
    # the folder for a pull request
    ui.click("shareFolder")
    folder = Path(ui.files) / "cable-clip"
    try:
        ui.wait_until(lambda: (folder / "preview.png").is_file(), 30, "the submission folder")
    except Exception as e:
        raise AssertionError(f"{e}; toasts={ui.store.get('toasts')} files={list(Path(ui.files).rglob('*'))} activity={ui.js('Store.activity')}")
    ui.eq(sorted(p.name for p in folder.iterdir()), ["meta.json", "preview.png", "recipe.py"])
    ui.eq(json.loads((folder / "meta.json").read_text())["id"], "cable-clip")
    ui.click_text("Close", within=ui.item("sheetCard"), exact=False) if ui.exists(text="Close") else ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 3, "closed")


def journey_design_to_recipe(ui):
    home(ui)
    pid = ui.api("/projects", {"name": "Coat hook", "recipe": "hook", "brief": "", "values": {"load_kg": 6}})["id"]
    wait_job(ui, pid)
    ui.run_js("Store.reloadStudio().then(function () { Store.open(%r) })" % pid)
    ui.wait_until(lambda: ui.store.get("screen") == "work", 60, "the design")
    ui.settle(500)
    ui.run_js('Store.openSheet("designRecipe", { project: %r })' % pid)
    open_sheet_wait(ui, "designRecipe")
    ui.wait_until(lambda: ui.item("deriveBuild").property("enabled"), 20, "the parameters")
    ui.settle(300)
    ui.shot("design-to-recipe")
    btn = ui.item("deriveBuild")
    ui.click(btn)
    # a real slow action: the kernel builds the rewritten recipe and the design
    ui.wait_until(lambda: sheet(ui) == "recipe" or btn.property("showsBusy"), 10, "busy feedback or the result")
    ui.wait_until(lambda: sheet(ui) == "recipe", 180, "the review")
    ui.settle(300)
    ui.expect("Builds the same solid as the design")
    ui.shot("derived-review")
    ui.click("recipeInstall")
    open_sheet_wait(ui, "shareRecipe")
    mine = [i for i in _mine(ui) if i.get("origin") == "design"]
    ui.eq(len(mine), 1)
    ui.eq(mine[0]["derived_from"]["project"], pid)
    ui.wait_until(lambda: ui.item("sharePreview").property("ready"), 180, "its preview")
    ui.key("Escape")
