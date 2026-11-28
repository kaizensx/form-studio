"""The bracket from Start blank, by hand, no agent (the Beyond Studio plan's Wave B acceptance test), timed.

Start blank → Model it by hand → an L profile drawn on the XZ plane with the line tool (six clicks and one to close;
the lines snap horizontal and vertical) → four dimensions typed (base 60, upright 40, both 5 thick: fully
constrained) → extruded 40 mm → an M4 clearance hole into the base, picked in Annotate → a 2 mm fillet on a picked
edge. Every step is a real click or key on the window; every outcome is read from the engine. The clock runs from
the Start blank click to the fillet's revision.

What the time means: it is the time the window and the engine take with scripted input, which does not hesitate.
A person also reads, aims and thinks; the number shows the tools are not what makes it slow. The journey prints it
and fails above 120 s."""
import json
import os
import time

from _lib import toasts_gone, wait_job

DATA = "fresh"
S = {}
LIMIT_S = 120.0


def crop(ui, item, name):
    out = os.environ.get("FORM_CRAFT_OUT")
    if not out:
        return
    from pathlib import Path
    from PySide6.QtCore import QPointF, QRect, Qt
    it = ui.item(item) if isinstance(item, str) else item
    ui._pump(80)
    img = ui.win.grabWindow()
    dpr = img.devicePixelRatio() or 1.0
    p = it.mapToScene(QPointF(0, 0))
    r = QRect(int((p.x() - 8) * dpr), int((p.y() - 8) * dpr), int((it.width() + 16) * dpr), int((it.height() + 16) * dpr))
    c = img.copy(r).scaled(int(r.width() * 2 / dpr), int(r.height() * 2 / dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    Path(out).mkdir(parents=True, exist_ok=True)
    c.save(str(Path(out) / f"{name}-{os.environ.get('FORM_APPEARANCE', 'dark')}.png"))


def pad_click(ui, x, y):
    """Click the sketch pad at (x, y) mm, through the editor's own view transform."""
    ed, pad = ui.item("sketchEditor"), ui.item("sketchEdPad")
    k, ox, oy = (float(ed.property(n)) for n in ("k", "ox", "oy"))
    w, h = pad.width(), pad.height()
    ui.click(pad, (ox + x * k) / w, (h - oy - y * k) / h)
    ui.settle(120)


def sketch(ui):
    v = ui.item("sketchEditor").property("sk")
    return v.toVariant() if hasattr(v, "toVariant") else v


def solved(ui):
    v = ui.item("sketchEditor").property("sol")
    v = v.toVariant() if hasattr(v, "toVariant") else v
    return v or {}


def head(ui):
    return ui.api("/projects/" + S["pid"])["project"]["head"]


def hits(ui, want):
    vp = ui.item("viewport")
    w, h = vp.width(), vp.height()
    out = []
    for j in range(28):
        for i in range(28):
            x, y = w * (0.08 + 0.84 * (i + 0.5) / 28), h * (0.08 + 0.84 * (j + 0.5) / 28)
            r = ui.js("JSON.stringify(Store.viewer.hitAt(%f, %f))" % (x, y))
            if r and r != "null":
                hit = json.loads(r)
                if want(hit):
                    out.append((x / w, y / h, hit))
    return out


def add_from_panel(ui, what):
    ui.click(ui.item("modelPreview"))
    ui.wait_until(lambda: ui.item("modelImpact").property("text"), 90, f"the {what} previewed")
    h0 = head(ui)
    ui.click(ui.item("modelAdd"))
    ui.wait_until(lambda: head(ui) == h0 + 1, 120, f"the {what} saved")
    ui.wait_until(lambda: ui.js("Store.project.head") == h0 + 1, 60, "the window on the new revision")
    ui.settle(400)


def journey_bracket(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    t0 = time.perf_counter()
    ui.click(ui.item("startBlank"))
    ui.click(ui.item("blankByHand", timeout=15))
    ui.wait_until(lambda: (ui.store.get("sheet") or {}).get("kind") == "handsketch", 6, "the sketch editor")
    ui.settle(500)
    ui.click_text("XZ", within=ui.item("sketchDatum"))
    for x, y in ((0, 0), (60, 0), (60, 5), (5, 5), (5, 40), (0, 40), (0, 0)):
        pad_click(ui, x, y)
    sk = sketch(ui)
    ui.eq(len(sk["entities"]), 6, "six lines")
    ui.eq(sorted(c["k"] for c in sk["constraints"]), ["horizontal"] * 3 + ["vertical"] * 3, "snapped H and V")
    ui.wait_until(lambda: solved(ui).get("closed"), 10, "a closed profile")
    ui.key("V")
    for (x, y), val in (((30, 0), "60"), ((0, 20), "40"), ((60, 2.5), "5"), ((2.5, 40), "5")):
        pad_click(ui, x, y)
        f = ui.item("sketchDim")
        ui.click(f)
        ui.key("Ctrl+A")
        ui.type(val)
        ui.key("Return")
        ui.settle(250)
    ui.wait_until(lambda: solved(ui).get("fully_constrained"), 10, "the profile fully constrained")
    ui.click(ui.item("sketchName"))
    ui.type("Wall bracket")
    d = ui.item("sketchDepth")
    ui.click(d)
    ui.key("Ctrl+A")
    ui.type("40")
    ui.settle(300)
    ui.shot("bracket-1-sketch")
    crop(ui, "sheetCard", "sketch-editor")
    ui.click(ui.item("sketchCommit"))
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.js("!!Store.view"), 120, "the bracket open as a design")
    S["pid"] = ui.store.get("pid")
    p = ui.api("/projects/" + S["pid"])
    vals = p["project"]["revisions"][-1]["values"]
    ui.eq({k: vals[k] for k in ("extrude_1_l1", "extrude_1_l2", "extrude_1_l3", "extrude_1_l4", "extrude_1_depth")},
          {"extrude_1_l1": 60, "extrude_1_l2": 40, "extrude_1_l3": 5, "extrude_1_l4": 5, "extrude_1_depth": 40},
          "every typed dimension is a parameter of the design")
    ui.wait_until(lambda: ui.js("!!Store.viewer && !!Store.view && Store.view.volume_mm3 > 0"), 60, "the solid")
    ui.check(abs(ui.js("Store.view.volume_mm3") - (60 * 5 + 35 * 5) * 40) < 1, "the solid the sketch says")
    ui.settle(600)
    # an M4 clearance hole into the base, picked on its top face
    ui.click(ui.item("railHole"))
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate" and ui.store.get("selMode") == "face", 3, "face picking")
    ui.settle(500)
    top = hits(ui, lambda h: h["normal"][2] > 0.95 and abs(h["at"][2] - 5) < 1e-3 and 25 < h["at"][0] < 50
               and -30 < h["at"][1] < -10)
    ui.check(top, "a pixel on the base's top")
    ui.click("viewport", top[len(top) // 2][0], top[len(top) // 2][1])
    ui.wait_until(lambda: (ui.store.get("selection") or {}).get("items"), 60, "the face analysed")
    ui.click(ui.item("holeHere"))
    ui.click_text("M4", within=ui.item("modelPanel"))
    add_from_panel(ui, "hole")
    # a 2 mm fillet on the end edge of the base, picked
    ui.click(ui.item("railRound"))
    ui.wait_until(lambda: ui.store.get("selMode") == "edge", 3, "edge picking")
    ui.settle(500)
    end = hits(ui, lambda h: h["normal"][2] > 0.95 and abs(h["at"][2] - 5) < 1e-3 and h["at"][0] > 56)
    ui.check(end, "a pixel at the base's far end")
    x, y, _h = max(end, key=lambda t: t[2]["at"][0])
    ui.click("viewport", x, y)
    it = ui.wait_until(lambda: (ui.store.get("selection") or {}).get("items"), 60, "an edge")[0]
    ui.eq(it["kind"], "edge", "an edge was picked")
    ui.click(ui.item("roundEdges"))
    f = ui.item("model_radius")
    ui.click(f)
    ui.key("Ctrl+A")
    ui.type("2")
    add_from_panel(ui, "fillet")
    elapsed = time.perf_counter() - t0
    said = f"BRACKET BY HAND: {elapsed:.1f} s from Start blank to the fillet's revision (scripted input)"
    print(said, flush=True)
    if os.environ.get("FORM_CRAFT_OUT"):
        with open(os.path.join(os.environ["FORM_CRAFT_OUT"], "bracket-time.txt"), "a", encoding="utf-8") as fh:
            fh.write(f"{os.environ.get('FORM_APPEARANCE', 'dark')}: {said}\n")
    ids = ui.js("Store.recipe.features.map(function (f) { return f.id })")
    ui.eq(ids, ["extrude_1", "hole_1", "fillet_1"], "three features, each one method in the code")
    ui.check(elapsed < LIMIT_S, f"made in {elapsed:.1f} s, under {LIMIT_S:.0f} s")
    wait_job(ui, S["pid"])
    ui.click_text("Select")
    toasts_gone(ui)
    ui.settle(900)
    ui.shot("bracket-2-made")
