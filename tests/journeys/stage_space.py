"""The stage is the hero: how much of the free stage the part fills, in Design and in Check with a result on it.

The part's box is projected to the screen through the view's own camera and compared with the free stage (the
rectangle the camera frames into: under the ribbon, left of the pane, above the bottom stack; with the ribbon showing
there is no tool dock, so it starts right of the conversation's column or of the folded project rail). At 1440, 1280
and 1100, the column open and folded, the part's box fills at least 70 % of the free stage's binding side (height or
width, whichever binds) and at most 82 %; it stands a little above the free stage's middle, never below it. The free
stage keeps most of the window's height (the head and the bottom stack stay slim), nothing is left of the dock, and an
idle tool leaves no options capsule on the stage. FORM_CRAFT_OUT: pictures of each case, dark or light.
FORM_SPACE_REPORT=1 prints the numbers and checks nothing (the before pictures of a pass)."""
import json
import os

from _lib import make, toasts_gone, wait_job

DATA = "fresh"
TALK = [{"t": "user", "text": "make it a little taller", "local": True},
        {"t": "text", "text": "Done as revision 2.", "local": True}]

BOX = """(function(){var v=Store.viewer,b=v.bounds,xs=[],ys=[];
for(var i=0;i<8;i++){var q=v._px(Qt.vector3d(i&1?b.hi.x:b.lo.x,i&2?b.hi.y:b.lo.y,i&4?b.hi.z:b.lo.z));if(q){xs.push(q.x);ys.push(q.y)}}
var f={l:v.insetLeft,t:v.insetTop,r:v.width-v.insetRight,b:v.height-v.insetBottom};
var x0=Math.min.apply(null,xs),x1=Math.max.apply(null,xs),y0=Math.min.apply(null,ys),y1=Math.max.apply(null,ys);
var bw=x1-x0,bh=y1-y0;
return {free:[Math.round(f.l),Math.round(f.t),Math.round(f.r),Math.round(f.b)],fw:Math.round(f.r-f.l),fh:Math.round(f.b-f.t),
box:[Math.round(bw),Math.round(bh)],kw:bw/Math.max(1,f.r-f.l),kh:bh/Math.max(1,f.b-f.t),win:[v.width,v.height],
up:((f.t+f.b)/2-(y0+y1)/2)/Math.max(1,f.b-f.t)}})()"""


def shot(ui, name):
    out = os.environ.get("FORM_CRAFT_OUT")
    if not out:
        return
    from pathlib import Path
    from PySide6.QtCore import Qt
    ui.hover("viewport", 0.5, 0.62)
    ui.settle(250)
    ui._pump(80)
    img = ui.win.grabWindow()
    dpr = img.devicePixelRatio() or 1.0
    img = img.scaled(int(img.width() * 2 / dpr), int(img.height() * 2 / dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    Path(out).mkdir(parents=True, exist_ok=True)
    col = "col" if ui.js("Store.talkCol > 0") else "folded"
    img.save(str(Path(out) / f"{name}-{ui.win.width()}-{col}-{os.environ.get('FORM_APPEARANCE', 'dark')}.png"))


def measure(ui, what, tall=None, idle=False):
    ui.settle(1500)
    m = ui.js(BOX)
    fill = max(m["kw"], m["kh"])
    print("SPACE %s %dx%d: free %dx%d at %s, part %dx%d, fills %.0f%% of the width, %.0f%% of the height (binding %.0f%%), "
          "centre %.1f%% of the free height above the middle"
          % (what, m["win"][0], m["win"][1], m["fw"], m["fh"], m["free"], m["box"][0], m["box"][1], 100 * m["kw"], 100 * m["kh"],
             100 * fill, 100 * m["up"]), flush=True)
    if os.environ.get("FORM_SPACE_REPORT") == "1":
        return m
    ui.check(0.70 <= fill <= 0.82, f"{what}: the part fills {fill:.0%} of the free stage's binding side; 70 to 82 %")
    ui.check(0.0 <= m["up"] <= 0.06, f"{what}: the part stands {m['up']:.1%} of the free height above its middle; 0 to 6 %")
    # the free stage keeps most of the window's height: the head and the bottom stack stay slim
    if tall is not None:
        h = m["fh"] / m["win"][1]
        ui.check(h >= tall, f"{what}: the free stage is {h:.0%} of the window's height; at least {tall:.0%}")
    # the ribbon holds the four tools: no dock on the stage
    ui.check(not ui.exists("toolDock"), f"{what}: no tool dock while the ribbon shows")
    if idle:
        ui.check(not ui.exists("toolCapsule"), f"{what}: no options capsule while no tool has anything to say")
    return m


def run(ui):
    ui.wait_until(lambda: ui.store.get("screen") == "home", 30, "Home")
    pid = make(ui, "storage_box", "Parts box", purpose="model")
    ui.wait_until(lambda: ui.js("!!Store.viewer && !Store.viewer.revealing && Store.buildOf === 0") is True, 60, "the build-up to end")
    toasts_gone(ui)
    # a result of the later engines on the part: the CNC manufacturability check (computed in the kernel)
    r = ui.api("/projects/" + pid + "/study", {"id": "dfm_cnc"})
    ok = isinstance(r, dict) and not r.get("error")
    if ok:
        wait_job(ui, pid)
        ui.wait_until(lambda: (ui.js("Store.loadBench(), (Store.benchEntry('dfm_cnc') || {}).state") == "current"), 120, "the CNC check")
    for w, h in ((1440, 900), (1280, 800), (1100, 700)):
        ui.resize(w, h)
        tall = 0.6 if w >= 1440 else 0.55 if w >= 1280 else 0.5
        for col in (False, True):
            ui.run_js("Store.talkOpen = true; Store.chatItems = %s; Store.talkCalm = %s; Store.setStage('shape')"
                      % ("[]" if not col else json.dumps(TALK), "false" if col else "true"))
            measure(ui, "design" + (" col" if col else ""), tall, idle=True)
            shot(ui, "space-design")
            ui.run_js("Store.setStage('prove'); Store.setAnalysis('thickness')")
            ui.wait_until(lambda: ui.js("!!Store.analysis"), 60, "the thickness map")
            measure(ui, "check-map" + (" col" if col else ""), tall * 0.85)
            shot(ui, "space-check-map")
            ui.run_js("Store.setAnalysis('')")
            if ok:
                ui.run_js("Store.benchPick('check', Store.benchEntry('dfm_cnc'))")
                ui.wait_until(lambda: ui.js("Results.on") is True, 30, "the check drawn on the part")
                measure(ui, "check-result" + (" col" if col else ""), tall * 0.85, idle=True)
                # (under 1200 px with the column open the pane folds to its button: there is no card to look at)
                if os.environ.get("FORM_SPACE_REPORT") != "1" and ui.exists("programPane"):
                    # the opened card in the pane: its buttons in view, not cut by the pane's foot
                    ui.settle(1700)
                    # (or, a card taller than the pane, a copy of them at the pane's foot)
                    run_btn = None if ui.exists("cardRunStuck") else ui.find("cardRun")
                    ui.check(run_btn is not None or ui.exists("cardRunStuck"), "the card's Run again is on screen")
                    if run_btn is not None:
                        pane = ui.item("inspector")
                        b = run_btn.mapToItem(pane, 0, 0)
                        ui.check(b.y() >= 0 and b.y() + run_btn.height() <= pane.height() + 0.5,
                                 f"the card's Run again stands inside the pane: {b.y():.0f} + {run_btn.height():.0f} / {pane.height():.0f}")
                    ui.check(ui.js("Frame.find('result:dfm_cnc') ? Frame.find('result:dfm_cnc').title : ''") == "CNC check",
                             "the tab's name is short: CNC check")
                shot(ui, "space-check-result")
                ui.run_js("var m = Object.assign({}, Store.benchSel); m.check = ''; Store.benchSel = m")
    ui.resize(1440, 900)
