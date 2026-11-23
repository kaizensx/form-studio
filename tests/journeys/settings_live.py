"""Settings apply at once, both ways: the default printer chosen from Settings › Printing shows in Settings, in Review
and the open design's checks; turning 3D printing off in Settings › General › Set up for hides the Printing tab, the
printer chip and the Fit stage (nothing is uninstalled), and turning it on brings them back. Nothing needs a restart.

Environment (tests/test_ui_journeys.py test_settings_live): Bambu Studio is a fixture config folder (an A1 mini, an X1
Carbon and a user printer "My mini"); every other slicer points at a program that does not exist. Because a slicer is
configured, the one-time migration (form/capabilities.py) turns 3D printing on at the first start."""
from _lib import make, open_sheet_wait, sheet, toasts_gone

DATA = "fresh"
X1 = "Bambu Lab X1 Carbon 0.4 nozzle"


def journey_default_printer_from_settings(ui):
    pid = make(ui, "hook", "Settings journey", purpose="print")    # made for printing: new designs are 3D models unless said
    ui.run_js("Store.setStage('prove')")                        # the printer is named in Fit, Review and Make
    ui.run_js("Store.openSettings('printer')")
    open_sheet_wait(ui, "settings")
    ui.wait_until(lambda: ui.find(name="settingsPrinterName") is not None, 10, "the default printer card")
    before = ui.item("settingsPrinterName").property("text")
    ui.check(before and before != X1, f"starts on the slicer's selection: {before}")
    ui.shot("settings-printing")
    ui.click("settingsChoosePrinter")
    open_sheet_wait(ui, "printer")
    sh = ui.item("printerSheet")
    r = ui.wait_until(lambda: next((x for x in ui.find_all(name="printerRow", shown=False) if x.property("pid_") == "bambu:" + X1), None),
                      20, "the X1 Carbon row")
    ui.scroll_to(r, 0.5)
    ui.click(r, 0.3, 0.5)
    ui.wait_until(lambda: sh.property("pickId") == "bambu:" + X1, 10, "the X1 Carbon to be chosen")
    ui.wait_until(lambda: ui.find(name="printerFilament") is not None and ui.find(name="printerFilament").property("value"), 15, "its filament")
    ui.click("printerMakeDefault")
    ui.wait_until(lambda: (ui.api("/printers").get("default") or {}).get("machine") == X1, 10, "the default printer")
    ui.wait_until(lambda: sh.property("busy") == "", 20, "the sheet to finish")
    # the top bar and the open design follow, with no restart and no click on the design
    ui.wait_until(lambda: ui.js("Store.printing.available && Store.printing.presets.machine.name") == X1, 10, "the app to follow")
    ui.wait_until(lambda: ui.sees(X1, ui.item("printerChip")), 10, "the printer chip in Review")
    ui.wait_until(lambda: (ui.api("/projects/" + pid).get("checks") or {}).get("context", {}).get("envelope") == [256.0, 256.0, 250.0],
                  120, "the design's checks to use the X1's bed")
    # and Settings shows it when opened again
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 4, "the sheet to close")
    ui.run_js("Store.openSettings('printer')")
    open_sheet_wait(ui, "settings")
    ui.wait_until(lambda: ui.item("settingsPrinterName").property("text") == X1, 10, "Settings to name the new default")
    ui.shot("settings-printing-x1")


def journey_search(ui):
    f = ui.item("settingsSearch")
    ui.click(f)
    ui.type("bed size")
    ui.wait_until(lambda: ui.sees("Bed size when no printer is chosen"), 5, "the search to find the bed size")
    ui.check(not ui.sees("Spending cap per message"), "other rows are filtered out")
    ui.shot("settings-search")
    ui.key("Ctrl+A")
    ui.key("Backspace")
    ui.settle(200)


def journey_just_design_from_settings(ui):
    toasts_gone(ui)
    ui.check(ui.js("Store.printOn") is True, "a configured slicer kept this person on printing")
    ui.run_js("Store.openSettings('general')")
    open_sheet_wait(ui, "settings")
    ui.wait_until(lambda: ui.find(name="capCard_print") is not None, 10, "the Set up for cards")
    ui.settle(300)
    ui.shot("settings-set-up-for")
    ui.click("capCard_print")
    ui.wait_until(lambda: ui.js("!Store.printOn"), 10, "3D printing to turn off")
    ui.settle(300)
    tabs = ui.texts("sheetCard")
    ui.check("Printing" not in tabs, f"the Printing tab is gone: {tabs[:12]}")
    ui.shot("settings-just-design")
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 4, "the sheet to close")
    # printing off hides every print surface, even for a design made for printing; nothing was uninstalled
    ui.wait_until(lambda: ui.find(name="printerChip") is None, 5, "the printer chip to go")
    ui.check(not ui.sees("not for printing", "topBar"), "no “just designing” chip either")
    ui.check("fit" not in [s["id"] for s in ui.js("Store.stages")], "no Fit stage")
    ui.check((ui.api("/install") and any(r["id"] == "slicer.bambu" and r["status"] == "ok" for r in ui.api("/install")["software"])),
             "the slicer is still installed")
    ui.shot("workspace-printing-off")
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "Home")
    ui.check(ui.js("Store.purposeInfo['default']") == "model", "new designs now start as 3D models")
    ui.settle(800)
    ui.run_js("Store.openSettings('general')")
    open_sheet_wait(ui, "settings")
    ui.wait_until(lambda: ui.find(name="capCard_print") is not None, 10, "the Set up for cards")
    ui.click("capCard_print")
    ui.wait_until(lambda: ui.js("Store.printOn"), 10, "3D printing to turn on again")
    ui.wait_until(lambda: "Printing" in ui.texts("sheetCard"), 5, "the Printing tab back")
    ui.key("Escape")
    ui.run_js("Store.open(Store.studio.projects[0].id).then(function () { Store.setStage('prove') })")
    ui.wait_until(lambda: ui.store.get("screen") == "work", 30, "the design")
    ui.wait_until(lambda: ui.find(name="printerChip") is not None, 10, "the printer chip back")
    ui.check("fit" in [s["id"] for s in ui.js("Store.stages")], "the Fit stage back")
    ui.settle(600)
    ui.shot("workspace-printing-on")


def journey_appearance(ui):
    """Settings › General › Appearance switches between the dark and the light bench at once."""
    if ui.js("Bridge.appearanceOverride"):          # FORM_APPEARANCE forces one for this run: the control says so and is off
        return
    ui.run_js("Store.openSettings('general')")
    open_sheet_wait(ui, "settings")
    seg = ui.item("appearanceSeg")
    ui.check(ui.js("Theme.dark") is True, "Form Studio starts dark")
    ui.click_text("Light", within=seg)
    ui.wait_until(lambda: ui.js("Theme.dark") is False and ui.js("Theme.appearance") == "light", 3, "the light appearance")
    ui.check(ui.js("String(Theme.plate)") != "#0e1113", "the bench follows")
    ui.settle(300)
    ui.shot("settings-appearance-light")
    ui.click_text("Dark", within=seg)
    ui.wait_until(lambda: ui.js("Theme.dark") is True, 3, "the dark appearance again")
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 4, "the sheet to close")
