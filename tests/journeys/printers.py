"""Printers: pick the printer, filament and process for one design, make one the default, go back to the default.

Environment the test suite sets (tests/test_ui_journeys.py test_printers): a studio.toml whose Bambu Studio is a
fixture config folder (tests/test_printers.py bambu_dir: an A1 mini 0.4/0.6, an X1 Carbon and a user printer
"My mini") and every other slicer pointed at a program that does not exist. Nothing is sliced for real."""
from _lib import make, open_sheet_wait, sheet

DATA = "fresh"


def open_printers(ui):
    ui.key("Ctrl+K")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is True, 3, "the palette")
    ui.type("printer")
    pal = ui.item("palette")
    ui.wait_until(lambda: pal.property("selText") == "Choose printer", 3, "“Choose printer” in the palette")
    ui.key("Return")
    open_sheet_wait(ui, "printer")
    ui.wait_until(lambda: ui.find_all(name="printerRow"), 20, "the printer list")


def row(ui, pid):
    return ui.wait_until(lambda: next((r for r in ui.find_all(name="printerRow", shown=False) if r.property("pid_") == pid), None),
                         8, f"the row {pid}")


def pick(ui, pid):
    sh = ui.item("printerSheet")
    ui.wait_until(lambda: sh.property("busy") == "", 20, "the sheet to finish saving")    # rows ignore clicks while it saves
    r = row(ui, pid)
    ui.scroll_to(r, 0.5)
    ui.click(r, 0.3, 0.5)
    ui.wait_until(lambda: sh.property("pickId") == pid, 10, f"the row {pid} to be chosen")
    ui.wait_until(lambda: ui.find(name="printerFilament") is not None and ui.find(name="printerFilament").property("value"),
                  15, "the filament of the chosen printer")
    ui.settle(200)


def run(ui):
    pid = make(ui, "hook", "Printer journey")
    inv = ui.api("/printers")
    ids = [p["id"] for p in inv["printers"]]
    ui.check({"bambu:My mini", "bambu:Bambu Lab X1 Carbon 0.4 nozzle", "bambu:Bambu Lab A1 mini 0.6 nozzle"} <= set(ids), f"printers: {ids}")
    ui.check("bambu:Bambu Lab A1 mini 0.8 nozzle" not in ids, "a nozzle the person did not enable is not offered")

    # 1. this design on the X1 Carbon
    open_printers(ui)
    ui.shot("printers-sheet")
    pick(ui, "bambu:Bambu Lab X1 Carbon 0.4 nozzle")
    ui.eq(ui.find(name="printerFilament").property("value"), "Bambu PLA Basic @BBL X1C", "the slicer's filament for that printer")
    ui.eq(ui.find(name="printerProcess").property("value"), "0.20mm Standard @BBL X1C", "the slicer's process for that printer")
    ui.click("printerUseHere")
    ui.wait_until(lambda: (ui.api("/projects/" + pid)["project"].get("printer") or {}).get("machine") == "Bambu Lab X1 Carbon 0.4 nozzle",
                  10, "the project to keep its printer")
    st = ui.api("/printers?project=" + pid)["project"]
    ui.eq((st["source"], st["env"]["envelope"]), ("project", [256.0, 256.0, 250.0]), "checks use that printer's bed")
    ui.wait_until(lambda: ui.sees("Bambu Lab X1 Carbon 0.4 nozzle", "sheetCard"), 5, "the sheet to show the new choice")

    # 2. the user printer as the default, written to studio.toml
    pick(ui, "bambu:My mini")
    ui.click("printerMakeDefault")
    ui.wait_until(lambda: (ui.api("/printers").get("default") or {}).get("machine") == "My mini", 10, "the default printer")
    import os
    from pathlib import Path
    toml = (Path(os.environ["FORM_UITEST_TMP"]) / "studio.toml").read_text(encoding="utf-8")
    ui.check('machine = "My mini"' in toml, "the default is written to studio.toml")
    ui.check(any(p.name.startswith("studio.toml.bak-form-") for p in Path(os.environ["FORM_UITEST_TMP"]).iterdir()),
             "studio.toml was backed up first")

    # 3. back to the default for this design
    ui.wait_until(lambda: ui.item("printerSheet").property("busy") == "", 20, "the default to finish saving")
    ui.click_text("Use the default")
    ui.wait_until(lambda: "printer" not in ui.api("/projects/" + pid)["project"], 10, "the design to forget its own printer")
    st = ui.api("/printers?project=" + pid)["project"]
    ui.eq((st["source"], st["choice"]["machine"], st["env"]["envelope"]), ("default", "My mini", [180.0, 180.0, 180.0]),
          "the design follows the default")
    ui.key("Escape")
    ui.wait_until(lambda: sheet(ui) is None, 4, "the sheet to close")
    ui.settle(300)
    ui.expect("My mini")                                   # the top bar names the printer this design uses
    ui.shot("printers-default")
