"""Bringing work in and keeping up: a project archive exported and imported again with its conversation, and What's
New shown once after an update. (How a design starts on Home is tests/journeys/start.py.)"""
import json
import zipfile
from pathlib import Path

from _lib import open_sheet_wait, sheet, wait_job

DATA = "fresh"


def home(ui):
    ui.wait_until(lambda: ui.store.get("screen") in ("home", "work"), 30, "the window")
    if ui.store.get("screen") == "work":                 # the journey before this one left a design open
        ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")


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
    open_sheet_wait(ui, "import")
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
