"""Drag a face, change the parameter behind it (form/dragface.py, FaceDrag.qml): Cmd-drag (Ctrl-drag) on the top of a
storage box raises its height, on its side widens it; the readout names the parameter and the draft's impact; a plain
drag still orbits. Real presses on real pixels: the pixel to press is found by asking the viewport what is under it."""
import json

from _lib import make

DATA = "fresh"
S = {}


def hits(ui, n=34):
    """Viewport pixels on the part with what is under them: [(x, y, hit)]. The grid covers the open room: the part of
    the 3D view no pane covers, where the camera keeps the part."""
    vp = ui.item("viewport")
    l, t = float(vp.property("insetLeft")), float(vp.property("insetTop"))
    w, h = vp.width() - l - float(vp.property("insetRight")), vp.height() - t - float(vp.property("insetBottom"))
    out = []
    for j in range(n):
        for i in range(n):
            x, y = float(int(l + w * (i + 0.5) / n)), float(int(t + h * (j + 0.5) / n))      # whole pixels: a press lands on one
            r = ui.js("JSON.stringify(Store.viewer.hitAt(%f, %f))" % (x, y))
            r = json.loads(r) if r and r != "null" else None
            if r:
                out.append((x, y, r))
    return out


def press_drag(ui, x, y, dx, dy, steps=10, shot=None):
    """Cmd/Ctrl-press at viewport pixel (x, y), move by (dx, dy) in steps, a picture half way, release."""
    from PySide6.QtCore import QPoint, QPointF
    vp = ui.item("viewport")
    a = vp.mapToScene(QPointF(x, y))
    a = QPoint(int(a.x()), int(a.y()))
    mods = ui._mods("ctrl")
    ui.T.mouseMove(ui.win, a)
    ui.T.mousePress(ui.win, ui._btn("left"), mods, a)
    # the engine says which parameter (one rebuild per parameter)
    ui.wait_until(lambda: _info(ui) is not None, 120, "the parameter behind the face")
    for k in range(1, steps + 1):
        ui.T.mouseMove(ui.win, QPoint(a.x() + dx * k // steps, a.y() + dy * k // steps))
        ui._pump(60)
        if shot and k == steps // 2:
            ui.settle(400)
            ui.shot(shot)
    ui.settle(300)
    b = QPoint(a.x() + dx, a.y() + dy)
    return a, b


def _fd(ui):
    return ui.item("faceDrag")


def _info(ui):
    v = _fd(ui).property("info")
    try:
        return v.toVariant() if hasattr(v, "toVariant") else v
    except Exception:
        return v


def release(ui, b):
    ui.T.mouseRelease(ui.win, ui._btn("left"), ui._mods("ctrl"), b)
    ui._pump(30)


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["box"] = make(ui, "storage_box", "Drag box")
    ui.settle(900)
    ui.shot("drag-0-before")


def journey_drag_top_raises_height(ui):
    hs = hits(ui)
    top = [(x, y, h) for x, y, h in hs if h["normal"][2] > 0.95 and h["at"][2] > 39.5 and h["feature"] == "shell"]
    ui.check(top, "a pixel on the box's top rim")
    x, y, h = max(top, key=lambda t: t[2]["at"][0])          # the front rim (the back carries the lid grooves)
    h0 = ui.store.get("head")["values"]["inner_h"]
    a, b = press_drag(ui, x, y, 0, -90, shot="drag-1-pulling-top")
    info = _info(ui)
    ui.eq(info["best"]["key"], "inner_h", "the top of the box is its inner height")
    ui.wait_until(lambda: (ui.store.get("draftValues") or {}).get("inner_h", h0) > h0 + 2, 30, "the height to grow")
    ui.wait_until(lambda: ui.store.get("preview") is not None, 120, "the draft to rebuild")
    label = ui.item("faceDragLabel").property("text")
    ui.check("→" in label and "height" in label.lower(), f"the readout names it: {label}")
    ui.shot("drag-2-top-raised")
    release(ui, b)
    ui.settle(400)
    ui.check(ui.js("Store.hasDraft"), "the change stays as a draft to commit or discard")
    S["inner_h"] = ui.store.get("draftValues")["inner_h"]
    ui.shot("drag-3-released")
    ui.run_js("Store.discard()")
    ui.wait_until(lambda: not ui.js("Store.hasDraft"), 10, "the draft to go")


def journey_drag_side_widens(ui):
    ui.settle(1500)
    hs = hits(ui)
    side = [(x, y, h) for x, y, h in hs if h["normal"][0] < -0.95 and h["at"][0] < -40]
    if not side:
        side = [(x, y, h) for x, y, h in hs if abs(h["normal"][1]) > 0.95 and abs(h["at"][1]) > 31]
    ui.check(side, "a pixel on an outer side wall")
    x, y, h = side[len(side) // 2]
    a, b = press_drag(ui, x, y, -70, 25, shot="drag-4-pulling-side")
    key = _info(ui)["best"]["key"]
    ui.check(key in ("inner_w", "inner_d"), f"the side is a size of the box: {key}")
    ui.wait_until(lambda: key in (ui.store.get("draftValues") or {}), 30, "the size to change")
    release(ui, b)
    ui.wait_until(lambda: ui.store.get("preview") is not None, 120, "the draft to rebuild")
    ui.settle(600)
    ui.shot("drag-5-side-widened")
    ui.run_js("Store.discard()")


def journey_plain_drag_orbits(ui):
    az = ui.js("Store.viewer.az")
    ui.drag("viewport", (80, 0), fx=0.5, fy=0.5)
    ui.settle(300)
    ui.check(abs(ui.js("Store.viewer.az") - az) > 5, "a drag without Cmd still orbits")
    ui.check(not ui.js("Store.hasDraft"), "and changes nothing")
    ui.no_warnings()
