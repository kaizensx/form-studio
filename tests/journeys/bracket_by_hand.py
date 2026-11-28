"""The bracket from Start blank, by hand, no agent (the Beyond Studio plan's Wave B acceptance test), timed.

Start blank → Model it by hand → the XZ plane → an L profile drawn on that plane in the 3D view with the line tool
(six clicks and one to close; the lines snap horizontal and vertical) → four dimensions typed in place (base 60,
upright 40, both 5 thick: nothing left free) → extruded 40 mm → Cut: the base's top face picked, a rectangle drawn on
it, cut 2 mm deep with the kernel's preview on the part → an M4 clearance hole into the base → a 2 mm fillet on a
picked edge. Every step is a real click or key on the window; every outcome is read from the engine. The clock runs
from the Start blank click to the fillet's revision.

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
HOST = "Store.sketchHost"


def crop(ui, item, name, pad=8):
    out = os.environ.get("FORM_CRAFT_OUT")
    if not out:
        return
    from pathlib import Path
    from PySide6.QtCore import QPointF, QRect, Qt
    ui._pump(80)
    img = ui.win.grabWindow()
    dpr = img.devicePixelRatio() or 1.0
    if isinstance(item, tuple):
        x, y, w, h = item
    else:
        it = ui.item(item) if isinstance(item, str) else item
        p = it.mapToScene(QPointF(0, 0))
        x, y, w, h = p.x() - pad, p.y() - pad, it.width() + 2 * pad, it.height() + 2 * pad
    r = QRect(int(x * dpr), int(y * dpr), int(w * dpr), int(h * dpr))
    c = img.copy(r).scaled(int(r.width() * 2 / dpr), int(r.height() * 2 / dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    Path(out).mkdir(parents=True, exist_ok=True)
    size = f"{ui.win.width()}-{'col' if ui.js('Store.talkCol > 0') else 'folded'}"
    c.save(str(Path(out) / f"{name}-{size}-{os.environ.get('FORM_APPEARANCE', 'dark')}.png"))


def clear_symbols(ui, when):
    """The constraint symbols on the sketch cover neither each other nor a dimension's tag (greedy seats, SketchOnPart)."""
    lay = ui.js("Store.sketchHost.lay")
    gs = [(g["x"] - 9, g["y"] - 9, 18, 18) for g in lay["glyphs"]]
    tags = []
    for i in range(len(ui.js("Store.sketchHost.sk.constraints"))):
        t = ui.find(name=f"sketchDim-{i}")
        if t is not None and t.isVisible():
            tags.append((t.x(), t.y(), t.width(), t.height()))

    def hit(a, b):
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
    for i, a in enumerate(gs):
        for b in gs[i + 1:]:
            ui.check(not hit(a, b), f"{when}: two constraint symbols overlap at {a[:2]} and {b[:2]}")
        for b in tags:
            ui.check(not hit(a, b), f"{when}: a constraint symbol at {a[:2]} covers a dimension at {b[:2]}")
    return len(gs)


def frames(ui, ms):
    """How many frames the window swaps in ms while nothing is touched."""
    n = [0]

    def tick():
        n[0] += 1
    ui.win.frameSwapped.connect(tick)
    ui._pump(ms)
    ui.win.frameSwapped.disconnect(tick)
    return n[0]


def px(ui, x, y):
    """Where the sketch's point (x, y) mm is on the window, through the view's own camera, as fractions of the stage."""
    p = ui.js("(function () { var p = %s.px([%f, %f]); return [p.x, p.y] })()" % (HOST, x, y))
    a = ui.item("sketchArea")
    return p[0] / a.width(), p[1] / a.height()


def plane_click(ui, x, y):
    fx, fy = px(ui, x, y)
    ui.click("sketchArea", fx, fy)
    ui.settle(120)


def sketch(ui):
    return json.loads(ui.js("JSON.stringify(%s.sk)" % HOST))


def solved(ui):
    return json.loads(ui.js("JSON.stringify(%s.sol || {})" % HOST))


def sketching(ui, what):
    ui.wait_until(lambda: ui.js("!!%s && %s.on" % (HOST, HOST)) is True, 20, what)
    ui.check((ui.store.get("sheet") or {}).get("kind") != "handsketch", "no sheet: the sketch is on the stage")
    ui.settle(900)                                  # the camera eases normal to the plane


def head(ui):
    return ui.api("/projects/" + S["pid"])["project"]["head"]


def hits(ui, want, n=28):
    vp = ui.item("viewport")
    w, h = vp.width(), vp.height()
    out = []
    for j in range(n):
        for i in range(n):
            x, y = w * (0.08 + 0.84 * (i + 0.5) / n), h * (0.08 + 0.84 * (j + 0.5) / n)
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


def stage_rect(ui):
    a = ui.item("sketchArea")
    cap = ui.item("sketchCapsule")
    x = cap.x() - 60
    return (x, cap.y() - 8, min(a.width() - x, 760), a.height() - cap.y())


def journey_bracket(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    t0 = time.perf_counter()
    ui.click(ui.item("startBlank"))
    ui.click(ui.item("blankByHand", timeout=15))
    sketching(ui, "the sketch on the empty floor")
    ui.click(ui.item("sketchPlane-XZ"))
    ui.wait_until(lambda: sketch(ui)["plane"].get("datum") == "XZ", 5, "the XZ plane")
    ui.settle(900)
    az, el = ui.js("Store.sketchHost.vp.az"), ui.js("Store.sketchHost.vp.el")
    ui.check(abs(((az + 180) % 360) - 180) < 1 and abs(el) < 1, f"the camera looks straight at the XZ plane: az {az:.1f}, el {el:.1f}")
    for x, y in ((0, 0), (60, 0), (60, 5), (5, 5), (5, 40), (0, 40), (0, 0)):
        plane_click(ui, x, y)
    sk = sketch(ui)
    ui.eq(len(sk["entities"]), 6, "six lines")
    ui.eq(sorted(c["k"] for c in sk["constraints"]), ["horizontal"] * 3 + ["vertical"] * 3, "snapped H and V")
    ui.wait_until(lambda: solved(ui).get("closed"), 10, "a closed profile")
    ui.check(solved(ui).get("dof", 0) > 0 and "free" in " ".join(ui.texts(ui.item("sketchDof"))), "the capsule counts what is left free")
    ui.key("D")                                     # Dimension: click a line, type its size in place
    for (x, y), val in (((30, 0), "60"), ((0, 20), "40"), ((60, 2.5), "5"), ((2.5, 40), "5")):
        plane_click(ui, x, y)
        ui.wait_until(lambda: ui.js("Store.sketchHost.editing") >= 0, 5, "the dimension, open to type in")
        ui.key("Ctrl+A")
        ui.type(val)
        ui.key("Return")
        ui.settle(250)
    ui.wait_until(lambda: solved(ui).get("fully_constrained"), 10, "the profile fully constrained")
    ui.check("0 free" in " ".join(ui.texts(ui.item("sketchDof"))), "the capsule says nothing is left free")
    ui.click(ui.item("sketchName"))
    ui.type("Wall bracket")
    d = ui.item("sketchDepth")
    ui.click(d)
    ui.key("Ctrl+A")
    ui.type("40")
    ui.settle(300)
    ui.shot("bracket-1-sketch")
    clear_symbols(ui, "the L profile")
    crop(ui, stage_rect(ui), "sketch-new")
    crop(ui, "sketchCapsule", "sketch-capsule")
    crop(ui, "sketchFoot", "sketch-foot")
    ui.click(ui.item("sketchCommit"))
    ui.wait_until(lambda: ui.store.get("screen") == "work" and ui.js("!!Store.view"), 120, "the bracket open as a design")
    S["pid"] = ui.store.get("pid")
    p = ui.api("/projects/" + S["pid"])
    vals = p["project"]["revisions"][-1]["values"]
    ui.eq({k: vals[k] for k in ("extrude_1_l1", "extrude_1_l2", "extrude_1_l3", "extrude_1_l4", "extrude_1_depth")},
          {"extrude_1_l1": 60, "extrude_1_l2": 40, "extrude_1_l3": 5, "extrude_1_l4": 5, "extrude_1_depth": 40},
          "every typed dimension is a parameter of the design")
    ui.wait_until(lambda: ui.js("!!Store.viewer && !!Store.view && Store.view.volume_mm3 > 0"), 60, "the solid")
    v0 = ui.js("Store.view.volume_mm3")
    ui.check(abs(v0 - (60 * 5 + 35 * 5) * 40) < 1, "the solid the sketch says")
    ui.wait_until(lambda: ui.js("!!Store.viewer && !Store.viewer.revealing") is True, 30, "the build-up to end")
    ui.settle(600)

    ui.hover("viewport", 0.5, 0.3)
    ui.settle(1200)
    S["idle0"] = frames(ui, 2000)
    # a pocket: Cut, the base's top face picked on the part, a rectangle drawn on it, 2 mm deep
    ui.click(ui.item("railCut"))
    ui.wait_until(lambda: ui.js("Store.sketchHost.picking") is True, 3, "Cut waits for a face")
    crop(ui, "sketchCapsule", "sketch-pick")
    top = hits(ui, lambda h: h["normal"][2] > 0.95 and abs(h["at"][2] - 5) < 1e-3 and 10 < h["at"][0] < 30 and -30 < h["at"][1] < -10)
    ui.check(top, "a pixel on the base's top")
    fx, fy, hit = min(top, key=lambda t: abs(t[2]["at"][0] - 16) + abs(t[2]["at"][1] + 20))
    ox, oy = hit["at"][0], hit["at"][1]             # the sketch's origin is the picked point; its x is the part's x
    ui.click("sketchArea", fx, fy)
    sketching(ui, "the sketch on the picked face")
    ui.check("face" in sketch(ui)["plane"], "the plane is the picked face, kept as a query")
    ui.check(ui.js("Store.sketchHost.vp.el") > 85, "the camera looks straight down on the face")
    ui.key("R")
    a, b = px(ui, 8 - ox, -26 - oy), px(ui, 24 - ox, -14 - oy)
    area = ui.item("sketchArea")
    ui.drag("sketchArea", ((b[0] - a[0]) * area.width(), (b[1] - a[1]) * area.height()), a[0], a[1])
    ui.wait_until(lambda: solved(ui).get("closed") and len(sketch(ui)["entities"]) == 4, 10, "a closed rectangle on the face")
    d = ui.item("sketchDepth")
    ui.click(d)
    ui.key("Ctrl+A")
    ui.type("2")
    ui.wait_until(lambda: "mm³" in ui.item("sketchSay").property("text"), 60, "the kernel's preview of the cut")
    ui.check(ui.item("sketchSay").property("text").startswith("−384.0"), f"the preview says what the cut removes: {ui.item('sketchSay').property('text')}")
    ui.settle(300)
    ui.shot("bracket-2-pocket")
    clear_symbols(ui, "the pocket on the face")
    crop(ui, stage_rect(ui), "sketch-face")
    # nothing touched: what the window draws in 2 s with the sketch open, against the same 2 s before it was opened
    # (the keyboard is back on the plane, so no caret is blinking in the depth field)
    ui.run_js("Store.sketchHost.setTool('select')")
    ui.settle(1200)
    n = frames(ui, 2000)
    print(f"SKETCH IDLE: {n} frames in 2 s with a sketch open on a face; {S['idle0']} in 2 s before it was opened", flush=True)
    ui.check(n <= S["idle0"] + 2, f"a sketch open adds no idle redraws: {n} frames in 2 s, {S['idle0']} without it")
    h0 = head(ui)
    ui.click(ui.item("sketchCommit"))
    ui.wait_until(lambda: head(ui) == h0 + 1, 120, "the pocket saved")
    ui.wait_until(lambda: ui.js("Store.project.head") == h0 + 1 and ui.js("!Store.sketchHost.on") is True, 60, "the window on the new revision")
    ui.wait_until(lambda: abs(ui.js("Store.view.volume_mm3") - (v0 - 384)) < 1, 60, "the pocket in the solid")
    ui.settle(900)

    # an M4 clearance hole into the base, picked on its top face
    ui.click(ui.item("railHole"))
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate" and ui.store.get("selMode") == "face" and ui.js("Ws.want") == "hole", 3, "face picking for a hole")
    ui.settle(500)
    top = hits(ui, lambda h: h["normal"][2] > 0.95 and abs(h["at"][2] - 5) < 1e-3 and 35 < h["at"][0] < 50
               and -30 < h["at"][1] < -10)
    ui.check(top, "a pixel on the base's top")
    ui.click("viewport", top[len(top) // 2][0], top[len(top) // 2][1])
    ui.wait_until(lambda: (ui.store.get("selection") or {}).get("items"), 60, "the face analysed")
    ui.wait_until(lambda: ui.item("modelPanel").property("kind") == "hole", 5, "the hole's panel, opened by the tool")
    ui.click_text("M4", within=ui.item("modelPanel"))
    add_from_panel(ui, "hole")
    # a 2 mm fillet on the end edge of the base, picked
    ui.click(ui.item("railRound"))
    ui.wait_until(lambda: ui.store.get("selMode") == "edge" and ui.js("Ws.want") == "fillet", 3, "edge picking for a fillet")
    ui.settle(500)
    end = hits(ui, lambda h: h["normal"][2] > 0.95 and abs(h["at"][2] - 5) < 1e-3 and h["at"][0] > 56)
    ui.check(end, "a pixel at the base's far end")
    x, y, _h = max(end, key=lambda t: t[2]["at"][0])
    ui.click("viewport", x, y)
    it = ui.wait_until(lambda: (ui.store.get("selection") or {}).get("items"), 60, "an edge")[0]
    ui.eq(it["kind"], "edge", "an edge was picked")
    ui.wait_until(lambda: ui.item("modelPanel").property("kind") == "fillet", 5, "the fillet's panel, opened by the tool")
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
    ui.eq(ids, ["extrude_1", "cut_1", "hole_1", "fillet_1"], "four features, each one method in the code")
    ui.check(elapsed < LIMIT_S, f"made in {elapsed:.1f} s, under {LIMIT_S:.0f} s")
    wait_job(ui, S["pid"])
    ui.click(ui.item("railSelect"))
    toasts_gone(ui)
    ui.settle(900)
    ui.shot("bracket-3-made")
    if os.environ.get("FORM_CRAFT_OUT") and ui.win.width() >= 1200:     # pictures with the conversation column open
        ui.run_js("Store.talkOpen = true; Store.talkCalm = false")
        try:
            ui.wait_until(lambda: ui.js("Store.talkCol > 0") is True, 4, "the conversation column")
        except Exception:                           # noqa: BLE001
            print("NOTE: the conversation column did not open; no pictures with it", flush=True)
            return
        ui.settle(900)
        ui.key("S")
        ui.wait_until(lambda: ui.js("Store.sketchHost.picking") is True, 3, "Sketch waits for a face or a plane")
        crop(ui, "toolDock", "dock-design")
        ui.click(ui.item("sketchPlane-XZ"))
        sketching(ui, "a sketch on XZ with the column open")
        ui.key("C")
        a, b = px(ui, 30, 20), px(ui, 38, 20)
        area = ui.item("sketchArea")
        ui.drag("sketchArea", ((b[0] - a[0]) * area.width(), (b[1] - a[1]) * area.height()), a[0], a[1])
        ui.wait_until(lambda: len(sketch(ui)["entities"]) == 1, 5, "a circle")
        ui.key("D")
        plane_click(ui, 38, 20)
        ui.wait_until(lambda: ui.js("Store.sketchHost.editing") >= 0, 5, "its diameter, open to type in")
        ui.settle(300)
        crop(ui, stage_rect(ui), "sketch-column")
        crop(ui, "sketchDimEdit", "sketch-dim-edit", 24)
        ui.key("Escape")
        ui.click(ui.item("sketchCancel"))
        ui.wait_until(lambda: ui.js("!Store.sketchHost.on") is True, 5, "the sketch left")
