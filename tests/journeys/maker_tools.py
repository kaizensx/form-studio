"""The 12.1 maker tools in the window: text on a face picked in Annotate (a new revision with a text feature), the
geometric diff between that revision and the one before (added material, computed on the solids), and assembly
instructions as a PDF from the assembly declaration. Every number checked here is read back from the engine."""
from _lib import fold, open_project, open_sheet_wait, sheet, toasts_gone, wait_job, mode_key

DATA = "fresh"
S = {}

SOURCE = '''
"""A box with a lid: a test of the maker tools."""
from build123d import Align, Box, Pos
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Lid box", "A base and a lid that presses on."
    solids = 2
    params = [Param("w", "Width", 50, 50, 50, 1, "mm", "form", "base")]
    features = [Feature("base", "Base", "structure"), Feature("lid", "Lid", "structure")]

    def build(self, v):
        s = Box(50, 50, 20, align=A)
        st = [Stage("base", s)]
        s = s + Pos(70, 0, 0) * Box(50, 50, 4, align=A)
        st.append(Stage("lid", s))
        return st

    def assembly(self, v):
        return Assembly(parts=[Part("base", "Base", 0, note="Stand the base on the table."),
                               Part("lid", "Lid", 1, move=(-70, 0, 20), explode=(0, 0, 30), attach="base",
                                    note="Press the lid onto the base.")])
'''


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    d = ui.studio.create_design("Lid box", SOURCE)
    S["pid"] = d["id"]
    ui.api("/projects/" + d["id"] + "/run", {"nodes": [], "force": False})
    wait_job(ui, S["pid"])
    open_project(ui, S["pid"])


def _hits(ui, n=16):
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


def journey_text_on_a_face(ui):
    ui.click_text("Annotate")
    ui.wait_until(lambda: ui.js("Ws.tool") == "annotate" and ui.store.get("selecting") is True, 3, "the Annotate tool")
    ui.settle(900)
    hs = ui.wait_until(lambda: _hits(ui), 15, "the part under the pointer")
    head0 = ui.api("/projects/" + S["pid"])["project"]["head"]
    picked = None
    for fx, fy in hs:          # the first face that points up, on the base: room for the text
        ui.js("Store.selClear()")
        ui.click("viewport", fx, fy)
        it = ui.wait_until(lambda: (ui.store.get("selection") or {}).get("items"), 60, "a face")[0]
        if it.get("normal", [0, 0, 0])[2] > 0.99 and abs(it["on"][2] - 20) < 1e-3 and abs(it["on"][0]) < 14 and abs(it["on"][1]) < 14:
            picked = it
            break
    ui.check(picked is not None, "a point on the top of the base was picked")
    ui.expect("Text here…", within=ui.item("selectionPanel"))
    ui.click(ui.item("textHere"))
    open_sheet_wait(ui, "text")
    ui.click(ui.item("textWords"))
    ui.type("BOX 1")
    ui.wait_until(lambda: ui.sees("Computed on the glyphs."), 10, "printability computed on the glyphs")
    ui.settle(600)
    ui.shot("maker-text-sheet")
    ui.click(ui.item("textAdd"))
    ui.wait_until(lambda: sheet(ui) is None, 120, "the text to be built into a new revision")
    p = ui.api("/projects/" + S["pid"])["project"]
    ui.eq(p["head"], head0 + 1, "a new revision")
    marks = ui.api("/projects/" + S["pid"] + "/text")["marks"]
    ui.eq([m["text"] for m in marks], ["BOX 1"], "the text is in the design's source")
    ui.check(abs(marks[0]["at"][2] - 20) < 1e-3, "at the picked point")
    wait_job(ui, S["pid"])
    ui.wait_until(lambda: ui.js("!!Store.view && Store.view.rev === %d" % p["head"]), 60, "the new model in the viewport")
    feats = {m["feature"] for m in ui.js("Store.view.mesh")}
    ui.check("text_1" in feats, "the text is a feature in the viewport")
    ui.click_text("Select")
    toasts_gone(ui)
    ui.settle(900)
    ui.shot("maker-text-on-part")


def journey_geometric_diff(ui):
    ui.key(mode_key(3))
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "the Release stage")
    ui.settle(500)
    btn = ui.item(text="Compare with head")
    ui.scroll_to(btn)
    ui.click(btn)
    g = ui.wait_until(lambda: ui.js("Store.compare && Store.compare.geo"), 300, "the solids compared in the kernel")
    ref = ui.api("/projects/%s/geomdiff?a=1" % S["pid"])
    ui.eq((g["key"], g["added"]["volume_mm3"], g["removed"]["volume_mm3"]), (ref["key"], ref["added"]["volume_mm3"], ref["removed"]["volume_mm3"]), "the window shows the engine's diff")
    ui.check(g["added"]["volume_mm3"] > 1 and g["removed"]["regions"] == 0, f"text added {g['added']['volume_mm3']} mm³, nothing removed")
    ui.check(g["added"]["regions"] >= 4, f"one region per glyph ({g['added']['regions']})")
    box = ui.item("geoDiff")
    ui.scroll_to(box, 1.0)
    ui.settle(1200)
    ui.shot("maker-geometric-diff")


def journey_assembly_instructions(ui):
    fold(ui, "Maker documents for r%02d" % ui.api("/projects/" + S["pid"])["project"]["head"])
    b = ui.item("makeInstructions")
    ui.scroll_to(b)
    ui.click(b)
    r = ui.wait_until(lambda: ui.js("Store.instructions"), 300, "the instructions")
    ui.eq([s["text"] for s in r["steps"]], ["Stand the base on the table.", "Press the lid onto the base."], "steps from the declaration")
    ui.eq(len(r["pages"]), 3, "a parts page and two steps")
    ui.click_text("Save PDF…")
    out = ui.saved(r["pdf"])
    ui.check(out.read_bytes()[:4] == b"%PDF", "a PDF was saved")
    toasts_gone(ui)
    ui.scroll_to(ui.item("instructions"), 0.0)
    ui.settle(1200)
    ui.shot("maker-instructions")
