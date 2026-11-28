"""The two Pareto fronts in the Bench card, each from a real run of its engine in this journey's data folder.

Print orientation (form/printphys/orient.py): the bracket of tests/journeys/_results.py as a print design. Selecting
*Orientation front* in Check draws the front as a chart in the card; a point of it turns the part on the stage to lie
that way (a preview, the print setup unchanged), and *Use this* writes that orientation to the print setup. *As
designed* turns it back.

Inverse design (form/inverse/design.py): needs the FEA engine (every variant is solved). Its front is a Design entry,
opened from the Bench sheet; a point opens its variant as the draft. Without the engine the journey says so and stops.

FORM_RESULT_CROPS=<dir> saves 200 % crops of the stage and the card.
"""
import math
import os
from pathlib import Path

import _results as R
from _lib import open_project, printing_on

DATA = "fresh"


def res(ui, expr="Results.kind"):
    return ui.js(expr)


def crop(ui, name):
    R.stage_crops(ui, name)


def point_at(ui, idx):
    """Where point `idx` of the card's front is drawn, as fractions of the chart (FrontChart.qml's own mapping)."""
    ch = ui.item("frontChart")
    pts = res(ui, "Results.r.points")
    w, h = ch.width(), ch.height()

    def span(k):
        vs = [p["at"][k] for p in pts if p["at"][k] is not None]
        lo, hi = min(vs), max(vs)
        pad = (hi - lo) * 0.08 or abs(hi) * 0.1 or 1
        return lo - pad, hi + pad
    sx, sy = span(0), span(1)
    p = next(q for q in pts if q["index"] == idx)
    x = 16 + (p["at"][0] - sx[0]) / (sx[1] - sx[0]) * (w - 32)
    y = 26 + (h - 56) - (p["at"][1] - sy[0]) / (sy[1] - sy[0]) * (h - 56)
    return x / w, y / h


def journey_orientation(ui):
    printing_on(ui)
    st = ui.studio
    pid = st.create_design("Print bracket", R.BRACKET, purpose="print")["id"]
    e = R.bench(st, pid, "print.orient")
    ui.check(e.get("state") == "current", f"the orientation front ran: {e.get('state')} {e.get('why', '')}")
    open_project(ui, pid)
    ui.key("Ctrl+2")
    ui.wait_until(lambda: ui.find(name="bench-print.orient"), 15, "the orientation front's row")
    ui.scroll_to(ui.item("bench-print.orient"), 0.4)
    ui.click("bench-print.orient", 0.3, 0.5)
    ui.wait_until(lambda: res(ui, "Results.id") == "print.orient" and res(ui, "!!Results.r && !Results.busy"), 20, "the front")
    ui.eq(res(ui), "front", "drawn as a front")
    pts = res(ui, "Results.r.points")
    ui.check(len(pts) >= 2 and all(p.get("id") for p in pts), f"every point of the front names its orientation ({len(pts)} points)")
    ui.scroll_to(ui.item("frontChart"), 0.5)
    ui.settle(300)
    pick = next((p for p in pts if not p.get("current") and p.get("down") and abs(p["down"][2] + 1) > 1e-3), None)
    ui.check(pick is not None, "a point of the front that is not the part as it stands")
    ui.click("frontChart", *point_at(ui, pick["index"]))
    ui.wait_until(lambda: res(ui, "Results.point") == pick["index"], 3, "the point to open")
    ui.eq(res(ui, "Results.previewId"), pick["id"], "the point's orientation is previewed")
    ui.wait_until(lambda: abs(res(ui, "Store.viewer.orientK") - 1) < 1e-6, 3, "the part to turn")
    d = pick["down"]
    n = math.sqrt(sum(x * x for x in d))
    # the design node's turn takes the picked down direction to -Z
    from PySide6.QtGui import QQuaternion, QVector3D
    w, x, y, z = res(ui, "[Store.viewer.orientQ.scalar, Store.viewer.orientQ.x, Store.viewer.orientQ.y, Store.viewer.orientQ.z]")
    v = QQuaternion(w, x, y, z).rotatedVector(QVector3D(d[0] / n, d[1] / n, d[2] / n))
    ui.check(abs(v.x()) < 1e-3 and abs(v.y()) < 1e-3 and abs(v.z() + 1) < 1e-3, f"the picked side faces the floor: {v.x():.3f}, {v.y():.3f}, {v.z():.3f}")
    was = st.load(pid)["orientation"]
    ui.check(was != pick["id"], "previewing writes nothing to the print setup")
    ui.check(ui.find(name="orientUseThis") is not None, "the card offers Use this")
    ui.settle(300)
    crop(ui, "orient-preview")
    ui.click("orientAsDesigned")
    ui.wait_until(lambda: res(ui, "Store.viewer.orientK") < 1e-6, 3, "the part to turn back")
    ui.eq(st.load(pid)["orientation"], was, "As designed changes nothing either")
    ui.click("frontChart", *point_at(ui, pick["index"]))
    ui.wait_until(lambda: res(ui, "Results.previewId") == pick["id"], 3, "the point again")
    ui.click("orientUseThis")
    ui.wait_until(lambda: st.load(pid)["orientation"] == pick["id"], 20, "Use this to write the print setup")
    ui.check(st.load(pid)["print"]["orient"]["picked"]["was"] == was, "the pick says what it replaced")
    ui.wait_until(lambda: res(ui, "Store.viewer.orientK") < 1e-6, 3, "the preview to end once written")


def journey_inverse(ui):
    st = ui.studio
    if not R.fea_ready(st):
        print("INVERSE: the FEA engine is not installed; the front was not exercised", flush=True)
        return
    from form.inverse import design as I
    pid = R.design(st, "Search bracket", R.BRACKET)
    R.strength(st, pid, R.STATIC)
    I.run(st, pid, {"minimize": ["mass_g", "fea.max_displacement_mm"], "vary": [{"key": "t", "min": 3, "max": 12}, {"key": "r", "min": 0, "max": 10}],
                    "budget": {"solves": 6, "seconds": 300}})
    open_project(ui, pid)
    ui.key("Ctrl+1")
    ui.settle(300)
    ui.key("Ctrl+B")
    ui.wait_until(lambda: ui.find(name="sheet-inverse"), 15, "the inverse design row in the sheet")
    ui.settle(400)
    ui.click("sheet-inverse", 0.3, 0.5)
    ui.click(ui.wait_until(lambda: ui.find(name="benchFootOpen"), 3, "Open in Design"))
    ui.wait_until(lambda: res(ui, "Results.id") == "inverse" and res(ui, "!!Results.r && !Results.busy"), 20, "the front")
    ui.eq(res(ui), "front", "drawn as a front in the card")
    ui.eq(ui.store.get("stage"), "shape", "in Design")
    pts = res(ui, "Results.r.points")
    front = [p for p in pts if p["state"] == "front"]
    ui.check(len(front) >= 1, f"the front has its variants ({len(front)} of {len(pts)})")
    ui.scroll_to(ui.item("frontChart"), 0.5)
    ui.settle(300)
    crop(ui, "inverse-front")
    other = next((p for p in front if not p.get("current")), None)
    ui.check(other is not None, "a variant on the front that is not the design as it stands")
    ui.click("frontChart", *point_at(ui, other["index"]))
    ui.wait_until(lambda: res(ui, "Store.hasDraft"), 20, "the variant to open as the draft")
    ui.settle(600)
    crop(ui, "inverse-draft")


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    journey_orientation(ui)
    journey_inverse(ui)
