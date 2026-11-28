"""The pro-density surfaces: the version compare sheet, the feature property card, the Bench's tiles, the tree's
extra rows and the study card's verdict.

Compare: a revision card's "What changed" opens the sheet; one model lights what changed, side by side keeps one
camera for both views, the script is a coloured line diff, and the dimensions and the solid's deltas are the
engine's (GET /compare, /geomdiff). The property card writes a feature's parameters as a draft with a live kernel
preview and its volume change, then OK commits one revision and Cancel leaves the head. The Bench sheet switches to
tiles grouped Analysis / Manufacturing / Documents, each with its sentence and Run. The tree shows the origin planes,
Equations, Material, Purchased parts, an eye per feature (display only), the sketch under its feature and the PMI
the drawing declares. With FORM_CRAFT_OUT set, 200 % crops are written there."""
import os
from pathlib import Path

from _lib import open_project, toasts_gone, wait_job

DATA = "fresh"
S = {}

PLATE = '''
from build123d import Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Plate"
    params = [Param("w", "Width", 60, 30, 110, 1, "mm", "form", "body"),
              Param("hole_d", "Hole", 5, 2, 10, 0.1, "mm", "form", "holes")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], 40, 10)

    @feature("Holes", role="interface")
    def holes(self, v, body):
        return body - Pos(v["w"] / 4, 0, 0) * Cylinder(v["hole_d"] / 2, 20)

    @feature("Rib")
    def rib(self, v, body):
        return body + Pos(0, 0, 8) * Box(v["w"], 4, 6)

    def drawing(self, v):
        return {"datums": [{"letter": "A", "at": {"feature": "body", "normal": [0, 0, -1]}}],
                "fits": [{"param": "hole_d", "class": "H7"}], "notes": ["Break sharp edges"]}
'''


def crop(ui, item, name):
    """A 200 % crop of one item, for looking at closely (FORM_CRAFT_OUT)."""
    out = os.environ.get("FORM_CRAFT_OUT")
    if not out:
        return
    from PySide6.QtCore import QPointF, QRect, Qt
    toasts_gone(ui)
    it = ui.item(item) if isinstance(item, str) else item
    ui._pump(120)
    img = ui.win.grabWindow()
    dpr = img.devicePixelRatio() or 1.0
    p = it.mapToScene(QPointF(0, 0))
    x0, y0 = max(0, p.x() - 8), max(0, p.y() - 8)
    w = min(it.width() + 16, ui.win.width() - x0)
    h = min(it.height() + 16, ui.win.height() - y0)
    r = QRect(int(x0 * dpr), int(y0 * dpr), int(w * dpr), int(h * dpr))
    c = img.copy(r).scaled(int(w * 2), int(h * 2), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    c.save(str(d / f"{name}-{os.environ.get('FORM_APPEARANCE', 'dark')}-{ui.win.width()}.png"))


def head(ui):
    return ui.api("/projects/" + S["pid"])["project"]["head"]


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    p = ui.studio.create_design("Plate", PLATE, purpose="model")
    S["pid"] = p["id"]
    ui.studio.commit(ui.studio.load(p["id"]), {"hole_d": 6.5}, note="A bigger hole")
    ui.api("/projects/" + p["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["pid"])
    open_project(ui, S["pid"])
    ui.wait_until(lambda: ui.exists("feature-rib"), 10, "the tree")
    ui.settle(600)


def journey_compare(ui):
    ui.run_js("Store.openSheet('compare', { a: 1, b: 2 })")
    sheet = ui.wait_until(lambda: ui.find(name="compareSheet"), 5, "the compare sheet")
    ui.wait_until(lambda: ui.find(name="compareParam-hole_d"), 20, "the changed dimension")
    ui.check(ui.sees("5 → 6.5 mm", within=ui.item("compareParam-hole_d")), "the hole went from 5 to 6.5 mm")
    ui.wait_until(lambda: ui.find(name="compareSolid-volume"), 120, "the solid's deltas from the geometric diff")
    g = ui.api("/projects/%s/geomdiff?a=1&b=2" % S["pid"])
    ui.check(ui.sees("%.2f" % (g["volume_b_mm3"] / 1000), within=ui.item("compareSolid-volume")), "the volume is the kernel's")
    ui.check(ui.sees("1 → 1", within=ui.item("compareSolid-bodies")), "one body in each")
    ui.check(ui.sees("changed", within=ui.item("compareFeature-holes")), "Holes changed")
    ui.check(ui.sees("same", within=ui.item("compareFeature-body")), "Body is the same")
    one = ui.wait_until(lambda: ui.find(name="compareOne"), 5, "one model")
    ui.wait_until(lambda: "holes" in (one.property("flagged").toVariant() if hasattr(one.property("flagged"), "toVariant") else one.property("flagged") or []), 20,
                  "the changed feature lit on the model")
    ui.check(ui.js("!!Store.sheet") and ui.js("Store.compare") is None, "the stage is not touched")
    ui.settle(900)
    crop(ui, "sheetCard", "compare-one")
    ui.run_js("(function () { var s = Store.sheet; Store.openSheet('compare', Object.assign({}, s.props, { tab: 'side' })) })()")
    left = ui.wait_until(lambda: ui.find(name="compareLeft"), 5, "side by side")
    right = ui.find(name="compareRight")
    ui.settle(800)
    left.setProperty("az", 12.0)
    ui.settle(100)
    ui.eq(round(float(right.property("az")), 3), 12.0, "turning one view turns the other")
    right.setProperty("dist", 300.0)
    ui.settle(100)
    ui.eq(round(float(left.property("dist")), 3), 300.0, "zooming one zooms the other")
    ui.settle(600)
    crop(ui, "sheetCard", "compare-side")
    ui.run_js("(function () { var s = Store.sheet; Store.openSheet('compare', Object.assign({}, s.props, { tab: 'script' })) })()")
    ui.wait_until(lambda: ui.sees("The code is the same"), 5, "a value change keeps the code")
    ui.key("Escape")
    ui.wait_until(lambda: not ui.js("!!Store.sheet"), 5, "the sheet closed")
