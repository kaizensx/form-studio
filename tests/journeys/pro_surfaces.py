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


def crop(ui, item, name, clip=None):
    """A 200 % crop of one item, for looking at closely (FORM_CRAFT_OUT); clip: only the part inside that item (the
    pane's scrolling area)."""
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
    x1, y1 = p.x() + it.width() + 8, p.y() + it.height() + 8
    if clip is not None:
        c = ui.item(clip) if isinstance(clip, str) else clip
        q = c.mapToScene(QPointF(0, 0))
        x0, y0 = max(x0, q.x()), max(y0, q.y())
        x1, y1 = min(x1, q.x() + c.width()), min(y1, q.y() + c.height())
    w = min(x1 - x0, ui.win.width() - x0)
    h = min(y1 - y0, ui.win.height() - y0)
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


def journey_property_card(ui):
    """A fillet made by hand: its card writes the radius as a draft, previewed by the kernel, then OK or Cancel."""
    h0 = head(ui)
    r = ui.api("/projects/%s/model" % S["pid"], {"kind": "fillet", "picks": [{"at": [0, -20, 5]}], "radius": 1, "expect_head": h0})
    ui.check(r.get("feature") == "fillet_1", f"a fillet added by hand: {r}")
    wait_job(ui, S["pid"])
    ui.run_js("Store.refresh(true)")
    ui.wait_until(lambda: ui.js("Store.project.head") == h0 + 1, 30, "the window to read the fillet's revision")
    ui.wait_until(lambda: ui.exists("feature-fillet_1"), 10, "the fillet's line")
    ui.settle(400)
    ui.click("feature-fillet_1", 0.4, 0.5)
    card = ui.wait_until(lambda: ui.find(name="featureCard"), 5, "the property card")
    ui.wait_until(lambda: ui.sees("1 picked edge", within=card), 10, "the card says which edges it was made on")
    f = ui.item("cardValue-r")
    ui.eq(str(f.property("text")), "1", "the radius field shows the head's value")
    ui.click(f, 0.5, 0.5)
    ui.key("Ctrl+A")
    ui.type("2")
    ui.wait_until(lambda: ui.js("Store.draftValues.fillet_1_r") == 2, 5, "the radius as a draft")
    ui.wait_until(lambda: ui.js("!!Store.preview && !!Store.preview.impact"), 60, "the kernel's preview")
    ui.wait_until(lambda: "mm³ of material" in str(ui.item("cardVolume").property("text")), 10, "the volume change on the card")
    ui.check(str(ui.item("cardVolume").property("text")).startswith("−"), "a bigger fillet takes material away")
    ui.eq(head(ui), h0 + 1, "nothing saved yet")
    ui.scroll_to(ui.item("featureCard"), 0.2)
    ui.settle(500)
    crop(ui, "programPane", "property-card")
    ui.click("cardCancel")
    ui.wait_until(lambda: not ui.js("Object.keys(Store.draftValues).length"), 5, "Cancel drops the draft")
    ui.wait_until(lambda: str(ui.item("cardValue-r").property("text")) == "1", 5, "the field shows the head again")
    ui.click(ui.item("cardValue-r"), 0.5, 0.5)
    ui.key("Ctrl+A")
    ui.type("1.5")
    ui.key("Return")
    ui.wait_until(lambda: ui.js("!!Store.preview && Store.draftValues.fillet_1_r === 1.5"), 60, "the preview of 1.5 mm")
    ui.wait_until(lambda: ui.item("cardOk").property("enabled"), 10, "OK ready")
    ui.click("cardOk")
    ui.wait_until(lambda: head(ui) == h0 + 2, 60, "OK saved one revision")
    ui.eq(ui.api("/projects/" + S["pid"])["project"]["revisions"][-1]["values"]["fillet_1_r"], 1.5, "with the radius from the card")
    wait_job(ui, S["pid"])
    ui.run_js("Store.select('')")


def bench_entry(ui, sid):
    return next(e for e in ui.api("/projects/%s/bench" % S["pid"])["entries"] if e["id"] == sid)


def journey_tiles(ui):
    """Ctrl+B, then Tiles: each chapter tiled Analysis / Manufacturing / Documents, a sentence and Run on each."""
    ui.key("Ctrl+B")
    ui.wait_until(lambda: ui.js("Store.benchOpen") is True, 3, "the Bench sheet")
    sheet = ui.item("benchSheet")
    ui.settle(500)
    ui.click_text("Tiles", within=ui.item("benchLook"))
    tiles = ui.wait_until(lambda: ui.find(name="benchTiles"), 3, "the tiles")
    ui.wait_until(lambda: tiles.property("visible"), 3, "the tiles shown")
    for ch in ("design", "check", "document"):
        ui.check(ui.find(name="tilesBand-" + ch, within=sheet) is not None, f"the {ch} chapter is a band")
    st = ui.item("tile-strength")
    ui.check(ui.sees("A study with the stress plot, the peak stress, the safety factor and a pass or fail", within=st), "a plain sentence on the tile")
    ui.check(ui.sees("Manufacturing", within=ui.item("tilesBand-check")) and ui.sees("Analysis", within=ui.item("tilesBand-check")), "Check is tiled Analysis and Manufacturing")
    ui.check(ui.sees("Documents", within=ui.item("tilesBand-document")), "and Document holds the documents")
    th = ui.item("tile-map.thickness")
    ui.check(ui.sees("not run", within=th), "our state, in words, on a tile that never ran")
    ui.settle(300)
    ui.hover(sheet, 0.5, 0.985)
    ui.settle(300)
    crop(ui, "benchSheet", "bench-tiles")
    ui.scroll_to(th, 0.5)
    ui.click("tileRun-map.thickness")
    ui.wait_until(lambda: bench_entry(ui, "map.thickness")["state"] == "current", 120, "the thickness study run from its tile")
    ui.wait_until(lambda: ui.find(name="tileValue", within=ui.item("tile-map.thickness")) is not None
                  and ui.item("tile-map.thickness").property("visible"), 10, "its number on the tile")
    ui.click("tile-map.thickness", 0.5, 0.3)
    ui.wait_until(lambda: ui.find(name="benchFoot", within=sheet), 3, "the selected tile opened at the foot")
    ui.click_text("List", within=ui.item("benchLook"))
    ui.wait_until(lambda: ui.find(name="benchTiles") is None and ui.find(name="sheet-checks") is not None, 3, "back to the list")
    ui.run_js("Store.benchSheetSel = ''; Store.benchOpen = false; Store.setAnalysis('')")
    ui.settle(300)


def journey_tree_rows(ui):
    """Equations, Material, Purchased parts, the origin's planes, the eye, a sketch under its cut, the PMI."""
    from form import handsketch, modelling
    st = ui.studio
    p = st.load(S["pid"])
    sk, _ = handsketch.apply_ops(handsketch.empty({"datum": "XY", "offset": 0}),
                                 [{"op": "add_circle", "center": [-20, 10], "r": 3},
                                  {"op": "dimension", "kind": "diameter", "entities": [0], "value": 6, "name": "d"}])
    plan = modelling.plan(st, p, "cut", None, sketch=sk, depth=0)
    modelling.commit(st, p, plan["ops"], planned=plan)
    ui.api("/projects/" + S["pid"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["pid"])
    ui.run_js("Store.refresh(true)")
    ui.wait_until(lambda: ui.exists("feature-cut_1"), 20, "the cut's line")
    ui.settle(500)
    ui.check(ui.exists("treeSketch-cut_1"), "the cut's sketch nested under it")
    ui.check(ui.sees("1 dimension", within=ui.item("treeSketch-cut_1")), "with its named dimension")
    ui.check(not ui.exists("treeSketch-rib"), "a feature written as code has no sketch line")
    ui.check(ui.sees("not chosen", within=ui.item("treeMaterial")), "no material chosen yet")
    ui.wait_until(lambda: ui.sees("none", within=ui.item("treeParts")), 10, "no purchased parts")
    ui.check(ui.sees("Equations", within=ui.item("treeEquations")), "the parameters as Equations")
    # the PMI the drawing declares
    pm = ui.wait_until(lambda: ui.find(name="treePmi"), 10, "the PMI section")
    ui.check(ui.sees("3 annotations", within=pm), "three annotations declared")
    ui.check(ui.exists("treePmi-datum-0") and ui.exists("treePmi-fit-1") and ui.exists("treePmi-note-2"), "a datum, a fit and a note")
    ui.check(ui.sees("Hole H7", within=ui.item("treePmi-fit-1")), "the fit names its size and class")
    # the eye hides a feature in the view only
    h0 = head(ui)
    ui.scroll_to(ui.item("feature-rib"), 0.5)

    def eye():                                       # the line may be rebuilt as the revision lands: hover it again
        ui.hover(ui.item("programPane"), 0.5, 0.01)
        ui.settle(80)
        ui.hover(ui.item("feature-rib"), 0.5, 0.3)
        ui.settle(150)
        return ui.find(name="featureEye-rib")
    ui.click(ui.wait_until(eye, 8, "the eye on the hovered line"))
    ui.wait_until(lambda: ui.js("Store.hidden.indexOf('rib') >= 0"), 3, "Rib hidden in the view")
    ui.eq(head(ui), h0, "hiding saves nothing")
    ui.check(not ui.js("Store.recipe.features.filter(function (f) { return f.id === 'rib' })[0].suppressed"), "and does not suppress it")
    ui.hover(ui.item("programPane"), 0.5, 0.01)
    ui.settle(300)
    ui.check(ui.find(name="featureEye-rib") is not None, "a hidden line keeps its eye")
    crop(ui, "programPane", "tree-rows")
    ui.run_js("Store.toggleHidden('rib')")
    # the cut's card: a cut of depth 0 reads Through all; Blind is a choice the kernel builds before anything is saved
    ui.click("feature-cut_1", 0.4, 0.4)
    card = ui.wait_until(lambda: ui.find(name="featureCard"), 5, "the cut's card")
    ui.wait_until(lambda: str(ui.item("cardEnd").property("value")) == "through", 10, "a cut through everything reads Through all")
    ui.check(ui.find(name="cardValue-depth") is None, "with no depth to type")
    ui.check(ui.find(name="cardSection-Direction 2", within=card) is not None, "a second direction is offered")
    end_pick(ui, "cardEnd", "blind")
    ui.wait_until(lambda: ui.js("Store.cardFor") == "cut_1" and ui.find(name="cardValue-depth") is not None, 5, "Blind gives the cut a depth")
    ui.wait_until(lambda: "mm³ of material" in str(ui.item("cardVolume").property("text")), 60, "the preview of the blind cut")
    ui.scroll_to(ui.item("featureCard"), 0.2)
    ui.settle(400)
    crop(ui, "programPane", "property-card-cut")
    ui.click("cardCancel")
    ui.wait_until(lambda: str(ui.item("cardEnd").property("value")) == "through", 5, "Cancel: Through all again")
    ui.run_js("Store.select('')")
    ui.settle(300)
    # Equations opens the Values view; an origin plane starts a sketch on it
    ui.scroll_to(ui.item("treeEquations"), 0.5)
    ui.click("treeEquations")
    ui.wait_until(lambda: ui.js("Store.treeLower") == "values" and ui.js("Store.feature") == "", 3, "the Values view")
    ui.scroll_to(ui.item("treeOrigin"), 0.5)
    ui.click("treeOrigin")
    ui.wait_until(lambda: ui.exists("treePlane-XZ"), 3, "the three planes")
    ui.scroll_to(ui.item("treePlane-XZ"), 0.5)
    ui.click("treePlane-XZ")
    ui.wait_until(lambda: ui.js("(Store.sketchHost && Store.sketchHost.on && Store.sketchHost.sk.plane.datum === 'XZ') || (!!Store.sheet && Store.sheet.kind === 'handsketch')"), 5,
                  "a sketch on the XZ plane")
    ui.key("Escape")
    ui.settle(200)
    ui.run_js("if (Store.sketchHost && Store.sketchHost.on) Store.sketchHost.end(); Store.openSheet(null)")
    ui.settle(300)


def journey_compare_script(ui):
    """The cut added by hand, compared with the revision before: an added feature and its code, coloured."""
    h = head(ui)
    ui.run_js("Store.openSheet('compare', { a: %d, b: %d, tab: 'script' })" % (h - 1, h))
    ui.wait_until(lambda: ui.find(name="scriptRow-add") is not None, 20, "added lines in the script")
    rows = ui.api("/projects/%s/compare?a=%d&b=%d" % (S["pid"], h - 1, h))
    ui.check(any("def cut_1" in r["text"] for r in rows["script"]["rows"] if r["t"] == "add"), "the cut's method is an added line")
    ui.check(ui.sees("added", within=ui.wait_until(lambda: ui.find(name="compareFeature-cut_1"), 10, "the cut's row")), "Cut 1 is added")
    ui.settle(500)
    crop(ui, "sheetCard", "compare-script")
    ui.key("Escape")
    ui.wait_until(lambda: not ui.js("!!Store.sheet"), 5, "closed")


def end_pick(ui, button, value):
    """Open an end-condition menu of the card and pick one entry, once the popover is in place."""
    ui.click(button)
    entry = ui.wait_until(lambda: ui.find(name="cardEndPick-" + value), 4, f"the {value} entry")
    ui.wait_until(lambda: entry.property("visible") and entry.width() > 0, 3, "the menu in place")
    ui.settle(250)
    ui.click(ui.find(name="cardEndPick-" + value))
    ui.wait_until(lambda: ui.find(name="cardEndPick-" + value) is None or not ui.find(name="cardEndPick-" + value).property("visible"), 3, "the menu closed")


def card_done(ui, what):
    """The card's preview from the kernel: its volume line, or the reason it was refused."""
    def done():
        c, v = ui.find(name="featureCard"), ui.find(name="cardVolume")
        return c is not None and not c.property("pending") and (
            (v is not None and "mm³ of material" in str(v.property("text"))) or refused(ui) is not None)
    return ui.wait_until(done, 90, what)


def refused(ui):
    """Why the kernel refused the card's draft, when it did (the line is hidden otherwise)."""
    r = ui.find(name="cardRefused")
    return str(r.property("text")) if r is not None and r.property("visible") else None


def crop_card(ui, name):
    """The card at 200 %, its head and its foot (the pane scrolls: a long card never stands whole in it)."""
    if not os.environ.get("FORM_CRAFT_OUT"):
        return
    card = ui.item("featureCard")
    ui.scroll_to(card, 0.0)
    ui.settle(400)
    crop(ui, "featureCard", name + "-head", clip="inspector")
    ui.scroll_to(ui.item("cardOk"), 0.5)
    ui.settle(400)
    crop(ui, "featureCard", name + "-foot", clip="inspector")


def card_vol(ui):
    v = ui.item("featureCard").property("vol")
    return None if v is None else float(v)


def journey_end_conditions(ui):
    """The cut's card wired to the engine: up to a face picked on the stage, a draft, a second direction and a thin
    wall, each previewed by the kernel with its change in volume; OK writes one revision, Cancel leaves the head. One
    OK and one Cancel only: the draft panel at the pane's foot shows none of its own while the card is open."""
    from math import pi
    h0 = head(ui)
    ui.scroll_to(ui.item("feature-cut_1"), 0.5)
    ui.click("feature-cut_1", 0.4, 0.4)
    card = ui.wait_until(lambda: ui.find(name="featureCard"), 5, "the cut's card")
    ui.wait_until(lambda: str(ui.item("cardEnd").property("value")) == "through", 10, "Through all")
    # up to a face: pick the plate's underside (z = -5) on the stage. The pick goes in as the viewport hands one over
    # (Viewport.selPicked: the surface point under the pointer)
    end_pick(ui, "cardEnd", "face")
    pick = ui.wait_until(lambda: ui.find(name="cardPick-to_at"), 5, "the face pick")
    ui.check(ui.sees("Pick a face", within=pick), "it asks for the face")
    ui.click(pick)
    ui.wait_until(lambda: ui.js("!!Store.facePick && Store.selecting"), 3, "the stage waits for the face")
    ui.run_js("Store.selAdd([{ kind: 'face', at: [5, -10, -5], part: '' }], false)")
    ui.wait_until(lambda: not ui.js("!!Store.facePick") and not ui.js("Store.selecting"), 3, "the pick handed to the card")
    card_done(ui, "the preview up to the face")
    ui.check(refused(ui) is None, str(refused(ui)))
    # the cut went through the 10 mm plate both ways from z = 0; up to the underside it goes 5 mm: half the material back
    want, got = pi * 9 * 5, card_vol(ui)
    ui.check(got is not None and abs(got - want) < 0.5, f"+{want:.1f} mm³ back, computed by the kernel: {got}")
    ui.check(ui.sees("+%.1f mm³ of material" % got, within=card), "the card says it")
    ui.eq(head(ui), h0, "nothing saved yet")
    ui.check(not ui.js("Store.hasDraft"), "a choice is the card's draft, not a value draft")
    # a draft angle beside it (a parameter the choice adds)
    f = ui.wait_until(lambda: ui.find(name="cardValue-draft"), 5, "the draft field")
    ui.click(f, 0.5, 0.5)
    ui.key("Ctrl+A")
    ui.type("4")
    ui.key("Return")
    ui.wait_until(lambda: not ui.item("featureCard").property("pending") and (refused(ui) or (card_vol(ui) or 0) > want + 1),
                  90, "the draft previewed: a tapered cut takes less, so more material stays")
    ui.check(refused(ui) is None, str(refused(ui)))
    ui.check(ui.sees("Changed Cut 1: up to a face", within=card), "the card says what the kernel built")
    crop_card(ui, "card-up-to-face")
    # one OK, one Cancel
    ui.check(ui.find(name="draftActions") is None, "the draft panel shows no Commit of its own")
    ui.wait_until(lambda: ui.item("cardOk").property("enabled"), 20, "OK ready")
    ui.click("cardOk")
    ui.wait_until(lambda: head(ui) == h0 + 1, 120, "OK saved one revision")
    src = ui.api("/projects/%s/compare?a=%d&b=%d" % (S["pid"], h0, h0 + 1))
    added = "\n".join(r["text"] for r in src["script"]["rows"] if r["t"] == "add")
    ui.check('end="face"' in added and "cut_1_draft" in added, "the cut's call now goes up to the face, with its draft")
    ui.eq(ui.api("/projects/" + S["pid"])["project"]["revisions"][-1]["values"]["cut_1_draft"], 4, "the draft is a parameter")
    wait_job(ui, S["pid"])
    ui.run_js("Store.refresh(true)")
    ui.wait_until(lambda: str(ui.item("cardEnd").property("value")) == "face", 20, "the card reads the new head")
    # a thin wall: a ring 1 mm wide cut down to the underside, the core still joined to the plate above it
    ui.click("cardToggle-thin")
    ui.wait_until(lambda: ui.find(name="cardSeg-thin_mode") is not None, 5, "the wall's side")
    card_done(ui, "the thin preview")
    ui.check(refused(ui) is None, str(refused(ui)))
    v_ring = card_vol(ui)
    ui.check(v_ring is not None and v_ring > 0, f"a ring takes less than the full circle: {v_ring}")
    crop_card(ui, "card-thin")
    # and a second direction up through the top: the core would come loose, so the kernel refuses it with the reason
    end_pick(ui, "cardEnd2", "blind")
    ui.wait_until(lambda: ui.find(name="cardValue-depth2") is not None, 5, "the second depth")
    card_done(ui, "the second direction's preview")
    ui.check("2 solids" in (refused(ui) or ""), f"refused, with the reason: {refused(ui)}")
    ui.check(not ui.item("cardOk").property("enabled"), "no OK for a draft the kernel refused")
    crop_card(ui, "card-direction2-refused")
    ui.click("cardCancel")
    ui.wait_until(lambda: str(ui.item("cardEnd2").property("value")) == "" and ui.find(name="cardSeg-thin_mode") is None, 5, "Cancel")
    ui.eq(head(ui), h0 + 1, "Cancel saves nothing")
    ui.run_js("Store.select('')")
    ui.settle(300)


def journey_new_kinds(ui):
    """A datum plane and a mirror made by hand open their own cards: a number is a value draft (one OK, the draft
    panel without its own Commit), a choice (the mirror plane) is rewritten in the call and previewed."""
    h0 = head(ui)
    r = ui.api("/projects/%s/model" % S["pid"], {"kind": "datum_plane", "base": "XY", "offset": 20, "expect_head": h0})
    ui.check(r.get("feature") == "datum_plane_1", f"a datum plane: {r}")
    wait_job(ui, S["pid"])
    r = ui.api("/projects/%s/model" % S["pid"], {"kind": "mirror", "plane": "YZ", "expect_head": h0 + 1})
    ui.check(r.get("feature") == "mirror_1", f"a mirror: {r}")
    wait_job(ui, S["pid"])
    ui.run_js("Store.refresh(true)")
    ui.wait_until(lambda: ui.exists("feature-mirror_1"), 30, "the mirror's line")
    ui.settle(400)
    ui.scroll_to(ui.item("feature-datum_plane_1"), 0.5)
    ui.click("feature-datum_plane_1", 0.4, 0.4)
    card = ui.wait_until(lambda: ui.find(name="featureCard"), 5, "the datum plane's card")
    ui.wait_until(lambda: ui.sees("Datum plane · property card", within=card), 5, "its name")
    f = ui.item("cardValue-offset")
    ui.eq(str(f.property("text")), "20", "the offset from the head")
    ui.click(f, 0.5, 0.5)
    ui.key("Ctrl+A")
    ui.type("25")
    ui.wait_until(lambda: ui.js("Store.draftValues.datum_plane_1_offset") == 25, 5, "a value draft")
    ui.wait_until(lambda: ui.js("Store.cardFor") == "datum_plane_1", 3, "the card holds the draft's OK")
    ui.wait_until(lambda: ui.find(name="draftCard") is not None and ui.item("draftCard").property("visible"), 10, "the draft panel")
    ui.check(ui.find(name="draftActions") is None, "with no Commit or Discard of its own")
    ui.click("cardCancel")
    ui.wait_until(lambda: not ui.js("Store.hasDraft"), 5, "Cancel")
    ui.scroll_to(ui.item("feature-mirror_1"), 0.5)
    ui.click("feature-mirror_1", 0.4, 0.4)
    ui.wait_until(lambda: ui.sees("Mirror · property card", within=ui.item("featureCard")), 5, "the mirror's card")
    seg = ui.wait_until(lambda: ui.find(name="cardSeg-plane"), 5, "the mirror plane")
    ui.eq(seg.property("value"), "YZ", "mirrored about YZ")
    ui.click_text("XZ", within=seg)
    card_done(ui, "the mirror about XZ, previewed")
    ui.check(refused(ui) is None, str(refused(ui)))
    crop_card(ui, "card-mirror")
    ui.click("cardCancel")
    ui.wait_until(lambda: ui.item("cardSeg-plane").property("value") == "YZ", 5, "Cancel: YZ again")
    ui.eq(head(ui), h0 + 2, "nothing saved by the cards")
    ui.run_js("Store.select('')")
    ui.settle(300)


def journey_study_verdict(ui):
    """The study card's verdict and load scale, on a fixture result (the FEA engine is optional; tests/journeys/results.py
    checks the same card on a real solved study when it is installed). The numbers below are inputs, not results."""
    ui.run_js("""(function () {
        var o = Qt.createQmlObject('import QtQuick; import Form; Rectangle { objectName: "verdictHost"; x: 900; y: 160; width: 300; height: 240; radius: 14; color: Theme.plate2; '
            + 'StudyVerdict { id: sv; objectName: "fixtureVerdict"; x: 14; y: 14; width: 272 } }', win.contentItem)
        o.children[0].r = { linear: true, safety: { value: 5.4, low: 5.36, against: "yield" }, peak: { value: 51.2 }, max_displacement: { value: 0.021 } }
    })()""")
    v = ui.wait_until(lambda: ui.find(name="fixtureVerdict"), 3, "the verdict")
    t = lambda: str(ui.find(name="verdictText", within=v).property("text"))
    ui.eq(t(), "Holds the load with a safety factor of 5.4 (at least 5.3 with the stated error).", "the sentence, the bound rounded down")
    ui.check(ui.sees("linear: exact for this model", within=v), "the slider says why it is exact")
    crop(ui, "verdictHost", "study-verdict")
    v.setProperty("k", 2.0)
    ui.settle(50)
    ui.eq(t(), "Holds 2 × the load with a safety factor of 2.7 (at least 2.6 with the stated error).", "twice the load")
    ui.check("peak stress 102 MPa" in str(ui.find(name="loadScaleNote", within=v).property("text")), "the peak stress doubles with it")
    v.setProperty("k", 6.0)
    ui.settle(50)
    ui.check(t().startswith("Too weak at 6 × the load: it holds up to 0.90 ×"), t())
    ui.run_js("""(function () { var h = null, k = win.contentItem.children; for (var i = 0; i < k.length; i++) if (k[i].objectName === "verdictHost") h = k[i];
        h.children[0].r = { linear: false, safety: { value: 3.1, low: 3.0 }, peak: { value: 9 }, max_displacement: { value: 0.1 } } })()""")
    ui.settle(50)
    ui.check(ui.find(name="loadScale", within=v) is None, "no load scale for a study that is not linear static")
    ui.check(t().startswith("Holds the load with a safety factor of 3.1"), "the verdict stays, at 1 ×")
    ui.run_js("""(function () { var k = win.contentItem.children; for (var i = 0; i < k.length; i++) if (k[i].objectName === "verdictHost") k[i].destroy() })()""")
