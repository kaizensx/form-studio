"""Someone with no 3D printer and no slicer: printing is opt-in, so the launcher leaves 3D printing off and installs
nothing printing-related, a new design is a 3D model, and its checks, Prove, Release and exports work without any
slicer and without a word about printing. Then 3D printing is turned on in Settings › Set up for, the design is switched
to "For 3D printing" in its Brief and back, and the top bar follows.

Environment (tests/test_ui_journeys.py test_no_printer): every slicer points at a program that does not exist."""
import os
from pathlib import Path

from _lib import open_project, toasts_gone, wait_job

DATA = "empty"
S = {}


def data(ui):
    return ui.api("/projects/" + S["pid"])


def toml(ui):
    return (Path(os.environ["FORM_UITEST_TMP"]) / "studio.toml").read_text(encoding="utf-8")


def journey_first_run_just_designing(ui):
    ui.wait_until(lambda: ui.store.get("welcome") is True, 30, "the first-run screen")
    ui.wait_until(lambda: ui.store.get("software") is not None and ui.js("!!Store.caps"), 90, "the software check")
    ui.expect("What do you want to make?")
    ui.check(not ui.js("Store.capOn('print')"), "3D printing starts off")
    ui.check(not ui.js("Store.printingDecided"), "nothing is written before Continue")
    ui.settle(300)
    ui.shot("noprinter-first-run-choice")
    ui.click_text("Continue")
    ui.expect("Step 2 of 3")
    ui.wait_until(lambda: ui.js("Store.printingDecided && !Store.prints"), 10, "the choice to be applied")
    ui.check("capabilities = " in toml(ui) and '"print"' not in toml(ui), "written to studio.toml without printing")
    sw = ui.api("/install")
    sl = [r for r in sw["software"] if r["id"].startswith("slicer.")]
    ui.check(sl and all(r["level"] == "optional" for r in sl), "slicers are optional while printing is off")
    ui.eq([g["id"] for g in sw["groups"]][-1], "slicer", "3D printing is the last group in Software")
    ui.run_js("var p = {}; Store.software.software.forEach(function (r) { p[r.id] = false }); Store.installPick = p")
    ui.click_text("Continue")
    ui.expect("Step 3 of 3")
    ui.check(not any(i.startswith("slicer.") for i in ui.api("/capabilities")["install"]), "no slicer is installed")
    ui.expect("3D printing is off")
    ui.settle(300)
    ui.shot("noprinter-first-run-just-design")
    if ui.find(name="welcomeOpenWithout") is not None:
        ui.click("welcomeOpenWithout")
    else:
        ui.click_text("Open Form Studio")
    ui.wait_until(lambda: ui.store.get("screen") == "home" and ui.store.get("welcome") is False, 30, "Home")
    ui.check(ui.find(name="purposeChip") is None, "no “just designing” chip")
    ui.check(ui.find(name="printerChip") is None, "no printer chip")
    ui.check(not ui.js("Store.setup && Store.setup.attention.some(function (i) { return i.indexOf('slicer') === 0 })"),
             "setup does not ask for a slicer")
    ui.shot("noprinter-home")


def journey_a_3d_model(ui):
    # the API the new-design flow calls; no purpose given: the person's default, a 3D model
    ui.run_js("Store.newDesign({ name: 'Wall plate', recipe: 'storage_box' })")
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.store.get("pid"), 60, "the new design to open")
    S["pid"] = ui.store.get("pid")
    wait_job(ui, S["pid"])
    open_project(ui, S["pid"])
    d = data(ui)
    ui.eq(d["purpose"]["purpose"], "model", "a 3D model")
    ui.eq(d["status"]["slice"]["off"]["why"], "purpose", "not sliced because it is not for printing")
    ui.check("Slice" not in ui.texts("pipeline"), "the pipeline strip has no Slice step")
    ui.check(ui.find(name="purposeChip") is None and ui.find(name="printerChip") is None, "the top bar says nothing about printing")
    ui.check("fit" not in [x["id"] for x in ui.js("Store.stages")], "no Fit stage")
    ids = [c["id"] for c in d["checks"]["checks"]]
    ui.check(not {"envelope", "overhang", "adhesion", "wall"} & set(ids), f"no print checks: {ids}")
    ui.check({"glb", "obj", "step", "stl"} <= set(d["exports"]["files"]), "STEP, STL, OBJ and GLB exports")
    ui.click("stage-prove")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "Prove")
    ui.settle(300)
    ui.check(ui.find(name="modelChecksNote") is None and ui.find(name="makePrintable") is None, "Prove does not talk about printing")
    ui.check(not ui.exists(text="Print orientation"), "no print orientation table")
    ui.check(not ui.exists(name="designOnlyNote"), "no Design only note: nothing is missing")
    ui.settle(300)
    ui.shot("noprinter-prove")


def journey_release_a_model(ui):
    toasts_gone(ui)
    ui.click("stage-release")
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "Release")
    ui.settle(300)
    g = data(ui)["gate"]
    ui.check(not any("slice" in r.lower() for r in g["reasons"]) and "slice" not in g["evidence_level"].lower(),
             f"the gate says nothing about slicing: {g}")
    ui.check(ui.find(name="releaseModel") is None, "Release does not talk about printing while it is off")
    for c in ui.find_all(name="ackCheck"):
        ui.click(c)
    btn = ui.item(text="Approve and release r%02d" % data(ui)["project"]["head"])
    ui.wait_until(lambda: btn.property("enabled") is True, 5, "Approve to be enabled")
    ui.shot("noprinter-release")
    ui.click(btn)
    ui.wait_until(lambda: data(ui)["approval"]["state"] == "approved", 90, "the release")
    rel = data(ui)["releases"][-1]
    v = ui.api("/projects/%s/release/%s" % (S["pid"], rel))
    names = [f["file"] for f in v["files"]]
    for ext in (".step", ".stl", ".obj", ".glb", ".3mf", "_iso.png"):
        ui.check(any(n.endswith(ext) for n in names), f"{ext} in the release: {names}")
    ui.check(v["intact"] and not any(n.endswith(".gcode") for n in names), "intact, with no G-code")


def journey_purpose_switch(ui):
    toasts_gone(ui)
    ui.check(ui.find(name="purposeSeg") is None, "no print purpose to pick while printing is off")
    ui.run_js("Store.openSettings('general')")
    ui.wait_until(lambda: ui.find(name="capCard_print") is not None, 10, "the Set up for cards")
    ui.click("capCard_print")                          # turn 3D printing on; no slicer here, so nothing installs
    ui.wait_until(lambda: ui.js("Store.printOn"), 10, "3D printing to turn on")
    ui.key("Escape")
    ui.wait_until(lambda: ui.store.get("sheet") is None, 4, "the sheet to close")
    ui.wait_until(lambda: ui.find(name="purposeChip") is not None, 5, "a 3D model now says it is not a print")
    toasts_gone(ui)
    ui.settle(600)                                     # the top bar and stage tabs settle after printing turns on
    ui.click("stage-brief")
    ui.wait_until(lambda: ui.store.get("stage") == "brief", 3, "Brief")
    seg = ui.item("purposeSeg")
    ui.scroll_to(seg, 0.5)
    ui.click_text("For 3D printing", within=seg)
    ui.wait_until(lambda: data(ui)["purpose"]["purpose"] == "print", 10, "the design to be for printing")
    ui.wait_until(lambda: ui.js("Store.purpose") == "print", 10, "the app to follow")
    ui.eq(data(ui)["status"]["slice"]["off"]["why"], "no_slicer", "a print with no slicer: Design only, never an error")
    ui.wait_until(lambda: ui.find(name="printerChip") is not None, 5, "the printer chip for a design made for printing")
    wait_job(ui, S["pid"])
    ids = [c["id"] for c in data(ui)["checks"]["checks"]]
    ui.check("envelope" in ids, f"the print checks run now: {ids}")
    ui.wait_until(lambda: "Slice" in ui.texts("pipeline"), 5, "the Slice step back in the strip")
    ui.shot("noprinter-switched-to-print")
    ui.click_text("Just a 3D model", within=ui.item("purposeSeg"))
    ui.wait_until(lambda: data(ui)["purpose"]["purpose"] == "model", 10, "a 3D model again")
    ui.wait_until(lambda: ui.find(name="purposeChip") is not None, 5, "the 3D model chip again")
    pick = ui.item("processPick")
    ui.check(pick is not None, "a model can name how it will be made")
    ui.run_js("Store.setPurpose('model', 'cnc')")
    ui.wait_until(lambda: data(ui)["purpose"].get("process") == "cnc", 10, "the process")
    wait_job(ui, S["pid"])
    feat = [c for c in data(ui)["checks"]["checks"] if c["id"] == "feature"]
    ui.check(feat and feat[0]["status"] in ("PASS", "WARN", "FAIL") and "CNC" in feat[0]["detail"], f"checked against CNC: {feat}")
