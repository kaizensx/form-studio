"""Modelling by hand (form/modelling.py, Shape.qml, ModelPanel.qml): the Program's tree and one picked feature.

The rollback bar dragged up to a feature shows the part as it stood then (from the checkpoints, nothing saved) and
back; a line's menu suppresses and restores it, renames it in place, says what it depends on, and moves it (a move
the build refuses leaves the head where it was, with the reason); a line dragged by its number moves it. Then an edge
picked in Annotate gets a fillet: previewed with its computed change, added as one feature in the code. Every
outcome is read from the engine. With FORM_CRAFT_OUT set, 200 % crops of the Program and the panel are written."""
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

    @feature("Rib slot")
    def rib_slot(self, v, body):
        return body - Pos(0, 0, 9) * Box(8, 10, 2)
'''


def crop(ui, item, name):
    """A 200 % crop of one item (the owner looks at these before anything is claimed)."""
    out = os.environ.get("FORM_CRAFT_OUT")
    if not out:
        return
    from PySide6.QtCore import QPointF, QRect, Qt
    toasts_gone(ui)                                       # a crop shows the pane, not the toasts over it
    if item == "programPane":
        ui.run_js("Store.revealInspector(0)")
        ui.settle(300)
    it = ui.item(item) if isinstance(item, str) else item
    ui._pump(80)
    img = ui.win.grabWindow()
    dpr = img.devicePixelRatio() or 1.0
    p = it.mapToScene(QPointF(0, 0))
    r = QRect(int((p.x() - 8) * dpr), int((p.y() - 8) * dpr), int((it.width() + 16) * dpr), int((it.height() + 16) * dpr))
    c = img.copy(r)
    c = c.scaled(int(r.width() * 2 / dpr), int(r.height() * 2 / dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    c.save(str(d / f"{name}-{os.environ.get('FORM_APPEARANCE', 'dark')}.png"))


def head(ui):
    return ui.api("/projects/" + S["pid"])["project"]["head"]


def feats(ui):
    return ui.js("Store.recipe.features.map(function (f) { return [f.id, f.label, !!f.suppressed] })")


def menu(ui, fid, entry):
    """Open a line's menu and run one entry. The listing is rebuilt when a revision lands (and when the conversation
    column arrives with its first card): if the line went away between finding and pressing it, find it again."""
    for attempt in range(3):
        try:
            return _menu(ui, fid, entry)
        except RuntimeError:                       # the item was rebuilt under the pointer: try once the window rests
            ui.key("Escape")
            ui.idle(10)
            ui.settle(600)
    return _menu(ui, fid, entry)


def _menu(ui, fid, entry):
    ui.idle(10)
    row = ui.item("feature-" + fid)
    ui.scroll_to(row)
    ui.hover(ui.item("programPane"), 0.5, 0.01)            # off the line first: a rebuilt line needs the pointer to enter it
    ui.settle(100)
    ui.hover(row, 0.5, 0.3)
    ui.settle(200)
    ui.click(ui.item("featureMore-" + fid))
    ui.wait_until(lambda: ui.exists(text=entry), 4, f"the menu entry {entry}")
    ui.settle(150)
    ui.click_text(entry)


def after(ui, h0, what):
    ui.wait_until(lambda: head(ui) == h0 + 1, 120, what)
    ui.wait_until(lambda: ui.js("Store.project.head") == h0 + 1, 60, "the window to read the new revision")
    ui.settle(500)


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    p = ui.studio.create_design("Plate", PLATE, purpose="model")
    S["pid"] = p["id"]
    ui.api("/projects/" + p["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["pid"])
    open_project(ui, S["pid"])
    ui.wait_until(lambda: ui.exists("feature-rib_slot"), 10, "the Program listing")
    ui.settle(600)
    crop(ui, "programPane", "program-0")


def journey_rollback_bar(ui):
    grip = ui.item("rollBar")
    target = ui.item("feature-holes")
    v_all = ui.js("Store.shown.volume_mm3")
    ui.drag(grip, target, fx=0.12, fy=0.5, steps=10)
    ui.wait_until(lambda: ui.js("Store.scrub && Store.scrub.upto") == "holes", 20, "the part rolled back to Holes")
    ui.wait_until(lambda: abs(ui.js("Store.shown.volume_mm3") - (24000 - 3.14159265 * 2.5 ** 2 * 10)) < 1, 10,
                  "the solid as it stood after Holes")
    ui.check(ui.js("Store.shown.upto.ms") < 100, "rolled back from the checkpoints in under 100 ms")
    ui.check(ui.sees("Rolled back to Holes · viewing only"), "the notice over the view says what is shown")
    ui.eq(head(ui), 1, "nothing saved")
    ui.settle(600)
    ui.shot("modelling-rollback")
    crop(ui, "programPane", "program-rollback")
    ui.click(ui.item("backToHead"))
    ui.wait_until(lambda: not ui.js("!!Store.scrub"), 10, "every feature shown again")
    ui.wait_until(lambda: abs(ui.js("Store.shown.volume_mm3") - v_all) < 1e-6, 10, "the head's solid again")


def journey_suppress_restore(ui):
    h0 = head(ui)
    menu(ui, "rib", "Suppress")
    after(ui, h0, "Rib suppressed as a new revision")
    ui.eq(feats(ui)[2], ["rib", "Rib", True], "Rib is suppressed in the source")
    ui.check(ui.sees("suppressed", within=ui.item("feature-rib")), "the line says suppressed")
    src = ui.api("/projects/" + S["pid"] + "/tree")
    ui.check(src["features"][2]["suppressed"], "the engine reads it from the code")
    # the hand edit is a revision card in the conversation, as an agent's change is
    ui.wait_until(lambda: ui.js("Store.chatItems.some(function (e) { return e.t === 'act' && !!e.change && e.change.to === %d })"
                                % (h0 + 1)), 15, "the revision card in the conversation")
    cid = ui.js("Store.convId")
    evs = ui.api("/conversations/" + cid)["items"]
    card = [e for e in evs if e.get("t") == "act" and e.get("change")][-1]
    ui.eq((card["text"], card["change"]["from"], card["change"]["to"]), ("Suppressed rib", h0, h0 + 1), "the card says what changed")
    crop(ui, "programPane", "program-suppressed")
    menu(ui, "rib", "Restore")
    after(ui, h0 + 1, "Rib restored")
    ui.eq(feats(ui)[2][2], False, "Rib is built again")


def journey_rename_and_depends(ui):
    h0 = head(ui)
    menu(ui, "holes", "Rename…")
    f = ui.item("renameField")
    ui.wait_until(lambda: ui.focus_inside(f), 3, "the name field focused")
    ui.key("Ctrl+A")
    ui.type("Mount holes")
    ui.key("Return")
    after(ui, h0, "the rename saved")
    ui.eq(feats(ui)[1][1], "Mount holes", "the new label is the feature's label in the code")
    menu(ui, "holes", "What it depends on")
    ui.wait_until(lambda: "Reads hole_d = 5, w = 60." in (ui.item("featureDepends").property("text") or ""), 10,
                  "what Holes reads, from its code")
    ui.settle(300)
    crop(ui, "programPane", "program-depends")
    ui.click_text("Close", within=ui.item("feature-holes"))


def journey_moves(ui):
    h0 = head(ui)
    # moving the slot above the rib would make it cut nothing: the build refuses it and nothing is saved
    menu(ui, "rib_slot", "Move up")
    ui.wait_until(lambda: ui.sees("Refused: rib_slot would do nothing"), 60, "the refusal with its reason")
    ui.eq(head(ui), h0, "the head did not move")
    ui.settle(2800)
    # by drag: Holes, taken by its number, goes below the rib
    ui.drag(ui.item("featureDrag-holes"), ui.item("feature-rib"), fx=0.5, fy=0.5, steps=10)
    after(ui, h0, "the move by drag saved")
    ui.eq([x[0] for x in feats(ui)], ["body", "rib", "holes", "rib_slot"], "the new build order")


def journey_fillet_on_a_picked_edge(ui):
    ui.click_text("Annotate")
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate", 3, "the Annotate tool")
    ui.key("R")                                           # edges
    ui.wait_until(lambda: ui.store.get("selMode") == "edge", 3, "edge mode")
    ui.settle(700)
    vp = ui.item("viewport")
    w, h = vp.width(), vp.height()
    best = None
    for j in range(24):
        for i in range(24):
            x, y = w * (0.1 + 0.8 * (i + 0.5) / 24), h * (0.1 + 0.8 * (j + 0.5) / 24)
            r = ui.js("JSON.stringify(Store.viewer.hitAt(%f, %f))" % (x, y))
            if r and r != "null":
                import json
                hit = json.loads(r)
                if hit["normal"][2] > 0.95 and abs(hit["at"][2] - 5) < 1e-3 and abs(hit["at"][0]) > 6:
                    if best is None or hit["at"][1] > best[2]["at"][1]:
                        best = (x / w, y / h, hit)
    ui.check(best is not None, "a pixel on the plate's top, near its back edge")
    ui.click("viewport", best[0], best[1])
    it = ui.wait_until(lambda: (ui.store.get("selection") or {}).get("items"), 60, "an edge")[0]
    ui.eq(it["kind"], "edge", "an edge was picked")
    ui.click(ui.item("roundEdges"))
    f = ui.item("model_radius")
    ui.click(f)
    ui.key("Ctrl+A")
    ui.type("2")
    h0 = head(ui)
    ui.click(ui.item("modelPreview"))
    ui.wait_until(lambda: ui.item("modelImpact").property("text"), 60, "the draft's computed change")
    ui.check("mm³" in ui.item("modelImpact").property("text"), "the change in volume, computed")
    ui.eq(head(ui), h0, "a preview saves nothing")
    ui.settle(500)
    ui.shot("modelling-fillet-draft")
    crop(ui, "selectionPanel", "fillet-panel")
    ui.click(ui.item("modelAdd"))
    after(ui, h0, "the fillet added as a revision")
    ids = [x[0] for x in feats(ui)]
    ui.eq(ids[-1], "fillet_1", "Fillet 1 is the last feature")
    src = ui.api("/projects/" + S["pid"] + "/tree")
    ui.eq(src["features"][-1]["reads"]["params"], ["fillet_1_r"], "its radius is a parameter in the code")
    wait_job(ui, S["pid"])
    ui.click_text("Select")
    ui.settle(900)
    ui.shot("modelling-fillet-added")
    crop(ui, "programPane", "program-fillet")
