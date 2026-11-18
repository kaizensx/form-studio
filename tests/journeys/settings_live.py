"""Settings apply at once, both ways: the default printer chosen from Settings › Printing shows in Settings, the top bar
and the open design's checks; "I just design" in Settings › General hides the Printing tab and the printer chip, and
"I have a 3D printer" brings them back. Nothing needs a restart.

Environment (tests/test_ui_journeys.py test_settings_live): Bambu Studio is a fixture config folder (an A1 mini, an X1
Carbon and a user printer "My mini"); every other slicer points at a program that does not exist."""
from _lib import make, open_sheet_wait, sheet, toasts_gone

DATA = "fresh"
X1 = "Bambu Lab X1 Carbon 0.4 nozzle"


def journey_default_printer_from_settings(ui):
    pid = make(ui, "hook", "Settings journey")
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
    ui.wait_until(lambda: ui.sees(X1, ui.item("printerChip")), 10, "the top bar chip")
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
    ui.check(not ui.sees("Spending limit per message"), "other rows are filtered out")
    ui.shot("settings-search")
    ui.key("Ctrl+A")
    ui.key("Backspace")
    ui.settle(200)


def journey_just_design_from_settings(ui):
    toasts_gone(ui)
    ui.run_js("Store.openSettings('general')")
    open_sheet_wait(ui, "settings")
    ui.click("settingsJustDesign")
    ui.wait_until(lambda: ui.js("!Store.prints"), 10, "“I just design” to apply")
    ui.settle(300)
    tabs = ui.texts("sheetCard")
    ui.check("Printing" not in tabs, f"the Printing tab is gone: {tabs[:12]}")
    ui.shot("settings-just-design")
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 4, "the sheet to close")
    # the open design was made for printing: it keeps its printer chip; Home says "just designing"
    ui.check(ui.find(name="printerChip") is not None, "a design made for printing still shows its printer")
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "Home")
    ui.wait_until(lambda: ui.find(name="purposeChip") is not None, 5, "the “just designing” chip")
    ui.check(ui.js("Store.purposeInfo['default']") == "model", "new designs now start as 3D models")
    ui.settle(800)                                     # Home sets its bench and the top bar settles before the click
    ui.click("purposeChip")
    open_sheet_wait(ui, "settings")
    ui.click("settingsPrinter")
    ui.wait_until(lambda: ui.js("Store.prints"), 10, "“I have a 3D printer” to apply")
    ui.wait_until(lambda: "Printing" in ui.texts("sheetCard"), 5, "the Printing tab back")
    ui.key("Escape")
    ui.wait_until(lambda: ui.find(name="printerChip") is not None, 5, "the printer chip back")
