"""Direction I (docs/design/directions/i/IA.md), as a person meets it: four modes at the top, the Overview from the
design capsule, Fit as a study in Check, the view cube and the shading chip at the stage's top right, and the legend
strip under the part while a result is shown on it."""
from _lib import goto, phone_dock, plate_toggle, toasts_gone

DATA = "fresh"


def _rect(ui, name):
    it = ui.item(name)
    p = it.mapToScene(it.boundingRect().topLeft())
    return (p.x(), p.y(), it.width(), it.height())


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    phone_dock(ui)                                     # a design made for printing: it has a fit model
    ui.wait_until(lambda: ui.js("!!Store.viewer && !Store.viewer.revealing && Store.buildOf === 0") is True, 60, "the build-up to end")
    toasts_gone(ui)

    # ── four modes, each with its line; Describe and Fit are not among them ──
    ui.eq(ui.js("Store.stages.map(function (s) { return s.title }).join(' ')"), "Design Check Make Document", "the four modes")
    for gone in ("stage-brief", "stage-fit"):
        ui.check(not ui.exists(gone), f"{gone} is no longer a tab")
    for sid, key in (("prove", "Ctrl+2"), ("release", "Ctrl+3"), ("document", "Ctrl+4"), ("shape", "Ctrl+1")):
        goto(ui, sid)
        ui.eq(ui.js("Store.mode"), sid, f"the mode after a click on {sid}")
        ui.check(len(ui.texts(ui.item("stage-" + sid))) >= 2 and ui.texts(ui.item("stage-" + sid))[1] != "", f"{sid} carries its one line of state: {ui.texts(ui.item('stage-' + sid))}")
    for sid, key in (("prove", "Ctrl+2"), ("release", "Ctrl+3"), ("document", "Ctrl+4"), ("shape", "Ctrl+1")):
        ui.key(key)
        ui.wait_until(lambda: ui.store.get("stage") == sid, 3, f"{key} to go to {sid}")
    ui.check(ui.find(name="printerChip") is None, "the printer is not named in Design")
    goto(ui, "release")
    ui.wait_until(lambda: ui.find(name="printerChip", within=ui.item("topBar")) is not None, 5, "the printer is named in Make")
    ui.shot("direction-i-make")

    # ── Document: what exists has a state, what is not built says so ──
    goto(ui, "document")
    ui.settle(400)
    ui.check(ui.sees("not built yet", within=ui.item("docDrawing")), "the drawing sheet says it is not built yet")
    ui.shot("direction-i-document")

    # ── the Overview: Describe, opened from the design capsule; the mode stays ──
    goto(ui, "shape")
    goto(ui, "brief")
    ui.eq(ui.store.get("stage"), "shape", "the Overview is not a mode: Design stays")
    ui.settle(500)
    ov = ui.item("overview")
    ui.check(ui.exists("purposeSeg", within=ov), "the brief is in the Overview")
    ui.check(ui.exists("overviewRevisions", within=ov), "and the revisions")
    ui.shot("direction-i-overview")
    ui.click("overviewClose")
    ui.wait_until(lambda: ui.js("Store.overview") is False, 3, "the Overview to close")
    ui.run_js("Store.setStage('brief')")               # the old route still lands
    ui.wait_until(lambda: ui.js("Store.overview") is True, 3, "setStage('brief') to open the Overview")
    ui.click("stage-prove")
    ui.wait_until(lambda: ui.js("Store.overview") is False and ui.store.get("stage") == "prove", 3, "a mode to close the Overview")

    # ── Fit is a study in Check: a row with its number and how it is known ──
    row = ui.item("studyFit")
    ui.check(any("%" in t for t in ui.texts(row)) and ui.sees("modelled", within=row), f"the Fit row reads as a study: {ui.texts(row)}")
    ui.click("studyFit")
    ui.wait_until(lambda: ui.store.get("stage") == "fit", 3, "the Fit study to open")
    ui.eq(ui.js("Store.mode"), "prove", "Fit is in Check")
    ui.eq(int(ui.item("stageTabs").property("at")), 1, "Check stays lit while the Fit study is open")
    ui.shot("direction-i-fit-study")
    ui.click("studyBack")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "the way back to the studies")

    # ── the view cube and the shading chip, top right of the stage; no view buttons at the foot ──
    goto(ui, "shape")
    ui.settle(400)
    ui.check(not ui.exists("viewsCapsule"), "the view buttons at the foot are gone")
    c, pane, dock = _rect(ui, "viewCube"), _rect(ui, "programPane"), _rect(ui, "toolDock")
    ui.check(c[0] + c[2] <= pane[0] - 8 and c[0] > dock[0] + dock[2] and abs(c[1] - pane[1]) <= 1, f"the cube stands at the stage's top right: {c} beside {pane}")
    for fx, fy, name in ((0.5, 0.36, "top"), (0.38, 0.62, "front"), (0.62, 0.58, "side"), (0.5, 0.94, "iso")):
        ui.wait(450)                                   # not a double click
        ui.click("viewCube", fx, fy)
        ui.wait_until(lambda: ui.store.get("viewName") == name, 3, f"the cube's {name} view")
    ui.wait(450)
    ui.dclick("viewCube", 0.5, 0.94)
    ui.wait_until(lambda: ui.store.get("viewName") == "under", 3, "a double click to look from under")
    ui.key("1")
    ui.wait_until(lambda: ui.store.get("viewName") == "iso", 3, "key 1")
    s = _rect(ui, "shadeChip")
    ui.check(abs(s[0] + s[2] - (c[0] + c[2])) <= 1 and s[1] >= c[1] + c[3], f"the shading chip stands under the cube: {s}")
    was = ui.js("Store.viewer.plateShown")
    plate_toggle(ui)
    ui.wait_until(lambda: ui.js("Store.viewer.plateShown") is not was, 3, "the chip's menu to switch the build plate")
    plate_toggle(ui)
    ui.shot("direction-i-design")

    # ── a result on the part has its legend under the part: the scale, how it is known, what it does not tell ──
    ui.check(not ui.exists("resultStrip"), "no strip while nothing is shown on the part")
    ui.run_js('Store.setAnalysis("thickness")')
    ui.wait_until(lambda: ui.js("!!Store.analysis && Store.analysis.map === 'thickness' && !Store.analysisBusy"), 120, "the thickness map")
    ui.settle(600)
    r = _rect(ui, "resultStrip")
    pane, dock = _rect(ui, "programPane"), _rect(ui, "toolDock")
    ui.check(r[0] >= dock[0] + dock[2] and r[0] + r[2] <= pane[0], f"the strip lies under the part, between the dock and the pane: {r}")
    ui.check(ui.sees("Wall thickness", within=ui.item("resultStrip")), "it names the result")
    ui.check("computed" in str(ui.item("stripEvidence").property("text")).lower(), "it says how the result is known")
    ui.check(len(str(ui.item("stripLimits").property("text"))) > 20, "and what it does not tell")
    ui.check(not ui.exists("analysisLegend"), "the legend is no longer a panel in the right column")
    ui.shot("direction-i-strip")
    ui.run_js('Store.setAnalysis("")')
    ui.wait_until(lambda: not ui.exists("resultStrip"), 3, "the strip to leave with the result")
    ui.no_warnings()
