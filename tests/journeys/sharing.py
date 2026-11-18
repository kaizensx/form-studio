"""Feedback while the engine works: a button's busy state and the activity bar during a slow action. (Recipe sharing
left the interface; it stays in the engine and the CLI: tests/test_recipe_share.py.)"""
import time

DATA = "fresh"
SLOW, QUICK = "fakeSlow", "fakeQuick"         # buttons the first journey makes at run time (not in the QML files)


def home(ui):
    ui.wait_until(lambda: ui.store.get("screen") in ("home", "work"), 30, "the window")
    if ui.store.get("screen") == "work":
        ui.run_js("Store.home()")
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")


def journey_busy_feedback(ui):
    """A slow action: the button shows a spinner and its busy label, ignores more clicks, and the bar names the work."""
    home(ui)
    ui.settle(300)
    ui.run_js("""
        var b = Qt.createQmlObject('import QtQuick; import Form; Btn { objectName: "fakeSlow"; x: 520; y: 240; kind: "primary"; icon: "play"; text: "Run it"; busyText: "Running…"; property int clicks: 0 }', win.contentItem)
        b.z = 999
        b.clicked.connect(function () {
            b.clicks++
            b.run(function () { return Store.act("Running a slow test action", new Promise(function (res) {
                var t = Qt.createQmlObject('import QtQuick; Timer { interval: 1600; running: true }', b)
                t.triggered.connect(function () { res(true); t.destroy() }) })) })
        })""")
    btn = ui.item(SLOW)
    t0 = time.time()
    ui.click(btn)
    ui.wait_until(lambda: btn.property("showsBusy"), 1.0, "the spinner on the button")
    shown_after = time.time() - t0
    ui.check(shown_after < 0.6, f"busy within {shown_after:.2f} s of the click")
    ui.eq(btn.property("shownText"), "Running…")
    ui.check(ui.find(name="btnSpinner", within=btn) is not None, "a spinner replaces the icon")
    ui.click(btn)                                       # a second click while busy does nothing
    ui.eq(btn.property("clicks"), 1, "presses ignored while busy")
    ui.wait_until(lambda: ui.js("Store.activity.length") > 0, 2, "the activity bar")
    ui.wait_until(lambda: ui.item("activityLabel").property("text") == "Running a slow test action…", 2, "the work named in the bar")
    ui.shot("busy-button-and-activity-bar")
    ui.wait_until(lambda: not btn.property("showsBusy"), 4, "the button to come back")
    ui.check(time.time() - t0 >= 1.5, "busy for as long as the work ran")
    ui.wait_until(lambda: ui.js("Store.activity.length") == 0, 3, "the bar to clear")
    ui.settle(600)                                       # work under 3 s says nothing when it ends: the button already did
    ui.check(not any("Running a slow test action" in t["msg"] for t in ui.store.get("toasts")), "no toast for short work")
    # a quick answer never flashes: the spinner waits a moment before it shows
    ui.run_js("""var q = Qt.createQmlObject('import QtQuick; import Form; Btn { objectName: "fakeQuick"; x: 520; y: 300; text: "Quick" }', win.contentItem); q.z = 999
        q.clicked.connect(function () { q.run(function () { return Promise.resolve(1) }) })""")
    quick = ui.item(QUICK)
    ui.click(quick)
    ui.settle(250)
    ui.check(not quick.property("showsBusy"), "an instant answer shows no spinner")
    for b in (btn, quick):
        b.setVisible(False)
        b.deleteLater()
    ui.settle(200)
