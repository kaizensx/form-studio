"""Settings, page by page: the rail opens every page, each page has its title and its cards, the search finds rows on
every page, and Engines & software shows “Use in Form Studio” for what is installed. A picture of each page is kept
(settings-<page>-<dark|light>.png).

Environment (tests/test_ui_journeys.py test_settings_tour): FORM_APPEARANCE picks the appearance for the run."""
from _lib import open_sheet_wait

PAGES = (("general", "General"), ("chat", "Agents & models"), ("software", "Engines & software"), ("apps", "Other apps"),
         ("backups", "Backups"), ("updates", "Updates"), ("advanced", "Advanced"))


def _row(ui, name, sid):
    for it in ui.find_all(name=name, shown=False):
        if it.property("sid") == sid:
            return it
    return None


def run(ui):
    theme = "dark" if ui.js("Theme.dark") else "light"
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.run_js("Store.openSettings('general')")
    open_sheet_wait(ui, "settings")
    ui.wait_until(lambda: ui.store.get("config") is not None and ui.store.get("software") is not None, 90, "the settings and the software list")
    card = ui.item("sheetCard")
    printing = ui.js("Store.printOn") is True
    for value, text in PAGES + ((("printer", "Printing"),) if printing else ()):
        ui.click("settingsNav_" + value)
        ui.wait_until(lambda: ui.item("settingsTitle").property("text") == text, 5, f"the {text} page")
        ui.settle(500)
        ui.shot(f"settings-{value}-{theme}")
    ui.eq("Printing" in ui.texts(card), printing, "the Printing page is there only with 3D printing on")

    # the rail keeps its place while a long page scrolls
    ui.click("settingsNav_software")
    ui.wait_until(lambda: _row(ui, "softwareStatus", "kernel") is not None, 30, "the engine rows")
    y0 = ui.item("settingsNav_general").mapToScene(ui.item("settingsNav_general").position()).y()
    ui.wheel(ui.item("settingsScroll"), -720)
    ui.settle(300)
    ui.check(ui.item("settingsScroll").property("contentY") > 100, "the page scrolled")
    ui.eq(ui.item("settingsNav_general").mapToScene(ui.item("settingsNav_general").position()).y(), y0, "the rail did not move")

    # installed and used are two things: the kernel has no switch, an optional engine that is installed has one
    ui.check(_row(ui, "softwareUse", "kernel") is None or not _row(ui, "softwareUse", "kernel").isVisible(), "the kernel has no switch")
    rows = ui.js("Store.software.software")
    switched = [r for r in rows if r["status"] == "ok" and r.get("use")]
    for r in [r for r in rows if r.get("use")]:
        sw = _row(ui, "softwareUse", r["id"])
        ui.check(sw is not None, f"{r['id']} has a Use switch on its card")
        ui.eq(sw.isVisible(), r["status"] == "ok", f"{r['id']}: the switch shows only once it is installed")
    if switched:
        r = switched[0]
        sw = _row(ui, "softwareUse", r["id"])
        ui.scroll_to(sw)
        ui.settle(300)
        ui.check(len(_row(ui, "softwareUseEffect", r["id"]).property("text")) > 30, "the card says what the switch changes")
        ui.shot(f"settings-use-on-{theme}")
        ui.click(sw)
        sec, key = r["use"]["key"].split(".", 1)
        ui.wait_until(lambda: ui.api("/config") and [x for x in ui.api("/config")["settings"] if x["key"] == r["use"]["key"]][0]["value"] is (not r["use"]["on"]),
                      15, "the switch to be written")
        ui.wait_until(lambda: ui.js(f"Store.softwareItem({r['id']!r}).use.on") is (not r["use"]["on"]), 60, "the software list to follow")
        ui.eq(ui.js(f"Store.softwareItem({r['id']!r}).status"), "ok", "it is still installed")
        ui.settle(400)
        ui.shot(f"settings-use-off-{theme}")
        ui.click(_row(ui, "softwareUse", r["id"]))
        ui.wait_until(lambda: ui.js(f"Store.softwareItem({r['id']!r}).use.on") is r["use"]["on"], 60, "the switch back")
    ui.settle(300)

    # search finds rows on every page
    ui.click("settingsSearch")
    ui.type("spending cap")
    ui.wait_until(lambda: ui.sees("Spending cap per message"), 5, "the search to find a row of another page")
    ui.eq(ui.item("settingsTitle").property("text"), "Search", "the page says it is a search")
    ui.settle(300)
    ui.shot(f"settings-search-{theme}")
    ui.click("settingsNav_updates")
    ui.wait_until(lambda: ui.item("settingsTitle").property("text") == "Updates", 5, "a page to end the search")
    ui.key("Escape")
