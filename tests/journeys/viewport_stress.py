"""The 3D view under stress: orbit, pan and zoom to their extremes while panels open and close and the window
changes size, and a new revision arrives in the middle of a drag. After each step the window is grabbed and the
middle of the view must show the part or the plate, not a field of the clear colour (the view once went black)."""
import math

from _lib import make, wait_job

DATA = "fresh"
S = {}
CLEAR = (0x0e, 0x11, 0x13)          # Theme.plate: the View3D's clear colour


def vp(ui):
    return ui.item("viewport")


def free_rect(ui):
    """The viewport's free area (what the HUD does not cover), in window pixels: (left, top, right, bottom)."""
    from PySide6.QtCore import QPointF
    v = vp(ui)
    p = v.mapToScene(QPointF(0, 0))
    l = p.x() + float(v.property("insetLeft"))
    t = p.y() + float(v.property("insetTop"))
    r = p.x() + v.width() - float(v.property("insetRight"))
    b = p.y() + v.height() - float(v.property("insetBottom"))
    return l, t, max(l + 40, r), max(t + 40, b)


def not_blank(ui, what, need=6):
    """The middle 40% of the free area holds at least `need` sampled pixels that are not the clear colour."""
    ui.settle(120)
    img = ui.win.grabWindow()
    k = img.width() / max(1, ui.win.width())
    l, t, r, b = free_rect(ui)
    cx, cy, w, h = (l + r) / 2, (t + b) / 2, (r - l) * 0.4, (b - t) * 0.4
    off, n = 0, 0
    for i in range(17):
        for j in range(17):
            x = int((cx - w / 2 + w * i / 16) * k)
            y = int((cy - h / 2 + h * j / 16) * k)
            if not (0 <= x < img.width() and 0 <= y < img.height()):
                continue
            c = img.pixelColor(x, y)
            n += 1
            if max(abs(c.red() - CLEAR[0]), abs(c.green() - CLEAR[1]), abs(c.blue() - CLEAR[2])) > 6:
                off += 1
    if off < need:
        shot = ui.shot("blank-" + what.replace(" ", "-"))
        raise AssertionError(f"the view is blank {what}: {off} of {n} pixels differ from the clear colour ({shot})")
    cam = ui.js("(function () { var v = Store.viewer; return [v.az, v.el, v.dist, v.target.x, v.target.y, v.target.z, v.fitK] })()")
    ui.check(all(math.isfinite(x) for x in cam), f"the camera is finite {what}: {cam}")
    ui.check(cam[6] <= 4.0 + 1e-6, f"the pull-back stays at most 4x {what}: {cam[6]}")
    return off


def held_still_gone(ui):
    """A geometry change is drawn in place: no held frame is ever laid over the view."""
    ui.check(not ui.exists("viewportStill"), "no held frame over the view")


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["pid"] = make(ui, "enclosure", "Stress box")
    ui.settle(600)
    not_blank(ui, "after opening")
    ui.shot("viewport-stress-open")


def journey_orbit_extremes(ui):
    for dx, dy in ((900, 0), (-1800, 0), (0, 900), (0, -1800), (600, 600)):
        ui.drag("viewport", (dx, dy), fx=0.45, fy=0.5, steps=24)
        el = float(vp(ui).property("el"))
        ui.check(-89 <= el <= 89, f"the elevation stays within ±89°: {el}")
        not_blank(ui, f"after orbiting {dx},{dy}", need=3)
    ui.key("1")
    ui.settle(700)
    not_blank(ui, "back at iso")


def journey_zoom_extremes(ui):
    for _ in range(60):
        ui.wheel("viewport", -480)
    ui.settle(300)
    ui.check(float(vp(ui).property("dist")) >= 2999, "zoomed all the way out")
    not_blank(ui, "zoomed all the way out", need=2)
    ui.shot("viewport-stress-far")
    for _ in range(80):
        ui.wheel("viewport", 480)
    ui.settle(300)
    ui.check(float(vp(ui).property("dist")) <= 31, "zoomed all the way in")
    not_blank(ui, "zoomed all the way in")
    ui.key("1")
    ui.settle(700)


def journey_pan_extremes(ui):
    for _ in range(30):                     # far past any sensible pan, in drags that stay inside the window
        ui.drag("viewport", (300, 200), fx=0.3, fy=0.3, steps=6, button="right")
    for _ in range(30):
        ui.drag("viewport", (-300, -200), fx=0.7, fy=0.7, steps=6, button="right")
    t = ui.js("(function () { var v = Store.viewer, c = v.center(v.bounds); return [v.target.x - c.x, v.target.y - c.y, v.target.z - c.z, v.reach + Math.abs(c.z)] })()")
    ui.check(all(abs(x) <= t[3] + 1e-3 for x in t[:3]), f"panning keeps the orbit centre near the part: {t}")
    ui.key("F")
    ui.settle(700)
    not_blank(ui, "after panning far and framing again")


def journey_panels_while_moving(ui):
    # the conversation and the window change the free area while the camera is zoomed out and moving
    for _ in range(40):
        ui.wheel("viewport", -480)
    w0, h0 = ui.win.width(), ui.win.height()
    for i in range(6):
        at = ui.drag("viewport", (120, 40), fx=0.4, fy=0.5, steps=6, hold=True)
        ui.key("Ctrl+J")
        ui.settle(80)
        ui.release((at.x(), at.y()))
        not_blank(ui, f"with the conversation toggled ({i})", need=2)
    ui.resize(900, 560)
    ui.drag("viewport", (-200, 80), fx=0.5, fy=0.5, steps=10)
    not_blank(ui, "in a small window", need=2)
    ui.resize(w0, h0)
    ui.key("1")
    ui.settle(800)
    not_blank(ui, "back at full size")
    if not ui.store.get("talkOpen"):
        ui.key("Ctrl+J")
        ui.settle(300)


def journey_new_revision_mid_drag(ui):
    pid = S["pid"]
    d = ui.api("/projects/" + pid)
    spec = [p for p in d["recipe"]["params"] if p["key"] == "wall"][0]
    at = ui.drag("viewport", (80, 20), fx=0.45, fy=0.5, steps=6, hold=True)
    ui.api("/projects/" + pid + "/commit", {"values": {"wall": spec["default"] + 0.8}, "provenance": {}, "note": "thicker",
                                            "origin": "user", "expect_head": d["project"]["head"]})
    wait_job(ui, pid)
    ui.wait_until(lambda: ui.js("Store.project && Store.project.head") == d["project"]["head"] + 1, 30, "the new revision to load")
    ui.settle(300)
    ui.release((at.x(), at.y()))
    held_still_gone(ui)
    not_blank(ui, "after a revision arrived mid-drag")
    # and once more at rest: the change is drawn in place
    ui.settle(800)
    d = ui.api("/projects/" + pid)
    ui.api("/projects/" + pid + "/commit", {"values": {"wall": spec["default"]}, "provenance": {}, "note": "back",
                                            "origin": "user", "expect_head": d["project"]["head"]})
    wait_job(ui, pid)
    ui.wait_until(lambda: ui.js("Store.project && Store.project.head") == d["project"]["head"] + 1, 30, "the next revision to load")
    held_still_gone(ui)
    not_blank(ui, "after a revision arrived at rest")
    ui.shot("viewport-stress-end")
