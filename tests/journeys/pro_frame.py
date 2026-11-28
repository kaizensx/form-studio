"""The pro frame around a design: the labelled ribbon per mode, the document tabs, the project rail.

- The ribbon: at the head of the stage, the mode's tools with their labels in captioned groups; the dock keeps the four
  universal tools. A tool whose feature kind the engine does not list is not shown, and appears when it is listed.
  Keys are in the tooltips. Nothing wraps: in a narrow window groups lose their labels, then the captions go, then
  tools move into More. Hide folds it into the dock (remembered: a design opened again still has it hidden); the stage
  gives up the ribbon's 44 px and no more.
- The tabs: the model is always there; a result opened anywhere is a tab; tabs switch with ⌘1..9 (Alt elsewhere),
  close and reorder, and come back when the design is opened again.
- The rail: Home, the Bench, recent designs with their conversation counts, Trash and Settings. Folded it is 44 px
  and the stage keeps its width; opened it is 220 px, remembered.
Pictures (FORM_CRAFT_OUT): the ribbon, the tabs and the rail at each window size, column open and folded."""
import json
import os
import time

from _lib import TAB_KEY, make, open_project, tool, toasts_gone, wait_job

DATA = "fresh"
TALK = [{"t": "user", "text": "make it a little taller", "local": True},
        {"t": "text", "text": "Done as revision 2.", "local": True}]
S = {}


def rect(ui, name):
    it = ui.item(name) if isinstance(name, str) else name
    p = it.mapToScene(it.boundingRect().topLeft())
    return (round(p.x(), 1), round(p.y(), 1), round(it.width(), 1), round(it.height(), 1))


def crop(ui, items, name, pad=10):
    out = os.environ.get("FORM_CRAFT_OUT")
    if not out:
        return
    from pathlib import Path
    from PySide6.QtCore import QRect, Qt
    ui._pump(80)
    img = ui.win.grabWindow()
    dpr = img.devicePixelRatio() or 1.0
    rs = [rect(ui, i) for i in items if ui.exists(i)]
    if not rs:
        return
    x0, y0 = max(0, min(r[0] for r in rs) - pad), max(0, min(r[1] for r in rs) - pad)
    x1, y1 = max(r[0] + r[2] for r in rs) + pad, max(r[1] + r[3] for r in rs) + pad
    r = QRect(int(x0 * dpr), int(y0 * dpr), int((x1 - x0) * dpr), int((y1 - y0) * dpr))
    c = img.copy(r).scaled(int(r.width() * 2 / dpr), int(r.height() * 2 / dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    Path(out).mkdir(parents=True, exist_ok=True)
    col = "col" if ui.js("Store.talkCol > 0") else "folded"
    c.save(str(Path(out) / f"{name}-{ui.win.width()}-{col}-{os.environ.get('FORM_APPEARANCE', 'dark')}.png"))


def whole(ui, name):
    out = os.environ.get("FORM_CRAFT_OUT")
    if out:
        from pathlib import Path
        Path(out).mkdir(parents=True, exist_ok=True)
        col = "col" if ui.js("Store.talkCol > 0") else "folded"
        ui._pump(80)
        ui.win.grabWindow().save(str(Path(out) / f"{name}-{ui.win.width()}-{col}-{os.environ.get('FORM_APPEARANCE', 'dark')}.png"))


def frames(ui, ms):
    n = [0]

    def tick():
        n[0] += 1
    ui.win.frameSwapped.connect(tick)
    ui._pump(ms)
    ui.win.frameSwapped.disconnect(tick)
    return n[0]


def free(ui):
    return ui.js("(function(){var v=Store.viewer;return [v.width-v.insetLeft-v.insetRight, v.height-v.insetTop-v.insetBottom, v.insetTop]})()")


def column(ui, on):
    ui.run_js("Store.talkOpen = true; Store.chatItems = %s; Store.talkCalm = %s" % (json.dumps(TALK), "false" if on else "true"))
    ui.settle(1300)


def journey_ribbon(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["pid"] = make(ui, "storage_box", "Parts box", purpose="model")
    ui.wait_until(lambda: ui.js("!!Store.viewer && !Store.viewer.revealing && Store.buildOf === 0") is True, 60, "the build-up to end")
    toasts_gone(ui)
    ui.click("stage-shape")
    ui.settle(400)
    ui.check(ui.exists("toolRibbon") and ui._shown(ui.item("toolRibbon")), "the ribbon is at the head of the stage")
    r, d = rect(ui, "toolRibbon"), rect(ui, "toolDock")
    ui.eq(r[3], 38.0, "one slim band")
    ui.check(d[1] >= r[1] + r[3] + 4, f"the dock stands under it: {d} / {r}")
    ui.check(r[0] + r[2] <= rect(ui, "viewCube")[0] - 4, f"clear of the view cube: {r}")
    # the dock keeps the four universal tools
    for n in ("railSelect", "railMeasure", "railSection", "railAnnotate"):
        ui.check(ui._shown(ui.item(n)), f"{n} in the dock")
    for n in ("railSketch", "railRound", "railSep"):
        ui.check(not ui.exists(n), f"{n} is not in the dock while the ribbon shows")
    ui.check(d[3] < 4 * 38 + 24, f"the dock holds the four alone: {d}")

    # ── each mode: its groups, captioned; the tools that have an engine; keys in the tooltips ──
    want = {"shape": ({"create": ["sketch", "extrude", "cut", "revolve"], "modify": ["fillet", "chamfer", "hole", "pattern", "shell"],
                       "insert": ["part", "text"]}, ["sweep", "loft", "rib", "mirror", "draft", "split", "move_face", "plane", "axis"]),
            "prove": ({"inspect": ["analyze", "mass", "section"], "review": ["history"]}, []),
            "release": ({"output": ["render"]}, ["slice", "plates"]),
            "document": ({"sheets": ["views", "dims"], "picture": ["frame"]}, [])}
    four = [rect(ui, n) for n in ("railSelect", "railMeasure", "railSection", "railAnnotate")]
    for mode, (groups, absent) in want.items():
        # every value the tools' opacity takes on the way, from the item's own signal (a slow machine draws few frames)
        body, seen = ui.item("ribbonBody"), []

        def took():
            seen.append(body.opacity())
        body.opacityChanged.connect(took)
        ui.click("stage-" + mode)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 0.35:
            ui._pump(16)
        body.opacityChanged.disconnect(took)
        ui.settle(300)
        if mode != "shape":
            ui.check(any(0.02 < o < 0.98 for o in seen), f"{mode}: the tools cross-fade, they do not cut: {seen[:6]}")
        for g, ids in groups.items():
            ui.check(ui.exists("ribbonGroup-" + g), f"{mode}: the {g} group")
            for t in ids:
                ui.check(ui.exists("ribbon-" + t) or ui.exists("ribbonMore"), f"{mode}: {t} in the ribbon (or its More)")
        for t in absent:
            ui.check(not ui.exists("ribbon-" + t), f"{mode}: {t} is not shown: the engine has no {t} yet / it does not apply")
        ui.eq([rect(ui, n) for n in ("railSelect", "railMeasure", "railSection", "railAnnotate")], four, f"{mode}: the four have not moved")
        ui.eq(rect(ui, "toolRibbon")[3], 38.0, f"{mode}: one line, nothing wraps")
        crop(ui, ["toolRibbon", "toolDock"], "ribbon-" + mode)
    ui.click("stage-shape")
    ui.settle(300)
    ui.eq(ui.item("ribbon-sketch").property("keys"), "S", "Sketch says its key")
    ui.eq(ui.item("ribbon-fillet").property("keys"), "Shift+F", "Fillet says its key")
    ui.check(ui.exists("ribbonCaption-create") and ui.item("ribbonCaption-create").property("text") == "Create", "the Create caption")

    # ── a kind the engine learns appears by itself (the capability check reads GET /studio feature_kinds) ──
    kinds = ui.js("Store.studio.feature_kinds")
    ui.check(isinstance(kinds, list) and "fillet" in kinds and "extrude" in kinds, f"the engine lists its feature kinds: {kinds}")
    ui.run_js("Store.studio = Object.assign({}, Store.studio, { feature_kinds: Store.studio.feature_kinds.concat(['sweep', 'mirror']) })")
    ui.settle(300)
    ui.check(ui.exists("ribbon-sweep") or ui.exists("ribbonMore"), "Sweep appears once the engine lists it")
    ui.run_js("Store.reloadStudio()")
    ui.wait_until(lambda: not ui.exists("ribbon-sweep"), 5, "and goes when the engine does not")

    # ── the tools work from the ribbon ──
    tool(ui, "fillet")
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate" and ui.js("Ws.want") == "fillet", 3, "Fillet from the ribbon picks edges")
    ui.check(ui.item("ribbon-fillet").property("active") is True, "the ribbon lights Fillet")
    c = rect(ui, "toolCapsule")
    ui.check(c[1] >= r[1] + r[3] and c[0] >= rect(ui, "toolDock")[0] + 48 + 8, f"the capsule stands under the ribbon, right of the dock: {c}")
    crop(ui, ["toolRibbon", "toolDock", "toolCapsule"], "ribbon-fillet")
    ui.key("Escape")
    ui.wait_until(lambda: ui.js("Ws.tool") == "select", 3, "Esc hands back to Select")
    ui.key("S")
    ui.wait_until(lambda: ui.js("Store.sketchHost.picking") is True, 3, "S: Sketch")
    ui.check(ui.item("ribbon-sketch").property("active") is True, "the ribbon lights Sketch")
    ui.key("Escape")
    ui.wait_until(lambda: ui.js("Store.sketchHost.picking") is False, 3, "Esc leaves it")
    ui.click("stage-prove")
    ui.settle(300)
    tool(ui, "analyze")
    ui.wait_until(lambda: ui.js("Ws.tool") == "analyze", 3, "Analyze from the ribbon")
    ui.key("V")

    # ── idle: the ribbon draws nothing ──
    ui.hover("viewport", 0.5, 0.25)
    ui.settle(1500)
    n = frames(ui, 2000)
    print(f"RIBBON IDLE: {n} frames in 2 s", flush=True)
    ui.check(n <= 2, f"idle redraws with the ribbon: {n} frames in 2 s")

    # ── Hide: the dock takes the tools back; remembered when the design opens again ──
    ui.click("stage-shape")
    ui.settle(300)
    on = free(ui)
    ui.hover("ribbonHide")
    ui.settle(200)
    ui.click("ribbonHide")
    ui.wait_until(lambda: not ui.exists("toolRibbon") or not ui._shown(ui.item("toolRibbon")), 3, "the ribbon to fold away")
    ui.settle(900)
    off = free(ui)
    ui.eq(on[2] - off[2], 44, "the stage gains back exactly the ribbon's 44 px")
    ui.check(ui._shown(ui.item("railSketch")) and ui._shown(ui.item("railRibbon")), "the dock has the mode's tools again, and a way back")
    crop(ui, ["toolDock"], "dock-hidden")
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "Home")
    open_project(ui, S["pid"])
    ui.check(not ui.exists("toolRibbon") or not ui._shown(ui.item("toolRibbon")), "hidden is remembered")
    ui.click("railRibbon")
    ui.wait_until(lambda: ui.exists("toolRibbon") and ui._shown(ui.item("toolRibbon")), 3, "the ribbon back")
    ui.settle(600)


def journey_fits(ui):
    """At 1440, 1280 and 1100, column open and folded: one line, inside the stage's head, never over the cube."""
    for w, h in ((1440, 900), (1280, 800), (1100, 700)):
        ui.resize(w, h)
        for col in (False, True):
            column(ui, col)
            for mode in ("shape", "prove", "release", "document"):
                ui.click("stage-" + mode)
                ui.settle(450)
                r = rect(ui, "toolRibbon")
                ui.eq(r[3], 38.0, f"{w} {mode}: one line")
                lim = rect(ui, "viewCube")[0] if ui._shown(ui.item("viewCube")) else w
                ui.check(r[0] + r[2] <= lim - 4, f"{w} {mode}: clear of the cube ({r}, {lim})")
                more = ui.exists("ribbonMore") and ui._shown(ui.item("ribbonMore"))
                print(f"FIT {w} col={col} {mode}: ribbon {r[2]:.0f} px, more={more}", flush=True)
                if mode == "shape":
                    crop(ui, ["toolRibbon"], "ribbon-fit-" + mode)
            ui.click("stage-shape")
            ui.settle(400)
            whole(ui, "frame")
    ui.resize(1440, 900)
    column(ui, False)


def journey_tabs(ui):
    pid = S["pid"]
    ui.click("stage-shape")
    ui.settle(300)
    ui.check(not ui.exists("docTabs") or not ui._shown(ui.item("docTabs")), "one open thing: no tabs, the design capsule is enough")
    # a document opened from the ribbon is a tab
    ui.click("stage-document")
    ui.settle(300)
    tool(ui, "report")
    ui.wait_until(lambda: ui.js("Frame.active") == "doc:report", 3, "the report in front")
    ui.wait_until(lambda: ui.exists("docTab-doc:report"), 3, "its tab")
    ui.check(ui._shown(ui.item("docTabs")), "the tabs show")
    # a version compare is a tab
    d = ui.api("/projects/" + pid)
    ui.api("/projects/" + pid + "/commit", {"values": {"wall": 3.0}, "provenance": {}, "note": "wall", "origin": "user", "expect_head": d["project"]["head"]})
    wait_job(ui, pid)
    ui.run_js("Store.refresh(true)")
    ui.wait_until(lambda: ui.js("Store.project.head") == 2, 10, "r02")
    ui.run_js("Store.setStage('release'); Store.compareWith(1)")
    ui.wait_until(lambda: ui.js("Frame.active") == "compare:1", 10, "the compare in front")
    ui.wait_until(lambda: ui.exists("docTab-compare:1"), 3, "its tab")
    ui.eq([t["key"] for t in ui.js("Frame.all")], ["design", "doc:report", "compare:1"], "three tabs, in the order they opened")
    crop(ui, ["titleCapsule", "docTabs", "stageTabs"], "tabs")
    whole(ui, "tabs")
    # switch with the keys
    ui.key(TAB_KEY + "+1")
    ui.wait_until(lambda: ui.js("Frame.active") == "design" and not ui.js("!!Store.compare"), 3, f"{TAB_KEY}+1: the model, the compare put away")
    ui.key(TAB_KEY + "+2")
    ui.wait_until(lambda: ui.js("Frame.active") == "doc:report" and ui.js("Store.mode") == "document", 3, f"{TAB_KEY}+2: the report, in Document")
    ui.key(TAB_KEY + "+9")
    ui.wait_until(lambda: ui.js("Frame.active") == "compare:1", 10, f"{TAB_KEY}+9: the last tab, the compare again")
    # click a tab
    ui.click("docTab-design")
    ui.wait_until(lambda: ui.js("Frame.active") == "design", 3, "a click on the model tab")
    # reorder: the compare dragged before the report
    ui.drag("docTab-compare:1", (-int(rect(ui, "docTab-doc:report")[2]) - 10, 0), steps=10)
    ui.settle(300)
    ui.eq([t["key"] for t in ui.js("Frame.all")], ["design", "compare:1", "doc:report"], "dragged to a new place")
    # restore: the tabs come back with the design
    ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "Home")
    open_project(ui, pid)
    ui.wait_until(lambda: [t["key"] for t in ui.js("Frame.all")] == ["design", "compare:1", "doc:report"], 5, "the tabs restored")
    # close
    ui.click("docTab-doc:report")
    ui.wait_until(lambda: ui.js("Frame.active") == "doc:report", 3, "the report")
    ui.click("docTabClose-doc:report")
    ui.wait_until(lambda: ui.js("Frame.active") == "design" and not ui.exists("docTab-doc:report"), 3, "closed: the model in front")
    ui.hover("docTab-compare:1")             # the close of a tab behind shows under the pointer
    ui.settle(200)
    ui.click("docTabClose-compare:1")
    ui.wait_until(lambda: ui.js("Frame.tabs.length") == 0, 3, "all closed")
    ui.wait_until(lambda: not ui._shown(ui.item("docTabs")) if ui.exists("docTabs") else True, 3, "no tabs: the row as it was")


def journey_rail(ui):
    pid = S["pid"]
    other = make(ui, "vase", "Vase", purpose="model", open=False)
    ui.run_js("Store.reloadStudio()")
    ui.settle(400)
    for w, h in ((1440, 900), (1280, 800), (1100, 700)):
        ui.resize(w, h)
        for col in (False, True):
            column(ui, col)
            ui.check(ui.exists("projectRail") and ui._shown(ui.item("projectRail")), f"{w}: the rail")
            rr = rect(ui, "projectRail")
            ui.eq(rr[2], 44.0, f"{w}: folded, 44 px")
            if col:
                ui.eq(ui.js("Store.talkCol"), ui.js("Theme.edge") + min(480, max(300, min(w - 700, 340))), f"{w}: the conversation gives the rail its room; the stage starts where it did")
                ui.check(rect(ui, "talk")[0] >= rr[0] + rr[2] + 4, f"{w}: the conversation stands right of the rail")
            else:
                ui.check(rr[1] >= rect(ui, "toolDock")[1] + rect(ui, "toolDock")[3], f"{w}: under the dock, in its column")
                ui.eq(ui.js("Store.viewer.insetLeft") >= rect(ui, "toolDock")[0] + 48, True, f"{w}: the stage starts right of the dock, as before")
            print(f"STAGE {w} col={col}: free {free(ui)}", flush=True)
            crop(ui, ["projectRail", "toolDock"], "rail")
    ui.resize(1440, 900)
    column(ui, False)
    # the recent designs: the one in front lit, another one click away; Home, Bench, Settings
    ui.check(ui.exists("railDesign-" + other), "the other design is in the rail")
    ui.click("railBench")
    ui.wait_until(lambda: ui.store.get("benchOpen") is True, 3, "the Bench from the rail")
    ui.click("railBench")
    ui.wait_until(lambda: ui.store.get("benchOpen") is False, 3, "and closed again")
    # opened: 220 px, names and counts; the stage moves right of it; remembered
    w0 = free(ui)[0]
    ui.click("railToggle")
    ui.wait_until(lambda: rect(ui, "projectRail")[2] == 220.0, 3, "the rail opened")
    ui.settle(900)
    ui.check(ui.sees("Parts box", within=ui.item("projectRail")) and ui.sees("Vase", within=ui.item("projectRail")), "the designs by name")
    ui.check(free(ui)[0] <= w0, "opened, the stage makes room")
    crop(ui, ["projectRail"], "rail-open")
    whole(ui, "rail-open")
    column(ui, True)
    crop(ui, ["projectRail", "talk"], "rail-open")
    ui.check(rect(ui, "talk")[0] >= rect(ui, "projectRail")[0] + 220, "the conversation right of the opened rail")
    column(ui, False)
    ui.click("railDesign-" + other)
    ui.wait_until(lambda: ui.store.get("pid") == other, 20, "the other design from the rail")
    ui.wait_until(lambda: ui.js("!!Store.view"), 30, "its model")
    ui.check(ui.js("Frame.railOpen") is True and rect(ui, "projectRail")[2] == 220.0, "still open in the next design")
    ui.click("railToggle")
    ui.wait_until(lambda: rect(ui, "projectRail")[2] == 44.0, 3, "folded")
    ui.click("railHome")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 10, "Home from the rail")
    ui.check(not ui.exists("projectRail") or not ui._shown(ui.item("projectRail")), "Home has no rail")
    open_project(ui, pid)
