"""The 3D view stays calm: orbiting, zooming and rebuilding never blink, a slider drag rebuilds the part in place with
no preview step in between, and a new build grows in feature by feature, in build order.

While each gesture runs, a sampler grabs the window over and over (between the events, as the app processes them)
and counts, inside the viewport's free area, the pixels that are the clear colour and the pixels of the clay part. A
blink is a sample where the part (nearly) disappears between two samples that show it, or where the middle of the
view is the clear colour."""
import os
import time

from _lib import make, wait_job

DATA = "fresh"
S = {}
CLEAR = (0x0e, 0x11, 0x13)          # Theme.plate: the View3D's clear colour


def vp(ui):
    return ui.item("viewport")


def free_rect(ui):
    from PySide6.QtCore import QPointF
    v = vp(ui)
    p = v.mapToScene(QPointF(0, 0))
    l = p.x() + float(v.property("insetLeft"))
    t = p.y() + float(v.property("insetTop"))
    r = p.x() + v.width() - float(v.property("insetRight"))
    b = p.y() + v.height() - float(v.property("insetBottom"))
    return l, t, max(l + 40, r), max(t + 40, b)


def measure(ui, img=None):
    """(clay pixels on a 48x32 grid over the free area, clear-colour pixels in its middle 40% on a 17x17 grid)"""
    img = img or ui.win.grabWindow()
    k = img.width() / max(1, ui.win.width())
    l, t, r, b = free_rect(ui)
    clay = 0
    for i in range(48):
        for j in range(32):
            c = img.pixelColor(int((l + (r - l) * (i + 0.5) / 48) * k), int((t + (b - t) * (j + 0.5) / 32) * k))
            rr, gg, bb = c.red(), c.green(), c.blue()
            if min(rr, gg, bb) > 110 and abs(rr - bb) < 60:
                clay += 1
    cx, cy, w, h = (l + r) / 2, (t + b) / 2, (r - l) * 0.4, (b - t) * 0.4
    clear = 0
    for i in range(17):
        for j in range(17):
            c = img.pixelColor(int((cx - w / 2 + w * i / 16) * k), int((cy - h / 2 + h * j / 16) * k))
            if max(abs(c.red() - CLEAR[0]), abs(c.green() - CLEAR[1]), abs(c.blue() - CLEAR[2])) <= 6:
                clear += 1
    return clay, clear


class Sampler:
    """Grabs the window on every turn of the event loop while a gesture runs; each sample also records `extra()`."""

    def __init__(self, ui, extra=None):
        from PySide6.QtCore import QTimer
        self.ui, self.extra, self.samples = ui, extra, []
        self.timer = QTimer()
        self.timer.setInterval(0)
        self.timer.timeout.connect(self.tick)

    def tick(self):
        self.timer.stop()                 # grabbing renders a frame: never re-entered
        try:
            clay, clear = measure(self.ui)
            self.samples.append({"t": time.time(), "clay": clay, "clear": clear, "x": self.extra() if self.extra else None})
        finally:
            self.timer.start()

    def __enter__(self):
        self.timer.start()
        return self

    def __exit__(self, *a):
        self.timer.stop()


def no_blink(ui, sm, what, min_samples=6):
    s = sm.samples
    print(f"  {what}: {len(s)} frames, clay pixels {min(x['clay'] for x in s) if s else '-'}..{max(x['clay'] for x in s) if s else '-'}", flush=True)
    ui.check(len(s) >= min_samples, f"enough frames sampled {what}: {len(s)}")
    for i, x in enumerate(s):
        if x["clear"] > 17 * 17 * 0.6:
            raise AssertionError(f"the middle of the view is the clear colour {what} (sample {i}: {x}) ({ui.shot('blink-' + what.replace(' ', '-'))})")
    for i in range(1, len(s) - 1):
        a, x, b = s[i - 1]["clay"], s[i]["clay"], s[i + 1]["clay"]
        if min(a, b) >= 20 and x < 0.4 * min(a, b):
            raise AssertionError(f"the part blinked {what}: clay pixels {a} → {x} → {b} (sample {i} of {len(s)})")
    ui.check(not ui.exists("viewportStill"), "no held frame is laid over the view")


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["pid"] = make(ui, "enclosure", "Calm box")
    ui.settle(800)
    clay, clear = measure(ui)
    ui.check(clay > 40, f"the part is on screen: {clay} clay pixels")
    ui.shot("viewport-calm-open")


def journey_orbit_and_zoom(ui):
    with Sampler(ui) as sm:
        for dx, dy in ((420, 0), (-300, 120), (0, -160)):
            ui.drag("viewport", (dx, dy), fx=0.45, fy=0.5, steps=30)
        ui.settle(300)                    # the moment after letting go (the old snapshot was taken here)
        ui.drag("viewport", (160, 40), fx=0.45, fy=0.5, steps=20)
    no_blink(ui, sm, "while orbiting")
    ui.key("1")
    ui.settle(700)
    with Sampler(ui) as sm:
        for i in range(24):
            ui.wheel("viewport", -120 if i < 12 else 120)
            if i % 4 == 3:
                ui.settle(220)           # pauses between bursts, like a trackpad
    no_blink(ui, sm, "while zooming")
    ui.key("1")
    ui.settle(700)


def journey_rebuild_at_rest_and_moving(ui):
    """New revisions arrive at rest and in the middle of an orbit: the part is replaced in place."""
    from PySide6.QtCore import QPoint
    pid = S["pid"]
    for moving in (False, True):
        d = ui.api("/projects/" + pid)
        spec = [p for p in d["recipe"]["params"] if p["key"] == "wall"][0]
        wall = [r for r in d["project"]["revisions"] if r["n"] == d["project"]["head"]][0]["values"]["wall"]
        ui.api("/projects/" + pid + "/commit", {"values": {"wall": spec["default"] + (0.6 if abs(wall - spec["default"]) < 0.3 else 0)},
                                                "provenance": {}, "note": "wall", "origin": "user", "expect_head": d["project"]["head"]})
        wait_job(ui, pid)
        with Sampler(ui) as sm:
            at = ui.drag("viewport", (60, 10), fx=0.45, fy=0.5, steps=6, hold=True) if moving else None
            ui.run_js("Store.refresh(true)")
            ui.wait_until(lambda: ui.js("Store.view && Store.project && Store.view.rev === Store.project.head") is True, 30, "the revision to load")
            for i in range(8):
                if moving:
                    ui.T.mouseMove(ui.win, QPoint(at.x() + 10 * (i + 1), at.y()))
                ui.wait(40)
            if moving:
                ui.release((at.x() + 80, at.y()))
            ui.settle(300)
        no_blink(ui, sm, "when a revision arrives " + ("mid-orbit" if moving else "at rest"))


def journey_slider_drag_is_live(ui):
    """Dragging a parameter's slider rebuilds the part while the pointer moves, with no "Previewing" step."""
    pid = S["pid"]
    ui.run_js("Store.setStage('shape')")
    fid = ui.js("(Store.recipe.params.filter(function (p) { return p.key === 'wall' })[0] || {}).feature || "
                "Store.recipe.features.filter(function (f) { return Store.recipe.params.some(function (p) { return p.feature === f.id && p.group !== 'brief' }) })[0].id")
    ui.click("feature-" + fid)
    ui.wait_until(lambda: ui.store.get("feature") == fid, 3, "the feature picked from the list")
    ui.settle(500)
    rows = ui.wait_until(lambda: [r for r in ui.find_all() if r.objectName() == "param-wall" and ui._on_screen(r)]
                         or [r for r in ui.find_all() if r.objectName().startswith("param-") and ui._on_screen(r)], 5, "a parameter row")
    row = rows[0]
    key = row.objectName()[6:]
    spec = ui.js("Store.spec(%r)" % key)
    v0 = ui.js("Store.values[%r]" % key)
    beam = ui.find(name="paramBeam", within=row)
    frac = (v0 - spec["min"]) / (spec["max"] - spec["min"])
    to = 0.2 if frac > 0.5 else 0.8
    labels = set()

    def extra():
        for a in ui.js("Store.activity.map(function (a) { return a.label })") or []:
            labels.add(a)
        return ui.js("Store.preview ? Store.preview.impact.params.map(function (p) { return p.to }).join(',') : ''")

    from PySide6.QtCore import QPoint
    a = ui._pt(beam, frac * (beam.width() - 10) / beam.width() + 5 / beam.width(), 0.5)
    b = QPoint(a.x() + int((to - frac) * beam.width()), a.y())
    with Sampler(ui, extra) as sm:
        ui.T.mouseMove(ui.win, a)
        ui.T.mousePress(ui.win, ui._btn("left"), ui._mods(), a)
        steps = 40
        for i in range(1, steps + 1):
            ui.T.mouseMove(ui.win, QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y()))
            ui.wait(70)
        t_last = time.time()
        held = [x["x"] for x in sm.samples if x["x"]]
        ui.wait_until(lambda: ui.js("!!Store.preview && Math.abs(Store.preview.impact.params.filter(function (p) { return p.key === %r })[0].to - Store.values[%r]) < 1e-9" % (key, key)),
                      30, "the preview of where the slider stopped")
        lag = time.time() - t_last
        ui.T.mouseRelease(ui.win, ui._btn("left"), ui._mods(), b)
        ui.settle(300)
    shown = []
    for x in held:
        if not shown or shown[-1] != x:
            shown.append(x)
    ui.check(len(shown) >= 2, f"the part rebuilt while the slider was still moving ({len(shown)} different drafts drawn: {shown})")
    ui.check(not any("Preview" in a for a in labels), f"no preview step is announced while dragging: {sorted(labels)}")
    limit = 6.0 if os.environ.get("CI") else 3.0     # shared CI runners build the draft about twice as slowly
    ui.check(lag < limit, f"the last position is drawn soon after the pointer stops: {lag:.2f} s")
    ui.log.append(f"slider: {len(sm.samples)} frames sampled")
    ui.check(ui.js("Store.viewer.model.mesh[0].positions === Store.preview.mesh[0].positions") is True,
             f"the viewport draws the draft itself: {ui.js('[!!Store.viewer.model, !!Store.preview, Store.viewer.model === Store.preview, Store.viewer.model && Store.viewer.model.rev, Store.hasDraft]')}")
    no_blink(ui, sm, "while dragging a slider")
    ui.log.append(f"slider: {len(shown)} drafts drawn during the drag, last one {lag * 1000:.0f} ms after the pointer stopped")
    ui.shot("viewport-calm-slider")
    ui.run_js("Store.discard()")
    ui.settle(300)


def _reveal(ui, start, what):
    """Run `start` (JS that makes a build grow in), sampling which features are still held; returns the reveal order."""
    def extra():
        return ui.js("Store.viewer ? [Store.viewer._hold.slice(), Store.viewer.revealing] : [[], false]")
    if isinstance(start, str) and "open(" in start:     # a new design arrives on an empty plate, as from the Designing screen
        ui.run_js("Store.viewer.setModel(null)")
        ui.settle(300)
    with Sampler(ui, extra) as sm:
        if isinstance(start, str):
            ui.run_js(start)
        else:
            start()
        if isinstance(start, str) and "open(" in start:
            # the build-up that counts is the opened design's: a late refresh of the design in front before it (an
            # agent's revision the app noticed a moment ago) may still be drawn first, with its own steps
            ui.wait_until(lambda: ui.js("!!Store.viewer.model && Store.viewer.model.pid === Store.pid") is True, 30,
                          "the opened design on the plate " + what)
        ui.wait_until(lambda: any(x["x"] and x["x"][1] for x in sm.samples), 30, "the build-up to start " + what)
        n = ui.js("Store.viewer._steps.length")
        if n >= 3:                        # a picture halfway: some features in place, one arriving, the rest still to come
            ui.wait_until(lambda: ui.js("Store.viewer._stepAt") >= n // 2, 10, "the build-up to be halfway " + what)
            ui.wait(120)
            ui.shot("viewport-calm-growing-" + "-".join(what.split()[2:]))
        ui.wait_until(lambda: ui.js("Store.viewer && !Store.viewer.revealing") is True, 30, "the build-up to finish " + what)
        ui.settle(500)
    gone, prev = [], None
    for x in sm.samples:
        h = x["x"][0] if x["x"] else []
        if prev is not None:
            gone += [f for f in prev if f not in h and f not in gone]
        prev = h
    first = next(i for i, x in enumerate(sm.samples) if x["x"] and x["x"][1])
    clay = [x["clay"] for x in sm.samples[first:]]
    peak = 0
    for i, c in enumerate(clay):
        ui.check(c >= 0.7 * peak - 6, f"the part only grows {what}: clay pixels {peak} → {c} at sample {i}")
        peak = max(peak, c)
    ui.check(ui.js("(function () { var a = Store.viewer._mesh, b = Store.view.mesh; return Store.viewer.model.rev === Store.view.rev && a.length === b.length"
                   " && a.every(function (m, i) { return m.positions === b[i].positions && m.indices === b[i].indices }) })()") is True,
             f"the build-up ends on exactly the head model {what}")
    ui.check(ui.js("Store.viewer._hold.length === 0") is True, f"nothing is held after the build-up {what}")
    ui.check(ui.js("Store.viewer._mesh.length") > 0, f"meshes are drawn {what}")
    return gone, clay


def journey_build_grows_in_order(ui):
    """A design opened as a new build (the agent made it) grows in feature by feature, in the recipe's order."""
    pid = make(ui, "enclosure", "Built box", open=False)
    S["pid2"] = pid
    order, clay = _reveal(ui, "Store._buildNext = Date.now(); Store.view = null; Store.open(%r)" % pid, "on a new design")
    feats = [f["id"] for f in ui.js("Store.recipe.features")]
    drawn = ui.js("(function () { var s = {}, o = []; Store.view.mesh.forEach(function (m) { if (!s[m.feature]) { s[m.feature] = 1; o.push(m.feature) } }); return o })()")
    want = [f for f in feats if f in drawn] + [f for f in drawn if f not in feats]
    ui.check(len(want) >= 2, f"the design has several features: {want}")
    ui.eq(order, want, "features are revealed in build order")
    ui.check(clay[-1] > 40 and clay[-1] >= 1.5 * max(1, clay[0]), f"the part grew from little to whole: {clay[0]} → {clay[-1]}")
    ui.shot("viewport-calm-built")


GEO = """(function () {               // feature id -> a short fingerprint of its geometry (the strings are megabytes)
    var g = Store.viewer._featureGeo(Store.viewer.model), out = {}
    for (var f in g) { var s = g[f], h = 5381; for (var i = 0; i < s.length; i += 3) h = ((h * 33) ^ s.charCodeAt(i)) | 0; out[f] = s.length + ":" + h }
    return out })()"""


def journey_new_revision_reveals_only_what_changed(ui):
    pid = S["pid2"]
    d = ui.api("/projects/" + pid)
    spec = [p for p in d["recipe"]["params"] if p["key"] == "wall"][0]
    before = ui.js(GEO)

    def commit():                         # the agent commits; the app notices it by itself and grows the change in
        ui.api("/projects/" + pid + "/commit", {"values": {"wall": spec["default"] + 0.8}, "provenance": {}, "note": "thicker",
                                                "origin": "agent:Test", "expect_head": d["project"]["head"]})
    order, clay = _reveal(ui, commit, "on a new revision")
    after = ui.js(GEO)
    changed = [f for f in after if before.get(f) != after[f]]
    ui.eq(sorted(order), sorted(changed), "only the features whose geometry changed grow in again")


def journey_one_feature_build(ui):
    """A design with one feature (or a single mesh) fades and rises in as one step."""
    pid = make(ui, "coupon", "One piece", open=False)
    order, clay = _reveal(ui, "Store._buildNext = Date.now(); Store.view = null; Store.open(%r)" % pid, "on a one-piece design")
    ui.check(len(order) >= 1, f"something grew in: {order}")
    ui.check(clay[-1] > 10, f"the piece is on screen at the end: {clay[-1]}")
    ui.shot("viewport-calm-one-piece")
