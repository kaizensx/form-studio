"""The tool dock by mode (docs/design/directions/i/IA.md, decision 8) and the tool capsule (decision 9).

Four tools are always there and never move: Select, Measure, Section, Annotate. Under a thin rule stand the tools of
the mode you are in. Changing mode cross-fades that group in 180 ms: the four stay where they are, and nothing else
on the stage moves. The options of the active tool are one capsule at the head of the stage, in the same place for
every tool. Each mode's tools answer to their keys in that mode only. Idle, the dock and the capsule redraw nothing."""
import os
import time

from _lib import goto, phone_dock, toasts_gone

DATA = "fresh"
FOUR = ("railSelect", "railMeasure", "railSection", "railAnnotate")
GROUPS = {"shape": ["railSketch", "railExtrude", "railCut", "railRevolve", "railRound", "railChamfer", "railHole", "railPattern", "railShell", "railPart"],
          "prove": ["railAnalyze", "railMass", "railHistory"],
          "release": ["railSimulate"],
          "document": ["railViews", "railDims"]}


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
    rs = [rect(ui, i) for i in items]
    x0, y0 = min(r[0] for r in rs) - pad, min(r[1] for r in rs) - pad
    x1, y1 = max(r[0] + r[2] for r in rs) + pad, max(r[1] + r[3] for r in rs) + pad
    r = QRect(int(x0 * dpr), int(y0 * dpr), int((x1 - x0) * dpr), int((y1 - y0) * dpr))
    c = img.copy(r).scaled(int(r.width() * 2 / dpr), int(r.height() * 2 / dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    Path(out).mkdir(parents=True, exist_ok=True)
    col = "col" if ui.js("Store.talkCol > 0") else "folded"
    c.save(str(Path(out) / f"{name}-{ui.win.width()}-{col}-{os.environ.get('FORM_APPEARANCE', 'dark')}.png"))


def frames(ui, ms):
    """How many frames the window draws in ms while nothing is touched (the journeys' own perf method)."""
    n = [0]

    def tick():
        n[0] += 1
    ui.win.frameSwapped.connect(tick)
    ui._pump(ms)
    ui.win.frameSwapped.disconnect(tick)
    return n[0]


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    phone_dock(ui)
    ui.wait_until(lambda: ui.js("!!Store.viewer && !Store.viewer.revealing && Store.buildOf === 0") is True, 60, "the build-up to end")
    toasts_gone(ui)
    goto(ui, "shape")
    ui.settle(500)
    # ── with the ribbon (the default) the dock keeps the four; the mode's tools are labelled in the ribbon ──
    ui.check(ui._shown(ui.item("toolRibbon")), "the ribbon shows by default")
    ui.check(not ui.exists("railSep") and not ui.exists("railSketch"), "the dock keeps the four alone")
    for mode, first in (("prove", "analyze"), ("release", "render"), ("document", "views"), ("shape", "sketch")):
        ui.click("stage-" + mode)
        ui.wait_until(lambda: ui.exists("ribbon-" + first), 3, f"{mode}: {first} in the ribbon")
        ui.settle(250)
        d = rect(ui, "toolDock")
        ui.check(d[1] >= rect(ui, "toolRibbon")[1] + 38, f"{mode}: the dock stands under the ribbon")
    # the rest of this journey is the dock as it is with the ribbon folded away (its Hide, remembered)
    ui.hover("ribbonHide")                           # the pointer arrives first: a mode's tooltip just above is gone
    ui.settle(200)
    ui.click("ribbonHide")
    ui.wait_until(lambda: ui._shown(ui.item("railSep")), 3, "the dock with its mode's tools again")
    ui.settle(900)
    stage = (rect(ui, "viewCube"), rect(ui, "programPane")[0], ui.js("Store.viewer.insetLeft"))
    four = [rect(ui, n) for n in FOUR]
    ui.check(rect(ui, "railSep")[1] > four[-1][1] + four[-1][3], "a thin rule under the four")

    # ── each mode: its own tools under the four, which have not moved; the group glides in, nothing jumps ──
    for mode in ("prove", "release", "document", "shape"):
        ui.click("stage-" + mode)
        t0 = time.perf_counter()
        seen = []
        while time.perf_counter() - t0 < 0.4:
            ui._pump(16)
            seen.append((time.perf_counter() - t0, ui.item("railGroup-" + mode, timeout=2).opacity() if ui.exists("railGroup-" + mode) else 0, ui.item("toolDock").height()))
        full = next((t for t, o, _h in seen if o > 0.99), None)
        ui.check(full is not None and full <= 0.26, f"{mode}: its tools are in within the glide (≤ 200 ms and a frame): {full}")
        ui.check(any(0.02 < o < 0.98 for _t, o, _h in seen), f"{mode}: the group cross-fades, it does not cut")
        ui.settle(300)
        ui.eq([rect(ui, n) for n in FOUR], four, f"{mode}: the four universal tools have not moved")
        ui.eq((rect(ui, "viewCube"), rect(ui, "programPane")[0], ui.js("Store.viewer.insetLeft")), stage, f"{mode}: nothing on the stage moved with the dock")
        for n in GROUPS[mode]:
            ui.check(ui.exists(n) and ui._shown(ui.item(n)), f"{mode}: {n} is in the dock")
        for other, names in GROUPS.items():
            if other != mode:
                ui.check(not ui.exists(names[0]), f"{mode}: the tools of {other} are not shown")
        d = rect(ui, "toolDock")
        ui.check(d[1] + d[3] <= ui.win.height() - 20, f"{mode}: the dock ends above the window's foot: {d}")
        crop(ui, ["toolDock"], "dock-" + mode)
    ui.shot("dock-design")

    # ── the capsule: one place for every tool's options ──
    at = None
    for name, bar, title in (("railMeasure", "measureBar", "Measure"), ("railSection", "sectionBar", "Section"), ("railAnnotate", "annotateBar", "Annotate")):
        ui.click(name)
        ui.wait_until(lambda: ui.exists(bar) and ui._shown(ui.item(bar)), 3, f"the options of {title}")
        ui.settle(120)
        c = rect(ui, "toolCapsule")
        ui.eq(ui.texts(ui.item("toolCapsule"))[0], title, "the capsule names the tool")
        ui.check(at is None or (c[0], c[1]) == at, f"{title}: the capsule stands where the last one stood: {c} / {at}")
        at = (c[0], c[1])
        ui.check(c[1] + c[3] / 2 > rect(ui, "toolDock")[1] and c[0] >= rect(ui, "toolDock")[0] + 48 + 8, "at the head of the stage, right of the dock")
        ui.check(c[0] + c[2] <= rect(ui, "viewCube")[0] - 4, f"{title}: clear of the view cube: {c}")
        crop(ui, ["toolCapsule"], "capsule-" + title.lower())
    ui.click("railSelect")
    ui.wait_until(lambda: not ui.exists("toolCapsule"), 3, "no capsule with Select")

    # ── keys: the mode's tools answer in their mode only ──
    ui.click("railSelect")
    ui.key("Shift+F")
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate" and ui.js("Ws.want") == "fillet" and ui.store.get("selMode") == "edge", 3, "Shift+F: Fillet picks edges")
    ui.eq(ui.texts(ui.item("toolCapsule"))[0], "Fillet", "the capsule names it")
    crop(ui, ["toolDock", "toolCapsule"], "dock-fillet")
    ui.key("Shift+H")
    ui.wait_until(lambda: ui.js("Ws.want") == "hole" and ui.store.get("selMode") == "face", 3, "Shift+H: Hole picks a face")
    ui.check(ui.item("railHole").property("active") is True, "the dock lights Hole")
    ui.key("Escape")
    ui.wait_until(lambda: ui.js("Ws.tool") == "select" and ui.js("Ws.want") == "", 3, "Esc hands back to Select")
    ui.key("S")
    ui.wait_until(lambda: ui.js("Store.sketchHost.picking") is True, 3, "S: Sketch waits for a face or a plane")
    ui.eq(rect(ui, "sketchCapsule")[:2], at, "the sketch's capsule stands in the same place")
    crop(ui, ["toolDock", "sketchCapsule"], "dock-sketch-pick")
    ui.key("Escape")
    ui.wait_until(lambda: ui.js("Store.sketchHost.picking") is False, 3, "Esc leaves it")
    # A, E and T are Check's tools: from Design their key goes to Check and the dock shows the tool lit
    ui.key("A")
    ui.wait_until(lambda: ui.store.get("mode") == "prove" and ui.js("Ws.tool") == "analyze", 3, "A from Design: Analyze, in Check")
    ui.wait_until(lambda: ui.item("railAnalyze") is not None and ui.item("railAnalyze").property("active") is True, 3, "the dock lights Analyze")
    ui.key("V")
    goto(ui, "shape")
    ui.key("T")
    ui.wait_until(lambda: ui.store.get("mode") == "prove" and ui.js("Ws.tool") == "history", 3, "T from Design: History, in Check")
    ui.check(ui.item("railHistory").property("active") is True, "the dock lights History")
    ui.key("V")
    goto(ui, "prove")
    ui.settle(300)
    ui.key("S")
    ui.key("Shift+F")
    ui.settle(200)
    ui.check(ui.js("Store.sketchHost.picking") is False and ui.js("Ws.want") == "", "Design's keys do nothing in Check")
    ui.key("A")
    ui.wait_until(lambda: ui.js("Ws.tool") == "analyze", 3, "A: Analyze in Check")
    ui.eq(ui.texts(ui.item("toolCapsule"))[0], "Analyze", "the capsule names it")
    crop(ui, ["toolDock", "toolCapsule"], "dock-analyze")
    ui.key("V")
    goto(ui, "document")
    ui.settle(300)
    ui.key("W")
    ui.wait_until(lambda: ui.js("Ws.tool") == "views", 3, "W: Views in Document")
    ui.click_text("Front", within=ui.item("viewsBar"))
    ui.wait_until(lambda: ui.store.get("viewName") == "front", 3, "the front view")
    ui.key("V")
    goto(ui, "shape")
    ui.wait_until(lambda: ui.js("Ws.tool") == "select", 3, "Select again")
    ui.js("Store.setView('iso')")

    # ── idle: with a tool's capsule open and nothing touched, the window draws nothing ──
    ui.click("railMeasure")
    ui.hover("viewport", 0.5, 0.2)
    ui.settle(1500)
    n = frames(ui, 2000)
    print(f"DOCK IDLE: {n} frames in 2 s with the Measure capsule open", flush=True)
    ui.check(n <= 2, f"idle redraws with the capsule open: {n} frames in 2 s")
    ui.click("railSelect")
    ui.click("railRibbon")
    ui.wait_until(lambda: ui.exists("toolRibbon") and ui._shown(ui.item("toolRibbon")), 3, "the ribbon back")

