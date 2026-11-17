"""Home: filter, sort, a card's menu (rename, duplicate, export, move to trash), and what happens to a deleted
design's conversations."""
import zipfile

from _lib import wait_job

DATA = "fresh"
NAMES = ["Zebra hook", "Alpha knob", "Mango planter", "Bravo bin", "Delta coupon", "Echo dock", "Kilo box"]
RECIPES = ["hook", "knob", "planter", "gridfinity", "coupon", "dock", "enclosure"]


def projects(ui):
    return ui.api("/studio")["projects"]


def card(ui, name):
    return ui.wait_until(lambda: next((c for c in ui.find_all(name="projectCard") if ui.sees(name, c)), None), 8, f"the card of {name}")


def shown_names(ui):
    return [c.property("title") for c in ui.find_all(name="projectCard")]


def menu(ui, name, entry):
    c = card(ui, name)
    ui.right_click(c, 0.5, 0.4)
    ui.settle(250)
    ui.click_text(entry)
    ui.settle(200)


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    # seven designs straight in the engine (no pipeline runs: Home does not need them built) and one released
    ids = {}
    for n, r in zip(NAMES, RECIPES):
        ids[n] = ui.studio.create(n, r, "", None)["id"]
    rel = ids["Echo dock"]
    ui.api("/projects/" + rel + "/run", {"nodes": [], "force": False})
    wait_job(ui, rel)
    g = ui.api("/projects/" + rel)["gate"]
    ui.api("/projects/" + rel + "/approve", {"acknowledged": [w["id"] for w in g.get("warnings") or []], "note": ""})
    # a conversation about the design that will be deleted
    conv = ui.api("/conversations", {"project": ids["Zebra hook"], "agent": "fake"})
    ui.run_js("Store.reloadStudio()")
    ui.wait_until(lambda: len(ui.find_all(name="projectCard")) == 7, 20, "seven cards")
    ui.settle(900)
    ui.shot("home-grid")

    # ── filter ──
    ui.click_text("Released")
    ui.wait_until(lambda: shown_names(ui) == ["Echo dock"], 3, "only the released design")
    ui.click_text("In progress")
    ui.wait_until(lambda: len(shown_names(ui)) == 6 and "Echo dock" not in shown_names(ui), 3, "the six unreleased designs")
    ui.click_text("All")
    ui.wait_until(lambda: len(shown_names(ui)) == 7, 3, "all seven again")
    # ── sort ──
    ui.click_text("Last changed")
    ui.wait_until(lambda: shown_names(ui) == sorted(NAMES), 3, "the designs by name")
    ui.click_text("Name")
    ui.wait_until(lambda: shown_names(ui)[0] == "Echo dock", 3, "the designs by last change")
    ui.settle(300)

    # ── rename from the card's menu ──
    menu(ui, "Alpha knob", "Rename")
    ui.wait_until(lambda: ui.win.activeFocusItem() is not None and "TextInput" in ui.win.activeFocusItem().metaObject().className(),
                  3, "the name field to take the keyboard")
    ui.settle(200)                # past the moment the closing menu hands focus back
    ui.clear()
    ui.type("Volume knob")
    ui.key("Return")
    ui.wait_until(lambda: "Volume knob" in shown_names(ui), 2, "the card to show the new name at once")
    ui.wait_until(lambda: any(p["name"] == "Volume knob" for p in projects(ui)), 30, "the new name in the engine")
    # the renamed design is now the last one changed: wait for the grid to finish moving it to the front, or the
    # next right-click lands on whichever card slides under the pointer
    ui.wait_until(lambda: shown_names(ui)[0] == "Volume knob", 10, "the renamed design to move to the front")
    ui.settle(500)
    card(ui, "Volume knob")

    # ── duplicate ──
    menu(ui, "Bravo bin", "Duplicate")
    ui.wait_until(lambda: len(projects(ui)) == 8, 10, "a copy in the engine")
    copy = [p for p in projects(ui) if p["id"] not in ids.values()][0]
    ui.check("Bravo bin" in copy["name"] and copy["id"] != ids["Bravo bin"], f"the copy is its own project: {copy['name']}")
    ui.wait_until(lambda: len(ui.find_all(name="projectCard")) == 8, 5, "eight cards")

    # ── export .formproj ──
    menu(ui, "Delta coupon", "Export .formproj…")
    arch = ui.saved(ids["Delta coupon"] + ".formproj", 30)
    ui.check(zipfile.is_zipfile(arch) and any("project.json" in n for n in zipfile.ZipFile(arch).namelist()), "the archive holds the project")

    # ── the "…" button opens the same menu ──
    c = card(ui, "Kilo box")
    ui.hover(c, 0.5, 0.4)
    ui.settle(250)
    ui.click(ui.item("cardMore", within=c))
    ui.settle(250)
    ui.expect("Move to trash…")
    ui.key("Escape")
    ui.settle(250)

    # ── move to trash: asks first, keeps the files, detaches the conversation ──
    menu(ui, "Zebra hook", "Move to trash…")
    ui.eq(len(projects(ui)), 8, "nothing is deleted before the confirmation")
    ui.settle(200)
    ui.shot("home-delete-confirm")
    ui.click_text("Move to trash")
    ui.wait_until(lambda: len(projects(ui)) == 7 and not any(p["id"] == ids["Zebra hook"] for p in projects(ui)), 10, "the design to leave the list")
    from pathlib import Path
    data_dir = Path(ui.bridge._data)
    ui.check(any(d.name.startswith(ids["Zebra hook"] + "-") for d in (data_dir / ".trash").iterdir()), "the folder is in .trash, not erased")
    meta = [c for c in ui.api("/conversations")["conversations"] if c["id"] == conv["id"]][0]
    ui.eq(meta["project"], None, "the conversation no longer points at the deleted design")
    ui.eq(meta["project_was"]["name"], "Zebra hook", "and remembers what it was about")
    ui.wait_until(lambda: len(ui.find_all(name="projectCard")) == 7, 5, "seven cards")

    # ── a click opens a design ──
    ui.click(card(ui, "Echo dock"), 0.5, 0.4)
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == rel, 30, "the design to open")
    ui.idle(120)
    ui.key("Ctrl+Shift+H")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 5, "Home again with the shortcut")
    ui.settle(600)
    ui.shot("home-after")
