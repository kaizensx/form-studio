"""The Bench: every study, route and document of a design in the Review and Make panes, each with the state the
engine gives it. A study that never ran says so and runs on click; once current it opens what it made; the next
revision makes it stale and the line names the revision it describes; the palette finds every entry.

FORM_BENCH_CROPS=<dir> also saves the Program pane at 200 % (bench-review-*.png, bench-make-*.png)."""
import os
from pathlib import Path

from _lib import make, printing_on, toasts_gone, wait_job

DATA = "fresh"
S = {}


def bench(ui):
    return ui.api("/projects/%s/bench" % S["pid"])


def entry(ui, sid):
    return next(e for e in bench(ui)["entries"] if e["id"] == sid)


def role(ui, sid):
    """What a line says on its right: its state, lettered."""
    r = ui.find_all(name="benchState", within=ui.item("bench-" + sid), shown=False)
    return str(r[0].property("text")).lower() if r else ""


def crop(ui, name):
    """The Program pane at 200 %, beside the screenshot (for looking at it closely)."""
    out = os.environ.get("FORM_BENCH_CROPS")
    shot = ui.shot(name)
    if not out:
        return
    from PIL import Image
    from PySide6.QtCore import QPointF
    pane = ui.item("programPane")
    p = pane.mapToItem(ui.win.contentItem(), QPointF(0, 0))
    img = Image.open(shot)
    k = img.width / ui.win.width()                 # device pixels per point
    box = [int(p.x() * k), int(p.y() * k), int((p.x() + pane.width()) * k), int((p.y() + pane.height()) * k)]
    c = img.crop(box)
    c = c.resize((int(pane.width() * 2), int(pane.height() * 2)), Image.LANCZOS)
    tag = "%s-%dx%d" % (os.environ.get("FORM_APPEARANCE", "dark"), ui.win.width(), ui.win.height())
    Path(out).mkdir(parents=True, exist_ok=True)
    c.save(str(Path(out) / f"{name}-{tag}.png"))


def journey_setup(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    printing_on(ui)
    S["pid"] = make(ui, "storage_box", "Bench box", purpose="print")
    wait_job(ui, S["pid"])
    ui.idle(120)


def journey_review(ui):
    ui.key("Ctrl+2")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "Check")
    ui.wait_until(lambda: ui.find(name="bench-checks"), 10, "the Bench in the Review pane")
    rows = [e for e in bench(ui)["entries"] if e["chapter"] == "check" and e["state"] != "n/a"]
    ui.check(len(rows) >= 8, f"the studies of a printed box are listed ({len(rows)})")
    for e in rows:                                     # every study the engine lists is a line, with the engine's state
        line = ui.find(name="bench-" + e["id"])
        ui.check(line is not None, f"a line for {e['id']}")
        lab = (ui.find_all(name="benchState", within=line, shown=False) or [None])[0]
        said = str(lab.property("text")).lower() if lab is not None else None
        if e["state"] == "current":                    # a current row shows its number and how it is known, not a word
            ui.check(said == "" if e["headline"] else "current" in said, f"{e['id']} is current and shows its headline: {said!r}")
            ui.check(str(line.property("state")) in ("ok", "warn"), f"{e['id']} has a filled mark: {line.property('state')}")
        else:
            want = {"stale": "describes", "never": "not run", "failed": "failed", "running": "running"}.get(e["state"])
            ui.check(said is not None and (want in said if want else said != ""), f"{e['id']} reads {want or 'what it needs'}: {said!r}")
            ui.eq(bool(line.property("dim")), e["state"] == "unavailable", f"{e['id']} is dimmed only when it cannot run")
    c = entry(ui, "checks")
    ui.eq(c["state"], "current", "the checks are current after the pipeline")
    ui.eq(c["rev"], 1, "and describe r01")
    ui.eq(entry(ui, "map.thickness")["state"], "never", "the wall-thickness map has never run")
    ui.settle(300)
    crop(ui, "bench-review-before-run")
    # a row that never ran opens under the list when clicked: what you get, the exact request, and Run
    ui.scroll_to(ui.item("bench-map.thickness"), 0.5)
    ui.click("bench-map.thickness", 0.3, 0.5)
    card = ui.wait_until(lambda: ui.find(name="benchCard"), 5, "the row, opened under the list")
    ui.check(ui.sees("not run", within=card), "the opened row says it has not run")
    ui.check("map.thickness" in str(ui.find(name="cardRequest", within=card).property("text")), "and shows the request Run makes")
    ui.check(ui.find(name="bench-checks") is not None, "the list above stays as the way out")
    ui.scroll_to(ui.item("cardRun"), 0.5)
    ui.click("cardRun")
    ui.wait_until(lambda: entry(ui, "map.thickness")["state"] == "current", 120, "the thickness study to finish")
    ui.wait_until(lambda: role(ui, "map.thickness") == "", 10, "its row to show the number in place of the words")
    h = entry(ui, "map.thickness")["headline"]
    ui.check("mm" in h, f"a headline with a number: {h}")
    ui.expect(h[:8], within=ui.item("bench-map.thickness"))
    ui.check(ui.sees("current for r01", within=ui.item("benchCard")), "the opened row says which revision it is current for")
    # once current, a click puts what it made on the part
    ui.scroll_to(ui.item("bench-map.thickness"), 0.5)
    ui.click("bench-map.thickness", 0.3, 0.5)
    ui.wait_until(lambda: ui.store.get("analysisMap") == "thickness", 5, "the thickness map on the part")
    ui.wait_until(lambda: not ui.store.get("analysisBusy"), 60, "the map")
    ui.settle(400)
    crop(ui, "bench-review")
    ui.run_js("Store.setAnalysis('')")


def journey_sheet(ui):
    """Ctrl+B opens the Bench: all four chapters at once, filters, find, and the selected row's request at the foot."""
    ui.key("Ctrl+B")
    ui.wait_until(lambda: ui.js("Store.benchOpen") is True, 3, "the Bench sheet")
    sheet = ui.item("benchSheet")
    ui.settle(500)
    for ch in ("design", "check", "make", "document"):
        ui.check(ui.find(name="benchCol-" + ch, within=sheet) is not None, f"the {ch} chapter is a column")
    ui.check(ui.find(name="sheet-map.thickness", within=sheet) is not None and ui.find(name="sheet-exports", within=sheet) is not None
             and ui.find(name="sheet-doc.bom", within=sheet) is not None, "studies, routes and documents are on the one sheet")
    ui.click("sheet-lighter", 0.3, 0.5)
    foot = ui.wait_until(lambda: ui.find(name="benchFoot", within=sheet), 3, "the selected row, opened at the foot")
    ui.check("lighter" in str(ui.find(name="benchFootRequest", within=foot).property("text")), "with the exact request")
    ui.shot("bench-sheet")
    ui.run_js("Store.benchSheetSel = ''")
    ui.key("/")
    ui.type("thick")
    ui.settle(300)
    ui.check(ui.find(name="sheet-map.thickness", within=sheet) is not None and ui.find(name="sheet-exports", within=sheet) is None, "find narrows every column")
    ui.key("Escape")
    ui.settle(200)
    ui.check(ui.find(name="sheet-exports", within=sheet) is not None, "Esc clears the find first")
    ui.key("Escape")
    ui.wait_until(lambda: ui.js("Store.benchOpen") is False, 3, "Esc to close the Bench")
    ui.click("benchButton")
    ui.wait_until(lambda: ui.js("Store.benchOpen") is True, 3, "the button in the top right to open it")
    ui.settle(300)
    ui.key("Ctrl+B")
    ui.wait_until(lambda: ui.js("Store.benchOpen") is False, 3, "Ctrl+B to close it")
    ui.settle(300)


def journey_palette(ui):
    ui.key("Ctrl+K")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is True, 3, "the palette")
    ui.type("thickness")
    ui.settle(200)
    ui.check(ui.sees("Wall thickness"), "the palette finds a Bench entry")
    # the closest match is the one lit: a mode by its name or by what it was called, then entries that start with it
    def lit(words):
        ui.key("Ctrl+A"); ui.type(words); ui.settle(200)
        return str(ui.item("palette").property("selText"))
    ui.eq(lit("check"), "Check", "'check' lights the Check mode, not an entry that only contains it")
    ui.eq(lit("review"), "Check", "'review' still finds the mode that was called Review")
    ui.eq(lit("checks"), "Checks", "'checks' lights the Checks study")
    ui.check("thickness" in lit("wall th").lower(), "a word start inside a name is found")
    ui.eq(lit("bench"), "Bench", "'bench' lights the Bench sheet")
    ui.key("Escape")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is False, 3, "the palette to close")
    n = ui.js("Store.bench.entries.filter(function (e) { return e.state !== 'n/a' }).length")
    ui.check(n >= 20, f"the palette has every entry that applies to offer ({n})")


def journey_stale(ui):
    # the next revision: what was computed for r01 is stale and says so; nothing shows current for r02 by mistake
    ui.api("/projects/%s/commit" % S["pid"], {"values": {"inner_w": 90}, "note": "wider"})
    ui.wait_until(lambda: bench(ui)["head"] == 2, 10, "the new head")
    t = entry(ui, "map.thickness")
    ui.eq(t["state"], "stale", "the thickness study is stale")
    ui.eq(t["rev"], 1, "and describes r01")
    ui.wait_until(lambda: "describes r01" in str(role(ui, "map.thickness")).lower(),
                  15, "the row to name the revision it describes")
    for e in bench(ui)["entries"]:
        if e["state"] == "current" and not e.get("live"):
            ui.check(e["rev"] == 2 or e.get("note"), f"{e['id']} is current for r{e['rev']}, not the head")
    wait_job(ui, S["pid"])
    ui.idle(120)
    toasts_gone(ui)


def journey_make(ui):
    ui.key("Ctrl+3")
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "Make")
    ui.wait_until(lambda: ui.find(name="bench-exports"), 10, "the Bench in the Make pane")
    ui.eq(entry(ui, "exports")["state"], "current", "the exports are current")
    ui.check(ui.find(name="bench-release") is not None, "the release is a route")
    ui.key("Ctrl+4")                                   # the documents are the Document mode's chapter
    ui.wait_until(lambda: ui.store.get("stage") == "document", 3, "Document")
    ui.wait_until(lambda: ui.find(name="bench-doc.bom"), 10, "the documents in the Document pane")
    ui.eq(entry(ui, "doc.bom")["state"], "never", "the parts list was never written for this revision")
    ui.settle(300)
    crop(ui, "bench-make-before-run")
    line = ui.item("bench-doc.bom")
    ui.scroll_to(line, 0.5)
    ui.hover(line, 0.5, 0.5)
    go = ui.wait_until(lambda: ui.find(name="benchRun", within=line), 3, "the run mark under the pointer")
    ui.click(go)
    ui.wait_until(lambda: entry(ui, "doc.bom")["state"] == "current", 60, "the parts list")
    ui.check(entry(ui, "doc.bom")["files"], "the parts list names its file")
    rel = entry(ui, "release")
    ui.eq(rel["by"], "person", "only a person releases")
    ui.hover("viewport", 0.5, 0.3)
    ui.settle(400)
    crop(ui, "bench-make")
