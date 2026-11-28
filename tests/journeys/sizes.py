"""A smoke journey at the window size the suite passes (--size): the smallest window FORM allows (1120 × 700) and a
large laptop screen (1728 × 1117). Nothing may overlap or run off its container, and the main controls still work."""
from PySide6.QtCore import QPointF, QRectF

from _lib import goto, has_slicer, open_sheet_wait, close_sheet_esc, phone_dock

DATA = "fresh"


def rect(it):
    p = it.mapToScene(QPointF(0, 0))
    return QRectF(p.x(), p.y(), it.width(), it.height())


def painted(it):
    """Where the item's text is actually drawn: elided text paints inside its width, unelided text can spill."""
    r = rect(it)
    pw = it.property("paintedWidth")
    if pw is not None and not it.property("truncated") and pw > r.width() + 0.5:
        r.setWidth(pw)
    return r


def no_overlaps(ui, name, what):
    """No two texts under the named item cover each other, and none runs outside it."""
    root = ui.item(name)
    box = rect(root)
    texts = [t for t in ui._walk(root) if ui._shown(t) and isinstance(t.property("text"), str) and t.property("text").strip()
             and t.property("paintedWidth") is not None]
    rs = [(t.property("text"), painted(t)) for t in texts]
    for s, r in rs:
        ui.check(r.left() >= box.left() - 1 and r.right() <= box.right() + 1, f"{what}: “{s}” runs outside ({r.left():.0f}–{r.right():.0f} of {box.left():.0f}–{box.right():.0f})")
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            a, b = rs[i][1], rs[j][1]
            inter = a.intersected(b)
            ui.check(inter.width() < 2 or inter.height() < 2, f"{what}: “{rs[i][0]}” and “{rs[j][0]}” overlap by {inter.width():.0f} × {inter.height():.0f} px")
    return len(rs)


def run(ui):
    w, h = ui.win.width(), ui.win.height()
    tag = f"{w}x{h}"
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    ui.settle(500)
    ui.shot(f"size-{tag}-home")
    pid = phone_dock(ui)
    ui.settle(600)
    ui.check(no_overlaps(ui, "pipeline", "the pipeline strip") >= 1, "the pipeline strip says where the design stands")
    no_overlaps(ui, "topBar", "the top bar")
    no_overlaps(ui, "stageTabs", "the stage tabs")
    ui.shot(f"size-{tag}-shape")
    for stage in ("brief", "fit", "prove", "release", "document", "shape"):
        goto(ui, stage)
        ui.settle(450)
        no_overlaps(ui, "pipeline", f"the pipeline strip on {stage}")
        no_overlaps(ui, "stageTabs", f"the stage tabs on {stage}")
        ui.shot(f"size-{tag}-{stage}")
    # tools still reachable
    ui.click_text("Measure")
    ui.wait_until(lambda: ui.store.get("measuring") is True, 3, "Measure")
    no_overlaps(ui, "measureBar", "the measure options")
    ui.key("Escape")
    ui.click_text("Analyze")
    ui.settle(300)
    opts = ui.item("analyzeBar")
    if ui.exists(text="Thickness", within=opts):
        ui.click_text("Thickness", within=opts)
    else:                                              # a narrow viewport folds the maps into a menu
        ui.run_js('Store.setAnalysis("thickness")')
    ui.wait_until(lambda: ui.js("!!Store.analysis && Store.analysis.map === 'thickness' && !Store.analysisBusy"), 120, "the thickness map")
    ui.settle(700)
    no_overlaps(ui, "resultStrip", "the map legend")
    lg, vp = rect(ui.item("resultStrip")), rect(ui.item("viewport"))
    ui.check(lg.height() <= vp.height() * 0.62, f"the legend leaves the part visible: {lg.height():.0f} of {vp.height():.0f} px")
    ui.shot(f"size-{tag}-thickness")
    ui.run_js('Store.setAnalysis("")')
    ui.key("V")
    ui.key("T")
    ui.settle(400)
    no_overlaps(ui, "timeline", "the timeline")
    ui.shot(f"size-{tag}-timeline")
    ui.key("T")
    if has_slicer(ui):
        ui.click_text("Simulate the print")
        ui.wait_until(lambda: ui.store.get("layers") is not None and ui.item("printSim").property("count") > 0, 120, "the print simulation")
        ui.settle(800)
        ui.item("printSim").setProperty("playing", False)
        ui.shot(f"size-{tag}-simulate")
        ui.run_js("Store.showLayers(false)")
        ui.settle(300)
    for opener, kind in (("Ctrl+,", "settings"), ("?", "shortcuts")):
        ui.key(opener)
        open_sheet_wait(ui, kind)
        card = rect(ui.item("sheetCard"))
        ui.check(card.left() >= 0 and card.top() >= 0 and card.right() <= w and card.bottom() <= h, f"the {kind} sheet fits the window")
        ui.shot(f"size-{tag}-sheet-{kind}")
        close_sheet_esc(ui)
    ui.key("Ctrl+K")
    ui.settle(300)
    ui.shot(f"size-{tag}-palette")
    ui.key("Escape")
    ui.key("Ctrl+J")
    ui.settle(500)
    for attempt in range(10):          # the strip glides to its new width; on a machine without a GPU that takes longer
        try:
            no_overlaps(ui, "pipeline", "the pipeline strip with the conversation hidden")
            break
        except Exception:
            if attempt == 9:
                raise
            ui.settle(500)
    ui.shot(f"size-{tag}-no-talk")
    ui.key("Ctrl+J")
    ui.settle(400)
