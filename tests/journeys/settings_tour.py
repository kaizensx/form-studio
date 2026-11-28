"""Settings, page by page: the nav opens every page (the sheet names the page in front: pageTitle), each page has its
groups, General has its tiles and its list of engines, the search finds rows on every page, and Engines & software shows “Use in Form Studio” for what is installed. A picture of each page is kept
(settings-<page>-<dark|light>.png).

Environment (tests/test_ui_journeys.py test_settings_tour): FORM_APPEARANCE picks the appearance for the run."""
from _lib import open_sheet_wait

PAGES = (("general", "General"), ("chat", "Agents & models"), ("software", "Engines & software"), ("costs", "Costs"),
         ("apps", "Other apps"), ("appearance", "Appearance"), ("backups", "Backups"), ("updates", "Updates"), ("advanced", "Advanced"))


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
    # the sheet draws its own head: the word over a bare nav, no title bar and no action bar while nothing is unsaved
    ui.eq(ui.item("settingsSheet").property("pageTitle"), "General", "General is in front")
    ui.check(not ui.exists("settingsSaveBar"), "no Save bar while nothing is changed")
    # General: what it is set up for as tiles with a switch, then every engine with its licence, size and state
    ui.wait_until(lambda: ui.exists("capCard_core") and len(ui.find_all(name="engineRow")) > 0, 30, "the tiles and the engines")
    engines = {r.property("sid") for r in ui.find_all(name="engineRow", shown=False)}
    ui.check("kernel" in engines and "data" not in engines, f"the kernel is an engine, the project folder is not: {sorted(engines)[:6]}")
    group = {i: g["id"] for g in ui.js("Store.software.groups") for i in g["items"]}
    ui.check(not any(group.get(e) in ("ai", "agents") for e in engines), "agents are not listed with the engines")
    ui.settle(400)
    ui.shot(f"settings-general-top-{theme}")
    # Reduce Motion (Appearance): the person's own switch; it takes effect at once and movement is dropped (Theme.move returns 0)
    ui.click("settingsNav_appearance")
    ui.wait_until(lambda: ui.exists("reduceMotionToggle"), 5, "the Appearance page")
    ui.eq(ui.js("Theme.reduced"), False, "motion is on to begin with")
    ui.scroll_to("reduceMotionToggle")
    ui.click("reduceMotionToggle")
    ui.wait_until(lambda: ui.js("Theme.reduced") is True and ui.js("Theme.move(200)") == 0, 5, "Reduce Motion to be on")
    ui.shot(f"settings-reduce-motion-{theme}")
    ui.click("reduceMotionToggle")
    ui.wait_until(lambda: ui.js("Theme.reduced") is False and ui.js("Theme.move(200)") == 200, 5, "Reduce Motion to be off again")
    printing = ui.js("Store.printOn") is True
    for value, text in PAGES + ((("printer", "Printing"),) if printing else ()):
        ui.click("settingsNav_" + value)
        ui.wait_until(lambda: ui.item("settingsSheet").property("pageTitle") == text, 5, f"the {text} page")
        ui.settle(500)
        ui.shot(f"settings-{value}-{theme}")
    ui.eq("Printing" in ui.texts(card), printing, "the Printing page is there only with 3D printing on")

    # the rail keeps its place while a long page scrolls
    ui.click("settingsNav_software")
    ui.wait_until(lambda: _row(ui, "softwareStatus", "kernel") is not None, 30, "the engine rows")
    # the mesh generators have their switches here (off until turned on; nothing is sent by a switch)
    gens = ui.wait_until(lambda: ui.find_all(name="generatorUse", shown=False), 10, "the mesh generators' switches")
    ui.check(all(g.property("checked") is False for g in gens), "every mesh generator is off to begin with")
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
    ui.eq(ui.item("settingsSheet").property("pageTitle"), "Search", "the page says it is a search")
    ui.expect("Search", within=ui.item("settingsScroll"))
    ui.settle(300)
    ui.shot(f"settings-search-{theme}")
    ui.click("settingsNav_updates")
    ui.wait_until(lambda: ui.item("settingsSheet").property("pageTitle") == "Updates", 5, "a page to end the search")
    ui.key("Escape")
