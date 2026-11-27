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
    ui.key("Ctrl+4")
    ui.wait_until(lambda: ui.store.get("stage") == "prove", 3, "Review")
    ui.wait_until(lambda: ui.find(name="bench-checks"), 10, "the Bench in the Review pane")
    rows = [e for e in bench(ui)["entries"] if e["group"] == "study" and e["state"] != "n/a"]
    ui.check(len(rows) >= 8, f"the studies of a printed box are listed ({len(rows)})")
    for e in rows:                                     # every study the engine lists is a line, with the engine's state
        line = ui.find(name="bench-" + e["id"])
        ui.check(line is not None, f"a line for {e['id']}")
        lab = (ui.find_all(name="benchState", within=line, shown=False) or [None])[0]
        want = {"current": "current", "stale": "stale", "never": "never run", "unavailable": "needs", "failed": "failed",
                "running": "running"}[e["state"]]
        ui.check(lab is not None and want in str(lab.property("text")).lower(), f"{e['id']} reads {want}: {lab.property('text') if lab else None}")
    c = entry(ui, "checks")
    ui.eq(c["state"], "current", "the checks are current after the pipeline")
    ui.eq(c["rev"], 1, "and describe r01")
    ui.eq(entry(ui, "map.thickness")["state"], "never", "the wall-thickness map has never run")
    ui.settle(300)
    crop(ui, "bench-review-before-run")
    # a line that never ran runs on click, on the activity bar, and lands current
    ui.scroll_to(ui.item("bench-map.thickness"), 0.5)
    ui.click("bench-map.thickness", 0.3, 0.5)
    ui.wait_until(lambda: entry(ui, "map.thickness")["state"] == "current", 120, "the thickness study to finish")
    ui.wait_until(lambda: "current" in str(role(ui, "map.thickness")).lower(),
                  10, "its line to say current")
    h = entry(ui, "map.thickness")["headline"]
    ui.check("mm" in h, f"a headline with a number: {h}")
    ui.expect(h[:12], within=ui.item("bench-map.thickness"))
    # once current, it opens what it made: the map on the part, and the line is lit (cyan: where you are)
    ui.click("bench-map.thickness", 0.3, 0.5)
    ui.wait_until(lambda: ui.store.get("analysisMap") == "thickness", 5, "the thickness map on the part")
    ui.wait_until(lambda: not ui.store.get("analysisBusy"), 60, "the map")
    ui.settle(400)
    crop(ui, "bench-review")
    ui.run_js("Store.setAnalysis('')")


def journey_palette(ui):
    ui.key("Ctrl+K")
    ui.wait_until(lambda: ui.store.get("paletteOpen") is True, 3, "the palette")
    ui.type("thickness")
    ui.settle(200)
    ui.check(ui.sees("Wall thickness"), "the palette finds a Bench entry")
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
    ui.wait_until(lambda: "r01" in str(role(ui, "map.thickness")).lower(),
                  15, "the line to name the revision it describes")
    for e in bench(ui)["entries"]:
        if e["state"] == "current" and not e.get("live"):
            ui.check(e["rev"] == 2 or e.get("note"), f"{e['id']} is current for r{e['rev']}, not the head")
    wait_job(ui, S["pid"])
    ui.idle(120)
    toasts_gone(ui)


def journey_make(ui):
    ui.key("Ctrl+5")
    ui.wait_until(lambda: ui.store.get("stage") == "release", 3, "Make")
    ui.wait_until(lambda: ui.find(name="bench-exports"), 10, "the Bench in the Make pane")
    ui.eq(entry(ui, "exports")["state"], "current", "the exports are current")
    ui.check(ui.find(name="bench-doc.bom") is not None and ui.find(name="bench-release") is not None, "documents and the release are listed")
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
