"""Frames for the README and website animations, captured from the real app window (scripts/make_app_media.py runs it).

Every clip is the real window drawing a real design: the hinged box is built by build123d on OpenCascade, its lid
turns on the joint the recipe declares, and the print is played back from the G-code your slicer wrote. Nothing is
drawn by hand. Each frame sets the app's own state (camera angle, joint angle, exploded spread, print position) and
then grabs the window, so the motion is smooth and eased no matter how long a frame takes to draw.

    python -m form.app --uitest scripts/media/app_clips.py --size 1440x900       # frames into $FORM_UITEST_OUT/<clip>/
"""
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "journeys"))
from _lib import has_slicer, make, open_project, printing_on, wait_job  # noqa: E402

DATA = "fresh"
FPS = 30
WIDTH = int(os.environ.get("FORM_MEDIA_WIDTH", "1920"))     # frames are grabbed at the screen's pixel ratio, then scaled
ONLY = set(filter(None, os.environ.get("FORM_MEDIA_CLIPS", "").split(",")))
S = {}


def ease(t):                       # ease in-out (cubic): starts and ends at rest
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def frames(seconds):
    return max(2, int(round(seconds * FPS)))


class Clip:
    """Writes numbered frames of the window, or of one item of it (crop in logical pixels)."""

    def __init__(self, ui, name, crop=None):
        self.ui, self.n, self.crop = ui, 0, crop
        self.dir = ui.out / name
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.glob("*.png"):
            old.unlink()

    def grab(self, settle=20):
        from PySide6.QtCore import QRect, Qt
        self.ui._pump(settle)
        img = self.ui.win.grabWindow()
        if self.crop:
            r = img.devicePixelRatio()
            x, y, w, h = self.crop
            img = img.copy(QRect(int(x * r), int(y * r), int(w * r), int(h * r)))
        if img.width() > WIDTH:
            img = img.scaledToWidth(WIDTH, Qt.TransformationMode.SmoothTransformation)
        self.n += 1
        img.save(str(self.dir / f"{self.n:04d}.png"))

    def hold(self, seconds):
        for _ in range(frames(seconds)):
            self.grab(5)


def item_rect(ui, name):
    it = ui.item(name)
    p = it.mapToScene(it.boundingRect().topLeft())
    return (p.x(), p.y(), it.width(), it.height())


def want(name):
    return not ONLY or name in ONLY


def cam(ui, az, el=None, dist=None):
    code = "Store.viewer.tween = false; Store.viewer.az = %f" % az
    if el is not None:
        code += "; Store.viewer.el = %f" % el
    if dist is not None:
        code += "; Store.viewer.dist = %f" % dist
    ui.run_js(code)


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 60, "Home")
    printing_on(ui)                             # a design made for printing: the print clip needs its slice
    S["box"] = make(ui, "hinged_box", "Hinged box", open=False, purpose="print")     # built, checked and sliced by the engine
    S["slicer"] = has_slicer(ui)
    open_project(ui, S["box"])
    wait_job(ui, S["box"])
    ui.hover("viewport", 0.97, 0.03)            # the pointer rests in a corner: no hover highlight on the part
    ui.settle(800)


def journey_orbit(ui):
    """The design turning once on its plate, in the full workspace, with a gentle rise and fall of the camera."""
    if not want("orbit"):
        return
    ui.run_js("Store.setAsmMode('assembled'); Store.pose = ({})")
    ui.settle(1400)
    pull_back(ui, 1.7, 4)                      # the open lid stays under the top row, over the bar
    v = ui.js("[Store.viewer.az, Store.viewer.el, Store.viewer.dist]")
    az0, el0, d0 = v
    j = ui.js("Store.assembly.joints[0]")
    jid, hi = j["id"], float(j["range"][1])
    c = Clip(ui, "orbit")
    c.hold(0.4)
    n = frames(7.0)
    for i in range(n + 1):
        t = ease(i / n)
        lid = 0.5 * hi * ease((i / n - 0.6) / 0.4)          # the lid opens as the front comes round again
        ui.run_js("Store.pose = ({%r: %f})" % (jid, lid))
        cam(ui, az0 + 360 * t, el0 - 6 * math.sin(math.pi * t), d0 * (1 - 0.05 * math.sin(math.pi * t)))
        c.grab()
    c.hold(0.5)
    n = frames(1.1)
    for i in range(n + 1):                                    # and closes, so the loop starts where it ends
        ui.run_js("Store.pose = ({%r: %f})" % (jid, 0.5 * hi * (1 - ease(i / n))))
        c.grab()
    c.hold(0.3)
    ui.run_js("Store.pose = ({})")
    cam(ui, az0, el0, d0)


def journey_hinge(ui):
    """The lid swung on its hinge through the range the recipe declares, then the parts pulled apart and put back."""
    if not want("hinge"):
        return
    ui.run_js("Store.talkOpen = false; Store.setAsmMode('assembled'); Store.pose = ({})")
    ui.settle(1600)
    pull_back(ui, 1.65, 6)
    j = ui.js("Store.assembly.joints[0]")
    jid, lo, hi = j["id"], float(j["range"][0]), float(j["range"][1])
    x, y, w, h = item_rect(ui, "viewport")
    crop = (x, y, w, h)                            # the whole stage: the 3D view fills the window
    for name, box in (("hinge", crop),):
        c = Clip(ui, name, box)
        c.hold(0.5)
        n = frames(2.2)
        for i in range(n + 1):
            ui.run_js("Store.pose = ({%r: %f})" % (jid, lo + (hi - lo) * ease(i / n)))
            c.grab()
        c.hold(0.7)
        for i in range(n + 1):
            ui.run_js("Store.pose = ({%r: %f})" % (jid, hi - (hi - lo) * ease(i / n)))
            c.grab()
        c.hold(0.4)
        # pulled apart: the exploded view's spread from together to the design's offsets and back
        ui.run_js("Store.explode = 0; Store.setAsmMode('exploded')")
        ui.settle(1400)
        pull_back(ui, 1.9, 0)
        n = frames(1.6)
        for i in range(n + 1):
            ui.run_js("Store.explode = %f" % (1.15 * ease(i / n)))
            c.grab()
        c.hold(0.8)
        for i in range(n + 1):
            ui.run_js("Store.explode = %f" % (1.15 * (1 - ease(i / n))))
            c.grab()
        c.hold(0.3)
    ui.run_js("Store.explode = 1; Store.setAsmMode('assembled'); Store.pose = ({}); Store.talkOpen = true")
    ui.settle(1600)


def pull_back(ui, k=1.32, up=11):
    """Room above the box for the open lid and the lifted parts: the camera steps back and looks a little higher."""
    ui.run_js("(function(){ var v = Store.viewer; v.tween = false; v.dist = v.dist * %f;"
              " v.target = Qt.vector3d(v.target.x, v.target.y + %f, v.target.z) })()" % (k, up))
    ui.settle(120)


def journey_print(ui):
    """The print played back from the slicer's G-code: every layer and line type, the nozzle where it is."""
    if not want("print") or not S.get("slicer"):
        if want("print"):
            print("  (no slicer here: no print clip)")
        return
    ui.run_js("Store.setAsmMode('print')")
    ui.settle(800)
    ui.wait_until(lambda: ui.js("!!Store.data.slice"), 600, "a current slice")
    ui.click_text("Simulate the print")
    ui.wait_until(lambda: ui.store.get("layers") is not None, 60, "the simulation to open")
    sim = ui.item("printSim")
    ui.wait_until(lambda: sim.property("count") > 0, 180, "the toolpaths to load")
    sim.setProperty("playing", False)
    ui.run_js("Store.talkOpen = false")
    sim.setProperty("typesFold", True)                      # the line-type list folded: the print in full view
    ui.hover("printSim", 0.97, 0.03)
    ui.settle(1500)
    view = next(k for k in sim.childItems() if k.property("framed") is not None and k.property("az") is not None)
    view.setProperty("tween", False)
    _frame_view(view)
    ui.settle(300)
    az0, d0 = view.property("az"), view.property("dist")
    count = sim.property("count")
    c = Clip(ui, "print")
    n = frames(8.0)
    for i in range(n + 1):
        p = count * (i / n * 0.8 + 0.2 * ease(i / n))          # nearly constant speed, soft start and finish
        _set_now(sim, p)
        view.setProperty("az", az0 + 50 * ease(i / n))       # and the camera drifts round a little while it prints
        view.setProperty("dist", d0 * (0.86 - 0.06 * ease(i / n)))
        c.grab(30)
    c.hold(1.0)
    ui.run_js("Store.talkOpen = true")


def _frame_view(view):
    from PySide6.QtCore import Q_ARG, QMetaObject
    QMetaObject.invokeMethod(view, "frame", Q_ARG("QVariant", False))


def _set_now(sim, p):
    from PySide6.QtCore import Q_ARG, QMetaObject
    QMetaObject.invokeMethod(sim, "setNow", Q_ARG("QVariant", float(p)))
