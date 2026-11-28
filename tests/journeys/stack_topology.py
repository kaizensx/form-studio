"""The tolerance stack-up's loop and the topology run on the part (docs/TOLERANCES.md `draw`, docs/OPTIMISATION.md
frames), each from a real run of its engine in this journey's data folder.

Stack-up: the box, the lid and the screw of tests/stack_designs.py; the gap from the screw's tip to the floor of its
pilot hole, kept as a stack. Selecting its row in Check draws the loop: a line per link along the gap's direction, the
gap lit, a tick on each face of the loop, each link's length at its middle (the engine's numbers), and the strip
says worst case, RSS and Cpk.

Topology: needs the FEA engine (a static study to optimise against). Without it the journey checks the honest state:
the row says what it needs and nothing is drawn. With it, the run plays from the even start to the last iteration
once (the "result develops" moment), and the timeline scrubs through the iterations the engine stored.

The Bench row says the short number (`row`), the card the sentence.
"""
import os
import sys
from pathlib import Path

import _results as R
from _lib import open_project, mode_key

DATA = "fresh"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stack_designs import BOX_LID_SCREW  # noqa: E402

TIP, FLOOR = {"at": [100, 0, 0], "part": "screw"}, {"at": [0, 0, 8]}
HAND = {"screw_l": 0.2, "lid_t": 0.1, "hole_depth": 0.15}


def res(ui, expr="Results.kind"):
    return ui.js(expr)


def crop(ui, name):
    out = os.environ.get("FORM_RESULT_CROPS")
    shot = ui.shot(name)
    if not out:
        return
    from PIL import Image
    img = Image.open(shot)
    k = img.width / ui.win.width()
    tag = "%s-%d-%s" % (os.environ.get("FORM_APPEARANCE", "dark"), ui.win.width(), "col" if ui.js("Store.talkCol > 0") else "folded")
    Path(out).mkdir(parents=True, exist_ok=True)
    for nm in ("viewport", "legendStrip", "benchCard"):
        it = ui.find(name=nm)
        if it is None or it.width() < 4:
            continue
        p = it.mapToScene(it.boundingRect().topLeft())
        box = tuple(int(v * k) for v in (p.x(), p.y(), p.x() + it.width(), p.y() + it.height()))
        c = img.crop(box)
        f = 2 / k
        c.resize((int(c.width * f), int(c.height * f)), Image.LANCZOS).save(str(Path(out) / f"{name}-{nm}-{tag}.png"))


def journey_stack(ui):
    from form.stack import tools
    st = ui.studio
    pid = st.create_design("Box lid screw", BOX_LID_SCREW, purpose="model")["id"]
    r = tools.call(st, pid, a=TIP, b=FLOOR, save=True, name="Tip to floor", tolerances=HAND, samples=20000)
    open_project(ui, pid)
    ui.key(mode_key(2))
    ui.wait_until(lambda: ui.find(name="bench-stack"), 15, "the stack-up row")
    row = ui.item("bench-stack")
    val = ui.find(name="benchValue", within=row)
    ui.check(val is not None and val.property("text") == "gap 3.000 mm", f"the row says the short number: {val.property('text') if val else None}")
    ui.scroll_to(row, 0.4)
    ui.click("bench-stack", 0.3, 0.5)
    ui.wait_until(lambda: res(ui, "Results.id") == "stack" and res(ui, "!!Results.r && !Results.busy"), 20, "the stack's result")
    ui.wait_until(lambda: res(ui) == "stack", 10, "the loop drawn")
    ui.settle(600)
    d = res(ui, "Results.r")
    ui.eq(round(d["gap"]["nominal"], 6), round(r["gap"]["nominal"], 6), "the gap is the engine's")
    ui.eq(len(d["draw"]["segments"]), len(r["draw"]["segments"]), "every segment of the engine's loop")
    gl = ui.find(name="stackGapLabel")
    ui.check(gl is not None and gl.isVisible() and "3.00 mm" in " ".join(ui.texts(gl)), "the gap's length stands at its middle")
    ui.check("RSS" in " ".join(ui.texts(ui.item("legendStrip"))), "the strip says RSS")
    ui.check(ui.sees("Worst case", within=ui.item("benchCard")), "the card has the numbers")
    crop(ui, "stack")
    # labels never sit on one another
    labs = [x for x in ui.find_all(name="stackLinkLabel") if x.isVisible()] + ([gl] if gl else [])
    rects = []
    for x in labs:
        p = x.mapToScene(x.boundingRect().topLeft())
        rects.append((p.x(), p.y(), x.width(), x.height()))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            ui.check(not (a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]), "two loop labels overlap")


def journey_topology(ui):
    st = ui.studio
    pid = R.design(st, "Bracket", R.BRACKET)
    if not R.fea_ready(st):
        open_project(ui, pid)
        ui.key(mode_key(1))
        ui.settle(300)
        ui.run_js("Store.benchSheetSel = 'topology'")
        e = ui.api("/projects/" + pid + "/result?id=topology")
        ui.check(e.get("state") != "current" and e.get("kind") == "topology", f"no FEA engine: the topology says it is not run ({e.get('state')})")
        print("TOPOLOGY: the FEA engine is not installed; the playback was not exercised", flush=True)
        return
    from form.topo import study as T
    R.strength(st, pid, R.STATIC)
    T.run(st, pid, {"volfrac": 0.55, "max_iter": 24})
    open_project(ui, pid)
    ui.key(mode_key(1))
    ui.wait_until(lambda: ui.find(name="bench-topology"), 15, "the topology row")
    ui.click("bench-topology", 0.3, 0.5)
    ui.wait_until(lambda: res(ui) == "topology", 20, "the density drawn")
    n0 = res(ui, "Results.developed")
    ui.wait_until(lambda: not res(ui, "Results.developing") and res(ui, "Results.settle") == 1, 5, "the run to play")
    ui.check(res(ui, "Results.developed") >= n0, "the run played once")
    ui.eq(res(ui, "Results.iteration"), res(ui, "Results.duration"), "it rests on the last iteration")
    ui.click("scrubArea", 0.0, 0.5)
    ui.eq(res(ui, "Results.iteration"), 0, "the timeline scrubs to the even start")
    crop(ui, "topology")


def run(ui):
    journey_stack(ui)
    journey_topology(ui)
