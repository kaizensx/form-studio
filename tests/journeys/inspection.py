"""Inspecting a design: measuring on multi-part designs in every view (print layout, assembled, exploded), the
Annotate tool (pick, paint, lasso, keep, ask the agent), and colours and materials. Real clicks on the real part:
the pixels to click are found by asking the viewport what is under them, part by part."""
import json
import zipfile

from _lib import make, open_project, wait_job, printing_on

DATA = "fresh"
S = {}


def tool(ui):
    return ui.js("Ws.tool")


def hits(ui, n=18):
    """Pixels (as fractions of the viewport) that land on each part: { part id: [(fx, fy), ...] }."""
    vp = ui.item("viewport")
    w, h = vp.width(), vp.height()
    out = {}
    for j in range(n):
        for i in range(n):
            x, y = w * (0.08 + 0.84 * (i + 0.5) / n), h * (0.08 + 0.84 * (j + 0.5) / n)
            r = ui.js("JSON.stringify(Store.viewer.hitAt(%f, %f))" % (x, y))
            r = json.loads(r) if r and r != "null" else None
            if r:
                out.setdefault(r["part"], []).append((x / w, y / h))
    return out


def two_parts(ui):
    ui.settle(900)                              # the camera glides when the dock opens or closes
    hs = ui.wait_until(lambda: hits(ui), 15, "the part under the pointer somewhere")   # a rebuilt model can be swapping in
    parts = sorted(hs, key=lambda k: -len(hs[k]))
    a, b = parts[0], parts[1] if len(parts) > 1 else parts[0]
    return hs[a][len(hs[a]) // 2], hs[b][len(hs[b]) // 2], a, b


def journey_setup(ui):
    printing_on(ui)                      # this journey is about printing: turn it on as someone who prints would
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    S["hinged"] = make(ui, "hinged_box", "Hinged box", open=False)
    S["gears"] = make(ui, "gear_pair", "Gear pair", open=False)
    S["box"] = make(ui, "enclosure", "Enclosure", open=False)
    from form.design_guide import EXAMPLE
    d = ui.studio.create_design("Two bodies", EXAMPLE.split("    def assembly(self, v):")[0])
    S["bodies"] = d["id"]
    ui.api("/projects/" + d["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["bodies"])


def measure_in(ui, mode):
    if mode:
        ui.run_js("Store.setAsmMode(%r)" % mode)
        ui.wait_until(lambda: ui.store.get("asmMode") == mode, 3, mode)
        ui.settle(1200)
    ui.click_text("Distance", within=ui.item("measureBar"))
    ui.run_js("Store.clearMeasures()")
    a, b, pa, pb = two_parts(ui)
    ui.click("viewport", *a)
    ui.wait_until(lambda: ui.store.get("measureFrom") is not None, 60, f"the first point ({mode or 'as opened'})")
    ui.click("viewport", *b)
    m = ui.wait_until(lambda: ui.store.get("measures"), 60, f"a distance ({mode or 'as opened'})")[0]
    ui.eq(m["kind"], "distance")
    ui.eq((m["pa"], m["pb"]), (pa, pb), "each end knows its part")
    ui.check(float(m["label"].split()[0]) > 0.1, f"a distance: {m['label']}")
    ui.eq(ui.store.get("asmMode"), mode or ui.store.get("asmMode"), "measuring keeps the view it was started in")
    ui.click_text("Face", within=ui.item("measureBar"))
    a, _b, pa, _pb = two_parts(ui)
    ui.click("viewport", *a)
    ui.wait_until(lambda: len(ui.store.get("measures")) == 2, 60, f"a face ({mode or 'as opened'})")
    f = ui.store.get("measures")[1]
    ui.check(f["face"]["area_mm2"] > 0 and f["part"] == pa, f"a face on {pa}: {f['label']}")
    ui.eq(len(ui.js("Store.viewer.shownMeasures")), 2, "both are drawn")


def diameter(ui):
    """Click around until a hole or round boss answers with a diameter."""
    ui.click_text("Diameter", within=ui.item("measureBar"))
    ui.settle(900)
    hs = hits(ui, 22)
    n0 = len(ui.store.get("measures"))
    for part, pts in sorted(hs.items(), key=lambda kv: -len(kv[1])):
        for pt in pts[::3]:
            ui.click("viewport", *pt)
            ui.wait_until(lambda: ui.store.get("measureBusy") == 0, 30, "the engine")
            ms = ui.store.get("measures")
            if len(ms) > n0:
                return ms[-1]
    return None


def journey_measure_on_parts_in_every_view(ui):
    for key in ("hinged", "gears", "box"):
        open_project(ui, S[key])
        ui.check(ui.store.get("assembly") is not None, f"{key} is several parts")
        ui.click_text("Measure")
        ui.wait_until(lambda: tool(ui) == "measure", 3, "the Measure tool")
        for mode in ("print", "assembled", "exploded"):
            measure_in(ui, mode)
        ui.shot(f"inspect-measure-{key}-exploded")
        ui.run_js("Store.setAsmMode('print')")
        ui.settle(1200)
        if key in ("hinged", "gears"):
            d = diameter(ui)
            ui.check(d is not None and d["kind"] == "diameter", f"a diameter on the {key}")
            ui.check(d["label"].startswith("Ø"), d["label"])
        ui.click_text("Select")
        ui.wait_until(lambda: tool(ui) == "select" and ui.store.get("measuring") is False, 3, "Select leaves measuring")


def journey_two_bodies_say_what_they_cannot_show(ui):
    open_project(ui, S["bodies"])
    ui.check(ui.js("Store.assembly.derived") is True, "two bodies with no declaration")
    ui.click_text("Assembly")
    ui.wait_until(lambda: tool(ui) == "assembly", 3, "the Assembly tool")
    bar = ui.item("asmBar")
    ui.expect("Exploded", within=bar)
    ui.expect("As modelled", within=bar)
    ui.click_text("Assembled", within=bar)                 # shown, but off: it cannot be placed
    ui.settle(300)
    ui.check(ui.store.get("asmMode") != "assembled", "Assembled cannot be picked for undeclared parts")
    ui.check(ui.exists("asmDerivedNote"), "the bar says why")
    ui.click_text("Ask the agent to add it", within=bar)
    ui.wait_until(lambda: "assembly()" in (ui.js("Store.chatRecall") or ""), 3, "the request in the composer")
    ui.click_text("Exploded", within=bar)
    ui.wait_until(lambda: ui.store.get("asmMode") == "exploded", 3, "exploded")
    ui.click_text("Measure")
    ui.wait_until(lambda: tool(ui) == "measure", 3, "the Measure tool")
    measure_in(ui, "exploded")
    ui.shot("inspect-two-bodies-exploded")
    ui.click_text("Select")


def journey_annotate(ui):
    pid = S["hinged"]
    open_project(ui, pid)
    ui.click_text("Annotate")
    ui.wait_until(lambda: tool(ui) == "annotate" and ui.store.get("selecting") is True, 3, "the Annotate tool")
    a, b, pa, pb = two_parts(ui)
    ui.click("viewport", *a)                                # Face is the default
    ui.wait_until(lambda: len((ui.store.get("selection") or {}).get("items", [])) == 1, 60, "a face")
    ui.click_text("Edge", within=ui.item("annotateBar"))
    a, b, pa, pb = two_parts(ui)
    ui.click("viewport", *b, mods="shift")
    ui.wait_until(lambda: len((ui.store.get("selection") or {}).get("items", [])) == 2, 60, "Shift adds an edge")
    ui.click_text("Brush", within=ui.item("annotateBar"))
    a, b, pa, pb = two_parts(ui)
    ui.stroke("viewport", [(16, 3), (32, 8), (48, 10)], fx=a[0], fy=a[1], mods="shift")
    sel = ui.wait_until(lambda: [x for x in (ui.store.get("selection") or {}).get("items", []) if x["kind"] == "region"], 60, "a painted region")
    ui.check(sel[0]["area_mm2"] > 1 and sel[0]["mode"] == "brush", f"a painted area: {sel[0].get('area_mm2')} mm²")
    kinds = [x["kind"] for x in ui.store.get("selection")["items"]]
    ui.eq(kinds[:2], ["face", "edge"], "the stroke was added to what was picked")
    ui.expect("Ask the agent", within=ui.item("selectionPanel"))
    ui.shot("inspect-annotate-selection")
    ui.click_text("Lasso", within=ui.item("annotateBar"))
    a, b, pa, pb = two_parts(ui)
    ui.stroke("viewport", [(36, -8), (60, 18), (44, 52), (0, 44), (-8, 10)], fx=a[0] - 0.03, fy=a[1] - 0.02)
    ui.wait_until(lambda: any(x.get("mode") == "lasso" for x in (ui.store.get("selection") or {}).get("items", [])), 60, "a lasso region")
    # keep it, with a name and a note
    ui.click(ui.item("keepSelection"))
    ui.settle(300)
    ui.click(ui.item("annName"))
    ui.type("Lid corner")
    ui.click(ui.item("annNote"))
    ui.type("Is the wall thick enough here?")
    ui.key("Return")
    ui.wait_until(lambda: len(ui.js("Store.annotations") or []) == 1, 30, "the annotation kept")
    kept = ui.api("/projects/" + pid + "/annotations")["annotations"]
    ui.eq((kept[0]["name"], kept[0]["note"], kept[0]["rev"]), ("Lid corner", "Is the wall thick enough here?", ui.js("Store.project.head")))
    ui.check(kept[0]["analysis"]["items"][0]["area_mm2"] > 1, "kept with its numbers")
    ui.wait_until(lambda: any("Lid corner" in (p.property("modelData") or {}).get("text", "") for p in ui.find_all("pinLabel")), 10, "its pin")
    ui.settle(500)
    ui.click(ui.item("askAnnotation"))
    ui.wait_until(lambda: "Lid corner" in (ui.js("Store.chatRecall") or "") and "area" in ui.js("Store.chatRecall"), 10, "the composer gets the numbers")
    ui.check(ui.store.get("talkOpen") is True, "the conversation opens")
    ui.shot("inspect-annotate-kept")
    # it rides along when the parts move, and survives reopening the design
    ui.run_js("Store.setAsmMode('exploded')")
    ui.settle(1500)
    ui.shot("inspect-annotate-exploded")
    ui.run_js("Store.setAsmMode('print')")
    ui.click_text("Select")
    ui.wait_until(lambda: ui.store.get("selecting") is False, 3, "Select leaves annotating")
    open_project(ui, S["gears"])
    open_project(ui, pid)
    ui.wait_until(lambda: any("Lid corner" in (p.property("modelData") or {}).get("text", "") for p in ui.find_all("pinLabel")), 10, "the pin after reopening")
    pin = [p for p in ui.find_all("pinLabel") if "Lid corner" in (p.property("modelData") or {}).get("text", "")][0]
    ui.click(pin)
    ui.wait_until(lambda: (ui.store.get("annFocus") or {}).get("analysis") is not None, 30, "the pin opens the annotation")
    ui.click_text("Delete", within=ui.item("selectionPanel"))
    ui.wait_until(lambda: ui.api("/projects/" + pid + "/annotations")["annotations"] == [], 10, "deleted")


def journey_colours_and_materials(ui):
    pid = S["hinged"]
    open_project(ui, pid)
    ui.run_js("Store.setStage('shape')")
    ui.settle(500)
    ui.scroll_to(ui.item("appearance"), 0.1)
    ui.click(ui.item("look-design"), 0.5, 0.1)
    ui.settle(300)
    ui.click(ui.item("swatch-#3f7fbf"))
    ui.wait_until(lambda: (ui.js("Store.appearance.color") or "") == "#3f7fbf", 10, "the design colour")
    ui.click(ui.item("materialPick"))
    ui.settle(300)
    ui.click_text("PETG")
    ui.wait_until(lambda: ui.js("Store.appearance.material") == "PETG", 10, "the material")
    ui.eq(ui.api("/projects/" + pid)["project"]["material"], "PETG", "kept where the slicer reads it")
    # the material re-runs the checks and the panel redraws: open the lid's row only once it holds still, and make
    # sure it is the one open before picking its colour
    ui.wait_until(lambda: ui.js("Store.activity.length") == 0, 120, "the checks to finish")
    from _lib import wait_job
    wait_job(ui, pid)                                  # a material re-slices; changes wait for the running pipeline
    for _ in range(3):
        ui.settle(300)
        ui.click(ui.item("look-lid"), 0.5, 0.1)
        try:
            ui.wait_until(lambda: ui.item("appearance").property("open") == "lid", 4, "the lid's row to open")
            break
        except Exception:
            continue
    ui.settle(300)
    ui.click(ui.item("swatch-#e08a2c"))
    ui.wait_until(lambda: ((ui.js("Store.appearance.parts") or {}).get("lid") or {}).get("color") == "#e08a2c", 10, "the lid's colour")
    ui.eq(ui.js("Store.viewer.colorOf('lid')"), "#e08a2c", "the viewport draws the lid in its colour")
    ui.eq(ui.js("Store.viewer.colorOf('body')"), "#3f7fbf", "and the body in the design's")
    ui.settle(600)
    ui.shot("inspect-colours")
    wait_job(ui, pid)
    rows = [c for c in ui.api("/projects/" + pid)["checks"]["checks"] if c["id"].startswith("material_")]
    ui.check(rows and rows[0]["evidence"] == "heuristic", f"the material is in the checks: {rows}")
    ui.scroll_to(ui.item("save3mf"), 0.5)
    ui.click(ui.item("save3mf"))
    f = ui.saved(pid + "-colours.3mf", 120)
    model = zipfile.ZipFile(f).read("3D/3dmodel.model").decode()
    ui.check('displaycolor="#E08A2CFF"' in model and 'displaycolor="#3F7FBFFF"' in model, "the 3MF carries both colours")
    ui.no_warnings()
