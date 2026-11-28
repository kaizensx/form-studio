"""The viewport's tools, from the rail and from their keys: select, measure, section, analyze, assembly, history,
print simulation, photo render."""
import os

from _lib import has_slicer, make, open_project, open_sheet_wait, close_sheet_esc, printing_on, dock

DATA = "fresh"
S = {}


def tool(ui):
    return ui.js("Ws.tool")


def box(it):
    """An item's rectangle in window pixels: (left, top, right, bottom)."""
    from PySide6.QtCore import QPointF
    p = it.mapToScene(QPointF(0, 0))
    return (p.x(), p.y(), p.x() + it.width(), p.y() + it.height())


def journey_setup(ui):
    printing_on(ui)                      # this journey is about printing: turn it on as someone who prints would
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["box"] = make(ui, "enclosure", "Tool box", open=False, purpose="print")
    S["hinged"] = make(ui, "hinged_box", "Hinged box", open=False, purpose="print")
    # a second revision, so the history has something to play
    spec = [p for p in ui.api("/projects/" + S["box"])["recipe"]["params"] if p["key"] == "wall"][0]
    ui.api("/projects/" + S["box"] + "/commit", {"values": {"wall": spec["default"] + 0.6}, "provenance": {}, "note": "thicker wall", "origin": "user"})
    from _lib import wait_job
    wait_job(ui, S["box"])
    open_project(ui, S["box"])


def journey_select_and_views(ui):
    ui.eq(tool(ui), "select")
    for name, key in (("front", "2"), ("side", "3"), ("top", "4"), ("under", "5"), ("iso", "1")):
        ui.key(key)
        ui.wait_until(lambda: ui.store.get("viewName") == name, 3, f"key {key} to show the {name} view")
    for fx, fy, name in ((0.38, 0.62, "front"), (0.5, 0.36, "top"), (0.5, 0.94, "iso")):      # a face of the view cube; its rim is Iso
        ui.wait(450)                                   # not a double click
        ui.click("viewCube", fx, fy)
        ui.wait_until(lambda: ui.store.get("viewName") == name, 3, f"the cube's {name} view")
    ui.settle(500)
    # orbit by dragging: the camera moves, nothing is selected
    az0 = ui.item("viewport").property("az")
    ui.drag("viewport", (140, 30), fx=0.55, fy=0.25)             # in the open room, clear of the panes
    ui.check(abs(ui.item("viewport").property("az") - az0) > 1, "dragging orbits the camera")
    ui.eq(ui.store.get("feature"), "", "a drag does not select")
    # zoom with the wheel
    d0 = ui.item("viewport").property("dist")
    ui.wheel("viewport", 240)
    ui.wait_until(lambda: abs(ui.item("viewport").property("dist") - d0) > 1e-3, 3, "the wheel to zoom")
    ui.key("F")
    ui.settle(500)
    ui.key("1")
    ui.settle(500)
    # the two view switches on the rail
    dock(ui, "Hide overall dimensions")
    ui.wait_until(lambda: ui.store.get("dims") is False, 2, "dimensions to hide")
    dock(ui, "Show overall dimensions")
    ui.wait_until(lambda: ui.store.get("dims") is True, 2, "dimensions to show")


def room(ui, u, v):
    """A point of the open room (the part of the 3D view no pane covers, where the camera keeps the part) as
    fractions of the whole view: (0, 0) is its top left, (1, 1) its bottom right."""
    vp = ui.item("viewport")
    l, t, r, b = (float(vp.property(k)) for k in ("insetLeft", "insetTop", "insetRight", "insetBottom"))
    return (l + u * (vp.width() - l - r)) / vp.width(), (t + v * (vp.height() - t - b)) / vp.height()


def journey_measure(ui):
    ui.key("M")
    ui.wait_until(lambda: tool(ui) == "measure" and ui.store.get("measuring") is True, 3, "M to start measuring")
    ui.key("V")
    ui.wait_until(lambda: tool(ui) == "select" and ui.store.get("measuring") is False, 3, "V to go back to Select")
    ui.click_text("Measure")
    ui.wait_until(lambda: ui.store.get("measuring") is True, 3, "the Measure rail button")
    # the enclosure is two parts laid out for printing, framed whole: a point can land in the gap between them
    def hit(points, cond, what):
        for u, v in points:
            ui.click("viewport", *room(ui, u, v))
            try:
                return ui.wait_until(cond, 4, what)
            except Exception:
                continue
        return ui.wait_until(cond, 6, what)
    hit(((0.45, 0.58), (0.47, 0.45), (0.42, 0.38)), lambda: ui.store.get("measureFrom") is not None, "the first point")
    ui.expect("Click the second point")
    m = hit(((0.58, 0.68), (0.62, 0.76), (0.52, 0.74)), lambda: ui.store.get("measures"), "a measurement after two clicks")[0]
    ui.eq(m["kind"], "distance")
    mm = float(m["label"].split()[0])
    bb = ui.js("Store.view.bbox")
    diag = sum((bb[1][i] - bb[0][i]) ** 2 for i in range(3)) ** 0.5
    ui.check(0.5 < mm <= diag + 0.5, f"a plausible distance: {mm} mm on a part with a {diag:.0f} mm diagonal")
    ui.eq(ui.store.get("feature"), "", "measuring does not select features")
    ui.expect(m["label"])
    ui.click_text("Face")
    ui.wait_until(lambda: ui.store.get("measureKind") == "face", 2, "face mode")
    # the enclosure is two parts laid out for printing; a single point can land in the gap between them
    for u, v in ((0.45, 0.58), (0.58, 0.68), (0.47, 0.45)):
        ui.click("viewport", *room(ui, u, v))
        try:
            ui.wait_until(lambda: len(ui.store.get("measures")) == 2, 5, "a face measurement")
            break
        except Exception:
            continue
    ui.wait_until(lambda: len(ui.store.get("measures")) == 2, 5, "a face measurement")
    f = ui.store.get("measures")[1]
    ui.check(f["kind"] == "face" and f["face"]["area_mm2"] > 0, f"a face with an area: {f['label']}")
    ui.settle(300)
    ui.shot("tools-measure")
    ui.click_text("Clear")
    ui.wait_until(lambda: ui.store.get("measures") == [], 2, "Clear to remove the measurements")
    ui.key("Escape")
    ui.wait_until(lambda: tool(ui) == "select" and ui.store.get("measuring") is False, 3, "Esc to leave the measure tool")


def journey_section(ui):
    ui.click_text("Section")
    ui.wait_until(lambda: tool(ui) == "section" and (ui.store.get("section") or {}).get("axis") == "y", 3, "a Y cut from the Section button")
    bar = ui.item("sectionBar")
    for axis in ("X", "Z", "Y"):
        ui.click_text(axis, within=bar)
        ui.wait_until(lambda: ui.store.get("section")["axis"] == axis.lower(), 2, f"the {axis} cut")
        ui.wait_until(lambda: ui.item("viewport").property("clipOn") is True, 3, "the viewport to cut the part")
    t0 = ui.store.get("section")["t"]
    beam = [b for b in ui.find_all(within=bar) if b.metaObject().className().startswith("Beam")][0]
    ui.drag(beam, (30, 0))
    ui.wait_until(lambda: ui.store.get("section")["t"] > t0 + 0.1, 2, "the cut to move with the slider")
    ui.settle(400)
    ui.shot("tools-section")
    ui.click_text("Remove cut")
    ui.wait_until(lambda: not (ui.store.get("section") or {}).get("axis"), 2, "the cut to be removed")
    ui.wait_until(lambda: tool(ui) == "select", 2, "Select again")
    ui.key("X")
    ui.wait_until(lambda: tool(ui) == "section", 3, "X to start a section")
    ui.key("X")
    ui.wait_until(lambda: tool(ui) == "select", 3, "X again to hand back to Select")
    ui.run_js('Store.setSection("", 0.5)')


def journey_analyze(ui):
    ui.key("A")
    ui.wait_until(lambda: tool(ui) == "analyze", 3, "A to open Analyze")
    bar = ui.item("analyzeBar")
    for label, mid in (("Thickness", "thickness"), ("Overhang", "overhang"), ("Section", "section"), ("Features", "features")):
        ui.click_text(label, within=bar)
        ui.wait_until(lambda: ui.store.get("analysisMap") == mid, 2, f"the {label} map to be asked for")
        ui.wait_until(lambda: ui.js("!!Store.analysis && Store.analysis.map === %r && !Store.analysisBusy" % mid), 120, f"the {label} map to load")
        legend = ui.item("resultStrip")
        ui.check(len(ui.texts(legend)) >= 3, f"the {label} legend shows")
        ui.wait_until(lambda: ui.item("viewport").property("mapShown") is True, 5, "the map on the part")
        ui.settle(500)
        # a marker's label never sits on a dimension number
        pins, dims = [box(p) for p in ui.find_all(name="pinLabel")], [box(d) for d in ui.find_all(name="dimLabel")]
        for p in pins:
            for d in dims:
                ui.check(not (p[0] < d[2] and d[0] < p[2] and p[1] < d[3] and d[1] < p[3]), f"a {label} marker label sits on a dimension: {p} {d}")
        ui.shot("tools-analyze-" + mid)
    ui.click_text("Clear map")
    ui.wait_until(lambda: ui.store.get("analysisMap") == "" and ui.store.get("analysis") is None, 2, "the map to clear")
    ui.key("V")


def journey_history(ui):
    dock(ui, "History")
    ui.wait_until(lambda: ui.store.get("timelineOpen") is True and tool(ui) == "history", 3, "the timeline")
    ui.settle(300)
    track = ui.item("timelineTrack")
    def at_r01():
        return (ui.store.get("scrub") or {}).get("rev") == 1
    for attempt in range(3):          # a synthetic drag is sometimes dropped by a virtual display: drag again
        ui.drag(track, (-track.width() * 0.9, 0), fx=0.97)
        try:
            ui.wait_until(at_r01, 30, "scrubbing to r01")
            break
        except Exception:
            if attempt == 2:
                raise
            print("  (drag did not register; trying again)")
    ui.expect("Back to head")
    ui.click_text("Back to head")
    ui.wait_until(lambda: ui.store.get("scrub") is None, 20, "back to the head")
    ui.click("timelinePlay")
    ui.wait_until(lambda: ui.store.get("morphing") is True, 5, "the history to play")
    seen = set()
    def played():
        s = ui.store.get("scrub")
        if s:
            seen.add(s["rev"])
        return ui.store.get("morphing") is False
    ui.wait_until(played, 60, "the history to finish playing")
    ui.check(1 in seen, f"the earlier revision was shown while playing: {seen}")
    ui.key("T")
    ui.wait_until(lambda: ui.store.get("timelineOpen") is False and ui.store.get("scrub") is None, 20, "T to close the timeline")


def journey_simulate(ui):
    if not has_slicer(ui):
        print("  (no slicer on this machine: print simulation not exercised)")
        return
    ui.wait_until(lambda: ui.js("!!Store.data.slice"), 300, "a current slice")
    dock(ui, "Simulate the print")
    ui.wait_until(lambda: ui.store.get("layers") is not None, 60, "the simulation to open")
    sim = ui.item("printSim")
    ui.wait_until(lambda: sim.property("count") > 0, 120, "the toolpaths to load")
    ui.wait_until(lambda: sim.property("playing") is True, 10, "it to start playing")
    n0 = sim.property("now")
    ui.wait_until(lambda: sim.property("now") > n0, 10, "the nozzle to advance")
    ui.click_text("Pause")
    ui.wait_until(lambda: sim.property("playing") is False, 3, "Pause")
    n1 = sim.property("now")
    ui.wait(300)
    ui.eq(sim.property("now"), n1, "paused means still")
    for label, v in (("1×", 1), ("16×", 16), ("4×", 4)):
        ui.click_text(label)
        ui.wait_until(lambda: sim.property("speed") == v, 2, f"speed {label}")
    # scrub the layer slider to about the middle
    ui.click("simLayers", 0.5, 0.5)
    ui.wait_until(lambda: abs(sim.property("cur") - sim.property("count") / 2) < sim.property("count") * 0.15 + 2, 3, "the layer scrubber")
    ui.click("simAlong", 0.5, 0.5)
    ui.wait_until(lambda: 0.3 < sim.property("frac") < 0.7, 3, "the along-the-layer scrubber")
    # line-type filters
    types = sim.property("types")
    types = types.toVariant() if hasattr(types, "toVariant") else types
    first = ui.find_all(name="simType")[0]
    ui.click(first)
    ui.wait_until(lambda: len(_hidden(sim)) == 1, 2, "a line type to hide")
    ui.click_text("All")
    ui.wait_until(lambda: len(_hidden(sim)) == 0, 2, "All to show every line type")
    info = sim.property("info")
    info = info.toVariant() if hasattr(info, "toVariant") else info
    if info.get("bridge_layers"):
        ui.click_text("Next bridge")
        ui.wait_until(lambda: sim.property("cur") in [int(x) for x in info["bridge_layers"]], 3, "Next bridge to jump to a bridge layer")
    # (in 3D, as it was framed when it opened) a view panned and zoomed is the person's until the stage changes; then the print is framed in its middle again
    view = ui.item("printSimView")
    def cam():
        t = view.property("target")
        return (round(t.x(), 1), round(t.y(), 1), round(t.z(), 1), round(view.property("dist")))
    home = cam()
    ui.drag("printSimView", (70, 40), 0.5, 0.45, button="right")
    ui.wheel("printSimView", 240, 0.5, 0.45)
    ui.settle(500)
    ui.check(cam() != home, "a pan and a zoom move the print simulation's camera")
    ui.run_js("Store.paneFolded = true")
    ui.wait_until(lambda: cam() == home, 6, "the print to be framed again once the pane has folded")
    ui.run_js("Store.paneFolded = false")
    ui.settle(900)
    for label, mode in (("Layer", "2d"), ("Copies", "plate"), ("3D", "3d")):
        ui.click_text(label, within=sim)
        ui.wait_until(lambda: sim.property("mode") == mode, 3, f"the {label} mode")
        ui.settle(500)
    ui.click_text("Play")
    ui.wait_until(lambda: sim.property("playing") is True, 3, "Play")
    ui.settle(700)
    ui.shot("tools-simulate")
    ui.click_text("Pause")
    ui.click_text("Back to the design")
    ui.wait_until(lambda: ui.store.get("layers") is None, 3, "back to the design")
    ui.settle(400)


def _hidden(sim):
    h = sim.property("hidden")
    h = h.toVariant() if hasattr(h, "toVariant") else h
    return [k for k, v in (h or {}).items() if v]


def journey_photo_render_sheet(ui):
    dock(ui, "Photo render")
    open_sheet_wait(ui, "render")
    rs = ui.item("renderSheet")
    ui.wait_until(lambda: rs.property("st") is not None, 30, "the render sheet to load what Blender it has")
    card = ui.item("sheetCard")
    btn = ui.wait_until(lambda: next((b for b in ui.find_all(within=card) if b.metaObject().className().startswith("Btn")
                                      and b.property("text") in ("Render", "Render again")), None), 5, "the Render button")
    ui.shot("tools-render-sheet")
    if not rs.property("ready"):
        print("  (Blender is not installed: the Render button is off, as it should be)")
        ui.check(btn.property("enabled") is False, "Render is off without Blender")
        return close_sheet_esc(ui)
    ui.check(btn.property("enabled") is True, "Render is on when Blender is installed")
    if os.environ.get("FORM_UI_RENDER") != "1":
        print("  (set FORM_UI_RENDER=1 to make one real Blender render)")
        return close_sheet_esc(ui)
    # one real render, with Fast preview ticked
    ui.click_text("Fast preview", within=card)
    ui.wait_until(lambda: rs.property("fast") is True, 2, "Fast preview")
    ui.click(btn)
    ui.wait_until(lambda: rs.property("busy") is True or rs.property("shown") is not None, 10, "the render to be asked for")
    ui.wait_until(lambda: rs.property("busy") is False, 600, "Blender to finish")
    err = rs.property("error")
    ui.check(not (err.toVariant() if hasattr(err, "toVariant") else err), f"the render finished without an error: {err}")
    latest = ui.api("/projects/" + ui.store.get("pid") + "/photo")["latest"]
    ui.check(latest and latest["samples"] > 0, f"the engine has a render: {latest}")
    ui.settle(800)
    ui.shot("tools-render-done")
    close_sheet_esc(ui)


def journey_assembly(ui):
    open_project(ui, S["hinged"])
    ui.check(ui.store.get("assembly") is not None, "the hinged box is an assembly")
    ui.key("E")
    ui.wait_until(lambda: tool(ui) == "assembly", 3, "E to open Assembly")
    bar = ui.item("asmBar")
    ui.click_text("Exploded", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "exploded", 3, "exploded mode")
    ui.settle(600)
    e0 = ui.store.get("explode")
    spread = [h for h in ui.find_all(text="Spread", within=bar) if h.property("from") is not None][0]
    beam = [b for b in ui.find_all(within=spread) if b.metaObject().className().startswith("Beam")][0]
    ui.click(beam, 0.9, 0.5)
    ui.wait_until(lambda: ui.store.get("explode") > e0 + 0.1, 2, "the spread slider")
    ui.settle(500)
    ui.shot("tools-assembly-exploded")
    ui.click_text("Assembled", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "assembled", 3, "assembled mode")
    joints = ui.js("Store.assembly.joints")
    ui.check(len(joints) >= 1, "the hinged box has a joint")
    j = joints[0]
    slider = [h for h in ui.find_all(text=j["label"], within=bar) if h.property("from") is not None][0]
    beam = [b for b in ui.find_all(within=slider) if b.metaObject().className().startswith("Beam")][0]
    ui.click(beam, 0.8, 0.5)
    ui.wait_until(lambda: abs((ui.store.get("pose") or {}).get(j["id"], 0)) > 1, 2, f"the {j['label']} slider to move the joint")
    ui.settle(600)
    ui.shot("tools-assembly-hinge")
    ui.click_text("Print layout", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "print", 3, "print layout")
    ui.key("V")
