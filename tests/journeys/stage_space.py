"""The stage is the hero: how much of the free stage the part fills, in Design and in Check with a result on it.

The part's box is projected to the screen through the view's own camera and compared with the free stage (the
rectangle the camera frames into: right of the dock, under the ribbon, left of the pane, above the bottom stack).
At 1440 x 900 with the pane open the part fills at least 60 % of the free height or 55 % of its width, whichever
binds; at 1100 at least 50 %. The free stage itself must keep most of the window: the bottom stack (legend, bar)
and the head (top row, ribbon) are measured too. FORM_CRAFT_OUT: pictures of each case, dark or light."""
import json
import os

from _lib import make, toasts_gone, wait_job

DATA = "fresh"
TALK = [{"t": "user", "text": "make it a little taller", "local": True},
        {"t": "text", "text": "Done as revision 2.", "local": True}]

BOX = """(function(){var v=Store.viewer,b=v.bounds,xs=[],ys=[];
for(var i=0;i<8;i++){var q=v._px(Qt.vector3d(i&1?b.hi.x:b.lo.x,i&2?b.hi.y:b.lo.y,i&4?b.hi.z:b.lo.z));if(q){xs.push(q.x);ys.push(q.y)}}
var f={l:v.insetLeft,t:v.insetTop,r:v.width-v.insetRight,b:v.height-v.insetBottom};
var bw=Math.max.apply(null,xs)-Math.min.apply(null,xs),bh=Math.max.apply(null,ys)-Math.min.apply(null,ys);
return {free:[Math.round(f.l),Math.round(f.t),Math.round(f.r),Math.round(f.b)],fw:Math.round(f.r-f.l),fh:Math.round(f.b-f.t),
box:[Math.round(bw),Math.round(bh)],kw:bw/Math.max(1,f.r-f.l),kh:bh/Math.max(1,f.b-f.t),win:[v.width,v.height]}})()"""


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


def measure(ui, what, need=None):
    ui.settle(1500)
    m = ui.js(BOX)
    fill = max(m["kw"], m["kh"])
    print("SPACE %s %dx%d: free %dx%d, part %dx%d, fills %.0f%% of the width, %.0f%% of the height (binding %.0f%%)"
          % (what, m["win"][0], m["win"][1], m["fw"], m["fh"], m["box"][0], m["box"][1], 100 * m["kw"], 100 * m["kh"], 100 * fill), flush=True)
    if need is not None and os.environ.get("FORM_SPACE_REPORT") != "1":
        ui.check(fill >= need, f"{what}: the part fills {fill:.0%} of the free stage; at least {need:.0%}")
        # and the free stage keeps most of the window's height: the head and the bottom stack stay slim
        tall = m["fh"] / m["win"][1]
        ui.check(tall >= need, f"{what}: the free stage is {tall:.0%} of the window's height; at least {need:.0%}")
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
        need = 0.55 if w >= 1440 else 0.5 if w <= 1100 else None
        for col in (False, True):
            ui.run_js("Store.talkOpen = true; Store.chatItems = %s; Store.talkCalm = %s; Store.setStage('shape')"
                      % ("[]" if not col else json.dumps(TALK), "false" if col else "true"))
            measure(ui, "design" + (" col" if col else ""), need)
            shot(ui, "space-design")
            ui.run_js("Store.setStage('prove'); Store.setAnalysis('thickness')")
            ui.wait_until(lambda: ui.js("!!Store.analysis"), 60, "the thickness map")
            measure(ui, "check-map" + (" col" if col else ""), need)
            shot(ui, "space-check-map")
            ui.run_js("Store.setAnalysis('')")
            if ok:
                ui.run_js("Store.benchPick('check', Store.benchEntry('dfm_cnc'))")
                ui.wait_until(lambda: ui.js("Results.on") is True, 30, "the check drawn on the part")
                measure(ui, "check-result" + (" col" if col else ""), need)
                shot(ui, "space-check-result")
                ui.run_js("var m = Object.assign({}, Store.benchSel); m.check = ''; Store.benchSel = m")
    ui.resize(1440, 900)
