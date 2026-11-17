"""Starting a design: learned starters on Home (pin, remove, add, use), the new-design sheet (search the library,
create from a recipe, install a recipe from a file after reviewing it, a community recipe, describe it), a project
archive exported and imported again with its conversation, and What's New shown once after an update."""
import json
import os
import zipfile
from pathlib import Path

from _lib import open_sheet_wait, sheet, wait_job

DATA = "fresh"

BLOCK = '''from build123d import Box
from form.recipes.base import Feature, Param, Recipe, Stage


class Block(Recipe):
    title = "Shelf block"
    summary = "A plain block, installed from a file in a test."
    params = [Param("w", "Width", 24, 5, 80, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["w"], 12, 6))]
'''


def home(ui):
    ui.wait_until(lambda: ui.store.get("screen") in ("home", "work"), 30, "the window")
    if ui.store.get("screen") == "work":                 # the journey before this one left a design open
        ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")


def starter_card(ui, text):
    return ui.wait_until(lambda: next((c for c in ui.find_all(name="starterCard") if text in (c.property("text") or "")), None),
                         8, f"the starter “{text}”")


def prompts(ui):
    return ui.api("/starters")["prompts"]


def hover_for(ui, card, name):
    """Hover a starter card until its hover-only button shows (synthetic hover can be missed on a busy runner)."""
    for _ in range(5):
        ui.hover((4, 4))                     # leave first: the cards reorder under a resting pointer, so no hover arrives
        ui.settle(100)
        ui.hover(card, 0.5, 0.5)
        ui.settle(300)
        b = ui.find(name=name, within=card)
        if b is not None and b.property("visible"):
            return b
        ui.hover(card, 0.2, 0.2)
    return ui.item(name, within=card)


def journey_learned_starters(ui):
    home(ui)
    ui.wait_until(lambda: len(ui.find_all(name="starterCard")) >= 6, 15, "the suggested starters")
    ui.settle(700)
    ui.shot("starters-fresh")
    # pin one: it moves to the front, in the engine and on Home
    card = starter_card(ui, "Gridfinity bin")
    ui.click(hover_for(ui, card, "starterPin"))
    ui.wait_until(lambda: prompts(ui)[0]["id"] == "d-gridfinity" and prompts(ui)[0]["pinned"], 15, "the pinned starter first in the engine")
    ui.wait_until(lambda: "Gridfinity bin" in (ui.find_all(name="starterCard")[0].property("text") or ""), 5, "the pinned starter first on Home")
    # remove one: hidden, and it stays hidden
    card = starter_card(ui, "lightest wall hook")
    ui.click(hover_for(ui, card, "starterRemove"))
    ui.wait_until(lambda: "d-hook" not in [p["id"] for p in prompts(ui)], 15, "the removed starter gone from the engine")
    ui.wait_until(lambda: not any("lightest wall hook" in (c.property("text") or "") for c in ui.find_all(name="starterCard")), 5, "and from Home")
    # add your own
    ui.click("starterAdd")
    ui.settle(300)
    ui.type("A clip for 6 mm cables under the desk")
    ui.key("Return")
    ui.wait_until(lambda: any(p["text"] == "A clip for 6 mm cables under the desk" and p["source"] == "mine" for p in prompts(ui)), 15, "your starter in the engine")
    starter_card(ui, "A clip for 6 mm cables")
    ui.settle(400)
    ui.shot("starters-changed")
    # a click puts the words in the composer, to be adjusted before sending
    ui.click(starter_card(ui, "A clip for 6 mm cables"), 0.4, 0.6)
    ui.wait_until(lambda: ui.store.get("chatRecall") == "A clip for 6 mm cables under the desk", 3, "the starter in the composer")
    state = json.loads((Path(ui.bridge._data) / ".form-starters.json").read_text(encoding="utf-8"))
    ui.check("d-hook" in state["hidden"] and "d-gridfinity" in state["pinned"], "kept in the data folder")
    # history: a design of a kind changes what is suggested
    ui.studio.create("Tool bin", "gridfinity", "A bin for hex bits, 2 by 1, with a label shelf")
    ui.run_js("Store.reloadStudio()")
    ui.wait_until(lambda: any(p["source"] == "learned" for p in prompts(ui)), 10, "a starter learned from the new design")
    ui.wait_until(lambda: any("Tool bin" in (c.property("text") or "") for c in ui.find_all(name="starterCard")), 10, "and on Home")


def journey_new_design_flow(ui):
    home(ui)
    ui.settle(300)
    ui.click_text("New design")
    open_sheet_wait(ui, "new")
    card = ui.item("sheetCard")
    # search the library
    ui.click("recipeSearch")
    ui.type("gear")
    ui.wait_until(lambda: ui.item("recipeGrid").property("count") == 1 and ui.exists(text="Spur gear pair", within=card), 30, "only the gears")    # live previews keep a software-rendered runner busy
    ui.click_text("Spur gear pair", within=card)
    ui.click("newName")
    ui.type("Clock gears")
    ui.shot("new-library-search")
    ui.click("recipePrimary")
    ui.wait_until(lambda: ui.store.get("screen") == "work", 120, "the new design to open")
    pid = ui.store.get("pid")
    ui.eq(ui.api("/projects/" + pid)["project"]["recipe"], "gear_pair")
    ui.eq(ui.api("/projects/" + pid)["project"]["name"], "Clock gears")
    wait_job(ui, pid)
    ui.run_js("Store.home()")
    home(ui)
    ui.settle(400)

    # install a recipe from a file: the code and its hash are shown first; nothing is installed before Install
    src = Path(os.environ["FORM_UITEST_TMP"]) / "shelf_block.py"
    src.write_bytes(BLOCK.encode("utf-8"))           # byte for byte: write_text would add CRLF on Windows
    ui.click_text("New design")
    open_sheet_wait(ui, "new")
    ui.pick_file(src)
    ui.click("installRecipeFile")
    open_sheet_wait(ui, "recipe")
    import hashlib
    sha = hashlib.sha256(BLOCK.encode()).hexdigest()
    ui.expect(sha)
    ui.expect("A recipe is code")
    ui.eq(ui.api("/recipes/library?section=mine")["items"], [], "nothing installed before Install")
    ui.shot("recipe-review")
    ui.click("recipeInstall")
    ui.wait_until(lambda: [i["id"] for i in ui.api("/recipes/library?section=mine")["items"]] == ["shelf-block"], 5, "the recipe installed")
    open_sheet_wait(ui, "new")
    ui.wait_until(lambda: ui.js("Store.sheet.props.section") == "mine", 3, "the library on Mine")
    ui.item(text="Shelf block", within=ui.item("sheetCard"))
    ui.click("recipePrimary")
    ui.wait_until(lambda: ui.store.get("screen") == "work", 120, "a design from the installed recipe")
    pid = ui.store.get("pid")
    ui.check(ui.api("/projects/" + pid)["project"]["recipe"].startswith("src:"), "built from the installed code")
    ui.run_js("Store.home()")
    home(ui)
    ui.settle(300)

    # community: the index from the website (a local copy in this test); install after review
    ui.click_text("New design")
    open_sheet_wait(ui, "new")
    for attempt in range(3):              # the sheet can still be swapping in: a card found a moment ago may be gone
        try:
            ui.settle(200)
            card = ui.item("sheetCard")
            ui.click_text("Community", within=card, exact=False)
            break
        except RuntimeError:
            if attempt == 2:
                raise
    ui.item(text="Cable clip", within=card, timeout=10)
    ui.click_text("Cable clip", within=card)
    ui.wait_until(lambda: ui.item("recipePrimary").property("text") == "Review and install…", 3, "Review and install")
    ui.click("recipePrimary")
    open_sheet_wait(ui, "recipe")
    ui.expect("matches the index")
    ui.click("recipeInstall")
    ui.wait_until(lambda: any(i.get("community_id") == "cable-clip" for i in ui.api("/recipes/library?section=mine")["items"]), 5, "the community recipe installed")
    open_sheet_wait(ui, "new")
    close = ui.store.get("sheet")
    ui.check(close is not None, "back in the library")
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 3, "the sheet closed")
    ui.settle(400)                                        # the scrim fades out before the next click

    # describe it: the words go to the composer with Edit in the composer
    ui.click_text("New design")
    open_sheet_wait(ui, "new")
    ui.click_text("Describe it", within=ui.item("sheetCard"))
    ui.settle(300)
    ui.click("describeArea")
    ui.type("A bracket for a 120 mm fan")
    ui.click_text("Edit in the composer")
    ui.wait_until(lambda: sheet(ui) is None and ui.store.get("chatRecall") == "A bracket for a 120 mm fan", 3, "the words in the composer")


def journey_archive_round_trip(ui):
    home(ui)
    pid = ui.api("/projects", {"name": "Desk hook", "recipe": "hook", "brief": ""})["id"]
    wait_job(ui, pid)
    conv = ui.api("/conversations", {"project": pid, "agent": "fake", "title": "About the desk hook"})
    ui.run_js("Store.reloadStudio()")
    card = ui.wait_until(lambda: next((c for c in ui.find_all(name="projectCard") if c.property("title") == "Desk hook"), None), 10, "the card")
    ui.settle(800)
    ui.right_click(card, 0.5, 0.4)
    ui.settle(250)
    ui.click_text("Export…")
    arch = ui.saved(pid + ".formstudio", 30)
    names = zipfile.ZipFile(arch).namelist()
    ui.check("manifest.json" in names and f"conversations/{conv['id']}/meta.json" in names, f"project and conversation in the file: {names[:6]}")
    # import it again: the id exists, so it gets a new one; the conversation comes along
    before = len(ui.api("/studio")["projects"])
    ui.pick_file(arch)
    ui.click_text("Import…")
    open_sheet_wait(ui, "new")
    ui.click("importProject")
    ui.wait_until(lambda: len(ui.api("/studio")["projects"]) == before + 1, 30, "the imported design")
    ui.wait_until(lambda: ui.store.get("screen") == "work", 60, "the imported design to open")
    new = ui.store.get("pid")
    ui.check(new != pid and new.startswith(pid), f"a new id: {new}")
    convs = ui.api("/conversations?project=" + new)["conversations"]
    ui.eq([c["title"] for c in convs], ["About the desk hook"], "its conversation came with it")
    ui.eq(len(ui.api("/conversations?project=" + pid)["conversations"]), 1, "the original keeps its own")
    ui.settle(500)
    ui.shot("imported")


def journey_whats_new_once(ui):
    home(ui)
    ui.settle(300)
    data = Path(ui.bridge._data)
    version = ui.js("Bridge.version")
    (data / ".form-whatsnew.json").write_text(json.dumps({"seen": "0.0.1"}), encoding="utf-8")   # as after an update
    ui.run_js("Store.checkWhatsNew(false)")
    open_sheet_wait(ui, "whatsnew")
    ui.expect(version, within=ui.item("sheetCard"))
    ui.shot("whats-new")
    ui.click("whatsNewDone")
    ui.wait_until(lambda: sheet(ui) is None, 3, "it closes")
    ui.eq(json.loads((data / ".form-whatsnew.json").read_text(encoding="utf-8"))["seen"], version, "remembered as seen")
    ui.run_js("Store.checkWhatsNew(false)")                       # the next start
    ui.settle(1200)
    ui.eq(sheet(ui), None, "not shown a second time")
    # always reachable from About
    ui.run_js('Store.openSheet("about")')
    open_sheet_wait(ui, "about")
    ui.click_text("What’s new", within=ui.item("sheetCard"))
    open_sheet_wait(ui, "whatsnew")
    ui.key("Escape")
