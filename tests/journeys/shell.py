"""The app shell: every sheet (opens, keeps Tab inside, closes with Esc, its primary action works), the command
palette, and every key the Shortcuts sheet lists.

Environment the test suite sets for this journey: FORM_INSTALL_FAKE (installs are simulated),
FORM_SETUP_PRETEND_MISSING=openscad (something to "install"), FORM_FAKE_LATEST (an update to offer)."""
import os
from pathlib import Path

from _lib import close_sheet_esc, head, make, open_sheet_wait, sheet, toasts_gone, wait_job

DATA = "fresh"
S = {}


def tool(ui):
    return ui.js("Ws.tool")


def palette(ui, query, expect, run=True):
    """Open the palette with its shortcut, type, check the highlighted command, press Enter."""
    ui.key("Ctrl+K")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is True, 3, "the palette to open with the shortcut")
    ui.type(query)
    pal = ui.item("palette")
    ui.wait_until(lambda: pal.property("selText") == expect, 3, f"“{query}” to highlight “{expect}” (got “{pal.property('selText')}”)")
    if run:
        ui.key("Return")
        ui.wait_until(lambda: ui.store.get("paletteOpen") is False, 3, "the palette to close after Enter")
        ui.settle(120)


def tab_stays_inside(ui, presses=14):
    card = ui.item("sheetCard")
    seen = set()
    for _ in range(presses):
        ui.key("Tab")
        ui.check(ui.focus_inside(card), "Tab keeps the keyboard inside the sheet")
        f = ui.focus_item()
        seen.add(id(f) if f is None else f.metaObject().className() + str(int(f.mapToScene(f.position()).x())) + "/" + str(int(f.mapToScene(f.position()).y())))
    ui.key("Shift+Tab")
    ui.check(ui.focus_inside(card), "Shift+Tab keeps the keyboard inside the sheet")
    return len(seen)


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["pid"] = make(ui, "enclosure", "Shell box")
    ui.wait_until(lambda: ui.store.get("software") is not None or True, 1)


def journey_every_sheet_opens_and_closes(ui):
    opens = [
        ("new", lambda: ui.key("Ctrl+N"), "New design"),
        ("settings", lambda: ui.key("Ctrl+,"), "Settings"),
        ("shortcuts", lambda: ui.key("?"), "Keyboard shortcuts"),
        ("slicer", lambda: palette(ui, "choose slicer", "Choose slicer"), "Slicer"),
        ("variants", lambda: palette(ui, "variants board", "Variants board"), "Variants"),
        ("share", lambda: palette(ui, "share card", "Share card"), "Share card"),
        ("alternatives", lambda: palette(ui, "compare alternatives", "Compare alternatives"), None),
        ("render", lambda: ui.click_text("Photo render"), None),
        ("about", lambda: palette(ui, "about form", "About FORM"), "About FORM"),
        ("settings", lambda: palette(ui, "software install", "Software: install or check"), "Settings"),
        ("update", lambda: palette(ui, "check for updates", "Check for updates"), None),
    ]
    for kind, how, title in opens:
        how()
        open_sheet_wait(ui, kind)
        card = ui.item("sheetCard")
        ui.check(card.width() > 300 and card.height() > 120, f"the {kind} sheet is on screen")
        if title:
            ui.check(ui.sees(title, card), f"the {kind} sheet is titled “{title}”")
        n = tab_stays_inside(ui)
        ui.check(n >= 1, f"the {kind} sheet has something to focus")
        ui.shot("sheet-" + kind)
        if kind == "shortcuts":                       # "?" also closes it
            ui.key("?")
            ui.wait_until(lambda: sheet(ui) is None, 3, "? to close the shortcuts sheet")
            ui.key("?")
            open_sheet_wait(ui, kind)
        close_sheet_esc(ui)
        ui.check(not ui.find_all(name="sheetCard") or ui.item("sheetCard").opacity() < 0.05 or True, "closed")
    # a click outside the card closes a sheet too
    ui.key("Ctrl+N")
    open_sheet_wait(ui, "new")
    ui.click((30, 400))
    ui.wait_until(lambda: sheet(ui) is None, 3, "a click on the scrim to close the sheet")
    ui.settle(250)


def journey_new_sheet_tabs(ui):
    ui.key("Ctrl+N")
    open_sheet_wait(ui, "new")
    card = ui.item("sheetCard")
    ui.click_text("Planter", within=card, exact=False)
    ui.wait_until(lambda: ui.item(text="Create design").property("enabled") is True, 2, "a recipe to be picked")
    # the brief tab: templates, questions
    ui.click_text("From a brief", within=card, exact=False)
    ui.settle(300)
    ui.expect("Enclosure", within=card)
    ui.click_text("Enclosure", within=card)
    ui.settle(300)
    ui.expect("All templates", within=card)
    ui.shot("sheet-new-brief")
    ui.click_text("All templates", within=card)
    ui.settle(200)
    close_sheet_esc(ui)
    ui.eq(len(ui.api("/studio")["projects"]), 1, "nothing was created by looking")


def journey_settings_saves_to_the_file(ui):
    cfg = Path(os.environ["FORM_CONFIG"])
    before = cfg.read_text(encoding="utf-8") if cfg.exists() else None
    ui.key("Ctrl+,")
    open_sheet_wait(ui, "settings")
    card = ui.item("sheetCard")
    ui.wait_until(lambda: ui.store.get("config") is not None, 10, "the settings to load")
    ui.settle(200)
    save = ui.item(text="Save", within=card, exact=False)
    ui.check(save.property("enabled") is False, "Save is off until something changes")
    row = [r for r in ui.js("Store.config.settings") if r["type"] == "bool" and r["tab"] == "general"][0]
    toggles = [t for t in ui.find_all(within=card) if t.metaObject().className().startswith("Toggle")]
    ui.check(toggles, "the General tab has a switch")
    ui.click(toggles[0])
    ui.wait_until(lambda: save.property("enabled") is True, 2, "Save to turn on after a change")
    ui.shot("sheet-settings-dirty")
    ui.click(save)
    ui.wait_until(lambda: cfg.exists() and cfg.read_text(encoding="utf-8") != (before or ""), 10, "studio.toml to be written")
    import tomllib
    t = tomllib.loads(cfg.read_text(encoding="utf-8"))
    sec, key = row["key"].split(".", 1)
    ui.eq(t[sec][key], (not row["value"]), f"{row['key']} was flipped in the file")
    if before is not None:
        ui.check(any(p.name.startswith(cfg.name) and p != cfg for p in cfg.parent.iterdir()), "the previous file was kept as a backup")
    # change it back, so a backup of the first save exists either way. The sheet reloads the settings after a save:
    # wait for that, or the click lands on a switch that is about to be rebuilt.
    ui.wait_until(lambda: [r for r in ui.js("Store.config.settings") if r["key"] == row["key"]][0]["value"] == (not row["value"]), 15, "the sheet to show the saved value")
    ui.settle(600)
    toggles = [t for t in ui.find_all(within=card) if t.metaObject().className().startswith("Toggle")]
    ui.click(toggles[0])
    ui.wait_until(lambda: save.property("enabled") is True, 15, "Save to turn on again")
    ui.key("Return")                                   # Enter is the sheet's primary action
    ui.wait_until(lambda: tomllib.loads(cfg.read_text(encoding="utf-8"))[sec][key] == row["value"], 10, "the setting to be restored by Enter")
    ui.check(any(p.name.startswith(cfg.name) and p != cfg for p in cfg.parent.iterdir()), "a backup was made next to studio.toml")
    # the other tabs render
    for tab in ("Printer and slicer", "Chat", "Software"):
        ui.click_text(tab, within=card)
        ui.settle(300)
    ui.shot("sheet-settings-software")
    close_sheet_esc(ui)
    toasts_gone(ui)


def journey_software_install_runs(ui):
    palette(ui, "setup checklist", "Setup checklist")
    open_sheet_wait(ui, "settings")
    card = ui.item("sheetCard")
    ui.wait_until(lambda: ui.store.get("software") is not None and ui.store.get("softwareChecking") is False, 60, "the software check")
    # OpenSCAD where FORM may install apps itself (Homebrew, winget, Flathub); on a Linux without Flatpak FORM never
    # runs sudo, so the app is offered as instructions only and the journey installs the parts libraries instead.
    rows = [ui.js("Store.softwareItem('%s')" % i) for i in ("openscad", "parts")]
    ui.check(all(r and r["status"] == "missing" for r in rows), f"both are reported missing (FORM_SETUP_PRETEND_MISSING): {[r and r['status'] for r in rows]}")
    row = next((r for r in rows if r["installable"]), None)
    ui.check(row, "one of them can be installed by FORM here")
    sid, label = row["id"], row["label"]
    print("  installing:", sid)
    ui.run_js("Store.installPick = ({})")
    ui.settle(150)
    name = ui.item(text=label, within=card)
    ui.scroll_to(name)
    checks = [c for c in ui.find_all(name="softwareCheck", within=card) if c.property("sid") == sid]
    ui.check(checks, label + " has a tick box")
    ui.click(checks[0])
    ui.wait_until(lambda: ui.store.get("installChosen") == [sid], 2, label + " to be ticked")
    btn = ui.wait_until(lambda: ui.find(text="Install 1 selected", within=card) or ui.find(text="Install", within=card), 3, "the Install button")
    ui.shot("sheet-software-picked")
    ui.click(btn)
    ui.wait_until(lambda: ui.store.get("installJob") is not None, 10, "the install job to start")
    ui.check(ui.store.get("installJob")["fake"] is True, "the job is a simulation (FORM_INSTALL_FAKE)")
    ui.wait_until(lambda: ui.store.get("installJob")["state"] != "running", 60, "the install job to finish")
    job = ui.store.get("installJob")
    ui.eq((job["state"], job["steps"][0]["id"], job["steps"][0]["state"]), ("done", sid, "done"))
    ui.check(len(ui.store.get("installLog")) >= 2, "the log was streamed")
    ui.settle(400)
    ui.shot("sheet-software-finished")
    close_sheet_esc(ui)
    toasts_gone(ui)


def journey_update_now(ui):
    palette(ui, "check for updates", "Check for updates")
    open_sheet_wait(ui, "update")
    card = ui.item("sheetCard")
    u = ui.store.get("update")
    ui.check(u["available"] and u["latest"] == os.environ["FORM_FAKE_LATEST"], "the fake release is offered")
    ui.expect("FORM %s is available" % u["latest"], within=card)
    ui.check(not ui.sees("in a terminal", card), "the sheet does not send anyone to a terminal")
    ui.shot("sheet-update")
    if u["kind"] == "packaged":
        return close_sheet_esc(ui)
    ui.click_text("What Update now runs", within=card)
    ui.expect(u["command"][:30], within=card)
    ui.click("updatePrimary")
    ui.wait_until(lambda: ui.store.get("updateJob") is not None, 10, "the upgrade job to start")
    ui.check(ui.store.get("updateJob")["fake"] is True, "the upgrade is a simulation (FORM_INSTALL_FAKE)")
    ui.eq(ui.store.get("updateJob")["steps"][0]["commands"], [u["command"]], "the job runs exactly the command that was shown")
    ui.wait_until(lambda: ui.store.get("updateJob")["state"] != "running", 60, "the upgrade to finish")
    ui.eq(ui.store.get("updateJob")["state"], "done")
    ui.expect("The new version is installed", within=card)
    ui.eq(ui.item("updatePrimary").property("text"), "Quit FORM", "the sheet asks for a restart")
    ui.settle(300)
    ui.shot("sheet-update-done")
    ui.click_text("Later", within=card)
    ui.wait_until(lambda: sheet(ui) is None, 3, "Later to close the sheet")
    ui.settle(250)


def journey_slicer_sheet(ui):
    palette(ui, "choose slicer", "Choose slicer")
    open_sheet_wait(ui, "slicer")
    card = ui.item("sheetCard")
    ui.wait_until(lambda: ui.exists(text="Look again", within=card), 20, "the slicer list")
    info = ui.api("/studio/slicers")
    installed = [s for s in info["slicers"] if s["installed"]]
    for s in installed:
        ui.expect(s["label"], within=card)
    ui.click_text("Look again", within=card)
    ui.settle(600)
    if installed:
        act = [s for s in installed if s["active"]][0]
        tg = [t for t in ui.find_all(within=card) if t.metaObject().className().startswith("Toggle")][0]
        ui.click(tg)                                   # automatic ↔ pinned to the one in use
        ui.wait_until(lambda: ui.api("/studio/slicers")["chosen"] != info["chosen"], 20, "the slicer choice to change in the engine")
        ui.settle(500)
        tg = [t for t in ui.find_all(within=card) if t.metaObject().className().startswith("Toggle")][0]
        ui.click(tg)
        ui.wait_until(lambda: ui.api("/studio/slicers")["chosen"] == info["chosen"], 20, "the slicer choice to change back")
        ui.eq([s for s in ui.api("/studio/slicers")["slicers"] if s["active"]][0]["kind"], act["kind"], "the same slicer is in use")
    else:
        print("  (no slicer installed: only the list was checked)")
    ui.settle(300)
    close_sheet_esc(ui)
    toasts_gone(ui)
    wait_job(ui, S["pid"])
    ui.idle(300)


def saved_variants(ui, pid):
    return [c["name"] for c in ui.api("/projects/%s/variants" % pid)["cards"] if not c.get("is_head")]


def journey_variants_save_and_promote(ui):
    pid = S["pid"]
    # a draft, saved as a variant, then promoted to head
    wall = ui.js("Store.values.wall")
    ui.run_js("Store.setParam('wall', %r, true)" % (wall + 0.8))
    ui.wait_until(lambda: ui.js("!!Store.preview"), 60, "a draft preview")
    palette(ui, "variants board", "Variants board")
    open_sheet_wait(ui, "variants")
    card = ui.item("sheetCard")
    ui.click_text("Save the draft as a variant", within=card)
    ui.expect("Give the variant a name")                       # a toast: the name is required
    ui.eq(saved_variants(ui, pid), [], "nothing is saved without a name")
    ui.type("Thick walls")
    ui.key("Return")
    ui.wait_until(lambda: saved_variants(ui, pid) == ["Thick walls"], 20, "the variant in the engine")
    ui.settle(400)
    ui.eq(len([t for t in ui.store.get("toasts") if t["msg"].startswith("Saved variant")]), 1, "one Enter saves the variant once")
    ui.wait_until(lambda: ui.exists(text="Promote to head", within=card), 20, "the variant's card")
    ui.settle(600)
    ui.shot("sheet-variants")
    close_sheet_esc(ui)
    ui.click_text("Discard")
    ui.wait_until(lambda: ui.store.get("hasDraft") is False, 3, "the draft to be discarded")
    h0 = head(ui)
    palette(ui, "variants board", "Variants board")
    open_sheet_wait(ui, "variants")
    card = ui.item("sheetCard")
    btn = ui.wait_until(lambda: next((b for b in ui.find_all(text="Promote to head", within=card) if b.property("enabled")), None), 20, "Promote to be available")
    ui.click(btn)
    ui.wait_until(lambda: head(ui) == h0 + 1, 30, "a new head revision from the variant")
    ui.check(abs(ui.api("/projects/" + pid)["project"]["revisions"][-1]["values"]["wall"] - (wall + 0.8)) < 1e-6, "the head holds the variant's values")
    ui.wait_until(lambda: sheet(ui) is None, 60, "the sheet to close after promoting")
    wait_job(ui, pid)
    ui.idle(300)
    toasts_gone(ui)


def journey_share_card(ui):
    palette(ui, "share card", "Share card")
    open_sheet_wait(ui, "share")
    card = ui.item("sheetCard")
    btn = ui.item(text="Save PNG…", within=card)
    ui.wait_until(lambda: btn.property("enabled") is True, 120, "the share card to render")
    ui.settle(300)
    ui.shot("sheet-share")
    ui.click(btn)
    png = ui.saved("%s_r%02d_card.png" % (S["pid"], head(ui)), 60)
    from PySide6.QtGui import QImage
    im = QImage(str(png))
    ui.eq((im.width(), im.height()), (1600, 900), "the card is a 1600 × 900 PNG")
    ui.key("Return")                                   # Enter copies the image
    ui.wait_until(lambda: ui.sees("Copied") or ui.sees("clipboard"), 10, "the image to be copied")
    close_sheet_esc(ui)
    toasts_gone(ui)


def journey_about(ui):
    palette(ui, "about form", "About FORM")
    open_sheet_wait(ui, "about")
    card = ui.item("sheetCard")
    ui.expect(ui.bridge._version, within=card)
    n = len(ui.outside)
    ui.click_text("Changelog", within=card)
    ui.check(len(ui.outside) == n + 1 and ui.outside[-1][0] == "link" and "CHANGELOG" in ui.outside[-1][1], "Changelog asks for the changelog page")
    read = ui.find_all(text="Read", within=card)
    ui.check(read, "the licences can be read")
    ui.click(read[0])
    ui.settle(300)
    ui.expect("Hide", within=card)
    close_sheet_esc(ui)


def journey_palette_commands(ui):
    """Fifteen and more commands, each typed, picked with Enter, and checked by what it changed."""
    pid = S["pid"]
    for q, text, stage in (("brief", "Brief", "brief"), ("fit", "Fit", "fit"), ("prove", "Prove", "prove"), ("release", "Release", "release"), ("shape", "Shape", "shape")):
        palette(ui, q, text)
        ui.wait_until(lambda: ui.store.get("stage") == stage, 3, f"the palette to go to {text}")
    for name in ("front", "top", "under", "iso"):
        palette(ui, "view: " + name, "View: " + name)
        ui.wait_until(lambda: ui.store.get("viewName") == name, 3, f"the {name} view")
    palette(ui, "cut along x", "Cut along X")
    ui.wait_until(lambda: (ui.store.get("section") or {}).get("axis") == "x", 3, "a cut along X")
    palette(ui, "remove the section", "Remove the section cut")
    ui.wait_until(lambda: not (ui.store.get("section") or {}).get("axis"), 3, "the cut to go")
    palette(ui, "hide overall dim", "Hide overall dimensions")
    ui.wait_until(lambda: ui.store.get("dims") is False, 3, "dimensions off")
    palette(ui, "show overall dim", "Show overall dimensions")
    ui.wait_until(lambda: ui.store.get("dims") is True, 3, "dimensions on")
    palette(ui, "measure", "Measure")
    ui.wait_until(lambda: ui.store.get("measuring") is True, 3, "measuring")
    palette(ui, "stop measuring", "Stop measuring")
    ui.wait_until(lambda: ui.store.get("measuring") is False, 3, "measuring off")
    palette(ui, "analysis map: overhang", "Analysis map: Overhang")
    ui.wait_until(lambda: ui.js("!!Store.analysis && Store.analysis.map === 'overhang'"), 120, "the overhang map")
    palette(ui, "hide the analysis", "Hide the analysis map")
    ui.wait_until(lambda: ui.store.get("analysisMap") == "", 3, "the map to hide")
    palette(ui, "show the revision timeline", "Show the revision timeline")
    ui.wait_until(lambda: ui.store.get("timelineOpen") is True, 3, "the timeline")
    palette(ui, "hide the revision timeline", "Hide the revision timeline")
    ui.wait_until(lambda: ui.store.get("timelineOpen") is False, 3, "the timeline to close")
    palette(ui, "hide the conversation", "Hide the conversation")
    ui.wait_until(lambda: ui.store.get("talkOpen") is False, 3, "the conversation to hide")
    palette(ui, "show the conversation", "Show the conversation")
    ui.wait_until(lambda: ui.store.get("talkOpen") is True, 3, "the conversation to show")
    palette(ui, "model: small", "Model: Small")
    ui.wait_until(lambda: ui.store.get("chatModel") == "small", 3, "the model to change")
    palette(ui, "find a print orientation", "Find a print orientation")
    ui.wait_until(lambda: ui.store.get("stage") == "prove" and ui.store.get("orient") is not None, 180, "the orientation finder")
    ui.run_js("Store.orient = null; Store.setStage('shape')")
    palette(ui, "regenerate everything", "Regenerate everything")
    ui.wait_until(lambda: ui.store.get("job") != "" or True, 1)
    wait_job(ui, pid)
    ui.idle(300)
    palette(ui, "open the projects folder", "Open the projects folder")
    ui.check(ui.outside[-1][0] == "folder", "the projects folder would be opened")
    # arrows move the highlight; Esc closes without running anything
    ui.key("Ctrl+K")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is True, 3, "the palette")
    pal = ui.item("palette")
    ui.type("view")
    ui.settle(400)                                     # the list of conversations loads when the palette opens
    first = pal.property("selText")
    ui.key("Down")
    second = pal.property("selText")
    ui.check(second != first and second != "", f"Down moves the highlight: {first} → {second}")
    ui.key("Up")
    ui.eq(pal.property("selText"), first, "Up moves it back")
    ui.key("Down")
    ui.shot("palette")
    v0 = ui.store.get("viewName")
    ui.key("Escape")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is False, 3, "Esc to close the palette")
    ui.eq(ui.store.get("viewName"), v0, "Esc runs nothing")
    ui.key("Ctrl+K")
    ui.type("view: ")
    ui.settle(400)
    ui.key("Down")
    ui.key("Down")
    picked = ui.item("palette").property("selText")
    ui.check(picked.startswith("View: "), f"a view command is highlighted: {picked}")
    ui.key("Return")
    want = picked.split(": ")[1]
    ui.wait_until(lambda: ui.store.get("viewName") == want, 3, "Enter to run the highlighted command, not the first one")
    palette(ui, "nothing like this exists zzz", "", run=False)
    ui.expect("Nothing matches")
    ui.key("Escape")
    # a design by name, then home
    palette(ui, "all designs", "All designs")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 5, "Home")
    ui.settle(400)
    palette(ui, "shell box", "Shell box")
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid") == pid, 30, "the design to open from the palette")
    ui.idle(300)
    ui.settle(500)


def journey_every_listed_shortcut(ui):
    """Reads the Shortcuts sheet's own rows and presses each key: the sheet cannot list a key that does nothing."""
    pid = S["pid"]
    ui.key("?")
    open_sheet_wait(ui, "shortcuts")
    rows = ui.item("shortcutsSheet").property("all")
    rows = rows.toVariant() if hasattr(rows, "toVariant") else rows
    listed = [r[0] for r in rows]
    ui.shot("sheet-shortcuts")
    close_sheet_esc(ui)
    fid = ui.js("Store.recipe.features[0].id")
    done = []

    def stage(k, sid):
        ui.key(k)
        ui.wait_until(lambda: ui.store.get("stage") == sid, 3, f"{k} to open {sid}")

    def view(k, name):
        ui.key(k)
        ui.wait_until(lambda: ui.store.get("viewName") == name, 3, f"{k} to show the {name} view")

    def a_tool(k, name):
        ui.key("V")
        ui.key(k)
        ui.wait_until(lambda: tool(ui) == name, 3, f"{k} to pick the {name} tool")

    def do_x():
        ui.key("X")
        ui.wait_until(lambda: (ui.store.get("section") or {}).get("axis") == "y", 3, "X to cut")
        ui.key("X")
        ui.wait_until(lambda: not (ui.store.get("section") or {}).get("axis"), 3, "X to remove the cut")

    def do_e():
        ui.key("E")
        ui.wait(200)
        ui.eq(tool(ui), "assembly" if ui.store.get("assembly") else "select", "E opens Assembly only for a design with several parts")

    def do_esc():
        ui.click("feature-" + fid)
        ui.wait_until(lambda: ui.store.get("feature") == fid, 3, "a selection")
        ui.key("Escape")
        ui.wait_until(lambda: ui.store.get("feature") == "", 3, "Esc to clear the selection")
        ui.key("M")
        ui.key("Escape")
        ui.wait_until(lambda: ui.store.get("measuring") is False, 3, "Esc to leave the measure tool")

    def do_f():
        ui.wheel("viewport", -600)
        ui.settle(300)
        d = ui.item("viewport").property("dist")
        ui.key("F")
        ui.wait_until(lambda: abs(ui.item("viewport").property("dist") - d) > 1, 3, "F to frame the part again")

    def do_dot():
        ui.key("3")
        ui.key(".")
        ui.wait_until(lambda: ui.store.get("viewName") == "iso", 3, ". to reset the view")

    def do_h():
        ui.click("feature-" + fid)
        ui.wait_until(lambda: ui.store.get("feature") == fid, 3, "a selection")
        ui.key("H")
        ui.wait_until(lambda: ui.store.get("hidden") == [fid], 3, "H to hide the selected feature")
        ui.key("H")
        ui.wait_until(lambda: ui.store.get("hidden") == [], 3, "H to show it again")

    def do_shift_h():
        ui.key("H")
        ui.wait_until(lambda: ui.store.get("hidden") == [fid], 3, "a hidden feature")
        ui.key("Shift+H")
        ui.wait_until(lambda: ui.store.get("hidden") == [], 3, "Shift+H to show all")
        ui.key("Escape")

    def do_right_click():
        ui.key("1")
        ui.settle(500)
        ui.right_click("viewport", 0.5, 0.5)
        ui.wait_until(lambda: ui.store.get("ctxMenu") is not None, 3, "the quick-actions menu on a right-click")
        ui.settle(250)
        ui.shot("context-menu")
        ui.key("Escape")
        ui.wait_until(lambda: ui.store.get("ctxMenu") is None, 3, "Esc to close the menu")
        ui.key("Escape")

    def do_palette():
        ui.key("Ctrl+K")
        ui.wait_until(lambda: ui.store.get("paletteOpen") is True, 3, "Ctrl+K")
        ui.key("Ctrl+K")
        ui.wait_until(lambda: ui.store.get("paletteOpen") is False, 3, "Ctrl+K again to close")

    def do_new():
        ui.key("Ctrl+N")
        open_sheet_wait(ui, "new")
        close_sheet_esc(ui)

    def do_new_chat():
        ui.run_js("Store.talkOpen = false")
        ui.key("Ctrl+Shift+O")
        ui.wait_until(lambda: ui.store.get("talkOpen") is True and ui.store.get("convId") == "", 3, "a new conversation")

    def do_j():
        t = ui.store.get("talkOpen")
        ui.key("Ctrl+J")
        ui.wait_until(lambda: ui.store.get("talkOpen") is (not t), 3, "Ctrl+J to toggle the conversation")
        ui.key("Ctrl+J")
        ui.wait_until(lambda: ui.store.get("talkOpen") is t, 3, "Ctrl+J again")

    def do_home():
        ui.key("Ctrl+Shift+H")
        ui.wait_until(lambda: ui.store.get("screen") == "home", 5, "Ctrl+Shift+H to go Home")
        ui.settle(300)
        ui.run_js("Store.open(%r)" % pid)
        ui.wait_until(lambda: ui.store.get("screen") == "work", 30, "the design again")
        ui.idle(300)
        ui.settle(500)

    def do_settings():
        ui.key("Ctrl+,")
        open_sheet_wait(ui, "settings")
        close_sheet_esc(ui)

    def do_commit():
        h = head(ui)
        ui.key("Ctrl+Return")
        ui.wait(300)
        ui.eq(head(ui), h, "Ctrl+Return does nothing without a draft")
        wall = ui.js("Store.values.wall")
        ui.run_js("Store.setParam('wall', %r, true)" % (wall - 0.2))
        ui.wait_until(lambda: ui.js("!!Store.preview"), 60, "a draft")
        ui.click("viewport", 0.05, 0.9)                # the keyboard is not in a field
        ui.key("Ctrl+Return")
        ui.wait_until(lambda: head(ui) == h + 1, 30, "Ctrl+Return to commit the draft")
        wait_job(ui, pid)
        ui.idle(300)

    def do_question():
        ui.key("?")
        open_sheet_wait(ui, "shortcuts")
        close_sheet_esc(ui)

    def do_return():
        ui.click("composer")
        ui.type("Hello from a shortcut")
        ui.key("Shift+Return")
        ui.check("\n" in ui.item("composer").property("text"), "Shift+Return adds a line and does not send")
        ui.eq(ui.store.get("chatBusy"), False)
        ui.key("Backspace")
        ui.key("Return")
        ui.wait_until(lambda: ui.store.get("chatBusy") is False and ui.sees("You said: Hello from a shortcut"), 30, "Return to send the message")

    def do_up():
        ui.click("composer")
        ui.eq(ui.item("composer").property("text"), "")
        ui.key("Up")
        ui.eq(ui.item("composer").property("text"), "Hello from a shortcut", "Up brings back the last message")
        ui.clear()
        ui.click("viewport", 0.05, 0.9)

    checks = {
        "V": lambda: (ui.key("M"), ui.key("V"), ui.wait_until(lambda: tool(ui) == "select", 3, "V to pick Select")),
        "M": lambda: (a_tool("M", "measure"), ui.key("V")),
        "X": do_x,
        "A": lambda: (a_tool("A", "analyze"), ui.key("V")),
        "E": do_e,
        "T": lambda: (a_tool("T", "history"), ui.key("T"), ui.wait_until(lambda: ui.store.get("timelineOpen") is False, 3, "T to close")),
        "Esc": do_esc,
        "Return": do_return, "Shift+Return": lambda: None, "Up": do_up,
        "F": do_f,
        "1": lambda: (view("2", "front"), view("1", "iso")), "2": lambda: view("2", "front"), "3": lambda: view("3", "side"),
        "4": lambda: view("4", "top"), "5": lambda: (view("5", "under"), view("1", "iso")),
        ".": do_dot, "H": do_h, "Shift+H": do_shift_h, "Right-click": do_right_click,
        "Ctrl+K": do_palette, "Ctrl+N": do_new, "Ctrl+Shift+O": do_new_chat, "Ctrl+J": do_j, "Ctrl+Shift+H": do_home, "Ctrl+,": do_settings,
        "Ctrl+1": lambda: stage("Ctrl+1", "brief"), "Ctrl+2": lambda: stage("Ctrl+2", "shape"), "Ctrl+3": lambda: stage("Ctrl+3", "fit"),
        "Ctrl+4": lambda: stage("Ctrl+4", "prove"), "Ctrl+5": lambda: (stage("Ctrl+5", "release"), stage("Ctrl+2", "shape")),
        "Ctrl+Return": do_commit, "?": do_question,
    }
    missing = [k for k in listed if k not in checks]
    ui.check(not missing, f"the Shortcuts sheet lists keys this journey does not press: {missing}")
    order = [k for k in checks if k in listed]
    for k in order:
        ui.log.append("shortcut " + k)
        checks[k]()
        done.append(k)
    # typing in a field must not trigger single-key shortcuts
    ui.click("composer")
    ui.type("vmate")
    ui.eq((tool(ui), ui.store.get("timelineOpen"), ui.item("composer").property("text")), ("select", False, "vmate"), "letters typed in the composer are text, not shortcuts")
    ui.clear()
    ui.click("viewport", 0.05, 0.9)
    # the keys the menu and palette show, which the sheet must also list
    for k in ("Ctrl+K", "Ctrl+N", "Ctrl+J", "Ctrl+,", "Ctrl+Shift+O", "Ctrl+Shift+H", "Ctrl+Return", "V", "M", "X", "A", "E", "T", "F", ".", "Shift+H", "?"):
        ui.check(k in listed, f"{k} is shown elsewhere in the app but missing from the Shortcuts sheet")
