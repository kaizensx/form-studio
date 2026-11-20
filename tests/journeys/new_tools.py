"""The 12.3 tools in the window: a screw boss added at a face picked in Annotate (a new revision with the boss as a
feature of the code), the design sliced on every printer and compared in Prove, and a turntable made from the real
mesh. Every number checked here is read back from the engine."""
from pathlib import Path

from _lib import fold, open_project, open_sheet_wait, sheet, toasts_gone, wait_job, printing_on

DATA = "fresh"
S = {}

SOURCE = '''
"""A plate to screw down: a test of the 12.3 tools."""
from build123d import Align, Box
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title, summary = "Mount plate", "A flat plate."
    params = [Param("w", "Width", 60, 60, 60, 1, "mm", "form", "plate")]
    features = [Feature("plate", "Plate", "structure")]

    def build(self, v):
        return [Stage("plate", Box(60, 40, 6, align=(Align.CENTER, Align.CENTER, Align.MIN)))]
'''


def journey_setup(ui):
    printing_on(ui)                      # this journey is about printing: turn it on as someone who prints would
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    d = ui.studio.create_design("Mount plate", SOURCE)
    S["pid"] = d["id"]
    ui.api("/projects/" + d["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["pid"])
    open_project(ui, S["pid"])


def _hits(ui, n=14):
    vp = ui.item("viewport")
    w, h = vp.width(), vp.height()
    out = []
    for j in range(n):
        for i in range(n):
            x, y = w * (0.1 + 0.8 * (i + 0.5) / n), h * (0.1 + 0.8 * (j + 0.5) / n)
            r = ui.js("JSON.stringify(Store.viewer.hitAt(%f, %f))" % (x, y))
            if r and r != "null":
                out.append((x / w, y / h))
    return out


def journey_boss_on_a_face(ui):
    ui.click_text("Annotate")
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate" and ui.store.get("selecting") is True, 3, "the Annotate tool")
    ui.settle(900)
    hs = ui.wait_until(lambda: _hits(ui), 15, "the part under the pointer")
    head0 = ui.api("/projects/" + S["pid"])["project"]["head"]
    picked = None
    for fx, fy in hs:
        ui.js("Store.selClear()")
        ui.click("viewport", fx, fy)
        it = ui.wait_until(lambda: (ui.store.get("selection") or {}).get("items"), 60, "a face")[0]
        if it.get("normal", [0, 0, 0])[2] > 0.99 and abs(it["on"][2] - 6) < 1e-3 and abs(it["on"][0]) < 20 and abs(it["on"][1]) < 10:
            picked = it
            break
    ui.check(picked is not None, "a point on the top of the plate was picked")
    ui.click(ui.item("featureHere"))
    open_sheet_wait(ui, "feature")
    ui.click_text("M4")
    ui.click_text("Heat-set insert")
    ui.wait_until(lambda: ui.sees("Boss wall"), 10, "the boss wall computed")
    ui.wait_until(lambda: ui.sees("Hole Ø 5.60 mm"), 10, "the M4 insert hole")
    ui.settle(500)
    ui.shot("tools-feature-sheet")
    ui.click(ui.item("featureAdd"))
    ui.wait_until(lambda: sheet(ui) is None, 120, "the boss to be built into a new revision")
    p = ui.api("/projects/" + S["pid"])["project"]
    ui.eq(p["head"], head0 + 1, "a new revision")
    fs = ui.api("/projects/" + S["pid"] + "/features")["features"]
    ui.eq([(f["id"], f["size"], f["hole"], f["hole_d"]) for f in fs], [("boss_1", "M4", "insert", 5.6)], "the boss is in the design's source")
    wait_job(ui, S["pid"])
    ui.wait_until(lambda: ui.js("!!Store.view && Store.view.rev === %d" % p["head"]), 60, "the new model in the viewport")
    ui.check("boss_1" in {m["feature"] for m in ui.js("Store.view.mesh")}, "the boss is a feature in the viewport")
    ui.click_text("Select")
    toasts_gone(ui)
    ui.settle(900)
    ui.shot("tools-boss-on-part")


def journey_every_printer(ui):
    ui.key("Ctrl+4")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "the Prove stage")
    ui.settle(500)
    b = ui.item("comparePrinters")
    ui.scroll_to(b)
    ui.click(b)
    r = ui.wait_until(lambda: ui.js("Store.printerCompare"), 600, "every printer sliced")
    ref = ui.api("/projects/%s/slicecompare" % S["pid"])
    ui.eq([(x["id"], x["time_s"], x["filament_g"]) for x in r["rows"]], [(x["id"], x["time_s"], x["filament_g"]) for x in ref["rows"]],
          "the window shows the engine's slices")
    ok = [x for x in r["rows"] if x["status"] == "ok"]
    ui.check(len(ok) >= 1 and all(x["time_s"] > 0 and x["filament_g"] > 0 for x in ok), f"real slices: {[(x['printer'], x['time_s']) for x in ok]}")
    ui.check(r["best"].get("fastest") == min(ok, key=lambda x: x["time_s"])["id"], "the fastest is marked")
    toasts_gone(ui)
    ui.scroll_to(ui.item("printerCompare"), 1.0)
    ui.settle(1500)
    ui.shot("tools-every-printer")


def journey_turntable(ui):
    ui.key("Ctrl+5")
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "the Release stage")
    ui.settle(400)
    fold(ui, "Share")
    b = ui.item("openTurntable")
    ui.scroll_to(b)
    ui.click(b)
    open_sheet_wait(ui, "turntable")
    ui.click_text("24")
    ui.click(ui.item("turntableMake"))
    ui.wait_until(lambda: ui.find("turntableSave") is not None, 300, "the turntable rendered")
    f = ui.wait_until(lambda: [x for x in (Path(ui.studio.dir(S["pid"])) / "artifacts" / "motion").glob("*.webp")], 10, "the WebP on disk")[0]
    ui.check(f.stat().st_size > 10000, f"a turntable of {f.stat().st_size} bytes")
    from PIL import Image
    with Image.open(f) as im:
        ui.eq(im.n_frames, 24, "one frame per step of the turn")
    ui.expect("24 frames")
    ui.settle(1200)
    ui.shot("tools-turntable")
